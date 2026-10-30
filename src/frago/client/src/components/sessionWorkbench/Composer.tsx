/**
 * Composer — 中栏底部的输入区：文本、图片、发送。
 *
 * 发送走 `POST /api/workbench/sessions/{sid}/send`（见 `useSendToSession`），它同时收
 * 文本与图片，允许纯发图。**四家（Claude Code / opencode / codex / CoreAgent）都能发**：
 * 该续接哪一家、在哪个目录续接由服务端按会话编号判定，这一侧不按来源设闸。
 *
 * 从前这里对 opencode 与 codex 是硬闸死的，因为那条通道背后写死了一个 claude，别家的
 * 会话编号发过去不报错、而是凭空开一场新的 claude 会话。现在服务端按家族挑 driver
 * （`codex resume <id>` / `opencode -s <id>`），闸门没有存在的理由了。
 *
 * CoreAgent 那一家最后放开：它没有挂在终端里的交互界面，从前每次运行都是跑完就退出的
 * 一个进程，所以整个输入区被换成一句「这一场只能回看」。现在内核认续接——给它这一场的
 * 编号，它先把这一场的记录读回来当记忆，再接着往下想，所以这里与另外三家同一条路。
 *
 * 五条纪律：
 *
 * 1. **发完要能在中栏看到自己刚说的话。** 成功后调 `onSent`，页面把它接到记录流的
 *    `reload` 上，重新拉一次真记录。NEVER 在本地插一条假的——假的没有真实序号与出处，
 *    刷新就没了。
 * 2. **点了发送，输入框当场空出来，那句话搬到上方的气泡里。** 气泡与记录流里的「You
 *    said」同一种画法，下面挂同一串步骤名（见 `SendProgress`）：
 *
 *    | 档 | 什么意思 | 长什么样 |
 *    |---|---|---|
 *    | On its way | 请求出了门，会话里还找不到它 | 虚线框、转圈 |
 *    | Queued | 进了会话，但 agent 正忙，它排在队列上 | 中性实线框加时钟，不用绿 |
 *
 *    全部落进记录流之后留一行「↑ … moved up into the conversation · Show」交代去处。
 *
 * 3. **失败不丢字。** 输入框还空着就把这一单原样退回去，人已经在打新的字就先收着，
 *    重试重发的仍是原来那一份。错误原因照抄服务端的说法，旁边给重试。
 * 4. **图片走粘贴、拖入、选文件三条路**，发送前显示缩略图，逐个可移除。
 * 5. **正在跟哪一家说话要看得见。** 三家的会话摆在同一份清单里，输入框的占位话直接
 *    写出这一场是哪一家——发之前就知道这句话要交给谁。
 * 6. **敲 `/` 挑 skill。** 行首或空白后敲 `/` 弹出 frago 集中管理的 skill 清单（名字加一截
 *    说明），接着打的字用来筛；挑中后 `/…` 那几个字从框里抹掉，换成框里上方的一枚引用
 *    （名字加更短的一截说明），可逐个去掉。发出去只带名字，服务端把全文嵌进这句话——不走
 *    任何一家的原生写法，codex 那种把 `/名字` 当自己命令拦下的事就不会发生。
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type DragEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import {
  ArrowDown,
  ArrowUp,
  Clock,
  CornerUpLeft,
  GitBranch,
  GitBranchPlus,
  ListOrdered,
  Loader2,
  RotateCcw,
  ShieldAlert,
  Trash2,
  X,
} from 'lucide-react';
import { useSendToSession } from '@/hooks/useSendToSession';
import type { QueuedMessageItem } from '@/hooks/useSessionQueue';
import AttachmentStrip from '@/components/ui/AttachmentStrip';
import PromptComposerBox, { slashQuery } from './PromptComposerBox';
import { useWorkbenchLabels, type SessionFamily } from '@/hooks/useWorkbenchSessions';
import type { OutboundMessage, SendTrail } from '@/hooks/useWorkbenchRecords';
import SendProgress from './SendProgress';

export { slashQuery };

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
  /**
   * 服务端说这一单是**排队投进去的**：那一场此刻正忙，这句话要等当前这一步结束才被读到。
   * 页面据此把信封标成「排队中」——一路显示「已发送」会让人以为话已经被接住了。
   */
  onQueued?: (outboundId?: string) => void;
  /** 那句话确实落进会话的时刻。它一变就把发送按钮放回去。 */
  deliveredAt?: number | null;
  /**
   * 已经发出、还没成为新一轮的那些消息（页面接的是记录流的 `outbound`）。
   *
   * 输入框在点发送那一刻就空了，这里是那句话此后唯一看得见的去处。空数组就什么都不画。
   */
  outbound?: OutboundMessage[];
  /**
   * 每一句话的进度（页面接的是记录流的 `trails`）。待发气泡下面、报错条里各挂一行。
   */
  trails?: SendTrail[];
  /**
   * 「↑ … moved up into the conversation · Show」里的 Show：把记录流滚到那句话。
   * 不给就不画 Show。
   */
  onShowInStream?: (recordId: string) => void;
  /**
   * 人在记录流里圈了一段话、按了「引用」交过来的那一份。
   *
   * `at` 是按下的时刻：同一段话连引两次是两件事，光比文字会把第二次吃掉。落进输入框
   * 的形状是三引号包住原话、下面一行 `>>> `，光标停在 `>>> ` 后面——引的是什么和要
   * 接着说什么，在框里一眼分得开。
   *
   * 从右栏暂存列表「填入」的那一份还带着当时写下的想法 `note`，接在 `>>> ` 后面，光标
   * 停在想法末尾——人多半是顺着那句想法往下补完决定。
   */
  quote?: { text: string; note?: string; at: number } | null;
  /**
   * 从 FileViewer「打包批注填入对话框」送过来的整份新 prompt。
   * 直接填入输入框并展示关联存档路径提示条，供人检视后按 Send 发送。
   */
  packedPrompt?: { text: string; count: number; tracePath: string; at: number } | null;
  /**
   * 人在决定卡片上点出来的那一句答复，等着整句投出。
   *
   * 走的是跟「发送」同一条路（信封、进度、失败退回），只是不经输入框：框里人正在打的字
   * 原样留着。`at` 与引用同理——同一句答复发两次是两件事，光比文字会把第二次吃掉。
   */
  answer?: { text: string; at: number } | null;
  /**
   * 从 FileViewer「发送修改到对话」直接投出的通知消息，走与卡片答复相同的整句发送管线，
   * 不覆盖用户正在输入框里编写的草稿。
   */
  directSend?: { text: string; at: number } | null;
  /**
   * 这场此刻的上下文水位（最后一道用量刻度报的提示词大小）。null = 还没读到刻度。
   *
   * 「交接到新会话」只在它到了 {@link HANDOFF_MIN_CONTEXT} 才放开：没那么长的会话换场只会
   * 丢细节，换不来速度。
   */
  contextTokens?: number | null;
  /** 按下「交接到新会话」。不给就不画那个按钮。 */
  onHandoff?: () => void;
  /** 交接请求还在路上。 */
  handingOff?: boolean;
  /**
   * 输入框上方那一行原地提示，与「↑ … moved up into the conversation · Show」同一个位置、同一种
   * 写法。起分支之后用它说「已在新会话处理：<标题> · 打开」，起失败时换成失败原因。
   * 页面切走会话或人点了关闭，页面就把它撤掉。
   */
  notice?: ComposerNotice | null;
  /**
   * 按下「带回主线」。只有分支会话、而且它的原会话还在清单里时页面才给，不给就不画。
   * 切回原会话、把最后一段回复按引用格式填进去都由页面做，这里只是一颗按钮。
   */
  onBringBack?: () => void;
  /**
   * 会话自有消息队列里的待发消息（按先进先出顺序排列，首项为最早一条）。
   */
  queueItems?: QueuedMessageItem[];
  /**
   * 检测到末尾 `[end, end-5]` 轮会话存在未作答的交互卡时为 true，暂停自动注入。
   */
  queueBlockedByCard?: boolean;
  /**
   * 把当前输入区的内容加入会话自有消息队列（不在 agent 执行过程中发进其原生运行队列）。
   */
  onEnqueue?: (
    text: string,
    images: string[],
    documents: { name: string; data: string }[],
    skills: string[]
  ) => Promise<unknown>;
  /** 从会话自有消息队列中删除指定消息。 */
  onRemoveQueueItem?: (itemId: string) => void | Promise<void>;
  /** 调整会话自有消息队列中的顺序。 */
  onMoveQueueItem?: (itemId: string, direction: 'up' | 'down') => void | Promise<void>;
}

/** 输入框上方那一行原地提示。 */
export interface ComposerNotice {
  text: string;
  /** error＝起失败了，字走报错色；plain＝中性。 */
  tone?: 'plain' | 'error';
  /** 行尾的动作（「打开」）。不给就不画。 */
  actionLabel?: string;
  onAction?: () => void;
  onDismiss?: () => void;
}

/** 输入框右下角常驻的三个数。取不到的那一项是 null，逐项决定显不显示。 */
export interface ComposerUsage {
  /** 当前模型。中途切过模型，这里是最后一条带模型名的记录报的那个。 */
  model: string;
  /** 上下文水位。null = 这场还没留下用量刻度。 */
  context: number | null;
  /** 这场一路烧掉的累计。null = 同上。 */
  total: number | null;
}

/**
 * 上下文到多大才放开「交接到新会话」。
 *
 * 取的是人自己的体感：到三十万上下，模型明显变慢、变笨，换一场接着做才划算。
 */
export const HANDOFF_MIN_CONTEXT = 300_000;

/** 悬停说明里那种 k 为单位的写法：312k。 */
function formatK(n: number): string {
  return `${Math.round(n / 1000)}k`;
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
  onQueued,
  deliveredAt,
  outbound = [],
  trails = [],
  onShowInStream,
  quote = null,
  packedPrompt = null,
  answer = null,
  directSend = null,
  contextTokens = null,
  onHandoff,
  handingOff = false,
  notice = null,
  onBringBack,
  queueItems = [],
  queueBlockedByCard = false,
  onEnqueue,
  onRemoveQueueItem,
  onMoveQueueItem,
}: ComposerProps) {
  const { t } = useTranslation();
  const { familyLabel } = useWorkbenchLabels();
  const blocked = blockReason(sessionId);
  const [enqueueing, setEnqueueing] = useState(false);
  const [queueError, setQueueError] = useState<string | null>(null);
  const {
    text,
    setText,
    images,
    documents,
    addFiles,
    removeImage,
    removeDocument,
    skills: picked,
    addSkill,
    removeSkill,
    sending,
    error,
    canSend,
    send,
    retry,
    sendText,
    held,
  } = useSendToSession(sessionId, {
      enabled: !blocked,
      onSendStart,
      onSent,
      onSendFailed,
      onQueued,
      deliveredAt,
    });

  useEffect(() => {
    setQueueError(null);
    setEnqueueing(false);
  }, [sessionId]);

  const hasDraft = Boolean(
    text.trim() || images.length > 0 || documents.length > 0 || picked.length > 0
  );
  const canEnqueue = Boolean(!blocked && sessionId && onEnqueue && !enqueueing && hasDraft);

  const handleEnqueue = useCallback(async () => {
    if (!sessionId || !onEnqueue || enqueueing || !hasDraft) return;
    const draftText = text.trim();
    const draftImages = [...images];
    const draftDocs = [...documents];
    const draftSkills = [...picked];
    setEnqueueing(true);
    setQueueError(null);
    setPackedBanner(null);
    setText('');
    for (const sk of draftSkills) removeSkill(sk.name);
    for (const im of draftImages) removeImage(im.id);
    for (const doc of draftDocs) removeDocument(doc.id);
    try {
      await onEnqueue(
        draftText,
        draftImages.map((im) => im.dataUrl),
        draftDocs.map((d) => ({ name: d.name, data: d.dataUrl })),
        draftSkills.map((s) => s.name)
      );
    } catch (e) {
      setQueueError(e instanceof Error ? e.message : String(e));
      setText(draftText);
      for (const sk of draftSkills) addSkill(sk);
    } finally {
      setEnqueueing(false);
    }
  }, [
    sessionId,
    onEnqueue,
    enqueueing,
    hasDraft,
    text,
    images,
    documents,
    picked,
    setText,
    removeSkill,
    removeImage,
    removeDocument,
    addSkill,
  ]);
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
  const attachCount = images.length + documents.length;
  const trailOf = new Map(trails.map((tr) => [tr.id, tr]));
  /**
   * 气泡全部落进记录流之后，输入框上方留一行交代它们去了哪。
   *
   * 数的是**这一批**：从上一次输入框上方空着算起发出的那几句。下一次发送或换会话时
   * 这一行消失——那时上方又有了新的气泡，或者说的已是另一场。
   */
  const [movedUp, setMovedUp] = useState<string[]>([]);
  const batch = useRef<string[]>([]);
  const outboundIds = outbound.map((m) => m.id).join(',');
  // 换会话先清——这一条必须排在下面那条前面：挂载那一拍两条都跑，排在后面会把刚记下的
  // 这一批一起清掉
  useEffect(() => {
    batch.current = [];
    setMovedUp([]);
  }, [sessionId]);
  useEffect(() => {
    if (outbound.length) {
      if (!batch.current.length) setMovedUp([]);
      for (const m of outbound) if (!batch.current.includes(m.id)) batch.current.push(m.id);
      return;
    }
    if (!batch.current.length) return;
    const landed = batch.current.filter((id) => {
      const tr = trails.find((x) => x.id === id);
      return tr && tr.recordId && tr.steps.failed === undefined && !tr.expired;
    });
    batch.current = [];
    setMovedUp(landed);
    // 只在气泡清单变化时判一次；进度随后的变化不该让这一行闪
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outboundIds]);
  const movedTarget = movedUp
    .map((id) => trails.find((tr) => tr.id === id)?.recordId)
    .find((rid): rid is string => Boolean(rid));
  /** 刚失败的那一份：报错条里画它的步骤链。 */
  const failedTrail = error
    ? [...trails].reverse().find((tr) => tr.steps.failed !== undefined)
    : undefined;

  // 引用落进输入框。同一段话连引两次也是两次，靠的是按下的时刻，不是文字本身。
  const quoteAt = quote?.at ?? 0;
  const quoteText = quote?.text ?? '';
  const quoteNote = quote?.note ?? '';
  useEffect(() => {
    // 时刻为 0 表示这一场还没有人引用过任何东西。
    if (!quoteText || !quoteAt) return;
    const prev = textRef.current;
    const lead = prev && !prev.endsWith('\n') ? '\n' : '';
    const next = `${prev}${lead}"""\n${quoteText}\n"""\n>>> ${quoteNote}`;
    caretTo.current = next.length;
    setText(next);
  }, [quoteAt, quoteText, quoteNote, setText]);

  // 文档批注打包填入输入框：附带可溯源存档路径条，供人检视或补充后按 Send 发送。
  const [packedBanner, setPackedBanner] = useState<{ count: number; tracePath: string } | null>(
    null
  );
  useEffect(() => {
    setPackedBanner(null);
  }, [sessionId]);
  useEffect(() => {
    if (sending) setPackedBanner(null);
  }, [sending]);
  const packedAt = packedPrompt?.at ?? 0;
  const packedText = packedPrompt?.text ?? '';
  const packedCount = packedPrompt?.count ?? 0;
  const packedTrace = packedPrompt?.tracePath ?? '';
  useEffect(() => {
    if (!packedText || !packedAt) return;
    caretTo.current = packedText.length;
    setText(packedText);
    setPackedBanner({ count: packedCount, tracePath: packedTrace });
  }, [packedAt, packedText, packedCount, packedTrace, setText]);

  // 卡片答复整句投出。时刻为 0 表示这一场还没点过卡片；记下已消费的序号，防止重挂载或同帧重渲染重复投出。
  const lastAnswerAt = useRef(0);
  const answerAt = answer?.at ?? 0;
  const answerText = answer?.text ?? '';
  useEffect(() => {
    if (!answerText || !answerAt || lastAnswerAt.current === answerAt) return;
    lastAnswerAt.current = answerAt;
    void sendText(answerText);
    // 只盯「点了卡片」那一刻；sendText 换了引用不是又点了一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [answerAt, answerText]);

  const lastDirectSendAt = useRef(0);
  const directSendAt = directSend?.at ?? 0;
  const directSendText = directSend?.text ?? '';
  useEffect(() => {
    if (!directSendText || !directSendAt || lastDirectSendAt.current === directSendAt) return;
    lastDirectSendAt.current = directSendAt;
    void sendText(directSendText);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [directSendAt, directSendText]);

  const takeFiles = useCallback(
    (files: FileList | File[] | null) => {
      if (!files || files.length === 0) return;
      void addFiles(files);
    },
    [addFiles]
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

  return (
    <div
      data-testid="composer"
      onDragOver={(e) => {
        e.preventDefault();
        if (!blocked) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`relative shrink-0 border-t border-border-color bg-bg-primary px-4 py-3 ${
        dragging ? 'bg-bg-hover' : ''
      }`}
    >
      <LineWalker walking={running || sending} />

      {/* 输入框跟上面的记录流同宽、同左边距：两者左边界对齐，视线上下直着走。
          收窄居中会让它看起来是另一样东西、缩在中间，跟正文错开一整块。 */}
      <div className="flex w-full min-w-0 flex-col gap-2">
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
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="break-words">
                {t('workbench.composer.sendFailed', { reason: error })}
              </span>
              {failedTrail ? <SendProgress trail={failedTrail} /> : null}
              <span data-testid="composer-kept" className="text-[11px] text-text-muted">
                {held ? t('workbench.composer.heldForRetry') : t('workbench.composer.textIsBack')}
              </span>
            </span>
            <button
              type="button"
              data-testid="composer-retry"
              onClick={() => void retry()}
              disabled={!canSend}
              className="flex shrink-0 items-center gap-1 rounded-[6px] border border-border-color px-2 py-[2px] text-text-secondary hover:bg-bg-hover disabled:opacity-40"
            >
              <RotateCcw size={11} />
              {t('workbench.composer.retry')}
            </button>
          </div>
        ) : null}

        {queueError ? (
          <div
            data-testid="composer-queue-error"
            className="flex items-center justify-between gap-2 rounded-[8px] bg-bg-subtle px-3 py-2 text-[12px] text-accent-error"
          >
            <span className="min-w-0 flex-1 break-words">
              {t('workbench.composer.sendFailed', { reason: queueError })}
            </span>
            <button
              type="button"
              onClick={() => setQueueError(null)}
              className="flex h-4 w-4 shrink-0 items-center justify-center rounded-[4px] text-text-muted hover:text-text-primary"
            >
              <X size={11} />
            </button>
          </div>
        ) : null}

        {/* 会话自有消息队列：不在 agent 执行时发进其原生运行队列，堆积在此，
            当且仅当会话 stop 且 [end, end-5] 轮无交互卡时自动注入最早一条并从队列移除。 */}
        {queueItems.length > 0 ? (
          <div
            data-testid="session-message-queue"
            data-blocked-by-card={queueBlockedByCard ? 'yes' : 'no'}
            className="flex min-w-0 flex-col gap-1.5 rounded-[10px] border border-border-color bg-bg-subtle px-3 py-2"
          >
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-1.5">
                <ListOrdered size={13} className="shrink-0 text-text-secondary" />
                <span className="shrink-0 text-[12px] font-medium text-text-primary">
                  {t('workbench.queue.title')}
                </span>
                <span
                  data-testid="session-queue-count"
                  className="shrink-0 rounded-full bg-bg-secondary px-2 py-[1px] text-[11px] font-medium text-text-secondary"
                >
                  {t('workbench.queue.count', { n: queueItems.length })}
                </span>
              </div>
              <span
                data-testid="session-queue-status"
                className={`flex min-w-0 items-center gap-1 text-[11px] ${
                  queueBlockedByCard ? 'text-accent-warning' : 'text-text-muted'
                }`}
              >
                {queueBlockedByCard ? (
                  <ShieldAlert size={12} className="shrink-0 text-accent-warning" />
                ) : (
                  <Clock size={12} className="shrink-0 text-text-muted" />
                )}
                <span className="truncate">
                  {queueBlockedByCard
                    ? t('workbench.queue.blockedByCard')
                    : running
                      ? t('workbench.queue.waitingForStop')
                      : t('workbench.queue.readyToInject')}
                </span>
              </span>
            </div>

            <div className="flex flex-col gap-1">
              {queueItems.map((item, idx) => (
                <div
                  key={item.id}
                  data-testid="session-queue-item"
                  data-earliest={idx === 0 ? 'yes' : 'no'}
                  className="flex min-w-0 items-center gap-2 rounded-[7px] border border-border-color bg-bg-primary px-2.5 py-1.5"
                >
                  <span className="shrink-0 font-mono text-[11px] text-text-muted">
                    #{idx + 1}
                  </span>
                  {idx === 0 ? (
                    <span
                      data-testid="session-queue-earliest-badge"
                      className="shrink-0 rounded-[4px] bg-bg-subtle px-1.5 py-[1px] text-[10px] font-medium text-text-secondary"
                    >
                      {t('workbench.queue.nextBadge')}
                    </span>
                  ) : null}
                  {item.skills?.map((name) => (
                    <span
                      key={name}
                      className="shrink-0 font-mono text-[11px] text-text-secondary"
                    >
                      /{name}
                    </span>
                  ))}
                  <span className="min-w-0 flex-1 truncate text-[12px] text-text-primary">
                    {item.text ||
                      (item.skills?.length ? '' : t('workbench.composer.attachmentsOnly'))}
                  </span>
                  {item.attachments > 0 ? (
                    <span className="shrink-0 text-[11px] text-text-muted">
                      {t('workbench.composer.outboundAttachments', { n: item.attachments })}
                    </span>
                  ) : null}
                  {onMoveQueueItem && queueItems.length > 1 ? (
                    <div className="flex shrink-0 items-center gap-0.5">
                      <button
                        type="button"
                        data-testid={`session-queue-up-${idx}`}
                        disabled={idx === 0}
                        title={t('workbench.queue.moveUp')}
                        aria-label={t('workbench.queue.moveUp')}
                        onClick={() => void onMoveQueueItem(item.id, 'up')}
                        className="flex h-5 w-5 items-center justify-center rounded-[4px] text-text-muted hover:bg-bg-hover hover:text-text-primary disabled:opacity-30"
                      >
                        <ArrowUp size={11} />
                      </button>
                      <button
                        type="button"
                        data-testid={`session-queue-down-${idx}`}
                        disabled={idx === queueItems.length - 1}
                        title={t('workbench.queue.moveDown')}
                        aria-label={t('workbench.queue.moveDown')}
                        onClick={() => void onMoveQueueItem(item.id, 'down')}
                        className="flex h-5 w-5 items-center justify-center rounded-[4px] text-text-muted hover:bg-bg-hover hover:text-text-primary disabled:opacity-30"
                      >
                        <ArrowDown size={11} />
                      </button>
                    </div>
                  ) : null}
                  {onRemoveQueueItem ? (
                    <button
                      type="button"
                      data-testid="session-queue-delete"
                      title={t('workbench.queue.remove')}
                      aria-label={t('workbench.queue.remove')}
                      onClick={() => void onRemoveQueueItem(item.id)}
                      className="flex h-5 w-5 shrink-0 items-center justify-center rounded-[4px] text-text-muted hover:bg-bg-hover hover:text-accent-error"
                    >
                      <Trash2 size={11} />
                    </button>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        ) : null}

        <AttachmentStrip
          images={images}
          documents={documents}
          onRemoveImage={removeImage}
          onRemoveDocument={removeDocument}
          idPrefix="composer"
        />

        {/* 待发的气泡：已经点了发送、还没落进记录流的那几句，与记录流里的「You said」
            同一种画法，下面挂同一串步骤名。两档的分野是**它进没进这场会话**：
            On its way＝请求出了门、会话里还找不到它（虚线框、转圈）；Queued＝进来了但
            agent 正忙，排在队列上（中性实线框加时钟）。都不用绿——排队不是成功，也不是
            动作，这一屏的实心绿只给 Send。标题已经说了当前这一档，步骤链只留之前走过的，
            刚发出时整行不画。 */}
        {outbound.length ? (
          <div className="flex flex-col gap-1.5">
            {outbound.map((msg) => {
              const queued = msg.state === 'queued';
              const trail = trailOf.get(msg.id);
              return (
                <div
                  key={msg.id}
                  data-testid="composer-outbound"
                  data-state={msg.state}
                  className={`flex min-w-0 flex-col gap-1 rounded-[10px] bg-bg-subtle px-3 py-2 ${
                    queued ? 'border border-border-strong' : 'border border-dashed border-border-strong'
                  }`}
                >
                  <div className="flex min-w-0 items-center gap-2">
                    {queued ? (
                      <Clock size={13} className="shrink-0 text-text-muted" />
                    ) : (
                      <Loader2 size={13} className="shrink-0 animate-spin text-text-muted" />
                    )}
                    <span className="shrink-0 text-[11px] font-medium text-text-secondary">
                      {t(queued ? 'workbench.progress.queued' : 'workbench.progress.onItsWay')}
                    </span>
                    {msg.skills?.map((name) => (
                      <span
                        key={name}
                        data-testid="composer-outbound-skill"
                        className="shrink-0 font-mono text-[11px] text-text-secondary"
                      >
                        /{name}
                      </span>
                    ))}
                    <span className="min-w-0 flex-1 truncate text-[12px] text-text-primary">
                      {msg.text || (msg.skills?.length ? '' : t('workbench.composer.attachmentsOnly'))}
                    </span>
                    {msg.attachments ? (
                      <span className="shrink-0 text-[11px] text-text-muted">
                        {t('workbench.composer.outboundAttachments', { n: msg.attachments })}
                      </span>
                    ) : null}
                  </div>
                  <p className="text-[11px] text-text-muted">
                    {t(queued ? 'workbench.composer.queuedHint' : 'workbench.composer.onItsWayHint')}
                  </p>
                  {trail ? (
                    <SendProgress trail={trail} headline={queued ? 'queued' : 'on_its_way'} />
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : movedUp.length ? (
          <p
            data-testid="composer-moved-up"
            className="flex items-center gap-1.5 text-[11px] text-text-muted"
          >
            <ArrowUp size={12} className="shrink-0" />
            <span>
              {movedUp.length === 1
                ? t('workbench.composer.movedUpOne')
                : movedUp.length === 2
                  ? t('workbench.composer.movedUpBoth')
                  : t('workbench.composer.movedUpMany', { n: movedUp.length })}
            </span>
            {onShowInStream && movedTarget ? (
              <>
                <span aria-hidden>·</span>
                <button
                  type="button"
                  data-testid="composer-moved-up-show"
                  onClick={() => onShowInStream(movedTarget)}
                  className="text-text-secondary underline-offset-2 hover:text-text-primary hover:underline"
                >
                  {t('workbench.composer.show')}
                </button>
              </>
            ) : null}
          </p>
        ) : null}

        {/* 起分支之后的原地提示：页面不跳走，人在这一行上看见分支去了哪、点「打开」才过去。
            与上面「moved up」那一行同一种写法——都是「刚才那件事去了哪」。 */}
        {notice ? (
          <p
            data-testid="composer-notice"
            data-tone={notice.tone ?? 'plain'}
            className={`flex min-w-0 items-center gap-1.5 text-[11px] ${
              notice.tone === 'error' ? 'text-accent-error' : 'text-text-muted'
            }`}
          >
            <GitBranch size={12} className="shrink-0" />
            <span className="min-w-0 truncate">{notice.text}</span>
            {notice.actionLabel && notice.onAction ? (
              <>
                <span aria-hidden>·</span>
                <button
                  type="button"
                  data-testid="composer-notice-action"
                  onClick={notice.onAction}
                  className="shrink-0 text-text-secondary underline-offset-2 hover:text-text-primary hover:underline"
                >
                  {notice.actionLabel}
                </button>
              </>
            ) : null}
            {notice.onDismiss ? (
              <button
                type="button"
                data-testid="composer-notice-dismiss"
                aria-label={t('workbench.branch.dismiss')}
                title={t('workbench.branch.dismiss')}
                onClick={notice.onDismiss}
                className="ml-auto flex h-4 w-4 shrink-0 items-center justify-center rounded-[4px] text-text-muted hover:text-text-primary"
              >
                <X size={11} />
              </button>
            ) : null}
          </p>
        ) : null}

        <PromptComposerBox
          text={text}
          onChangeText={setText}
          skills={picked}
          onAddSkill={addSkill}
          onRemoveSkill={removeSkill}
          onAddFiles={takeFiles}
          attachCount={attachCount}
          canSubmit={canSend}
          submitting={sending}
          onSubmit={send}
          disabled={Boolean(blocked)}
          placeholder={
            blocked
              ? ''
              : family
                ? t('workbench.composer.placeholderWithFamily', { family: familyLabel(family) })
                : t('workbench.composer.placeholder')
          }
          idPrefix="composer"
          menuPlacement="above"
          caretToRef={caretTo}
          bannerSlot={
            packedBanner ? (
              <div
                data-testid="composer-packed-bar"
                className="mb-2 flex items-center justify-between gap-2 rounded-[6px] border border-border-color bg-bg-secondary px-2.5 py-1 text-[11px] text-text-secondary"
              >
                <span className="min-w-0 truncate">
                  <strong className="font-semibold text-accent-warning">
                    {t('workbench.composer.packedBanner', { n: packedBanner.count })}
                  </strong>
                  <span className="mx-1.5 text-text-dim">·</span>
                  <code className="font-mono text-[10.5px] text-text-muted">
                    {packedBanner.tracePath}
                  </code>
                </span>
                <button
                  type="button"
                  data-testid="composer-packed-clear"
                  onClick={() => {
                    setPackedBanner(null);
                    setText('');
                  }}
                  className="shrink-0 rounded-[4px] px-1.5 py-0.5 text-[11px] text-text-muted hover:bg-bg-hover hover:text-text-primary"
                >
                  {t('workbench.composer.packedClear')}
                </button>
              </div>
            ) : null
          }
          rightActionsSlot={
            <>
              {onEnqueue && !blocked ? (
                <button
                  type="button"
                  data-testid="composer-enqueue"
                  disabled={!canEnqueue}
                  onClick={() => void handleEnqueue()}
                  title={t('workbench.composer.enqueueHint')}
                  className="flex h-7 shrink-0 items-center gap-1.5 rounded-[8px] border border-border-color px-2.5 text-[12px] text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary disabled:opacity-40"
                >
                  <ListOrdered size={13} />
                  {enqueueing
                    ? t('workbench.composer.enqueueing')
                    : t('workbench.composer.enqueue')}
                </button>
              ) : null}
              {onBringBack && !blocked ? (
                <button
                  type="button"
                  data-testid="composer-bring-back"
                  onClick={onBringBack}
                  title={t('workbench.branch.bringBackHint')}
                  className="flex h-7 shrink-0 items-center gap-1.5 rounded-[8px] border border-border-accent px-3 text-[12px] text-accent-primary transition-colors hover:bg-accent-primary-10"
                >
                  <CornerUpLeft size={13} />
                  {t('workbench.branch.bringBack')}
                </button>
              ) : null}
              {onHandoff && !blocked ? (
                <button
                  type="button"
                  data-testid="composer-handoff"
                  disabled={handingOff || contextTokens === null || contextTokens < HANDOFF_MIN_CONTEXT}
                  onClick={onHandoff}
                  title={
                    contextTokens === null
                      ? t('workbench.composer.handoffLockedUnknown', {
                          limit: formatK(HANDOFF_MIN_CONTEXT),
                        })
                      : contextTokens < HANDOFF_MIN_CONTEXT
                        ? t('workbench.composer.handoffLocked', {
                            limit: formatK(HANDOFF_MIN_CONTEXT),
                            now: formatK(contextTokens),
                          })
                        : t('workbench.composer.handoffHint')
                  }
                  className="flex h-7 shrink-0 items-center gap-1.5 rounded-[8px] border border-border-accent px-3 text-[12px] text-accent-primary transition-colors hover:bg-accent-primary-10 disabled:border-border-color disabled:text-text-muted disabled:opacity-60 disabled:hover:bg-transparent"
                >
                  {handingOff ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <GitBranchPlus size={13} />
                  )}
                  {handingOff ? t('workbench.composer.handingOff') : t('workbench.composer.handoff')}
                </button>
              ) : null}
            </>
          }
          submitLabel={t('workbench.composer.send')}
          submittingLabel={t('workbench.composer.sending')}
          submitAriaLabel={t('workbench.composer.send')}
          submitTestId="composer-send"
        />
      </div>
    </div>
  );
}
