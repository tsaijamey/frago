/**
 * useSessionSearch — ⌘K 浮窗的数据源，与 `frago session search` 是同一条检索。
 *
 * 一句话发去 `GET /api/workbench/search`：模型先把它摊成一组关键词，再扫遍会话备份，
 * 按命中的不同关键词数排序。字段与 `frago.session.search.SearchResult` 逐字对齐。
 *
 * **只在人按下回车时发。** 一趟里模型扩展要十几秒，边敲边搜每个字都烧一次模型，而
 * 前面那些结果一个都不会被看到。前一趟没回来就又搜了一句时直接掐掉，NEVER 让慢的那趟
 * 后到、把新一句的结果盖回旧的。
 */

import { useCallback, useRef, useState } from 'react';

import i18n from '@/i18n';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

export interface SessionSearchHit {
  /** 会话出自哪一家：`claude` 或 `opencode`。 */
  source: string;
  session_id: string;
  title: string | null;
  cwd: string | null;
  /** 最后活动时刻（epoch 秒），判不出时为 0。 */
  last_activity: number;
  matched_terms: string[];
  /** 命中的不同记录数。 */
  hit_lines: number;
  resume_command: string;
  /** 触到了计数上限，实际命中只多不少。 */
  capped: boolean;
  /** 这场只剩早期加工副本，搜不到 NEVER 等于没发生。 */
  degraded: boolean;
  snippets: { term: string; text: string }[];
}

export interface SessionSearchResult {
  query: string;
  plan: {
    terms: string[];
    note: string;
    /** `agent` 模型扩展 / `explicit` 调用方指定 / `literal` 退回原句切词。 */
    source: string;
  };
  hits: SessionSearchHit[];
  scanned_sessions: number;
  duration_ms: number;
  /** 这一趟没做全的地方。NEVER 藏起来——做不全却不说等于谎报覆盖面。 */
  warnings: string[];
}

export async function fetchSessionSearch(
  query: string,
  signal?: AbortSignal
): Promise<SessionSearchResult> {
  const res = await fetch(`${API_BASE_URL}/api/workbench/search?q=${encodeURIComponent(query)}`, {
    signal,
  });
  if (!res.ok) {
    throw new Error(i18n.t('sessionSearch.failed', { status: res.status }));
  }
  return (await res.json()) as SessionSearchResult;
}

export interface SessionSearchState {
  /** 正在搜、或者最后一次搜的是哪一句。 */
  query: string;
  result: SessionSearchResult | null;
  searching: boolean;
  error: string | null;
  run: (query: string) => void;
}

export function useSessionSearch(): SessionSearchState {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<SessionSearchResult | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inflight = useRef<AbortController | null>(null);

  const run = useCallback((raw: string) => {
    const q = raw.trim();
    if (!q) return;
    inflight.current?.abort();
    const controller = new AbortController();
    inflight.current = controller;
    setQuery(q);
    setSearching(true);
    setError(null);
    fetchSessionSearch(q, controller.signal)
      .then((body) => {
        setResult(body);
        setSearching(false);
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === 'AbortError') return;
        setResult(null);
        setError(e instanceof Error ? e.message : String(e));
        setSearching(false);
      });
  }, []);

  return { query, result, searching, error, run };
}
