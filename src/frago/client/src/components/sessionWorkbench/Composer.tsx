/**
 * Composer — 中栏底部的输入区：文本、图片、发送。
 *
 * 发送走已经在跑的现成通道 `POST /api/claude-sessions/{sid}/send`（见 `useSendToSession`），
 * 它同时收文本与图片，允许纯发图。四条纪律：
 *
 * 1. **发完要能在中栏看到自己刚说的话。** 成功后调 `onSent`，页面把它接到记录流的
 *    `reload` 上，重新拉一次真记录。NEVER 在本地插一条假的——假的没有真实序号与出处，
 *    刷新就没了。
 * 2. **失败不清空。** 文本与已挂的图片原样留着，错误原因照抄服务端的说法，旁边给重试。
 * 3. **图片走粘贴、拖入、选文件三条路**，发送前显示缩略图，逐个可移除。
 * 4. **不能发的会话在打字之前就摆明。** 那条通道背后是 tmux 里的 claude，别家（opencode /
 *    codex）的会话编号在 claude 的档案里根本不存在——发过去不报错，而是凭空开一场新会话。
 *    所以这类会话整个输入区禁用并写明原因，NEVER 让人打完字才发现发不出去。
 */

import { useCallback, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent } from 'react';
import { ImagePlus, Loader2, RotateCcw, SendHorizontal, X } from 'lucide-react';
import { useSendToSession, MAX_ATTACHMENTS } from '@/hooks/useSendToSession';
import type { SessionFamily } from '@/hooks/useWorkbenchSessions';

export interface ComposerProps {
  sessionId: string | null;
  /** 这场会话是哪一家。取不到时按不可发处理。 */
  family: SessionFamily | null;
  /** 发送成功后重拉记录。页面接的是记录流的 `reload`。 */
  onSent: () => void | Promise<void>;
}

/**
 * 这场会话为什么发不出去。可发时返回 null。
 *
 * 判定在打字之前就做完，理由直接写在界面上——「发不出去」和「为什么发不出去」得同时给，
 * 只禁用不说明，人只会以为界面坏了。
 */
export function blockReason(sessionId: string | null, family: SessionFamily | null): string | null {
  if (!sessionId) return '从左边挑一场会话，再在这里说话';
  if (family !== 'claude-code') {
    const label = family === 'codex' ? 'codex' : 'opencode';
    return `${label} 的会话发不出去：发送通道背后是 tmux 里的 claude，这个会话编号在它那儿不存在`;
  }
  return null;
}

export default function Composer({ sessionId, family, onSent }: ComposerProps) {
  const blocked = blockReason(sessionId, family);
  const { text, setText, images, addFiles, removeImage, sending, error, canSend, send } =
    useSendToSession(sessionId, { enabled: !blocked, onSent });
  const [dragging, setDragging] = useState(false);
  const filePicker = useRef<HTMLInputElement>(null);

  const takeFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;
      void addFiles(files);
    },
    [addFiles]
  );

  const handlePaste = useCallback(
    (e: ClipboardEvent<HTMLTextAreaElement>) => {
      const files = e.clipboardData?.files;
      if (!files || files.length === 0) return;
      // 截图粘贴进来的是文件而不是文字，拦下来当附件，别让它变成一串乱码落进文本框。
      e.preventDefault();
      takeFiles(files);
    },
    [takeFiles]
  );

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragging(false);
      if (blocked) return;
      takeFiles(e.dataTransfer?.files ?? null);
    },
    [blocked, takeFiles]
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      // 回车换行，Cmd/Ctrl+回车才发。中栏里打的多是整段交代，回车即发会把话腰斩。
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        if (canSend) void send();
      }
    },
    [canSend, send]
  );

  return (
    <div
      data-testid="composer"
      onDragOver={(e) => {
        e.preventDefault();
        if (!blocked) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`shrink-0 border-t border-border-color bg-bg-primary px-5 py-3 ${
        dragging ? 'bg-bg-hover' : ''
      }`}
    >
      <div className="mx-auto flex w-full min-w-0 max-w-[760px] flex-col gap-2">
        {blocked ? (
          <p
            data-testid="composer-blocked"
            className="rounded-[8px] bg-bg-subtle px-3 py-2 text-[12px] text-text-secondary"
          >
            {blocked}
          </p>
        ) : null}

        {error ? (
          <div
            data-testid="composer-error"
            className="flex items-start gap-2 rounded-[8px] bg-bg-subtle px-3 py-2 text-[12px] text-accent-error"
          >
            <span className="min-w-0 flex-1 break-words">没发出去：{error}</span>
            <button
              type="button"
              data-testid="composer-retry"
              onClick={() => void send()}
              disabled={!canSend}
              className="flex shrink-0 items-center gap-1 rounded-[6px] border border-border-color px-2 py-[2px] text-text-secondary hover:bg-bg-hover disabled:opacity-40"
            >
              <RotateCcw size={11} />
              重试
            </button>
          </div>
        ) : null}

        {images.length ? (
          <div className="flex flex-wrap gap-2">
            {images.map((image) => (
              <div
                key={image.id}
                data-testid="composer-thumb"
                className="relative h-16 w-16 overflow-hidden rounded-[8px] border border-border-color bg-bg-subtle"
              >
                <img src={image.dataUrl} alt={image.name} className="h-full w-full object-cover" />
                <button
                  type="button"
                  data-testid="composer-remove"
                  aria-label={`移除 ${image.name}`}
                  onClick={() => removeImage(image.id)}
                  className="absolute right-[2px] top-[2px] rounded-full bg-bg-card/90 p-[2px] text-text-secondary hover:text-text-primary"
                >
                  <X size={11} />
                </button>
              </div>
            ))}
          </div>
        ) : null}

        <div className="flex min-w-0 items-end gap-2 rounded-[10px] border border-border-color bg-bg-card px-3 py-2 focus-within:border-accent-primary">
          <button
            type="button"
            data-testid="composer-pick"
            aria-label="添加图片"
            disabled={Boolean(blocked) || images.length >= MAX_ATTACHMENTS}
            onClick={() => filePicker.current?.click()}
            className="shrink-0 pb-[3px] text-text-muted hover:text-text-primary disabled:opacity-40"
          >
            <ImagePlus size={16} />
          </button>
          <input
            ref={filePicker}
            type="file"
            accept="image/*"
            multiple
            hidden
            data-testid="composer-file"
            onChange={(e) => {
              takeFiles(e.target.files);
              e.target.value = '';
            }}
          />
          <textarea
            data-testid="composer-input"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onPaste={handlePaste}
            onKeyDown={handleKeyDown}
            disabled={Boolean(blocked)}
            rows={2}
            placeholder={blocked ? '' : '说点什么，图片可以直接粘贴或拖进来'}
            className="min-h-[44px] min-w-0 flex-1 resize-none bg-transparent text-[13px] leading-6 text-text-primary outline-none placeholder:text-text-muted disabled:cursor-not-allowed"
          />
          <button
            type="button"
            data-testid="composer-send"
            aria-label="发送"
            disabled={!canSend}
            onClick={() => void send()}
            className="flex shrink-0 items-center gap-1 rounded-[8px] bg-accent-primary px-3 py-[6px] text-[12px] text-white disabled:opacity-40"
          >
            {sending ? <Loader2 size={13} className="animate-spin" /> : <SendHorizontal size={13} />}
            {sending ? '发送中' : '发送'}
          </button>
        </div>
      </div>
    </div>
  );
}
