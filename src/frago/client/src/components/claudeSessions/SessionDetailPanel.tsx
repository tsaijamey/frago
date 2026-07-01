import type { TFunction } from 'i18next';
import {
  RefreshCw,
  Copy,
  X,
  User,
  Bot,
  Terminal,
  Send,
  Loader2,
  AlertCircle,
} from 'lucide-react';
import type { ClaudeSessionItem, ClaudeSessionDetail } from '@/api/client';
import MessageBlock from './MessageBlock';

interface SessionDetailPanelProps {
  t: TFunction;
  sessions: ClaudeSessionItem[];
  detailSid: string;
  detail: ClaudeSessionDetail | null;
  detailLoading: boolean;
  input: string;
  setInput: (s: string) => void;
  sending: boolean;
  sendError: string | null;
  activation: 'activating' | 'ready' | null;
  pollStalled: boolean;
  streamRef: React.RefObject<HTMLDivElement | null>;
  handleStreamScroll: () => void;
  closeDetail: () => void;
  handleSend: () => void;
  refreshDetail: () => void;
  handleCopy: (cmd: string, sid: string) => void;
}

export default function SessionDetailPanel({
  t,
  sessions,
  detailSid,
  detail,
  detailLoading,
  input,
  setInput,
  sending,
  sendError,
  activation,
  pollStalled,
  streamRef,
  handleStreamScroll,
  closeDetail,
  handleSend,
  refreshDetail,
  handleCopy,
}: SessionDetailPanelProps) {
  return (
    <>
      <div className="cs-drawer-backdrop" onClick={closeDetail} />
      <aside className="cs-drawer">
        <div className="cs-drawer-header">
          <div className="cs-drawer-titlebar">
            <div className="cs-drawer-title">
              {(() => {
                const s = sessions.find((x) => x.sid === detailSid);
                return s ? s.title || s.name || s.ai_title || t('claudeSessions.unnamed') : detailSid;
              })()}
            </div>
            <div className="cs-drawer-sid">{detailSid}</div>
          </div>
          <button type="button" className="cs-drawer-close" onClick={closeDetail}>
            <X size={18} />
          </button>
        </div>

        <div className="cs-drawer-actions">
          <button
            type="button"
            className="cs-copy"
            onClick={() => handleCopy(`claude --resume ${detailSid}`, detailSid)}
          >
            <Copy size={14} />
            <span>{t('claudeSessions.copyResume')}</span>
          </button>
          <button
            type="button"
            className="cs-copy"
            onClick={refreshDetail}
            title={t('claudeSessions.refresh')}
          >
            <RefreshCw size={14} />
            <span>{t('claudeSessions.refresh')}</span>
          </button>
          {detail?.truncated && (
            <span className="cs-drawer-trunc">
              {t('claudeSessions.truncated', {
                shown: detail.returned_messages,
                total: detail.total_messages,
              })}
            </span>
          )}
        </div>

        <div className="cs-drawer-stream" ref={streamRef as React.RefObject<HTMLDivElement>} onScroll={handleStreamScroll}>
          {detailLoading ? (
            <div className="cs-drawer-loading">{t('claudeSessions.loadingDetail')}</div>
          ) : detail && detail.messages.length > 0 ? (
            detail.messages.map((m, i) => {
              const blocks = m.blocks && m.blocks.length > 0
                ? m.blocks
                : [{ type: 'text' as const, text: m.text }];
              // A "user" message carrying only tool results is the tool talking
              // back, not the human — label it accordingly.
              const isToolReturn = m.role === 'user'
                && blocks.every((b) => b.type === 'tool_result');
              const displayRole = isToolReturn ? 'tool' : m.role;
              return (
                <div key={i} className={`cs-msg cs-msg-${displayRole}`}>
                  <div className="cs-msg-role">
                    {displayRole === 'user' ? <User size={12} />
                      : displayRole === 'tool' ? <Terminal size={12} />
                      : <Bot size={12} />}
                    <span>{displayRole}</span>
                  </div>
                  {blocks.map((b, j) => (
                    <MessageBlock key={j} block={b} />
                  ))}
                </div>
              );
            })
          ) : (
            <div className="cs-drawer-loading">{t('claudeSessions.noMessages')}</div>
          )}
        </div>

        {/* Activation / awaiting-reply progress bar (cold start or streaming) */}
        {activation && (
          <div className="cs-activation" role="status" aria-live="polite">
            <Loader2 size={13} className="cs-spin" />
            <span>
              {activation === 'activating'
                ? t('claudeSessions.activating')
                : t('claudeSessions.awaitingReply')}
            </span>
            <div className="cs-activation-bar">
              <div className="cs-activation-bar-fill" />
            </div>
          </div>
        )}

        {/* Poll gave up before the reply landed — let the user re-check. */}
        {pollStalled && !activation && (
          <div className="cs-activation cs-activation-stalled" role="status">
            <AlertCircle size={13} />
            <span>{t('claudeSessions.replyStalled')}</span>
            <button type="button" className="cs-copy" onClick={refreshDetail}>
              <RefreshCw size={13} />
              <span>{t('claudeSessions.refresh')}</span>
            </button>
          </div>
        )}

        {/* Composer — forward input into the resident tmux claude */}
        <div className="cs-composer">
          {sendError && (
            <div className="cs-composer-error">
              <AlertCircle size={13} />
              <span>{t('claudeSessions.sendFailed', { error: sendError })}</span>
            </div>
          )}
          <div className="cs-composer-row">
            <textarea
              className="cs-composer-input"
              value={input}
              rows={2}
              placeholder={t('claudeSessions.composerPlaceholder')}
              disabled={sending}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
            />
            <button
              type="button"
              className="cs-composer-send"
              disabled={sending || !input.trim()}
              onClick={handleSend}
              title={t('claudeSessions.send')}
              aria-label={t('claudeSessions.send')}
            >
              {sending ? <Loader2 size={16} className="cs-spin" /> : <Send size={16} />}
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}
