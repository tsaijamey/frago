import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  getClaudeSessionDetail,
  sendClaudeSessionMessage,
  sendPaSessionMessage,
} from '@/api';
import type { ClaudeSessionDetail } from '@/api/client';

/** 一张已附加、待发送的图像：dataUrl 直接传后端，name 供预览 alt / 标题。 */
export interface AttachedImage {
  id: string;
  dataUrl: string; // data:image/...;base64,....
  name: string;
}

// composer 一次最多附 8 张（与后端 _MAX_COUNT 对齐），只收 image/* 文件。
const MAX_ATTACHMENTS = 8;

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error('read failed'));
    reader.readAsDataURL(file);
  });
}

/**
 * useSessionDetail — owns the detail side panel: transcript fetching,
 * chat-style bottom-pinned scroll, the composer that forwards input into
 * the resident tmux claude, and the reply-polling state machine.
 */
export function useSessionDetail() {
  // Detail side panel
  const [detailSid, setDetailSid] = useState<string | null>(null);
  const [detail, setDetail] = useState<ClaudeSessionDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  // Set only when opened from the PA-sessions tab: a group name (for the
  // header, since this sid won't be in the general scan's `sessions` list)
  // and the conv_key `handleSend` needs to route into PA's own resident
  // session instead of the UI-only send endpoint.
  const [detailTitle, setDetailTitle] = useState<string | null>(null);
  const [detailConvKey, setDetailConvKey] = useState<string | null>(null);

  // Composer (send message into the resident tmux claude) + reply polling
  const [input, setInput] = useState('');
  const [images, setImages] = useState<AttachedImage[]>([]);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

  // 生成附件 id 不依赖 Date.now/random（够用即可）——单调自增计数器。
  const attachCounterRef = useRef(0);
  // null = idle; 'activating' = cold start in progress; 'ready' = warm,
  // awaiting reply. Drives the progress bar; cleared once the probe says done.
  const [activation, setActivation] = useState<'activating' | 'ready' | null>(null);
  // True when polling gave up before a new reply landed — surfaces a manual
  // refresh hint so the user is never stranded waiting.
  const [pollStalled, setPollStalled] = useState(false);

  // Track the currently open session for poll callbacks (avoids stale closures
  // and lets us drop responses that arrive after the user switched sessions).
  const detailSidRef = useRef<string | null>(null);
  const pollTimerRef = useRef<number | null>(null);
  // Marker (last terminal uuid) captured at send time. Polling waits for a
  // *changed* marker so the prior turn's stale done can't stop us early.
  const baselineMarkerRef = useRef<string | null>(null);
  // Wall-clock deadline for the current poll cycle (ms epoch); past it we stop
  // and show the refresh hint rather than spin forever.
  const pollDeadlineRef = useRef<number>(0);

  // Chat-style scroll: the message stream pins to the bottom (newest) on open
  // and as new content arrives, but releases the pin the moment the user
  // scrolls up to read history — and re-engages when they return to the bottom.
  const streamRef = useRef<HTMLDivElement | null>(null);
  const pinnedToBottomRef = useRef(true);

  const scrollStreamToBottom = useCallback(() => {
    const el = streamRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  const handleStreamScroll = useCallback(() => {
    const el = streamRef.current;
    if (!el) return;
    // Within 60px of the bottom counts as "at bottom" — re-pins; otherwise the
    // user is reading history, so we let go of the pin.
    pinnedToBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  }, []);

  // Keep the view glued to the newest message whenever content changes (open,
  // poll refresh, manual refresh) — but only while the user hasn't scrolled up.
  useLayoutEffect(() => {
    if (pinnedToBottomRef.current) scrollStreamToBottom();
  }, [detail, detailLoading, scrollStreamToBottom]);

  const clearPoll = useCallback(() => {
    if (pollTimerRef.current != null) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    detailSidRef.current = detailSid;
  }, [detailSid]);

  // Clean up the poll timer on unmount so a backgrounded page never leaks.
  useEffect(() => clearPoll, [clearPoll]);

  // Poll the detail endpoint until the transcript_completion probe reports the
  // turn finished (done=true). Content is always taken from this endpoint's
  // jsonl-derived payload — never from the send response. Backoff caps at 8s.
  const pollReply = useCallback(
    (sid: string, delay: number) => {
      clearPoll();
      pollTimerRef.current = window.setTimeout(async () => {
        let finished = false;
        try {
          const d = await getClaudeSessionDetail(sid, 300);
          if (detailSidRef.current !== sid) return; // user switched away
          setDetail(d);
          // Done alone isn't enough: the session may already have been done
          // before we sent. Only stop once the marker advanced past the
          // baseline captured at send time — that's *this* turn finishing.
          const newReply =
            d.done === true && (d.last_uuid ?? null) !== baselineMarkerRef.current;
          if (newReply) {
            finished = true;
            setActivation(null);
            setPollStalled(false);
          }
        } catch {
          // transient read error — keep polling under backoff
        }
        if (finished || detailSidRef.current !== sid) return;
        // Give up after the deadline rather than spinning forever; surface a
        // manual-refresh hint so the user can re-check on demand.
        if (Date.now() >= pollDeadlineRef.current) {
          setActivation(null);
          setPollStalled(true);
          return;
        }
        pollReply(sid, Math.min(delay * 1.4, 8000));
      }, delay);
    },
    [clearPoll]
  );

  // Attach image files (from picker / paste / drag-drop). Non-image files are
  // ignored; the list is capped at MAX_ATTACHMENTS. Reads each into a data URL
  // so `handleSend` can ship it as base64 the server saves to disk.
  const addImageFiles = useCallback(async (files: FileList | File[]) => {
    const picked = Array.from(files).filter((f) => f.type.startsWith('image/'));
    if (picked.length === 0) return;
    const read = await Promise.all(
      picked.map(async (f) => ({
        id: `img-${attachCounterRef.current++}`,
        dataUrl: await readFileAsDataUrl(f),
        name: f.name || 'image',
      }))
    );
    setImages((cur) => [...cur, ...read].slice(0, MAX_ATTACHMENTS));
  }, []);

  const removeImage = useCallback((id: string) => {
    setImages((cur) => cur.filter((im) => im.id !== id));
  }, []);

  const openDetail = useCallback(async (sid: string, opts?: { title?: string; convKey?: string }) => {
    clearPoll();
    setDetailSid(sid);
    setDetailTitle(opts?.title ?? null);
    setDetailConvKey(opts?.convKey ?? null);
    setDetail(null);
    setDetailLoading(true);
    setInput('');
    setImages([]);
    setSending(false);
    setSendError(null);
    setActivation(null);
    setPollStalled(false);
    pinnedToBottomRef.current = true; // open at the newest message
    try {
      const d = await getClaudeSessionDetail(sid, 300);
      if (detailSidRef.current === sid) setDetail(d);
    } catch {
      if (detailSidRef.current === sid) setDetail(null);
    } finally {
      if (detailSidRef.current === sid) setDetailLoading(false);
    }
  }, [clearPoll]);

  const closeDetail = useCallback(() => {
    clearPoll();
    setDetailSid(null);
    setDetailTitle(null);
    setDetailConvKey(null);
    setDetail(null);
    setInput('');
    setImages([]);
    setSending(false);
    setSendError(null);
    setActivation(null);
    setPollStalled(false);
  }, [clearPoll]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    const imgUrls = images.map((im) => im.dataUrl);
    // Allow text-only, image-only, or both — but never an empty turn.
    if ((!text && imgUrls.length === 0) || !detailSid || sending) return;
    setSending(true);
    setSendError(null);
    setPollStalled(false);
    // Baseline the marker BEFORE the new turn so polling can tell the new reply
    // apart from the (possibly already-done) prior turn.
    baselineMarkerRef.current = detail?.last_uuid ?? null;
    // Claude turns can run minutes; give the poll a generous deadline.
    pollDeadlineRef.current = Date.now() + 6 * 60 * 1000;
    try {
      // PA-tab sessions route through PA's own resident session (conv_key) so
      // sending never spins up a second tmux session racing PA's own pane;
      // everything else uses the UI-only send endpoint as before.
      const res = detailConvKey
        ? await sendPaSessionMessage(detailConvKey, text, imgUrls)
        : await sendClaudeSessionMessage(detailSid, text, imgUrls);
      setInput('');
      setImages([]);
      // activating → cold start (show "waking up"); ready → warm, awaiting reply.
      setActivation(res.status === 'activating' ? 'activating' : 'ready');
      pollReply(detailSid, 1500);
    } catch (e) {
      setSendError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  }, [input, images, detailSid, detailConvKey, sending, detail, pollReply]);

  // Manual refresh: re-fetch the transcript on demand. Used by the refresh
  // button and after the poll deadline lapses, so the user is never stuck.
  const refreshDetail = useCallback(async () => {
    const sid = detailSidRef.current;
    if (!sid) return;
    try {
      const d = await getClaudeSessionDetail(sid, 300);
      if (detailSidRef.current !== sid) return;
      setDetail(d);
      // If the awaited reply has now landed, clear the stalled hint.
      if (d.done === true && (d.last_uuid ?? null) !== baselineMarkerRef.current) {
        setPollStalled(false);
        setActivation(null);
      }
    } catch {
      // ignore — transient; user can retry.
    }
  }, []);

  return {
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
    openDetail,
    closeDetail,
    handleSend,
    refreshDetail,
  };
}
