/**
 * SessionItem — 左栏会话卡片，从 SessionRail 拆出，供窗口化渲染与骨架屏共用高度基线。
 */

import { Check, Copy } from 'lucide-react';
import {
  FAMILY_LABEL,
  STATUS_LABEL,
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
  return session.family === 'opencode'
    ? `opencode -s ${session.session_id}`
    : `claude --resume ${session.session_id}`;
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

export default function SessionItem({
  session,
  selected,
  copied,
  onSelect,
  onCopy,
}: {
  session: WorkbenchSession;
  selected: boolean;
  copied: boolean;
  onSelect: (id: string) => void;
  onCopy: (session: WorkbenchSession) => void;
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
      className={`w-full cursor-pointer rounded-[10px] border border-border-color px-[11px] pb-[11px] pt-[10px] text-left transition-colors duration-200 ${
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
        <span className="shrink-0 font-mono text-[11px] text-text-muted">
          {relativeTime(session.last_active_at)}
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

      {session.digest_done ? (
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
