/**
 * SessionItem — 左栏清单里的一行，从 SessionRail 拆出，供窗口化渲染与骨架屏共用高度基线。
 */

import { useTranslation } from 'react-i18next';
import { Check, Copy, CornerDownRight, GitBranch, Loader2, Pin } from 'lucide-react';
import i18n from '@/i18n';
import { formatClock } from './RecordCard';
import { activityTs, type WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import type { ForYouEmphasis, ForYouInfo } from '@/hooks/useForYou';

/** 选中：整张卡换中性底加一圈完整描边。选中是「你在看哪一条」，不是动作，不用绿，也不用单边条。 */
const SELECTED = 'bg-[var(--sel-bg)] shadow-[inset_0_0_0_1px_var(--sel-border)]';

/** 加重的 For you 悬停说什么。 */
const EMPHASIS_HINT_KEY: Record<ForYouEmphasis, string> = {
  answer: 'workbench.forYou.whyAnswer',
  'pick-one': 'workbench.forYou.whyPickOne',
  stopped: 'workbench.forYou.whyStopped',
  'decision-card': 'workbench.forYou.whyDecisionCard',
};

/**
 * 在终端里接着这一场说话的那条命令 —— 复制按钮给的就是它。
 *
 * 每一家只认自己那一种写法：claude 是 `--resume <编号>`，codex 是 `resume <编号>`，
 * opencode 是 `-s <编号>`。三条都与 frago 起这些会话时用的续接命令同一个写法（见各家
 * driver 的 `_launch`），只是不带自动化用的那几个免确认开关——人自己在终端里跑，该问
 * 的还是要问。
 *
 * **CoreAgent 没有这样一条命令，所以返回 null，按钮不长出来。** 它不是一个能挂在终端里
 * 的交互程序：一轮就是一个进程，接着说话要同时给出这一轮要说的话和它当初跑的目录。
 * 从前这一家落进 claude 那条默认分支，复制出来的是 `claude --resume core_…`——那个编号
 * 在 claude 的档案里根本不存在，粘到终端里 claude 会拿它当新编号开一场空白会话，人以为
 * 自己接上了原来那场。要接着说话就在页面上说，CoreAgent 那一家已经能在中栏直接回话。
 */
export function resumeCommand(session: WorkbenchSession): string | null {
  switch (session.family) {
    case 'opencode':
      return `opencode -s ${session.session_id}`;
    case 'codex':
      return `codex resume ${session.session_id}`;
    case 'coreagent':
      return null;
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
 * 过了多久，不带「ago」：「just now」「5 min」「3 h」「2 d」，一个月以上写日期。
 *
 * 清单第一行的时间只剩这一种写法。For you 那几场它就是「停了多久」，其余是「多久前说的
 * 最后一句」——两种读法都不需要「ago」来撑。
 */
export function shortAge(ts: number, now: number = Date.now()): string {
  if (!ts) return '';
  const delta = Math.max(0, now - ts);
  const minute = 60_000;
  if (delta < minute) return i18n.t('workbench.rail.ageNow');
  if (delta < 60 * minute) return i18n.t('workbench.rail.ageMin', { n: Math.floor(delta / minute) });
  if (delta < 24 * 60 * minute) {
    return i18n.t('workbench.rail.ageHour', { n: Math.floor(delta / (60 * minute)) });
  }
  const days = Math.floor(delta / (24 * 60 * minute));
  if (days < 30) return i18n.t('workbench.rail.ageDay', { n: days });
  const d = new Date(ts);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate()
  ).padStart(2, '0')}`;
}

/** 「For you」标签。加重的换告警橙底，其余中性描边；都不用绿。 */
export function ForYouChip({ emphasis }: { emphasis: ForYouEmphasis | null }) {
  const { t } = useTranslation();
  return (
    <span
      data-testid="for-you-chip"
      data-emphasis={emphasis ?? 'none'}
      title={emphasis ? t(EMPHASIS_HINT_KEY[emphasis]) : undefined}
      className={`inline-flex shrink-0 items-center rounded-[5px] px-1.5 py-[1px] text-[11px] font-medium leading-[1.4] ${
        emphasis
          ? 'bg-accent-warning-10 text-accent-warning'
          : 'border border-border-strong text-text-secondary'
      }`}
    >
      {t('workbench.forYou.label')}
    </span>
  );
}

/** 本地先挂的「Sending」：话刚出门，不等清单那 15 秒一刷。 */
export function SendingChip() {
  const { t } = useTranslation();
  return (
    <span
      data-testid="sending-chip"
      className="inline-flex shrink-0 items-center gap-1 rounded-[5px] border border-border-color px-1.5 py-[1px] text-[11px] leading-[1.4] text-text-muted"
    >
      <Loader2 size={10} className="animate-spin" />
      {t('workbench.forYou.sending')}
    </span>
  );
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

export default function SessionItem({
  session,
  selected,
  copied,
  pinned = false,
  forYou = null,
  sending = false,
  nested = false,
  branchOf = null,
  workerCount = 0,
  workersExpanded = false,
  onSelect,
  onCopy,
  onTogglePin,
  onToggleWorkers,
}: {
  session: WorkbenchSession;
  selected: boolean;
  copied: boolean;
  /** 这场会话在不在置顶名单里。 */
  pinned?: boolean;
  /**
   * 这一场挂着 For you：有 agent 停在输入框前等你（判据见 `useForYou`）。挂着的两行，
   * 没挂的一行——清单上没有别的状态词。
   */
  forYou?: ForYouInfo | null;
  /** 这一场本地刚发出一句话、还在路上。 */
  sending?: boolean;
  /**
   * 这一行是挂在别人下面的 worker。
   *
   * 区分**不靠颜色**：从属关系靠三样一起说：缩进（位置本身）、行首那个折角、标题降一档字色。
   */
  nested?: boolean;
  /**
   * 这一场是从哪场会话分出来的分支。分支会话和人自己开的会话一样摆在主干上（它等的是人），
   * 出处只在这一行说：「分支自 <原会话>」，点它切到原会话。原会话标题认不出时写编号开头。
   */
  branchOf?: { id: string; title: string | null } | null;
  /** 这场派出去过几个 worker。0 就不长展开按钮。 */
  workerCount?: number;
  workersExpanded?: boolean;
  onSelect: (id: string) => void;
  onCopy: (session: WorkbenchSession) => void;
  /** 置顶开关。不给就不长这颗按钮——骨架屏与只读场景用得上。 */
  onTogglePin?: (session: WorkbenchSession) => void;
  /** 展开/折起这场派出去的 worker。不给就不长这颗按钮。 */
  onToggleWorkers?: (session: WorkbenchSession) => void;
}) {
  const { t } = useTranslation();
  const cmd = resumeCommand(session);
  const age = forYou ? forYou.waitingSince : activityTs(session);
  const bold = forYou?.unseen ?? false;
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
        data-for-you={forYou ? 'true' : undefined}
        data-pinned={pinned ? 'true' : undefined}
        data-origin={session.origin}
        data-nested={nested ? 'true' : undefined}
        data-stacked={stacked ? 'true' : undefined}
        /* **平时不是一张卡。** 从前每一场会话都有自己的边框与卡底，一屏摆下五六张，人看到
           的先是五六个方框，然后才是里面的字。清单要的是一列可扫读的行：平时没有任何容器，
           鼠标经过才浮出一层底，选中的那一场换中性底再加一圈完整描边——整张卡换样子，
           不靠任何单边色条，也不用绿：绿只留给在跑，选中不是动作。
           **底下压着 worker 的那几场是例外**：它们要有一张实在的纸，身后那一叠才立得住。
           容器在这里不是装饰，它就是"这下面还有东西"这句话本身。 */
        className={`group/session relative w-full cursor-pointer rounded-[8px] px-2.5 py-2 text-left transition-colors duration-200 ${
          selected ? SELECTED : 'hover:bg-bg-hover'
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
        <span
          className={`min-w-0 flex-1 truncate leading-[1.5] ${
            nested ? 'text-[12px]' : 'text-[13px]'
          } ${bold ? 'font-semibold' : 'font-medium'} ${
            nested && !selected ? 'text-text-secondary' : 'text-text-primary'
          }`}
        >
          {session.title}
        </span>
        {/* 时间与悬停按钮叠在同一格：平时是时间，鼠标进卡（或键盘走到）换成按钮。 */}
        <span className="relative flex shrink-0 items-center">
          <span
            className={`flex items-center gap-1 font-mono text-[11px] text-text-muted ${
              onTogglePin || cmd ? 'group-hover/session:invisible group-focus-within/session:invisible' : ''
            }`}
            title={
              forYou
                ? t('workbench.forYou.stoppedAt', { time: formatClock(forYou.waitingSince) })
                : session.last_reply_at
                  ? t('workbench.rail.tsLastReply')
                  : t('workbench.rail.tsLastActive')
            }
          >
            {pinned ? (
              <Pin size={10} fill="currentColor" className="text-text-primary" aria-hidden />
            ) : null}
            {shortAge(age)}
          </span>
          <span className="absolute right-0 top-1/2 hidden -translate-y-1/2 items-center gap-1 group-hover/session:flex group-focus-within/session:flex">
            {onTogglePin ? (
              <button
                type="button"
                title={pinned ? t('workbench.rail.unpinHint') : t('workbench.rail.pinHint')}
                aria-label={pinned ? t('workbench.rail.unpin') : t('workbench.rail.pin')}
                aria-pressed={pinned}
                data-testid="toggle-pin"
                onClick={(e) => {
                  e.stopPropagation();
                  onTogglePin(session);
                }}
                /* 带字的按钮：图钉图标不说「点了会怎样」，字说。中性色，不用品牌绿。 */
                className="flex items-center gap-1 rounded-[5px] border border-border-color bg-bg-secondary px-1.5 py-[1px] text-[11px] text-text-secondary hover:bg-bg-hover hover:text-text-primary"
              >
                <Pin size={10} fill={pinned ? 'currentColor' : 'none'} />
                {pinned ? t('workbench.rail.unpin') : t('workbench.rail.pin')}
              </button>
            ) : null}
            {/* 没有续接命令的那一家（CoreAgent）不长这颗按钮：一颗点了会把错命令放进剪贴板
                的按钮，比没有按钮坏得多。 */}
            {cmd ? (
              <button
                type="button"
                title={cmd}
                aria-label={t('workbench.rail.copyResume')}
                data-testid="copy-resume"
                onClick={(e) => {
                  e.stopPropagation();
                  onCopy(session);
                }}
                className="rounded-[5px] border border-border-color bg-bg-secondary p-[3px] text-text-muted hover:text-text-primary"
              >
                {copied ? <Check size={11} /> : <Copy size={11} />}
              </button>
            ) : null}
          </span>
        </span>
      </div>

      {/* 第二行只有两种可能：For you 加它收尾的原话，或者刚发出、还在路上的 Sending。
          其余的会话只有一行——状态词、来源、目录、摘要都退场了。 */}
      {forYou || sending ? (
        <div className="mt-1 flex min-w-0 items-start gap-1.5">
          {sending ? <SendingChip /> : forYou ? <ForYouChip emphasis={forYou.emphasis} /> : null}
          {!sending && forYou?.words ? (
            <p
              data-testid="for-you-words"
              className="line-clamp-2 min-w-0 flex-1 text-[11px] leading-[1.5] text-text-secondary"
            >
              {forYou.words}
            </p>
          ) : null}
        </div>
      ) : null}

      {/* 分支的出处。中性灰小字，不抢 For you 那一行；点它去原会话，不点就是普通的一行说明。 */}
      {branchOf ? (
        <button
          type="button"
          data-testid="branch-of"
          title={t('workbench.rail.branchOfHint')}
          onClick={(e) => {
            e.stopPropagation();
            onSelect(branchOf.id);
          }}
          className="mt-1 flex max-w-full items-center gap-1 text-left text-[11px] leading-[1.5] text-text-muted hover:text-text-secondary"
        >
          <GitBranch size={11} className="shrink-0" aria-hidden="true" />
          <span className="min-w-0 truncate">
            {t('workbench.rail.branchOf', { title: branchOf.title ?? branchOf.id.slice(0, 8) })}
          </span>
        </button>
      ) : null}
      </div>
    </div>
  );
}
