/**
 * FileViewer — 会话文件清单上点开一份文件的浮窗（支持行级/选区批注、会话溯源落盘与打包填入对话框）。
 *
 * 1. **固定比例大视野窗口**：默认采用与主窗口成固定比例的 `88vw × 86vh`（改动对照模式 `92vw × 86vh`），
 *    给代码阅读与逐行批注留出充裕视野。
 * 2. **行级与选区批注**：点击行号 `+` 或在代码区划选多行文本，原地展开批注输入框；保存后实时落盘到
 *    `~/.frago/sessions/<family>/<sid>/file-annotations.json`，跟当前会话建立可溯源关联。
 * 3. **打包成完整新 prompt 填入对话框**：右侧批注栏底部提供「打包 N 条批注填入对话框」按钮（遵循全局单实心绿纪律，
 *    采用中性选中态描边按钮），点击后将所有批注连同溯源路径组装为结构化 prompt 直接填入底部 Composer，
 *    由用户确认或补充后按 Send 发送。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ChevronLeft,
  ChevronRight,
  Copy,
  Check,
  FileText,
  FolderOpen,
  Loader2,
  MessageSquarePlus,
  Send,
  X,
} from 'lucide-react';
import { getSessionFileContent, getSessionFileDiff } from '@/api';
import type { SessionFileContent, SessionFileDiff, SessionFileRow } from '@/types/api';
import {
  formatPackedAnnotationsPrompt,
  useFileAnnotations,
  type FileAnnotationsState,
} from '@/hooks/useFileAnnotations';
import FileDiff from './FileDiff';
import { baseOf, dirOf, langOf, withTilde } from './filePaths';
import { FILE_BADGE } from './fileBadge';
import {
  MAX_AUTODETECT_CHARS,
  MAX_HIGHLIGHT_CHARS,
  loadHighlighter,
} from '@/utils/codeHighlight';

export interface PackedAnnotationsPayload {
  text: string;
  count: number;
  tracePath: string;
}

export interface FileViewerProps {
  sessionId: string;
  /** 这场会话改过的全部文件，顺序与清单一致——‹ › 与「3 / 8」按它走。 */
  files: SessionFileRow[];
  index: number;
  onClose: () => void;
  /** ‹ › 翻上一个／下一个，绕圈。 */
  onStep: (delta: number) => void;
  /** 「打开所在目录」。真正去开的是页面那一侧（要报错、要提示），这里只管喊一声。 */
  onReveal: (path: string) => void;
  /** 外部传入的会话批注状态（不传则组件内部自己按 sessionId 挂载）。 */
  fileAnnotations?: FileAnnotationsState;
  /** 点击「打包 N 条批注填入对话框」时触发，把组装好的完整 prompt 填入 Composer。 */
  onPackPrompt?: (payload: PackedAnnotationsPayload) => void;
}

/** 字节数说成人看得懂的样子。 */
export function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * 把内容染上色。交回的是可以直接塞进 `dangerouslySetInnerHTML` 的 HTML——引擎自己会把
 * 正文里的尖括号转义掉，这一点是它的契约（`highlight()` 的输出永远是转义过的）。
 *
 * 交回 null 表示**不染色**：内容还没到、太大、或引擎取不回来。那边照原样摆纯文本。
 */
export function useHighlightedHtml(text: string | null, lang: string): string | null {
  const [html, setHtml] = useState<string | null>(null);
  useEffect(() => {
    if (text === null) {
      setHtml(null);
      return;
    }
    const budget = lang ? MAX_HIGHLIGHT_CHARS : MAX_AUTODETECT_CHARS;
    if (text.length > budget) {
      setHtml(null);
      return;
    }
    let alive = true;
    loadHighlighter()
      .then((hljs) => {
        if (!alive) return;
        if (lang && hljs.getLanguage(lang)) setHtml(hljs.highlight(text, { language: lang }).value);
        else if (text.length <= MAX_AUTODETECT_CHARS) setHtml(hljs.highlightAuto(text).value);
        else setHtml(null);
      })
      .catch(() => {
        if (alive) setHtml(null);
      });
    return () => {
      alive = false;
    };
  }, [text, lang]);
  return html;
}

interface DraftRange {
  lineStart: number;
  lineEnd: number;
  quote: string;
}

export default function FileViewer({
  sessionId,
  files,
  index,
  onClose,
  onStep,
  onReveal,
  fileAnnotations: externalAnnotations,
  onPackPrompt,
}: FileViewerProps) {
  const { t } = useTranslation();
  const internalAnnotations = useFileAnnotations(externalAnnotations ? null : sessionId);
  const annState = externalAnnotations ?? internalAnnotations;
  const { annotations, tracePath, addAnnotation, removeAnnotation } = annState;

  const file = files[index];
  const [content, setContent] = useState<SessionFileContent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [mode, setMode] = useState<'file' | 'changes'>('file');
  const [diff, setDiff] = useState<SessionFileDiff | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState<string | null>(null);

  const [annotationsOpen, setAnnotationsOpen] = useState(true);
  const [draftRange, setDraftRange] = useState<DraftRange | null>(null);
  const [draftNote, setDraftNote] = useState('');
  const draftInputRef = useRef<HTMLTextAreaElement | null>(null);
  const codeContainerRef = useRef<HTMLDivElement | null>(null);

  const path = file?.path ?? '';
  const lang = useMemo(() => langOf(path), [path]);

  // 现取文件内容；切换文件时收起未保存的行内批注草稿。
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setContent(null);
    setError(null);
    setLoading(true);
    setMode('file');
    setDiff(null);
    setDiffError(null);
    setDraftRange(null);
    setDraftNote('');
    getSessionFileContent(sessionId, path)
      .then((body) => {
        if (alive) setContent(body);
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [sessionId, path]);

  useEffect(
    () => () => {
      if (copyTimer.current) clearTimeout(copyTimer.current);
    },
    []
  );

  // 改动那一档：切过去才取。
  useEffect(() => {
    if (mode !== 'changes' || !path) return;
    let alive = true;
    setDiffLoading(true);
    setDiffError(null);
    getSessionFileDiff(sessionId, path)
      .then((body) => {
        if (alive) setDiff(body);
      })
      .catch((e: unknown) => {
        if (alive) setDiffError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setDiffLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [mode, sessionId, path]);

  // Esc 关（若行内批注框开着则先关批注框），← → 翻页（焦点在输入框内时不抢左右键）。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const inInput =
        e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement;
      if (e.key === 'Escape') {
        e.preventDefault();
        if (draftRange !== null) {
          setDraftRange(null);
          setDraftNote('');
          return;
        }
        onClose();
      } else if (!inInput && e.key === 'ArrowLeft') {
        onStep(-1);
      } else if (!inInput && e.key === 'ArrowRight') {
        onStep(1);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose, onStep, draftRange]);

  useEffect(() => {
    if (draftRange) {
      draftInputRef.current?.focus();
    }
  }, [draftRange]);

  const copyPath = useCallback(() => {
    void navigator.clipboard
      ?.writeText(path)
      .then(() => {
        setCopied(true);
        if (copyTimer.current) clearTimeout(copyTimer.current);
        copyTimer.current = setTimeout(() => setCopied(false), 1_500);
      })
      .catch(() => {});
  }, [path]);

  const text = content?.text ?? null;
  const html = useHighlightedHtml(text, lang);

  const lines = useMemo(() => {
    if (text === null) return [];
    const raw = text.split('\n');
    // 末尾换行不额外多出一行空行号（除非整份只有一个空串）
    if (raw.length > 1 && raw[raw.length - 1] === '') {
      return raw.slice(0, -1);
    }
    return raw;
  }, [text]);

  const htmlLines = useMemo(() => {
    if (html === null) return null;
    const raw = html.split('\n');
    if (raw.length > 1 && raw[raw.length - 1] === '') {
      return raw.slice(0, -1);
    }
    return raw;
  }, [html]);

  const currentFileAnnotations = useMemo(
    () => annotations.filter((a) => a.file === path),
    [annotations, path]
  );

  const countByFile = useMemo(() => {
    const map = new Map<string, number>();
    for (const ann of annotations) {
      map.set(ann.file, (map.get(ann.file) ?? 0) + 1);
    }
    return map;
  }, [annotations]);

  const openLineDraft = useCallback(
    (lineStart: number, lineEnd: number, customQuote?: string) => {
      if (!lines.length) return;
      const start = Math.max(1, Math.min(lineStart, lineEnd));
      const end = Math.min(lines.length, Math.max(lineStart, lineEnd));
      const sliceQuote =
        customQuote && customQuote.trim()
          ? customQuote.trim()
          : lines
              .slice(start - 1, end)
              .join('\n')
              .trim();
      setDraftRange({
        lineStart: start,
        lineEnd: end,
        quote: sliceQuote || lines[start - 1] || '',
      });
      setDraftNote('');
    },
    [lines]
  );

  const saveDraft = useCallback(() => {
    if (!draftRange || !path) return;
    const trimmed = draftNote.trim();
    if (!trimmed) return;
    addAnnotation({
      file: path,
      line_start: draftRange.lineStart,
      line_end: draftRange.lineEnd,
      quote: draftRange.quote,
      note: trimmed,
    });
    setDraftRange(null);
    setDraftNote('');
    setAnnotationsOpen(true);
  }, [draftRange, draftNote, path, addAnnotation]);

  const handleCodeMouseUp = useCallback(() => {
    const sel = window.getSelection?.();
    if (!sel || sel.isCollapsed) return;
    const selectedText = sel.toString().trim();
    if (!selectedText) return;
    const anchorEl =
      sel.anchorNode instanceof HTMLElement ? sel.anchorNode : sel.anchorNode?.parentElement;
    const focusEl =
      sel.focusNode instanceof HTMLElement ? sel.focusNode : sel.focusNode?.parentElement;
    const startRow = anchorEl?.closest?.('[data-line]') as HTMLElement | null;
    const endRow = focusEl?.closest?.('[data-line]') as HTMLElement | null;
    if (!startRow || !endRow) return;
    const l1 = Number(startRow.getAttribute('data-line'));
    const l2 = Number(endRow.getAttribute('data-line'));
    if (!Number.isFinite(l1) || !Number.isFinite(l2)) return;
    openLineDraft(Math.min(l1, l2), Math.max(l1, l2), selectedText);
    sel.removeAllRanges();
  }, [openLineDraft]);

  const handlePackToPrompt = useCallback(() => {
    if (!annotations.length) return;
    const effectiveTrace =
      tracePath || `~/.frago/sessions/.../${sessionId}/file-annotations.json`;
    const promptText = formatPackedAnnotationsPrompt(annotations, effectiveTrace);
    onPackPrompt?.({
      text: promptText,
      count: annotations.length,
      tracePath: effectiveTrace,
    });
    onClose();
  }, [annotations, tracePath, sessionId, onPackPrompt, onClose]);

  if (!file) return null;

  const iconBtn =
    'inline-flex h-[24px] w-[24px] shrink-0 items-center justify-center rounded-[6px] text-text-muted hover:bg-bg-hover hover:text-text-primary';

  const noPreview = () => {
    const reason = content?.reason;
    const line =
      reason === 'too-large'
        ? t('workbench.files.tooLarge', { size: content ? humanSize(content.size) : '' })
        : reason === 'not-text'
          ? t('workbench.files.notText')
          : t('workbench.files.noContent');
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-5 py-8 text-center text-[12px] leading-relaxed text-text-muted">
        <FileText size={28} strokeWidth={1.4} className="text-text-dim" />
        <span>{t('workbench.files.noPreview')}</span>
        <span className="max-w-[360px]">{line}</span>
        <button
          type="button"
          onClick={() => onReveal(file.path)}
          className="mt-1 rounded-[6px] px-2 py-[3px] text-[11px] text-text-secondary hover:bg-bg-hover hover:text-text-primary"
        >
          {t('workbench.files.openFolder')}
        </button>
      </div>
    );
  };

  return (
    <div
      data-testid="file-viewer"
      className="fixed inset-0 z-[80] flex items-center justify-center p-3"
      role="dialog"
      aria-modal="true"
      aria-label={baseOf(file.path)}
    >
      <div
        data-testid="file-viewer-backdrop"
        className="absolute inset-0 bg-[var(--bg-overlay)]"
        onClick={onClose}
      />

      {/* 固定比例大尺寸窗口：默认 88vw × 86vh，改动对照模式 92vw × 86vh，给阅读与批注留出开阔视野 */}
      <div
        data-testid="file-viewer-window"
        className={`relative flex h-[86vh] max-h-[calc(100vh-24px)] max-w-[calc(100vw-24px)] flex-col overflow-hidden rounded-[12px] border border-border-strong bg-bg-primary shadow-2xl ${
          mode === 'changes' ? 'w-[92vw]' : 'w-[88vw]'
        }`}
      >
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border-color px-3.5">
          <FileText size={14} className="shrink-0 text-text-muted" />
          <span className="min-w-0 flex-1 truncate font-mono text-[12px]">
            <span className="text-text-dim" title={dirOf(file.path)}>
              {withTilde(dirOf(file.path))}
            </span>
            <b className="ml-1 font-medium text-text-primary">{baseOf(file.path)}</b>
          </span>

          <span
            data-testid="file-viewer-badge"
            className={`shrink-0 rounded-[4px] px-1.5 py-[1px] text-[10.5px] ${
              FILE_BADGE[file.action].tone
            }`}
          >
            {t(FILE_BADGE[file.action].label)}
          </span>
          {file.count > 1 ? (
            <span className="shrink-0 font-mono text-[10.5px] text-text-muted">
              {t('workbench.files.touched', { n: file.count })}
            </span>
          ) : null}

          {text !== null ? (
            <span
              data-testid="file-viewer-mode"
              className="ml-1 flex shrink-0 items-center rounded-[6px] bg-bg-hover p-[2px]"
            >
              {(['file', 'changes'] as const).map((id) => (
                <button
                  key={id}
                  type="button"
                  data-testid={`file-viewer-mode-${id}`}
                  aria-pressed={mode === id}
                  onClick={() => setMode(id)}
                  className={`rounded-[4px] px-2 py-[2px] text-[11px] transition-colors duration-200 ${
                    mode === id
                      ? 'bg-bg-active font-medium text-text-primary'
                      : 'text-text-muted hover:text-text-secondary'
                  }`}
                >
                  {t(id === 'file' ? 'workbench.files.modeFile' : 'workbench.files.modeChanges')}
                </button>
              ))}
            </span>
          ) : null}

          {mode === 'file' ? (
            <button
              type="button"
              data-testid="file-viewer-annotate-toggle"
              aria-pressed={annotationsOpen}
              onClick={() => setAnnotationsOpen((v) => !v)}
              className={`ml-1 inline-flex h-[24px] shrink-0 items-center gap-1 rounded-[6px] border px-2 text-[11px] transition-colors ${
                annotationsOpen
                  ? 'border-[var(--sel-border)] bg-[var(--sel-bg)] font-medium text-text-primary'
                  : 'border-border-color text-text-secondary hover:bg-bg-hover hover:text-text-primary'
              }`}
            >
              <MessageSquarePlus size={12} />
              <span>{t('workbench.files.annotateToggle', { n: annotations.length })}</span>
            </button>
          ) : null}

          <span className="ml-1 flex shrink-0 items-center gap-0.5">
            <span className="mr-1 font-mono text-[11px] text-text-muted">
              {index + 1} / {files.length}
            </span>
            <button
              type="button"
              data-testid="file-viewer-prev"
              title={t('workbench.files.prev')}
              onClick={() => onStep(-1)}
              className={iconBtn}
            >
              <ChevronLeft size={14} />
            </button>
            <button
              type="button"
              data-testid="file-viewer-next"
              title={t('workbench.files.next')}
              onClick={() => onStep(1)}
              className={iconBtn}
            >
              <ChevronRight size={14} />
            </button>
            <button
              type="button"
              data-testid="file-viewer-copy"
              title={t('workbench.files.copyPath')}
              onClick={copyPath}
              className={iconBtn}
            >
              {copied ? <Check size={14} className="text-accent-info" /> : <Copy size={14} />}
            </button>
            <button
              type="button"
              data-testid="file-viewer-reveal"
              title={t('workbench.files.openFolderHint')}
              onClick={() => onReveal(file.path)}
              className={iconBtn}
            >
              <FolderOpen size={14} />
            </button>
            <button
              type="button"
              data-testid="file-viewer-close"
              title={t('workbench.files.close')}
              onClick={onClose}
              className={iconBtn}
            >
              <X size={14} />
            </button>
          </span>
        </div>

        <div
          className={`grid min-h-0 flex-1 tablet:grid-cols-1 ${
            mode === 'changes'
              ? 'grid-cols-1'
              : annotationsOpen
                ? 'grid-cols-[196px_minmax(0,1fr)_308px]'
                : 'grid-cols-[196px_minmax(0,1fr)]'
          }`}
        >
          {/* 左栏：会话改动文件导航（带各文件批注计数标） */}
          <div
            className={`min-h-0 overflow-auto border-r border-border-color bg-bg-secondary px-[6px] py-2 tablet:hidden ${
              mode === 'changes' ? 'hidden' : ''
            }`}
          >
            {files.map((row, i) => {
              const fileAnnCount = countByFile.get(row.path) ?? 0;
              return (
                <button
                  key={row.path}
                  type="button"
                  title={row.path}
                  onClick={() => onStep(i - index)}
                  className={`flex w-full items-center justify-between gap-1.5 rounded-[5px] px-2 py-1 text-left font-mono text-[11.5px] ${
                    i === index
                      ? 'bg-bg-active font-medium text-text-primary'
                      : 'text-text-muted hover:bg-bg-hover hover:text-text-secondary'
                  }`}
                >
                  <span className="min-w-0 flex-1 truncate">{baseOf(row.path)}</span>
                  {fileAnnCount > 0 ? (
                    <span
                      data-testid="file-viewer-nav-ann-count"
                      className="shrink-0 rounded-full bg-accent-warning-10 px-1.5 py-[1px] font-mono text-[10px] font-medium text-accent-warning"
                    >
                      {fileAnnCount}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>

          {/* 中栏：代码与行内批注区 */}
          <div
            ref={codeContainerRef}
            onMouseUp={mode === 'file' && text !== null ? handleCodeMouseUp : undefined}
            className="min-h-0 min-w-0 overflow-auto bg-bg-base"
          >
            {mode === 'changes' ? (
              <FileDiff diff={diff} loading={diffLoading} error={diffError} />
            ) : loading ? (
              <p className="flex h-full items-center justify-center gap-2 text-[12px] text-text-muted">
                <Loader2 size={14} className="animate-spin" />
                {t('workbench.files.loadingContent')}
              </p>
            ) : error ? (
              <div className="flex h-full flex-col items-center justify-center gap-2 px-5 text-center text-[12px] leading-relaxed text-text-muted">
                <FileText size={28} strokeWidth={1.4} className="text-text-dim" />
                <span>{t('workbench.files.readFailed')}</span>
                <span className="max-w-[360px]">{error}</span>
              </div>
            ) : text === null ? (
              noPreview()
            ) : (
              <div className="flex min-h-full flex-col">
                <div
                  data-testid="file-viewer-annotate-bar"
                  className="sticky top-0 z-[2] flex items-center justify-between gap-2 border-b border-border-color bg-bg-secondary px-3.5 py-1.5 text-[11px] text-text-muted"
                >
                  <span>{t('workbench.files.annotateHint')}</span>
                  {lines.length > 0 ? (
                    <button
                      type="button"
                      data-testid="file-viewer-quick-annotate"
                      onClick={() => openLineDraft(1, 1)}
                      className="shrink-0 rounded-[4px] border border-border-color px-1.5 py-[1px] font-mono text-[10.5px] text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                    >
                      + L1
                    </button>
                  ) : null}
                </div>

                <pre className="m-0 flex-1 py-2.5 font-mono text-[12px] leading-[1.65] text-text-secondary">
                  <code className="hljs block">
                    {lines.map((lineText, idx) => {
                      const lineNo = idx + 1;
                      const isAnnotated = currentFileAnnotations.some(
                        (a) => lineNo >= a.line_start && lineNo <= a.line_end
                      );
                      const endingHere = currentFileAnnotations.filter(
                        (a) => a.line_end === lineNo
                      );
                      const showDraftHere = draftRange !== null && draftRange.lineEnd === lineNo;
                      const lineHtml = htmlLines ? (htmlLines[idx] ?? '') : null;

                      return (
                        <div key={lineNo}>
                          <div
                            data-testid="file-viewer-line"
                            data-line={lineNo}
                            className={`group grid grid-cols-[52px_minmax(0,1fr)] items-baseline px-2 ${
                              isAnnotated ? 'bg-accent-warning-10' : 'hover:bg-bg-hover'
                            }`}
                          >
                            <button
                              type="button"
                              data-testid={`file-viewer-line-btn-${lineNo}`}
                              onClick={() => openLineDraft(lineNo, lineNo)}
                              className="relative flex w-full select-none items-center justify-end pr-3 font-mono text-[11px] text-text-dim hover:text-text-primary"
                              title={`L${lineNo}`}
                            >
                              <span className="absolute left-1.5 inline-flex h-[15px] w-[15px] items-center justify-center rounded-[3px] border border-border-strong bg-bg-elevated text-[11px] leading-none text-text-secondary opacity-0 transition-opacity group-hover:opacity-100">
                                +
                              </span>
                              <span>{lineNo}</span>
                            </button>
                            {lineHtml !== null ? (
                              <span
                                className="whitespace-pre-wrap break-all pl-1"
                                dangerouslySetInnerHTML={{ __html: lineHtml || ' ' }}
                              />
                            ) : (
                              <span className="whitespace-pre-wrap break-all pl-1">
                                {lineText || ' '}
                              </span>
                            )}
                          </div>

                          {endingHere.map((ann) => {
                            const rangeLabel =
                              ann.line_start === ann.line_end
                                ? `L${ann.line_start}`
                                : `L${ann.line_start}–L${ann.line_end}`;
                            return (
                              <div
                                key={ann.id}
                                data-testid="file-viewer-inline-card"
                                className="my-1.5 ml-[52px] mr-4 flex items-start gap-2 rounded-[7px] border border-border-color border-l-[3px] border-l-accent-warning bg-bg-secondary px-2.5 py-1.5 font-sans text-[12px] text-text-primary"
                              >
                                <span className="shrink-0 rounded-[4px] bg-accent-warning-10 px-1.5 py-[1px] font-mono text-[10.5px] font-semibold text-accent-warning">
                                  {rangeLabel}
                                </span>
                                <span className="min-w-0 flex-1 whitespace-pre-wrap break-words leading-[1.45]">
                                  {ann.note}
                                </span>
                                <button
                                  type="button"
                                  data-testid={`file-viewer-inline-remove-${ann.id}`}
                                  title={t('workbench.files.annotationRemove')}
                                  onClick={() => removeAnnotation(ann.id)}
                                  className="inline-flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[4px] text-text-muted hover:bg-bg-hover hover:text-text-primary"
                                >
                                  <X size={12} />
                                </button>
                              </div>
                            );
                          })}

                          {showDraftHere && draftRange ? (
                            <div
                              data-testid="file-viewer-inline-editor"
                              className="my-2 ml-[52px] mr-4 rounded-[8px] border border-border-strong bg-bg-elevated p-2.5 font-sans shadow-lg"
                            >
                              <div className="mb-1.5 flex items-center justify-between text-[11px] text-text-muted">
                                <span className="font-mono text-text-secondary">
                                  {t('workbench.files.annotateLineTitle', {
                                    file: baseOf(file.path),
                                    range:
                                      draftRange.lineStart === draftRange.lineEnd
                                        ? `L${draftRange.lineStart}`
                                        : `L${draftRange.lineStart}–L${draftRange.lineEnd}`,
                                  })}
                                </span>
                                <span>{t('workbench.files.annotateShortcutHint')}</span>
                              </div>
                              <div className="mb-2 max-h-[54px] overflow-hidden truncate rounded-[5px] border-l-2 border-border-strong bg-bg-secondary px-2 py-1 font-mono text-[11px] text-text-muted">
                                {draftRange.quote}
                              </div>
                              <textarea
                                ref={draftInputRef}
                                data-testid="file-viewer-inline-input"
                                value={draftNote}
                                onChange={(e) => setDraftNote(e.target.value)}
                                onKeyDown={(e) => {
                                  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                                    e.preventDefault();
                                    saveDraft();
                                  } else if (e.key === 'Escape') {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    setDraftRange(null);
                                    setDraftNote('');
                                  }
                                }}
                                rows={2}
                                placeholder={t('workbench.files.annotatePlaceholder')}
                                className="w-full resize-y rounded-[6px] border border-border-strong bg-bg-card px-2.5 py-1.5 text-[12px] leading-[1.45] text-text-primary outline-none focus:border-text-muted"
                              />
                              <div className="mt-2 flex items-center justify-end gap-1.5">
                                <button
                                  type="button"
                                  data-testid="file-viewer-inline-cancel"
                                  onClick={() => {
                                    setDraftRange(null);
                                    setDraftNote('');
                                  }}
                                  className="rounded-[6px] border border-border-color px-2.5 py-1 text-[11.5px] text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                                >
                                  {t('workbench.files.annotateCancel')}
                                </button>
                                <button
                                  type="button"
                                  data-testid="file-viewer-inline-save"
                                  disabled={!draftNote.trim()}
                                  onClick={saveDraft}
                                  className="rounded-[6px] border border-[var(--sel-border)] bg-[var(--sel-bg)] px-2.5 py-1 text-[11.5px] font-medium text-text-primary hover:bg-bg-active disabled:opacity-40"
                                >
                                  {t('workbench.files.annotateSave')}
                                </button>
                              </div>
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                  </code>
                </pre>
              </div>
            )}
          </div>

          {/* 右栏：会话级批注清单、落盘溯源路径与打包填入 Composer */}
          {mode === 'file' && annotationsOpen ? (
            <aside
              data-testid="file-viewer-annotations-rail"
              className="flex min-h-0 flex-col border-l border-border-color bg-bg-secondary tablet:hidden"
            >
              <div className="flex flex-col gap-1 border-b border-border-color px-3 py-2.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[12px] font-semibold text-text-primary">
                    {t('workbench.files.annotationsTitle')}
                  </span>
                  <span
                    data-testid="file-viewer-annotations-count"
                    className="rounded-full bg-bg-active px-2 py-[1px] font-mono text-[10.5px] text-text-secondary"
                  >
                    {annotations.length}
                  </span>
                </div>
                <div className="text-[10.5px] text-text-muted">
                  <div>{t('workbench.files.annotationsTraceHint')}</div>
                  <code
                    data-testid="file-viewer-trace-path"
                    title={tracePath}
                    className="mt-0.5 block truncate rounded-[4px] border border-border-color bg-bg-primary px-1.5 py-0.5 font-mono text-[10px] text-text-dim"
                  >
                    {tracePath || `~/.frago/sessions/.../${sessionId}/file-annotations.json`}
                  </code>
                </div>
              </div>

              <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-auto p-2.5">
                {annotations.length === 0 ? (
                  <p
                    data-testid="file-viewer-annotations-empty"
                    className="px-2 py-6 text-center text-[11.5px] leading-relaxed text-text-muted"
                  >
                    {t('workbench.files.annotationsEmpty')}
                  </p>
                ) : (
                  annotations.map((ann, idx) => {
                    const rangeLabel =
                      ann.line_start === ann.line_end
                        ? `L${ann.line_start}`
                        : `L${ann.line_start}–L${ann.line_end}`;
                    const targetIdx = files.findIndex((f) => f.path === ann.file);
                    return (
                      <div
                        key={ann.id}
                        data-testid="file-viewer-annotation-item"
                        onClick={() => {
                          if (targetIdx >= 0 && targetIdx !== index) {
                            onStep(targetIdx - index);
                          }
                        }}
                        className="cursor-pointer rounded-[8px] border border-border-color bg-bg-primary p-2.5 transition-colors hover:border-border-strong"
                      >
                        <div className="mb-1 flex items-center gap-1.5 text-[11px]">
                          <span className="font-mono text-[10.5px] text-text-dim">#{idx + 1}</span>
                          <span
                            className="min-w-0 flex-1 truncate font-mono text-text-secondary"
                            title={ann.file}
                          >
                            {baseOf(ann.file)}
                          </span>
                          <span className="shrink-0 rounded-[4px] bg-accent-warning-10 px-1.5 py-[1px] font-mono text-[10px] font-semibold text-accent-warning">
                            {rangeLabel}
                          </span>
                          <button
                            type="button"
                            data-testid={`file-viewer-annotation-delete-${ann.id}`}
                            title={t('workbench.files.annotationRemove')}
                            onClick={(e) => {
                              e.stopPropagation();
                              removeAnnotation(ann.id);
                            }}
                            className="inline-flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[4px] text-text-muted hover:bg-bg-hover hover:text-text-primary"
                          >
                            <X size={11} />
                          </button>
                        </div>
                        <div className="mb-1.5 truncate rounded-[4px] border-l-2 border-border-strong bg-bg-secondary px-1.5 py-1 font-mono text-[10.5px] text-text-muted">
                          {ann.quote}
                        </div>
                        <div className="whitespace-pre-wrap break-words text-[12px] leading-[1.45] text-text-primary">
                          {ann.note}
                        </div>
                      </div>
                    );
                  })
                )}
              </div>

              <div className="flex flex-col gap-1.5 border-t border-border-color p-2.5">
                {/* 遵循全局单实心绿规则（Send 独占实心绿），打包按钮采用中性选中态描边按钮 */}
                <button
                  type="button"
                  data-testid="file-viewer-pack-btn"
                  disabled={annotations.length === 0}
                  onClick={handlePackToPrompt}
                  className="flex w-full items-center justify-center gap-1.5 rounded-[8px] border border-[var(--sel-border)] bg-[var(--sel-bg)] px-3 py-2 text-[12px] font-semibold text-text-primary transition-colors hover:bg-bg-active disabled:cursor-not-allowed disabled:opacity-45"
                >
                  <Send size={13} />
                  <span>{t('workbench.files.packToPrompt', { n: annotations.length })}</span>
                </button>
                <span className="text-center text-[10.5px] text-text-dim">
                  {t('workbench.files.packFootHint')}
                </span>
              </div>
            </aside>
          ) : null}
        </div>
      </div>
    </div>
  );
}
