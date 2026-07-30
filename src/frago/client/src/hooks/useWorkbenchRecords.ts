/**
 * useWorkbenchRecords — 会话工作台中栏的数据源，尾部优先的游标分页。
 *
 * 拉 `GET /api/workbench/sessions/{sid}/records`，三种取法各管一件事：
 *
 * 1. **打开会话取尾部。** `tail=true&limit=200` 取整场最后两百条——中栏要直接落在最新
 *    内容上，从头一页页翻到尾会把大会话整个塞进浏览器。
 * 2. **往上翻取更早。** `after=<窗口首条 seq 减一页>` 取当前窗口之前的一页，往顶部前插。
 * 3. **新内容取增量。** `after=<末条 seq 加一>` 只取比手头更新的，往尾部追加。轮询与
 *    发话后的重拉都走这条路和尾部重取。
 *
 * `after` 是**本批第一条的 seq、闭区间起点**，不是绝对下标：会话被重新解析后 seq 会变，
 * 界面拿着过期的游标只会错位，过期时从尾部重取。
 *
 * 轮询的开关在「这场会话还活不活」：左栏状态为 running，或者刚刚有过动静（发话后的重拉、
 * 上一次增量真的取到了新条目）——活的会话每五秒取一次增量，安静十五分钟后自己停。
 *
 * 分页是硬要求不是礼貌——单条工具结果见过 7.2 万字符，一次拉整场大会话会打死浏览器。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getWebSocketClient, MessageType, type WebSocketMessage } from '../api/websocket';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/** 一页拉多少条。服务端上限 500，这里取默认的 200。 */
export const PAGE_SIZE = 200;

/** 活会话多久取一次增量。 */
export const POLL_INTERVAL_MS = 5_000;

/** 最后一次动静过后，多久还当这场会话是活的。 */
export const HOT_WINDOW_MS = 15 * 60_000;

/** 十五种形态。身份由形态直接表达，统一记录不设发言人字段。 */
export type RecordKind =
  | 'user.say'
  | 'agent.say'
  | 'agent.think'
  | 'tool.call'
  | 'tool.result'
  | 'subagent.dispatch'
  | 'context.inject'
  | 'media.attach'
  | 'todo.snapshot'
  | 'permission.outcome'
  | 'error'
  | 'interrupt'
  | 'context.compact'
  | 'session.state'
  | 'call.envelope';

export const RECORD_KINDS: RecordKind[] = [
  'user.say',
  'agent.say',
  'agent.think',
  'tool.call',
  'tool.result',
  'subagent.dispatch',
  'context.inject',
  'media.attach',
  'todo.snapshot',
  'permission.outcome',
  'error',
  'interrupt',
  'context.compact',
  'session.state',
  'call.envelope',
];

/** 截断三态。不是布尔——两家都有「看着完整其实不完整」的情况。 */
export type TruncationState = 'none' | 'clipped' | 'offloaded';

/** 一条统一记录 = 中栏的一张卡片。字段与 `unified_record.UnifiedRecord` 逐字对齐。 */
export interface WorkbenchRecord {
  id: string;
  session_id: string;
  /** 同一次模型回复的分组键。用户输入类为 null。**这个值永不显示给人看。** */
  group_id: string | null;
  seq: number;
  /** 毫秒时间戳。只用于显示，不参与排序。 */
  ts: number;
  kind: RecordKind;
  agent_path: string[];
  payload: Record<string, unknown>;
  raw_available: boolean;
}

export interface WorkbenchRecordsState {
  records: WorkbenchRecord[];
  /** 初次装载或整流重取中。 */
  loading: boolean;
  /** 顶部前插旧页中。与 loading 分开——往上翻不该把整栏打回装载态。 */
  loadingOlder: boolean;
  /** 当前窗口之上还有没有更早的记录。 */
  hasOlder: boolean;
  error: string | null;
  /** 取当前窗口之前的一页，往顶部前插。 */
  loadOlder: () => Promise<void>;
  /** 重取尾部一页。发完话调它，让自己刚说的话立刻落进流里。 */
  reload: () => Promise<void>;
}

export async function fetchWorkbenchRecords(
  sessionId: string,
  opts: { after?: number; limit?: number; tail?: boolean } = {}
): Promise<WorkbenchRecord[]> {
  const { after = 0, limit = PAGE_SIZE, tail = false } = opts;
  const query = tail
    ? `tail=true&limit=${limit}`
    : `after=${after}&limit=${limit}`;
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/sessions/${encodeURIComponent(sessionId)}/records?${query}`
  );
  if (!res.ok) {
    throw new Error(`记录取不到（HTTP ${res.status}）`);
  }
  return (await res.json()) as WorkbenchRecord[];
}

/**
 * 取单条记录的原文。
 *
 * **报错类恒被服务端拒（403）**，界面这一层也不给挂入口——两道都要有。这个函数只被
 * 工具结果那条路调用。
 */
export async function fetchWorkbenchRaw(
  sessionId: string,
  recordId: string
): Promise<unknown> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/records/${encodeURIComponent(recordId)}/raw` +
      `?session_id=${encodeURIComponent(sessionId)}`
  );
  if (!res.ok) {
    throw new Error(`原文不予提供（HTTP ${res.status}）`);
  }
  return res.json();
}

export function useWorkbenchRecords(
  sessionId: string | null,
  opts: { live?: boolean } = {}
): WorkbenchRecordsState {
  const { live = false } = opts;
  const [records, setRecords] = useState<WorkbenchRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [hasOlder, setHasOlder] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 同一方向的两次加载不许叠在一起：滚动与轮询触发得都很密，不闸住会重复插入。
  const inflightNewer = useRef(false);
  const inflightOlder = useRef(false);
  // 换会话时把旧请求的返回丢掉，否则慢的那个后到，会把新会话的流覆盖掉。
  const activeSession = useRef<string | null>(sessionId);
  // 记录流的实时镜像，给轮询与前插读——在 setState 的回调里反读 state 是绕路，不如直接照镜子。
  const recordsRef = useRef<WorkbenchRecord[]>([]);
  // 还活不活：最后一次真的取到新条目、或刚刚重拉过的时刻。轮询据此自己熄火。
  const hotUntil = useRef(0);
  // live 是外部给的（左栏状态），hotUntil 是内部长出来的，取增量时两个都看。
  const liveRef = useRef(live);
  liveRef.current = live;

  const loadTail = useCallback(async (sid: string) => {
    if (inflightNewer.current) return;
    inflightNewer.current = true;
    setLoading(true);
    setError(null);
    try {
      const batch = await fetchWorkbenchRecords(sid, { tail: true, limit: PAGE_SIZE });
      if (activeSession.current !== sid) return;
      recordsRef.current = batch;
      setRecords(batch);
      setHasOlder(batch.length > 0 && batch[0].seq > 0);
    } catch (e) {
      if (activeSession.current !== sid) return;
      setError(e instanceof Error ? e.message : String(e));
      setHasOlder(false);
    } finally {
      inflightNewer.current = false;
      if (activeSession.current === sid) setLoading(false);
    }
  }, []);

  /** 取比手头末条更新的记录，往尾部追加。返回新取到几条——轮询靠它续命。 */
  const appendNewer = useCallback(async (sid: string): Promise<number> => {
    if (inflightNewer.current) return 0;
    const last = recordsRef.current[recordsRef.current.length - 1];
    if (!last) return 0;
    inflightNewer.current = true;
    try {
      const batch = await fetchWorkbenchRecords(sid, { after: last.seq + 1, limit: PAGE_SIZE });
      if (activeSession.current !== sid || !batch.length) return 0;
      setRecords((prev) => {
        const floor = prev.length ? prev[prev.length - 1].seq : -1;
        const fresh = batch.filter((r) => r.seq > floor);
        const next = fresh.length ? [...prev, ...fresh] : prev;
        recordsRef.current = next;
        return next;
      });
      hotUntil.current = Date.now() + HOT_WINDOW_MS;
      return batch.length;
    } catch {
      // 增量取不到不打断看记录的人——下一次轮询再试。错误只在整流重取时才摆出来。
      return 0;
    } finally {
      inflightNewer.current = false;
    }
  }, []);

  const reload = useCallback(async () => {
    if (!sessionId) return;
    // 重拉大多跟在发话后面——这一刻起会话是活的，轮询该醒了。
    hotUntil.current = Date.now() + HOT_WINDOW_MS;
    await loadTail(sessionId);
  }, [sessionId, loadTail]);

  useEffect(() => {
    activeSession.current = sessionId;
    recordsRef.current = [];
    setRecords([]);
    setHasOlder(false);
    setError(null);
    if (!sessionId) return;
    void loadTail(sessionId);
  }, [sessionId, loadTail]);

  const loadOlder = useCallback(async () => {
    if (!sessionId || !hasOlder || loadingOlder || inflightOlder.current) return;
    inflightOlder.current = true;
    setLoadingOlder(true);
    try {
      const first = recordsRef.current[0];
      if (!first || activeSession.current !== sessionId) return;
      const start = Math.max(0, first.seq - PAGE_SIZE);
      const count = first.seq - start;
      if (count <= 0) {
        setHasOlder(false);
        return;
      }
      const batch = await fetchWorkbenchRecords(sessionId, { after: start, limit: count });
      if (activeSession.current !== sessionId) return;
      setRecords((prev) => {
        const ceiling = prev.length ? prev[0].seq : Number.POSITIVE_INFINITY;
        const older = batch.filter((r) => r.seq < ceiling);
        const next = older.length ? [...older, ...prev] : prev;
        recordsRef.current = next;
        return next;
      });
      setHasOlder(start > 0);
    } catch (e) {
      if (activeSession.current !== sessionId) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      inflightOlder.current = false;
      if (activeSession.current === sessionId) setLoadingOlder(false);
    }
  }, [sessionId, hasOlder, loadingOlder]);

  // 轮询：会话活着（左栏判 running，或刚刚还有过动静）且页面看得见时，每五秒取一次增量。
  useEffect(() => {
    if (!sessionId) return;
    const timer = setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      if (!liveRef.current && hotUntil.current < Date.now()) return;
      void appendNewer(sessionId);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [sessionId, appendNewer]);

  // WebSocket：服务端有文件监听时直接推增量，比轮询快一整个量级。
  // 轮询留作兜底——WebSocket 断连时它还在跑。
  useEffect(() => {
    if (!sessionId) return;
    const sidRef = { current: sessionId };

    const onRecordsAppend = (msg: WebSocketMessage) => {
      const data = msg.data as Record<string, unknown> | undefined;
      if (!data || data.session_id !== sidRef.current) return;
      const batch = (data.records ?? []) as WorkbenchRecord[];
      if (!batch.length) return;
      setRecords((prev) => {
        const existing = new Set(prev.map((r) => r.id));
        const fresh = batch.filter((r) => !existing.has(r.id));
        if (!fresh.length) return prev;
        const next = [...prev, ...fresh];
        recordsRef.current = next;
        return next;
      });
      hotUntil.current = Date.now() + HOT_WINDOW_MS;
    };

    const onTurnDone = (msg: WebSocketMessage) => {
      const data = msg.data as Record<string, unknown> | undefined;
      if (!data || data.session_id !== sidRef.current) return;
      hotUntil.current = Date.now() + HOT_WINDOW_MS;
    };

    const client = getWebSocketClient();
    const unsub1 = client.on(MessageType.SESSION_RECORDS_APPEND, onRecordsAppend);
    const unsub2 = client.on(MessageType.SESSION_TURN_DONE, onTurnDone);

    return () => {
      unsub1();
      unsub2();
    };
  }, [sessionId]);

  return { records, loading, loadingOlder, hasOlder, error, loadOlder, reload };
}
