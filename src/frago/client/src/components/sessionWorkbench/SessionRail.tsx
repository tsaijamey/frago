/**
 * SessionRail — 左栏：搜索与新建、时间范围、For you / 全部、会话清单、底部汇总。
 *
 * 三家（Claude Code / opencode / codex）的会话在核心数据层就合并排好了，这里不重排时间序。
 *
 * **清单只回答一个问题：哪几场要我来读、来接着说。** 每一条要么挂「For you」（有 agent
 * 停在输入框前等你，判据见 `useForYou`），要么什么状态都不挂。Running / Done / Idle /
 * Error 这些状态词、来源字样、摘要预览都已退场——人来清单不是来看每场处在哪个状态的。
 *
 * **分区顺序**：Pinned（组内 For you 在前）→ For you（等得最久的在上）→ Everything else
 * （按时间）→ Workers with no parent session（默认折起）。worker 仍按派活的那场折在它下面。
 * **分支会话不折**：它是人亲手起的、等的也是人，和人开的会话一样摆在主干上（等你时进
 * For you），出处只在卡片上一行「分支自 <原会话>」里说（主人 09-28 定）。
 * 按标签分组（含 AI 分组）随第三轮原型退场：Everything else 里只按时间排。
 *
 * **搜索不筛这张清单。** 顶上那一行只是入口，点它或按 ⌘K 打开全站的搜会话浮窗。
 *
 * **置顶区是一片自己说了算的地方。** 名单存在服务端（见 `useSessionPins`），次序照置顶的
 * 次序，不跟时间范围与档位走。整组一块略浅的底加一圈发丝描边——窗口化列表里整组不是一个
 * 节点，所以跟 worker 框一样拆成头、中、尾三段画。
 *
 * **清单打开时停在顶部。** 选中那条不在视野里时，筛选区下面摆一行「Current session is
 * below ↓」，点一下滚过去；行尾只跟 For you 或 Sending。
 *
 * **列表走窗口化渲染。** 全量会话可能上千场，用 Virtuoso 只渲染视口内可见的卡片。分区标题
 * 是列表里的普通一行，不是 group header——后者要等量完每一行的高度才摆得出来。
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Virtuoso, type VirtuosoHandle } from 'react-virtuoso';
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  Loader2,
  Mail,
  Pin,
  Plus,
  RefreshCw,
  Search,
  X,
} from 'lucide-react';
import { useAppStore, useUIStore } from '@/stores/appStore';
import { modKey } from '@/hooks/usePlatform';
import { closeTmuxSessions } from '@/api';
import SessionItem, { ForYouChip, SendingChip, resumeCommand, shortAge } from './SessionItem';
import NewSessionModal from './NewSessionModal';
import { useSessionPins } from '@/hooks/useSessionPins';
import type { SessionViewsState } from '@/hooks/useSessionViews';
import type { ForYouState } from '@/hooks/useForYou';
import { LiveBorder } from '@/components/ui/LiveEdge';
import type { PendingLaunch } from '@/hooks/useAgentClients';
import type { SessionLaunch } from '@/hooks/useSessionLaunch';
import {
  DAY_OPTIONS,
  type DayRange,
  type ListFilter,
  type WorkbenchSession,
  type WorkbenchSessionsState,
} from '@/hooks/useWorkbenchSessions';

/** 档位选中态：中性填充 + 字重。整块换底，不靠任何单边色条，也不用绿。 */
const CHIP_ON = 'bg-bg-active text-text-primary font-medium';
const CHIP_OFF = 'text-text-muted hover:bg-bg-hover hover:text-text-secondary';

/** 只剩两档：For you 与全部。 */
const FILTERS: ListFilter[] = ['for-you', 'all'];

const FILTER_LABEL_KEY: Record<ListFilter, string> = {
  'for-you': 'workbench.forYou.label',
  all: 'workbench.rail.filterAll',
};

/**
 * 一次往清单里放多少场。滚到底再放下一批。
 *
 * **窗口化渲染解决的是"画多少个节点"，不是"这条清单有多长"。** 七百多场会话一次全摆进去，
 * 滚动条被压成一道细缝；切成一批一批之后，滚动条的长度重新与"我看过多少"对得上。
 */
const PAGE_SIZE = 50;

/** 时间范围：三档加不限。 */
const DAY_FILTERS: DayRange[] = [...DAY_OPTIONS, 0];

/**
 * 列表里的一行：分区标题，或一张会话卡。
 *
 * 会话卡带着它在这棵树里的位置：`nested` 是"挂在上面那一行下面的 worker"，
 * `workerCount` 是这一行自己派出去过几个。两样都由 `rows` 一次算完，卡片不自己推导。
 */
type RailRow =
  | { kind: 'pinned-header' }
  | { kind: 'for-you-header'; count: number; pinnedAbove: number }
  | { kind: 'rest-header'; count: number }
  | { kind: 'workers-header' }
  /** 置顶组的收尾：组是一块整的底，末一行要把框收上。 */
  | { kind: 'pinned-tail' }
  | {
      kind: 'session';
      session: WorkbenchSession;
      nested?: boolean;
      workerCount?: number;
      workersExpanded?: boolean;
      groupPos?: GroupPos;
      /** 在置顶那一块里。 */
      inPinned?: boolean;
    };

/**
 * 展开之后，主会话与它的 worker 被一个框圈在一起。框跨了好几行，而每一行在窗口化列表
 * 里是独立的一项，所以框只能拆着画：头一行画上半框、中间几行画两侧、末一行收底。
 * 三段拼起来就是一个完整的框，与折叠时那张纸同一套颜色、粗细、圆角。
 *
 * 这不是单边色条：三段合起来是四条边，颜色是清单里到处在用的那个分隔线色，不带任何强调
 * 语义——它说的是"这几行是一组"，不是"这一行被选中了"。
 */
type GroupPos = 'head' | 'mid' | 'tail';

/** 此刻开在 tmux 里的那几场，卡片外面长一圈流光；其余原样摆着，不多包一层节点。 */
function MaybeLive({ live, children }: { live: boolean; children: ReactNode }) {
  return live ? <LiveBorder>{children}</LiveBorder> : <>{children}</>;
}

export interface SessionRailProps {
  state: WorkbenchSessionsState;
  selectedId: string | null;
  onSelect: (id: string) => void;
  /**
   * 正在起、还没进清单的那一场。有值就在清单上方摆一张启动卡——从点完创建到这一行
   * 真的长出来有将近十秒，那十秒里左栏什么都不说的话，人只会以为没建成。
   */
  launch?: SessionLaunch | null;
  /** 建出去了。等编号、反复重取清单这些事由页面那边的启动状态接手，左栏不自己等。 */
  onCreated?: (pending: PendingLaunch, text: string) => void;
  /**
   * 把没起来的那张卡收掉。
   *
   * 这个入口在左栏也要有：人在等的时候点开了别的会话，中栏就不再是那块启动面板，
   * 那边的收起按钮他够不着，而没起来的卡不会自己消失。
   */
  onDismissLaunch?: () => void;
  /** 上次点开各场的时刻与「开在 tmux 里」。页面那一层持有，For you 判「看过没」也用它。 */
  views: SessionViewsState;
  /** 哪几场挂 For you（页面那一层持有，页头也要读）。 */
  forYou: ForYouState;
  /** 本地刚发出一句、还在路上的那一场。 */
  sendingId?: string | null;
}

export default function SessionRail({
  state,
  selectedId,
  onSelect,
  launch = null,
  onCreated,
  onDismissLaunch,
  views,
  forYou,
  sendingId = null,
}: SessionRailProps) {
  const { sessions, visible, counts, loading, error, filter, setFilter, days, setDays, reload } =
    state;
  const { t } = useTranslation();
  const showToast = useAppStore((s) => s.showToast);
  const openSearch = useUIStore((s) => s.setSessionSearchOpen);
  const pins = useSessionPins();
  const [newOpen, setNewOpen] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  /** 哪几场把自己派出去的 worker 展开着。默认一场都不展开——清单的主干是主会话。 */
  const [expandedWorkers, setExpandedWorkers] = useState<Set<string>>(new Set());
  /** 认不出谁派的那堆 worker 那一区是不是展开着。默认折起来。 */
  const [orphansOpen, setOrphansOpen] = useState(false);
  /** 眼下这条清单已经放进来多少场。滚到底加一批（见 `PAGE_SIZE`）。 */
  const [shown, setShown] = useState(PAGE_SIZE);

  const familyCounts = useMemo(() => {
    let cc = 0;
    let oc = 0;
    let cx = 0;
    let ca = 0;
    for (const s of sessions) {
      if (s.family === 'claude-code') cc += 1;
      else if (s.family === 'opencode') oc += 1;
      else if (s.family === 'codex') cx += 1;
      else if (s.family === 'coreagent') ca += 1;
    }
    return { cc, oc, cx, ca };
  }, [sessions]);

  /**
   * 置顶区摆哪几场。
   *
   * 次序照置顶的次序，不按最后活动时刻重排——那一区的意义正是"我说了算"，跟着活动时刻
   * 重排等于把人刚摆好的次序打乱。名单里有编号、清单里却没有那场（档案被删或被滚删）时
   * 就是不显示，NEVER 因此把编号从名单里踢掉：一次滚删不该悄悄清空人的置顶。
   */
  const pinnedRows = useMemo(() => {
    if (!pins.pinned.length) return [];
    const rank = new Map(pins.pinned.map((id, i) => [id, i]));
    // 组内 For you 在前；同一档里保持置顶的次序
    const waiting = (s: WorkbenchSession) => (forYou.infoOf(s.session_id) ? 0 : 1);
    return sessions
      .filter((s) => rank.has(s.session_id))
      .sort(
        (a, b) =>
          waiting(a) - waiting(b) || rank.get(a.session_id)! - rank.get(b.session_id)!
      );
  }, [sessions, pins.pinned, forYou]);

  /**
   * 把那一列会话摆成两层：主干是主会话，frago 派出去的 worker 折在派活的那一场下面。
   *
   * **为什么要分层。** 本机两千多场会话里一千五百场是 worker，它们与人自己开的会话
   * 混在同一列里，人找自己刚才谈的那一场要一直往下翻。分层之后主干只剩人开的那几百场，
   * worker 一个都没丢，只是收在它自己该在的地方。
   *
   * 三种去处，判据只看服务端给的两个字段：
   * - 派活的那场会话**也在当前这份清单里** → 折到它下面。
   * - 是 worker 但认不出谁派的（或派活的那场被筛掉了）→ 收进末尾那一区。
   * - 其余 → 主干。
   */
  /** 编号 → 标题。分支会话卡片上那一行「分支自」用；在整份清单里认，原会话被筛掉了也认得出。 */
  const titleOf = useMemo(() => new Map(sessions.map((s) => [s.session_id, s.title])), [sessions]);

  const { trunkRows, childrenOf, orphanRows } = useMemo(() => {
    // 认父亲要在**整份清单**里认，不是只在下面那一片里认：派活的那场会话可能被置顶了，
    // 只看下面那一片的话，它的 worker 会认不出父亲、掉进末尾那一区——而它的父亲就摆在
    // 屏幕最上面。
    const present = new Set(visible.map((s) => s.session_id));
    const children = new Map<string, WorkbenchSession[]>();
    const trunk: WorkbenchSession[] = [];
    const orphans: WorkbenchSession[] = [];
    for (const session of visible) {
      const parent = session.parent_session_id;
      // **分支会话不折。** 它是人亲手起的、等的也是人：起完要一眼看见它在不在，停下来等你
      // 拍板时要出现在 For you 那一组里。折进原会话底下，这两件事全被藏住了——worker 能折，
      // 是因为它等的是派它的那个 agent，不是人。和原会话的关系只写在卡片上那一行出处里。
      const nestable =
        session.relation?.kind !== 'branch' &&
        Boolean(parent) &&
        parent !== session.session_id &&
        present.has(parent as string) &&
        // 自己也被置顶的那几场留在置顶区，不再折进父亲下面：同一场摆两处，人会以为是两场。
        !pins.isPinned(session.session_id);
      if (nestable) {
        const bucket = children.get(parent as string);
        if (bucket) bucket.push(session);
        else children.set(parent as string, [session]);
        continue;
      }
      // 置顶的那几场由置顶区去摆，这里只管下面那一片。
      if (pins.isPinned(session.session_id)) continue;
      if (session.origin === 'worker') orphans.push(session);
      else trunk.push(session);
    }
    return { trunkRows: trunk, childrenOf: children, orphanRows: orphans };
  }, [visible, pins]);

  /**
   * 主干拆成两区：For you（等得最久的在上）与 Everything else（按时间，服务端排好的序）。
   */
  const { forYouRows, restRows } = useMemo(() => {
    const waiting: WorkbenchSession[] = [];
    const rest: WorkbenchSession[] = [];
    for (const s of trunkRows) {
      if (forYou.infoOf(s.session_id)) waiting.push(s);
      else rest.push(s);
    }
    waiting.sort(
      (a, b) =>
        (forYou.infoOf(a.session_id)?.waitingSince ?? 0) -
        (forYou.infoOf(b.session_id)?.waitingSince ?? 0)
    );
    return { forYouRows: waiting, restRows: rest };
  }, [trunkRows, forYou]);
  /** 置顶里也挂着 For you 的有几场——For you 组标题右端注明「+ N in Pinned above」。 */
  const pinnedForYou = useMemo(
    () => pinnedRows.filter((s) => forYou.infoOf(s.session_id)).length,
    [pinnedRows, forYou]
  );

  /**
   * 这一批清单放到哪儿了。预算只喂 Everything else：For you 那几场本来就不多，而且是人
   * 来这一页最要看的，不该被截在「下一批」里。末尾那一区默认折着，折着不占名额。
   */
  const orphansVisible = orphansOpen;
  const pagedRest = useMemo(() => restRows.slice(0, shown), [restRows, shown]);
  const pagedOrphans = useMemo(
    () => (orphansVisible ? orphanRows.slice(0, Math.max(0, shown - restRows.length)) : []),
    [orphansVisible, orphanRows, shown, restRows.length]
  );
  const loadable = restRows.length + (orphansVisible ? orphanRows.length : 0);
  const loaded = pagedRest.length + pagedOrphans.length;
  const hasMore = loaded < loadable;

  useEffect(() => {
    setShown(PAGE_SIZE);
  }, [filter, days]);

  /**
   * 摆进列表的每一行：分区标题与会话卡走同一条队。
   *
   * 一场都没置顶、也没有 For you 时不长任何分区标题，整片就是一个单列清单——空着的分区
   * 标题只是噪音。末尾那一区同理：没有认不出出处的 worker 就不长那行标题。
   */
  const rows = useMemo<RailRow[]>(() => {
    const trunkWithKids = (session: WorkbenchSession, inPinned = false): RailRow[] => {
      const kids = childrenOf.get(session.session_id) ?? [];
      const expanded = expandedWorkers.has(session.session_id);
      const head: RailRow = {
        kind: 'session',
        session,
        workerCount: kids.length,
        workersExpanded: expanded,
        inPinned,
      };
      if (!kids.length || !expanded) return [head];
      // 展开之后这一组被一个框圈起来：主会话那行画上半框，子会话画两侧，末一行收底。
      return [
        { ...head, groupPos: 'head' as const },
        ...kids.map((kid, i) => ({
          kind: 'session' as const,
          session: kid,
          nested: true,
          inPinned,
          groupPos: (i === kids.length - 1 ? 'tail' : 'mid') as GroupPos,
        })),
      ];
    };

    const out: RailRow[] = [];
    if (pins.pinned.length) {
      out.push({ kind: 'pinned-header' });
      if (!pins.collapsed) out.push(...pinnedRows.flatMap((s) => trunkWithKids(s, true)));
      out.push({ kind: 'pinned-tail' });
    }
    const sectioned = pins.pinned.length > 0 || forYouRows.length > 0;
    if (forYouRows.length) {
      out.push({ kind: 'for-you-header', count: forYouRows.length, pinnedAbove: pinnedForYou });
      out.push(...forYouRows.flatMap((s) => trunkWithKids(s)));
    }
    if (sectioned && pagedRest.length) out.push({ kind: 'rest-header', count: restRows.length });
    out.push(...pagedRest.flatMap((s) => trunkWithKids(s)));
    if (orphanRows.length) {
      out.push({ kind: 'workers-header' });
      out.push(
        ...pagedOrphans.map((session) => ({ kind: 'session' as const, session, nested: true }))
      );
    }
    return out;
  }, [
    pins.pinned.length,
    pins.collapsed,
    pinnedRows,
    forYouRows,
    pinnedForYou,
    pagedRest,
    restRows.length,
    childrenOf,
    orphanRows.length,
    pagedOrphans,
    expandedWorkers,
  ]);

  /**
   * 选中那一条在这张清单里排第几行，以及它此刻在不在视野里。
   *
   * 不在视野里就在筛选区下面摆一行「Current session is below ↓」。选中那条在折起的置顶组
   * 里时同样摆：点一下先展开置顶组，再滚过去。
   */
  const virtuoso = useRef<VirtuosoHandle>(null);
  const [range, setRange] = useState<{ startIndex: number; endIndex: number } | null>(null);
  const selectedIndex = useMemo(
    () =>
      selectedId
        ? rows.findIndex((r) => r.kind === 'session' && r.session.session_id === selectedId)
        : -1,
    [rows, selectedId]
  );
  const selectedHiddenInPins =
    selectedIndex < 0 && Boolean(selectedId) && pins.collapsed && pins.isPinned(selectedId ?? '');
  const pendingScroll = useRef(false);
  const offscreen: 'above' | 'below' | null = selectedHiddenInPins
    ? 'below'
    : selectedIndex < 0 || !range
      ? null
      : selectedIndex < range.startIndex
        ? 'above'
        : selectedIndex > range.endIndex
          ? 'below'
          : null;
  const scrollToSelected = () => {
    if (selectedHiddenInPins) {
      pendingScroll.current = true;
      pins.setCollapsed(false);
      return;
    }
    if (selectedIndex >= 0) virtuoso.current?.scrollToIndex({ index: selectedIndex, align: 'center' });
  };
  // 置顶组刚被展开：等它的行摆进清单再滚
  useEffect(() => {
    if (!pendingScroll.current || selectedIndex < 0) return;
    pendingScroll.current = false;
    virtuoso.current?.scrollToIndex({ index: selectedIndex, align: 'center' });
  }, [selectedIndex]);
  const selectedForYou = selectedId ? forYou.infoOf(selectedId) : null;

  /** 可关终端那一块摊没摊开，以及勾了哪几个（默认全勾）。 */
  const [closeOpen, setCloseOpen] = useState(false);
  const [unchecked, setUnchecked] = useState<Set<string>>(new Set());
  const [closing, setClosing] = useState(false);
  const closable = forYou.closable;
  const toClose = closable.filter((r) => !unchecked.has(r.name));
  const closeChecked = async () => {
    if (!toClose.length) return;
    setClosing(true);
    try {
      const res = await closeTmuxSessions(toClose.map((r) => r.name));
      showToast(t('workbench.rail.closedTerminals', { count: res.closed }), res.failed ? 'error' : 'success');
      setCloseOpen(false);
      setUnchecked(new Set());
      forYou.refresh();
      void reload();
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e), 'error');
    } finally {
      setClosing(false);
    }
  };

  /**
   * 展开末尾那一区。
   *
   * 展开的同时先给它一批名额：主干还没摆完时，那一区的名额是 0，人点开会看到一个写着
   * 一千两百场的标题底下一条都没有。展开这一下本身就是"我要看它们"，名额跟上。
   */
  const toggleOrphans = () => {
    const opening = !orphansOpen;
    if (opening) setShown((s) => Math.max(s, restRows.length + PAGE_SIZE));
    setOrphansOpen(opening);
  };

  const toggleWorkers = (session: WorkbenchSession) => {
    setExpandedWorkers((prev) => {
      const next = new Set(prev);
      if (!next.delete(session.session_id)) next.add(session.session_id);
      return next;
    });
  };

  const handleTogglePin = async (session: WorkbenchSession) => {
    const wasPinned = pins.isPinned(session.session_id);
    try {
      await pins.toggle(session.session_id);
      // 折起来的时候置顶一场，那一场会立刻消失在眼前。说一句它去哪了。
      if (!wasPinned && pins.collapsed) {
        showToast(t('workbench.rail.pinnedToastCollapsed'), 'success');
      }
    } catch (e) {
      showToast(
        e instanceof Error ? e.message : t('workbench.errors.pinSaveFailedPlain'),
        'error'
      );
    }
  };

  /**
   * 清单头尾那两块。
   *
   * 尾巴上报这一刻放了多少、还有多少——滚动条不再是"全部会话"的长度之后，人需要另一处
   * 知道下面还有没有东西。全部放完就把这行收掉，只留原来那点留白：都摆出来了还挂着一行
   * 数字，是在报一件已经没有悬念的事。
   *
   * 用 `useMemo` 兜住：这两个组件的**身份**一变，列表会把它们整个重挂载，滚动位置跟着跳。
   */
  const listComponents = useMemo(
    () => ({
      Header: () => <div className="h-2" />,
      Footer: () =>
        hasMore ? (
          <div
            data-testid="rail-page-progress"
            className="px-2.5 pb-4 pt-2 text-center text-[11px] text-text-muted"
          >
            {t('workbench.rail.pageProgress', { shown: loaded, total: loadable })}
          </div>
        ) : (
          <div className="h-4" />
        ),
    }),
    [hasMore, loaded, loadable, t]
  );

  /**
   * 点开一场会话。
   *
   * 顺手记一笔「这一场我此刻看过了」——For you 那一条停下之后没点开过的，标题加粗，
   * 不记的话它一直是粗的。
   */
  const handleSelect = useCallback(
    (sessionId: string) => {
      views.markViewed(sessionId);
      onSelect(sessionId);
    },
    [views, onSelect]
  );

  const handleCopy = async (session: WorkbenchSession) => {
    const cmd = resumeCommand(session);
    // 这一家没有续接命令（CoreAgent）。按钮本来就不长出来，这里再拦一道：拦不住的话
    // 剪贴板里会落进一句 "null"，人粘到终端里才发现。
    if (!cmd) return;
    try {
      await navigator.clipboard.writeText(cmd);
      setCopiedId(session.session_id);
      showToast(t('workbench.rail.copied'), 'success');
      setTimeout(() => setCopiedId((cur) => (cur === session.session_id ? null : cur)), 1500);
    } catch {
      showToast(t('workbench.rail.copyFailed'), 'error');
    }
  };

  return (
    <aside className="flex h-full min-h-0 w-full flex-col border-r border-border-color bg-bg-secondary">
      <div className="shrink-0 space-y-1.5 border-b border-border-color px-2.5 pb-2.5 pt-2.5">
        {/* 搜索入口与新建挤在一行。新建从一整块实心绿降成右边一颗中性图标按钮：人来这一页
            是为了找会话、接着说话，这一屏唯一的实心绿留给 Send。 */}
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => openSearch(true)}
            data-testid="session-search-trigger"
            aria-label={t('sessionSearch.label')}
            className="flex h-7 min-w-0 flex-1 items-center gap-1.5 rounded-[8px] bg-bg-subtle px-2.5 text-[13px] text-text-muted transition-colors duration-200 hover:bg-bg-hover hover:text-text-secondary"
          >
            <Search size={14} strokeWidth={1.5} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate text-left">{t('sessionSearch.trigger')}</span>
            <kbd className="shrink-0 rounded-[4px] border border-border-color px-1 font-mono text-[11px] leading-[16px]">
              {modKey}K
            </kbd>
          </button>
          <button
            type="button"
            onClick={() => setNewOpen(true)}
            data-testid="new-session"
            aria-label={t('workbench.rail.newSession')}
            title={t('workbench.rail.newSession')}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[8px] border border-border-color text-text-secondary transition-colors duration-200 hover:bg-bg-hover hover:text-text-primary"
          >
            <Plus size={16} strokeWidth={1.5} />
          </button>
        </div>

        {/* 时间范围这一行的右端顺带放刷新：对整张清单的动作，与筛选同属「这张清单怎么摆」。 */}
        <div className="flex items-center gap-1">
          <div className="flex min-w-0 flex-1 flex-wrap gap-1">
            {DAY_FILTERS.map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDays(d)}
                aria-pressed={days === d}
                data-testid={`day-filter-${d}`}
                className={`rounded-[6px] px-2 py-[3px] text-[11px] transition-colors duration-200 ${
                  days === d ? CHIP_ON : CHIP_OFF
                }`}
              >
                {d === 0 ? t('workbench.rail.dayAll') : t('workbench.rail.dayRange', { days: d })}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => {
              void reload();
              forYou.refresh();
            }}
            disabled={loading}
            aria-label={t('workbench.rail.reload')}
            title={t('workbench.rail.reload')}
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[6px] text-text-muted transition-colors duration-200 hover:bg-bg-hover hover:text-text-primary disabled:opacity-50"
          >
            {loading ? (
              <Loader2 size={14} strokeWidth={1.5} className="animate-spin" />
            ) : (
              <RefreshCw size={14} strokeWidth={1.5} />
            )}
          </button>
        </div>

        <div className="flex flex-wrap gap-1">
          {FILTERS.map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => setFilter(id)}
              aria-pressed={filter === id}
              data-testid={`list-filter-${id}`}
              className={`flex items-center gap-1.5 rounded-[6px] px-2 py-[3px] text-[11px] transition-colors duration-200 ${
                filter === id ? CHIP_ON : CHIP_OFF
              }`}
            >
              <span>{t(FILTER_LABEL_KEY[id])}</span>
              <span className="font-mono opacity-60">{counts[id]}</span>
            </button>
          ))}
        </div>

        {/* 可关的终端：客户端已经退出、只剩一个 shell 的那几个。在等你的、在忙的都不算。
            一个都没有时这一行不出现。 */}
        {closable.length ? (
          <div data-testid="closable-terminals" className="text-[11px]">
            <button
              type="button"
              onClick={() => setCloseOpen((v) => !v)}
              aria-expanded={closeOpen}
              className="flex items-center gap-1 text-text-muted hover:text-text-secondary"
            >
              {closeOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              {t('workbench.rail.idleTerminals', { count: closable.length })}
            </button>
            {closeOpen ? (
              <div className="mt-1.5 space-y-1 rounded-[8px] border border-border-color bg-bg-primary p-2">
                {closable.map((r) => (
                  <label key={r.name} className="flex cursor-pointer items-start gap-2">
                    <input
                      type="checkbox"
                      checked={!unchecked.has(r.name)}
                      onChange={() =>
                        setUnchecked((prev) => {
                          const next = new Set(prev);
                          if (!next.delete(r.name)) next.add(r.name);
                          return next;
                        })
                      }
                      className="mt-[2px]"
                    />
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate font-mono text-text-secondary">
                        {r.name.replace(/^frago-agent-/, '')}
                      </span>
                      <span className="text-text-muted">
                        {r.last_stop_at
                          ? t('workbench.rail.idleFor', { age: shortAge(Date.parse(r.last_stop_at)) })
                          : t('workbench.rail.clientExited')}
                      </span>
                    </span>
                  </label>
                ))}
                <button
                  type="button"
                  data-testid="close-terminals"
                  disabled={!toClose.length || closing}
                  onClick={() => void closeChecked()}
                  className="mt-1 flex w-full items-center justify-center gap-1 rounded-[6px] border border-border-color px-2 py-1 text-text-secondary hover:bg-bg-hover hover:text-text-primary disabled:opacity-40"
                >
                  {closing ? <Loader2 size={11} className="animate-spin" /> : null}
                  {t('workbench.rail.closeTerminals', { count: toClose.length })}
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {/* 正在起的那一场先占一行。它摆在滚动区**外面**：这一行的意义是"你刚建的那场在
          这儿"，滚下去看不见就等于没有。会话真进了清单它自己就消失，位置随即让给真那一行。 */}
      {launch ? (
        <div className="shrink-0 px-2 pt-2">
          <div
            data-testid="rail-launch"
            data-phase={launch.phase}
            className={`flex items-center gap-2 rounded-[8px] border px-2.5 py-2 ${
              launch.phase === 'failed'
                ? 'border-accent-error bg-accent-error-10'
                : 'border-border-strong bg-bg-subtle'
            }`}
          >
            <Mail
              size={14}
              strokeWidth={2}
              className={`shrink-0 ${
                launch.phase === 'failed' ? 'text-accent-error' : 'text-text-secondary'
              }`}
            />
            <div className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-[12px] font-medium text-text-primary">
                {launch.text || t('workbench.launch.railTitle')}
              </span>
              <span className="truncate text-[11px] text-text-muted">
                {launch.phase === 'failed'
                  ? t('workbench.launch.railFailed')
                  : launch.phase === 'claiming'
                    ? t('workbench.launch.railClaiming', { name: launch.agentName })
                    : t('workbench.launch.railWarming', { name: launch.agentName })}
              </span>
            </div>
            {launch.phase === 'failed' ? (
              <button
                type="button"
                data-testid="rail-launch-dismiss"
                onClick={() => onDismissLaunch?.()}
                aria-label={t('workbench.launch.dismiss')}
                className="shrink-0 rounded-[6px] p-0.5 text-text-muted hover:text-text-primary"
              >
                <X size={13} />
              </button>
            ) : (
              <Loader2 size={13} className="shrink-0 animate-spin text-text-muted" />
            )}
          </div>
        </div>
      ) : null}

      {/* 选中那条不在视野里：说一声它在哪，点一下滚过去。行尾只跟 For you 或 Sending。 */}
      {offscreen ? (
        <div className="shrink-0 px-2 pt-2">
          <button
            type="button"
            data-testid="current-below"
            data-direction={offscreen}
            onClick={scrollToSelected}
            className="flex w-full items-center gap-1.5 rounded-[8px] border border-border-color px-2.5 py-1.5 text-left text-[11px] text-text-secondary hover:bg-bg-hover"
          >
            {offscreen === 'above' ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
            <span className="min-w-0 flex-1 truncate">
              {offscreen === 'above'
                ? t('workbench.rail.currentAbove')
                : t('workbench.rail.currentBelow')}
            </span>
            {sendingId && sendingId === selectedId ? (
              <SendingChip />
            ) : selectedForYou ? (
              <ForYouChip emphasis={selectedForYou.emphasis} />
            ) : null}
          </button>
        </div>
      ) : null}

      {/* 列表区：Virtuoso 只渲染视口内卡片。装载时给骨架屏占位，有数据才展示窗口化列表。 */}
      <div className="min-h-0 flex-1">
        {/* 报错摆在清单**上面**而不是替掉清单：定时重取偶尔失手时，手上那份清单仍
            比一句错误有用得多。 */}
        {error && (
          <p className="m-3 rounded-[6px] bg-bg-subtle px-2.5 py-2 text-[12px] text-text-secondary">
            {error}
          </p>
        )}
        {loading && !visible.length ? (
          <div className="animate-pulse px-2 pt-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="mb-0.5 w-full rounded-[8px] px-2.5 py-2">
                <div className="mb-2 h-3.5 w-2/3 rounded bg-bg-hover" />
                <div className="h-2.5 w-1/2 rounded bg-bg-hover" />
              </div>
            ))}
          </div>
        ) : !rows.length ? (
          <p className="px-3 py-8 text-center text-[12px] text-text-muted">
            {filter === 'for-you' ? t('workbench.rail.emptyForYou') : t('workbench.rail.empty')}
          </p>
        ) : (
          /* 置顶区与其余那一片共用同一条队、同一条滚动条。 */
          <Virtuoso
            ref={virtuoso}
            data={rows}
            initialItemCount={Math.min(rows.length, 30)}
            components={listComponents}
            rangeChanged={setRange}
            /* 滚到底就续上下一批。人已经滚到底了，那一下就是"还要看"本身。 */
            endReached={() => {
              if (hasMore) setShown((s) => s + PAGE_SIZE);
            }}
            /* 拿不到行也要给得出键：清单重算时行数会变短，窗口化列表可能还按上一批的位置来问。 */
            computeItemKey={(index, row) =>
              !row ? `row-${index}` : row.kind === 'session' ? row.session.session_id : row.kind
            }
            itemContent={(_, row) => {
              // 同上：位置对不上时给一个空位，NEVER 伸手去读一个不在的行。
              if (!row) return null;
              if (row.kind === 'pinned-header') {
                /* 置顶整组一块略浅的底加一圈发丝描边，这是它的上半框。标题正常字重、正文色，
                   右端写「Always on top」——不用绿，不用大写。 */
                return (
                  <div className="px-2 pt-2">
                    <button
                      type="button"
                      onClick={() => pins.setCollapsed(!pins.collapsed)}
                      aria-expanded={!pins.collapsed}
                      data-testid="pinned-header"
                      className={`flex w-full items-center gap-1.5 border border-border-color bg-bg-subtle px-2.5 py-1.5 text-[12px] text-text-primary transition-colors duration-200 hover:bg-bg-hover ${
                        pins.collapsed ? 'rounded-[8px]' : 'rounded-t-[8px] border-b-0'
                      }`}
                    >
                      {pins.collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
                      <Pin size={11} fill="currentColor" className="text-text-primary" />
                      <span>{t('workbench.rail.pinnedHeader')}</span>
                      <span className="font-mono text-[11px] text-text-muted">{pinnedRows.length}</span>
                      <span className="flex-1" />
                      <span className="text-[11px] text-text-muted">{t('workbench.rail.alwaysOnTop')}</span>
                    </button>
                  </div>
                );
              }
              if (row.kind === 'pinned-tail') {
                return pins.collapsed ? (
                  <div className="h-2" />
                ) : (
                  <div className="px-2 pb-2">
                    <div className="h-1.5 rounded-b-[8px] border border-t-0 border-border-color bg-bg-subtle" />
                  </div>
                );
              }
              if (row.kind === 'for-you-header' || row.kind === 'rest-header') {
                const forYouHead = row.kind === 'for-you-header';
                return (
                  <div
                    data-testid={forYouHead ? 'for-you-header' : 'rest-header'}
                    className="flex items-center gap-1.5 px-2.5 pb-1 pt-3 text-[11px] text-text-muted"
                  >
                    <span className="font-medium text-text-secondary">
                      {forYouHead ? t('workbench.forYou.label') : t('workbench.rail.everythingElse')}
                    </span>
                    <span className="font-mono opacity-70">{row.count}</span>
                    <span className="flex-1" />
                    {forYouHead && row.pinnedAbove ? (
                      <span>{t('workbench.rail.inPinnedAbove', { n: row.pinnedAbove })}</span>
                    ) : null}
                  </div>
                );
              }
              if (row.kind === 'workers-header') {
                return (
                  <button
                    type="button"
                    onClick={toggleOrphans}
                    aria-expanded={orphansVisible}
                    data-testid="workers-header"
                    className="flex w-full items-center gap-1.5 px-2.5 pb-1 pt-3 text-[11px] text-text-muted transition-colors duration-200 hover:text-text-secondary"
                  >
                    {orphansVisible ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    <span>{t('workbench.rail.orphanWorkersHeader')}</span>
                    <span className="font-mono opacity-70">{orphanRows.length}</span>
                  </button>
                );
              }
              const session = row.session;
              const pos = row.groupPos;
              /* worker 框的三段：1px、清单的分隔线色、8px 圆角。 */
              const box =
                pos === 'head'
                  ? 'rounded-t-[8px] border border-b-0 border-border-color'
                  : pos === 'mid'
                    ? 'border-x border-border-color'
                    : pos === 'tail'
                      ? 'rounded-b-[8px] border border-t-0 border-border-color'
                      : '';
              const item = (
                <div className={row.nested && !pos ? 'pl-6 pr-2' : 'px-2'}>
                  <div className={box} data-group={pos}>
                    <div className={row.nested && pos ? 'pl-4' : ''}>
                      {/* 开在 tmux 里的那几场外面一圈流光（主人 09-24 定：保留）。 */}
                      <MaybeLive live={views.isInTmux(session)}>
                        <SessionItem
                          session={session}
                          selected={session.session_id === selectedId}
                          copied={copiedId === session.session_id}
                          pinned={pins.isPinned(session.session_id)}
                          forYou={forYou.infoOf(session.session_id)}
                          sending={sendingId === session.session_id}
                          nested={row.nested}
                          branchOf={
                            session.relation?.kind === 'branch' && session.parent_session_id
                              ? {
                                  id: session.parent_session_id,
                                  title: titleOf.get(session.parent_session_id) ?? null,
                                }
                              : null
                          }
                          workerCount={row.workerCount}
                          workersExpanded={row.workersExpanded}
                          onSelect={handleSelect}
                          onCopy={handleCopy}
                          onTogglePin={handleTogglePin}
                          onToggleWorkers={toggleWorkers}
                        />
                      </MaybeLive>
                    </div>
                  </div>
                  {/* 行与行之间的间隔。一组之内不留这道缝，留了框就断成几截。 */}
                  {pos === 'head' || pos === 'mid' ? null : <div className="h-2" />}
                </div>
              );
              /* 置顶那一块的中段：两侧发丝线，底色与标题同一块。 */
              return row.inPinned ? (
                <div className="px-2">
                  <div className="border-x border-border-color bg-bg-subtle pt-0.5">{item}</div>
                </div>
              ) : (
                item
              );
            }}
          />
        )}
      </div>

      <div className="shrink-0 border-t border-border-color px-2.5 py-2 font-mono text-[11px] leading-[1.6] text-text-muted">
        {t('workbench.rail.summary', {
          total: sessions.length,
          cc: familyCounts.cc,
          oc: familyCounts.oc,
          cx: familyCounts.cx,
          ca: familyCounts.ca,
        })}
      </div>

      {/* 建完就交出去。等编号、反复重取清单、把中栏切过去，这些事由页面那边的启动状态
          统一管（见 `useSessionLaunch`）。 */}
      <NewSessionModal
        isOpen={newOpen}
        onClose={() => setNewOpen(false)}
        onCreated={(pending, text) => onCreated?.(pending, text)}
      />
    </aside>
  );
}
