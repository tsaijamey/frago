import type { TFunction } from 'i18next';
import { Copy, Check, RefreshCw } from 'lucide-react';
import type { PaSessionItem } from '@/api/client';

interface PaSessionListProps {
  t: TFunction;
  loading: boolean;
  error: string | null;
  sessions: PaSessionItem[];
  detailSid: string | null;
  copiedSid: string | null;
  onRefresh: () => void;
  openDetail: (sid: string, opts?: { title?: string; convKey?: string }) => void;
  handleCopy: (cmd: string, sid: string) => void;
}

export default function PaSessionList({
  t,
  loading,
  error,
  sessions,
  detailSid,
  copiedSid,
  onRefresh,
  openDetail,
  handleCopy,
}: PaSessionListProps) {
  return (
    <>
      <div className="cs-statusline">
        <span>
          {loading
            ? t('claudeSessions.scanning')
            : t('claudeSessions.pa.summary', { count: sessions.length })}
        </span>
        <button
          type="button"
          className="cs-refresh"
          onClick={onRefresh}
          disabled={loading}
          title={t('claudeSessions.rescan')}
        >
          <RefreshCw size={13} className={loading ? 'cs-spin' : ''} />
        </button>
      </div>

      {error ? (
        <div className="cs-empty">
          <p>{t('claudeSessions.error')}</p>
          <p className="cs-empty-hint">{error}</p>
        </div>
      ) : sessions.length === 0 && !loading ? (
        <div className="cs-empty">
          <p>{t('claudeSessions.pa.empty')}</p>
          <p className="cs-empty-hint">{t('claudeSessions.pa.emptyHint')}</p>
        </div>
      ) : (
        <div className="cs-list">
          {sessions.map((s) => {
            const isCopied = copiedSid === s.sid;
            return (
              <div
                key={s.conv_key}
                className={`cs-row ${detailSid === s.sid ? 'selected' : ''}`}
                onClick={() => openDetail(s.sid, { title: s.group_name, convKey: s.conv_key })}
              >
                <div className="cs-row-main">
                  <div className="cs-row-titleline">
                    <span className="cs-row-title">{s.group_name}</span>
                    <span className="cs-row-slug">{s.channel}</span>
                  </div>
                  <div className="cs-row-meta">
                    <span className="cs-chip">{s.sid}</span>
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
