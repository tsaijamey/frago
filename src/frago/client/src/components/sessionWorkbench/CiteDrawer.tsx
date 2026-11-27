import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Copy, FileText, FolderOpen, Maximize2, X } from 'lucide-react';
import { getSessionFileContent } from '@/api';
import { parseLineAnchorRange, type CiteDefinition } from '@/components/ui/citations';
import type { SessionFileContent } from '@/types/api';
import { baseOf, withTilde } from './filePaths';

export type CiteDrawerTarget =
  | { mode: 'cite'; def: CiteDefinition }
  | { mode: 'file'; path: string; line?: string };

export interface CiteDrawerProps {
  sessionId: string;
  target: CiteDrawerTarget;
  onClose: () => void;
  onReveal: (path: string) => void;
  onOpenFullViewer: (path: string, line?: string) => void;
}

function mapFileError(
  err: unknown,
  reason: SessionFileContent['reason'] | undefined,
  t: (key: string, opts?: Record<string, unknown>) => string
): string {
  if (reason === 'too-large') return t('workbench.citations.tooLarge');
  if (reason === 'not-text') return t('workbench.citations.notText');
  if (reason === 'unreadable') return t('workbench.citations.unreadable');
  const msg = err instanceof Error ? err.message : String(err ?? '');
  if (/403|refused|forbidden|outside/i.test(msg)) return t('workbench.citations.unsafeBlocked');
  if (/404|not found|missing/i.test(msg)) return t('workbench.citations.missingFile');
  return msg || t('workbench.citations.unreadable');
}

export default function CiteDrawer({
  sessionId,
  target,
  onClose,
  onReveal,
  onOpenFullViewer,
}: CiteDrawerProps) {
  const { t } = useTranslation();
  const bodyRef = useRef<HTMLDivElement>(null);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const filePath = target.mode === 'cite' ? (target.def.filePath ?? '') : target.path;
  const lineAnchor = target.mode === 'cite' ? target.def.line : target.line;
  const lineRange = useMemo(() => parseLineAnchorRange(lineAnchor), [lineAnchor]);
  const hlStart =
    target.mode === 'cite'
      ? (target.def.hlStart ?? lineRange?.startLine)
      : lineRange?.startLine;
  const hlEnd =
    target.mode === 'cite'
      ? (target.def.hlEnd ?? lineRange?.endLine ?? hlStart)
      : lineRange?.endLine;

  const [fileContent, setFileContent] = useState<SessionFileContent | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    return () => {
      if (copyTimerRef.current !== null) clearTimeout(copyTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (!sessionId || !filePath) {
      setFileContent(null);
      setErrorMsg(t('workbench.citations.missingFile'));
      return;
    }
    let alive = true;
    setLoading(true);
    setErrorMsg(null);
    setFileContent(null);

    getSessionFileContent(sessionId, filePath, 'cited')
      .then((res) => {
        if (!alive) return;
        setFileContent(res);
        if (res.text === null || res.reason) {
          setErrorMsg(mapFileError(null, res.reason, t));
        }
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setErrorMsg(mapFileError(err, undefined, t));
        setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [sessionId, filePath, t]);

  const lines = useMemo(
    () => (typeof fileContent?.text === 'string' ? fileContent.text.split(/\r?\n/) : []),
    [fileContent?.text]
  );

  useEffect(() => {
    if (!fileContent?.text || !hlStart) return;
    const container = bodyRef.current;
    if (!container) return;
    const targetRow = container.querySelector<HTMLElement>(`[data-line="${hlStart}"]`);
    if (targetRow && typeof targetRow.scrollIntoView === 'function') {
      targetRow.scrollIntoView({ block: 'center' });
    }
  }, [fileContent?.text, hlStart, target.mode]);

  const displayName =
    target.mode === 'cite' ? target.def.title || baseOf(filePath) : baseOf(filePath) || filePath;
  const resolvedPath = fileContent?.path || filePath;
  const rangeLabel =
    hlStart !== undefined
      ? hlEnd && hlEnd !== hlStart
        ? `L${hlStart}–L${hlEnd}`
        : `L${hlStart}`
      : '';

  const handleCopyPath = () => {
    if (!resolvedPath || !navigator.clipboard?.writeText) return;
    void navigator.clipboard.writeText(resolvedPath);
    setCopied(true);
    if (copyTimerRef.current !== null) clearTimeout(copyTimerRef.current);
    copyTimerRef.current = setTimeout(() => {
      setCopied(false);
      copyTimerRef.current = null;
    }, 1800);
  };

  return (
    <aside
      className="cite-drawer open"
      data-testid="cite-preview-drawer"
      data-drawer-mode={target.mode}
      aria-label={t('workbench.citations.drawerAria')}
    >
      <div className="cite-drawer-head">
        <div className="cite-drawer-file">
          <FileText size={14} className="shrink-0 text-text-muted" />
          <div className="min-w-0 flex-1">
            <div className="cite-drawer-name" title={resolvedPath}>
              {displayName}
            </div>
            <div className="cite-drawer-sub" title={resolvedPath}>
              {withTilde(resolvedPath)}
              {rangeLabel ? `:${rangeLabel}` : ''}
            </div>
          </div>
        </div>
        <div className="cite-drawer-actions">
          <button
            type="button"
            className="cite-drawer-btn"
            data-testid="cite-drawer-copy"
            title={t('workbench.citations.copyPath')}
            onClick={handleCopyPath}
          >
            {copied ? <Check size={12} /> : <Copy size={12} />}
          </button>
          <button
            type="button"
            className="cite-drawer-btn"
            data-testid="cite-drawer-reveal"
            title={t('workbench.citations.revealFolder')}
            onClick={() => onReveal(resolvedPath)}
          >
            <FolderOpen size={12} />
          </button>
          <button
            type="button"
            className="cite-drawer-btn"
            data-testid="cite-drawer-expand"
            title={t('workbench.citations.openModal')}
            onClick={() => onOpenFullViewer(resolvedPath, lineAnchor)}
          >
            <Maximize2 size={12} />
          </button>
          <button
            type="button"
            className="cite-drawer-btn"
            data-testid="close-cite-drawer-btn"
            title={t('workbench.citations.closeDrawer')}
            aria-label={t('workbench.citations.closeDrawer')}
            onClick={onClose}
          >
            <X size={13} />
          </button>
        </div>
      </div>

      {target.mode === 'file' ? (
        <div
          className="cite-drawer-banner file-mode"
          data-testid="cite-drawer-banner"
        >
          <span>{t('workbench.citations.fileBanner')}</span>
          <span className="font-semibold">{t('workbench.citations.fullPreview')}</span>
        </div>
      ) : (
        <div
          className="cite-drawer-banner"
          data-testid="cite-drawer-banner"
        >
          <span>
            {rangeLabel
              ? t('workbench.citations.citeBanner', {
                  label: target.def.label,
                  range: rangeLabel,
                })
              : t('workbench.citations.citeBannerNoLine', {
                  label: target.def.label,
                })}
          </span>
          <span className="font-mono text-[10px] opacity-80">[{target.def.label}]</span>
        </div>
      )}

      <div className="cite-drawer-body" ref={bodyRef}>
        {loading ? (
          <div className="px-4 py-6 text-[12px] text-text-muted">
            {t('workbench.citations.loading')}
          </div>
        ) : errorMsg ? (
          <div
            className="px-4 py-6 text-[12px] leading-[1.6] text-text-muted"
            data-testid="cite-drawer-error"
          >
            {errorMsg}
          </div>
        ) : lines.length > 0 ? (
          <div className="cite-code">
            {lines.map((lineText, idx) => {
              const lineNo = idx + 1;
              const isHighlighted =
                target.mode === 'cite' &&
                hlStart !== undefined &&
                lineNo >= hlStart &&
                lineNo <= (hlEnd ?? hlStart);
              return (
                <div
                  key={lineNo}
                  data-line={lineNo}
                  data-highlighted={isHighlighted ? 'true' : undefined}
                  className={`cite-code-line${isHighlighted ? ' hl' : ''}`}
                >
                  <span className="cite-ln">{lineNo}</span>
                  <span className="cite-lt">{lineText || ' '}</span>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="px-4 py-6 text-[12px] text-text-muted">
            {t('workbench.citations.emptyFile')}
          </div>
        )}
      </div>
    </aside>
  );
}
