/**
 * useDecisionCards — 决定卡片要的那份页面状态：这场能不能答、每张卡答过没有、点了怎么发。
 *
 * 会话页与 Teams 页左栏共用。两处都把它的 `host` 交给 `DecisionCardContext`，把 `answer`
 * 交给输入区，把包过的 `onSendStart` / `onSendFailed` 接到输入区原来那两处。
 *
 * **「答过没有」按记录判，页面不另存。** 卡片所在那条 agent 回复之后，主会话里人的第一条
 * 发言就是它的答复：以【answer】开头的是点卡片发的，按它认回选中项；不是的，是人自己打字
 * 回了话，卡片同样锁住、不高亮任何项。刷新之后照样判得出。
 *
 * 点了还没在记录里见到那句话的，本地先记一笔「在答」立即锁卡；发送失败就撤掉，卡片重新
 * 可点。认得出是哪一单失败，靠的是出门那一刻把信封编号记到这一笔上。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import type { DecisionAnswer, DecisionCardHost } from '@/components/sessionWorkbench/DecisionCard';
import { isCardAnswer } from '@/utils/decisionBlock';

/** 队友经结对中继转来的请求以它开头：那是队友的话，不是主人在答卡片。 */
const RELAY_PREFIX = '【frago team】';

/**
 * 这条记录是不是人在主会话里说的一句话，是的话取出原文。
 *
 * 算：直接打进来的发言、agent 正忙时打进去的插话。不算：斜杠命令（那是在操作会话，不是
 * 回话）、子 agent 里的记录、队友经中继转来的请求。
 */
export function humanReplyText(r: WorkbenchRecord): string | null {
  if (r.agent_path.length) return null;
  const p = r.payload;
  let text: unknown = null;
  if (r.kind === 'user.say') {
    if (typeof p.command === 'string' && p.command) return null;
    text = p.text;
  } else if (r.kind === 'context.inject' && p.channel === 'queued_command') {
    text = p.body;
  }
  if (typeof text !== 'string' || !text.trim()) return null;
  if (text.startsWith(RELAY_PREFIX)) return null;
  return text;
}

/** 每条主会话 agent 回复之后人的第一句话。没有就不在表里。 */
export function repliesAfter(records: WorkbenchRecord[]): Map<string, WorkbenchRecord> {
  const out = new Map<string, WorkbenchRecord>();
  let waiting: string[] = [];
  for (const r of records) {
    if (r.kind === 'agent.say' && !r.agent_path.length) {
      waiting.push(r.id);
    } else if (waiting.length && humanReplyText(r) !== null) {
      for (const id of waiting) out.set(id, r);
      waiting = [];
    }
  }
  return out;
}

interface Pending {
  text: string;
  at: number;
  outboundId?: string;
}

export interface UseDecisionCardsOptions {
  sessionId: string | null;
  records: WorkbenchRecord[];
  /** 输入区发不出去的原因（词表键）。卡片照写同一句。 */
  blockedReason: string | null;
  onSendStart: (text: string, attachments: number) => string | void;
  onSendFailed?: (outboundId?: string) => void;
}

export interface DecisionCardsState {
  host: DecisionCardHost;
  /** 交给输入区的那一句答复。 */
  answer: { text: string; at: number } | null;
  onSendStart: (text: string, attachments: number) => string | void;
  onSendFailed: (outboundId?: string) => void;
}

export function useDecisionCards({
  sessionId,
  records,
  blockedReason,
  onSendStart,
  onSendFailed,
}: UseDecisionCardsOptions): DecisionCardsState {
  const [pending, setPending] = useState<Record<string, Pending>>({});
  const [answer, setAnswer] = useState<{ text: string; at: number } | null>(null);
  // 编号用自增次数：同一句答复连发两次是两件事
  const seq = useRef(0);

  useEffect(() => {
    setPending({});
    setAnswer(null);
  }, [sessionId]);

  const replies = useMemo(() => repliesAfter(records), [records]);

  const answerOf = useCallback(
    (recordId: string): DecisionAnswer | null => {
      const r = replies.get(recordId);
      if (r) {
        const text = humanReplyText(r) ?? '';
        return { kind: isCardAnswer(text) ? 'card' : 'own-words', text, at: r.ts };
      }
      const p = pending[recordId];
      return p ? { kind: 'pending', text: p.text, at: p.at } : null;
    },
    [replies, pending]
  );

  const answerCard = useCallback((recordId: string, text: string) => {
    setPending((cur) => ({ ...cur, [recordId]: { text, at: Date.now() } }));
    seq.current += 1;
    setAnswer({ text, at: seq.current });
  }, []);

  // 出门那一刻把信封编号记到对应那一笔「在答」上：失败时凭它撤。
  const startRef = useRef(onSendStart);
  startRef.current = onSendStart;
  const wrappedStart = useCallback((text: string, attachments: number) => {
    const id = startRef.current(text, attachments) || undefined;
    if (id) {
      setPending((cur) => {
        const hit = Object.entries(cur).find(([, p]) => !p.outboundId && p.text === text);
        return hit ? { ...cur, [hit[0]]: { ...hit[1], outboundId: id } } : cur;
      });
    }
    return id;
  }, []);

  const failedRef = useRef(onSendFailed);
  failedRef.current = onSendFailed;
  const wrappedFailed = useCallback((outboundId?: string) => {
    failedRef.current?.(outboundId);
    if (!outboundId) return;
    setPending((cur) => {
      const hit = Object.entries(cur).find(([, p]) => p.outboundId === outboundId);
      if (!hit) return cur;
      const next = { ...cur };
      delete next[hit[0]];
      return next;
    });
  }, []);

  const host = useMemo<DecisionCardHost>(
    () => ({ canAnswer: !blockedReason, blockedReason, answerOf, answer: answerCard }),
    [blockedReason, answerOf, answerCard]
  );

  return { host, answer, onSendStart: wrappedStart, onSendFailed: wrappedFailed };
}
