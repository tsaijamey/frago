/**
 * useWorkbenchRecords — 会话工作台中栏的数据源，尾部优先的游标分页。
 *
 * 拉 `GET /api/workbench/sessions/{sid}/records`，三种取法各管一件事：
 *
 * 1. **打开会话取尾部。** `tail=true&limit=200` 取整场最后两百条——中栏要直接落在最新
 *    内容上，从头一页页翻到尾会把大会话整个塞进浏览器。
 * 2. **往上翻取更早。** `after=<窗口首条 seq 减一页>` 取当前窗口之前的一页，往顶部前插。
 * 3. **新内容取增量。** `after=<末条自己的 seq>` 连手头末条一起要回来，多的那一条当对照，
 *    其余按身份并进尾部。轮询与发话后的重拉都走这条路和尾部重取。
 *
 * `after` 是**本批第一条的 seq、闭区间起点**，不是绝对下标：会话每次重新解析时 seq 都是
 * 现排的，编号会变。所以起点取末条自己那一格而不是它的下一格——对照那一条还在，说明编号
 * 没动；换了人，说明这场重排过，手上这份的位置全部作废，从尾部重取。**不这么做就会丢内容**：
 * 每一轮结束引擎都会重写这场会话的花费账本，账本只留最后一份，前面那份一被丢掉，它后面所有
 * 内容的编号就整体往前挪一格，人紧接着说的那句话正好落回已经问过的号段，从此取不回来。
 *
 * **新内容主要靠 WebSocket 推**（服务端盯着会话文件，一动就把增量推过来），轮询是断连时
 * 的兜底。轮询的开关在「这场会话还活不活」：左栏状态为 running，或者刚刚有过动静——活的
 * 会话平时五秒取一次增量，安静十五分钟后自己停。
 *
 * 节拍是**两档**的。刚按下发送那一分半钟走一秒一趟：发送那条接口要等整整一轮才返回（服务端
 * 把话投进 tmux 后一直轮询到这一轮说完，上限 180 秒），那段时间里页面手上没有任何别的
 * 消息来源。五秒一档在这一刻不够——人盯着屏幕等自己那句话落进流里，最坏要等满五秒才看到
 * 第一点动静，中间没有任何迹象说明话已经送出去了。
 *
 * 分页是硬要求不是礼貌——单条工具结果见过 7.2 万字符，一次拉整场大会话会打死浏览器。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getWebSocketClient, MessageType, type WebSocketMessage } from '../api/websocket';
import i18n from '@/i18n';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/** 一页拉多少条。服务端上限 500，这里取默认的 200。 */
export const PAGE_SIZE = 200;

/** 活会话多久取一次增量。 */
export const POLL_INTERVAL_MS = 5_000;

/**
 * 刚发完话那一阵多久取一次增量。
 *
 * 五秒的节拍在「一直开着看」时是够的，在「刚按下发送」那一刻不够：人盯着屏幕等自己那句
 * 话落进流里，最坏要等满五秒才看到第一点动静，中间没有任何迹象说明话已经送出去了。
 * WebSocket 通着的时候这条路根本用不上，它是断连时的兜底。
 */
export const FAST_POLL_INTERVAL_MS = 1_000;

/** 发完话之后，快节拍维持多久。跟服务端那次投喂的超时（180 秒）同一量级。 */
export const FAST_POLL_WINDOW_MS = 90_000;

/** 最后一次动静过后，多久还当这场会话是活的。 */
export const HOT_WINDOW_MS = 15 * 60_000;

/**
 * 发完话之后，最多等多久还认为"在等 agent 开口"。
 *
 * 到点还没等到就把提示撤掉——挂着一句永远不消失的"在等"，比不提示还糟：人分不出是
 * agent 在想，还是这条通道早就断了。
 */
export const AWAIT_REPLY_CEILING_MS = 180_000;

/**
 * 点了发送之后，那句话在成为新一轮之前会经过的两档。
 *
 * - `sent`（已发送）：请求出了门，会话记录里还找不到它。**这一档撤不回**——话已经交给
 *   服务端了，所以它不该继续待在输入框里装作还没发。
 * - `queued`（已入队列）：它已经进了这场会话，但 agent 那一轮还在跑，引擎把它挂在队列
 *   上，还没轮到它成为 prompt。
 *
 * 成为真正的一轮之后（用户发言落盘，或那张插话卡的下场从"还在队列里"变成"已并入"
 * 「已发出」）它就退出这个清单——那时它在记录流里有自己的位置，不需要信封替它站着。
 */
export type OutboundState = 'sent' | 'queued';

/** 一条已经点了发送、但还没成为新一轮的消息。信封区照着它画。 */
export interface OutboundMessage {
  id: string;
  /** 投出去的原文（已 trim）。纯附件时为空串。 */
  text: string;
  /** 随它一起发的图片加文档共几个。 */
  attachments: number;
  /** 点发送那一刻。用来跟记录的时刻比对，也用来判它是不是等太久了。 */
  at: number;
  state: OutboundState;
}

/** 这条记录是不是那条消息的落地形态，以及落成了哪一种。 */
type Landing = 'say' | 'queued' | 'drained';

/** 比对前把空白抹平：档案里那份带着换行与缩进，人打的那份没有。 */
function flatten(text: string): string {
  return text.replace(/\s+/g, ' ').trim();
}

/**
 * 斜杠命令落进档案时不是原样，认不出这层壳，那句话就永远等不到落地。
 *
 * 人在输入框里打的是 `/goal 把 webUI 的日历挪到底部`，写进会话档案的却是三段标签：
 * 命令名、命令说明、参数。两份字面上毫无关系，于是信封一直停在"已发送"那一档，直到
 * 等满上限才自己撤掉——人看见 agent 明明已经在干活了，输入区上方那句话却还挂着说没进去。
 *
 * 拆壳现在归数据层做：那三段标签在翻译时就已经拆开，命令落 `command`、参数落 `text`。
 * 这里把两半拼回人打的那一句。**档案里的原样包装仍要认**——它是给旧记录留的退路，那些
 * 早已翻译好并缓存下来的记录里，正文还是带标签的那一份。
 */
function unwrapCommandEcho(record: WorkbenchRecord, text: string): string | null {
  const command = typeof record.payload.command === 'string' ? record.payload.command : '';
  if (command) return flatten(`${command} ${text}`);
  const name = text.match(/<command-name>([\s\S]*?)<\/command-name>/);
  if (!name) return null;
  const args = text.match(/<command-args>([\s\S]*?)<\/command-args>/);
  return flatten(`${name[1]} ${args?.[1] ?? ''}`);
}

/**
 * 拿一条记录对一条待落地的消息。对不上返回 null。
 *
 * 纯附件（`text` 为空）那一路只能按时刻认：正文是服务端替它写的（"请查看以下附件。"
 * 加一串落盘路径），前端手上没有那份原文，比对无从下手。
 */
function landingOf(r: WorkbenchRecord, msg: OutboundMessage): Landing | null {
  if (r.ts < msg.at - 1_000) return null;
  const mine = flatten(msg.text);
  if (r.kind === 'user.say') {
    if (!mine) return 'say';
    const text = typeof r.payload.text === 'string' ? r.payload.text : '';
    // 附件的路径是服务端往后接的，所以比的是"开头是不是那一句"，不是整句相等。
    if (flatten(text).startsWith(mine)) return 'say';
    const unwrapped = unwrapCommandEcho(r, text);
    return unwrapped && unwrapped.startsWith(mine) ? 'say' : null;
  }
  if (r.kind === 'context.inject' && r.payload.channel === 'queued_command') {
    const body = typeof r.payload.body === 'string' ? r.payload.body : '';
    // 带附件的插话，卡上的原文同样被服务端接上了图片路径，所以也只比开头。
    if (mine && !flatten(body).startsWith(mine)) return null;
    // 插话卡自己带着下场：还在队列里的才算"已入队列"，已并入或已发出的那一轮已经开始，
    // 信封该退场了。
    return r.payload.queue_state === 'pending' ? 'queued' : 'drained';
  }
  return null;
}

/** 这条消息在当前这批记录里落到哪一档。终局（成为一轮）优先于"还在队列里"。 */
function landingIn(records: WorkbenchRecord[], msg: OutboundMessage): Landing | null {
  let seen: Landing | null = null;
  for (const r of records) {
    const landing = landingOf(r, msg);
    if (landing === 'say' || landing === 'drained') return landing;
    if (landing) seen = landing;
  }
  return seen;
}

/** 这几种形态出现，就算 agent 真的开口了。用户自己那句话不算。 */
const AGENT_ACTIVITY: ReadonlySet<RecordKind> = new Set<RecordKind>([
  'agent.say',
  'agent.think',
  'tool.call',
  'tool.result',
  'subagent.dispatch',
  'error',
]);

/** 十六种形态。身份由形态直接表达，统一记录不设发言人字段。 */
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
  | 'call.envelope'
  | 'usage.tick';

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
  'usage.tick',
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
  /**
   * 手上这批记录是替哪一场取回来的；手上没有记录时为 null。
   *
   * 中栏换会话的那一次渲染里，`records` 还是上一场的——清空要等下一拍。只看条数的人会把
   * 上一场的记录当成新这一场的：新建会话的启动卡就这样一挂上就被撤掉，人根本看不见它。
   */
  recordsSessionId: string | null;
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
  /**
   * 刚投了一句话进去，还没见 agent 有任何动静。
   *
   * 从按下发送到第一条新记录落盘，中间隔着一次 tmux 投喂加一轮冷启动，短则一两秒长则
   * 十几秒。这段空窗里界面上一个字都不变，人只能猜"是没发出去还是它在想"。这个标志
   * 就是给那句"在等"用的。
   */
  awaitingAgent: boolean;
  /**
   * 已经点了发送、还没成为新一轮的那些消息，按投出去的先后排。
   *
   * 输入区拿它画信封：`sent` 是"已发送、还没进这场会话"，`queued` 是"已经进来了、
   * 正排在队列上"。输入框在点发送那一刻就交还给人，这份清单是那句话此后唯一的去处——
   * 没有它，人只会以为自己那句话卡住了没发出去。
   */
  outbound: OutboundMessage[];
  /**
   * 告诉记录流「刚发出去一句」：进快节拍、举起"在等 agent 开口"、给它开一个信封。
   *
   * 返回那个信封的编号。发失败时把编号交回 `clearSent`，撤掉的就只是这一单。
   */
  markSent: (text: string, attachments?: number) => string;
  /**
   * 那句话**确实落进这场会话**的时刻（毫秒，没送达时为 null）。
   *
   * 发送那条接口要等整整一轮才返回（上限 180 秒），可"话送到了没有"这件事早在几秒内
   * 就有答案了——它会以一条记录的形式出现在流里。输入区靠这个时刻放行：清空输入框、
   * 把按钮从"发送中"放回去。挂在接口返回上的话，人明明看见自己的话已经在流里了，
   * 输入框却还塞着同一段字、按钮还转着圈，只能切走再切回来才恢复。
   */
  deliveredAt: number | null;
  /**
   * 那句话根本没发出去：撤掉"在等"，并把它的信封收走。
   *
   * 给了编号就只收那一个信封，不给就全收——挂着一个永远送不到的信封，比不提示还糟。
   */
  clearSent: (id?: string) => void;
  /**
   * 那一单的发送接口回来了，把它的信封收掉。
   *
   * 那条接口一直等到**这一轮说完**才返回，所以它一回来，那句话必定早就进了这场会话——
   * 认不认得出它在流里长什么样，都不该再替它站着。这是比对之外的第二道保险：记录的形状
   * 将来还会变（斜杠命令就变过一次），比对总有认不出的那天，而这一条不依赖任何形状。
   */
  settleSent: (id?: string) => void;
}

/**
 * 实时推送来的这一批，怎么并进手头这一窗。
 *
 * 三条：
 *
 * 1. **见过的按身份丢掉。** 同一条记录被重推是常态——服务端每次文件变动都整份重翻。
 * 2. **比手头这一窗头一条还早的一律丢掉。** 那不是新内容，是历史。页面手上只有尾部一页，
 *    窗外的记录接进来只能接在末尾，于是一段很早的对话被摆在最新内容前面，时间戳差出几个
 *    小时——这正是 2026-09-12 那天人看到的症状。窗外的历史该由往上翻那条路取回来，
 *    NEVER 从推送这条路进。
 * 3. **剩下的按序号落位，不是一律追加。** 引擎重写一条记录会让它后面的整体往前挪一格，
 *    新写下来的那句话因此可能落在窗内某个位置上；追加到末尾就把顺序搞乱了。同一个序号上
 *    新来的排在手头那条之后——挪位意味着它物理上更晚。
 *
 * 手上一条都没有时照收：那是新开的一场，它的档案本来就只有几行，这时候推送是唯一的内容来源。
 */
export function mergePushed(
  prev: WorkbenchRecord[],
  batch: WorkbenchRecord[]
): WorkbenchRecord[] {
  const held = new Set(prev.map((r) => r.id));
  const windowStart = prev.length ? prev[0].seq : Number.NEGATIVE_INFINITY;
  const fresh = batch
    .filter((r) => !held.has(r.id) && r.seq >= windowStart)
    .sort((a, b) => a.seq - b.seq);
  if (!fresh.length) return prev;
  const tail = prev.length ? prev[prev.length - 1].seq : Number.NEGATIVE_INFINITY;
  // 尾部追加是常态（新内容的序号都不小于手头末条），这一路一条都不搬。
  if (fresh[0].seq >= tail) return [...prev, ...fresh];
  const merged: WorkbenchRecord[] = [];
  let i = 0;
  for (const r of prev) {
    while (i < fresh.length && fresh[i].seq < r.seq) merged.push(fresh[i++]);
    merged.push(r);
  }
  while (i < fresh.length) merged.push(fresh[i++]);
  return merged;
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
    throw new Error(i18n.t('workbench.errors.recordsFetchFailed', { status: res.status }));
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
    throw new Error(i18n.t('workbench.errors.rawWithheld', { status: res.status }));
  }
  return res.json();
}

export function useWorkbenchRecords(
  sessionId: string | null,
  opts: { live?: boolean } = {}
): WorkbenchRecordsState {
  const { live = false } = opts;
  const [records, setRecords] = useState<WorkbenchRecord[]>([]);
  const [recordsSessionId, setRecordsSessionId] = useState<string | null>(null);
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
  // 刚发完话的快节拍窗口。WebSocket 通着时用不上，断连时它是唯一的兜底。
  const fastUntil = useRef(0);
  // 换节拍要把在飞的那个定时器一起换掉，否则"刚按下发送"还要先等满上一档的五秒。
  // 这个数字只用来重启轮询那个效应，本身不参与任何显示。
  const [pace, setPace] = useState(0);
  // 那句话是什么时候投出去的。等到 agent 真有动静、或者等满上限就清掉。
  const [awaitingSince, setAwaitingSince] = useState<number | null>(null);
  // 已发出、还没成为新一轮的那些消息。输入区照着它画信封。
  const [outbound, setOutbound] = useState<OutboundMessage[]>([]);
  // 信封编号用单调自增：同一毫秒连发两条不会撞。
  const outboundSeq = useRef(0);
  const [deliveredAt, setDeliveredAt] = useState<number | null>(null);

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
      setRecordsSessionId(batch.length ? sid : null);
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

  /**
   * 手上一条记录都没有时，改成重取尾部。
   *
   * 取增量要拿手头末条的位置当起点，一条都没有就无从下手。**刚建的那一场必定经过这个
   * 状态**：中栏在点完创建那一刻就切了过去，而那时这场会话的档案还没写下第一笔——第一
   * 次取尾部取了个空，此后每一趟取增量都因为没有起点而空手而回，中栏就一直空着，人只能
   * 切去别的会话再切回来，靠换会话那一次整个重取才看得见内容。
   *
   * 服务端那侧卡在同一个点上：实时推送是在取记录时顺带登记的，档案还不存在时登记不上，
   * 于是后来写下的内容也没有人推过来。所以空手这一趟改成重取尾部，一举两得——内容取回
   * 来了，实时推送也顺势登记上了。
   *
   * 不碰装载态：这条路是轮询走的，每隔几秒把中栏打回"加载中"会让整栏一直闪。
   */
  const pickUpTail = useCallback(async (sid: string): Promise<number> => {
    if (inflightNewer.current) return 0;
    inflightNewer.current = true;
    try {
      const batch = await fetchWorkbenchRecords(sid, { tail: true, limit: PAGE_SIZE });
      if (activeSession.current !== sid || !batch.length) return 0;
      recordsRef.current = batch;
      setRecords(batch);
      setRecordsSessionId(sid);
      setHasOlder(batch[0].seq > 0);
      hotUntil.current = Date.now() + HOT_WINDOW_MS;
      return batch.length;
    } catch {
      // 跟取增量一样：取不到不打断看记录的人，下一趟再试。
      return 0;
    } finally {
      inflightNewer.current = false;
    }
  }, []);

  /**
   * 取比手头末条更新的记录，往尾部追加。返回新取到几条——轮询靠它续命。
   *
   * **起点取手头末条自己那一格，不是它的下一格。** 序号不是地址：整场记录每次都是重新
   * 编号的，而每一轮结束引擎都会重写这场会话的花费账本，账本只留最后一份——前面那份一
   * 被丢掉，它后面所有内容的编号就整体往前挪一格。于是人刚发出去的那句话会落回轮询已经
   * 问过的号段，这一趟空手而归：话进去了，中栏却看不见它，输入区那个信封就一直挂着说没
   * 发出去（实时推送那条路认的是记录身份，所以推送通着的时候一切正常——症状因此时有时无）。
   *
   * 多要回来的这一条是对照：它还是原来那条，说明编号没动，后面的按身份并进去；换了人或
   * 者那一格整个没了，说明这场重排过，手上这份的位置全部作废，只能整段重取。
   */
  const appendNewer = useCallback(async (sid: string): Promise<number> => {
    if (inflightNewer.current) return 0;
    const last = recordsRef.current[recordsRef.current.length - 1];
    if (!last) return pickUpTail(sid);

    let renumbered = false;
    let taken = 0;
    inflightNewer.current = true;
    try {
      const batch = await fetchWorkbenchRecords(sid, { after: last.seq, limit: PAGE_SIZE });
      if (activeSession.current !== sid) return 0;
      if (!batch.length || batch[0].id !== last.id) {
        renumbered = true;
      } else {
        // 按身份并，不按位置并：对照那一条自己会被认出来丢掉，剩下的才是真的新内容。
        setRecords((prev) => {
          const next = mergePushed(prev, batch);
          if (next === prev) return prev;
          recordsRef.current = next;
          return next;
        });
        taken = batch.length - 1;
        if (taken > 0) hotUntil.current = Date.now() + HOT_WINDOW_MS;
      }
    } catch {
      // 增量取不到不打断看记录的人——下一次轮询再试。错误只在整流重取时才摆出来。
      return 0;
    } finally {
      inflightNewer.current = false;
    }
    // 重取放在闸门之外做：还占着 `inflightNewer` 的话，重取那一趟会被自己挡回去。
    return renumbered ? await pickUpTail(sid) : taken;
  }, [pickUpTail]);

  const reload = useCallback(async () => {
    if (!sessionId) return;
    // 重拉大多跟在发话后面——这一刻起会话是活的，轮询该醒了。
    hotUntil.current = Date.now() + HOT_WINDOW_MS;
    await loadTail(sessionId);
  }, [sessionId, loadTail]);

  const markSent = useCallback((text: string, attachments = 0) => {
    const now = Date.now();
    hotUntil.current = now + HOT_WINDOW_MS;
    fastUntil.current = now + FAST_POLL_WINDOW_MS;
    setAwaitingSince(now);
    setDeliveredAt(null);
    const id = `out-${now}-${outboundSeq.current++}`;
    setOutbound((prev) => [...prev, { id, text: text.trim(), attachments, at: now, state: 'sent' }]);
    setPace((n) => n + 1);
    return id;
  }, []);

  const clearSent = useCallback((id?: string) => {
    fastUntil.current = 0;
    setOutbound((prev) => (id ? prev.filter((m) => m.id !== id) : []));
    setAwaitingSince(null);
    setPace((n) => n + 1);
  }, []);

  const settleSent = useCallback((id?: string) => {
    if (!id) return;
    setOutbound((prev) => prev.filter((m) => m.id !== id));
  }, []);

  /**
   * 刚投出去那些话，在流里走到哪一档了。
   *
   * 两种露面方式都算，因为**投进去的话本来就有两种落地形态**：agent 当时闲着，它成为
   * 一条用户发言；agent 正忙着，它成为一张插话卡（那种情况下会话记录里根本不会有用户
   * 发言，只认前一种会让插话永远等不到放行）。
   *
   * 后一种再分两步：卡上写着"还在队列里"就是**已入队列**，信封留着并换成排队那一档；
   * 写着已并入或已发出，说明它已经成了那一轮的一部分，信封退场。
   *
   * 比时刻是必须的：同一句话重发一遍时，不比时刻会让上一轮那条老记录当场"送达"。
   */
  useEffect(() => {
    if (!outbound.length) return;
    const next = outbound.map((msg) => {
      const landing = landingIn(records, msg);
      if (landing === 'say' || landing === 'drained') return null;
      if (landing === 'queued' && msg.state !== 'queued') {
        return { ...msg, state: 'queued' as const };
      }
      return msg;
    });
    // 一个都没变就别回写：这个效应看着 outbound，回写同一份内容会把自己叫醒一遍。
    if (next.every((m, i) => m === outbound[i])) return;
    setOutbound(next.filter((m): m is OutboundMessage => m !== null));
    // 走到这里说明至少有一条真的进了这场会话——输入区的发送按钮据此放回去。
    setDeliveredAt(Date.now());
  }, [records, outbound]);

  /**
   * 「已发送」等太久就把信封撤掉。
   *
   * 服务端那次投喂最多等 180 秒，到点还没在流里露过面，多半是它以一种对不上的形态落了
   * 盘（比如纯附件那一路正文由服务端代写）。挂着一个永不消失的信封，比不提示还糟。
   * 「已入队列」不设这道闸——排队本来就可能排很久，它的退场信号是那一轮说完。
   */
  useEffect(() => {
    const waiting = outbound.filter((m) => m.state === 'sent');
    if (!waiting.length) return;
    const due = Math.min(...waiting.map((m) => m.at + AWAIT_REPLY_CEILING_MS));
    const timer = setTimeout(
      () => {
        const now = Date.now();
        setOutbound((prev) =>
          prev.filter((m) => m.state !== 'sent' || now < m.at + AWAIT_REPLY_CEILING_MS)
        );
      },
      Math.max(0, due - Date.now())
    );
    return () => clearTimeout(timer);
  }, [outbound]);

  // 等到 agent 真有动静就把"在等"撤掉。判据是**记录形态**，不是"记录变多了"——发完话
  // 重拉一次，多出来的第一条是用户自己刚说的那句，那不算 agent 开了口。
  useEffect(() => {
    if (awaitingSince === null) return;
    const spoke = records.some(
      (r) => r.ts >= awaitingSince - 1_000 && AGENT_ACTIVITY.has(r.kind)
    );
    // 跑在本机、跑完就完的那些命令（`/rename`、`/clear`）根本不会惊动模型，等 agent
    // 开口是在等一件永远不会发生的事——那句"在等"要一直挂到上限才自己撤掉，而命令其实
    // 早就跑完了。命令自己打印出来的那段就是回执，见到它就收。
    const printed = records.some(
      (r) =>
        r.ts >= awaitingSince - 1_000 &&
        r.kind === 'context.inject' &&
        r.payload.channel === 'local-command-output'
    );
    if (spoke || printed) {
      setAwaitingSince(null);
      return;
    }
    // 等满上限就撤。挂着一句永不消失的"在等"，比不提示还糟。
    const remaining = awaitingSince + AWAIT_REPLY_CEILING_MS - Date.now();
    const timer = setTimeout(() => setAwaitingSince(null), Math.max(0, remaining));
    return () => clearTimeout(timer);
  }, [records, awaitingSince]);

  useEffect(() => {
    activeSession.current = sessionId;
    recordsRef.current = [];
    setRecords([]);
    setRecordsSessionId(null);
    setHasOlder(false);
    setError(null);
    setAwaitingSince(null);
    setDeliveredAt(null);
    setOutbound([]);
    fastUntil.current = 0;
    if (!sessionId) return;
    void loadTail(sessionId);
  }, [sessionId, loadTail]);

  /**
   * 会话开始在跑、手上却一条记录都没有：当场补取一次，不必等下一趟轮询。
   *
   * 新建的那一场正落在这条缝里——中栏在它的档案存在之前就切了过去，那一次取尾部取了个
   * 空。它在左栏露面并显示「在跑」的那一刻，档案已经落地了，正是补取的时机。轮询本身也
   * 兜得住，但那要再等满一档（五秒），而这一刻人正盯着一片空白等它出内容。
   */
  useEffect(() => {
    if (!sessionId || !live) return;
    if (recordsRef.current.length) return;
    void pickUpTail(sessionId);
  }, [sessionId, live, pickUpTail]);

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

  // 轮询：会话活着（左栏判 running，或刚刚还有过动静）且页面看得见时取增量。
  //
  // 节拍是两档的：平时五秒，刚发完话那一分半钟一秒。定时器因此不能是 setInterval——
  // 节拍要能在两趟之间改，所以每跑完一趟自己排下一趟。
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const schedule = () => {
      const interval =
        fastUntil.current > Date.now() ? FAST_POLL_INTERVAL_MS : POLL_INTERVAL_MS;
      timer = setTimeout(tick, interval);
    };

    const tick = async () => {
      if (cancelled) return;
      const visible = document.visibilityState === 'visible';
      const awake = liveRef.current || hotUntil.current >= Date.now();
      if (visible && awake) {
        await appendNewer(sessionId);
      }
      if (!cancelled) schedule();
    };

    schedule();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // pace 变了就重排：换节拍必须连在飞的那个定时器一起换，否则"刚按下发送"还得先
    // 等满上一档的五秒——那五秒正是人盯着屏幕最想看到动静的五秒。
  }, [sessionId, appendNewer, pace]);

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
        // 顺序不托付给推送那一侧：见 mergePushed。推送只要错一次，人滚到底看见的就是
        // 一段很早的对话摆在最新内容前面，而界面上没有任何迹象说明发生了什么。
        const next = mergePushed(prev, batch);
        if (next === prev) return prev;
        recordsRef.current = next;
        return next;
      });
      setRecordsSessionId(sidRef.current);
      hotUntil.current = Date.now() + HOT_WINDOW_MS;
    };

    const onTurnDone = (msg: WebSocketMessage) => {
      const data = msg.data as Record<string, unknown> | undefined;
      if (!data || data.session_id !== sidRef.current) return;
      hotUntil.current = Date.now() + HOT_WINDOW_MS;
      // 这一轮说完，队列就排到头了：还挂着"已入队列"的信封该退场。那句话此刻要么
      // 已经被并进刚说完的这一轮，要么正作为下一轮开跑，两种下场都在记录流里有位置。
      setOutbound((prev) => prev.filter((m) => m.state !== 'queued'));
    };

    const client = getWebSocketClient();
    const unsub1 = client.on(MessageType.SESSION_RECORDS_APPEND, onRecordsAppend);
    const unsub2 = client.on(MessageType.SESSION_TURN_DONE, onTurnDone);

    return () => {
      unsub1();
      unsub2();
    };
  }, [sessionId]);

  return {
    records,
    recordsSessionId,
    loading,
    loadingOlder,
    hasOlder,
    error,
    loadOlder,
    reload,
    awaitingAgent: awaitingSince !== null,
    outbound,
    deliveredAt,
    markSent,
    clearSent,
    settleSent,
  };
}
