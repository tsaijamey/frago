/**
 * useWorkbenchSessions — 会话工作台左栏的数据源。
 *
 * 拉 `GET /api/workbench/sessions`：三家（Claude Code / opencode / codex）的会话已经
 * 在核心数据层合并并按**最后一句回复的时刻**倒序，这里一个字不重排。
 *
 * 搜会话不在这里：它是全站的 ⌘K 浮窗（见 `SessionSearchPalette`），结果只摆在浮窗里，
 * 不去筛这份清单。
 *
 * 与 `/api/claude-sessions` 那条路井水不犯河水——那条背后有正在跑的会话页。
 */

import { useCallback, useMemo, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';

import i18n from '@/i18n';
import { pageCache } from './pageCache';
import { useAutoRefresh } from './useAutoRefresh';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/**
 * 会话属于哪一家。判定全在服务端做完，界面只负责显示。
 *
 * `coreagent` 是 frago 自己那个 agent——定时任务、待办拟稿这些活儿由它去办，起头时没人
 * 在旁边看着。它的记录形状与 Claude Code 的一模一样，单列一家是因为**来源要分得开**：
 * 跟人自己开的会话混在一起就找不着了。这一家在中栏同样能接着说话，只是它没有挂在终端
 * 里的交互界面，所以清单上不给「复制续接命令」那颗按钮。
 */
export type SessionFamily = 'claude-code' | 'opencode' | 'codex' | 'coreagent';

/**
 * 会话现在什么情况。四档，没有第五档。
 *
 * 判定全在服务端做完（末条是报错 → 距今 90 秒内 → 末条是 agent 回复 → 其余），界面
 * 一个字都不重判。**没有「等你决策」这一档**：会话停在等人输入时，末条记录就是 agent
 * 的那句回复，与已经答完在数据上一模一样，凑不出来。
 */
export type SessionStatus = 'running' | 'error' | 'done' | 'idle';

/**
 * 这场会话是谁开的：人自己开的，还是 frago 派出去干活的 worker。
 *
 * 判定全在服务端做完（见 `frago.session.session_origin`），界面一个字都不重判。
 * 判不出来的一律是 `human`——把一场人自己谈了半天的会话折进 worker 堆里，比多显示
 * 几场 worker 糟得多。
 */
export type SessionOrigin = 'human' | 'worker';

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
  /** 人自己开的，还是 frago 派出去的 worker。 */
  origin: SessionOrigin;
  /**
   * 派活的那场会话。只有认得出来的 worker 才有值。
   *
   * 左栏据此把 worker 折到派活的那一场下面。认不出父亲的 worker 仍是 worker，只是
   * 没地方可挂，另有一处收它们（见 `SessionRail`）。
   */
  parent_session_id: string | null;
  /**
   * 这一场此刻开在某个 tmux 会话里。左栏据此给卡片挂流光。
   *
   * 服务端只按名字 `frago-agent-<编号>` 对，飞书群、语音这类名字是业务把手的会话开着
   * 也是 false。可选是因为旧服务端不给这个字段，没给就当没开着。
   */
  in_tmux?: boolean;
  /**
   * 开着时那个 tmux 会话的名字，没开着为 null。命名规则只在服务端一处，这里不自己拼——
   * 「关闭 tmux 会话」的弹窗要把它原样摆给人看。旧服务端不给，没给就不摆。
   */
  tmux_name?: string | null;
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

/**
 * 家族名与状态名摆的是**词表里的键**，不是字。
 *
 * 这两张表是模块级常量，模块加载时 `t()` 还没有语言上下文；在这里直接把字取出来，会
 * 把它锁死在开局那一种语言上——人切到另一种语言，左栏的「在跑」「已完成」一个字都不动。
 * 所以这里只存键，取字的那一下由用到它的组件在渲染时做（见 `useWorkbenchLabels`）。
 */
export const FAMILY_LABEL_KEY: Record<SessionFamily, string> = {
  'claude-code': 'workbench.family.claude-code',
  opencode: 'workbench.family.opencode',
  codex: 'workbench.family.codex',
  coreagent: 'workbench.family.coreagent',
};

export const STATUS_LABEL_KEY: Record<SessionStatus, string> = {
  running: 'workbench.status.running',
  error: 'workbench.status.error',
  done: 'workbench.status.done',
  idle: 'workbench.status.idle',
};

/**
 * 把上面那两张键表取成字。**取字这一下必须发生在渲染里。**
 *
 * 用这个 hook 的组件跟着 i18next 的语言重渲染，人在设置里换一次语言，左栏的状态名与
 * 家族名当场就变，不用刷新页面。家族名认不出时原样返回——服务端将来多接一家，界面上
 * 至少还看得见它叫什么，而不是一片空白。
 */
export function useWorkbenchLabels() {
  const { t } = useTranslation();
  return useMemo(
    () => ({
      statusLabel: (status: SessionStatus) => t(STATUS_LABEL_KEY[status]),
      familyLabel: (family: string) => {
        const key = FAMILY_LABEL_KEY[family as SessionFamily];
        return key ? t(key) : family;
      },
    }),
    [t]
  );
}

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
 * `0` 是不设上限。默认 1 天：左栏开局只摆最近一天的，更早的由人主动放宽。
 */
export const DAY_OPTIONS = [1, 2, 7] as const;

export type DayRange = 0 | (typeof DAY_OPTIONS)[number];

/**
 * 左栏隔多久自己去取一次清单。
 *
 * 一趟是把本机全部会话档案的元信息扫一遍，秒级；15 秒一趟在"看得出在跑"和"别把
 * 机器扫忙"之间。页面被藏起来时这个定时器不发请求（见 `useAutoRefresh`）。
 */
export const SESSION_REFRESH_MS = 15_000;

export interface WorkbenchSessionsState {
  sessions: WorkbenchSession[];
  /** 过滤后的清单，左栏实际渲染的就是它。 */
  visible: WorkbenchSession[];
  loading: boolean;
  error: string | null;
  status: StatusFilter;
  setStatus: (value: StatusFilter) => void;
  /** 只看最近几天有过动静的。0 = 不限。 */
  days: DayRange;
  setDays: (value: DayRange) => void;
  /**
   * 每一档各有几场，外加总数。全是已经发生的绝对数，没有分母。
   *
   * 计数按**时间范围之后、状态筛选之前**算：筛掉的那几档也要报出真实条数，否则点进
   * 「出错」看到 8 场、退回「全部」又变成另一个数，人会以为漏了。
   */
  counts: StatusCounts;
  reload: () => Promise<void>;
}

export async function fetchWorkbenchSessions(): Promise<WorkbenchSession[]> {
  const res = await fetch(`${API_BASE_URL}/api/workbench/sessions`);
  if (!res.ok) {
    throw new Error(i18n.t('workbench.errors.sessionsFetchFailed', { status: res.status }));
  }
  return (await res.json()) as WorkbenchSession[];
}

/**
 * 最近一次拿到手的清单（见 `pageCache`）。
 *
 * 回来时若从头开局，开局那一趟读到的还会是网页刚打开时预取的那份——可能是几小时前的，
 * 那之后新开的会话一场都不在。所以回来时摆上次那份，同时立刻安静地重取一趟。
 */
const lastSessions = pageCache<WorkbenchSession[]>();

export function useWorkbenchSessions(): WorkbenchSessionsState {
  const [sessions, setSessionsState] = useState<WorkbenchSession[]>(() => lastSessions.get() ?? []);
  const setSessions = useCallback((next: WorkbenchSession[]) => {
    lastSessions.set(next);
    setSessionsState(next);
  }, []);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<StatusFilter>('all');
  const [days, setDays] = useState<DayRange>(1);

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
  }, [setSessions]);

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
  }, [setSessions]);

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
        // 这个网页里已经拿到过清单（切去别的菜单又回来）：上次那份已经摆着，安静重取即可。
        // NEVER 再读预取那份——它停在网页刚打开的那一刻。
        if (lastSessions.get()) {
          await load(true);
          return;
        }
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
   * 再按时间范围收一道。比的是**清单排序用的那个时刻**（见 `activityTs`），不是创建
   * 时刻——人问「最近七天」，问的是这七天里说过话的会话，一场半年前开、昨天还在跑的
   * 必须留下。跟排序共用同一个时刻，否则会出现"排在第一条却被七天筛掉"这种怪事。
   */
  const inRange = useMemo(() => {
    if (!days) return sessions;
    const floor = Date.now() - days * 24 * 60 * 60 * 1000;
    return sessions.filter((s) => activityTs(s) >= floor);
  }, [sessions, days]);

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
    status,
    setStatus,
    days,
    setDays,
    counts,
    reload,
  };
}
