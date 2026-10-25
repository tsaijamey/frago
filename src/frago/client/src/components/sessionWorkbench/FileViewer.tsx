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
  RotateCcw,
  Save,
  Send,
  X,
} from 'lucide-react';
import { getSessionFileContent, getSessionFileDiff, putSessionFileContent } from '@/api';
import type { SessionFileContent, SessionFileDiff, SessionFileRow } from '@/types/api';
import {
  formatPackedAnnotationsPrompt,
  useFileAnnotations,
  type FileAnnotationsState,
} from '@/hooks/useFileAnnotations';
import FileDiff from './FileDiff';
import {
  baseOf,
  dirOf,
  isEditableTextFile,
  langOf,
  previewKindOf,
  withTilde,
} from './filePaths';
import { FILE_BADGE } from './fileBadge';
import MarkdownContent from '@/components/ui/MarkdownContent';
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

export interface FileEditSendPayload {
  path: string;
  fileName: string;
  text: string;
}

export interface FileViewerProps {
  sessionId: string;
  /** 这场会话改过的全部文件，顺序与清单一致——‹ › 与「3 / 8」按它走。 */
  files: SessionFileRow[];
  index: number;
  /** 从对话链接点进来时附带的行号锚点（如 `L84`、`L314-L368`）。 */
  line?: string;
  onClose: () => void;
  /** ‹ › 翻上一个／下一个，绕圈。 */
  onStep: (delta: number) => void;
  /** 「打开所在目录」。真正去开的是页面那一侧（要报错、要提示），这里只管喊一声。 */
  onReveal: (path: string) => void;
  /** 外部传入的会话批注状态（不传则组件内部自己按 sessionId 挂载）。 */
  fileAnnotations?: FileAnnotationsState;
  /** 点击「打包 N 条批注填入对话框」时触发，把组装好的完整 prompt 填入 Composer。 */
  onPackPrompt?: (payload: PackedAnnotationsPayload) => void;
  /** 点击「发送修改到对话」时触发，直接把人类修改了该文件的通知发往对话区。 */
  onSendFileEdit?: (payload: FileEditSendPayload) => void | Promise<void>;
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

interface PendingSelection {
  lineStart: number;
  lineEnd: number;
  quote: string;
  left: number;
  top: number;
}

const HTML_ENTITIES: Record<string, string> = {
  '&nbsp;': ' ',
  '&amp;': '&',
  '&lt;': '<',
  '&gt;': '>',
  '&quot;': '"',
  '&#39;': "'",
  '&apos;': "'",
  '&mdash;': '—',
  '&ndash;': '–',
  '&hellip;': '…',
  '&copy;': '©',
};

/**
 * 将源码扫描为去除了 HTML 注释、style/script 块、HTML 标签与空白字符的紧凑字符流，
 * 并记录每个可见字符在源码中对应的 1-based 行号。
 */
function buildCompactSourceLineMap(sourceText: string): {
  compact: string;
  lineMap: number[];
} {
  let compact = '';
  const lineMap: number[] = [];
  let lineNo = 1;
  let i = 0;
  const n = sourceText.length;

  const advanceRange = (endIdx: number) => {
    while (i < endIdx && i < n) {
      if (sourceText[i] === '\n') lineNo += 1;
      i += 1;
    }
  };

  while (i < n) {
    const ch = sourceText[i];
    if (ch === '\n') {
      lineNo += 1;
      i += 1;
      continue;
    }

    // 跳过 HTML 注释 <!-- ... -->
    if (ch === '<' && sourceText.startsWith('<!--', i)) {
      const closeIdx = sourceText.indexOf('-->', i + 4);
      advanceRange(closeIdx === -1 ? n : closeIdx + 3);
      continue;
    }

    // 跳过 <style...>...</style>、<script...>...</script> 与普通 HTML 标签
    if (ch === '<') {
      const rest = sourceText.slice(i, i + 10).toLowerCase();
      if (rest.startsWith('<style') && /^<style[\s>/]/i.test(rest)) {
        const closeMatch = /<\/style\s*>/i.exec(sourceText.slice(i + 6));
        advanceRange(closeMatch ? i + 6 + closeMatch.index + closeMatch[0].length : n);
        continue;
      }
      if (rest.startsWith('<script') && /^<script[\s>/]/i.test(rest)) {
        const closeMatch = /<\/script\s*>/i.exec(sourceText.slice(i + 7));
        advanceRange(closeMatch ? i + 7 + closeMatch.index + closeMatch[0].length : n);
        continue;
      }
      if (i + 1 < n && /[a-zA-Z/!]/.test(sourceText[i + 1])) {
        const closeTag = sourceText.indexOf('>', i + 1);
        if (closeTag !== -1) {
          advanceRange(closeTag + 1);
          continue;
        }
      }
    }

    // 处理常见 HTML 字符实体
    if (ch === '&') {
      const semi = sourceText.indexOf(';', i + 1);
      if (semi !== -1 && semi - i <= 10) {
        const entity = sourceText.slice(i, semi + 1).toLowerCase();
        if (entity in HTML_ENTITIES) {
          const decoded = HTML_ENTITIES[entity];
          if (decoded && !/\s/.test(decoded)) {
            for (const c of decoded) {
              compact += c;
              lineMap.push(lineNo);
            }
          }
          i = semi + 1;
          continue;
        }
      }
    }

    if (!/\s/.test(ch)) {
      compact += ch;
      lineMap.push(lineNo);
    }
    i += 1;
  }

  return { compact, lineMap };
}

/**
 * 从文档渲染预览（Markdown / HTML）中划选的可见文本反查源码行号区间。
 * 支持跨 HTML 内联标签（如 `<span>`、`<strong>`、`<br/>`）、跨多行块级标签以及 Markdown 语法标记。
 */
export function resolvePreviewSelectionLines(
  sourceText: string,
  lines: string[],
  selectedText: string
): { lineStart: number; lineEnd: number } {
  const totalLines = Math.max(1, lines.length);

  // 1. 原样精确子串匹配
  const exactIdx = sourceText.indexOf(selectedText);
  if (exactIdx !== -1) {
    const lineStart = sourceText.slice(0, exactIdx).split('\n').length;
    const lineEnd = Math.min(totalLines, lineStart + selectedText.split('\n').length - 1);
    return { lineStart, lineEnd };
  }

  // 2. 剥离 HTML 标签、注释、style/script 与空白后的紧凑字符流映射匹配
  const compactSel = selectedText.replace(/\s+/g, '');
  if (compactSel.length > 0) {
    const { compact, lineMap } = buildCompactSourceLineMap(sourceText);
    const cIdx = compact.indexOf(compactSel);
    if (cIdx !== -1) {
      return {
        lineStart: lineMap[cIdx] ?? 1,
        lineEnd: lineMap[cIdx + compactSel.length - 1] ?? lineMap[cIdx] ?? 1,
      };
    }

    // 3. 剥离常见 Markdown 行内修饰符后再次匹配
    const mdStripRe = /[*_~`#>\-[\]()]/g;
    const mdSel = compactSel.replace(mdStripRe, '');
    if (mdSel.length > 0) {
      let mdCompact = '';
      const mdLineMap: number[] = [];
      for (let i = 0; i < compact.length; i += 1) {
        if (!mdStripRe.test(compact[i])) {
          mdCompact += compact[i];
          mdLineMap.push(lineMap[i]);
        }
        mdStripRe.lastIndex = 0;
      }
      const mIdx = mdCompact.indexOf(mdSel);
      if (mIdx !== -1) {
        return {
          lineStart: mdLineMap[mIdx] ?? 1,
          lineEnd: mdLineMap[mIdx + mdSel.length - 1] ?? mdLineMap[mIdx] ?? 1,
        };
      }
    }
  }

  // 4. 兜底：按非空首尾词段在去标签后的源码行中定位
  const plainLines = lines.map((l) => l.replace(/<[^>]+>/g, '').replace(/\s+/g, ''));
  const selLines = selectedText
    .split('\n')
    .map((s) => s.replace(/\s+/g, ''))
    .filter(Boolean);
  const firstToken = selLines[0] ?? '';
  const lastToken = selLines[selLines.length - 1] ?? '';

  if (firstToken) {
    const startIdx = plainLines.findIndex((pl) => pl.includes(firstToken));
    if (startIdx !== -1) {
      let endIdx = startIdx;
      if (lastToken && lastToken !== firstToken) {
        for (let j = startIdx; j < plainLines.length; j += 1) {
          if (plainLines[j].includes(lastToken)) {
            endIdx = j;
            break;
          }
        }
      } else {
        endIdx = Math.min(plainLines.length - 1, startIdx + Math.max(0, selLines.length - 1));
      }
      return { lineStart: startIdx + 1, lineEnd: endIdx + 1 };
    }
  }

  return { lineStart: 1, lineEnd: 1 };
}

export default function FileViewer({
  sessionId,
  files,
  index,
  line,
  onClose,
  onStep,
  onReveal,
  fileAnnotations: externalAnnotations,
  onPackPrompt,
  onSendFileEdit,
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

  const path = file?.path ?? '';
  const lang = useMemo(() => langOf(path), [path]);
  const previewKind = useMemo(() => previewKindOf(path), [path]);
  const canEdit = useMemo(() => isEditableTextFile(path), [path]);
  const modeTabs = useMemo(() => {
    const tabs: Array<'preview' | 'file' | 'changes' | 'edit'> = [];
    if (previewKind) tabs.push('preview');
    tabs.push('file', 'changes');
    if (canEdit) tabs.push('edit');
    return tabs;
  }, [previewKind, canEdit]);

  const [mode, setMode] = useState<'preview' | 'file' | 'changes' | 'edit'>(() =>
    previewKindOf(files[index]?.path ?? '') ? 'preview' : 'file'
  );
  const [diff, setDiff] = useState<SessionFileDiff | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState<string | null>(null);

  const [editText, setEditText] = useState('');
  const [savingEdit, setSavingEdit] = useState(false);
  const [sendingEdit, setSendingEdit] = useState(false);
  const [editSaveError, setEditSaveError] = useState<string | null>(null);
  const [hasSavedEditInSession, setHasSavedEditInSession] = useState(false);

  const [annotationsOpen, setAnnotationsOpen] = useState(true);
  const [draftRange, setDraftRange] = useState<DraftRange | null>(null);
  const [draftNote, setDraftNote] = useState('');
  const [pendingSelection, setPendingSelection] = useState<PendingSelection | null>(null);
  const draftInputRef = useRef<HTMLTextAreaElement | null>(null);
  const selectionToolbarRef = useRef<HTMLDivElement | null>(null);
  const codeContainerRef = useRef<HTMLDivElement | null>(null);
  const htmlIframeRef = useRef<HTMLIFrameElement | null>(null);
  const [iframeLoadTick, setIframeLoadTick] = useState(0);

  // 现取文件内容；切换文件时收起未保存的行内批注草稿，并根据是否支持文档渲染预览设置默认模式。
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setContent(null);
    setError(null);
    setLoading(true);
    setMode(previewKindOf(path) ? 'preview' : 'file');
    setDiff(null);
    setDiffError(null);
    setEditText('');
    setSavingEdit(false);
    setSendingEdit(false);
    setEditSaveError(null);
    setHasSavedEditInSession(false);
    setDraftRange(null);
    setDraftNote('');
    setPendingSelection(null);
    getSessionFileContent(sessionId, path)
      .catch(async (err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err);
        if (
          path.startsWith('/') &&
          typeof fetch === 'function' &&
          (msg.includes('not a file this session changed') || msg.includes('403'))
        ) {
          const res = await fetch(`/api/file?disposition=inline&path=${encodeURIComponent(path)}`);
          if (!res.ok) throw err;
          const rawText = await res.text();
          const isBinary = rawText.slice(0, 4096).includes('\u0000');
          return {
            path,
            size: rawText.length,
            text: isBinary ? null : rawText,
            reason: isBinary ? ('not-text' as const) : null,
          };
        }
        throw err;
      })
      .then((body) => {
        if (alive) {
          setContent(body);
          setEditText(body.text ?? '');
        }
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

  // 改动那一档：切过去才取（若刚刚在 Edit 模式保存过且服务端已随保存带回最新 diff，直接使用最新结果）。
  useEffect(() => {
    if (mode !== 'changes' || !path) return;
    if (diff !== null) return;
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, sessionId, path]);

  // Esc 关（若悬浮划词按钮或行内批注框开着则依次先关它们），← → 翻页（焦点在输入框内时不抢左右键）。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const inInput =
        e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement;
      if (e.key === 'Escape') {
        e.preventDefault();
        if (pendingSelection !== null) {
          setPendingSelection(null);
          return;
        }
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
    const onMouseDown = (e: MouseEvent) => {
      if (
        e.target instanceof Node &&
        selectionToolbarRef.current &&
        selectionToolbarRef.current.contains(e.target)
      ) {
        return;
      }
      setPendingSelection(null);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onMouseDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onMouseDown);
    };
  }, [onClose, onStep, draftRange, pendingSelection]);

  useEffect(() => {
    setPendingSelection(null);
  }, [mode]);

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
      setPendingSelection(null);
      setDraftRange({
        lineStart: start,
        lineEnd: end,
        quote: sliceQuote || lines[start - 1] || '',
      });
      setDraftNote('');
    },
    [lines]
  );

  const computeSelectionSpot = useCallback(
    (sel: Selection, inIframe: boolean): { left: number; top: number } => {
      const vw = typeof window !== 'undefined' && window.innerWidth ? window.innerWidth : 1024;
      const fallback = { left: Math.round(vw / 2), top: 112 };
      try {
        if (typeof sel.getRangeAt !== 'function' || (sel.rangeCount ?? 0) === 0) {
          return fallback;
        }
        const rect = sel.getRangeAt(0).getBoundingClientRect();
        if (!rect || (rect.width === 0 && rect.height === 0 && rect.top === 0 && rect.left === 0)) {
          return fallback;
        }
        if (inIframe && htmlIframeRef.current) {
          const frameRect = htmlIframeRef.current.getBoundingClientRect();
          const left = Math.min(Math.max(frameRect.left + rect.left + rect.width / 2, 72), vw - 72);
          const top = Math.max(frameRect.top + rect.top - 8, Math.max(56, frameRect.top + 36));
          return { left, top };
        }
        const left = Math.min(Math.max(rect.left + rect.width / 2, 72), vw - 72);
        const top = Math.max(rect.top - 8, 56);
        return { left, top };
      } catch {
        return fallback;
      }
    },
    []
  );

  const confirmPendingSelection = useCallback(() => {
    if (!pendingSelection) return;
    openLineDraft(pendingSelection.lineStart, pendingSelection.lineEnd, pendingSelection.quote);
    try {
      window.getSelection?.()?.removeAllRanges?.();
    } catch {
      // 忽略选区清理异常
    }
    try {
      const iframe = htmlIframeRef.current;
      const iframeSel =
        iframe?.contentWindow?.getSelection?.() ?? iframe?.contentDocument?.getSelection?.();
      iframeSel?.removeAllRanges?.();
    } catch {
      // 忽略受限选区清理异常
    }
  }, [pendingSelection, openLineDraft]);

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
    if (!sel || sel.isCollapsed) {
      setPendingSelection(null);
      return;
    }
    const selectedText = sel.toString().trim();
    if (!selectedText) {
      setPendingSelection(null);
      return;
    }
    const anchorEl =
      sel.anchorNode instanceof HTMLElement ? sel.anchorNode : sel.anchorNode?.parentElement;
    const focusEl =
      sel.focusNode instanceof HTMLElement ? sel.focusNode : sel.focusNode?.parentElement;
    const startRow = anchorEl?.closest?.('[data-line]') as HTMLElement | null;
    const endRow = focusEl?.closest?.('[data-line]') as HTMLElement | null;
    if (!startRow || !endRow) {
      setPendingSelection(null);
      return;
    }
    const l1 = Number(startRow.getAttribute('data-line'));
    const l2 = Number(endRow.getAttribute('data-line'));
    if (!Number.isFinite(l1) || !Number.isFinite(l2)) {
      setPendingSelection(null);
      return;
    }
    const spot = computeSelectionSpot(sel, false);
    setPendingSelection({
      lineStart: Math.min(l1, l2),
      lineEnd: Math.max(l1, l2),
      quote: selectedText,
      left: spot.left,
      top: spot.top,
    });
  }, [computeSelectionSpot]);

  /** 在文档渲染预览（Markdown / HTML）中划选文本时，反查源码行号区间并浮出「批注」选择按钮，保留原选区供用户直接复制。 */
  const handlePreviewSelection = useCallback(
    (sel: Selection | null | undefined, inIframe = false) => {
      if (!sel || sel.isCollapsed || text === null) {
        setPendingSelection(null);
        return;
      }
      const selectedText = sel.toString().trim();
      if (!selectedText) {
        setPendingSelection(null);
        return;
      }
      const { lineStart, lineEnd } = resolvePreviewSelectionLines(text, lines, selectedText);
      const spot = computeSelectionSpot(sel, inIframe);
      setPendingSelection({
        lineStart,
        lineEnd,
        quote: selectedText,
        left: spot.left,
        top: spot.top,
      });
    },
    [text, lines, computeSelectionSpot]
  );

  const handlePreviewMouseUp = useCallback(() => {
    handlePreviewSelection(window.getSelection?.(), false);
  }, [handlePreviewSelection]);

  const handleHtmlPreviewMouseUp = useCallback(() => {
    const iframe = htmlIframeRef.current;
    const iframeSel =
      iframe?.contentWindow?.getSelection?.() ?? iframe?.contentDocument?.getSelection?.();
    if (iframeSel && !iframeSel.isCollapsed && iframeSel.toString().trim()) {
      handlePreviewSelection(iframeSel, true);
      return;
    }
    handlePreviewSelection(window.getSelection?.(), false);
  }, [handlePreviewSelection]);

  // 为 HTML 渲染预览 iframe 内部文档挂载鼠标圈选批注与快捷键监听，并确保文本可划选。
  useEffect(() => {
    if (mode !== 'preview' || previewKind !== 'html') return;
    const doc = htmlIframeRef.current?.contentDocument;
    if (!doc) return;
    try {
      if (doc.head && !doc.head.querySelector('style[data-frago-preview-annotatable]')) {
        const styleEl = doc.createElement('style');
        styleEl.setAttribute('data-frago-preview-annotatable', 'true');
        styleEl.textContent =
          '*, *::before, *::after { -webkit-user-select: text !important; user-select: text !important; }';
        doc.head.appendChild(styleEl);
      }
    } catch {
      // 忽略只读或异常文档
    }
    const onMouseDown = () => {
      setPendingSelection(null);
    };
    const onMouseUp = () => {
      handleHtmlPreviewMouseUp();
    };
    const onKeyDown = (e: KeyboardEvent) => {
      const inInput =
        e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement;
      if (e.key === 'Escape') {
        e.preventDefault();
        if (pendingSelection !== null) {
          setPendingSelection(null);
          return;
        }
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
    doc.addEventListener('mousedown', onMouseDown);
    doc.addEventListener('mouseup', onMouseUp);
    doc.addEventListener('keydown', onKeyDown);
    return () => {
      doc.removeEventListener('mousedown', onMouseDown);
      doc.removeEventListener('mouseup', onMouseUp);
      doc.removeEventListener('keydown', onKeyDown);
    };
  }, [
    mode,
    previewKind,
    text,
    iframeLoadTick,
    handleHtmlPreviewMouseUp,
    pendingSelection,
    draftRange,
    onClose,
    onStep,
  ]);

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

  const isEditDirty = text !== null && editText !== text;

  const performSaveEdit = useCallback(async (): Promise<boolean> => {
    if (!path || text === null) return false;
    if (editText === text && hasSavedEditInSession) return true;
    setSavingEdit(true);
    setEditSaveError(null);
    try {
      const res = await putSessionFileContent(sessionId, path, editText);
      const nextText = typeof res?.text === 'string' ? res.text : editText;
      setContent({
        path: res?.path ?? path,
        size: typeof res?.size === 'number' ? res.size : new Blob([nextText]).size,
        text: nextText,
        reason: res?.reason ?? null,
      });
      setEditText(nextText);
      if (res?.diff) {
        setDiff(res.diff);
      } else {
        setDiff(null);
      }
      setDiffError(null);
      setHasSavedEditInSession(true);
      return true;
    } catch (e: unknown) {
      setEditSaveError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setSavingEdit(false);
    }
  }, [path, text, editText, hasSavedEditInSession, sessionId]);

  const handleSendEditToChat = useCallback(async () => {
    if (!path || text === null || sendingEdit || savingEdit) return;
    setSendingEdit(true);
    try {
      if (editText !== text || !hasSavedEditInSession) {
        const ok = await performSaveEdit();
        if (!ok) return;
      }
      const fileName = baseOf(path);
      const noticeText = t('workbench.files.editSentNotice', {
        path: withTilde(path),
        name: fileName,
      });
      await onSendFileEdit?.({
        path,
        fileName,
        text: noticeText,
      });
      onClose();
    } finally {
      setSendingEdit(false);
    }
  }, [
    path,
    text,
    sendingEdit,
    savingEdit,
    editText,
    hasSavedEditInSession,
    performSaveEdit,
    t,
    onSendFileEdit,
    onClose,
  ]);

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
            {line ? (
              <span data-testid="file-viewer-line-anchor" className="ml-1 text-text-muted">
                #{line}
              </span>
            ) : null}
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
              {modeTabs.map((id) => (
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
                  {t(
                    id === 'preview'
                      ? 'workbench.files.modePreview'
                      : id === 'file'
                        ? 'workbench.files.modeFile'
                        : id === 'changes'
                          ? 'workbench.files.modeChanges'
                          : 'workbench.files.modeEdit'
                  )}
                </button>
              ))}
            </span>
          ) : null}

          {mode !== 'edit' && hasSavedEditInSession ? (
            <button
              type="button"
              data-testid="file-viewer-edit-send"
              disabled={savingEdit || sendingEdit}
              onClick={() => void handleSendEditToChat()}
              className="ml-1 inline-flex h-[24px] shrink-0 items-center gap-1 rounded-[6px] border border-[var(--sel-border)] bg-[var(--sel-bg)] px-2 text-[11px] font-medium text-text-primary transition-colors hover:bg-bg-active disabled:cursor-not-allowed disabled:opacity-45"
            >
              {sendingEdit ? <Loader2 size={11} className="animate-spin" /> : <Send size={11} />}
              <span>
                {sendingEdit
                  ? t('workbench.files.editSendingToChat')
                  : t('workbench.files.editSendToChat')}
              </span>
            </button>
          ) : null}

          {mode !== 'changes' && mode !== 'edit' ? (
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
              : mode === 'edit' || !annotationsOpen
                ? 'grid-cols-[196px_minmax(0,1fr)]'
                : 'grid-cols-[196px_minmax(0,1fr)_308px]'
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
            ) : mode === 'edit' && canEdit ? (
              <div data-testid="file-viewer-edit-panel" className="flex h-full min-h-0 flex-col">
                <div
                  data-testid="file-viewer-edit-bar"
                  className="sticky top-0 z-[2] flex flex-wrap items-center justify-between gap-2 border-b border-border-color bg-bg-secondary px-3.5 py-1.5 text-[11px]"
                >
                  <div className="min-w-0 flex-1 truncate">
                    {editSaveError ? (
                      <span data-testid="file-viewer-edit-error" className="text-accent-error">
                        {t('workbench.files.editSaveFailed', { reason: editSaveError })}
                      </span>
                    ) : isEditDirty ? (
                      <span
                        data-testid="file-viewer-edit-status"
                        className="font-medium text-accent-warning"
                      >
                        {t('workbench.files.editUnsaved')}
                      </span>
                    ) : hasSavedEditInSession ? (
                      <span
                        data-testid="file-viewer-edit-status"
                        className="font-medium text-accent-info"
                      >
                        {t('workbench.files.editSaved')}
                      </span>
                    ) : (
                      <span className="text-text-muted">{t('workbench.files.editHint')}</span>
                    )}
                  </div>

                  <div className="flex shrink-0 items-center gap-1.5">
                    {isEditDirty ? (
                      <button
                        type="button"
                        data-testid="file-viewer-edit-reset"
                        disabled={savingEdit || sendingEdit}
                        onClick={() => {
                          setEditText(text ?? '');
                          setEditSaveError(null);
                        }}
                        className="inline-flex items-center gap-1 rounded-[5px] border border-border-color px-2 py-[2px] text-[11px] text-text-secondary hover:bg-bg-hover hover:text-text-primary disabled:opacity-45"
                      >
                        <RotateCcw size={11} />
                        <span>{t('workbench.files.editReset')}</span>
                      </button>
                    ) : null}

                    <button
                      type="button"
                      data-testid="file-viewer-edit-save"
                      disabled={!isEditDirty || savingEdit || sendingEdit}
                      onClick={() => void performSaveEdit()}
                      className="inline-flex items-center gap-1 rounded-[5px] border border-[var(--sel-border)] bg-[var(--sel-bg)] px-2.5 py-[2px] text-[11px] font-medium text-text-primary transition-colors hover:bg-bg-active disabled:cursor-not-allowed disabled:opacity-45"
                    >
                      {savingEdit ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
                      <span>
                        {savingEdit ? t('workbench.files.editSaving') : t('workbench.files.editSave')}
                      </span>
                    </button>

                    <button
                      type="button"
                      data-testid="file-viewer-edit-send"
                      disabled={(!isEditDirty && !hasSavedEditInSession) || savingEdit || sendingEdit}
                      onClick={() => void handleSendEditToChat()}
                      className="inline-flex items-center gap-1 rounded-[5px] border border-[var(--sel-border)] bg-[var(--sel-bg)] px-2.5 py-[2px] text-[11px] font-medium text-text-primary transition-colors hover:bg-bg-active disabled:cursor-not-allowed disabled:opacity-45"
                    >
                      {sendingEdit ? <Loader2 size={11} className="animate-spin" /> : <Send size={11} />}
                      <span>
                        {sendingEdit
                          ? t('workbench.files.editSendingToChat')
                          : t('workbench.files.editSendToChat')}
                      </span>
                    </button>
                  </div>
                </div>

                <textarea
                  data-testid="file-viewer-edit-textarea"
                  value={editText}
                  onChange={(e) => {
                    setEditText(e.target.value);
                    if (editSaveError) setEditSaveError(null);
                  }}
                  onKeyDown={(e) => {
                    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
                      e.preventDefault();
                      if (isEditDirty && !savingEdit && !sendingEdit) {
                        void performSaveEdit();
                      }
                    } else if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                      e.preventDefault();
                      if ((isEditDirty || hasSavedEditInSession) && !savingEdit && !sendingEdit) {
                        void handleSendEditToChat();
                      }
                    }
                  }}
                  spellCheck={false}
                  className="min-h-0 w-full flex-1 resize-none border-0 bg-bg-base px-4 py-3 font-mono text-[12.5px] leading-[1.65] text-text-primary outline-none"
                />
              </div>
            ) : mode === 'preview' && previewKind ? (
              <div data-testid="file-viewer-doc-preview" className="flex min-h-full flex-col">
                <div
                  data-testid="file-viewer-annotate-bar"
                  className="sticky top-0 z-[2] flex items-center justify-between gap-2 border-b border-border-color bg-bg-secondary px-3.5 py-1.5 text-[11px] text-text-muted"
                >
                  <span>
                    {t(
                      previewKind === 'markdown'
                        ? 'workbench.files.previewAnnotateHint'
                        : 'workbench.files.htmlPreviewHint'
                    )}
                  </span>
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

                {draftRange ? (
                  <div
                    data-testid="file-viewer-inline-editor"
                    className="sticky top-[34px] z-[3] mx-4 my-2.5 rounded-[8px] border border-border-strong bg-bg-elevated p-2.5 font-sans shadow-lg"
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
                    <div className="mb-2 max-h-[54px] overflow-hidden truncate rounded-[5px] border border-border-color bg-bg-secondary px-2 py-1 font-mono text-[11px] text-text-muted">
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

                {previewKind === 'markdown' ? (
                  <div
                    data-testid="file-viewer-md-preview"
                    onMouseUp={handlePreviewMouseUp}
                    className="mx-auto w-full max-w-[820px] flex-1 px-6 py-5 text-[13.5px] leading-[1.7] text-text-primary"
                  >
                    <MarkdownContent content={text} />
                  </div>
                ) : (
                  <iframe
                    ref={htmlIframeRef}
                    data-testid="file-viewer-html-preview"
                    title={baseOf(file.path)}
                    srcDoc={text}
                    sandbox="allow-scripts allow-same-origin"
                    onLoad={() => setIframeLoadTick((v) => v + 1)}
                    onMouseUp={handleHtmlPreviewMouseUp}
                    className="min-h-[480px] w-full flex-1 border-0 bg-white"
                  />
                )}
              </div>
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
                                className="my-1.5 ml-[52px] mr-4 flex items-start gap-2 rounded-[7px] border border-border-strong bg-bg-secondary px-2.5 py-1.5 font-sans text-[12px] text-text-primary"
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
                              <div className="mb-2 max-h-[54px] overflow-hidden truncate rounded-[5px] border border-border-color bg-bg-secondary px-2 py-1 font-mono text-[11px] text-text-muted">
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
          {mode !== 'changes' && mode !== 'edit' && annotationsOpen ? (
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
                        <div className="mb-1.5 truncate rounded-[4px] border border-border-color bg-bg-secondary px-1.5 py-1 font-mono text-[10.5px] text-text-muted">
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

        {/* 划词后浮出的轻量选择按钮：不抢焦点、不清选区（方便直接 ⌘C 复制），点「批注」才展开输入框 */}
        {pendingSelection ? (
          <div
            ref={selectionToolbarRef}
            data-testid="file-viewer-selection-toolbar"
            style={{ left: pendingSelection.left, top: pendingSelection.top }}
            className="fixed z-[90] -translate-x-1/2 -translate-y-full"
          >
            <button
              type="button"
              data-testid="file-viewer-selection-annotate"
              title={t('workbench.files.selectionAnnotateTitle')}
              aria-label={t('workbench.files.selectionAnnotate', {
                range:
                  pendingSelection.lineStart === pendingSelection.lineEnd
                    ? `L${pendingSelection.lineStart}`
                    : `L${pendingSelection.lineStart}–L${pendingSelection.lineEnd}`,
              })}
              onMouseDown={(e) => e.preventDefault()}
              onClick={confirmPendingSelection}
              className="inline-flex h-8 items-center gap-1.5 rounded-[8px] bg-accent-primary px-2.5 text-[12px] font-medium text-[var(--text-on-accent)] shadow-lg transition-[filter] hover:brightness-110"
            >
              <MessageSquarePlus size={14} strokeWidth={1.9} />
              <span>
                {t('workbench.files.selectionAnnotate', {
                  range:
                    pendingSelection.lineStart === pendingSelection.lineEnd
                      ? `L${pendingSelection.lineStart}`
                      : `L${pendingSelection.lineStart}–L${pendingSelection.lineEnd}`,
                })}
              </span>
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
