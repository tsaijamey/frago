/**
 * SessionItem — 左栏清单里的一张会话卡，从 SessionRail 拆出，供窗口化渲染与骨架屏共用高度基线。
 *
 * **三行，每行独占整宽**（09-29 第五轮）。任何图标、按钮、标签都不和标题或预览挤在同一行：
 *
 * | 行 | 内容 |
 * |---|---|
 * | 标题 | 最多两行，放不下截断，悬停看全文 |
 * | 预览 | agent 最近一次回复，截开头留结尾，灰字最多两行；所有会话都有这一行 |
 * | 状态行 | For you（发出后是 Sending / Agent on it）· 时长 · 终端 · 子会话数 · 图钉；最右「…」 |
 *
 * For you 与其余会话同一结构；三档字：标题 13/600、预览 12/400、状态行 11，只有 For you
 * 标签带颜色。
 */

import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight, CornerDownRight, GitBranch, Loader2, Pin, SquareTerminal } from 'lucide-react';
import i18n from '@/i18n';
import { formatClock } from './RecordCard';
import { activityTs, type WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import { keepTail, type ForYouInfo } from '@/hooks/useForYou';
import { LiveBorder } from '@/components/ui/LiveEdge';
import SessionMenu from './SessionMenu';
import type { DeleteSessionResult } from './DeleteSessionButton';

/** 选中：整张卡换中性底加一圈完整描边。选中是「你在看哪一条」，不是动作，不用绿，也不用单边条。 */
const SELECTED = 'bg-[var(--sel-bg)] shadow-[inset_0_0_0_1px_var(--sel-border)]';

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

/**
 * 「For you」标签。所有 For you 长一个样：品牌绿淡底绿字，与 Send 同色系——它标的是人要做
 * 的决定（主人 09-29 定）。从前按问句 / 选项 / 出错 / 决策卡加重成告警橙、悬停说原因，
 * 第五轮一并删掉。
 */
export function ForYouChip() {
  const { t } = useTranslation();
  return (
    <span
      data-testid="for-you-chip"
      className="inline-flex shrink-0 items-center rounded-[5px] bg-accent-primary-10 px-1.5 text-[11px] font-medium leading-[17px] text-accent-primary"
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
      className="inline-flex shrink-0 items-center gap-1 rounded-[5px] border border-border-color px-1.5 text-[11px] leading-[15px] text-text-muted"
    >
      <Loader2 size={10} className="animate-spin" />
      {t('workbench.forYou.sending')}
    </span>
  );
}

/** 话已进会话、agent 接手了：中性圆点加字，不用绿（这一屏的绿只给 Send 与 For you）。 */
export function AgentOnItChip() {
  const { t } = useTranslation();
  return (
    <span
      data-testid="agent-on-it-chip"
      className="inline-flex shrink-0 items-center gap-1 text-[11px] font-medium leading-[17px] text-text-secondary"
    >
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-text-muted" />
      {t('workbench.forYou.agentOnIt')}
    </span>
  );
}

/**
 * 卡片第二行的预览。For you 那几场取收尾原话（tmux 清单的 `closing_text`，已截开头留结尾，
 * 有合法卡片时是卡片的问题）；其余取会话清单的 `digest_done`——它是最近一条回复的**开头**
 * 一段，服务端还没出「回复结尾」字段之前先用它，照样截开头留结尾，去掉开头的 Markdown
 * 标题符号。有卡片的换成卡片的问题。都没有返回空串，由卡片写「No reply from the agent yet」。
 */
export function previewOf(
  session: WorkbenchSession,
  forYou: ForYouInfo | null,
  card: string | null = null
): string {
  if (forYou?.words) return forYou.words;
  const text = card ?? session.digest_done ?? '';
  return keepTail(text.replace(/^\s*#{1,6}\s+/, ''));
}

function MaybeLiveCard({ live, children }: { live: boolean; children: ReactNode }) {
  return live ? <LiveBorder>{children}</LiveBorder> : <>{children}</>;
}

export default function SessionItem({
  session,
  selected,
  copied,
  pinned = false,
  inPinnedGroup = false,
  forYou = null,
  sending = false,
  agentOnIt = false,
  inTmux = false,
  card = null,
  busyTurn = false,
  nested = false,
  branchOf = null,
  workerCount = 0,
  workersExpanded = false,
  live = false,
  onSelect,
  onCopy,
  onTogglePin,
  onToggleWorkers,
  onStopped,
  onDeleted,
}: {
  session: WorkbenchSession;
  selected: boolean;
  copied: boolean;
  /** 这场会话在不在置顶名单里。 */
  pinned?: boolean;
  /**
   * 这张卡摆在 Pinned 那一块里：整组已经有底色、描边和「Always on top」，每张再画一个图钉
   * 是重复，不画。组外（按筛选单独看到的置顶会话）照旧画。
   */
  inPinnedGroup?: boolean;
  /** 这一场挂着 For you：有 agent 停在输入框前等你（判据见 `useForYou`）。 */
  forYou?: ForYouInfo | null;
  /** 这一场本地刚发出一句话、还在路上。 */
  sending?: boolean;
  /** 这一场本地发出的那句已进会话、这一轮还没答完。 */
  agentOnIt?: boolean;
  /** 此刻开在 tmux 里：状态行画终端图标，「…」菜单才有 Close tmux session。 */
  inTmux?: boolean;
  /** 选中那场末条回复里留了合法的「要人拍板」卡片：预览换成卡片的问题。 */
  card?: string | null;
  /** 本页刚发出的一句还没答完：菜单里关 tmux 先问。 */
  busyTurn?: boolean;
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
  /** 这场派出去过几个 worker。0 就不长子会话数。 */
  workerCount?: number;
  workersExpanded?: boolean;
  /** 开在 tmux 里：最上面这张卡外面一圈流光。 */
  live?: boolean;
  onSelect: (id: string) => void;
  onCopy: (session: WorkbenchSession) => void;
  /** 置顶开关。不给就没有「…」菜单里那一项——骨架屏与只读场景用得上。 */
  onTogglePin?: (session: WorkbenchSession) => void;
  /** 展开/折起这场派出去的 worker。不给就不长子会话数。 */
  onToggleWorkers?: (session: WorkbenchSession) => void;
  /** 从「…」菜单关掉了 tmux。 */
  onStopped?: (session: WorkbenchSession) => void;
  /** 从「…」菜单删掉了这一场。 */
  onDeleted?: (session: WorkbenchSession, result: DeleteSessionResult) => void;
}) {
  const { t } = useTranslation();
  const age = forYou ? forYou.waitingSince : activityTs(session);
  const hasWorkers = workerCount > 0 && Boolean(onToggleWorkers);
  /** 折着的时候才叠纸——展开之后那一叠已经摊在下面了，再画一叠是重复说一遍。 */
  const stacked = hasWorkers && !workersExpanded;
  const preview = previewOf(session, forYou, card);
  /** 发出之后状态行只说这句话走到哪了，不再写时长。 */
  const progress = sending ? 'sending' : agentOnIt ? 'agent' : null;
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
      {/* 开在 tmux 里的那道流光只围最上面这张卡。套在外层的话，身后那一叠纸也被圈进去，
          光就沿着整叠的外框跑到最底下那张纸的下缘去了（主人 09-29 指出）。 */}
      <MaybeLiveCard live={live}>
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
        /* **平时不是一张卡。** 清单要的是一列可扫读的行：平时没有任何容器，鼠标经过才浮出
           一层底，选中的那一场换中性底再加一圈完整描边——整张卡换样子，不靠任何单边色条，
           也不用绿。**底下压着 worker 的那几场是例外**：它们要有一张实在的纸，身后那一叠
           才立得住。内边距上下 10、左右 12（第五轮二改）。 */
        className={`group/session relative w-full cursor-pointer rounded-[8px] px-3 py-2.5 text-left transition-colors duration-200 ${
          selected ? SELECTED : 'hover:bg-bg-hover'
        }`}
      >
        {/* 第 1 行：标题，最多两行，悬停看全文。折角只在从属行上出现，且不可点。 */}
        <div className="flex min-w-0 items-start gap-1.5">
          {nested ? (
            <CornerDownRight size={11} className="mt-[3px] shrink-0 text-text-dim" aria-hidden="true" />
          ) : null}
          <span
            data-testid="session-title"
            title={session.title}
            className={`line-clamp-2 min-w-0 flex-1 break-words font-semibold leading-[1.35] ${
              nested ? 'text-[12px]' : 'text-[13px]'
            } ${nested && !selected ? 'text-text-secondary' : 'text-text-primary'}`}
          >
            {session.title}
          </span>
        </div>

        {/* 第 2 行：预览。所有会话都有这一行。 */}
        <p
          data-testid="session-preview"
          className={`mt-[3px] line-clamp-2 break-words leading-[1.5] ${nested ? 'text-[11px]' : 'text-[12px]'} ${
            preview ? 'text-[var(--card-pv)]' : 'text-[var(--card-meta)]'
          }`}
        >
          {preview || t('workbench.rail.noReply')}
        </p>

        {/* 分支的出处。中性灰小字，点它去原会话，不点就是普通的一行说明。 */}
        {branchOf ? (
          <button
            type="button"
            data-testid="branch-of"
            title={t('workbench.rail.branchOfHint')}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(branchOf.id);
            }}
            className="mt-1 flex max-w-full items-center gap-1 text-left text-[11px] leading-[1.5] text-[var(--card-meta)] hover:text-text-secondary"
          >
            <GitBranch size={12} className="shrink-0" aria-hidden="true" />
            <span className="min-w-0 truncate">
              {t('workbench.rail.branchOf', { title: branchOf.title ?? branchOf.id.slice(0, 8) })}
            </span>
          </button>
        ) : null}

        {/* 第 3 行：状态行。左组可收缩，放不下时时长先截断；「…」固定最右、不收缩。 */}
        <div
          data-testid="session-status"
          className="mt-2 flex h-[17px] min-w-0 items-center gap-1.5 text-[11px] leading-[17px] text-[var(--card-meta)]"
        >
          <div className="flex min-w-0 flex-1 items-center gap-1.5">
            {progress === 'sending' ? (
              <SendingChip />
            ) : progress === 'agent' ? (
              <AgentOnItChip />
            ) : forYou ? (
              <ForYouChip />
            ) : null}
            {progress ? null : (
              <span
                data-testid="session-age"
                className="min-w-0 truncate"
                title={
                  forYou
                    ? t('workbench.forYou.stoppedAt', { time: formatClock(forYou.waitingSince) })
                    : session.last_reply_at
                      ? t('workbench.rail.tsLastReply')
                      : t('workbench.rail.tsLastActive')
                }
              >
                {shortAge(age)}
              </span>
            )}
            {inTmux ? (
              <SquareTerminal
                size={12}
                data-testid="session-in-tmux"
                className="shrink-0"
                aria-label="tmux"
              />
            ) : null}
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
                className="flex shrink-0 items-center gap-0.5 rounded-[4px] px-0.5 hover:bg-bg-hover hover:text-text-primary"
              >
                <ChevronRight
                  size={12}
                  className={`transition-transform duration-200 ${workersExpanded ? 'rotate-90' : ''}`}
                  aria-hidden="true"
                />
                <span className="font-mono">{workerCount}</span>
              </button>
            ) : null}
            {pinned && !inPinnedGroup ? (
              <Pin size={12} fill="currentColor" data-testid="session-pinned" className="shrink-0" aria-hidden />
            ) : null}
          </div>
          <SessionMenu
            session={session}
            pinned={pinned}
            onTogglePin={onTogglePin}
            inTmux={inTmux}
            busyTurn={busyTurn}
            onStopped={() => onStopped?.(session)}
            onDeleted={(result) => onDeleted?.(session, result)}
            onCopy={onCopy}
            copied={copied}
          />
        </div>
      </div>
      </MaybeLiveCard>
    </div>
  );
}
