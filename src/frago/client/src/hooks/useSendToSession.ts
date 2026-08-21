/**
 * useSendToSession — 把工作台中栏输入区的内容送进当前会话。
 *
 * 走 `POST /api/workbench/sessions/{sid}/send`，三家（Claude Code / opencode / codex）
 * 共用这一条：该驱动哪一家、在哪个目录续接，全由服务端按会话编号判定，这一侧一个字
 * 都不猜。它同时收文本与图片：图片以 base64（data URL 或裸 base64）传入，服务端落盘后
 * 把绝对路径拼进投给 agent 的提示词。**允许纯发图**（文本空、图片非空）；两者都空时
 * 服务端回 400，所以这一侧直接把发送按钮闸死，不让请求出门。
 *
 * 两条纪律：
 *
 * 1. **失败不清空。** 文本与图片原样留在界面上，错误原因照抄服务端的说法，重试就是再调
 *    一次 `send`。NEVER 静默清空输入框——人打了几百字，一次网络抖动不该让它蒸发。
 * 2. **发完重拉真记录，不在本地插假的。** 成功后调 `onSent`（页面把它接到记录流的
 *    `reload` 上）。本地插一条假的既没有真实序号也没有出处，刷新就没了。
 */

import { useCallback, useEffect, useRef, useState } from 'react';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/** 一次最多附几张。与服务端 `webui_uploads._MAX_COUNT` 对齐，超出的丢弃。 */
export const MAX_ATTACHMENTS = 8;

/**
 * 发完之后隔多久再拉一次记录。
 *
 * 立刻那一次多半还看不到自己刚说的话——agent 要先把这一轮写进档案。补一次延迟重拉，
 * 人就不用自己去点刷新。这是「看得到」的兜底，不是轮询，只补这一次。
 */
const RELOAD_AGAIN_MS = 1500;

/** 一张已附加、待发送的图片。`dataUrl` 原样发给服务端，`name` 供缩略图的替代文字。 */
export interface AttachedImage {
  id: string;
  /** `data:image/...;base64,....` */
  dataUrl: string;
  name: string;
}

export interface SendResult {
  sid: string;
  status: string;
  text: string;
}

export interface SendToSessionState {
  text: string;
  setText: (value: string) => void;
  images: AttachedImage[];
  /** 收图片文件（选择、粘贴、拖入三条路共用）。非图片一律忽略。 */
  addFiles: (files: FileList | File[]) => Promise<void>;
  removeImage: (id: string) => void;
  sending: boolean;
  /** 失败原因，照抄服务端的说法。成功或重新发送时清掉。 */
  error: string | null;
  /** 有内容、不在发送中、且这场会话本来就能发。 */
  canSend: boolean;
  send: () => Promise<void>;
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error('图片读不出来'));
    reader.readAsDataURL(file);
  });
}

/** 把服务端的说法取出来。FastAPI 的报错落在 `detail` 里，取不到就退回状态码。 */
async function explainFailure(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === 'string' && body.detail) return body.detail;
  } catch {
    /* 响应不是 JSON，退回状态码 */
  }
  return `发送没成功（HTTP ${res.status}）`;
}

export async function sendToSession(
  sessionId: string,
  text: string,
  images: string[]
): Promise<SendResult> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/sessions/${encodeURIComponent(sessionId)}/send`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, images }),
    }
  );
  if (!res.ok) {
    throw new Error(await explainFailure(res));
  }
  return (await res.json()) as SendResult;
}

export interface UseSendToSessionOptions {
  /** 这场会话能不能发。为 false 时按钮恒禁用，`send` 直接不出门。 */
  enabled?: boolean;
  /** 发送成功后调它重拉记录。页面接的是记录流的 `reload`。 */
  onSent?: () => void | Promise<void>;
}

export function useSendToSession(
  sessionId: string | null,
  { enabled = true, onSent }: UseSendToSessionOptions = {}
): SendToSessionState {
  const [text, setText] = useState('');
  const [images, setImages] = useState<AttachedImage[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 附件编号用单调自增，不掺时间戳与随机数——同一毫秒连附两张会撞。
  const counter = useRef(0);
  const mounted = useRef(true);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // onSent 每渲染都是新的，放进 ref 让 send 保持稳定，同时永远调到最新那个。
  const onSentRef = useRef(onSent);
  onSentRef.current = onSent;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (timer.current !== null) clearTimeout(timer.current);
    };
  }, []);

  // 换会话时把上一场没发出去的内容与错误一起收走：那段话是对上一场说的。
  useEffect(() => {
    setText('');
    setImages([]);
    setSending(false);
    setError(null);
  }, [sessionId]);

  const addFiles = useCallback(async (files: FileList | File[]) => {
    const picked = Array.from(files).filter((f) => f.type.startsWith('image/'));
    if (picked.length === 0) return;
    const read = await Promise.all(
      picked.map(async (f) => ({
        id: `img-${counter.current++}`,
        dataUrl: await readFileAsDataUrl(f),
        name: f.name || 'image',
      }))
    );
    if (!mounted.current) return;
    setImages((cur) => [...cur, ...read].slice(0, MAX_ATTACHMENTS));
  }, []);

  const removeImage = useCallback((id: string) => {
    setImages((cur) => cur.filter((im) => im.id !== id));
  }, []);

  const body = text.trim();
  const canSend = Boolean(enabled && sessionId) && !sending && (!!body || images.length > 0);

  const send = useCallback(async () => {
    const payloadText = text.trim();
    const payloadImages = images.map((im) => im.dataUrl);
    if (!enabled || !sessionId || sending) return;
    if (!payloadText && payloadImages.length === 0) return;

    setSending(true);
    setError(null);
    try {
      await sendToSession(sessionId, payloadText, payloadImages);
      if (!mounted.current) return;
      // 只有成功才清。失败那条路一个字都不动。
      setText('');
      setImages([]);
      await onSentRef.current?.();
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        if (mounted.current) void onSentRef.current?.();
      }, RELOAD_AGAIN_MS);
    } catch (e) {
      if (!mounted.current) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mounted.current) setSending(false);
    }
  }, [enabled, sessionId, sending, text, images]);

  return {
    text,
    setText,
    images,
    addFiles,
    removeImage,
    sending,
    error,
    canSend,
    send,
  };
}
