/**
 * useSessionQueue — 会话工作台自有消息队列（Message Queue）。
 *
 * 作用：
 * 1. 不在 agent 执行过程中把消息直接塞进其原生运行队列（避免打断当前执行流），而是堆积到
 *    frago 会话自有的持久化队列中；
 * 2. 当且仅当会话已 stop 且检测到 stop 轮次出现后，其 `[end, end-5]`（最近 6 轮）会话都没有
 *    未作答的交互卡（避免因 hook 导致含交互卡的那一轮被补充会话遮挡），自动注入队列里最早的
 *    那一条消息，并从队列中删除该消息。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getWebSocketClient, MessageType, type WebSocketMessage } from '@/api/websocket';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import {
  isCardAnswer,
  parseUiComponentOutput,
  splitTrailingBlock,
  trailingDecision,
  UI_COMPONENT_MARKER,
  yamlNow,
} from '@/utils/decisionBlock';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/** 检测 `[end, end-5]` 共 6 轮会话是否包含交互卡。 */
export const TAIL_TURN_WINDOW = 6;

const BOOKKEEPING_KINDS = new Set([
  'call.envelope',
  'session.state',
  'todo.snapshot',
  'usage.tick',
]);

export interface QueuedMessageItem {
  id: string;
  text: string;
  skills: string[];
  attachments: number;
  created_at: number;
}

export interface SessionQueueResponse {
  sid: string;
  items: QueuedMessageItem[];
  session_stopped?: boolean;
  stop_turn_id?: string | null;
  blocked_by_card?: boolean;
  can_inject?: boolean;
}

export interface DrainQueueResponse {
  sid: string;
  injected: boolean;
  reason: string;
  item: QueuedMessageItem | null;
  items: QueuedMessageItem[];
}

function hasUiDecisionCard(text: string): boolean {
  if (!text || !text.includes('"frago_ui_component"')) return false;
  const parsed = parseUiComponentOutput(text);
  if (parsed !== null) return true;
  try {
    const obj = JSON.parse(text) as Record<string, unknown>;
    return Boolean(obj && typeof obj === 'object' && obj.frago_ui_component === UI_COMPONENT_MARKER);
  } catch {
    return false;
  }
}

/** 判断单条主会话记录是否携带交互卡（`answer-needed-by-human` 或 `decision-card`）。 */
export function recordHasInteractiveCard(record: WorkbenchRecord): boolean {
  if (record.agent_path.length > 0) return false;
  if (record.kind === 'agent.say') {
    const text = typeof record.payload.text === 'string' ? record.payload.text : '';
    if (!text.trim()) return false;
    if (splitTrailingBlock(text) !== null) return true;
    if (yamlNow() !== null) {
      const td = trailingDecision(text);
      if (td !== null) return true;
    }
    return hasUiDecisionCard(text);
  }
  if (record.kind === 'tool.result' && record.payload.status !== 'error') {
    const body = typeof record.payload.body === 'string' ? record.payload.body : '';
    if (!body.trim()) return false;
    return hasUiDecisionCard(body);
  }
  return false;
}

/** 判断单条主会话记录是否是人类点选交互卡发出的 `【answer】` 回复。 */
export function isCardAnswerRecord(record: WorkbenchRecord): boolean {
  if (record.agent_path.length > 0) return false;
  let text: unknown = null;
  if (record.kind === 'user.say') {
    if (record.payload.command) return false;
    text = record.payload.text;
  } else if (record.kind === 'context.inject' && record.payload.channel === 'queued_command') {
    text = record.payload.body;
  }
  return typeof text === 'string' && isCardAnswer(text.trimStart());
}

/**
 * 将主会话记录按「轮次」切分，保留每个有效回复轮次（含 `agent.say` 或交互卡），
 * 使末尾索引 `-1` 对应 `end` 轮、`-6` 对应 `end-5` 轮。
 */
export function segmentMainTurns(records: WorkbenchRecord[]): WorkbenchRecord[][] {
  const turns: WorkbenchRecord[][] = [];
  let current: WorkbenchRecord[] = [];
  let currentHasSay = false;
  let currentSayGroup: string | null = null;
  let currentHasAssistantStep = false;

  for (const rec of records) {
    if (rec.agent_path.length > 0) continue;
    if (BOOKKEEPING_KINDS.has(rec.kind)) {
      if (current.length > 0) current.push(rec);
      continue;
    }

    if (currentHasSay) {
      const sameGroup = Boolean(
        rec.group_id && currentSayGroup && rec.group_id === currentSayGroup
      );
      if (!sameGroup) {
        turns.push(current);
        current = [];
        currentHasSay = false;
        currentSayGroup = null;
        currentHasAssistantStep = false;
      }
    } else if (currentHasAssistantStep) {
      const isNewBoundary =
        rec.kind === 'user.say' ||
        (rec.kind === 'context.inject' && rec.payload.source === 'hook');
      if (isNewBoundary) {
        turns.push(current);
        current = [];
        currentHasSay = false;
        currentSayGroup = null;
        currentHasAssistantStep = false;
      }
    }

    current.push(rec);
    if (rec.kind === 'agent.say') {
      currentHasSay = true;
      currentSayGroup = rec.group_id ?? null;
      currentHasAssistantStep = true;
    } else if (
      rec.kind === 'agent.think' ||
      rec.kind === 'tool.call' ||
      rec.kind === 'tool.result'
    ) {
      currentHasAssistantStep = true;
    }
  }

  if (current.length > 0) {
    turns.push(current);
  }

  return turns.filter((turn) =>
    turn.some((r) => r.kind === 'agent.say' || recordHasInteractiveCard(r))
  );
}

/**
 * 检查末尾 `[end, end-5]`（共 6 轮）会话中是否存在未作答的交互卡。
 */
export function hasInteractiveCardInTailTurns(
  records: WorkbenchRecord[],
  window: number = TAIL_TURN_WINDOW
): boolean {
  const turns = segmentMainTurns(records);
  if (!turns.length) return false;
  const tailTurns = window > 0 ? turns.slice(-window) : turns;
  let hasUnansweredCard = false;
  for (const turn of tailTurns) {
    for (const rec of turn) {
      if (recordHasInteractiveCard(rec)) {
        hasUnansweredCard = true;
      } else if (hasUnansweredCard && isCardAnswerRecord(rec)) {
        hasUnansweredCard = false;
      }
    }
  }
  return hasUnansweredCard;
}

/**
 * 检测会话末尾是否已出现完成的 stop 轮次，返回该轮末尾实质记录的 `id`。
 */
export function detectStopTurnId(records: WorkbenchRecord[]): string | null {
  let lastSubstantive: WorkbenchRecord | null = null;
  for (const rec of records) {
    if (rec.agent_path.length > 0) continue;
    if (BOOKKEEPING_KINDS.has(rec.kind)) continue;
    if (rec.kind === 'context.inject') {
      if (rec.payload.channel === 'queued_command' && rec.payload.queue_state === 'pending') {
        lastSubstantive = rec;
      }
      continue;
    }
    lastSubstantive = rec;
  }
  if (!lastSubstantive) return null;
  if (lastSubstantive.kind === 'agent.say' || recordHasInteractiveCard(lastSubstantive)) {
    return lastSubstantive.id || 'stop';
  }
  return null;
}

export async function fetchSessionQueue(sessionId: string): Promise<SessionQueueResponse> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/sessions/${encodeURIComponent(sessionId)}/queue`
  );
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return (await res.json()) as SessionQueueResponse;
}

export async function enqueueSessionMessage(
  sessionId: string,
  text: string,
  images: string[] = [],
  documents: { name: string; data: string }[] = [],
  skills: string[] = []
): Promise<{ sid: string; item: QueuedMessageItem; items: QueuedMessageItem[] }> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/sessions/${encodeURIComponent(sessionId)}/queue`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, images, documents, skills }),
    }
  );
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === 'string' && body.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await res.json()) as { sid: string; item: QueuedMessageItem; items: QueuedMessageItem[] };
}

export async function deleteSessionQueueItem(
  sessionId: string,
  itemId: string
): Promise<QueuedMessageItem[]> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/sessions/${encodeURIComponent(sessionId)}/queue/${encodeURIComponent(itemId)}`,
    { method: 'DELETE' }
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = (await res.json()) as { items?: QueuedMessageItem[] };
  return data.items ?? [];
}

export async function reorderSessionQueue(
  sessionId: string,
  itemIds: string[]
): Promise<QueuedMessageItem[]> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/sessions/${encodeURIComponent(sessionId)}/queue`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_ids: itemIds }),
    }
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = (await res.json()) as { items?: QueuedMessageItem[] };
  return data.items ?? [];
}

export async function drainSessionQueue(sessionId: string): Promise<DrainQueueResponse> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/sessions/${encodeURIComponent(sessionId)}/queue/drain`,
    { method: 'POST' }
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as DrainQueueResponse;
}

export interface UseSessionQueueOptions {
  records: WorkbenchRecord[];
  recordsSessionId: string | null;
  running: boolean;
  onInjected?: (item: QueuedMessageItem) => void;
}

export function useSessionQueue(
  sessionId: string | null,
  { records, recordsSessionId, running, onInjected }: UseSessionQueueOptions
) {
  const [items, setItems] = useState<QueuedMessageItem[]>([]);
  const activeSessionRef = useRef<string | null>(sessionId);
  activeSessionRef.current = sessionId;
  const onInjectedRef = useRef(onInjected);
  onInjectedRef.current = onInjected;
  const drainingRef = useRef(false);
  const lastDrainedTurnRef = useRef<string | null>(null);

  const reload = useCallback(async (sid: string | null = activeSessionRef.current) => {
    if (!sid) {
      setItems([]);
      return;
    }
    try {
      const data = await fetchSessionQueue(sid);
      if (activeSessionRef.current === sid) {
        setItems(data.items ?? []);
      }
    } catch {
      if (activeSessionRef.current === sid) {
        setItems([]);
      }
    }
  }, []);

  useEffect(() => {
    setItems([]);
    drainingRef.current = false;
    lastDrainedTurnRef.current = null;
    if (!sessionId) return;
    void reload(sessionId);
  }, [sessionId, reload]);

  // 订阅服务端广播的队列更新与轮次完成事件
  useEffect(() => {
    if (!sessionId) return;
    const sid = sessionId;
    const client = getWebSocketClient();

    const onQueueUpdate = (msg: WebSocketMessage) => {
      const data = msg.data as { session_id?: string; items?: QueuedMessageItem[] } | undefined;
      if (!data || data.session_id !== sid) return;
      if (Array.isArray(data.items)) {
        setItems(data.items);
      }
    };

    const onTurnDone = (msg: WebSocketMessage) => {
      const data = msg.data as { session_id?: string; done?: boolean } | undefined;
      if (!data || data.session_id !== sid || !data.done) return;
      void reload(sid);
    };

    const unsubQueue = client.on(MessageType.SESSION_QUEUE_UPDATE, onQueueUpdate);
    const unsubTurn = client.on(MessageType.SESSION_TURN_DONE, onTurnDone);
    return () => {
      unsubQueue();
      unsubTurn();
    };
  }, [sessionId, reload]);

  const recordsMatchSession = Boolean(sessionId && recordsSessionId === sessionId);
  const blockedByCard = useMemo(
    () => (recordsMatchSession ? hasInteractiveCardInTailTurns(records, TAIL_TURN_WINDOW) : false),
    [records, recordsMatchSession]
  );
  const stopTurnId = useMemo(
    () => (recordsMatchSession ? detectStopTurnId(records) : null),
    [records, recordsMatchSession]
  );

  const enqueue = useCallback(
    async (
      text: string,
      images: string[] = [],
      documents: { name: string; data: string }[] = [],
      skills: string[] = []
    ) => {
      if (!sessionId) return null;
      const res = await enqueueSessionMessage(sessionId, text, images, documents, skills);
      if (activeSessionRef.current === sessionId) {
        setItems(res.items ?? []);
      }
      return res.item;
    },
    [sessionId]
  );

  const remove = useCallback(
    async (itemId: string) => {
      if (!sessionId) return;
      setItems((prev) => prev.filter((it) => it.id !== itemId));
      try {
        const next = await deleteSessionQueueItem(sessionId, itemId);
        if (activeSessionRef.current === sessionId) {
          setItems(next);
        }
      } catch {
        void reload(sessionId);
      }
    },
    [sessionId, reload]
  );

  const move = useCallback(
    async (itemId: string, direction: 'up' | 'down') => {
      if (!sessionId) return;
      const idx = items.findIndex((it) => it.id === itemId);
      if (idx < 0) return;
      const targetIdx = direction === 'up' ? idx - 1 : idx + 1;
      if (targetIdx < 0 || targetIdx >= items.length) return;
      const next = [...items];
      const [moved] = next.splice(idx, 1);
      next.splice(targetIdx, 0, moved);
      setItems(next);
      try {
        const saved = await reorderSessionQueue(
          sessionId,
          next.map((it) => it.id)
        );
        if (activeSessionRef.current === sessionId) {
          setItems(saved);
        }
      } catch {
        void reload(sessionId);
      }
    },
    [sessionId, items, reload]
  );

  // 当且仅当会话已 stop、检测到 stop 轮次出现，且 [end, end-5] 轮无交互卡时，触发自动注入最早一条消息
  useEffect(() => {
    if (!sessionId || !recordsMatchSession) return;
    if (items.length === 0) return;
    if (running) return;
    if (!stopTurnId) return;
    if (blockedByCard) return;

    const turnKey = `${sessionId}:${stopTurnId}`;
    if (drainingRef.current || lastDrainedTurnRef.current === turnKey) return;

    drainingRef.current = true;
    const timer = setTimeout(async () => {
      try {
        const res = await drainSessionQueue(sessionId);
        if (activeSessionRef.current !== sessionId) return;
        setItems(res.items ?? []);
        if (res.injected && res.item) {
          lastDrainedTurnRef.current = turnKey;
          onInjectedRef.current?.(res.item);
        }
      } catch {
        /* ignore drain transient failure */
      } finally {
        drainingRef.current = false;
      }
    }, 350);

    return () => {
      clearTimeout(timer);
      drainingRef.current = false;
    };
  }, [sessionId, recordsMatchSession, items.length, running, stopTurnId, blockedByCard]);

  return {
    items,
    blockedByCard,
    stopTurnId,
    enqueue,
    remove,
    move,
    reload,
  };
}
