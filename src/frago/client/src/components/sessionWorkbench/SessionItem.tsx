/**
 * SessionItem — 左栏会话卡片，从 SessionRail 拆出，供窗口化渲染与骨架屏共用高度基线。
 */

import { Check, Copy, Pin, Quote } from 'lucide-react';
import {
  activityTs,
  FAMILY_LABEL,
  STATUS_LABEL,
  type ContentMatch,
  type SessionStatus,
  type WorkbenchSession,
} from '@/hooks/useWorkbenchSessions';

const ACCENT_TEXT = 'text-accent-primary';
const ACCENT_BG = 'bg-accent-primary-10';
const ACCENT_RING = 'ring-[1.5px] ring-accent-primary';

const STATUS_DOT: Record<SessionStatus, string> = {
  running: 'bg-accent-primary',
  error: 'bg-accent-error',
  done: 'bg-accent-info',
  idle: 'bg-text-muted',
};

const STATUS_TEXT: Record<SessionStatus, string> = {
  running: 'text-accent-primary',
  error: 'text-accent-error',
  done: 'text-accent-info',
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

export function relativeTime(ts: number, now: number = Date.now()): string {
  if (!ts) return '';
  const delta = Math.max(0, now - ts);
  const minute = 60_000;
  if (delta < minute) return '刚刚';
  if (delta < 60 * minute) return `${Math.floor(delta / minute)} 分钟前`;
  if (delta < 24 * 60 * minute) return `${Math.floor(delta / (60 * minute))} 小时前`;
  const days = Math.floor(delta / (24 * 60 * minute));
  if (days < 30) return `${days} 天前`;
  const d = new Date(ts);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate()
  ).padStart(2, '0')}`;
}

function StatusDot({ status }: { status: SessionStatus }) {
  return (
    <span
      data-status={status}
      title={STATUS_LABEL[status]}
      className={`inline-flex shrink-0 items-center gap-1 text-[11px] ${STATUS_TEXT[status]}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[status]}`} />
      {STATUS_LABEL[status]}
    </span>
  );
}

/**
 * 内容命中摘要。**有命中就顶掉「已完成」那一格**——这一刻人是在找那句话，
 * 卡片上最该出现的就是它，而不是这场会话最后做完了什么。
 */
function ContentHits({ match }: { match: ContentMatch }) {
  const more = match.hit_count - match.hits.length;
  return (
    <div data-testid="content-hits" className="mt-1.5 space-y-1">
      {match.hits.map((hit) => (
        <p
          key={hit.record_id}
          className="line-clamp-2 rounded-[5px] bg-bg-subtle px-1.5 py-1 text-[11px] leading-[1.55] text-text-secondary"
        >
          <Quote size={9} className="mr-1 inline align-baseline text-text-muted" />
          <span className="text-text-muted">{hit.kind === 'user.say' ? '你说 ' : '回复 '}</span>
          {hit.snippet}
        </p>
      ))}
      {more > 0 ? (
        <p className="text-[11px] text-text-muted">
          这场还有 {more} 处{match.capped ? '（不止，太多了没数完）' : ''}
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
      className={`group/session w-full cursor-pointer rounded-[10px] border border-border-color px-[11px] pb-[11px] pt-[10px] text-left transition-colors duration-200 ${
        selected ? `${ACCENT_BG} ${ACCENT_RING} -translate-y-px` : 'bg-bg-card hover:bg-bg-hover'
      }`}
    >
      <div className="flex items-start gap-2">
        <span
          className={`line-clamp-2 min-w-0 flex-1 text-[13px] font-semibold leading-[1.5] ${
            selected ? ACCENT_TEXT : 'text-text-primary'
          }`}
        >
          {session.title}
        </span>
        <span
          className="shrink-0 font-mono text-[11px] text-text-muted"
          title={session.last_reply_at ? '最后一句回复的时刻' : '会话文件最后被动过的时刻'}
        >
          {relativeTime(activityTs(session))}
        </span>
      </div>

      <div className="mt-1.5 flex items-center gap-2">
        <StatusDot status={session.status} />
        <span className="shrink-0 rounded-full bg-bg-subtle px-2 py-[1px] text-[11px] text-text-muted">
          {FAMILY_LABEL[session.family] ?? session.family}
        </span>
        <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-text-muted">
          {dirTail}
        </span>
        {onTogglePin ? (
          <button
            type="button"
            title={pinned ? '取消置顶' : '置顶这场会话'}
            aria-label={pinned ? '取消置顶' : '置顶'}
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
          aria-label="复制恢复命令"
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
          className="mt-1.5 line-clamp-2 text-[11px] leading-[1.55] text-text-secondary"
        >
          <span className="text-text-muted">已完成 </span>
          {session.digest_done}
        </p>
      ) : null}
      {session.digest_stuck ? (
        <p
          data-testid="digest-stuck"
          className="mt-1.5 line-clamp-2 text-[11px] leading-[1.55] text-accent-error"
        >
          <span className="opacity-70">卡在 </span>
          {session.digest_stuck}
        </p>
      ) : null}
    </div>
  );
}
