/**
 * vibe teaming 在界面这一侧的取数。
 *
 * 两件事分得很开，因为它们的失败方式不一样：
 *
 * - **本机状态**（参加了哪些 team、中继配没配）不联网，所以中继连不上时这一屏照样
 *   画得出来。要是把它和中继那边的状态合成一次请求，人会在中继断线时连「我参加了
 *   哪些 team」都看不见，而那正是他这时候最需要看的。
 * - **对方的记录**只能从中继取，所以它会失败，而且失败是常态的一种——对方还没加入、
 *   对方那边同步停了、网断了。它自己带着错误，不影响左边那一列。
 *
 * 右边那列的记录与左边是**同一种形状**（`WorkbenchRecord`）。这不是巧合：两家会话
 * 的记录在离开各自机器之前就已经被翻译成同一种统一记录了，所以两列能用同一个卡片
 * 组件画出来。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/** 本机参加的一个 team。 */
export interface TeamBinding {
  code: string;
  session_id: string;
  side: 'A' | 'B';
  active: boolean;
  pushed_seq: number;
}

export interface TeamState {
  member: string;
  configured: boolean;
  relay_url: string;
  prefix: string;
  interval_seconds: number;
  teams: TeamBinding[];
}

/** 中继那边对这个连接码的说法。 */
export interface TeamStatus {
  exists: boolean;
  side: 'A' | 'B' | null;
  peer_present: boolean;
  inbox: number;
  peer_inbox: number;
}

/** 对方那一列每隔多久重取一次。与服务端同步循环的默认节奏对齐。 */
const PEER_POLL_MS = 15_000;

/** 一次失败属于哪一类。与服务端那三个值一一对应。 */
export type TeamTrouble = 'bad_code' | 'relay_down' | 'busy';

/**
 * 一次 team 操作没成。
 *
 * 除了那句话，还带着**类别**——界面照类别分支，NEVER 去那句话里找「限流」「连不上」
 * 这几个词。换个说法、翻成别的语言，找词那套当场失效，而且不报错，只会把三种完全
 * 不同的处境一律显示成同一种。
 */
export class TeamError extends Error {
  readonly trouble: TeamTrouble;

  constructor(message: string, trouble: TeamTrouble) {
    super(message);
    this.name = 'TeamError';
    this.trouble = trouble;
  }
}

async function readJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    // 服务端那一句人能照着做的话原样交给界面，NEVER 换成「请求失败」——那句话让人
    // 无从下手。类别另走 `trouble`，见 `TeamError`。
    const raw = body && typeof body === 'object' ? (body as { detail?: unknown }).detail : null;
    const said = typeof raw === 'string' ? raw : (raw as { detail?: string } | null)?.detail;
    const trouble = (raw as { trouble?: TeamTrouble } | null)?.trouble;
    throw new TeamError(said || `HTTP ${res.status}`, trouble ?? 'relay_down');
  }
  return body as T;
}

/** 本机这一侧的 team 状态。不联网。 */
export function useTeamState() {
  const [state, setState] = useState<TeamState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    try {
      setState(await readJson<TeamState>('/api/team'));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { state, error, loading, reload };
}

/** 对方那一列：中继上存着的、对方会话的记录。 */
export function usePeerRecords(code: string | null) {
  const [records, setRecords] = useState<WorkbenchRecord[]>([]);
  const [status, setStatus] = useState<TeamStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // 换 team 的那一拍，手上还是上一个 team 的记录。不记下这批是谁的，人会把上一个
  // team 的对话当成这一个的——工作台中栏踩过同一个坑。
  const belongsTo = useRef<string | null>(null);

  const reload = useCallback(async () => {
    if (!code) {
      setRecords([]);
      setStatus(null);
      belongsTo.current = null;
      return;
    }
    setLoading(true);
    try {
      const [gotRecords, gotStatus] = await Promise.all([
        readJson<{ records: WorkbenchRecord[] }>(`/api/team/${encodeURIComponent(code)}/records`),
        readJson<TeamStatus>(`/api/team/${encodeURIComponent(code)}/status`),
      ]);
      belongsTo.current = code;
      setRecords(gotRecords.records || []);
      setStatus(gotStatus);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [code]);

  useEffect(() => {
    void reload();
    if (!code) return;
    const timer = window.setInterval(() => void reload(), PEER_POLL_MS);
    return () => window.clearInterval(timer);
  }, [code, reload]);

  return {
    records: belongsTo.current === code ? records : [],
    status,
    error,
    loading,
    reload,
  };
}

export async function openTeam(sessionId: string): Promise<{ code: string; side: string }> {
  return readJson('/api/team/open', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId }),
  });
}

export async function joinTeam(code: string, sessionId: string): Promise<{ code: string; side: string }> {
  return readJson('/api/team/join', {
    method: 'POST',
    body: JSON.stringify({ code, session_id: sessionId }),
  });
}

export async function leaveTeam(code: string): Promise<void> {
  await readJson(`/api/team/${encodeURIComponent(code)}/leave`, { method: 'POST' });
}

export async function sendToPeer(code: string, text: string): Promise<void> {
  await readJson(`/api/team/${encodeURIComponent(code)}/send`, {
    method: 'POST',
    body: JSON.stringify({ text, note: '' }),
  });
}
