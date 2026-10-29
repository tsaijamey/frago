import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowDownToLine,
  Check,
  Copy,
  Loader2,
  PowerOff,
  RefreshCw,
  Terminal,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  closeTmuxSessions,
  getSessionTerminal,
  type SessionTerminalSnapshot,
} from '../../api';

export interface SessionTerminalProps {
  sessionId: string | null;
  open: boolean;
  /** 当终端里的 tmux 会话被手动关闭时通知上层刷新会话状态 */
  onStopped?: () => void;
  /** 抓屏后把当前 tmux 是否存活同步给外层（例如 Executor 栏上的绿点） */
  onAliveChange?: (alive: boolean) => void;
}

interface AnsiSpan {
  text: string;
  fg?: string;
  bold?: boolean;
  dim?: boolean;
}

const ANSI_16_FG: Record<number, string> = {
  30: '#6e7681',
  31: '#ff7b72',
  32: '#3fb950',
  33: '#d29922',
  34: '#58a6ff',
  35: '#bc8cff',
  36: '#39c5cf',
  37: '#e6edf3',
  90: '#8b949e',
  91: '#ffa198',
  92: '#56d364',
  93: '#e3b341',
  94: '#79c0ff',
  95: '#d2a8ff',
  96: '#56d4dd',
  97: '#ffffff',
};

function xterm256ToHex(n: number): string | undefined {
  if (n < 0 || n > 255) return undefined;
  if (n < 8) return ANSI_16_FG[30 + n];
  if (n < 16) return ANSI_16_FG[90 + (n - 8)];
  if (n < 232) {
    const idx = n - 16;
    const r = Math.floor(idx / 36);
    const g = Math.floor((idx % 36) / 6);
    const b = idx % 6;
    const toByte = (v: number) => (v === 0 ? 0 : 55 + v * 40);
    const hex = (v: number) => toByte(v).toString(16).padStart(2, '0');
    return `#${hex(r)}${hex(g)}${hex(b)}`;
  }
  const gray = 8 + (n - 232) * 10;
  const h = gray.toString(16).padStart(2, '0');
  return `#${h}${h}${h}`;
}

/**
 * 轻量 ANSI SGR 解析：保留色彩、粗体与暗色，剥掉清屏/光标控制序列（如 `\x1b[2J`、`\x1b[H`）。
 */
export function parseAnsiSegments(raw: string): AnsiSpan[] {
  if (!raw) return [];
  // 先剥除非 SGR（非 m 结尾）的 CSI 序列（例如 [2J, [H, [?25h 等）与 OSC 序列
  const cleaned = raw
    .replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, '')
    .replace(/\x1b\[[0-9;?]*[A-LN-Za-ln-z]/g, '');

  const spans: AnsiSpan[] = [];
  const sgrRegex = /\x1b\[([0-9;]*)m/g;
  let lastIndex = 0;
  let fg: string | undefined;
  let bold = false;
  let dim = false;

  let match: RegExpExecArray | null;
  while ((match = sgrRegex.exec(cleaned)) !== null) {
    if (match.index > lastIndex) {
      spans.push({
        text: cleaned.slice(lastIndex, match.index),
        fg,
        bold: bold || undefined,
        dim: dim || undefined,
      });
    }
    lastIndex = sgrRegex.lastIndex;
    const codes = (match[1] || '0')
      .split(';')
      .map((s) => (s === '' ? 0 : Number.parseInt(s, 10)));
    for (let i = 0; i < codes.length; i += 1) {
      const c = codes[i];
      if (Number.isNaN(c) || c === 0) {
        fg = undefined;
        bold = false;
        dim = false;
      } else if (c === 1) {
        bold = true;
      } else if (c === 2) {
        dim = true;
      } else if (c === 22) {
        bold = false;
        dim = false;
      } else if (c === 39) {
        fg = undefined;
      } else if ((c >= 30 && c <= 37) || (c >= 90 && c <= 97)) {
        fg = ANSI_16_FG[c];
      } else if (c === 38 && codes[i + 1] === 5 && typeof codes[i + 2] === 'number') {
        fg = xterm256ToHex(codes[i + 2]);
        i += 2;
      }
    }
  }
  if (lastIndex < cleaned.length) {
    spans.push({
      text: cleaned.slice(lastIndex),
      fg,
      bold: bold || undefined,
      dim: dim || undefined,
    });
  }
  return spans;
}

const POLL_INTERVAL_MS = 2_000;

export function SessionTerminal({
  sessionId,
  open,
  onStopped,
  onAliveChange,
}: SessionTerminalProps) {
  const { t } = useTranslation();
  const [snapshot, setSnapshot] = useState<SessionTerminalSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [copiedAttach, setCopiedAttach] = useState(false);
  const [stopping, setStopping] = useState(false);
  const viewportRef = useRef<HTMLPreElement | null>(null);

  const fetchSnapshot = useCallback(
    async (silent = false) => {
      if (!sessionId) {
        setSnapshot(null);
        return;
      }
      if (!silent) setLoading(true);
      try {
        const res = await getSessionTerminal(sessionId, 600);
        setSnapshot(res);
        setError(null);
        onAliveChange?.(res.alive);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [sessionId, onAliveChange]
  );

  // 切会话时清空旧快照；如果当前正打开 Terminal 档位，立即拉取新会话的屏幕
  useEffect(() => {
    setSnapshot(null);
    setError(null);
    if (open && sessionId) {
      void fetchSnapshot(false);
    }
  }, [sessionId, open, fetchSnapshot]);

  // 打开期间定时轮询：活着时 2s 一刷，已结束时不再高频轮询
  useEffect(() => {
    if (!open || !sessionId) return;
    const id = window.setInterval(() => {
      if (snapshot && !snapshot.alive) return;
      void fetchSnapshot(true);
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [open, sessionId, snapshot, fetchSnapshot]);

  // 内容更新且开启自动贴底时滚到底部
  useEffect(() => {
    if (!open || !autoScroll) return;
    const el = viewportRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [open, autoScroll, snapshot?.content]);

  const handleCopyAttach = useCallback(() => {
    if (!snapshot?.tmux_name) return;
    const cmd = `tmux attach -t ${snapshot.tmux_name}`;
    void navigator.clipboard?.writeText(cmd);
    setCopiedAttach(true);
    window.setTimeout(() => setCopiedAttach(false), 1800);
  }, [snapshot?.tmux_name]);

  const handleStopTmux = useCallback(async () => {
    if (!snapshot?.tmux_name || stopping) return;
    setStopping(true);
    try {
      await closeTmuxSessions([snapshot.tmux_name]);
      await fetchSnapshot(false);
      onStopped?.();
    } finally {
      setStopping(false);
    }
  }, [snapshot?.tmux_name, stopping, fetchSnapshot, onStopped]);

  const segments = useMemo(
    () => parseAnsiSegments(snapshot?.content ?? ''),
    [snapshot?.content]
  );

  const hasContent = Boolean(snapshot?.content && snapshot.content.trim().length > 0);

  return (
    <div
      data-terminal-view
      className="flex h-full min-h-0 flex-col bg-bg-primary"
    >
      {/* 顶部状态与工具栏 */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border bg-bg-secondary/60 px-4 py-2 text-[12px]">
        <div className="flex min-w-0 items-center gap-2">
          <Terminal size={14} className="shrink-0 text-text-muted" />
          {snapshot?.alive ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-medium text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              {t('workbench.terminal.liveBadge')}
            </span>
          ) : snapshot?.source === 'saved_pane' ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-medium text-amber-300">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
              {t('workbench.terminal.savedBadge')}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-bg-tertiary px-2 py-0.5 text-[11px] text-text-muted">
              <span className="h-1.5 w-1.5 rounded-full bg-text-dim" />
              {t('workbench.terminal.offlineBadge')}
            </span>
          )}

          {snapshot?.tmux_name ? (
            <span
              className="truncate font-mono text-[11.5px] text-text-secondary"
              title={snapshot.tmux_name}
            >
              {snapshot.tmux_name}
            </span>
          ) : null}

          {snapshot?.pane_command ? (
            <span className="rounded bg-bg-tertiary px-1.5 py-0.5 font-mono text-[11px] text-text-muted">
              {snapshot.pane_command}
            </span>
          ) : null}

          {snapshot && snapshot.memory_mb > 0 ? (
            <span className=" font-mono text-[11px] text-text-muted">
              · {snapshot.memory_mb} MB
            </span>
          ) : null}
        </div>

        <div className="flex items-center gap-1.5">
          {snapshot?.alive && snapshot.tmux_name ? (
            <button
              type="button"
              onClick={handleCopyAttach}
              title={`tmux attach -t ${snapshot.tmux_name}`}
              className="inline-flex items-center gap-1 rounded border border-border bg-bg-primary px-2 py-1 text-[11px] text-text-secondary transition-colors hover:border-border-hover hover:text-text-primary"
            >
              {copiedAttach ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
              <span>{copiedAttach ? t('workbench.terminal.copiedAttach') : t('workbench.terminal.copyAttach')}</span>
            </button>
          ) : null}

          <button
            type="button"
            onClick={() => setAutoScroll((v) => !v)}
            aria-pressed={autoScroll}
            title={t('workbench.terminal.autoScrollHint')}
            className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[11px] transition-colors ${
              autoScroll
                ? 'border-accent/50 bg-accent/10 text-text-primary'
                : 'border-border bg-bg-primary text-text-muted hover:text-text-primary'
            }`}
          >
            <ArrowDownToLine size={12} />
            <span>{t('workbench.terminal.autoScroll')}</span>
          </button>

          <button
            type="button"
            onClick={() => void fetchSnapshot(false)}
            disabled={loading}
            title={t('workbench.terminal.refresh')}
            className="inline-flex items-center gap-1 rounded border border-border bg-bg-primary px-2 py-1 text-[11px] text-text-secondary transition-colors hover:border-border-hover hover:text-text-primary disabled:opacity-50"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            <span>{t('workbench.terminal.refresh')}</span>
          </button>

          {snapshot?.alive && snapshot.tmux_name ? (
            <button
              type="button"
              onClick={() => void handleStopTmux()}
              disabled={stopping}
              title={t('workbench.terminal.stopHint')}
              className="inline-flex items-center gap-1 rounded border border-red-500/30 bg-red-500/10 px-2 py-1 text-[11px] text-red-300 transition-colors hover:bg-red-500/20 disabled:opacity-50"
            >
              <PowerOff size={12} />
              <span>{t('workbench.terminal.stop')}</span>
            </button>
          ) : null}
        </div>
      </div>

      {/* 终端屏幕主体 */}
      <div className="relative flex min-h-0 flex-1 flex-col bg-[#0d1117]">
        {loading && !snapshot ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-[13px] text-text-muted">
            <Loader2 size={16} className="animate-spin" />
            <span>{t('workbench.terminal.loading')}</span>
          </div>
        ) : error ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center text-[13px] text-red-400">
            <p>{error}</p>
            <button
              type="button"
              onClick={() => void fetchSnapshot(false)}
              className="rounded border border-border bg-bg-secondary px-3 py-1 text-[12px] text-text-primary hover:bg-bg-tertiary"
            >
              {t('workbench.terminal.retry')}
            </button>
          </div>
        ) : hasContent ? (
          <pre
            ref={viewportRef}
            data-terminal-screen
            className="m-0 flex-1 overflow-auto p-4 font-mono text-[12.5px] leading-[1.55] text-[#e6edf3] selection:bg-accent/30 whitespace-pre-wrap break-words"
          >
            {segments.map((seg, idx) => (
              <span
                key={idx}
                style={{
                  color: seg.fg,
                  fontWeight: seg.bold ? 600 : undefined,
                  opacity: seg.dim ? 0.68 : undefined,
                }}
              >
                {seg.text}
              </span>
            ))}
          </pre>
        ) : (
          <div
            data-terminal-empty
            className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center"
          >
            <Terminal size={24} className="text-text-dim" />
            <p className="text-[13px] font-medium text-text-secondary">
              {t('workbench.terminal.emptyTitle')}
            </p>
            <p className="max-w-[440px] text-[12px] leading-[1.6] text-text-muted">
              {t('workbench.terminal.emptyBody')}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
