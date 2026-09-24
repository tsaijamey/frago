/**
 * useSendToSession — 把工作台中栏输入区的内容送进当前会话。
 *
 * 走 `POST /api/workbench/sessions/{sid}/send`，三家（Claude Code / opencode / codex）
 * 共用这一条：该驱动哪一家、在哪个目录续接，全由服务端按会话编号判定，这一侧一个字
 * 都不猜。它同时收文本与图片：图片以 base64（data URL 或裸 base64）传入，服务端落盘后
 * 把绝对路径拼进投给 agent 的提示词。**允许纯发图**（文本空、图片非空）；两者都空时
 * 服务端回 400，所以这一侧直接把发送按钮闸死，不让请求出门。
 *
 * 三条纪律：
 *
 * 1. **点了发送，输入框当场交还给人。** 那一刻起这句话已经撤不回了，把它继续留在输入框
 *    里只会让人以为没发出去、又删不掉。它改由输入区上方的信封替它站着（`onSendStart`
 *    交给记录流开的那一个），信封会一路显示它是"已发送"还是"已入队列"。
 * 2. **失败一个字都不丢。** 输入框还空着就把这一单原样退回去；人已经在里面打了新的字
 *    就先收在 `failed` 里，重试重发的还是原来那一份。NEVER 让一次网络抖动吃掉几百字。
 *    **但只有真没发出去才算失败。** 这条接口要挂整整一轮，服务器在这一轮里重启（常常就是
 *    agent 自己重启的），请求会断在半路——那时候话早已进了会话。已经送达的，断了就当发成
 *    了：不亮红条、不退回；连接断了而还没见送达的，先等记录流核对 {@link CONFIRM_WINDOW_MS}，
 *    等不到才按失败退回。服务端明确回了错误的，照旧当场判失败。
 * 3. **发完重拉真记录，不在本地插假的。** 成功后调 `onSent`（页面把它接到记录流的
 *    `reload` 上）。本地插一条假的既没有真实序号也没有出处，刷新就没了。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import i18n from '@/i18n';
import {
  MAX_ATTACHMENTS,
  useAttachments,
  type AttachedDoc,
  type AttachedImage,
} from '@/hooks/useAttachments';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

// 收文件那一段（读成 base64、按 MIME 分图片与文档、数量上限）与新建会话对话框共用一份，
// 见 `useAttachments`。这里只管"发出去"，不再自己养一套附件状态。
export { MAX_ATTACHMENTS };
export type { AttachedDoc, AttachedImage };

/**
 * 发完之后隔多久再拉一次记录。
 *
 * 立刻那一次多半还看不到自己刚说的话——agent 要先把这一轮写进档案。补一次延迟重拉，
 * 人就不用自己去点刷新。这是「看得到」的兜底，不是轮询，只补这一次。
 */
const RELOAD_AGAIN_MS = 1500;

/**
 * 连接断了、又还没见送达时，等记录流核对多久。
 *
 * 断在半路的请求说明不了话有没有进会话：服务器可能是投完才重启的。重启一般几秒就回来，
 * 回来后记录流的轮询会把那句话取回来、报出送达。这段时间里信封照旧挂着「已发送」；
 * 等满还没见到，才当它真没发出去。
 */
export const CONFIRM_WINDOW_MS = 20_000;

/** 请求没拿到任何回应就断了（服务器重启、断网）。区别于服务端明确回了一个错误。 */
class ConnectionLostError extends Error {}

export interface SendResult {
  sid: string;
  status: string;
  text: string;
}

export interface SendToSessionState {
  text: string;
  setText: (value: string) => void;
  images: AttachedImage[];
  documents: AttachedDoc[];
  /** 收文件（选择、粘贴、拖入三条路共用）。按 MIME 分给图片或文档两条路。 */
  addFiles: (files: FileList | File[]) => Promise<void>;
  removeImage: (id: string) => void;
  removeDocument: (id: string) => void;
  sending: boolean;
  /** 失败原因，照抄服务端的说法。成功或重新发送时清掉。 */
  error: string | null;
  /** 有内容（或手上还压着一单没发成的）、不在发送中、且这场会话本来就能发。 */
  canSend: boolean;
  send: () => Promise<void>;
}

/** 一次投出去的全部内容。发送那一刻从输入框里整份取走，之后输入框与它再无关系。 */
interface OutboundPayload {
  text: string;
  images: AttachedImage[];
  documents: AttachedDoc[];
}

/** 把服务端的说法取出来。FastAPI 的报错落在 `detail` 里，取不到就退回状态码。 */
async function explainFailure(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === 'string' && body.detail) return body.detail;
  } catch {
    /* 响应不是 JSON，退回状态码 */
  }
  return i18n.t('workbench.errors.sendFailed', { status: res.status });
}

export async function sendToSession(
  sessionId: string,
  text: string,
  images: string[],
  documents: { name: string; data: string }[] = []
): Promise<SendResult> {
  let res: Response;
  try {
    res = await fetch(
      `${API_BASE_URL}/api/workbench/sessions/${encodeURIComponent(sessionId)}/send`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, images, documents }),
      }
    );
  } catch (e) {
    throw new ConnectionLostError(e instanceof Error ? e.message : String(e));
  }
  if (!res.ok) {
    throw new Error(await explainFailure(res));
  }
  return (await res.json()) as SendResult;
}

export interface UseSendToSessionOptions {
  /** 这场会话能不能发。为 false 时按钮恒禁用，`send` 直接不出门。 */
  enabled?: boolean;
  /**
   * 请求**出门那一刻**调它，不是回来的时候。
   *
   * 这条接口等的是整整一轮：服务端把话投进 tmux 之后一直轮询到这一轮说完才返回，上限
   * 180 秒。等它回来再做任何事，等于整轮跑完之前中栏一个字都不会变——那正是"发完话
   * 体现不出会话在进行"的根因。要让人立刻看见"在跑"，只能挂在这里。
   *
   * 带上这次投出去的原文与附件数：记录流靠原文认出"这句话已经落进流里了"，也靠这一次
   * 调用给它开一个信封。交回的是那个信封的编号，发失败时要用它精确撤掉这一单。
   */
  onSendStart?: (text: string, attachments: number) => string | void;
  /**
   * 发送成功后调它重拉记录，并带上这一单的信封编号。
   *
   * 这条接口一直等到这一轮说完才返回，所以它一回来，那句话必定早就进了这场会话——页面
   * 据此把那个信封收掉，不必等记录流认出它长什么样。
   */
  onSent?: (outboundId?: string) => void | Promise<void>;
  /** 没发出去。带上信封编号，页面据此撤掉这一单——挂着一个送不到的信封比不提示还糟。 */
  onSendFailed?: (outboundId?: string) => void;
  /**
   * 那句话**确实落进会话**的时刻（页面接的是记录流的 `deliveredAt`）。它一变就把发送
   * 按钮放回去，人可以接着说下一句。
   *
   * 不能等接口返回：那条接口一直等到整轮说完才回来（上限 180 秒）。等它的话，人明明
   * 看见自己的话已经出现在流里了，按钮却还转着圈，只能切到别的会话再切回来才恢复。
   * 输入框不归它管——那一份在点发送的时候就已经清了。
   */
  deliveredAt?: number | null;
}

export function useSendToSession(
  sessionId: string | null,
  {
    enabled = true,
    onSendStart,
    onSent,
    onSendFailed,
    deliveredAt = null,
  }: UseSendToSessionOptions = {}
): SendToSessionState {
  const [text, setText] = useState('');
  const { images, documents, addFiles, removeImage, removeDocument, clear, restore } =
    useAttachments();
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 发出去了却没发成、又退不回输入框（人已经在里面打了别的）的那一单。重试重发它。
  const [failed, setFailed] = useState<OutboundPayload | null>(null);

  // 输入框此刻空不空。发送失败是在 await 之后才知道的，那时候只能问 ref——闭包里的
  // text/images 停在点发送那一刻，拿它判"人有没有打新的字"必然判错。
  const boxEmpty = useRef(true);
  boxEmpty.current = !text && images.length === 0 && documents.length === 0;
  // 在飞的那一单的编号，以及"哪一单已经被送达信号清过了"。两者一比就知道接口回来时
  // 还该不该清——不比的话，人在放行后新打的字会被上一单的返回抹掉。
  const ticket = useRef(0);
  const clearedTicket = useRef(0);
  const mounted = useRef(true);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 连接断了、正等记录流核对的那一单。送达信号先到就作罢，等满了才按失败处理。
  const unconfirmed = useRef<{
    ticket: number;
    timer: ReturnType<typeof setTimeout>;
  } | null>(null);
  // 这三个回调每渲染都是新的，放进 ref 让 send 保持稳定，同时永远调到最新那个。
  const onSentRef = useRef(onSent);
  onSentRef.current = onSent;
  const onSendStartRef = useRef(onSendStart);
  onSendStartRef.current = onSendStart;
  const onSendFailedRef = useRef(onSendFailed);
  onSendFailedRef.current = onSendFailed;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (timer.current !== null) clearTimeout(timer.current);
      if (unconfirmed.current) clearTimeout(unconfirmed.current.timer);
    };
  }, []);

  // 换会话时把上一场没发出去的内容与错误一起收走：那段话是对上一场说的。
  useEffect(() => {
    if (unconfirmed.current) {
      clearTimeout(unconfirmed.current.timer);
      unconfirmed.current = null;
    }
    setText('');
    clear();
    setSending(false);
    setError(null);
    setFailed(null);
  }, [sessionId, clear]);

  /**
   * 送达信号一到就把按钮放回去。
   *
   * 放行之后人可以立刻接着说下一句——那句会成为插话，投进正在跑的那一轮。这是安全的：
   * "送达"本身就意味着上一句已经落了盘，两次投喂不会在会话里把字咬在一起。
   *
   * 输入框在这里一个字都不动：它在点发送那一刻就清过了，此刻里面装的是人新打的东西。
   */
  useEffect(() => {
    if (!deliveredAt) return;
    if (ticket.current === 0 || clearedTicket.current === ticket.current) return;
    clearedTicket.current = ticket.current;
    setSending(false);
    // 连接断了还在核对的那一单，送达信号一到就有了答案：它发出去了。
    if (unconfirmed.current && unconfirmed.current.ticket <= clearedTicket.current) {
      clearTimeout(unconfirmed.current.timer);
      unconfirmed.current = null;
    }
  }, [deliveredAt]);

  const body = text.trim();
  const canSend =
    Boolean(enabled && sessionId) &&
    !sending &&
    (!!body || images.length > 0 || documents.length > 0 || failed !== null);

  /**
   * 确认没发出去：亮出原因，内容得有个去处。输入框还空着就原样退回去，人接着改就是；
   * 人已经在里面打了新的字就先收着，重试重发的仍是这一份。两条路都一个字不丢。
   */
  const giveBack = useCallback(
    (payload: OutboundPayload, reason: string, outboundId?: string) => {
      setError(reason);
      if (boxEmpty.current) {
        setText(payload.text);
        restore(payload.images, payload.documents);
        setFailed(null);
      } else {
        setFailed(payload);
      }
      onSendFailedRef.current?.(outboundId);
    },
    [restore]
  );

  /** 真正把一单投出去。内容此刻已经不在输入框里了，成败都只影响 `failed` 与错误提示。 */
  const dispatch = useCallback(
    async (payload: OutboundPayload) => {
      if (!sessionId) return;
      const mine = ++ticket.current;
      let pending = false;
      setSending(true);
      setError(null);
      // 请求还没出门就先喊一声，顺手换回这一单的信封编号。这条接口要等整整一轮才回来，
      // 等它回来再喊就晚了整轮。
      const outboundId =
        onSendStartRef.current?.(
          payload.text,
          payload.images.length + payload.documents.length
        ) || undefined;
      try {
        await sendToSession(
          sessionId,
          payload.text,
          payload.images.map((im) => im.dataUrl),
          payload.documents.map((d) => ({ name: d.name, data: d.dataUrl }))
        );
        if (!mounted.current) return;
        setFailed(null);
        await onSentRef.current?.(outboundId);
        if (timer.current !== null) clearTimeout(timer.current);
        timer.current = setTimeout(() => {
          if (mounted.current) void onSentRef.current?.(outboundId);
        }, RELOAD_AGAIN_MS);
      } catch (e) {
        if (!mounted.current) return;
        // 送达信号早就到过：话已经在会话里了，断的只是那条等整轮的请求。当它发成了，
        // 不亮红条、不退回。也不去重拉记录——服务器这会儿多半还没起来，重拉只会在
        // 记录流上再添一条报错；它回来后轮询自己会接上。
        if (clearedTicket.current >= mine) {
          setFailed(null);
          return;
        }
        const reason = e instanceof Error ? e.message : String(e);
        if (e instanceof ConnectionLostError) {
          // 没见送达、连接却断了：说不准。信封留着，等记录流核对，等满了才判失败。
          if (unconfirmed.current) clearTimeout(unconfirmed.current.timer);
          unconfirmed.current = {
            ticket: mine,
            timer: setTimeout(() => {
              if (!mounted.current || unconfirmed.current?.ticket !== mine) return;
              unconfirmed.current = null;
              giveBack(payload, reason, outboundId);
              if (ticket.current === mine) setSending(false);
            }, CONFIRM_WINDOW_MS),
          };
          pending = true;
          return;
        }
        giveBack(payload, reason, outboundId);
      } finally {
        // 只有还是自己那一单时才落下"发送中"：放行之后人已经发了下一句的话，
        // 这里再动一次会把后一单的状态抹掉。还在核对的那一单由核对的结果去落。
        if (mounted.current && ticket.current === mine && !pending) setSending(false);
      }
    },
    [sessionId, giveBack]
  );

  const send = useCallback(async () => {
    if (!enabled || !sessionId || sending) return;
    // 手上压着一单没发成、而输入框已被人占用：重试重发的是那一单，不是框里的新内容。
    if (failed) {
      const retry = failed;
      setFailed(null);
      await dispatch(retry);
      return;
    }
    const payload: OutboundPayload = { text: text.trim(), images, documents };
    if (!payload.text && !payload.images.length && !payload.documents.length) return;
    // 点了发送就撤不回了，输入框当场交还给人。那句话改由上方的信封替它站着。
    setText('');
    clear();
    await dispatch(payload);
  }, [enabled, sessionId, sending, failed, text, images, documents, clear, dispatch]);

  return {
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
  };
}
