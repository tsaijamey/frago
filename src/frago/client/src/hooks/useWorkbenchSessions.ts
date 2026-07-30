/**
 * useWorkbenchSessions — 会话工作台左栏的数据源。
 *
 * 拉 `GET /api/workbench/sessions`：两家（Claude Code / opencode）的会话已经在核心
 * 数据层合并并按最后活动时刻倒序，这里一个字不重排。
 *
 * 与 `/api/claude-sessions` 那条路井水不犯河水——那条背后有正在跑的会话页。
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/** 会话属于哪一家。服务端按会话编号的形状判定，界面只负责显示。 */
export type SessionFamily = 'claude-code' | 'opencode';

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
  /** 毫秒时间戳。清单已按它倒序。 */
  last_active_at: number;
  agent_paths: string[];
  status: SessionStatus;
  /** 最近一件确定做完的事。取不到就是 null，界面不补占位话术。 */
  digest_done: string | null;
  /** 当前阻塞点。只有状态为报错时才有值。 */
  digest_stuck: string | null;
}

export const FAMILY_LABEL: Record<SessionFamily, string> = {
  'claude-code': 'Claude Code',
  opencode: 'opencode',
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

export interface WorkbenchSessionsState {
  sessions: WorkbenchSession[];
  /** 过滤后的清单，左栏实际渲染的就是它。 */
  visible: WorkbenchSession[];
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

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSessions(await fetchWorkbenchSessions());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!tryReadPrefetch()) {
      void reload();
    }
  }, [reload, tryReadPrefetch]);

  /** 搜索之后、按状态筛之前的那一批。计数与筛选都从它出发。 */
  const searched = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter((s) =>
      [s.title, s.directory, s.session_id, s.digest_done ?? '', s.digest_stuck ?? '']
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
        .includes(q)
    );
  }, [sessions, search]);

  /**
   * 再按时间范围收一道。比的是**最后活动时刻**，不是创建时刻——人问「最近七天」，问的是
   * 这七天里动过的会话，一场半年前开、昨天还在跑的必须留下。
   */
  const inRange = useMemo(() => {
    if (!days) return searched;
    const floor = Date.now() - days * 24 * 60 * 60 * 1000;
    return searched.filter((s) => s.last_active_at >= floor);
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
    loading,
    error,
    search,
    setSearch,
    status,
    setStatus,
    days,
    setDays,
    counts,
    reload,
  };
}
