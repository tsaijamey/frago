/**
 * useForYou — 哪几场会话此刻有 agent 停在输入框前等你。清单上只剩这一个标记。
 *
 * 人来清单要知道的是「哪几场要我读、要我接着说」，不是每场处在哪个状态（Running /
 * Done / Idle 都已退场）。一场会话挂「For you」当且仅当三条同时成立：
 *
 * 1. **开在 tmux 里**：tmux 清单认得出它（按名字里的编号，或屏底 claude 自报的 `sid=`）。
 *    这比会话清单的 `in_tmux` 准——`frago agent` 拉起的会话名字对不上编号。
 * 2. **客户端还活着**：窗格前台不是登录 shell。
 * 3. **停在待输入态**：没在转、没有后台 shell、没有编号菜单，输入框是空的（灰色建议与
 *    输入提示都算空）。
 *
 * 三条全是从终端直接读出的结构信号，NEVER 靠「末条是回复且超过 N 分钟」这类时间规则凑。
 * 判不出的（opencode、codex、codebuddy、非 frago 起的 tmux）一律不挂——宁可漏挂，不误挂。
 * worker 也不挂：它等的是主控，不是你。
 *
 * 挂上之后再看要不要**加重**（告警橙）：收尾在问你、让你选、出错停下。问句只认字面。
 *
 * 判据写成纯函数，用例直接盯它们（照 `useSessionViews` 的做法）。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getTmuxWaiting } from '@/api';
import type { TmuxWaitingItem } from '@/types/api';
import { useAutoRefresh } from './useAutoRefresh';
import { SESSION_REFRESH_MS, activityTs, type WorkbenchSession } from './useWorkbenchSessions';

/**
 * 加重的理由。`decision-card` 留给「要人拍板」卡片：卡片的解析与校验归
 * `20260924-webui-decision-cards`，那边落地后由调用方经 `decisionCardOf` 接进来。
 */
export type ForYouEmphasis = 'answer' | 'pick-one' | 'stopped' | 'decision-card';

export interface ForYouInfo {
  /** null = 中性描边 */
  emphasis: ForYouEmphasis | null;
  /** 从什么时候开始等你（毫秒）：tmux 行的 `last_stop_at`，给不出时退回会话的最后回复。 */
  waitingSince: number;
  /** 收尾原话；有合法卡片时是卡片的问题。 */
  words: string;
  /** 停下之后你没点开过 → 标题加粗。它不决定挂不挂。 */
  unseen: boolean;
}

/** 原话最多留多少字：两行放得下，截开头留结尾。 */
export const WORDS_MAX = 140;

/** 让你选：「A or B」「你来定」「选一个」。 */
const PICK_ONE = [/\b[A-Z]\s+or\s+[A-Z]\b/, /你来定|选一个|选哪个/, /\bpick one\b/i];

/**
 * 在问你：句末是问号，或带「要我…吗 / 告诉我 / 说一声 / Say the word」。
 *
 * 「报完工，等你验收」不算——本机 7 天 81 场，挂上等于每条都亮；「验收」只认「请你验收 /
 * 请你确认」这种明说的字面。
 */
const ASKING = [/[?？]\s*$/, /要我[^。！？\n]{0,40}吗/, /告诉我|说一声|请你验收|请你确认/, /\bsay the word\b/i];

/** 一段话切成句子，句末标点留在句子上。 */
function sentences(paragraph: string): string[] {
  return (paragraph.match(/[^。！？!?.\n]+[。！？!?.]*/g) ?? [])
    .map((s) => s.trim())
    .filter(Boolean);
}

function lastParagraph(text: string): string {
  const paras = text
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
  return paras[paras.length - 1] ?? '';
}

/** 超长截开头、保留结尾——要的东西（问句、选项）多在句末。 */
export function keepTail(text: string, max = WORDS_MAX): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  if (flat.length <= max) return flat;
  return `…${flat.slice(flat.length - max + 1).trimStart()}`;
}

/** 收尾里在让你选、在问你的那一句；都没有返回 null。 */
function pickSentence(text: string): { kind: 'answer' | 'pick-one'; sentence: string } | null {
  const para = lastParagraph(text);
  const all = sentences(para);
  for (let i = all.length - 1; i >= 0; i -= 1) {
    if (PICK_ONE.some((re) => re.test(all[i]))) return { kind: 'pick-one', sentence: all[i] };
  }
  if (PICK_ONE.some((re) => re.test(para))) return { kind: 'pick-one', sentence: para };
  for (let i = all.length - 1; i >= 0; i -= 1) {
    if (ASKING.some((re) => re.test(all[i]))) return { kind: 'answer', sentence: all[i] };
  }
  if (ASKING.some((re) => re.test(para))) return { kind: 'answer', sentence: para };
  return null;
}

/** 出错停下：卡住摘要有值、会话报错，或最后一轮的停止原因是出错。 */
function stoppedOnError(session: WorkbenchSession, row: TmuxWaitingItem): boolean {
  if (session.digest_stuck || session.status === 'error') return true;
  return /error|refus/i.test(row.stop_reason ?? '');
}

function parseTs(iso: string | null): number | null {
  if (!iso) return null;
  const n = Date.parse(iso);
  return Number.isFinite(n) ? n : null;
}

/**
 * 这一场挂不挂 For you，挂的话带什么。三条缺一条就是 null。
 *
 * `card` 是「要人拍板」卡片的问题（有合法卡片时）：原话换成它，加重为 decision-card。
 */
export function forYouOf(
  session: WorkbenchSession,
  row: TmuxWaitingItem | undefined,
  viewedAt: number | undefined,
  card: string | null = null
): ForYouInfo | null {
  if (session.origin !== 'human') return null;
  if (!row) return null;
  if (row.client_alive !== true) return null;
  if (row.awaiting_input !== true) return null;

  const waitingSince = parseTs(row.last_stop_at) ?? session.last_reply_at ?? activityTs(session);
  const text = row.closing_text || session.digest_done || '';
  const picked = pickSentence(text);
  let emphasis: ForYouEmphasis | null = null;
  let words = picked ? picked.sentence : lastParagraph(text);
  if (card) {
    emphasis = 'decision-card';
    words = card;
  } else if (stoppedOnError(session, row)) {
    emphasis = 'stopped';
    if (session.digest_stuck) words = session.digest_stuck;
  } else if (picked) {
    emphasis = picked.kind;
  }
  return {
    emphasis,
    waitingSince,
    words: keepTail(words),
    unseen: viewedAt === undefined || viewedAt < waitingSince,
  };
}

/** 能关的终端：客户端已经退出、只剩一个 shell。在等你的、在忙的都不算。 */
export function closableTerminals(rows: TmuxWaitingItem[]): TmuxWaitingItem[] {
  return rows.filter((r) => r.client_alive === false);
}

export interface ForYouState {
  /** 这一场的 For you；不挂为 null。 */
  infoOf: (sessionId: string) => ForYouInfo | null;
  /** 挂着 For you 的场数（只算人发起的）。 */
  count: number;
  /** 客户端已退出、可以关掉的那几个终端。 */
  closable: TmuxWaitingItem[];
  /** tmux 清单这一刻认得出的那几行。取不到时为空（当作零场，不弹错）。 */
  rows: TmuxWaitingItem[];
  /**
   * 本地先撤掉这一场的 For you：人刚发出一句话（或点了卡片），agent 接手期间什么都不挂。
   * 直到 tmux 清单报出比这一刻更晚的一次停下，才重新挂上。
   */
  suppress: (sessionId: string) => void;
  refresh: () => void;
}

export function useForYou(
  sessions: WorkbenchSession[],
  viewedAt: (sessionId: string) => number | undefined,
  decisionCardOf?: (sessionId: string) => string | null
): ForYouState {
  const [rows, setRows] = useState<TmuxWaitingItem[]>([]);
  const [suppressed, setSuppressed] = useState<Record<string, number>>({});
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const { refresh } = useAutoRefresh(
    async () => {
      try {
        const res = await getTmuxWaiting();
        if (alive.current) setRows(res.sessions ?? []);
      } catch {
        // 没起 tmux、接口报错：当作零场。清单照常，只是没有 For you 那一组。
        if (alive.current) setRows([]);
      }
    },
    { intervalMs: SESSION_REFRESH_MS }
  );

  const bySession = useMemo(() => {
    const map = new Map<string, TmuxWaitingItem>();
    for (const r of rows) if (r.session_id) map.set(r.session_id, r);
    return map;
  }, [rows]);

  const infos = useMemo(() => {
    const map = new Map<string, ForYouInfo>();
    for (const s of sessions) {
      const row = bySession.get(s.session_id);
      if (!row) continue;
      const hold = suppressed[s.session_id];
      if (hold !== undefined) {
        const stop = parseTs(row.last_stop_at);
        if (stop === null || stop <= hold) continue;
      }
      const info = forYouOf(s, row, viewedAt(s.session_id), decisionCardOf?.(s.session_id) ?? null);
      if (info) map.set(s.session_id, info);
    }
    return map;
  }, [sessions, bySession, suppressed, viewedAt, decisionCardOf]);

  const suppress = useCallback((sessionId: string) => {
    setSuppressed((prev) => ({ ...prev, [sessionId]: Date.now() }));
  }, []);

  const infoOf = useCallback((sessionId: string) => infos.get(sessionId) ?? null, [infos]);

  return useMemo(
    () => ({
      infoOf,
      count: infos.size,
      closable: closableTerminals(rows),
      rows,
      suppress,
      refresh,
    }),
    [infoOf, infos.size, rows, suppress, refresh]
  );
}
