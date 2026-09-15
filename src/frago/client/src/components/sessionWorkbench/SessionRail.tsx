/**
 * SessionRail — 左栏：新建会话、搜索、时间范围、状态筛选、会话清单、底部汇总。
 *
 * 三家（Claude Code / opencode / codex）的会话在核心数据层就合并排好了，这里不重排。
 *
 * **清单是两层的：主干是主会话，frago 派出去的 worker 折在派活的那一场下面。** 本机两千多
 * 场会话里一千五百场是 worker，摊平在同一列里，人找自己刚才谈的那一场要一直往下翻。判据
 * 全在服务端（每张卡带着「谁开的」与「谁派的活」两个字段），这里只负责摆位置：派活的那场
 * 也在清单里就折进去，认不出出处的收进末尾那一区，其余留在主干。搜索时整棵树摊开——那一刻
 * 人是在找某一句话，命中的要是一个折起来的 worker，折着就等于没搜到。
 *
 * **筛选是两个维度，不是一个。** 状态答「现在什么情况」，时间范围答「哪一段时间的」，
 * 两者并存、互不替代。按来源筛的那一维不在这里——一千多场 Claude Code 会话摆在一起，
 * 知道它们都来自 Claude Code 没有任何用；来源仍在每张卡上看得见，改由底部汇总报两家各几场。
 *
 * **搜索有两条腿。** 标题、目录、编号在本地即时筛，敲一个字就有反应；会话内容（提示词
 * 与 agent 回复正文）由服务端搜，慢一拍，所以它自己报进度、自己报哪里没搜全。两条的
 * 结果取并集，命中的那几场把命中的原话摆到卡片上。
 *
 * **状态与摘要一个字都不在这里推导。** 服务端已经判完四档、填好两格摘要，界面照着显示。
 * 摆两处判据迟早各走各的，那时中栏和左栏会对同一场会话说两种话。
 *
 * **选中态不用左侧竖条。** 整行换成品牌绿淡底、标题转品牌绿。单边竖条是肌肉记忆，
 * 不是设计决策。绿环后来也去掉了：淡底加标题转绿已经足够把那一行从一列灰字里分出来。
 *
 * **颜色一律走 CSS 变量。** 明暗两套主题各有一份品牌绿，写死色值会让其中一套失真。
 *
 * 底部汇总只报已经发生的绝对数：共几场、两家各几场。没有分母，也不该有。
 *
 * **列表走窗口化渲染。** 全量会话可能上千场，用 Virtuoso 只渲染视口内可见的卡片。
 *
 * **置顶区是一片自己说了算的地方。** 名单存在服务端（见 `useSessionPins`），次序照置顶
 * 的次序而不是活动时刻，数量不设上限，整片可以折起来。它**不跟状态与时间范围走**——那
 * 两道答的是「翻哪一段、翻哪一档」，而置顶答的是「这几场我随时要回来」，点一下「7 天」
 * 就让人挑出来的那几场消失，是把筛选的语义套到了一个不该被筛的地方。搜索另说：那一刻人
 * 是在找某一场，置顶区跟着筛才不会答非所问。
 *
 * 一场都没置顶时不长分区标题，整片仍是从前那个单列清单——空着的分区标题只是噪音。
 *
 * **分组把主干按主题拆成几区。** 标签与每个标签下的会话编号存在服务端（见
 * `useSessionGroups`）。一个标签都没有时不长任何分区标题，清单还是从前那样。有了标签，
 * 主干拆成「未分组」加各标签几区：未分组排最前——新开的会话都落在这，人一眼要看见它们；
 * 各标签按组里最近一场的活动时刻排，正在推进的主题在上面。各标签默认折起，折着时标题上
 * 的数就是全部线索。置顶的那几场留在置顶区、worker 仍折在派活的那场下面，都不进分区。
 *
 * **分区标题是列表里的普通一行，不是窗口化列表的 group header。** group header 的位置要
 * 等列表量完每一行的高度才算得出来，量完之前那两行标题一个都不在页面上——真实浏览器里
 * 撞见过整片清单已经摆好、标题还没出现。标题上坐着折叠开关，它不该等任何东西。
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Virtuoso } from 'react-virtuoso';
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  Mail,
  Pin,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import Modal from '@/components/ui/Modal';
import SessionItem, { resumeCommand } from './SessionItem';
import NewSessionModal from './NewSessionModal';
import GroupPicker from './GroupPicker';
import { useSessionPins } from '@/hooks/useSessionPins';
import { UNGROUPED, useSessionGroups, type GroupTag } from '@/hooks/useSessionGroups';
import { useSessionViews } from '@/hooks/useSessionViews';
import { LiveBorder, LiveRing } from '@/components/ui/LiveEdge';
import type { PendingLaunch } from '@/hooks/useAgentClients';
import type { SessionLaunch } from '@/hooks/useSessionLaunch';
import {
  activityTs,
  DAY_OPTIONS,
  MIN_CONTENT_QUERY,
  STATUS_LABEL_KEY,
  type DayRange,
  type StatusFilter,
  type WorkbenchSession,
  type WorkbenchSessionsState,
} from '@/hooks/useWorkbenchSessions';

/**
 * 品牌绿承担选中、当前、活跃。三处共用一套，别处不许再造。
 *
 * **筛选那两行不在这三处之内。** 时间范围与状态是页面自己的操作面，不是数据。
 * 五个筛选档同时用品牌绿点亮，会让页面上常年挂着两块绿——真正需要被看见的
 * 「哪一场会话被选中了」「哪一场在跑」反而没有地方可去。所以选中的筛选档换成
 * 中性填充加一档字重，颜色留给数据。
 */
const ACCENT_TEXT = 'text-accent-primary';

/** 筛选档选中态：中性填充 + 字重。整块换底，不靠任何单边色条。 */
const CHIP_ON = 'bg-bg-active text-text-primary font-medium';
const CHIP_OFF = 'text-text-muted hover:bg-bg-hover hover:text-text-secondary';

/** 四档筛选加一个全部。次序与判定顺序一致，看的人不必再学一套排列。 */
const FILTERS: StatusFilter[] = ['all', 'running', 'error', 'done', 'idle'];

/**
 * 一次往清单里放多少场。滚到底再放下一批。
 *
 * **窗口化渲染解决的是"画多少个节点"，不是"这条清单有多长"。** 时间范围默认不限，本机
 * 七百多场会话一次全摆进去，滚动条被压成一道几乎没有长度的细缝——人拖一下就滑过几百场，
 * 想回到刚才看的位置只能重新找。把清单切成一批一批之后，滚动条的长度重新与"我看过多少"
 * 对得上，而不是与"这台机器上一共存过多少场"对得上。
 *
 * 五十场是一屏半到两屏，滚到底那一下续上下一批，人不必去点任何东西。
 */
const PAGE_SIZE = 50;

/** 筛选档的**词表键**。取字在渲染时做，换语言这一行跟着变。 */
const FILTER_LABEL_KEY: Record<StatusFilter, string> = {
  all: 'workbench.rail.filterAll',
  ...STATUS_LABEL_KEY,
};

/** 时间范围：不限，加四档。0 排在最前，与状态那一行的「全部」对齐。 */
const DAY_FILTERS: DayRange[] = [0, ...DAY_OPTIONS];

/**
 * 每一档点的颜色。与清单里那份保持一致（见 SessionItem 的同名表）：只有在跑与出错
 * 带颜色，已完成与停着用两级灰。图例与清单说的必须是同一套，否则人按图例去清单里找
 * 蓝点，会一个都找不到。
 */
const STATUS_DOT: Record<string, string> = {
  running: 'bg-accent-primary',
  error: 'bg-accent-error',
  done: 'bg-text-secondary',
  idle: 'bg-text-dim',
};

/**
 * 列表里的一行：分区标题，或一张会话卡。
 *
 * 会话卡带着它在这棵树里的位置：`nested` 是"挂在上面那一行下面的 worker"，
 * `workerCount` 是这一行自己派出去过几个。两样都由 `rows` 一次算完，卡片不自己推导。
 */
type RailRow =
  | { kind: 'pinned-header' }
  | { kind: 'rest-header' }
  | { kind: 'workers-header' }
  /** 一个分区的标题。`tag` 为 null 是「未分组」那一区。 */
  | {
      kind: 'group-header';
      key: string;
      tag: GroupTag | null;
      count: number;
      open: boolean;
      /** 这一区里有你还没回去看过的新回复。 */
      unread: boolean;
      /** 这一区有一场此刻开在 tmux 里。 */
      inTmux: boolean;
    }
  /** 这一区这一批没放完，还剩几场。 */
  | { kind: 'section-more'; key: string; remaining: number }
  | {
      kind: 'session';
      session: WorkbenchSession;
      nested?: boolean;
      workerCount?: number;
      workersExpanded?: boolean;
      groupPos?: GroupPos;
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
}

export default function SessionRail({
  state,
  selectedId,
  onSelect,
  launch = null,
  onCreated,
  onDismissLaunch,
}: SessionRailProps) {
  const {
    sessions,
    visible,
    searched,
    counts,
    loading,
    error,
    search,
    setSearch,
    status,
    setStatus,
    days,
    setDays,
    content,
    reload,
  } = state;
  const { t } = useTranslation();
  const showToast = useAppStore((s) => s.showToast);
  const pins = useSessionPins();
  const groups = useSessionGroups();
  const views = useSessionViews();
  /** 「放进分组」那一小块开在哪一场、按钮在屏幕上的哪。 */
  const [picker, setPicker] = useState<{ session: WorkbenchSession; rect: DOMRect } | null>(null);
  /** 等人确认要删的那个标签。 */
  const [deleting, setDeleting] = useState<GroupTag | null>(null);
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
    for (const s of sessions) {
      if (s.family === 'claude-code') cc += 1;
      else if (s.family === 'opencode') oc += 1;
      else if (s.family === 'codex') cx += 1;
    }
    return { cc, oc, cx };
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
    return searched
      .filter((s) => rank.has(s.session_id))
      .sort((a, b) => rank.get(a.session_id)! - rank.get(b.session_id)!);
  }, [searched, pins.pinned]);

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
   *
   * **搜索的时候整棵树摊开。** 那一刻人是在找某一句话，命中的要是一个折起来的 worker，
   * 折着就等于没搜到。
   */
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
      const nestable =
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

  const searching = search.trim().length > 0;

  /**
   * 主干按分组拆成几区。一个标签都没有时为空，清单照从前那样摆。
   *
   * 「未分组」排最前：新开的会话都落在这，人一眼要看见它们。各标签按组里最近一场的活动
   * 时刻排——主干本来就按活动时刻倒序，每组第一场就是最近那场——正在推进的主题在上面；
   * 一场都没有的组排最后，照建的次序。
   *
   * 筛了状态、时间范围或在搜索时，一场都不剩的区不长标题：点「在跑」之后摆着十几行「0」
   * 只是噪音。什么都没筛时空组照样摆出来——人刚建的标签得看得见。
   */
  const grouping = groups.tags.length > 0;
  const filtering = searching || status !== 'all' || days !== 0;
  const { tags: groupTags, groupOf } = groups;
  const sections = useMemo(() => {
    if (!grouping) return [];
    const known = new Set(groupTags.map((tag) => tag.id));
    const buckets = new Map<string, WorkbenchSession[]>();
    const ungrouped: WorkbenchSession[] = [];
    for (const session of trunkRows) {
      const tagId = groupOf(session.session_id);
      if (tagId && known.has(tagId)) {
        const bucket = buckets.get(tagId);
        if (bucket) bucket.push(session);
        else buckets.set(tagId, [session]);
      } else {
        ungrouped.push(session);
      }
    }
    const latest = (list: WorkbenchSession[]) => (list.length ? activityTs(list[0]) : -1);
    const tagged = groupTags
      .map((tag) => ({ key: tag.id, tag: tag as GroupTag | null, sessions: buckets.get(tag.id) ?? [] }))
      .sort((a, b) => latest(b.sessions) - latest(a.sessions));
    return [{ key: UNGROUPED, tag: null as GroupTag | null, sessions: ungrouped }, ...tagged].filter(
      (section) => section.sessions.length > 0 || (section.tag !== null && !filtering)
    );
  }, [grouping, groupTags, groupOf, trunkRows, filtering]);

  /** 这一区摊没摊开。搜索时整片摊开——命中的要是折在某一区里，折着就等于没搜到。 */
  const { isCollapsed } = groups;
  const sectionOpen = useCallback(
    (key: string) => searching || !isCollapsed(key),
    [searching, isCollapsed]
  );

  /**
   * 这一批清单放到哪儿了。
   *
   * **预算先喂主干，主干摆完才轮到末尾那一区。** 那一区默认折着，折着的时候一条都不渲染，
   * 也就不该占掉这一批的名额——否则人还没看见任何 worker，主干却已经被截断了。
   *
   * 换一个筛选档、改一次搜索词，清单换成了另一批会话，这时候还停在第三页是答非所问：
   * 那三页是上一批的进度。所以那三样一变就回到第一页（见下面的重置）。置顶不在此列——
   * 置顶区不受分页管，它本来就是人自己挑出来的几场，摆在最上面。
   */
  const orphansVisible = orphansOpen || searching;
  /**
   * 主干里这一刻摊开着的那几场。分了组就只算摊开的那几区——折着的区一场都不渲染，
   * 不该占掉这一批的名额。
   */
  const openTrunk = useMemo(
    () =>
      grouping ? sections.flatMap((s) => (sectionOpen(s.key) ? s.sessions : [])) : trunkRows,
    [grouping, sections, sectionOpen, trunkRows]
  );
  const pagedTrunk = useMemo(() => openTrunk.slice(0, shown), [openTrunk, shown]);
  const pagedOrphans = useMemo(
    () => (orphansVisible ? orphanRows.slice(0, Math.max(0, shown - openTrunk.length)) : []),
    [orphansVisible, orphanRows, shown, openTrunk.length]
  );
  /** 这一刻还能往下放多少场，与已经放了多少场。底下那行进度报的就是这两个数。 */
  const loadable = openTrunk.length + (orphansVisible ? orphanRows.length : 0);
  const loaded = pagedTrunk.length + pagedOrphans.length;
  const hasMore = loaded < loadable;

  useEffect(() => {
    setShown(PAGE_SIZE);
  }, [search, status, days]);

  /**
   * 摆进列表的每一行：分区标题与会话卡走同一条队。
   *
   * 分区标题做成**普通一行**而不是窗口化列表的 group header：group header 的位置要等
   * 列表量完每一行的高度才算得出来，量完之前那两行标题一个都不在页面上——真实浏览器里
   * 就撞见过整片清单已经摆好、标题还没出现。标题是折叠开关所在，它不该等任何东西。
   *
   * 一场都没置顶时连标题都不长，整片就是从前那个单列清单——空着的分区标题只是噪音。
   * 末尾那一区同理：没有认不出出处的 worker 就不长那行标题。
   */
  const rows = useMemo<RailRow[]>(() => {
    const trunkWithKids = (session: WorkbenchSession): RailRow[] => {
      const kids = childrenOf.get(session.session_id) ?? [];
      const expanded = searching || expandedWorkers.has(session.session_id);
      const head: RailRow = {
        kind: 'session',
        session,
        workerCount: kids.length,
        workersExpanded: expanded,
      };
      if (!kids.length || !expanded) return [head];
      // 展开之后这一组被一个框圈起来：主会话那行画上半框，子会话画两侧，末一行收底。
      return [
        { ...head, groupPos: 'head' as const },
        ...kids.map((kid, i) => ({
          kind: 'session' as const,
          session: kid,
          nested: true,
          groupPos: (i === kids.length - 1 ? 'tail' : 'mid') as GroupPos,
        })),
      ];
    };

    let body: RailRow[];
    if (!grouping) {
      body = pagedTrunk.flatMap(trunkWithKids);
    } else {
      // 名额按分区的先后依次用：前一区放完才轮到下一区，与不分组时"一批一批往下放"是同一件事。
      let budget = shown;
      body = [];
      for (const section of sections) {
        const open = sectionOpen(section.key);
        body.push({
          kind: 'group-header',
          key: section.key,
          tag: section.tag,
          count: section.sessions.length,
          open,
          // 折起来的一区，里面的卡一张都不在页面上，这两件事只能由标题替它们说。
          unread: section.sessions.some(views.isUnread),
          inTmux: section.sessions.some(views.isInTmux),
        });
        if (!open) continue;
        const take = section.sessions.slice(0, Math.max(0, budget));
        budget -= take.length;
        body.push(...take.flatMap(trunkWithKids));
        // 这一区没放完就说一声还剩几场：它下面紧跟着别的分区标题，不说的话人会以为
        // 这一区就这么多。
        if (take.length < section.sessions.length) {
          body.push({
            kind: 'section-more',
            key: section.key,
            remaining: section.sessions.length - take.length,
          });
        }
      }
    }
    const tail: RailRow[] = orphanRows.length
      ? [
          { kind: 'workers-header' as const },
          ...pagedOrphans.map((session) => ({
            kind: 'session' as const,
            session,
            nested: true,
          })),
        ]
      : [];

    if (!pins.pinned.length) return [...body, ...tail];
    return [
      { kind: 'pinned-header' as const },
      // 置顶的那几场同样带着自己那一叠：置顶只改"摆在哪儿"，不改"它底下有没有东西"。
      ...(pins.collapsed ? [] : pinnedRows.flatMap(trunkWithKids)),
      // 分了组的话下面紧跟着各分区标题，再长一行「其余」是多说一遍。
      ...(grouping ? [] : [{ kind: 'rest-header' as const }]),
      ...body,
      ...tail,
    ];
  }, [
    pins.pinned.length,
    pins.collapsed,
    pinnedRows,
    pagedTrunk,
    childrenOf,
    orphanRows.length,
    pagedOrphans,
    expandedWorkers,
    searching,
    grouping,
    sections,
    sectionOpen,
    shown,
    views,
  ]);

  /**
   * 展开末尾那一区。
   *
   * 展开的同时先给它一批名额：主干还没摆完时，那一区的名额是 0，人点开会看到一个写着
   * 一千两百场的标题底下一条都没有。展开这一下本身就是"我要看它们"，名额跟上。
   */
  const toggleOrphans = () => {
    const opening = !orphansOpen;
    if (opening) setShown((s) => Math.max(s, openTrunk.length + PAGE_SIZE));
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

  const openPicker = useCallback((session: WorkbenchSession, anchor: HTMLElement) => {
    setPicker({ session, rect: anchor.getBoundingClientRect() });
  }, []);
  const closePicker = useCallback(() => setPicker(null), []);

  /**
   * 把这场放进某个组，或移出分组。
   *
   * 放进去之后这一场多半就从眼前消失了——它去了另一区，那一区可能还折着。说一句它去哪了。
   */
  const moveTo = async (session: WorkbenchSession, tag: GroupTag | null) => {
    setPicker(null);
    try {
      await groups.assign(session.session_id, tag ? tag.id : null);
      showToast(
        tag
          ? t('workbench.rail.groupMovedToast', { name: tag.name })
          : t('workbench.rail.groupRemovedToast'),
        'success'
      );
    } catch (e) {
      showToast(
        e instanceof Error ? e.message : t('workbench.errors.groupSaveFailedPlain'),
        'error'
      );
    }
  };

  /** 建一个标签并把这场放进去。建不成就抛，浮层留着让人改名重试。 */
  const createAndMove = async (session: WorkbenchSession, name: string) => {
    const tag = await groups.createTag(name);
    await moveTo(session, tag);
  };

  const confirmDelete = async () => {
    const tag = deleting;
    setDeleting(null);
    if (!tag) return;
    try {
      await groups.deleteTag(tag.id);
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e), 'error');
    }
  };

  const handleRunAi = async () => {
    try {
      await groups.runAi();
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e), 'error');
    }
  };

  /**
   * AI 那一趟跑完时报一句结果。
   *
   * 只在"这个页面看着它从在跑变成跑完"时报：开页面时它早就跑完了的那一趟，人没在等，
   * 报出来是在说一件跟眼下无关的旧事。
   */
  const aiJob = groups.aiJob;
  const wasRunning = useRef(aiJob.running);
  useEffect(() => {
    if (wasRunning.current && !aiJob.running) {
      if (aiJob.error) {
        showToast(t('workbench.rail.groupAiFailed', { error: aiJob.error }), 'error');
      } else if (!aiJob.total) {
        showToast(t('workbench.rail.groupAiNothing'), 'success');
      } else {
        showToast(
          t('workbench.rail.groupAiDone', { assigned: aiJob.assigned, tags: aiJob.created_tags }),
          'success'
        );
      }
    }
    wasRunning.current = aiJob.running;
  }, [aiJob, showToast, t]);

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
   * 顺手记一笔「这一场我此刻看过了」——那个绿圈是拿这个时刻与会话最后一句回复比出来的，
   * 不记的话它永远不灭。
   */
  const handleSelect = useCallback(
    (sessionId: string) => {
      views.markViewed(sessionId);
      onSelect(sessionId);
    },
    [views, onSelect]
  );

  const handleCopy = async (session: WorkbenchSession) => {
    try {
      await navigator.clipboard.writeText(resumeCommand(session));
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
        {/* 新建会话是一行，不是一整块实心色。整条侧栏最抢眼的东西不该是一颗按钮——
            人来这一页是为了找会话，不是为了建会话。 */}
        <button
          type="button"
          onClick={() => setNewOpen(true)}
          data-testid="new-session"
          className="flex h-8 w-full items-center gap-2 rounded-[8px] px-2.5 text-[13px] font-semibold bg-[var(--accent-primary)] text-[var(--text-on-accent)] transition-opacity duration-200 hover:opacity-90"
        >
          <Plus size={16} strokeWidth={1.5} className="shrink-0" />
          <span>{t('workbench.rail.newSession')}</span>
        </button>

        <div className="flex items-center gap-1.5">
          <div className="flex h-8 min-w-0 flex-1 items-center gap-1.5 rounded-[8px] bg-bg-subtle px-2.5 ring-1 ring-inset ring-transparent focus-within:ring-border-strong">
            <Search size={14} strokeWidth={1.5} className="shrink-0 text-text-muted" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('workbench.rail.searchPlaceholder')}
              aria-label={t('workbench.rail.searchLabel')}
              className="w-full min-w-0 bg-transparent text-[13px] text-text-primary outline-none placeholder:text-text-muted"
            />
            {content.searching ? (
              <Loader2 size={13} className="shrink-0 animate-spin text-text-muted" />
            ) : null}
            {search ? (
              <button
                type="button"
                onClick={() => setSearch('')}
                aria-label={t('workbench.rail.clearSearch')}
                className="shrink-0 text-text-muted hover:text-text-primary"
              >
                <X size={13} />
              </button>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => void reload()}
            disabled={loading}
            aria-label={t('workbench.rail.reload')}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] text-text-muted transition-colors duration-200 hover:bg-bg-hover hover:text-text-primary disabled:opacity-50"
          >
            {loading ? (
              <Loader2 size={14} strokeWidth={1.5} className="animate-spin" />
            ) : (
              <RefreshCw size={14} strokeWidth={1.5} />
            )}
          </button>
          {/* AI 分组只在人按下去时跑：整理这件事人要看着。只动还没分组的主会话。 */}
          <button
            type="button"
            onClick={() => void handleRunAi()}
            disabled={aiJob.running}
            aria-label={t('workbench.rail.groupAiHint')}
            title={t('workbench.rail.groupAiHint')}
            data-testid="group-ai"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] text-text-muted transition-colors duration-200 hover:bg-bg-hover hover:text-text-primary disabled:opacity-50"
          >
            {aiJob.running ? (
              <Loader2 size={14} strokeWidth={1.5} className="animate-spin" />
            ) : (
              <Sparkles size={14} strokeWidth={1.5} />
            )}
          </button>
        </div>

        <div className="flex flex-wrap gap-1">
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

        <div className="flex flex-wrap gap-1">
          {FILTERS.map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => setStatus(id)}
              aria-pressed={status === id}
              data-testid={`status-filter-${id}`}
              className={`flex items-center gap-1.5 rounded-[6px] px-2 py-[3px] text-[11px] transition-colors duration-200 ${
                status === id ? CHIP_ON : CHIP_OFF
              }`}
            >
              {/* 点保留各档的语义色：那是数据，不是操作面。 */}
              {id === 'all' ? null : <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[id]}`} />}
              <span>{t(FILTER_LABEL_KEY[id])}</span>
              <span className="font-mono opacity-60">{counts[id]}</span>
            </button>
          ))}
        </div>

        {/* 内容检索比敲字慢一拍，所以它自己报进度。没搜到就明说没搜到，NEVER 让人
            对着一份只按标题筛出来的清单以为"内容里也没有"。 */}
        {search.trim().length >= MIN_CONTENT_QUERY ? (
          <p data-testid="content-search-status" className="text-[11px] text-text-muted">
            {content.error
              ? content.error
              : content.searching
                ? t('workbench.rail.contentSearching')
                : t('workbench.rail.contentHits', { n: content.matches.size })}
          </p>
        ) : null}
        {/* AI 在跑时一直报它走到哪：一批要几十秒，不报的话那颗转圈看起来像卡住了。 */}
        {aiJob.running ? (
          <p data-testid="group-ai-status" className="text-[11px] text-text-muted">
            {aiJob.phase === 'tags'
              ? t('workbench.rail.groupAiDrafting')
              : t('workbench.rail.groupAiProgress', { done: aiJob.done, total: aiJob.total })}
          </p>
        ) : null}
        {content.warnings.map((warning) => (
          <p key={warning} className="text-[11px] text-text-secondary">
            {warning}
          </p>
        ))}
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
                : 'border-border-accent bg-accent-primary-10'
            }`}
          >
            <Mail
              size={14}
              strokeWidth={2}
              className={`shrink-0 ${
                launch.phase === 'failed' ? 'text-accent-error' : 'text-accent-primary'
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
              <Loader2 size={13} className="shrink-0 animate-spin text-accent-primary" />
            )}
          </div>
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
            {t('workbench.rail.empty')}
          </p>
        ) : (
          /* 置顶区与其余那一片共用同一条队、同一条滚动条。两个列表并排摆的话，置顶那一片
             要么自己不窗口化（置顶数不设上限，迟早卡），要么各滚各的（两条滚动条挨着，
             没人分得清该滚哪条）。 */
          <Virtuoso
            data={rows}
            initialItemCount={Math.min(rows.length, 30)}
            /* 滚动容器的内容不许贴着容器上下沿。顶上 8px 让第一张卡与筛选区之间有
               一道呼吸，底下 16px 让最后一张滚到底时不是被硬切在边框上。 */
            components={listComponents}
            /* 滚到底就续上下一批。不摆"加载更多"按钮：人已经滚到底了，那一下就是
               "还要看"本身，再让他点一次是白让他动一次手。 */
            endReached={() => {
              if (hasMore) setShown((s) => s + PAGE_SIZE);
            }}
            /* 拿不到行也要给得出键。清单重算时行数会变短，而窗口化列表可能还按上一批的
               位置来问键——问到一个已经不在的位置，这里要是伸手去读它，整页会当场抛错、
               整棵界面被卸掉，人看到的是一片空白。 */
            computeItemKey={(index, row) =>
              !row
                ? `row-${index}`
                : row.kind === 'session'
                ? row.session.session_id
                : row.kind === 'group-header'
                  ? `group:${row.key}`
                  : row.kind === 'section-more'
                    ? `more:${row.key}`
                    : row.kind
            }
            itemContent={(_, row) => {
              // 同上：位置对不上时给一个空位，NEVER 伸手去读一个不在的行。
              if (!row) return null;
              if (row.kind === 'pinned-header') {
                return (
                  <button
                    type="button"
                    onClick={() => pins.setCollapsed(!pins.collapsed)}
                    aria-expanded={!pins.collapsed}
                    data-testid="pinned-header"
                    className="flex w-full items-center gap-1.5 px-2.5 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-text-muted transition-colors duration-200 hover:text-text-secondary"
                  >
                    {pins.collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
                    <Pin size={11} fill="currentColor" className={ACCENT_TEXT} />
                    <span className={ACCENT_TEXT}>{t('workbench.rail.pinnedHeader')}</span>
                    {/* 折起来时这个数就是全部线索：不报的话，人看不出自己折掉了什么。 */}
                    <span className="font-mono opacity-70">{pinnedRows.length}</span>
                  </button>
                );
              }
              if (row.kind === 'rest-header') {
                return (
                  <div
                    data-testid="rest-header"
                    className="px-2.5 pb-1 pt-3 text-[11px] font-medium uppercase tracking-wide text-text-muted"
                  >
                    {t('workbench.rail.restHeader')}{' '}
                    {/* 报的是主干那几场。折在各自主会话下面的 worker 算在那一行的展开钮上，
                        认不出出处的算在下面那一区——每一场只被数一次。 */}
                    <span className="font-mono opacity-70">{trunkRows.length}</span>
                  </div>
                );
              }
              if (row.kind === 'group-header') {
                const tag = row.tag;
                const framed = row.inTmux && !row.open;
                const head = (
                  <div className="group/section flex items-center pr-2">
                    <button
                      type="button"
                      onClick={() => groups.toggleCollapsed(row.key)}
                      aria-expanded={row.open}
                      data-testid="group-header"
                      data-group-key={row.key}
                      /* 标签名是人或 AI 起的字，不做大写变换——其余几行分区标题是界面自己
                         的词，这一行是数据。套上绿边时，外框已经占了左边 8px + 1.5px，
                         标题自己的左边距要让出这一截，箭头才和没套边的分类对在同一条竖线上，
                         不然看着像上一组的子分类。 */
                      className={`flex min-w-0 flex-1 items-center gap-1.5 ${framed ? 'pl-[0.5px] pr-2.5' : 'px-2.5'} pb-1 pt-3 text-[11px] font-medium tracking-wide text-text-muted transition-colors duration-200 hover:text-text-secondary`}
                    >
                      {row.open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                      {/* 绿圈说的是「这一组里有你还没回去看过的新回复」。它长在标题左边，
                          与「最近动过」那圈边分工：圈是提醒，边是找路。 */}
                      {row.unread ? (
                        <span data-testid="group-unread">
                          <LiveRing label={t('workbench.rail.unreadMark')} />
                        </span>
                      ) : null}
                      <span className="truncate">
                        {tag ? tag.name : t('workbench.rail.ungroupedHeader')}
                      </span>
                      {tag?.source === 'ai' ? (
                        <Sparkles
                          size={10}
                          className="shrink-0 text-text-dim"
                          aria-label={t('workbench.rail.groupSourceAi')}
                        />
                      ) : null}
                      {/* 折着时这个数就是全部线索：不报的话，人看不出这一区里有多少。 */}
                      <span className="shrink-0 font-mono opacity-70">{row.count}</span>
                    </button>
                    {tag ? (
                      <button
                        type="button"
                        onClick={() => setDeleting(tag)}
                        aria-label={t('workbench.rail.groupDelete')}
                        title={t('workbench.rail.groupDelete')}
                        data-testid="group-delete"
                        className="mt-2 shrink-0 rounded-[5px] p-1 text-text-muted opacity-0 transition-colors duration-200 hover:text-accent-error focus-visible:opacity-100 group-hover/section:opacity-100"
                      >
                        <Trash2 size={11} />
                      </button>
                    ) : null}
                  </div>
                );
                /* 折着的时候，整条标题外面长一圈活的绿边，说「这一组有一场开在 tmux 里」。展开之后
                   这句话由组里那几张卡自己说，标题上再留一圈就是同一件事说了两遍。 */
                return framed ? (
                  <div className="px-2 pt-2" data-testid="group-in-tmux">
                    <LiveBorder>{head}</LiveBorder>
                  </div>
                ) : (
                  head
                );
              }
              if (row.kind === 'section-more') {
                return (
                  <button
                    type="button"
                    onClick={() => setShown((s) => s + PAGE_SIZE)}
                    data-testid="section-more"
                    className="w-full px-4 pb-2 pt-0.5 text-left text-[11px] text-text-muted transition-colors duration-200 hover:text-text-secondary"
                  >
                    {t('workbench.rail.sectionMore', { n: row.remaining })}
                  </button>
                );
              }
              if (row.kind === 'workers-header') {
                return (
                  <button
                    type="button"
                    onClick={toggleOrphans}
                    aria-expanded={orphansVisible}
                    data-testid="workers-header"
                    className="flex w-full items-center gap-1.5 px-2.5 pb-1 pt-3 text-[11px] font-medium uppercase tracking-wide text-text-muted transition-colors duration-200 hover:text-text-secondary"
                  >
                    {orphansVisible ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    <span>{t('workbench.rail.orphanWorkersHeader')}</span>
                    <span className="font-mono opacity-70">{orphanRows.length}</span>
                  </button>
                );
              }
              const session = row.session;
              const pos = row.groupPos;
              /* 框的三段。同一套值：1px、清单的分隔线色、8px 圆角——与折叠时那张纸
                 一模一样，展开只是把那张纸撑开成一个圈住整组的框。 */
              const box =
                pos === 'head'
                  ? 'rounded-t-[8px] border border-b-0 border-border-color'
                  : pos === 'mid'
                    ? 'border-x border-border-color'
                    : pos === 'tail'
                      ? 'rounded-b-[8px] border border-t-0 border-border-color'
                      : '';
              return (
                /* 从属行往里缩一格。缩进是**位置**，不是装饰：一眼就看得出这一行不与
                   上面那一行并列，而且不占用颜色——颜色在这张清单里只留给在跑与出错。
                   在框里的时候缩进改到框**内**做，否则框会被子会话推得比主会话窄一截，
                   看起来是两个框而不是一个。 */
                <div className={row.nested && !pos ? 'pl-6 pr-2' : 'px-2'}>
                  <div className={box} data-group={pos}>
                    <div className={row.nested && pos ? 'pl-4' : ''}>
                  <MaybeLive live={views.isInTmux(session)}>
                  <SessionItem
                    session={session}
                    selected={session.session_id === selectedId}
                    copied={copiedId === session.session_id}
                    pinned={pins.isPinned(session.session_id)}
                    unread={views.isUnread(session)}
                    contentMatch={content.matches.get(session.session_id) ?? null}
                    nested={row.nested}
                    workerCount={row.workerCount}
                    workersExpanded={row.workersExpanded}
                    onSelect={handleSelect}
                    onCopy={handleCopy}
                    onTogglePin={handleTogglePin}
                    onToggleWorkers={toggleWorkers}
                    /* worker 跟着派活的那场走，不单独分组，卡上也就不长这颗按钮。 */
                    onPickGroup={
                      row.nested || session.origin === 'worker' ? undefined : openPicker
                    }
                      />
                  </MaybeLive>
                    </div>
                  </div>
                  {/* 行与行之间的间隔。连同每行自己的 py-2，行间总共留出 24px，
                      而行内最大的间距是 4px——差出六倍，清单才读得出是一行一行的。
                      **一组之内不留这道缝**：留了框就断成几截，一眼看过去是几个小框
                      挨着，而不是一个圈住整组的框。 */}
                  {pos === 'head' || pos === 'mid' ? null : <div className="h-2" />}
                </div>
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
        })}
      </div>

      {picker ? (
        <GroupPicker
          anchor={picker.rect}
          tags={groups.tags}
          current={groups.groupOf(picker.session.session_id)}
          onPick={(tagId) =>
            void moveTo(picker.session, groups.tags.find((tag) => tag.id === tagId) ?? null)
          }
          onCreate={(name) => createAndMove(picker.session, name)}
          onClose={closePicker}
        />
      ) : null}

      <Modal
        isOpen={deleting !== null}
        onClose={() => setDeleting(null)}
        title={deleting ? t('workbench.rail.groupDeleteTitle', { name: deleting.name }) : ''}
        footer={
          <>
            <button
              type="button"
              onClick={() => setDeleting(null)}
              className="flex-1 rounded-[8px] px-3 py-1.5 text-[13px] text-text-secondary transition-colors duration-200 hover:bg-bg-hover"
            >
              {t('workbench.rail.groupDeleteCancel')}
            </button>
            <button
              type="button"
              onClick={() => void confirmDelete()}
              data-testid="group-delete-confirm"
              className="flex-1 rounded-[8px] bg-accent-error px-3 py-1.5 text-[13px] font-medium text-[var(--text-on-accent)] transition-opacity duration-200 hover:opacity-90"
            >
              {t('workbench.rail.groupDeleteOk')}
            </button>
          </>
        }
      >
        <p className="text-[13px] leading-[1.6] text-text-secondary">
          {deleting ? t('workbench.rail.groupDeleteConfirm', { n: groups.sizeOf(deleting.id) }) : null}
        </p>
      </Modal>

      {/* 建完就交出去。等编号、反复重取清单、把中栏切过去，这些事由页面那边的启动状态
          统一管（见 `useSessionLaunch`）——左栏自己等的话，那段等待只有左栏知道，中栏
          仍是一片空白，而人点完创建看的正是中栏。 */}
      <NewSessionModal
        isOpen={newOpen}
        onClose={() => setNewOpen(false)}
        onCreated={(pending, text) => onCreated?.(pending, text)}
      />
    </aside>
  );
}
