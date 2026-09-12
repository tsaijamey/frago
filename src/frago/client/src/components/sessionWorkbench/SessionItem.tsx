/**
 * SessionItem — 左栏清单里的一行，从 SessionRail 拆出，供窗口化渲染与骨架屏共用高度基线。
 */

import { useTranslation } from 'react-i18next';
import { Check, Copy, CornerDownRight, Pin, Quote, Tag } from 'lucide-react';
import { LiveRing } from '@/components/ui/LiveEdge';
import i18n from '@/i18n';
import {
  activityTs,
  useWorkbenchLabels,
  type ContentMatch,
  type SessionStatus,
  type WorkbenchSession,
} from '@/hooks/useWorkbenchSessions';

const ACCENT_TEXT = 'text-accent-primary';
const ACCENT_BG = 'bg-accent-primary-10';

/**
 * 每一档的点。
 *
 * **只有两档带颜色。** 在跑是绿、出错是红——这两档要人回来看一眼。已完成与停着占了清单
 * 的九成，它们是会话正常的归宿，给颜色等于把整条清单染花。这两档改用两级灰区分：
 * 已完成亮一档、停着暗一档，旁边本来就写着字，不靠颜色也读得出。
 */
const STATUS_DOT: Record<SessionStatus, string> = {
  running: 'bg-accent-primary',
  error: 'bg-accent-error',
  done: 'bg-text-secondary',
  idle: 'bg-text-dim',
};

/**
 * 状态文字的颜色。
 *
 * 「已完成」从前是蓝的。一千多场会话里六成是这一档，于是整条清单常年泛着蓝——一个占
 * 多数的、且不需要人做任何事的状态，不该拿一个颜色去标它。现在它跟其余静态信息一样是
 * 中性灰，颜色只留给需要人注意的两档：在跑（绿）与出错（红）。
 * 筛选行那几个点仍各有各的颜色——那里是图例，要的正是彼此可辨。
 */
const STATUS_TEXT: Record<SessionStatus, string> = {
  running: 'text-accent-primary',
  error: 'text-accent-error',
  done: 'text-text-muted',
  idle: 'text-text-muted',
};

export function resumeCommand(session: WorkbenchSession): string {
  switch (session.family) {
    case 'opencode':
      return `opencode -s ${session.session_id}`;
    case 'codex':
      return `codex resume ${session.session_id}`;
    default:
      return `claude --resume ${session.session_id}`;
  }
}

/**
 * 相对时刻。取字走 i18next 实例而不是 `useTranslation`——这是个纯函数，不是组件。
 *
 * 取字发生在**调用那一刻**（也就是渲染那一刻），所以它拿到的永远是当下这一种语言；
 * 调它的那张卡自己订阅了语言变化，换语言时整行重算，不用刷新页面。
 */
export function relativeTime(ts: number, now: number = Date.now()): string {
  if (!ts) return '';
  const delta = Math.max(0, now - ts);
  const minute = 60_000;
  if (delta < minute) return i18n.t('workbench.rail.justNow');
  if (delta < 60 * minute) {
    return i18n.t('workbench.rail.minutesAgo', { n: Math.floor(delta / minute) });
  }
  if (delta < 24 * 60 * minute) {
    return i18n.t('workbench.rail.hoursAgo', { n: Math.floor(delta / (60 * minute)) });
  }
  const days = Math.floor(delta / (24 * 60 * minute));
  if (days < 30) return i18n.t('workbench.rail.daysAgo', { n: days });
  const d = new Date(ts);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate()
  ).padStart(2, '0')}`;
}

/**
 * 展开那一叠的三角。
 *
 * **实心，不是细线。** 从前这里是一条 lucide 的箭头，1.5px 描边、中性灰、没有底——
 * 在 11px 的字号旁边它和右边那两颗图标一样重，读出来是"又一个图标"，不是"这里能按"。
 * 实心三角是文件夹展开这件事几十年的常规写法（访达就是它），同样大小下面积大得多，
 * 一眼分得出。
 *
 * **不用品牌绿。** 侧栏的规矩是绿色只承担选中、当前、活跃这几样；能展开是个不带状态的
 * 控件，主干里两百来张卡常年挂着一点绿，会把真正需要被看见的那两档淹掉。让它看得出能按，
 * 靠的是形状与底色，不是颜色。
 *
 * 转 90 度而不是换一个图标：形状不变、方向变，人才看得出是同一个东西的两个状态。
 */
function DisclosureTriangle({ expanded }: { expanded: boolean }) {
  return (
    <svg
      width="9"
      height="9"
      viewBox="0 0 8 8"
      fill="currentColor"
      aria-hidden="true"
      className={`transition-transform duration-200 ${expanded ? 'rotate-90' : ''}`}
    >
      <path d="M2 0.5 L7 4 L2 7.5 Z" />
    </svg>
  );
}

function StatusDot({ status }: { status: SessionStatus }) {
  const { statusLabel } = useWorkbenchLabels();
  return (
    <span
      data-status={status}
      title={statusLabel(status)}
      className={`inline-flex shrink-0 items-center gap-1 text-[11px] ${STATUS_TEXT[status]}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[status]}`} />
      {statusLabel(status)}
    </span>
  );
}

/**
 * 内容命中摘要。**有命中就顶掉「已完成」那一格**——这一刻人是在找那句话，
 * 卡片上最该出现的就是它，而不是这场会话最后做完了什么。
 */
function ContentHits({ match }: { match: ContentMatch }) {
  const { t } = useTranslation();
  const more = match.hit_count - match.hits.length;
  return (
    <div data-testid="content-hits" className="mt-1 space-y-1">
      {match.hits.map((hit) => (
        <p
          key={hit.record_id}
          className="line-clamp-2 rounded-[5px] bg-bg-subtle px-1.5 py-1 text-[11px] leading-[1.55] text-text-secondary"
        >
          <Quote size={9} className="mr-1 inline align-baseline text-text-muted" />
          <span className="text-text-muted">
            {hit.kind === 'user.say'
              ? t('workbench.rail.hitUserSay')
              : t('workbench.rail.hitAgentSay')}{' '}
          </span>
          {hit.snippet}
        </p>
      ))}
      {more > 0 ? (
        <p className="text-[11px] text-text-muted">
          {t('workbench.rail.moreHits', { n: more })}
          {match.capped ? t('workbench.rail.moreHitsCapped') : ''}
        </p>
      ) : null}
    </div>
  );
}

export default function SessionItem({
  session,
  selected,
  copied,
  pinned = false,
  unread = false,
  contentMatch,
  nested = false,
  workerCount = 0,
  workersExpanded = false,
  onSelect,
  onCopy,
  onTogglePin,
  onToggleWorkers,
  onPickGroup,
}: {
  session: WorkbenchSession;
  selected: boolean;
  copied: boolean;
  /** 这场会话在不在置顶名单里。 */
  pinned?: boolean;
  /**
   * agent 说完了话、你还没回去看过这一场。
   *
   * 判据在 `useSessionViews`：这场已经不在跑、最后一句回复比你上次点开它的时刻新，
   * 而且你至少点开过它一次。
   */
  unread?: boolean;
  /** 这场会话在内容检索里命中了什么。没搜内容、或这场没命中时为 null。 */
  contentMatch?: ContentMatch | null;
  /**
   * 这一行是挂在别人下面的 worker。
   *
   * 区分**不靠颜色**：颜色在这张清单里只有两个用处——在跑是绿、出错是红，多一种就把
   * 那两档淹了。从属关系靠三样一起说：缩进（位置本身）、行首那个折角、标题降一档字色。
   */
  nested?: boolean;
  /** 这场派出去过几个 worker。0 就不长展开按钮。 */
  workerCount?: number;
  workersExpanded?: boolean;
  onSelect: (id: string) => void;
  onCopy: (session: WorkbenchSession) => void;
  /** 置顶开关。不给就不长这颗按钮——骨架屏与只读场景用得上。 */
  onTogglePin?: (session: WorkbenchSession) => void;
  /** 展开/折起这场派出去的 worker。不给就不长这颗按钮。 */
  onToggleWorkers?: (session: WorkbenchSession) => void;
  /** 放进分组。`anchor` 是按钮本身，浮层按它的位置摆。不给就不长这颗按钮。 */
  onPickGroup?: (session: WorkbenchSession, anchor: HTMLElement) => void;
}) {
  const { t } = useTranslation();
  const { familyLabel } = useWorkbenchLabels();
  const dirTail = session.directory.split('/').filter(Boolean).slice(-2).join('/');
  const cmd = resumeCommand(session);
  const hasWorkers = workerCount > 0 && Boolean(onToggleWorkers);
  /** 折着的时候才叠纸——展开之后那一叠已经摊在下面了，再画一叠是重复说一遍。 */
  const stacked = hasWorkers && !workersExpanded;
  return (
    /* 叠纸画在这一层：两张纸片是绝对定位的兄弟节点，排在卡片**前面**，于是被卡片盖住，
       只露出下缘与两侧收进去的那一点。层数固定三层，不随实际条数变——数量由展开后
       列出来的那几行回答，让纸片去数数只会让一叠纸在 2 个和 9 个之间抖动。
       折着时底下多留一点空，否则最下面那张纸会贴到下一行头上。 */
    <div className={`relative ${stacked ? 'mb-3' : ''}`}>
      {stacked ? (
        <>
          {/* 每张纸都要有自己的一道边，否则两张纸的下缘挨在一起，看起来是文字底下浮了
              两道杠。边用的是清单里到处在用的那个分隔线色，不新增颜色。 */}
          <span
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-4 top-4 -bottom-[10px] rounded-[8px] border border-border-color bg-bg-secondary"
          />
          <span
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-2 top-3 -bottom-[5px] rounded-[8px] border border-border-color bg-bg-secondary"
          />
        </>
      ) : null}
      {/* 卡片背后垫一层不透明的底，否则身后那两张纸会透过卡片自己的半透明底色显出来。
          填的是侧栏自己的底色：看起来仍是一张干净的纸，只是把身后那两张挡住了。
          垫在这里而不是画在卡片上，是为了让卡片那一层继续只管自己的状态——选中换底、
          鼠标经过浮底，两样都还长在同一个地方。 */}
      {stacked ? (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 rounded-[8px] border border-border-color bg-bg-secondary"
        />
      ) : null}
      <div
        role="button"
        tabIndex={0}
        onClick={() => onSelect(session.session_id)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onSelect(session.session_id);
          }
        }}
        aria-current={selected ? 'true' : undefined}
        data-testid="session-item"
        data-status={session.status}
        data-pinned={pinned ? 'true' : undefined}
        data-origin={session.origin}
        data-nested={nested ? 'true' : undefined}
        data-stacked={stacked ? 'true' : undefined}
        /* **平时不是一张卡。** 从前每一场会话都有自己的边框与卡底，一屏摆下五六张，人看到
           的先是五六个方框，然后才是里面的字。清单要的是一列可扫读的行：平时没有任何容器，
           鼠标经过才浮出一层底，选中的那一场换成品牌绿淡底——整行换底，不靠任何单边色条。
           绿环去掉了：淡底加标题转绿已经足够把它从一列灰字里分出来，再加一圈亮绿只是喊。
           **底下压着 worker 的那几场是例外**：它们要有一张实在的纸，身后那一叠才立得住。
           容器在这里不是装饰，它就是"这下面还有东西"这句话本身。 */
        className={`group/session relative w-full cursor-pointer rounded-[8px] px-2.5 py-2 text-left transition-colors duration-200 ${
          selected ? ACCENT_BG : 'hover:bg-bg-hover'
        }`}
      >
      <div className="flex items-start gap-2">
        {/* 展开钮在标题**前面**，不在下面那行里。从前它挤在目录与复制按钮中间，跟旁边
            两颗图标一样大小、一样灰，读出来是"又一个图标"而不是"这里能展开"，还把目录
            挤短了一截。挪到行首之后它自成一列，与缩进对齐，一眼就知道是层级。 */}
        {hasWorkers ? (
          <button
            type="button"
            aria-expanded={workersExpanded}
            aria-label={
              workersExpanded
                ? t('workbench.rail.collapseWorkers')
                : t('workbench.rail.expandWorkers', { n: workerCount })
            }
            title={t('workbench.rail.workerCount', { n: workerCount })}
            data-testid="toggle-workers"
            onClick={(e) => {
              e.stopPropagation();
              onToggleWorkers?.(session);
            }}
            /* 给它一个真的能按的形状：20×20 的方块、有底、有圆角。没有底的时候它只是
               一个漂在标题左边的符号，和"可以点"这件事对不上；有了底，它和旁边那两颗
               图标的区别也立刻出来了——那两颗是悬停才浮出来的，这一颗一直在。 */
            className="-ml-0.5 mt-[1px] flex h-5 w-5 shrink-0 items-center justify-center rounded-[6px] bg-bg-hover text-text-secondary transition-colors duration-200 hover:bg-bg-active hover:text-text-primary"
          >
            <DisclosureTriangle expanded={workersExpanded} />
          </button>
        ) : null}
        {/* 折角只在从属行上出现，且不可点——它说的是"这一行属于上面那一行"，
            不是"点我会发生什么"。 */}
        {nested ? (
          <CornerDownRight
            size={11}
            className="mt-[3px] shrink-0 text-text-dim"
            aria-hidden="true"
          />
        ) : null}
        {/* 绿圈与分区标题上那个是同一个东西：这一场 agent 说完了话，你还没回来看。
            点开这张卡它就灭。 */}
        {unread ? (
          /* 这一格的高度就是标题第一行的高度（字号 × 1.5 的行高），圈在格子里上下居中，
             于是圈的中线正好落在标题第一行的中线上。从前靠一个 5px 的下推去凑，而这一格
             自己的高度跟着继承来的行高走、圈又按文字基线摆，两边各算各的，对不齐。 */
          <span
            data-testid="session-unread"
            className={`flex shrink-0 items-center ${nested ? 'h-[18px]' : 'h-[19.5px]'}`}
          >
            <LiveRing label={t('workbench.rail.unreadMark')} />
          </span>
        ) : null}
        <span
          className={`line-clamp-2 min-w-0 flex-1 font-medium leading-[1.5] ${
            nested ? 'text-[12px]' : 'text-[13px]'
          } ${selected ? ACCENT_TEXT : nested ? 'text-text-secondary' : 'text-text-primary'}`}
        >
          {session.title}
        </span>
        <span
          className="shrink-0 font-mono text-[11px] text-text-muted"
          title={
            session.last_reply_at
              ? t('workbench.rail.tsLastReply')
              : t('workbench.rail.tsLastActive')
          }
        >
          {relativeTime(activityTs(session))}
        </span>
      </div>

      {/* 行内挤、行间松——这一行贴着标题走，它是标题的附属而不是并列的另一件事。
          行与行之间留 8px（见 SessionRail 里那道间隔），内外差出四倍，
          眼睛才分得清「一行从哪开始」。workbuddy 的清单也不画分隔线，靠的就是这个比例。 */}
      <div className="mt-0.5 flex items-center gap-2">
        <StatusDot status={session.status} />
        {/* 来源从前套着一颗药丸。行没有卡底之后，药丸的底色与清单底色是同一个值——
            那圈药丸只剩一个看不见的轮廓在占位。改成一段普通的次要文字，
            用一个间隔点与目录分开就够了。 */}
        <span className="shrink-0 text-[11px] text-text-muted">
          {familyLabel(session.family)}
        </span>
        <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-text-dim">
          {dirTail}
        </span>
        {onPickGroup ? (
          <button
            type="button"
            title={t('workbench.rail.groupPick')}
            aria-label={t('workbench.rail.groupPick')}
            data-testid="pick-group"
            onClick={(e) => {
              e.stopPropagation();
              onPickGroup(session, e.currentTarget);
            }}
            /* 与图钉同一个规矩：平时不显形，鼠标进卡或键盘走到才浮出来。这张卡在哪个组，
               分区标题已经说了，卡上不必再常驻一颗。 */
            className="shrink-0 rounded-[5px] p-1 text-text-muted opacity-0 transition-colors duration-200 hover:text-text-primary focus-visible:opacity-100 group-hover/session:opacity-100"
          >
            <Tag size={12} />
          </button>
        ) : null}
        {onTogglePin ? (
          <button
            type="button"
            title={pinned ? t('workbench.rail.unpin') : t('workbench.rail.pinThis')}
            aria-label={pinned ? t('workbench.rail.unpin') : t('workbench.rail.pin')}
            aria-pressed={pinned}
            data-testid="toggle-pin"
            onClick={(e) => {
              e.stopPropagation();
              onTogglePin(session);
            }}
            /* 置顶的那几场图钉一直亮着，其余的平时不显形、鼠标进卡才浮出来：一千多张卡
               每张都常驻一颗图钉，视觉噪音远大于它的用处。键盘走到时同样显形。 */
            className={`shrink-0 rounded-[5px] p-1 transition-colors duration-200 ${
              pinned
                ? ACCENT_TEXT
                : 'text-text-muted opacity-0 hover:text-text-primary focus-visible:opacity-100 group-hover/session:opacity-100'
            }`}
          >
            {/* 图钉的形状不随状态变，只有颜色与实心变：形状一换（图钉↔断了的图钉），
                静止时看到的就成了"这一下会发生什么"，而不是"这场现在是什么状态"。 */}
            <Pin size={12} fill={pinned ? 'currentColor' : 'none'} />
          </button>
        ) : null}
        <button
          type="button"
          title={cmd}
          aria-label={t('workbench.rail.copyResume')}
          data-testid="copy-resume"
          onClick={(e) => {
            e.stopPropagation();
            onCopy(session);
          }}
          className={`shrink-0 rounded-[5px] p-1 transition-colors duration-200 ${
            copied ? ACCENT_TEXT : 'text-text-muted hover:text-text-primary'
          }`}
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
        </button>
      </div>

      {contentMatch ? <ContentHits match={contentMatch} /> : null}
      {!contentMatch && session.digest_done ? (
        <p
          data-testid="digest-done"
          className="mt-1 line-clamp-2 text-[11px] leading-[1.5] text-text-muted"
        >
          <span className="text-text-muted">{t('workbench.rail.digestDone')} </span>
          {session.digest_done}
        </p>
      ) : null}
      {session.digest_stuck ? (
        <p
          data-testid="digest-stuck"
          className="mt-1 line-clamp-2 text-[11px] leading-[1.55] text-accent-error"
        >
          <span className="opacity-70">{t('workbench.rail.digestStuck')} </span>
          {session.digest_stuck}
        </p>
      ) : null}
      </div>
    </div>
  );
}
