import type { TFunction } from 'i18next';
import { Copy, Check, MessageSquare, FolderGit2, Clock } from 'lucide-react';
import type { ClaudeSessionItem } from '@/api/client';
import type { SessionActivity } from './useSessionActivity';
import { HUMAN_META, relativeTime } from './sessionUtils';
import ActivityBadge from './ActivityBadge';

interface SessionListProps {
  t: TFunction;
  loading: boolean;
  error: string | null;
  visible: ClaudeSessionItem[];
  sessions: ClaudeSessionItem[];
  scannedFiles: number;
  detailSid: string | null;
  copiedSid: string | null;
  activity: Record<string, SessionActivity>;
  openDetail: (sid: string) => void;
  handleCopy: (cmd: string, sid: string) => void;
}

export default function SessionList({
  t,
  loading,
  error,
  visible,
  sessions,
  scannedFiles,
  detailSid,
  copiedSid,
  activity,
  openDetail,
  handleCopy,
}: SessionListProps) {
  return (
    <>
      {/* Status line */}
      <div className="cs-statusline">
        {loading
          ? t('claudeSessions.scanning')
          : t('claudeSessions.summary', {
              visible: visible.length,
              total: sessions.length,
              files: scannedFiles,
            })}
      </div>

      {/* Body */}
      {error ? (
        <div className="cs-empty">
          <p>{t('claudeSessions.error')}</p>
          <p className="cs-empty-hint">{error}</p>
        </div>
      ) : visible.length === 0 && !loading ? (
        <div className="cs-empty">
          <p>{t('claudeSessions.empty')}</p>
          <p className="cs-empty-hint">{t('claudeSessions.emptyHint')}</p>
        </div>
      ) : (
        <div className="cs-list">
          {visible.map((s) => {
            const meta = HUMAN_META[s.human];
            const primary = s.title || s.name || s.ai_title || t('claudeSessions.unnamed');
            const preview = s.recap || s.first_user_full;
            const isCopied = copiedSid === s.sid;
            return (
              <div
                key={s.sid}
                className={`cs-row ${detailSid === s.sid ? 'selected' : ''}`}
                onClick={() => openDetail(s.sid)}
              >
                <div className="cs-row-mark" title={s.human_reason} style={{ color: meta.color }}>
                  <meta.Icon size={16} />
                </div>

                <div className="cs-row-main">
                  <div className="cs-row-titleline">
                    <ActivityBadge state={activity[s.sid]} />
                    <span className="cs-row-title">{primary}</span>
                    {s.name && s.title && <span className="cs-row-slug">{s.name}</span>}
                  </div>
                  {preview && <div className="cs-row-preview">{preview}</div>}
                  <div className="cs-row-meta">
                    {s.project && (
                      <span className="cs-chip" title={s.cwd || s.project}>
                        <FolderGit2 size={11} />
                        {s.branch || s.project}
                      </span>
                    )}
                    <span className="cs-chip">
                      <MessageSquare size={11} />
                      {s.n_user_messages + s.n_assistant_messages}
                    </span>
                    <span className="cs-chip">
                      <Clock size={11} />
                      {relativeTime(s.first_interaction_at)}
                    </span>
                  </div>
                </div>

                <button
                  type="button"
                  className={`cs-copy ${isCopied ? 'copied' : ''}`}
                  title={s.resume_command}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleCopy(s.resume_command, s.sid);
                  }}
                >
                  {isCopied ? <Check size={14} /> : <Copy size={14} />}
                  <span>{isCopied ? t('claudeSessions.copiedShort') : t('claudeSessions.resume')}</span>
                </button>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
