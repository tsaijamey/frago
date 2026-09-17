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
 * 五条纪律：
 *
 * 1. **发完要能在中栏看到自己刚说的话。** 成功后调 `onSent`，页面把它接到记录流的
 *    `reload` 上，重新拉一次真记录。NEVER 在本地插一条假的——假的没有真实序号与出处，
 *    刷新就没了。
 * 2. **点了发送，输入框当场空出来，那句话搬到上方的信封里。** 从前它留在输入框里等着
 *    "送达"才清：撤又撤不回（话已经交出去了），看着又像没发成功。信封分两档，人一眼
 *    分得清它走到哪了：
 *
 *    | 档 | 什么意思 | 长什么样 |
 *    |---|---|---|
 *    | 已发送 | 请求出了门，会话里还找不到它 | 描边信封，虚线框，弱色 |
 *    | 已入队列 | 进了会话，但 agent 正忙，它排在队列上 | 填充信封（更大），实线框，品牌色，带排队指示 |
 *
 * 3. **失败不丢字。** 输入框还空着就把这一单原样退回去，人已经在打新的字就先收着，
 *    重试重发的仍是原来那一份。错误原因照抄服务端的说法，旁边给重试。
 * 4. **图片走粘贴、拖入、选文件三条路**，发送前显示缩略图，逐个可移除。
 * 5. **正在跟哪一家说话要看得见。** 三家的会话摆在同一份清单里，输入框的占位话直接
 *    写出这一场是哪一家——发之前就知道这句话要交给谁。
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ClipboardEvent,
  type DragEvent,
  type KeyboardEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Mail, Plus, RotateCcw, SendHorizontal } from 'lucide-react';
import { useSendToSession, MAX_ATTACHMENTS } from '@/hooks/useSendToSession';
import AttachmentStrip from '@/components/ui/AttachmentStrip';
import NoiseField from '@/components/ui/NoiseField';
import { useWorkbenchLabels, type SessionFamily } from '@/hooks/useWorkbenchSessions';
import type { OutboundMessage } from '@/hooks/useWorkbenchRecords';

export interface ComposerProps {
  sessionId: string | null;
  /** 这场会话是哪一家。只用来把「在跟谁说话」写进占位话，不参与可发判定。 */
  family: SessionFamily | null;
  /**
   * 这一场此刻在跑没有。只喂上沿那条线上的小人：在跑他踱步，说完了他坐下。
   * 不参与可发判定——跑着的时候照样能插话。
   */
  running?: boolean;
  /**
   * 请求**出门那一刻**调它。发送这条接口要等整整一轮才回来（上限 180 秒），"在跑"
   * 这件事必须挂在出门那一刻，挂在回来那一刻等于整轮之内界面一动不动。交回信封编号。
   */
  onSendStart?: (text: string, attachments: number) => string | void;
  /** 发送成功后重拉记录，并把这一单的信封编号交回去让页面收掉它。 */
  onSent: (outboundId?: string) => void | Promise<void>;
  /** 没发出去。页面据此撤掉这一单的信封与"在等 agent 开口"。 */
  onSendFailed?: (outboundId?: string) => void;
  /** 那句话确实落进会话的时刻。它一变就把发送按钮放回去。 */
  deliveredAt?: number | null;
  /**
   * 已经发出、还没成为新一轮的那些消息（页面接的是记录流的 `outbound`）。
   *
   * 输入框在点发送那一刻就空了，这里是那句话此后唯一看得见的去处。空数组就什么都不画。
   */
  outbound?: OutboundMessage[];
  /**
   * 人在记录流里圈了一段话、按了「引用」交过来的那一份。
   *
   * `at` 是按下的时刻：同一段话连引两次是两件事，光比文字会把第二次吃掉。落进输入框
   * 的形状是三引号包住原话、下面一行 `>>> `，光标停在 `>>> ` 后面——引的是什么和要
   * 接着说什么，在框里一眼分得开。
   */
  quote?: { text: string; at: number } | null;
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
export function blockReason(sessionId: string | null): string | null {
  if (!sessionId) return 'workbench.composer.blockedNoSession';
  return null;
}

/** 走多快，每秒多少像素。慢到眼角能忽略它，快到人偶尔看一眼会发现它换了地方。 */
const WALK_SPEED = 24;

/**
 * 输入框的高度契约：一行 24 像素（与正文的 `leading-6` 同值），最少两行，最多九行。
 *
 * 从前它是死高两行：贴一段长交代进去，人只能在一个两行的窗口里上下推着看，改前面
 * 一句要先滚回去找。现在它随内容长高，到九行封顶——再往上长会把记录流挤没，而人正
 * 需要一边看着上面那几条一边写。到顶之后框内自己滚。
 */
const LINE_PX = 24;
const MIN_LINES = 2;
const MAX_LINES = 9;

/**
 * 输入区上沿那条线上站着的一个人。
 *
 * agent 在跑，他就在这条线上来回踱步；这一轮说完了，他就地坐下打盹。它不表达任何
 * 新状态——「在跑」左栏与记录流早就说过了——它只是把那条一直亮着的横线变成一件
 * 有人气的东西。
 *
 * 两条实现上的约束：
 *
 * 1. **随机走动不能靠 CSS。** keyframes 的路线在写下的那一刻就定死了，来回都是同一段。
 *    这里由 JS 每走完一段临时抽一个新落点、按距离算这一段走多久，位移交给 transition
 *    去补——于是每一段的远近、快慢、朝向都不一样。
 * 2. **停下来要停在当下站的地方。** 位移正走到一半时状态变了，直接把目标位置清零他会
 *    瞬移回原点。所以停的那一刻先量一次他此刻在屏幕上的横坐标，把它当作坐下的位置。
 */
function LineWalker({ walking }: { walking: boolean }) {
  const lane = useRef<HTMLDivElement>(null);
  const mark = useRef<HTMLSpanElement>(null);
  const posRef = useRef(16);
  const [x, setX] = useState(16);
  const [facing, setFacing] = useState(1);
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    if (!walking) return;
    let timer: ReturnType<typeof setTimeout>;
    const step = () => {
      const width = lane.current?.clientWidth ?? 320;
      const target = Math.random() * Math.max(40, width - 24);
      const distance = Math.abs(target - posRef.current);
      const span = Math.max(0.5, distance / WALK_SPEED);
      setFacing(target >= posRef.current ? 1 : -1);
      posRef.current = target;
      setSeconds(span);
      setX(target);
      // 走完一段站着发会儿呆再挑下一个落点，不然就成了没有停顿的机器往返。
      timer = setTimeout(step, span * 1000 + 400 + Math.random() * 1600);
    };
    timer = setTimeout(step, 300);
    return () => clearTimeout(timer);
  }, [walking]);

  useEffect(() => {
    if (walking) return;
    const el = mark.current;
    const laneEl = lane.current;
    if (!el || !laneEl) return;
    const here = el.getBoundingClientRect().left - laneEl.getBoundingClientRect().left;
    posRef.current = here;
    setSeconds(0);
    setX(here);
  }, [walking]);

  return (
    <div
      ref={lane}
      aria-hidden
      data-testid="composer-walker"
      data-walking={walking ? 'yes' : 'no'}
      className="pointer-events-none absolute inset-x-0 top-0 z-10 h-0 select-none"
    >
      <span
        ref={mark}
        className="absolute bottom-[-1px] leading-none will-change-transform"
        style={{
          transform: `translateX(${x}px)`,
          transition: seconds ? `transform ${seconds}s linear` : 'none',
        }}
      >
        {/* 朝向与姿势必须分两层：两者都是 transform，摞在同一个元素上后写的那个会把先写的
            整条抹掉——他一坐下，朝哪边就没人管了。 */}
        <span className="inline-block" style={{ transform: `scaleX(${facing})` }}>
          <span className="composer-walker-sprite block" data-pose={walking ? 'walk' : 'rest'} />
        </span>
      </span>
    </div>
  );
}

export default function Composer({
  sessionId,
  family,
  running = false,
  onSendStart,
  onSent,
  onSendFailed,
  deliveredAt,
  outbound = [],
  quote = null,
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
  const box = useRef<HTMLTextAreaElement>(null);
  /**
   * 引用刚落进来时光标该停在哪。
   *
   * 文字是 React 画上去的，这一刻框里还是旧内容，当场挪光标会挪到一个还不存在的位置上。
   * 先把落点记在这里，等新内容画完那一帧再动。
   */
  const caretTo = useRef<number | null>(null);
  // 引用要接在此刻框里已有的内容后面。效应只盯「按了引用」那一刻，闭包里的 text 停在
  // 更早的一帧上，拿它拼会把人这中间打的字抹掉。
  const textRef = useRef(text);
  textRef.current = text;
  const [dragging, setDragging] = useState(false);
  // 边什么时候活过来：正在打字（框内有焦点）或者正在发。其余时候它冻在最后一帧上——
  // 一直在动的边会让人打字时眼角始终有东西在晃。
  const [focused, setFocused] = useState(false);
  const filePicker = useRef<HTMLInputElement>(null);
  const attachCount = images.length + documents.length;

  // 引用落进输入框。同一段话连引两次也是两次，靠的是按下的时刻，不是文字本身。
  const quoteAt = quote?.at ?? 0;
  const quoteText = quote?.text ?? '';
  useEffect(() => {
    // 时刻为 0 表示这一场还没有人引用过任何东西。
    if (!quoteText || !quoteAt) return;
    const prev = textRef.current;
    const lead = prev && !prev.endsWith('\n') ? '\n' : '';
    const next = `${prev}${lead}"""\n${quoteText}\n"""\n>>> `;
    caretTo.current = next.length;
    setText(next);
  }, [quoteAt, quoteText, setText]);

  /**
   * 高度跟着内容走，顺带把引用刚落进来的那一次光标安顿好。
   *
   * 量高度之前必须先把高度塌回 `auto`：框上还挂着上一帧的高度时，`scrollHeight` 报的
   * 是那个高度，删字永远不会变矮。
   */
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = 'auto';
    const content = el.scrollHeight;
    const ceiling = MAX_LINES * LINE_PX;
    el.style.height = `${Math.min(Math.max(content, MIN_LINES * LINE_PX), ceiling)}px`;
    el.style.overflowY = content > ceiling ? 'auto' : 'hidden';
    if (caretTo.current !== null) {
      const at = caretTo.current;
      caretTo.current = null;
      el.focus();
      el.setSelectionRange(at, at);
      // 引到第十行以后，光标那一行得看得见：框内滚到底。
      el.scrollTop = el.scrollHeight;
    }
  }, [text]);

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
      className={`relative shrink-0 border-t border-border-color bg-bg-primary px-5 py-3 ${
        dragging ? 'bg-bg-hover' : ''
      }`}
    >
      <LineWalker walking={running || sending} />

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

        <AttachmentStrip
          images={images}
          documents={documents}
          onRemoveImage={removeImage}
          onRemoveDocument={removeDocument}
          idPrefix="composer"
        />

        {/* 信封区：已经点了发送、还没成为新一轮的那些话在这儿等着。
            两档的分野是**它进没进这场会话**，不是"发了多久"：
            已发送＝请求出了门、会话里还找不到它；已入队列＝进来了但 agent 正忙，
            引擎把它挂在队列上。后一档在前一档的形态上加重：信封填实、放大、换成品牌色，
            再补一行会跳的点表示还在排。 */}
        {outbound.length ? (
          <div className="flex flex-col gap-1.5">
            {outbound.map((msg) => {
              const queued = msg.state === 'queued';
              return (
                <div
                  key={msg.id}
                  data-testid="composer-outbound"
                  data-state={msg.state}
                  className={`flex items-center gap-2.5 rounded-[10px] px-3 py-2 ${
                    queued
                      ? 'border border-border-accent bg-accent-primary-10'
                      : 'border border-dashed border-border-color bg-bg-subtle'
                  }`}
                >
                  {queued ? (
                    <span className="flex h-[24px] w-[24px] shrink-0 items-center justify-center rounded-[8px] bg-accent-primary text-[var(--text-on-accent)]">
                      <Mail size={15} strokeWidth={2} />
                    </span>
                  ) : (
                    <Mail
                      size={15}
                      strokeWidth={1.5}
                      className="shrink-0 animate-pulse text-text-muted"
                    />
                  )}
                  <span
                    className={`shrink-0 text-[11px] font-medium ${
                      queued ? 'text-accent-primary' : 'text-text-muted'
                    }`}
                  >
                    {t(queued ? 'workbench.composer.queued' : 'workbench.composer.sent')}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[12px] text-text-secondary">
                    {msg.text || t('workbench.composer.attachmentsOnly')}
                  </span>
                  {msg.attachments ? (
                    <span className="shrink-0 text-[11px] text-text-muted">
                      {t('workbench.composer.outboundAttachments', { n: msg.attachments })}
                    </span>
                  ) : null}
                  {queued ? (
                    <span
                      aria-hidden
                      data-testid="composer-outbound-queue-dots"
                      className="flex shrink-0 items-center gap-[3px]"
                    >
                      {[0, 1, 2].map((i) => (
                        <span
                          key={i}
                          className="h-[3px] w-[3px] animate-pulse rounded-full bg-accent-primary"
                          style={{ animationDelay: `${i * 180}ms` }}
                        />
                      ))}
                    </span>
                  ) : null}
                </div>
              );
            })}
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
            ref={box}
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
            className="min-h-[48px] w-full resize-none bg-transparent text-[13px] leading-6 text-text-primary outline-none focus-visible:shadow-none placeholder:text-text-muted disabled:cursor-not-allowed"
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
