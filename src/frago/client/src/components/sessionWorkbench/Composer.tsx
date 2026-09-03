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
import { useTranslation } from 'react-i18next';
import { FileText, Loader2, Plus, RotateCcw, SendHorizontal, X } from 'lucide-react';
import { useSendToSession, MAX_ATTACHMENTS } from '@/hooks/useSendToSession';
import NoiseField from '@/components/ui/NoiseField';
import { useWorkbenchLabels, type SessionFamily } from '@/hooks/useWorkbenchSessions';

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
 * 这场会话为什么发不出去。可发时返回 null，发不出去时返回**词表里的键**，取字由界面做。
 *
 * 现在只剩「一场都没选」这一条：三家都发得出去，来源不再是闸门。判定在打字之前就做完，
 * 理由直接写在界面上——「发不出去」和「为什么发不出去」得同时给，只禁用不说明，人只会
 * 以为界面坏了。
 *
 * 会话记录被删掉、目录查不出来这类情况在这一侧判不出来（要问各家的档案），由服务端在
 * 发送那一刻回 409 说明原因，走的是错误提示那条路，NEVER 在这里靠猜提前闸死。
 */
/** 字节数 → 人话。只报已经发生的量，没有分母。 */
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function blockReason(sessionId: string | null): string | null {
  if (!sessionId) return 'workbench.composer.blockedNoSession';
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
  const { t } = useTranslation();
  const { familyLabel } = useWorkbenchLabels();
  const blocked = blockReason(sessionId);
  const {
    text,
    setText,
    images,
    documents,
    addFiles,
    removeImage,
    removeDocument,
    sending,
    error,
    canSend,
    send,
  } = useSendToSession(sessionId, {
      enabled: !blocked,
      onSendStart,
      onSent,
      onSendFailed,
      deliveredAt,
    });
  const [dragging, setDragging] = useState(false);
  // 边什么时候活过来：正在打字（框内有焦点）或者正在发。其余时候它冻在最后一帧上——
  // 一直在动的边会让人打字时眼角始终有东西在晃。
  const [focused, setFocused] = useState(false);
  const filePicker = useRef<HTMLInputElement>(null);
  const attachCount = images.length + documents.length;

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
            {t(blocked)}
          </p>
        ) : null}

        {error ? (
          <div
            data-testid="composer-error"
            className="flex items-start gap-2 rounded-[8px] bg-bg-subtle px-3 py-2 text-[12px] text-accent-error"
          >
            <span className="min-w-0 flex-1 break-words">
              {t('workbench.composer.sendFailed', { reason: error })}
            </span>
            <button
              type="button"
              data-testid="composer-retry"
              onClick={() => void send()}
              disabled={!canSend}
              className="flex shrink-0 items-center gap-1 rounded-[6px] border border-border-color px-2 py-[2px] text-text-secondary hover:bg-bg-hover disabled:opacity-40"
            >
              <RotateCcw size={11} />
              {t('workbench.composer.retry')}
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
                  aria-label={t('workbench.composer.removeImage', { name: image.name })}
                  onClick={() => removeImage(image.id)}
                  className="absolute right-[2px] top-[2px] rounded-full bg-bg-card/90 p-[2px] text-text-secondary hover:text-text-primary"
                >
                  <X size={11} />
                </button>
              </div>
            ))}
          </div>
        ) : null}

        {/* 文档不做缩略图——一份 PDF 的首页缩成 64px 什么也看不出来。它需要的是
            名字（尤其扩展名，agent 靠它判断怎么读）和大小。 */}
        {documents.length ? (
          <div className="flex flex-wrap gap-1.5">
            {documents.map((doc) => (
              <span
                key={doc.id}
                data-testid="composer-doc"
                className="flex max-w-full items-center gap-1.5 rounded-[8px] border border-border-color bg-bg-subtle py-1 pl-2 pr-1 text-[12px] text-text-secondary"
              >
                <FileText size={13} strokeWidth={1.5} className="shrink-0 text-text-muted" />
                <span className="min-w-0 truncate">{doc.name}</span>
                <span className="shrink-0 font-mono text-[11px] text-text-dim">
                  {formatSize(doc.size)}
                </span>
                <button
                  type="button"
                  data-testid="composer-doc-remove"
                  aria-label={t('workbench.composer.removeFile', { name: doc.name })}
                  onClick={() => removeDocument(doc.id)}
                  className="shrink-0 rounded-[4px] p-0.5 text-text-muted hover:text-text-primary"
                >
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
        ) : null}

        {/* **这圈边是两个容器叠出来的，不是 border。**
            外层铺一块会自己生长的色场，内层盖住中间，只在四周露出 2px——于是那 2px
            是活的，而 border 属性画不出会动的颜色。内层必须不透明，否则色场会从正文
            底下透上来。 */}
        <div className="relative rounded-[15px] p-[3px]">
          <div className="pointer-events-none absolute inset-0 overflow-hidden rounded-[15px]">
            {/* 模糊只留 2px：3px 的边上抹 6px 的模糊，色场会被糊成一条均匀的颜色，
                等于白做。scale 稍微放大一点，盖住模糊在四角透出的底。 */}
            <NoiseField
              animate={focused || sending}
              className={`h-full w-full scale-105 blur-[2px] transition-opacity duration-500 ${
                focused || sending ? 'opacity-100' : 'opacity-40'
              }`}
            />
          </div>

          {/* 文本在上、控件在下一行。从前是一整行左右排：文本框有两行高，而 `+` 与发送
              贴着底边，于是占位话在最上面、`+` 在最下面，两者差了一行的距离，看着像是
              没对齐。分成两行之后，控件自己成一条基线。 */}
          <div className="relative min-w-0 rounded-[12px] bg-bg-card px-3 py-2.5">
          <input
            ref={filePicker}
            type="file"
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
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            disabled={Boolean(blocked)}
            rows={2}
            placeholder={
              blocked
                ? ''
                : family
                  ? t('workbench.composer.placeholderWithFamily', { family: familyLabel(family) })
                  : t('workbench.composer.placeholder')
            }
            /* 焦点由外面那圈色场表达，这里就不要再叠一个焦点环——同一件事两种说法，
               而且那个环是绿的，正是要去掉的东西。 */
            className="min-h-[46px] w-full resize-none bg-transparent text-[13px] leading-6 text-text-primary outline-none focus-visible:shadow-none placeholder:text-text-muted disabled:cursor-not-allowed"
          />
          <div className="mt-1 flex items-center gap-2">
            <button
              type="button"
              data-testid="composer-pick"
              aria-label={t('workbench.composer.addAttachment')}
              title={t('workbench.composer.addAttachment')}
              disabled={Boolean(blocked) || attachCount >= MAX_ATTACHMENTS}
              onClick={() => filePicker.current?.click()}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[8px] text-text-muted transition-colors hover:bg-bg-hover hover:text-text-primary disabled:opacity-40"
            >
              <Plus size={16} strokeWidth={1.5} />
            </button>
            <span className="flex-1" />
            <button
              type="button"
              data-testid="composer-send"
              aria-label={t('workbench.composer.send')}
              disabled={!canSend}
              onClick={() => void send()}
              /* 字色走 --text-on-accent 而不是写死白：深色主题的品牌绿被提亮过，白字压在
                 上面对比度不够；那个变量在两套主题下各是各的答案。 */
              className="flex h-7 shrink-0 items-center gap-1.5 rounded-[8px] bg-accent-primary px-3 text-[12px] font-medium text-[var(--text-on-accent)] disabled:opacity-40"
            >
              {sending ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <SendHorizontal size={13} />
              )}
              {sending ? t('workbench.composer.sending') : t('workbench.composer.send')}
            </button>
          </div>
          </div>
        </div>
      </div>
    </div>
  );
}
