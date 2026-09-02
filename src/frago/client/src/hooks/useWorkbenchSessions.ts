/**
 * useWorkbenchSessions — 会话工作台左栏的数据源。
 *
 * 拉 `GET /api/workbench/sessions`：三家（Claude Code / opencode / codex）的会话已经
 * 在核心数据层合并并按**最后一句回复的时刻**倒序，这里一个字不重排。
 *
 * 搜索是**两条腿**：本地那条按标题、目录、会话编号即时筛，敲一个字就有反应；另一条
 * 把同一句话发去 `GET /api/workbench/search`，在会话内容（提示词与 agent 回复正文）
 * 里找。两条的结果取并集——人记得住的有时是标题，有时是当时说过的那句话，堵掉任何
 * 一条都会让搜索在最该用上的时候用不上。
 *
 * 与 `/api/claude-sessions` 那条路井水不犯河水——那条背后有正在跑的会话页。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useAutoRefresh } from './useAutoRefresh';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/** 会话属于哪一家。判定全在服务端做完，界面只负责显示。 */
export type SessionFamily = 'claude-code' | 'opencode' | 'codex';

/**
 * 会话现在什么情况。四档，没有第五档。
 *
 * 判定全在服务端做完（末条是报错 → 距今 90 秒内 → 末条是 agent 回复 → 其余），界面
 * 一个字都不重判。**没有「等你决策」这一档**：会话停在等人输入时，末条记录就是 agent
 * 的那句回复，与已经答完在数据上一模一样，凑不出来。
 */
export type SessionStatus = 'running' | 'error' | 'done' | 'idle';

/** 左栏一行 = 一场会话。字段与 `record_reader.SessionCard` 逐字对齐。 */
export interface WorkbenchSession {
  session_id: string;
  family: SessionFamily;
  title: string;
  directory: string;
  /** 毫秒时间戳。 */
  created_at: number;
  /** 毫秒时间戳。会话文件最后被动过的时刻，判「还在跑吗」用它。 */
  last_active_at: number;
  /**
   * 最后一句 agent 回复是什么时候说的（毫秒时间戳）。**清单按它倒序。**
   *
   * 与上一格分开是因为两者会差很远：hook 每拦一次工具、模型每改一次标题都会推进
   * 「最后动过」，但那些都不是任何人说了话。取不到时为 null，退回上一格。
   */
  last_reply_at: number | null;
  agent_paths: string[];
  status: SessionStatus;
  /** 最近一件确定做完的事。取不到就是 null，界面不补占位话术。 */
  digest_done: string | null;
  /** 当前阻塞点。只有状态为报错时才有值。 */
  digest_stuck: string | null;
}

/**
 * 这场会话该按哪个时刻摆、显示哪个时刻。
 *
 * 先看最后一句回复，取不到才退回文件最后动过的时刻。服务端排序用的是同一条判据——
 * 界面显示的时刻必须跟排序用的是同一个，否则清单看起来就是乱的。
 */
export function activityTs(session: WorkbenchSession): number {
  return session.last_reply_at ?? session.last_active_at;
}

export const FAMILY_LABEL: Record<SessionFamily, string> = {
  'claude-code': 'Claude Code',
  opencode: 'opencode',
  codex: 'codex',
};

export const STATUS_LABEL: Record<SessionStatus, string> = {
  running: '在跑',
  error: '出错',
  done: '已完成',
  idle: '停着',
};

/**
 * 左栏的筛选维度是**状态**，不是来源。
 *
 * 左栏最值钱的是「一眼看出每场什么情况」，按来源分组答不了这个问题——本机 1139 场
 * Claude Code 会话摆在一起，知道它们都来自 Claude Code 没有任何用。来源仍留在卡片上
 * 看得见，只是不再当筛选维度。
 */
export type StatusFilter = SessionStatus | 'all';

export type StatusCounts = Record<StatusFilter, number>;

/**
 * 时间范围是**另一个维度**，与状态四档并存而不是二选一：状态答「现在什么情况」，
 * 时间答「哪一段时间的」。
 *
 * `0` 是不设上限。旧会话页把默认压在 7 天，代价是本机一千多场里绝大多数看不见；
 * 工作台的左栏本来就要一次摆开全部，所以默认不限，四档由人主动收窄。
 */
export const DAY_OPTIONS = [1, 7, 14, 30] as const;

export type DayRange = 0 | (typeof DAY_OPTIONS)[number];

/** 会话内容里的一处命中。只可能出自提示词或 agent 回复正文。 */
export interface ContentHit {
  record_id: string;
  kind: 'user.say' | 'agent.say';
  ts: number;
  /** 命中处前后各留一小段，空白已压平。 */
  snippet: string;
}

/** 一场会话的内容命中情况。 */
export interface ContentMatch {
  session_id: string;
  family: SessionFamily;
  /** 命中了多少条记录（不是多少次）。 */
  hit_count: number;
  hits: ContentHit[];
  /** 这场会话的命中太多，报出来的不是全部。 */
  capped: boolean;
}

/** 内容检索这一路的现状。 */
export interface ContentSearchState {
  /** 这批结果对应的是哪一句话。跟输入框不一定同步——结果总比敲字慢半拍。 */
  query: string;
  matches: Map<string, ContentMatch>;
  searching: boolean;
  /** 这一趟哪里没做全。NEVER 藏起来——做不全却不说等于谎报覆盖面。 */
  warnings: string[];
  error: string | null;
}

/** 敲完字等多久才去搜内容。一趟内容检索是秒级的，边敲边发只会白烧。 */
export const SEARCH_DEBOUNCE_MS = 450;

/** 少于这么多字不去搜内容：一个字能命中几乎所有会话，搜了也没用。 */
export const MIN_CONTENT_QUERY = 2;

/**
 * 左栏隔多久自己去取一次清单。
 *
 * 一趟是把本机全部会话档案的元信息扫一遍，秒级；15 秒一趟在"看得出在跑"和"别把
 * 机器扫忙"之间。页面被藏起来时这个定时器不发请求（见 `useAutoRefresh`）。
 */
export const SESSION_REFRESH_MS = 15_000;

export async function fetchContentMatches(
  query: string,
  signal?: AbortSignal
): Promise<{ matches: ContentMatch[]; warnings: string[] }> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/search?q=${encodeURIComponent(query)}`,
    { signal }
  );
  if (!res.ok) {
    throw new Error(`内容搜不了（HTTP ${res.status}）`);
  }
  const body = (await res.json()) as { sessions?: ContentMatch[]; warnings?: string[] };
  return { matches: body.sessions ?? [], warnings: body.warnings ?? [] };
}

export interface WorkbenchSessionsState {
  sessions: WorkbenchSession[];
  /** 过滤后的清单，左栏实际渲染的就是它。 */
  visible: WorkbenchSession[];
  /**
   * 只过了搜索这一道、还没按状态与时间范围收窄的那一批。**置顶区渲染的是它。**
   *
   * 置顶区不跟状态与时间范围走：那两道答的是"翻哪一段、翻哪一档"，而置顶区的意义正是
   * "这几场我随时要回来"——点一下「7 天」就让人自己挑出来的那几场消失，是把筛选的语义
   * 套到了一个根本不该被筛的地方。搜索另说：那一刻人是在找某一场，置顶区跟着筛才不会答
   * 非所问。
   *
   * 摆在这里而不是让左栏自己再筛一遍：搜索是两条腿取并集（见 `searched`），判据抄第二遍
   * 迟早两处各走各的。
   */
  searched: WorkbenchSession[];
  loading: boolean;
  error: string | null;
  search: string;
  setSearch: (value: string) => void;
  status: StatusFilter;
  setStatus: (value: StatusFilter) => void;
  /** 只看最近几天有过动静的。0 = 不限。 */
  days: DayRange;
  setDays: (value: DayRange) => void;
  /**
   * 每一档各有几场，外加总数。全是已经发生的绝对数，没有分母。
   *
   * 计数按**搜索与时间范围之后、状态筛选之前**算：筛掉的那几档也要报出真实条数，否则点进
   * 「出错」看到 8 场、退回「全部」又变成另一个数，人会以为漏了。
   */
  counts: StatusCounts;
  /** 内容检索这一路的现状。左栏据此显示"搜内容中"与每场的命中摘要。 */
  content: ContentSearchState;
  reload: () => Promise<void>;
}

export async function fetchWorkbenchSessions(): Promise<WorkbenchSession[]> {
  const res = await fetch(`${API_BASE_URL}/api/workbench/sessions`);
  if (!res.ok) {
    throw new Error(`会话清单取不到（HTTP ${res.status}）`);
  }
  return (await res.json()) as WorkbenchSession[];
}

export function useWorkbenchSessions(): WorkbenchSessionsState {
  const [sessions, setSessions] = useState<WorkbenchSession[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<StatusFilter>('all');
  const [days, setDays] = useState<DayRange>(0);

  /**
   * HTML 加载阶段已经并行发过一次会话清单请求（见 `index.html` 的内联预取）。挂载时
   * 若那一份已经到了，直接拿来用，省掉一次串在程序包之后的往返；没到就走原路。
   */
  const tryReadPrefetch = useCallback(() => {
    const w = window as unknown as {
      __frago_prefetched__?: { sessions: WorkbenchSession[] | null; fetchedAt: number | null };
    };
    if (w.__frago_prefetched__?.sessions?.length) {
      setSessions(w.__frago_prefetched__.sessions);
      return true;
    }
    return false;
  }, []);

  /**
   * 取清单。`silent` 决定这一趟要不要把「装载中」举起来。
   *
   * 定时那几趟必须是安静的：`loading` 一举起来，左栏整片会换成骨架屏，每 15 秒闪一
   * 次白，比清单旧还难用。人自己按刷新、或者开局第一趟才该看得见在装。
   */
  const load = useCallback(async (silent: boolean) => {
    if (!silent) setLoading(true);
    try {
      setSessions(await fetchWorkbenchSessions());
      setError(null);
    } catch (e) {
      // 取不到就说取不到，但**手上那份清单留着**——定时重取偶尔失手时把整片清单
      // 换成一句错误，代价远大于让人多看一句提示。
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  const reload = useCallback(() => load(false), [load]);

  /**
   * 清单会自己变新。
   *
   * 左栏这份清单的价值全在「现在什么情况」——哪场在跑、哪场刚报错。挂载时取一次
   * 就不动的话，人在旁边跑着 agent，界面上那场永远停在"在跑"或者根本没出现，而
   * 它看起来跟刚取回的一模一样，没有任何迹象说明这是旧的。
   *
   * 预取那一份只免掉开局第一趟，此后照常按时重取。
   */
  const firstRun = useRef(true);

  useAutoRefresh(
    async () => {
      if (firstRun.current) {
        firstRun.current = false;
        // 预取那一份已经到了就直接用，省掉一次串在程序包之后的往返。
        if (tryReadPrefetch()) return;
        // 开局手上什么都没有，这一趟该看得见在装。
        await load(false);
        return;
      }
      await load(true);
    },
    { intervalMs: SESSION_REFRESH_MS }
  );

  /**
   * 内容检索：敲字停下来才发，且**只发最后那一句**。
   *
   * 每敲一个字发一趟的话，服务端要在 3.2 GB 语料上白扫十几遍，而前面那些结果一个都
   * 不会被看到。前一趟没回来就换了词时直接掐掉，NEVER 让慢的那趟后到、把新词的结果
   * 盖回旧的。
   */
  const [content, setContent] = useState<ContentSearchState>({
    query: '',
    matches: new Map(),
    searching: false,
    warnings: [],
    error: null,
  });
  const inflight = useRef<AbortController | null>(null);

  useEffect(() => {
    const q = search.trim();
    inflight.current?.abort();
    if (q.length < MIN_CONTENT_QUERY) {
      setContent({ query: q, matches: new Map(), searching: false, warnings: [], error: null });
      return;
    }
    setContent((prev) => ({ ...prev, searching: true, error: null }));
    const timer = setTimeout(() => {
      const controller = new AbortController();
      inflight.current = controller;
      fetchContentMatches(q, controller.signal)
        .then(({ matches, warnings }) => {
          setContent({
            query: q,
            matches: new Map(matches.map((m) => [m.session_id, m])),
            searching: false,
            warnings,
            error: null,
          });
        })
        .catch((e: unknown) => {
          if (e instanceof DOMException && e.name === 'AbortError') return;
          setContent({
            query: q,
            matches: new Map(),
            searching: false,
            warnings: [],
            error: e instanceof Error ? e.message : String(e),
          });
        });
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [search]);

  /**
   * 搜索之后、按状态筛之前的那一批。计数与筛选都从它出发。
   *
   * 本地那条腿（标题、目录、编号）与内容那条腿取**并集**：两者各能答一半问题，取交集
   * 会让"记得说过什么但不记得叫什么"的场景一场都搜不到。
   */
  const searched = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter(
      (s) =>
        content.matches.has(s.session_id) ||
        [s.title, s.directory, s.session_id, s.digest_done ?? '', s.digest_stuck ?? '']
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
          .includes(q)
    );
  }, [sessions, search, content.matches]);

  /**
   * 再按时间范围收一道。比的是**清单排序用的那个时刻**（见 `activityTs`），不是创建
   * 时刻——人问「最近七天」，问的是这七天里说过话的会话，一场半年前开、昨天还在跑的
   * 必须留下。跟排序共用同一个时刻，否则会出现"排在第一条却被七天筛掉"这种怪事。
   */
  const inRange = useMemo(() => {
    if (!days) return searched;
    const floor = Date.now() - days * 24 * 60 * 60 * 1000;
    return searched.filter((s) => activityTs(s) >= floor);
  }, [searched, days]);

  const counts = useMemo(() => {
    const c: StatusCounts = { all: inRange.length, running: 0, error: 0, done: 0, idle: 0 };
    for (const s of inRange) {
      if (s.status in c) c[s.status] += 1;
    }
    return c;
  }, [inRange]);

  const visible = useMemo(
    () => (status === 'all' ? inRange : inRange.filter((s) => s.status === status)),
    [inRange, status]
  );

  return {
    sessions,
    visible,
    searched,
    loading,
    error,
    search,
    setSearch,
    status,
    setStatus,
    days,
    setDays,
    counts,
    content,
    reload,
  };
}
