/**
 * FileViewer — 会话文件清单上点开一份文件的那个浮窗。
 *
 * 它是**只读的一眼**：人正在读会话记录，想看看这场会话到底把那个文件写成什么样，看完就关。
 * 所以里面没有编辑、没有保存，只有内容、翻上一个／下一个、复制路径、去文件夹里打开。
 *
 * 三件事写在这里：
 *
 * 1. **内容现取。** 打开哪一份就问哪一份（`GET /api/workbench/sessions/{sid}/file`），不
 *    预先取回来摆在内存里——会话改过的文件可能很多、可能很大，而人一次只看一份。
 * 2. **取不到内容照实说。** 过大、读不成文本、文件已经不在，各是各的话，NEVER 拿半份当
 *    整份摆出来。能摆的那一份一个字不少。
 * 3. **颜色只是补充。** 染色取不到（离线、语言认不出）就摆纯文本，内容照样完整可读。
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
  X,
} from 'lucide-react';
import { getSessionFileContent, getSessionFileDiff } from '@/api';
import type { SessionFileContent, SessionFileDiff, SessionFileRow } from '@/types/api';
import FileDiff from './FileDiff';
import { baseOf, dirOf, langOf, withTilde } from './filePaths';
import { FILE_BADGE } from './fileBadge';
import {
  MAX_AUTODETECT_CHARS,
  MAX_HIGHLIGHT_CHARS,
  loadHighlighter,
} from '@/utils/codeHighlight';

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
function useHighlightedHtml(text: string | null, lang: string): string | null {
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
        // 认得出语言就按它染；认不出而且这一份不长，交给引擎自己猜。
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

export default function FileViewer({
  sessionId,
  files,
  index,
  onClose,
  onStep,
  onReveal,
}: FileViewerProps) {
  const { t } = useTranslation();
  const file = files[index];
  const [content, setContent] = useState<SessionFileContent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  /**
   * 看内容，还是看改动。默认看内容——人点开一份文件，多数时候是想看它现在长什么样。
   *
   * 改动那一档是**点了才取**：它要慢一步（服务端还得去 git 里取上一版、再算对齐），而多数
   * 人不会看；不像那一档的数字，那是摆在排上必须当场在的。
   */
  const [mode, setMode] = useState<'file' | 'changes'>('file');
  const [diff, setDiff] = useState<SessionFileDiff | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState<string | null>(null);

  const path = file?.path ?? '';
  const lang = useMemo(() => langOf(path), [path]);

  // 现取。换了文件就是另一次取，上一次回来的那份不算数。
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setContent(null);
    setError(null);
    setLoading(true);
    // 换了文件就回到「看内容」那一档：人翻到下一份时想看的是它长什么样，不是它的改动；
    // 停在改动那一档会让人以为「这份也有改动」。
    setMode('file');
    setDiff(null);
    setDiffError(null);
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

  // 改动那一档：切过去才取，同一个文件切回来不再取（已经拿到了）。
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

  // Esc 关，← → 翻。挂在 document 上：焦点多半在浮窗里的某个按钮上，挂在窗口元素上会漏掉
  // 点过按钮之后的那几次按键。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      } else if (e.key === 'ArrowLeft') {
        onStep(-1);
      } else if (e.key === 'ArrowRight') {
        onStep(1);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose, onStep]);

  const copyPath = useCallback(() => {
    void navigator.clipboard
      ?.writeText(path)
      .then(() => {
        setCopied(true);
        if (copyTimer.current) clearTimeout(copyTimer.current);
        copyTimer.current = setTimeout(() => setCopied(false), 1_500);
      })
      .catch(() => {
        /* 剪贴板不给用（非安全上下文之类）就算了，不打断人 */
      });
  }, [path]);

  const text = content?.text ?? null;
  const html = useHighlightedHtml(text, lang);

  if (!file) return null;

  const iconBtn =
    'inline-flex h-[24px] w-[24px] shrink-0 items-center justify-center rounded-[6px] text-text-muted hover:bg-bg-hover hover:text-text-primary';

  /** 摆不了内容时的那句话：过大、不是文本、取不回来各说各的。 */
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
      className="fixed inset-0 z-[80] flex items-center justify-center p-5"
      role="dialog"
      aria-modal="true"
      aria-label={baseOf(file.path)}
    >
      {/* 点窗外关掉。挡在后面那一层同时把底下挡住：浮窗开着时底下还能点，就成了两个界面
          在抢同一只手。 */}
      {/* 遮罩走 `--bg-overlay` 那条令牌。注意 `bg-bg-overlay` 这个类**不存在**
          （tailwind.config 里没有那一档，写着它只会静静地落空成透明），所以写成
          `bg-[var(--bg-overlay)]`——与搜索浮窗那一处同一个写法。 */}
      <div
        data-testid="file-viewer-backdrop"
        className="absolute inset-0 bg-[var(--bg-overlay)]"
        onClick={onClose}
      />

      {/* 改动那一档要平分两列，窗口跟着放宽（照原型：900 → 1120）。 */}
      <div
        className={`relative flex h-[min(76vh,680px)] flex-col overflow-hidden rounded-[12px] border border-border-strong bg-bg-primary shadow-2xl ${
          mode === 'changes' ? 'w-[min(1120px,100%)]' : 'w-[min(900px,100%)]'
        }`}
      >
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border-color px-3">
          <FileText size={14} className="shrink-0 text-text-muted" />
          <span className="min-w-0 flex-1 truncate font-mono text-[12px]">
            <span className="text-text-dim" title={dirOf(file.path)}>
              {withTilde(dirOf(file.path))}
            </span>
            <b className="ml-1 font-medium text-text-primary">{baseOf(file.path)}</b>
          </span>
          {/* 新建／改／删，与清单里那枚字母同一张表，这里写全称。 */}
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

          {/* 看内容 / 看改动。只在读得出内容时出现：读不出来的文件（太大、二进制）连内容都
              没有，也就没有什么可对照的。 */}
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

        {/* 改动那一档让出左边那 186px：两列并排本来就比一列窄，再把文件列摆在这儿，两边
            都读不成了。翻文件仍走顶上的 ‹ ›（与原型同一个做法）。 */}
        <div
          className={`grid min-h-0 flex-1 tablet:grid-cols-1 ${
            mode === 'changes' ? 'grid-cols-1' : 'grid-cols-[186px_minmax(0,1fr)]'
          }`}
        >
          {/* 左边那一列是同一场会话改过的文件，翻起来不用退回清单再点。 */}
          <div
            className={`min-h-0 overflow-auto border-r border-border-color bg-bg-secondary px-[5px] py-1.5 tablet:hidden ${
              mode === 'changes' ? 'hidden' : ''
            }`}
          >
            {files.map((row, i) => (
              <button
                key={row.path}
                type="button"
                title={row.path}
                onClick={() => onStep(i - index)}
                className={`block w-full truncate rounded-[5px] px-2 py-1 text-left font-mono text-[11.5px] ${
                  i === index
                    ? 'bg-bg-active font-medium text-text-primary'
                    : 'text-text-muted hover:bg-bg-hover hover:text-text-secondary'
                }`}
              >
                {baseOf(row.path)}
              </button>
            ))}
          </div>

          <div className="min-h-0 min-w-0 overflow-auto bg-bg-base">
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
              // 染色没回来（还在路上、太大、引擎取不到）就先摆纯文本：内容一个字不少，
              // 颜色到了再换上去。
              <pre className="p-4 font-mono text-[12px] leading-[1.6] text-text-secondary">
                {html !== null ? (
                  <code
                    className="hljs"
                    // 引擎的输出是转义过的 HTML，见 `useHighlightedHtml`。
                    dangerouslySetInnerHTML={{ __html: html }}
                  />
                ) : (
                  <code className="hljs">{text}</code>
                )}
              </pre>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
