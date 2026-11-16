import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  ArrowDownToLine,
  Check,
  Copy,
  CornerDownLeft,
  FolderOpen,
  Loader2,
  MessageSquare,
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
import {
  activityTs,
  useWorkbenchLabels,
  type WorkbenchSession,
} from '@/hooks/useWorkbenchSessions';
import type { ComposerUsage } from './Composer';
import { FAMILY_ICON, relativeTime, resumeCommand, shellArg } from './SessionItem';
import { formatDateTime } from './RecordCard';
import { formatTokensK, shortenPathMiddle, withTilde } from './filePaths';

export interface SessionTerminalProps {
  sessionId: string | null;
  open: boolean;
  /** 当前会话元数据（来自 SessionWorkbenchPage 的 selected） */
  session?: WorkbenchSession | null;
  /** 会话是否正在执行（包含服务端 running、awaitingAgent、inFlight） */
  sessionRunning?: boolean;
  /** 最近一条用量与模型读数 */
  usage?: ComposerUsage | null;
  /** 记录流统计（来自 RecordStream counts） */
  recordCounts?: { all: number; talk: number };
  /** 记录流是否还有未拉取的更早记录 */
  hasOlderRecords?: boolean;
  /** 当终端里的 tmux 会话被手动关闭时通知上层刷新会话状态 */
  onStopped?: () => void;
  /** 抓屏后把当前 tmux 是否存活同步给外层（例如镜头胶囊上的绿点） */
  onAliveChange?: (alive: boolean) => void;
  /** 切回「对话」Tab */
  onSwitchToTalk?: () => void;
  /** 聚焦底部消息输入框 */
  onFocusComposer?: () => void;
}

export type TerminalEmptyKind =
  | 'headless_running'
  | 'never_started'
  | 'completed'
  | 'dormant';

export type TerminalEmptyTone = 'running' | 'dormant' | 'error' | 'neutral';

export interface TerminalEmptyStateSpec {
  kind: TerminalEmptyKind;
  tone: TerminalEmptyTone;
  /** 顶部工具栏 Status Pill 文案 key */
  pillKey: string;
  /** 卡片主标题文案 key */
  titleKey: string;
  /** 卡片白话解释文案 key */
  descriptionKey: string;
  /** 主推按钮是否切回「对话」而非聚焦输入框 */
  preferSwitchToTalk: boolean;
  /** 是否有真实可恢复的后端会话记录（决定是否渲染 CLI --resume 命令） */
  hasResumableHistory: boolean;
  /** 后端判定的可续接性 */
  resumable: boolean;
  /** 不可续接原因（session_gone / not_resumable） */
  unresumableReason: 'session_gone' | 'not_resumable' | null;
  /** 若会话处于 error 状态且有阻塞摘要，附带展示 */
  errorSummary: string | null;
}

export function resolveTerminalEmptyState({
  session,
  snapshot,
  sessionRunning = false,
  usage = null,
  recordCounts = { all: 0, talk: 0 },
}: {
  session: WorkbenchSession | null;
  snapshot: SessionTerminalSnapshot | null;
  sessionRunning?: boolean;
  usage?: ComposerUsage | null;
  recordCounts?: { all: number; talk: number };
}): TerminalEmptyStateSpec {
  const isSyntheticOnly = usage?.model === '<synthetic>' && recordCounts.talk === 0;
  const hasHistory = recordCounts.all > 0 && !isSyntheticOnly;
  const resumable = snapshot?.resumable !== false;
  const unresumableReason: 'session_gone' | 'not_resumable' | null =
    snapshot?.resumable === false
      ? snapshot.unmount_reason === 'session_gone'
        ? 'session_gone'
        : 'not_resumable'
      : null;

  // 1. 场景 B：后台无头执行中（进程在跑，但未挂载交互式 tmux 窗格）
  if (
    snapshot?.hosting_mode === 'headless_subprocess' ||
    (session && (sessionRunning || session.status === 'running') && !snapshot?.alive)
  ) {
    return {
      kind: 'headless_running',
      tone: 'running',
      pillKey: 'workbench.terminal.empty.headless.pill',
      titleKey: 'workbench.terminal.empty.headless.title',
      descriptionKey: 'workbench.terminal.empty.headless.desc',
      preferSwitchToTalk: true,
      hasResumableHistory: hasHistory && resumable,
      resumable,
      unresumableReason,
      errorSummary: null,
    };
  }

  // 2. 场景 D：新会话尚未启动或仅存在合成占位（0 真实对话）
  if (
    !session ||
    (recordCounts.all === 0 && !sessionRunning && session.status !== 'error') ||
    isSyntheticOnly
  ) {
    return {
      kind: 'never_started',
      tone: 'neutral',
      pillKey: 'workbench.terminal.empty.neverStarted.pill',
      titleKey: 'workbench.terminal.empty.neverStarted.title',
      descriptionKey: 'workbench.terminal.empty.neverStarted.desc',
      preferSwitchToTalk: !resumable,
      hasResumableHistory: false,
      resumable,
      unresumableReason,
      errorSummary: null,
    };
  }

  // 3. 场景 C：已结束 / 分支已收口
  if (session.status === 'done' || session.relation?.closed === true) {
    return {
      kind: 'completed',
      tone: 'neutral',
      pillKey: 'workbench.terminal.empty.completed.pill',
      titleKey: 'workbench.terminal.empty.completed.title',
      descriptionKey: 'workbench.terminal.empty.completed.desc',
      preferSwitchToTalk: !resumable,
      hasResumableHistory: hasHistory && resumable,
      resumable,
      unresumableReason,
      errorSummary: null,
    };
  }

  // 4. 场景 A（默认兜底）：会话待命 / 终端已关闭（含异常退出提示）
  const isError = session.status === 'error';
  return {
    kind: 'dormant',
    tone: isError ? 'error' : 'dormant',
    pillKey: isError
      ? 'workbench.terminal.empty.dormantError.pill'
      : 'workbench.terminal.empty.dormant.pill',
    titleKey: isError
      ? 'workbench.terminal.empty.dormantError.title'
      : 'workbench.terminal.empty.dormant.title',
    descriptionKey: isError
      ? 'workbench.terminal.empty.dormantError.desc'
      : 'workbench.terminal.empty.dormant.desc',
    preferSwitchToTalk: !resumable,
    hasResumableHistory: hasHistory && resumable,
    resumable,
    unresumableReason,
    errorSummary: isError && session.digest_stuck ? session.digest_stuck : null,
  };
}

/** 生成本地终端续接命令；无真实历史或不支持直连时优雅降级为目录命令或 null。 */
export function buildTerminalSnippet(
  session: WorkbenchSession | null,
  hasResumableHistory: boolean
): { mode: 'resume' | 'cd'; command: string } | null {
  if (!session) return null;
  if (hasResumableHistory) {
    const cmd = resumeCommand(session);
    if (cmd) {
      if (session.family === 'coreagent' || !session.directory) {
        return { mode: 'resume', command: cmd };
      }
      return {
        mode: 'resume',
        command: `cd ${shellArg(session.directory)} && ${cmd}`,
      };
    }
  }
  if (session.directory) {
    return { mode: 'cd', command: `cd ${shellArg(session.directory)}` };
  }
  return null;
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
  const cleaned = raw
    // eslint-disable-next-line no-control-regex
    .replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, '')
    // eslint-disable-next-line no-control-regex
    .replace(/\x1b\[[0-9;?]*[A-LN-Za-ln-z]/g, '');

  const spans: AnsiSpan[] = [];
  // eslint-disable-next-line no-control-regex
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

const TONE_PILL_CLASSES: Record<TerminalEmptyTone, string> = {
  running: 'border-accent-primary-border bg-accent-primary-10 text-accent-primary',
  dormant: 'border-accent-warning-border bg-accent-warning-10 text-accent-warning',
  error: 'border-accent-error-border bg-accent-error-10 text-accent-error',
  neutral: 'border-border-color bg-bg-tertiary text-text-secondary',
};

const TONE_DOT_CLASSES: Record<TerminalEmptyTone, string> = {
  running: 'bg-accent-primary animate-pulse',
  dormant: 'bg-accent-warning',
  error: 'bg-accent-error',
  neutral: 'bg-text-dim',
};

const TONE_ICON_BOX_CLASSES: Record<TerminalEmptyTone, string> = {
  running: 'border-accent-primary-border bg-accent-primary-10 text-accent-primary',
  dormant: 'border-accent-warning-border bg-accent-warning-10 text-accent-warning',
  error: 'border-accent-error-border bg-accent-error-10 text-accent-error',
  neutral: 'border-border-color bg-[var(--surface-recessed)] text-text-muted',
};

export function SessionTerminal({
  sessionId,
  open,
  session = null,
  sessionRunning = false,
  usage = null,
  recordCounts = { all: 0, talk: 0 },
  hasOlderRecords = false,
  onStopped,
  onAliveChange,
  onSwitchToTalk,
  onFocusComposer,
}: SessionTerminalProps) {
  const { t } = useTranslation();
  const { familyLabel } = useWorkbenchLabels();
  const [snapshot, setSnapshot] = useState<SessionTerminalSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [copiedKey, setCopiedKey] = useState<'attach' | 'cmd' | 'cwd' | 'sid' | null>(null);
  const [stopping, setStopping] = useState(false);
  const viewportRef = useRef<HTMLPreElement | null>(null);
  const copyTimerRef = useRef<number | null>(null);
  const prevRunningRef = useRef(sessionRunning);

  const copyText = useCallback(
    (key: 'attach' | 'cmd' | 'cwd' | 'sid', text: string) => {
      if (!text) return;
      void navigator.clipboard?.writeText(text);
      setCopiedKey(key);
      if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
      copyTimerRef.current = window.setTimeout(() => setCopiedKey(null), 1800);
    },
    []
  );

  useEffect(() => {
    return () => {
      if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
    };
  }, []);

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

  // 切会话或打开 Terminal 时清空旧快照并立即拉取
  useEffect(() => {
    setSnapshot(null);
    setError(null);
    if (open && sessionId) {
      void fetchSnapshot(false);
    }
  }, [sessionId, open, fetchSnapshot]);

  // 底部输入框发送消息唤醒会话时，立即重抓一次终端状态
  useEffect(() => {
    const wasRunning = prevRunningRef.current;
    prevRunningRef.current = sessionRunning;
    if (open && sessionId && sessionRunning && !wasRunning) {
      void fetchSnapshot(true);
    }
  }, [open, sessionId, sessionRunning, fetchSnapshot]);

  // 存活时或正在发消息/运行中保持 2s 轮询，确保冷启动 tmux 后自动切入实时屏幕
  useEffect(() => {
    if (!open || !sessionId) return;
    if (!snapshot?.alive && !sessionRunning) return;
    const id = window.setInterval(() => {
      void fetchSnapshot(true);
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [open, sessionId, snapshot?.alive, sessionRunning, fetchSnapshot]);

  useEffect(() => {
    if (!open || !autoScroll) return;
    const el = viewportRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [open, autoScroll, snapshot?.content]);

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
  const emptySpec = useMemo(
    () =>
      resolveTerminalEmptyState({
        session,
        snapshot,
        sessionRunning,
        usage,
        recordCounts,
      }),
    [session, snapshot, sessionRunning, usage, recordCounts]
  );
  const snippet = useMemo(
    () => buildTerminalSnippet(session, emptySpec.hasResumableHistory),
    [session, emptySpec.hasResumableHistory]
  );

  const familyMeta = session ? FAMILY_ICON[session.family] : null;
  const activeTs = session ? activityTs(session) : 0;
  const modelDisplay =
    usage?.model && usage.model !== '<synthetic>'
      ? usage.model
      : t('workbench.terminal.snapshot.modelUnknown');
  const contextDisplay =
    usage?.context !== null && usage?.context !== undefined
      ? formatTokensK(usage.context)
      : t('workbench.terminal.snapshot.contextUnknown');

  const unresumableMessage =
    emptySpec.unresumableReason === 'session_gone'
      ? t('workbench.terminal.empty.unresumableGone')
      : emptySpec.unresumableReason === 'not_resumable'
        ? t('workbench.terminal.empty.unresumableReadonly')
        : null;

  return (
    <div
      data-terminal-view
      className="flex h-full min-h-0 flex-col bg-bg-primary"
    >
      {/* 顶部状态与工具栏（全用合法双主题令牌） */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border-color bg-bg-secondary px-4 py-2 text-[12px]">
        <div className="flex min-w-0 items-center gap-2">
          <Terminal size={14} strokeWidth={1.5} className="shrink-0 text-text-muted" />
          {snapshot?.alive ? (
            <span className="inline-flex h-[22px] items-center gap-1.5 rounded-full border border-accent-primary-border bg-accent-primary-10 px-2 text-[11px] font-medium text-accent-primary">
              <span className="h-1.5 w-1.5 rounded-full bg-accent-primary animate-pulse" />
              {t('workbench.terminal.liveBadge')}
            </span>
          ) : snapshot?.source === 'saved_pane' && hasContent ? (
            <span className="inline-flex h-[22px] items-center gap-1.5 rounded-full border border-accent-warning-border bg-accent-warning-10 px-2 text-[11px] font-medium text-accent-warning">
              <span className="h-1.5 w-1.5 rounded-full bg-accent-warning" />
              {t('workbench.terminal.savedBadge')}
            </span>
          ) : (
            <span
              data-testid="terminal-empty-pill"
              className={`inline-flex h-[22px] items-center gap-1.5 rounded-full border px-2 text-[11px] font-medium ${TONE_PILL_CLASSES[emptySpec.tone]}`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${TONE_DOT_CLASSES[emptySpec.tone]}`} />
              {t(emptySpec.pillKey)}
            </span>
          )}

          {snapshot?.tmux_name ? (
            <span
              className="truncate font-mono text-[12px] text-text-secondary"
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
            <span className="font-mono text-[11px] tabular-nums text-text-muted">
              · {snapshot.memory_mb} MB
            </span>
          ) : null}
        </div>

        <div className="flex items-center gap-1.5">
          {snapshot?.alive && snapshot.tmux_name ? (
            <button
              type="button"
              onClick={() => copyText('attach', `tmux attach -t ${snapshot.tmux_name}`)}
              title={`tmux attach -t ${snapshot.tmux_name}`}
              className="inline-flex h-7 items-center gap-1 rounded-[7px] border border-border-color bg-bg-primary px-2 text-[11px] text-text-secondary transition-colors hover:border-border-strong hover:text-text-primary"
            >
              {copiedKey === 'attach' ? (
                <Check size={12} strokeWidth={1.5} className="text-accent-primary" />
              ) : (
                <Copy size={12} strokeWidth={1.5} />
              )}
              <span>
                {copiedKey === 'attach'
                  ? t('workbench.terminal.copiedAttach')
                  : t('workbench.terminal.copyAttach')}
              </span>
            </button>
          ) : null}

          {/* 仅当存在真实终端内容流时渲染「自动贴底」，避免空状态亮起绿框误导 */}
          {hasContent ? (
            <button
              type="button"
              onClick={() => setAutoScroll((v) => !v)}
              aria-pressed={autoScroll}
              title={t('workbench.terminal.autoScrollHint')}
              className={`inline-flex h-7 items-center gap-1 rounded-[7px] border px-2 text-[11px] transition-colors ${
                autoScroll
                  ? 'border-accent-primary-border bg-accent-primary-10 text-accent-primary'
                  : 'border-border-color bg-bg-primary text-text-muted hover:border-border-strong hover:text-text-primary'
              }`}
            >
              <ArrowDownToLine size={12} strokeWidth={1.5} />
              <span>{t('workbench.terminal.autoScroll')}</span>
            </button>
          ) : null}

          <button
            type="button"
            onClick={() => void fetchSnapshot(false)}
            disabled={loading}
            title={t('workbench.terminal.refresh')}
            className="inline-flex h-7 items-center gap-1 rounded-[7px] border border-border-color bg-bg-primary px-2 text-[11px] text-text-secondary transition-colors hover:border-border-strong hover:text-text-primary disabled:opacity-50"
          >
            <RefreshCw size={12} strokeWidth={1.5} className={loading ? 'animate-spin' : ''} />
            <span>{t('workbench.terminal.refresh')}</span>
          </button>

          {snapshot?.alive && snapshot.tmux_name ? (
            <button
              type="button"
              onClick={() => void handleStopTmux()}
              disabled={stopping}
              title={t('workbench.terminal.stopHint')}
              className="inline-flex h-7 items-center gap-1 rounded-[7px] border border-accent-error-border bg-accent-error-10 px-2 text-[11px] text-accent-error transition-colors hover:brightness-110 disabled:opacity-50"
            >
              <PowerOff size={12} strokeWidth={1.5} />
              <span>{t('workbench.terminal.stop')}</span>
            </button>
          ) : null}
        </div>
      </div>

      {/* 终端屏幕主体：有真实 ANSI 内容走深色终端屏；其余走双主题工作台地层级画布 */}
      {!loading && !error && hasContent ? (
        <div className="relative flex min-h-0 flex-1 flex-col bg-[#0d1117]">
          <pre
            ref={viewportRef}
            data-terminal-screen
            className="m-0 flex-1 overflow-auto p-4 font-mono text-[13px] leading-[1.55] text-[#e6edf3] selection:bg-accent-primary-20 whitespace-pre-wrap break-words"
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
        </div>
      ) : (
        <div className="wb-term-empty-canvas relative flex min-h-0 flex-1 flex-col overflow-y-auto p-6 phone:p-4">
          {loading && !snapshot ? (
            <div className="m-auto flex items-center justify-center gap-2 text-[13px] text-text-muted">
              <Loader2 size={16} strokeWidth={1.5} className="animate-spin" />
              <span>{t('workbench.terminal.loading')}</span>
            </div>
          ) : error ? (
            <div className="ui-bezel-card m-auto flex w-full max-w-[440px] flex-col items-center gap-3 p-5 text-center">
              <p className="text-[13px] text-accent-error">{error}</p>
              <button
                type="button"
                onClick={() => void fetchSnapshot(false)}
                className="inline-flex h-7 items-center gap-1.5 rounded-[7px] border border-border-color bg-bg-secondary px-3 text-[12px] text-text-primary hover:border-border-strong hover:bg-bg-hover"
              >
                <RefreshCw size={13} strokeWidth={1.5} />
                <span>{t('workbench.terminal.retry')}</span>
              </button>
            </div>
          ) : (
            <div
              data-terminal-empty
              data-empty-kind={emptySpec.kind}
              data-resumable={emptySpec.resumable ? 'true' : 'false'}
              className="ui-bezel-card m-auto flex w-full max-w-[560px] flex-col gap-4 p-5"
            >
              {/* 1. 顶部状态头 */}
              <div className="flex items-start gap-3">
                <div
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-[8px] border ${TONE_ICON_BOX_CLASSES[emptySpec.tone]}`}
                >
                  {emptySpec.kind === 'headless_running' ? (
                    <Activity size={16} strokeWidth={1.5} />
                  ) : (
                    <Terminal size={16} strokeWidth={1.5} />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="text-[13px] font-semibold leading-[1.4] text-text-primary">
                    {t(emptySpec.titleKey)}
                  </h2>
                  <p className="mt-1 text-[12px] leading-[1.55] text-text-secondary">
                    {t(emptySpec.descriptionKey)}
                  </p>
                  {emptySpec.errorSummary ? (
                    <p
                      data-testid="terminal-empty-error-summary"
                      className="mt-2 rounded-[6px] border border-accent-error-border bg-accent-error-10 px-2.5 py-1.5 text-[11px] leading-[1.45] text-accent-error"
                    >
                      {emptySpec.errorSummary}
                    </p>
                  ) : null}
                  {unresumableMessage ? (
                    <p
                      data-testid="terminal-empty-unresumable"
                      className="mt-2 flex items-center gap-1.5 rounded-[6px] border border-accent-warning-border bg-accent-warning-10 px-2.5 py-1.5 text-[11px] leading-[1.45] text-accent-warning"
                    >
                      <AlertTriangle size={13} strokeWidth={1.5} className="shrink-0" />
                      <span>{unresumableMessage}</span>
                    </p>
                  ) : null}
                </div>
              </div>

              {/* 2. 会话元数据快照格（2×2 发丝网格） */}
              {session ? (
                <div
                  data-testid="terminal-session-snapshot"
                  className="grid grid-cols-2 gap-px overflow-hidden rounded-[8px] border border-border-subtle bg-border-subtle phone:grid-cols-1"
                >
                  {/* 格 1：执行内核与模型 */}
                  <div className="flex min-w-0 flex-col gap-1 bg-[var(--surface-recessed)] px-3 py-2.5">
                    <span className="text-[11px] text-text-muted">
                      {t('workbench.terminal.snapshot.kernel')}
                    </span>
                    <div className="flex min-w-0 items-center gap-1.5 text-[12px]">
                      {familyMeta ? (
                        <img
                          src={familyMeta.src}
                          alt=""
                          className="h-3.5 w-3.5 shrink-0 rounded-[3px] object-contain"
                        />
                      ) : null}
                      <span className="shrink-0 font-medium text-text-primary">
                        {familyLabel(session.family)}
                      </span>
                      <span className="text-text-dim">·</span>
                      <span
                        className="min-w-0 truncate font-mono text-[11px] text-text-muted"
                        title={usage?.model || modelDisplay}
                      >
                        {modelDisplay}
                      </span>
                    </div>
                  </div>

                  {/* 格 2：工作目录 */}
                  <div className="flex min-w-0 flex-col gap-1 bg-[var(--surface-recessed)] px-3 py-2.5">
                    <span className="text-[11px] text-text-muted">
                      {t('workbench.terminal.snapshot.cwd')}
                    </span>
                    <div className="flex min-w-0 items-center justify-between gap-1.5">
                      <span
                        className="min-w-0 truncate font-mono text-[12px] text-text-primary"
                        title={session.directory || undefined}
                      >
                        {session.directory
                          ? shortenPathMiddle(withTilde(session.directory))
                          : t('workbench.terminal.snapshot.cwdUnknown')}
                      </span>
                      {session.directory ? (
                        <button
                          type="button"
                          onClick={() => copyText('cwd', session.directory)}
                          title={t('workbench.terminal.actions.copyPath')}
                          aria-label={t('workbench.terminal.actions.copyPath')}
                          className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-[4px] text-text-muted hover:bg-bg-hover hover:text-text-primary"
                        >
                          {copiedKey === 'cwd' ? (
                            <Check size={12} strokeWidth={1.5} className="text-accent-primary" />
                          ) : (
                            <Copy size={12} strokeWidth={1.5} />
                          )}
                        </button>
                      ) : null}
                    </div>
                  </div>

                  {/* 格 3：会话规模与上下文水位 */}
                  <div className="flex min-w-0 flex-col gap-1 bg-[var(--surface-recessed)] px-3 py-2.5">
                    <span className="text-[11px] text-text-muted">
                      {t('workbench.terminal.snapshot.progress')}
                    </span>
                    <div className="flex min-w-0 items-center gap-1.5 font-mono text-[12px] tabular-nums text-text-primary">
                      <span className="truncate">
                        {t('workbench.terminal.snapshot.progressValue', {
                          prefix: hasOlderRecords ? '≥' : '',
                          records: recordCounts.all,
                          talks: recordCounts.talk,
                        })}
                      </span>
                      <span className="text-text-dim">·</span>
                      <span className="shrink-0 text-[11px] text-text-muted">
                        {t('workbench.terminal.snapshot.contextLabel', { value: contextDisplay })}
                      </span>
                    </div>
                  </div>

                  {/* 格 4：会话标识与最近活跃 */}
                  <div className="flex min-w-0 flex-col gap-1 bg-[var(--surface-recessed)] px-3 py-2.5">
                    <span className="text-[11px] text-text-muted">
                      {t('workbench.terminal.snapshot.identity')}
                    </span>
                    <div className="flex min-w-0 items-center justify-between gap-1.5">
                      <div className="flex min-w-0 items-center gap-1.5 font-mono text-[12px] tabular-nums">
                        <span className="text-text-primary" title={session.session_id}>
                          {session.session_id.slice(0, 8)}
                        </span>
                        <span className="text-text-dim">·</span>
                        <span
                          className="truncate font-sans text-[11px] text-text-muted"
                          title={activeTs ? formatDateTime(activeTs) : undefined}
                        >
                          {activeTs
                            ? relativeTime(activeTs)
                            : t('workbench.terminal.snapshot.timeUnknown')}
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={() => copyText('sid', session.session_id)}
                        title={t('workbench.terminal.actions.copySessionId')}
                        aria-label={t('workbench.terminal.actions.copySessionId')}
                        className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-[4px] text-text-muted hover:bg-bg-hover hover:text-text-primary"
                      >
                        {copiedKey === 'sid' ? (
                          <Check size={12} strokeWidth={1.5} className="text-accent-primary" />
                        ) : (
                          <Copy size={12} strokeWidth={1.5} />
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              ) : null}

              {/* 3. 可执行引导动作区 */}
              <div className="flex flex-col gap-2.5">
                {/* 动作 ①：单屏唯一主动作条 */}
                <div className="flex items-center justify-between gap-3 rounded-[8px] border border-border-color bg-bg-secondary px-3 py-2.5 phone:flex-col phone:items-stretch">
                  <div className="min-w-0">
                    <p className="text-[12px] font-medium text-text-primary">
                      {!emptySpec.resumable
                        ? t('workbench.terminal.actions.primaryUnresumableTitle')
                        : emptySpec.kind === 'headless_running'
                          ? t('workbench.terminal.actions.primaryHeadlessTitle')
                          : t('workbench.terminal.actions.primaryWakeTitle')}
                    </p>
                    <p className="mt-0.5 text-[11px] leading-[1.45] text-text-muted">
                      {!emptySpec.resumable
                        ? t('workbench.terminal.actions.primaryUnresumableDesc')
                        : emptySpec.kind === 'headless_running'
                          ? t('workbench.terminal.actions.primaryHeadlessDesc')
                          : t('workbench.terminal.actions.primaryWakeDesc')}
                    </p>
                  </div>
                  {emptySpec.preferSwitchToTalk && onSwitchToTalk ? (
                    <button
                      type="button"
                      data-testid="terminal-empty-primary-talk"
                      onClick={onSwitchToTalk}
                      className="inline-flex h-7 shrink-0 items-center justify-center gap-1.5 rounded-[7px] bg-accent-primary px-3 text-[12px] font-medium text-[var(--text-on-accent)] transition-[filter] hover:brightness-110"
                    >
                      <MessageSquare size={13} strokeWidth={1.5} />
                      <span>
                        {t('workbench.terminal.actions.switchToTalk', {
                          count: recordCounts.talk,
                        })}
                      </span>
                    </button>
                  ) : emptySpec.resumable && onFocusComposer ? (
                    <button
                      type="button"
                      data-testid="terminal-empty-focus-composer"
                      onClick={onFocusComposer}
                      className="inline-flex h-7 shrink-0 items-center justify-center gap-1.5 rounded-[7px] bg-accent-primary px-3 text-[12px] font-medium text-[var(--text-on-accent)] transition-[filter] hover:brightness-110"
                    >
                      <CornerDownLeft size={13} strokeWidth={1.5} />
                      <span>{t('workbench.terminal.actions.focusComposer')}</span>
                    </button>
                  ) : null}
                </div>

                {/* 动作 ②：本地终端续接命令框 */}
                {snippet ? (
                  <div className="flex flex-col gap-1">
                    <span className="text-[11px] font-medium text-text-muted">
                      {snippet.mode === 'resume'
                        ? t('workbench.terminal.actions.cliResumeLabel')
                        : t('workbench.terminal.actions.cliDirLabel')}
                    </span>
                    <div className="flex items-center gap-2 rounded-[8px] border border-border-subtle bg-[var(--surface-recessed)] px-3 py-2">
                      {snippet.mode === 'cd' ? (
                        <FolderOpen size={13} strokeWidth={1.5} className="shrink-0 text-text-muted" />
                      ) : (
                        <Terminal size={13} strokeWidth={1.5} className="shrink-0 text-text-muted" />
                      )}
                      <code
                        title={snippet.command}
                        className="min-w-0 flex-1 select-all truncate font-mono text-[12px] text-text-primary"
                      >
                        {snippet.command}
                      </code>
                      <button
                        type="button"
                        data-testid="terminal-empty-copy-cmd"
                        onClick={() => copyText('cmd', snippet.command)}
                        className="inline-flex h-6 shrink-0 items-center gap-1 rounded-[6px] border border-border-color bg-bg-primary px-2 text-[11px] text-text-secondary transition-colors hover:border-border-strong hover:text-text-primary"
                      >
                        {copiedKey === 'cmd' ? (
                          <Check size={12} strokeWidth={1.5} className="text-accent-primary" />
                        ) : (
                          <Copy size={12} strokeWidth={1.5} />
                        )}
                        <span>
                          {copiedKey === 'cmd'
                            ? t('workbench.terminal.copiedAttach')
                            : t('workbench.terminal.actions.copyCmd')}
                        </span>
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>

              {/* 4. 动作 ③：底部次级操作行 */}
              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border-subtle pt-3">
                {emptySpec.preferSwitchToTalk ? (
                  emptySpec.resumable && onFocusComposer ? (
                    <button
                      type="button"
                      data-testid="terminal-empty-focus-composer-secondary"
                      onClick={onFocusComposer}
                      className="inline-flex h-7 items-center gap-1.5 rounded-[7px] border border-border-color bg-bg-primary px-2.5 text-[12px] text-text-secondary transition-colors hover:border-border-strong hover:text-text-primary"
                    >
                      <CornerDownLeft size={13} strokeWidth={1.5} />
                      <span>{t('workbench.terminal.actions.queueFollowUp')}</span>
                    </button>
                  ) : (
                    <span />
                  )
                ) : onSwitchToTalk ? (
                  <button
                    type="button"
                    data-testid="terminal-empty-switch-talk"
                    onClick={onSwitchToTalk}
                    className="inline-flex h-7 items-center gap-1.5 rounded-[7px] border border-border-color bg-bg-primary px-2.5 text-[12px] text-text-secondary transition-colors hover:border-border-strong hover:text-text-primary"
                  >
                    <MessageSquare size={13} strokeWidth={1.5} />
                    <span>
                      {t('workbench.terminal.actions.switchToTalkFull', {
                        count: recordCounts.talk,
                      })}
                    </span>
                  </button>
                ) : (
                  <span />
                )}

                <button
                  type="button"
                  data-testid="terminal-empty-recheck"
                  onClick={() => void fetchSnapshot(false)}
                  disabled={loading}
                  className="inline-flex h-7 items-center gap-1.5 rounded-[7px] border border-border-color bg-bg-primary px-2.5 text-[12px] text-text-secondary transition-colors hover:border-border-strong hover:text-text-primary disabled:opacity-50"
                >
                  <RefreshCw size={12} strokeWidth={1.5} className={loading ? 'animate-spin' : ''} />
                  <span>{t('workbench.terminal.actions.recheck')}</span>
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
