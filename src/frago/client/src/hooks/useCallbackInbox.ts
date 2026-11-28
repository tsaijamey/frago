/**
 * useCallbackInbox — 异步回执只读收件箱状态（CallbackInbox）。
 *
 * 与人类 Next Task 队列物理分轨：拉取 `GET /api/workbench/sessions/{sid}/callback-inbox`，
 * 并在 WebSocket 推来会话更新/轮次结束/队列变更时自动刷新；必要时也可显式调用 `drain()`
 * 触发后端受控汇总。
 *
 * 测试或离线场景下如果后端接口尚未被 mock 或请求失败，静默回退到服务端列表行附带的
 * `initialSummary`（或空态 `{ count: 0, blocked_reason: null, items: [] }`），不打断主输入区。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchSessionCallbackInbox, drainSessionCallbackInbox } from '@/api/client';
import { getWebSocketClient, MessageType, type WebSocketMessage } from '@/api/websocket';
import type { CallbackInboxSummary, DrainCallbackInboxResponse } from '@/types/api';

const EMPTY_INBOX: CallbackInboxSummary = {
  count: 0,
  blocked_reason: null,
  items: [],
};

function normalizeSummary(summary?: CallbackInboxSummary | null): CallbackInboxSummary {
  if (!summary) return EMPTY_INBOX;
  return {
    count: typeof summary.count === 'number' ? summary.count : 0,
    blocked_reason: summary.blocked_reason ?? null,
    items: Array.isArray(summary.items) ? summary.items : [],
  };
}

export interface CallbackInboxState {
  inbox: CallbackInboxSummary;
  loading: boolean;
  reload: (sid?: string | null) => Promise<void>;
  drain: () => Promise<DrainCallbackInboxResponse | null>;
}

export function useCallbackInbox(
  sessionId: string | null,
  initialSummary?: CallbackInboxSummary | null
): CallbackInboxState {
  const [fetched, setFetched] = useState<{ sid: string; data: CallbackInboxSummary } | null>(null);
  const [loading, setLoading] = useState(false);
  const activeSidRef = useRef<string | null>(sessionId);
  activeSidRef.current = sessionId;

  const fallback = useMemo(() => normalizeSummary(initialSummary), [initialSummary]);

  const reload = useCallback(async (targetSid?: string | null) => {
    const sid = targetSid === undefined ? activeSidRef.current : targetSid;
    if (!sid) {
      setFetched(null);
      return;
    }
    setLoading(true);
    try {
      const res = await fetchSessionCallbackInbox(sid);
      if (res && typeof res.count === 'number' && activeSidRef.current === sid) {
        setFetched({
          sid,
          data: {
            count: res.count,
            blocked_reason: res.blocked_reason ?? null,
            items: Array.isArray(res.items) ? res.items : [],
          },
        });
      }
    } catch {
      // 保留 initialSummary 或空态回退，避免在无 mock 测试环境报错
    } finally {
      if (activeSidRef.current === sid) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    setFetched(null);
    if (!sessionId) return;
    void reload(sessionId);
  }, [sessionId, reload]);

  useEffect(() => {
    if (!sessionId) return;
    const sid = sessionId;
    const client = getWebSocketClient();

    const handleSessionEvent = (msg: WebSocketMessage) => {
      const data = msg.data as { session_id?: string; sid?: string } | undefined;
      const eventSid = data?.session_id ?? data?.sid;
      if (eventSid && eventSid !== sid) return;
      void reload(sid);
    };

    const unsubs = [
      client.on(MessageType.SESSION_TURN_DONE, handleSessionEvent),
      client.on(MessageType.SESSION_QUEUE_UPDATE, handleSessionEvent),
      client.on(MessageType.SESSION_UPDATED, handleSessionEvent),
      client.on(MessageType.SESSION_RECORDS_APPEND, handleSessionEvent),
    ];

    return () => {
      for (const unsub of unsubs) unsub();
    };
  }, [sessionId, reload]);

  const drain = useCallback(async () => {
    const sid = activeSidRef.current;
    if (!sid) return null;
    try {
      const res = await drainSessionCallbackInbox(sid);
      if (res && typeof res.count === 'number' && activeSidRef.current === sid) {
        setFetched({
          sid,
          data: {
            count: res.count,
            blocked_reason: res.blocked_reason ?? null,
            items: Array.isArray(res.items) ? res.items : [],
          },
        });
      }
      return res ?? null;
    } catch {
      return null;
    }
  }, []);

  const inbox = fetched && fetched.sid === sessionId ? fetched.data : fallback;

  return {
    inbox,
    loading,
    reload,
    drain,
  };
}
