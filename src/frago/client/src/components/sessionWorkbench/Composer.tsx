/**
 * Composer — 中栏底部的输入区：文本、图片、发送。
 *
 * 发送走 `POST /api/workbench/sessions/{sid}/send`（见 `useSendToSession`），它同时收
 * 文本与图片，允许纯发图。**三家（Claude Code / opencode / codex）都能发**：该续接哪一家、
 * 在哪个目录续接由服务端按会话编号判定，这一侧不按来源设闸。
 *
 * 从前这里对 opencode 与 codex 是硬闸死的，因为那条通道背后写死了一个 claude，别家的
 * 会话编号发过去不报错、而是凭空开一场新的 claude 会话。现在服务端按家族挑 driver
 * （`codex resume <id>` / `opencode -s <id>`），闸门没有存在的理由了。
 *
 * 四条纪律：
 *
 * 1. **发完要能在中栏看到自己刚说的话。** 成功后调 `onSent`，页面把它接到记录流的
 *    `reload` 上，重新拉一次真记录。NEVER 在本地插一条假的——假的没有真实序号与出处，
 *    刷新就没了。
 * 2. **失败不清空。** 文本与已挂的图片原样留着，错误原因照抄服务端的说法，旁边给重试。
 * 3. **图片走粘贴、拖入、选文件三条路**，发送前显示缩略图，逐个可移除。
 * 4. **正在跟哪一家说话要看得见。** 三家的会话摆在同一份清单里，输入框的占位话直接
 *    写出这一场是哪一家——发之前就知道这句话要交给谁。
 */

import { useCallback, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent } from 'react';
import { ImagePlus, Loader2, RotateCcw, SendHorizontal, X } from 'lucide-react';
import { useSendToSession, MAX_ATTACHMENTS } from '@/hooks/useSendToSession';
import { FAMILY_LABEL, type SessionFamily } from '@/hooks/useWorkbenchSessions';

export interface ComposerProps {
  sessionId: string | null;
  /** 这场会话是哪一家。只用来把「在跟谁说话」写进占位话，不参与可发判定。 */
  family: SessionFamily | null;
  /**
   * 请求**出门那一刻**调它。发送这条接口要等整整一轮才回来（上限 180 秒），"在跑"
   * 这件事必须挂在出门那一刻，挂在回来那一刻等于整轮之内界面一动不动。
   */
  onSendStart?: (text: string) => void;
  /** 发送成功后重拉记录。页面接的是记录流的 `reload`。 */
  onSent: () => void | Promise<void>;
  /** 没发出去。页面据此把"在等 agent 开口"撤掉。 */
  onSendFailed?: () => void;
  /** 那句话确实落进会话的时刻。它一变就清空输入框、把按钮放回去。 */
  deliveredAt?: number | null;
}

/**
 * 这场会话为什么发不出去。可发时返回 null。
 *
 * 现在只剩「一场都没选」这一条：三家都发得出去，来源不再是闸门。判定在打字之前就做完，
 * 理由直接写在界面上——「发不出去」和「为什么发不出去」得同时给，只禁用不说明，人只会
 * 以为界面坏了。
 *
 * 会话记录被删掉、目录查不出来这类情况在这一侧判不出来（要问各家的档案），由服务端在
 * 发送那一刻回 409 说明原因，走的是错误提示那条路，NEVER 在这里靠猜提前闸死。
 */
export function blockReason(sessionId: string | null): string | null {
  if (!sessionId) return '从左边挑一场会话，再在这里说话';
  return null;
}

export default function Composer({
  sessionId,
  family,
  onSendStart,
  onSent,
  onSendFailed,
  deliveredAt,
}: ComposerProps) {
  const blocked = blockReason(sessionId);
  const { text, setText, images, addFiles, removeImage, sending, error, canSend, send } =
    useSendToSession(sessionId, {
      enabled: !blocked,
      onSendStart,
      onSent,
      onSendFailed,
      deliveredAt,
    });
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
            placeholder={
              blocked
                ? ''
                : `对${family ? ` ${FAMILY_LABEL[family]} ` : ''}说点什么，图片可以直接粘贴或拖进来`
            }
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
