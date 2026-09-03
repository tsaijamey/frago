/**
 * SessionItem — 左栏清单里的一行，从 SessionRail 拆出，供窗口化渲染与骨架屏共用高度基线。
 */

import { useTranslation } from 'react-i18next';
import { Check, Copy, Pin, Quote } from 'lucide-react';
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
  contentMatch,
  onSelect,
  onCopy,
  onTogglePin,
}: {
  session: WorkbenchSession;
  selected: boolean;
  copied: boolean;
  /** 这场会话在不在置顶名单里。 */
  pinned?: boolean;
  /** 这场会话在内容检索里命中了什么。没搜内容、或这场没命中时为 null。 */
  contentMatch?: ContentMatch | null;
  onSelect: (id: string) => void;
  onCopy: (session: WorkbenchSession) => void;
  /** 置顶开关。不给就不长这颗按钮——骨架屏与只读场景用得上。 */
  onTogglePin?: (session: WorkbenchSession) => void;
}) {
  const { t } = useTranslation();
  const { familyLabel } = useWorkbenchLabels();
  const dirTail = session.directory.split('/').filter(Boolean).slice(-2).join('/');
  const cmd = resumeCommand(session);
  return (
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
      /* **不再是一张卡。** 从前每一场会话都有自己的边框与卡底，一屏摆下五六张，人看到
         的先是五六个方框，然后才是里面的字。清单要的是一列可扫读的行：平时没有任何容器，
         鼠标经过才浮出一层底，选中的那一场换成品牌绿淡底——整行换底，不靠任何单边色条。
         绿环去掉了：淡底加标题转绿已经足够把它从一列灰字里分出来，再加一圈亮绿只是喊。 */
      className={`group/session w-full cursor-pointer rounded-[8px] px-2.5 py-2 text-left transition-colors duration-200 ${
        selected ? ACCENT_BG : 'hover:bg-bg-hover'
      }`}
    >
      <div className="flex items-start gap-2">
        <span
          className={`line-clamp-2 min-w-0 flex-1 text-[13px] font-medium leading-[1.5] ${
            selected ? ACCENT_TEXT : 'text-text-primary'
          }`}
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
  );
}
