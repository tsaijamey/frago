/**
 * useSessionQueue — 会话工作台自有消息队列（Message Queue）。
 *
 * 作用：
 * 1. 不在 agent 执行过程中把消息直接塞进其原生运行队列（避免打断当前执行流），而是堆积到
 *    frago 会话自有的持久化队列中；
 * 2. 当且仅当会话已 stop 且检测到含实际内容（如 assistant response 文本）的 stop 轮次出现后，
 *    其最后一轮实际内容会话没有未作答的交互卡，自动注入队列里最早的那一条消息，并从队列中删除该消息。
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

/** 仅检测最后一轮实际内容会话是否包含交互卡。 */
export const TAIL_TURN_WINDOW = 1;

/**
 * 相邻记录之间超过这个间隔，说明 agent 已经停过一段（人在等，或定时器在等），不再算同一轮。
 *
 * 取 120 秒：正常工具流的间隔是秒级，切不到；而「每隔 45～120 秒自查一次」的长驻轮询会被
 * 切成独立轮次。没有这道切分时，一场「派发 Worker 后用定时器自问自答数小时」的会话会把
 * 全部内容算成一个巨型末轮，轮内一次误判（如把命令回显当卡片）就把队列闸门关死到最后。
 */
export const TURN_SILENCE_GAP_MS = 120_000;

/** 定时唤醒类工具：agent 给自己挂定时器，或查看 / 撤销定时器，标志新一轮自查开始。 */
const ASYNC_WAKEUP_TOOL_NAMES = new Set([
  'schedulewakeup',
  'croncreate',
  'crondelete',
  'cronlist',
]);

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
  employees?: string[];
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

/** 独立的 `frago ask` / `frago app ask` 调用：命令名之前只允许路径与空白。 */
const STANDALONE_ASK_CMD_RE = /^\s*(?:[A-Za-z0-9_./-]*\/)?frago(?:\.exe)?\s+(?:app\s+)?ask\b/;
/** 帮助类选项：只是在查用法，不会真的产出待人回答的卡片。 */
const ASK_HELP_FLAG_RE = /(?:^|\s)(?:-h|--help)\b/;
/** shell 命令分隔符：出现即说明这不是一条独立命令，而是复合脚本的一部分。 */
const SHELL_CHAIN_RE = /(?:&&|\|\||;|\||\n)/;

/**
 * 这段命令行是不是**独立**的 `frago ask` 调用。
 *
 * 只有独立调用才可能产出「等着人点选」的卡片。复合脚本（`a && b`）里的 `frago ask`
 * 往往是校验用例或演示，它打印出来的卡片 JSON 是**命令输出内容**，不是挂给人类的卡。
 */
export function isStandaloneAskCommand(command: string): boolean {
  const cmd = (command || '').trim();
  if (!cmd) return false;
  if (ASK_HELP_FLAG_RE.test(cmd)) return false;
  const head = cmd.split(SHELL_CHAIN_RE)[0] ?? '';
  return STANDALONE_ASK_CMD_RE.test(head);
}

/** 取出 `tool.call` 里的命令行原文（各家内核字段名不一，逐个兜）。 */
function toolCallCommand(record: WorkbenchRecord): string {
  const args = record.payload.args;
  if (args && typeof args === 'object' && !Array.isArray(args)) {
    const obj = args as Record<string, unknown>;
    for (const key of ['CommandLine', 'command', 'cmd']) {
      const val = obj[key];
      if (typeof val === 'string' && val.trim()) return val;
    }
  }
  for (const key of ['command', 'cmd'] as const) {
    const val = record.payload[key];
    if (typeof val === 'string' && val.trim()) return val;
  }
  return '';
}

/** 这条 `tool.call` 是不是「挂了张待人回答的卡」的调用。`null` 表示判不出。 */
function toolCallAskVerdict(record: WorkbenchRecord): boolean | null {
  const command = toolCallCommand(record);
  if (command) return isStandaloneAskCommand(command);
  for (const key of ['tool_name', 'tool', 'name'] as const) {
    const name = record.payload[key];
    if (typeof name === 'string' && name.trim()) {
      const lower = name.trim().toLowerCase();
      return lower === 'ask' || lower === 'app_ask' || lower === 'frago_ask' || lower.endsWith('_ask');
    }
  }
  return null;
}

/**
 * 为 `records[index]` 这条 `tool.result` 找配对的 `tool.call`。
 * 优先级：`call_id` 相同 → 同 `group_id` 的最近一条 → 紧邻的前序调用。
 */
function pairedToolCall(
  records: WorkbenchRecord[],
  index: number
): WorkbenchRecord | null {
  const target = records[index];
  const targetCallId = target.payload.call_id;
  const targetGroup = target.group_id;
  let fallback: WorkbenchRecord | null = null;
  for (let j = index - 1; j >= 0; j -= 1) {
    const cand = records[j];
    if (cand.kind !== 'tool.call') continue;
    if (typeof targetCallId === 'string' && cand.payload.call_id === targetCallId) return cand;
    if (fallback === null) {
      if (targetGroup && cand.group_id === targetGroup) fallback = cand;
      else if (!targetGroup) fallback = cand;
    }
  }
  return fallback;
}

/** 各家内核给工具输出套的元数据行：判「正文是否就是那一个组件输出」时不算内容。 */
const TOOL_OUTPUT_WRAPPER_RE =
  /^\s*(?:Created At|Completed At|Command exited with code|Command output|Showing lines|Tool is running as a background task)\b.*$/gm;

/**
 * 正文是否就是**规范独立的**组件输出（剥掉内核元数据后只剩那一个卡片 JSON）。
 * 命令回显（`ps aux` 行、`=== CLI VALID TEST ===` 分段日志）在 JSON 之前还夹着别的输出行。
 */
function bodyIsBareComponentOutput(body: string): boolean {
  if ((body.match(/"frago_ui_component"/g) ?? []).length !== 1) return false;
  const parsed = parseUiComponentOutput(body);
  if (parsed === null || !parsed.ok) return false;
  const idx = body.indexOf('"frago_ui_component"');
  const start = body.lastIndexOf('{', idx);
  if (start < 0) return false;
  const prefix = body.slice(0, start).replace(TOOL_OUTPUT_WRAPPER_RE, '');
  return !prefix.trim();
}

/** 剥掉 Markdown 代码围栏内的内容，用于排除「示例 JSON」误判。 */
function stripMarkdownCodeFences(text: string): string {
  if (!text.includes('```')) return text;
  const out: string[] = [];
  let inFence = false;
  for (const line of text.split('\n')) {
    if (line.trimStart().startsWith('```')) {
      inFence = !inFence;
      continue;
    }
    if (!inFence) out.push(line);
  }
  return out.join('\n');
}

/** `tool.result` 里的卡片 JSON 是否为「真的挂给人类」的那张。 */
function toolResultIsLiveCard(
  record: WorkbenchRecord,
  body: string,
  records?: WorkbenchRecord[]
): boolean {
  if (records) {
    const index = records.findIndex((r) => r === record);
    if (index >= 0) {
      const call = pairedToolCall(records, index);
      if (call) {
        const verdict = toolCallAskVerdict(call);
        if (verdict !== null) return verdict;
      }
    }
  }
  return bodyIsBareComponentOutput(body);
}

/** 判断单条主会话记录是否携带交互卡（`answer-needed-by-human` 或 `decision-card`）。 */
export function recordHasInteractiveCard(
  record: WorkbenchRecord,
  records?: WorkbenchRecord[]
): boolean {
  if (record.agent_path.length > 0) return false;
  if (record.kind === 'agent.say') {
    const text = typeof record.payload.text === 'string' ? record.payload.text : '';
    if (!text.trim()) return false;
    if (splitTrailingBlock(text) !== null) return true;
    if (yamlNow() !== null) {
      const td = trailingDecision(text);
      if (td !== null) return true;
    }
    return hasUiDecisionCard(stripMarkdownCodeFences(text));
  }
  if (record.kind === 'tool.result' && record.payload.status !== 'error') {
    const body = typeof record.payload.body === 'string' ? record.payload.body : '';
    if (!body.trim()) return false;
    if (!hasUiDecisionCard(body)) return false;
    return toolResultIsLiveCard(record, body, records);
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

/** 判断单条主会话记录是否为含实际文本内容的 assistant 回复（`agent.say` 非空文本）。 */
function hasSubstantiveAssistantResponse(record: WorkbenchRecord): boolean {
  if (record.agent_path.length > 0) return false;
  if (record.kind !== 'agent.say') return false;
  const text = typeof record.payload.text === 'string' ? record.payload.text : '';
  return Boolean(text.trim());
}

/** 这条记录是否标志「一次异步定时唤醒」的开始（`schedule` 族工具调用、后台任务通知）。 */
function isAsyncWakeupBoundary(record: WorkbenchRecord): boolean {
  if (record.kind === 'tool.call') {
    const family = typeof record.payload.tool_family === 'string' ? record.payload.tool_family : '';
    const name = typeof record.payload.tool_name === 'string' ? record.payload.tool_name : '';
    return (
      family.trim().toLowerCase() === 'schedule' ||
      ASYNC_WAKEUP_TOOL_NAMES.has(name.trim().toLowerCase())
    );
  }
  if (record.kind === 'context.inject') {
    return (
      record.payload.channel === 'task-notification' ||
      record.payload.source === 'task-notification'
    );
  }
  return false;
}

/**
 * 将主会话记录按「轮次」切分，保留每个有效回复轮次（含非空 `agent.say` 或交互卡），
 * 使末尾索引 `-1` 对应最后一轮实际内容会话。
 *
 * 除用户发言与 hook 注入这两条显式边界外，**静默与定时唤醒也要切轮**：相邻记录间隔超过
 * `TURN_SILENCE_GAP_MS`，或一段工具流之后又遇到定时唤醒，就把已攒下的那段收成一轮。
 * 没有这道切分时，一场「派发 Worker 后用定时器自问自答数小时」的会话会把全部内容算成
 * 一个巨型末轮，轮内一次误判就把队列闸门关死到最后。
 */
export function segmentMainTurns(records: WorkbenchRecord[]): WorkbenchRecord[][] {
  const turns: WorkbenchRecord[][] = [];
  let current: WorkbenchRecord[] = [];
  let currentHasSay = false;
  let currentSayGroup: string | null = null;
  let currentHasAssistantStep = false;
  let prevTs: number | null = null;

  const closeCurrent = () => {
    if (current.length > 0) turns.push(current);
    current = [];
    currentHasSay = false;
    currentSayGroup = null;
    currentHasAssistantStep = false;
  };

  for (const rec of records) {
    if (rec.agent_path.length > 0) continue;
    if (BOOKKEEPING_KINDS.has(rec.kind)) {
      if (current.length > 0) current.push(rec);
      continue;
    }

    // 定时唤醒是新一轮自查的起点：上一轮已经说过话之后，再出现一次定时唤醒就另起一段。
    // 这一条不能只挂在「还没说话」的分支下——事故现场那场会话的自查循环每轮都有回复，
    // 而同一次派发里所有记录的 group_id 相同，只按 group 判永远切不开。
    // 也不能无条件切：首次挂定时器是本轮内的一个动作，切了会把人的提问和它的回答剥开。
    if (currentHasSay && isAsyncWakeupBoundary(rec)) closeCurrent();

    if (currentHasSay) {
      const sameGroup = Boolean(
        rec.group_id && currentSayGroup && rec.group_id === currentSayGroup
      );
      if (!sameGroup) closeCurrent();
    } else if (currentHasAssistantStep) {
      const isNewBoundary =
        rec.kind === 'user.say' ||
        (rec.kind === 'context.inject' && rec.payload.source === 'hook');
      const curTs = typeof rec.ts === 'number' ? rec.ts : null;
      const silentGap =
        prevTs !== null && curTs !== null && curTs - prevTs > TURN_SILENCE_GAP_MS;
      if (isNewBoundary || silentGap) closeCurrent();
    }

    const curTs = typeof rec.ts === 'number' ? rec.ts : null;
    current.push(rec);
    if (curTs !== null) prevTs = curTs;
    if (hasSubstantiveAssistantResponse(rec)) {
      currentHasSay = true;
      currentSayGroup = rec.group_id ?? null;
      currentHasAssistantStep = true;
    } else if (
      rec.kind === 'agent.say' ||
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
    turn.some((r) => hasSubstantiveAssistantResponse(r) || recordHasInteractiveCard(r, records))
  );
}

/**
 * 检查最后一轮实际内容会话（默认 `window = 1`）中是否存在未作答的交互卡。
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
      if (recordHasInteractiveCard(rec, records)) {
        hasUnansweredCard = true;
      } else if (hasUnansweredCard && isCardAnswerRecord(rec)) {
        hasUnansweredCard = false;
      }
    }
  }
  return hasUnansweredCard;
}

/**
 * 检测会话末尾是否已出现完成的 stop 轮次（最后一轮必须是实际内容如 assistant response 文本），返回该轮末尾实质记录的 `id`。
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
  if (
    hasSubstantiveAssistantResponse(lastSubstantive) ||
    recordHasInteractiveCard(lastSubstantive, records)
  ) {
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
  skills: string[] = [],
  employees: string[] = []
): Promise<{ sid: string; item: QueuedMessageItem; items: QueuedMessageItem[] }> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/sessions/${encodeURIComponent(sessionId)}/queue`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        images,
        documents,
        skills,
        ...(employees.length ? { employees } : {}),
      }),
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
      skills: string[] = [],
      employees: string[] = []
    ) => {
      if (!sessionId) return null;
      const res = await enqueueSessionMessage(
        sessionId,
        text,
        images,
        documents,
        skills,
        employees
      );
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
