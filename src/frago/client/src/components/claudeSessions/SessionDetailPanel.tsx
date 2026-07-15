import { useRef, useState } from 'react';
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
  ImagePlus,
} from 'lucide-react';
import type { ClaudeSessionItem, ClaudeSessionDetail } from '@/api/client';
import type { AttachedImage } from './useSessionDetail';
import MessageBlock from './MessageBlock';

interface SessionDetailPanelProps {
  t: TFunction;
  sessions: ClaudeSessionItem[];
  detailSid: string;
  detailTitle?: string | null;
  detail: ClaudeSessionDetail | null;
  detailLoading: boolean;
  input: string;
  setInput: (s: string) => void;
  images: AttachedImage[];
  addImageFiles: (files: FileList | File[]) => void;
  removeImage: (id: string) => void;
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
  detailTitle,
  detail,
  detailLoading,
  input,
  setInput,
  images,
  addImageFiles,
  removeImage,
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
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const canSend = !sending && (!!input.trim() || images.length > 0);
  return (
    <>
      <div className="cs-drawer-backdrop" onClick={closeDetail} />
      <aside className="cs-drawer">
        <div className="cs-drawer-header">
          <div className="cs-drawer-titlebar">
            <div className="cs-drawer-title">
              {(() => {
                if (detailTitle) return detailTitle;
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

        {/* Composer — forward text + images into the resident tmux claude */}
        <div
          className={`cs-composer ${dragOver ? 'cs-composer--drag' : ''}`}
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes('Files')) {
              e.preventDefault();
              setDragOver(true);
            }
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            if (e.dataTransfer.files.length > 0) {
              e.preventDefault();
              addImageFiles(e.dataTransfer.files);
            }
            setDragOver(false);
          }}
        >
          {sendError && (
            <div className="cs-composer-error">
              <AlertCircle size={13} />
              <span>{t('claudeSessions.sendFailed', { error: sendError })}</span>
            </div>
          )}

          {images.length > 0 && (
            <div className="cs-composer-attachments">
              {images.map((im) => (
                <div key={im.id} className="cs-attachment" title={im.name}>
                  <img src={im.dataUrl} alt={im.name} />
                  <button
                    type="button"
                    className="cs-attachment-remove"
                    onClick={() => removeImage(im.id)}
                    aria-label={t('claudeSessions.removeImage')}
                    title={t('claudeSessions.removeImage')}
                  >
                    <X size={11} />
                  </button>
                </div>
              ))}
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
              onPaste={(e) => {
                const files = Array.from(e.clipboardData.items)
                  .filter((it) => it.kind === 'file' && it.type.startsWith('image/'))
                  .map((it) => it.getAsFile())
                  .filter((f): f is File => f != null);
                if (files.length > 0) {
                  e.preventDefault();
                  addImageFiles(files);
                }
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
            />
            <button
              type="button"
              className="cs-composer-attach"
              onClick={() => fileInputRef.current?.click()}
              disabled={sending}
              title={t('claudeSessions.attachImage')}
              aria-label={t('claudeSessions.attachImage')}
            >
              <ImagePlus size={16} />
            </button>
            <button
              type="button"
              className="cs-composer-send"
              disabled={!canSend}
              onClick={handleSend}
              title={t('claudeSessions.send')}
              aria-label={t('claudeSessions.send')}
            >
              {sending ? <Loader2 size={16} className="cs-spin" /> : <Send size={16} />}
            </button>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            hidden
            onChange={(e) => {
              if (e.target.files && e.target.files.length > 0) {
                addImageFiles(e.target.files);
              }
              e.target.value = ''; // allow re-picking the same file
            }}
          />
        </div>
      </aside>
    </>
  );
}
