/**
 * ClaudeSessionsPage — Web dashboard homepage for managing Claude Code sessions.
 *
 * Scans ~/.claude/projects via /api/claude-sessions and lets the user browse,
 * filter (human / maybe / agent), search, copy a `claude --resume` command, and
 * peek at a session's message stream in a side panel.
 *
 * Inspired by the claude_sessions_dashboard recipe's view mode, rebuilt as a
 * native in-app React page using the shared theme tokens.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  RefreshCw,
  Copy,
  Check,
  Search,
  X,
  User,
  Bot,
  CircleHelp,
  MessageSquare,
  FolderGit2,
  Clock,
  Wrench,
  Terminal,
  Brain,
} from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import { getClaudeSessions, getClaudeSessionDetail } from '@/api';
import type {
  ClaudeSessionItem,
  ClaudeSessionHuman,
  ClaudeSessionDetail,
  ClaudeSessionBlock,
} from '@/api/client';

function MessageBlock({ block }: { block: ClaudeSessionBlock }) {
  switch (block.type) {
    case 'text':
      return <div className="cs-msg-text">{block.text}</div>;
    case 'thinking':
      return (
        <details className="cs-block cs-block--thinking">
          <summary className="cs-block-summary"><Brain size={12} /> thinking</summary>
          <pre className="cs-block-body">{block.text}</pre>
        </details>
      );
    case 'tool_use': {
      const input = typeof block.tool_input === 'string'
        ? block.tool_input
        : JSON.stringify(block.tool_input ?? {}, null, 2);
      return (
        <details className="cs-block cs-block--tool">
          <summary className="cs-block-summary"><Wrench size={12} /> {block.name || 'tool'}</summary>
          <pre className="cs-block-body">{input}</pre>
        </details>
      );
    }
    case 'tool_result':
      return (
        <details className={`cs-block cs-block--result ${block.is_error ? 'cs-block--error' : ''}`}>
          <summary className="cs-block-summary">
            <Terminal size={12} /> {block.is_error ? 'tool error' : 'tool result'}
          </summary>
          <pre className="cs-block-body">{block.content}</pre>
        </details>
      );
    case 'image':
      return <div className="cs-msg-text cs-block-image">[image]</div>;
    default:
      return null;
  }
}

const DAY_OPTIONS = [1, 7, 14, 30];

const HUMAN_META: Record<
  ClaudeSessionHuman,
  { Icon: typeof User; color: string; labelKey: string }
> = {
  human: { Icon: User, color: 'var(--accent-success)', labelKey: 'claudeSessions.filter.human' },
  maybe: { Icon: CircleHelp, color: 'var(--accent-warning)', labelKey: 'claudeSessions.filter.maybe' },
  agent: { Icon: Bot, color: 'var(--text-muted)', labelKey: 'claudeSessions.filter.agent' },
};

function relativeTime(iso: string | null): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const diffMs = Date.now() - then;
  const min = Math.floor(diffMs / 60000);
  if (min < 1) return 'just now';
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day}d ago`;
  return new Date(iso).toLocaleDateString();
}

export default function ClaudeSessionsPage() {
  const { t } = useTranslation();
  const showToast = useAppStore((s) => s.showToast);

  const [sessions, setSessions] = useState<ClaudeSessionItem[]>([]);
  const [scannedFiles, setScannedFiles] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(7);
  const [search, setSearch] = useState('');
  const [filters, setFilters] = useState<Record<ClaudeSessionHuman, boolean>>({
    human: true,
    maybe: true,
    agent: false,
  });
  const [copiedSid, setCopiedSid] = useState<string | null>(null);

  // Detail side panel
  const [detailSid, setDetailSid] = useState<string | null>(null);
  const [detail, setDetail] = useState<ClaudeSessionDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const fetchSessions = useCallback(async (lookbackDays: number) => {
    setLoading(true);
    setError(null);
    try {
      const res = await getClaudeSessions({ days: lookbackDays });
      setSessions(res.sessions);
      setScannedFiles(res.scanned_files);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSessions(days);
  }, [days, fetchSessions]);

  const counts = useMemo(() => {
    const c: Record<ClaudeSessionHuman, number> = { human: 0, maybe: 0, agent: 0 };
    for (const s of sessions) c[s.human] += 1;
    return c;
  }, [sessions]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return sessions.filter((s) => {
      if (!filters[s.human]) return false;
      if (!q) return true;
      const haystack = [
        s.title,
        s.name,
        s.ai_title,
        s.recap,
        s.first_user_full,
        s.project,
        s.branch,
        s.sid,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [sessions, filters, search]);

  const handleCopy = useCallback(
    async (cmd: string, sid: string) => {
      try {
        await navigator.clipboard.writeText(cmd);
        setCopiedSid(sid);
        showToast(t('claudeSessions.copied'), 'success');
        setTimeout(() => setCopiedSid((cur) => (cur === sid ? null : cur)), 1500);
      } catch {
        showToast(t('claudeSessions.copyFailed'), 'error');
      }
    },
    [showToast, t]
  );

  const openDetail = useCallback(async (sid: string) => {
    setDetailSid(sid);
    setDetail(null);
    setDetailLoading(true);
    try {
      const d = await getClaudeSessionDetail(sid, 300);
      setDetail(d);
    } catch {
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const closeDetail = useCallback(() => {
    setDetailSid(null);
    setDetail(null);
  }, []);

  const toggleFilter = (key: ClaudeSessionHuman) =>
    setFilters((f) => ({ ...f, [key]: !f[key] }));

  return (
    <div className="page-scroll" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-md)' }}>
      {/* Header */}
      <div className="cs-header">
        <div>
          <h1 className="cs-title">{t('claudeSessions.title')}</h1>
          <p className="cs-subtitle">{t('claudeSessions.subtitle')}</p>
        </div>
        <button
          type="button"
          className="cs-refresh"
          onClick={() => fetchSessions(days)}
          disabled={loading}
          title={t('claudeSessions.rescan')}
        >
          <RefreshCw size={15} className={loading ? 'cs-spin' : ''} />
          <span>{t('claudeSessions.rescan')}</span>
        </button>
      </div>

      {/* Toolbar */}
      <div className="cs-toolbar">
        {/* Date range */}
        <div className="cs-segment">
          {DAY_OPTIONS.map((d) => (
            <button
              key={d}
              type="button"
              className={`cs-segment-btn ${days === d ? 'active' : ''}`}
              onClick={() => setDays(d)}
            >
              {t('claudeSessions.days', { count: d })}
            </button>
          ))}
        </div>

        {/* Search */}
        <div className="cs-search">
          <Search size={14} className="cs-search-icon" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('claudeSessions.searchPlaceholder')}
          />
          {search && (
            <button type="button" className="cs-search-clear" onClick={() => setSearch('')}>
              <X size={13} />
            </button>
          )}
        </div>

        {/* Filter pills */}
        <div className="cs-pills">
          {(['human', 'maybe', 'agent'] as ClaudeSessionHuman[]).map((key) => {
            const meta = HUMAN_META[key];
            const active = filters[key];
            return (
              <button
                key={key}
                type="button"
                className={`cs-pill ${active ? 'active' : ''}`}
                style={active ? { borderColor: meta.color, color: meta.color } : undefined}
                onClick={() => toggleFilter(key)}
              >
                <meta.Icon size={13} />
                <span>{t(meta.labelKey)}</span>
                <span className="cs-pill-count">{counts[key]}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Status line */}
      <div className="cs-statusline">
        {loading
          ? t('claudeSessions.scanning')
          : t('claudeSessions.summary', {
              visible: visible.length,
              total: sessions.length,
              files: scannedFiles,
            })}
      </div>

      {/* Body */}
      {error ? (
        <div className="cs-empty">
          <p>{t('claudeSessions.error')}</p>
          <p className="cs-empty-hint">{error}</p>
        </div>
      ) : visible.length === 0 && !loading ? (
        <div className="cs-empty">
          <p>{t('claudeSessions.empty')}</p>
          <p className="cs-empty-hint">{t('claudeSessions.emptyHint')}</p>
        </div>
      ) : (
        <div className="cs-list">
          {visible.map((s) => {
            const meta = HUMAN_META[s.human];
            const primary = s.title || s.name || s.ai_title || t('claudeSessions.unnamed');
            const preview = s.recap || s.first_user_full;
            const isCopied = copiedSid === s.sid;
            return (
              <div
                key={s.sid}
                className={`cs-row ${detailSid === s.sid ? 'selected' : ''}`}
                onClick={() => openDetail(s.sid)}
              >
                <div className="cs-row-mark" title={s.human_reason} style={{ color: meta.color }}>
                  <meta.Icon size={16} />
                </div>

                <div className="cs-row-main">
                  <div className="cs-row-titleline">
                    <span className="cs-row-title">{primary}</span>
                    {s.name && s.title && <span className="cs-row-slug">{s.name}</span>}
                  </div>
                  {preview && <div className="cs-row-preview">{preview}</div>}
                  <div className="cs-row-meta">
                    {s.project && (
                      <span className="cs-chip" title={s.cwd || s.project}>
                        <FolderGit2 size={11} />
                        {s.branch || s.project}
                      </span>
                    )}
                    <span className="cs-chip">
                      <MessageSquare size={11} />
                      {s.n_user_messages + s.n_assistant_messages}
                    </span>
                    <span className="cs-chip">
                      <Clock size={11} />
                      {relativeTime(s.first_interaction_at)}
                    </span>
                  </div>
                </div>

                <button
                  type="button"
                  className={`cs-copy ${isCopied ? 'copied' : ''}`}
                  title={s.resume_command}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleCopy(s.resume_command, s.sid);
                  }}
                >
                  {isCopied ? <Check size={14} /> : <Copy size={14} />}
                  <span>{isCopied ? t('claudeSessions.copiedShort') : t('claudeSessions.resume')}</span>
                </button>
              </div>
            );
          })}
        </div>
      )}

      {/* Detail side panel */}
      {detailSid && (
        <>
          <div className="cs-drawer-backdrop" onClick={closeDetail} />
          <aside className="cs-drawer">
            <div className="cs-drawer-header">
              <div className="cs-drawer-titlebar">
                <div className="cs-drawer-title">
                  {(() => {
                    const s = sessions.find((x) => x.sid === detailSid);
                    return s ? s.title || s.name || s.ai_title || t('claudeSessions.unnamed') : detailSid;
                  })()}
                </div>
                <div className="cs-drawer-sid">{detailSid}</div>
              </div>
              <button type="button" className="cs-drawer-close" onClick={closeDetail}>
                <X size={18} />
              </button>
            </div>

            <div className="cs-drawer-actions">
              <button
                type="button"
                className="cs-copy"
                onClick={() => handleCopy(`claude --resume ${detailSid}`, detailSid)}
              >
                <Copy size={14} />
                <span>{t('claudeSessions.copyResume')}</span>
              </button>
              {detail?.truncated && (
                <span className="cs-drawer-trunc">
                  {t('claudeSessions.truncated', {
                    shown: detail.returned_messages,
                    total: detail.total_messages,
                  })}
                </span>
              )}
            </div>

            <div className="cs-drawer-stream">
              {detailLoading ? (
                <div className="cs-drawer-loading">{t('claudeSessions.loadingDetail')}</div>
              ) : detail && detail.messages.length > 0 ? (
                detail.messages.map((m, i) => {
                  const blocks = m.blocks && m.blocks.length > 0
                    ? m.blocks
                    : [{ type: 'text' as const, text: m.text }];
                  // A "user" message carrying only tool results is the tool talking
                  // back, not the human — label it accordingly.
                  const isToolReturn = m.role === 'user'
                    && blocks.every((b) => b.type === 'tool_result');
                  const displayRole = isToolReturn ? 'tool' : m.role;
                  return (
                    <div key={i} className={`cs-msg cs-msg-${displayRole}`}>
                      <div className="cs-msg-role">
                        {displayRole === 'user' ? <User size={12} />
                          : displayRole === 'tool' ? <Terminal size={12} />
                          : <Bot size={12} />}
                        <span>{displayRole}</span>
                      </div>
                      {blocks.map((b, j) => (
                        <MessageBlock key={j} block={b} />
                      ))}
                    </div>
                  );
                })
              ) : (
                <div className="cs-drawer-loading">{t('claudeSessions.noMessages')}</div>
              )}
            </div>
          </aside>
        </>
      )}
    </div>
  );
}
