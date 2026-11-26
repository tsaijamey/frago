/**
 * StackPopover — 方案 4A 滚动条暂存轨向左浮层（3 态合一：单条 / 相近集群 / 顶部汇总）。
 *
 * - 支持点击空白处或按 `Esc` 关闭，且按 `Esc` 时把键盘焦点准确归还给触发元素；
 * - 支持单条内联编辑想法（Enter/失焦保存）、定位原文、复制原文、删除（配合外层 4 秒撤销条）、
 *   以及「填入输入框 / 从草稿移除」双向切换；
 * - 集群态当未填入草稿条目为 2–5 条时提供「全部填入 (N)」；
 * - 汇总态集中呈现活跃未加载条目与可折叠「已处理 (N)」列表。
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ArrowLeft,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Crosshair,
  Loader2,
  Trash2,
  X,
} from 'lucide-react';
import type { WorkbenchMark } from '@/types/api';
import type { LocateState } from './StackPanel';
import { cleanQuoteText, stackLabelText, stackStatusOf } from '@/utils/stackRailLayout';

export interface StackAnchorRect {
  top: number;
  left: number;
  right: number;
  bottom: number;
}

export type StackPopoverBackTarget =
  | {
      mode: 'cluster';
      clusterId?: string;
      markIds: string[];
    }
  | {
      mode: 'summary';
    };

export type StackPopoverState =
  | {
      mode: 'item';
      markId: string;
      anchorRect: StackAnchorRect;
      triggerEl: HTMLElement | null;
      placement?: 'left' | 'above-left';
      backTo?: StackPopoverBackTarget;
    }
  | {
      mode: 'cluster';
      clusterId?: string;
      markIds: string[];
      anchorRect: StackAnchorRect;
      triggerEl: HTMLElement | null;
      placement?: 'left' | 'above-left';
    }
  | {
      mode: 'summary';
      anchorRect: StackAnchorRect;
      triggerEl: HTMLElement | null;
      placement?: 'left' | 'above-left';
    };

export interface StackPopoverProps {
  state: StackPopoverState | null;
  marks: WorkbenchMark[];
  inDraftMarkIds: ReadonlySet<string>;
  unloadedMarkIds?: ReadonlySet<string>;
  locateState?: Record<string, LocateState>;
  onClose: (opts?: { restoreFocus?: boolean }) => void;
  onSwitchToItem?: (markId: string, backTo?: StackPopoverBackTarget) => void;
  onBack?: () => void;
  onFill: (mark: WorkbenchMark) => void;
  onRemoveFromDraft: (mark: WorkbenchMark) => void;
  onLocate: (mark: WorkbenchMark) => void;
  onDelete: (mark: WorkbenchMark) => void;
  onNoteChange: (id: string, note: string) => void;
  onPointerEnter?: () => void;
  onPointerLeave?: () => void;
}

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

function formatShortTime(ts: number): string {
  if (!Number.isFinite(ts) || ts <= 0) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

export default function StackPopover({
  state,
  marks,
  inDraftMarkIds,
  unloadedMarkIds,
  locateState,
  onClose,
  onSwitchToItem,
  onBack,
  onFill,
  onRemoveFromDraft,
  onLocate,
  onDelete,
  onNoteChange,
  onPointerEnter,
  onPointerLeave,
}: StackPopoverProps) {
  const { t } = useTranslation();
  const popRef = useRef<HTMLDivElement>(null);
  const noteDisplayRef = useRef<HTMLButtonElement>(null);
  const noteTextareaRef = useRef<HTMLTextAreaElement>(null);
  const skipBlurCommitRef = useRef(false);
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null);
  const [usedExpanded, setUsedExpanded] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState('');
  const [editingNoteId, setEditingNoteId] = useState<string | null>(null);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stackMarks = useMemo(() => marks.filter((m) => m.kind === 'stack'), [marks]);
  const markById = useMemo(() => new Map(stackMarks.map((m) => [m.id, m])), [stackMarks]);

  const singleMark =
    state?.mode === 'item' ? (markById.get(state.markId) ?? null) : null;

  const editingNoteIdRef = useRef<string | null>(null);
  editingNoteIdRef.current = editingNoteId;
  const singleMarkRef = useRef<WorkbenchMark | null>(null);
  singleMarkRef.current = singleMark;

  useEffect(() => {
    skipBlurCommitRef.current = false;
    setEditingNoteId(null);
    setNoteDraft(singleMark?.note ?? '');
  }, [state?.mode, singleMark?.id]);

  useEffect(() => {
    if (editingNoteId === null) {
      setNoteDraft(singleMark?.note ?? '');
    }
  }, [singleMark?.note, editingNoteId]);

  useEffect(() => {
    if (editingNoteId && singleMark && editingNoteId === singleMark.id) {
      const ta = noteTextareaRef.current;
      if (ta) {
        ta.focus();
        const len = ta.value.length;
        ta.setSelectionRange(len, len);
      }
    }
  }, [editingNoteId, singleMark?.id]);

  useEffect(
    () => () => {
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    },
    []
  );

  // 定位浮层到触发点左侧（或非轨兜底按钮的左上方）
  useLayoutEffect(() => {
    if (!state) {
      setCoords(null);
      return;
    }
    const el = popRef.current;
    const vw = typeof window !== 'undefined' ? window.innerWidth : 1280;
    const vh = typeof window !== 'undefined' ? window.innerHeight : 800;
    const popW = el?.offsetWidth || 340;
    const popH = el?.offsetHeight || 240;
    const rect = state.anchorRect;

    if (state.placement === 'above-left') {
      const left = clamp(rect.right - popW, 12, Math.max(12, vw - popW - 12));
      const top = clamp(rect.top - popH - 8, 12, Math.max(12, vh - popH - 12));
      setCoords({ top, left });
    } else {
      const left = Math.max(12, rect.left - popW - 8);
      const top = clamp(rect.top - 12, 12, Math.max(12, vh - popH - 12));
      setCoords({ top, left });
    }
  }, [state, stackMarks.length, usedExpanded, editingNoteId]);

  // 点击浮层外关闭 / Esc 编辑态仅取消编辑、非编辑态关闭并归还焦点至触发元素
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!state) return undefined;
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target;
      if (!(target instanceof Node)) return;
      if (popRef.current?.contains(target)) return;
      if (state.triggerEl && state.triggerEl.contains(target)) return;
      onCloseRef.current({ restoreFocus: false });
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      const activeEl = document.activeElement;
      const isEditingNote =
        editingNoteIdRef.current !== null ||
        (activeEl instanceof HTMLTextAreaElement && Boolean(popRef.current?.contains(activeEl)));
      if (isEditingNote) {
        e.preventDefault();
        e.stopPropagation();
        skipBlurCommitRef.current = true;
        setNoteDraft(singleMarkRef.current?.note ?? '');
        setEditingNoteId(null);
        requestAnimationFrame(() => {
          noteDisplayRef.current?.focus();
        });
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      onCloseRef.current({ restoreFocus: true });
    };
    document.addEventListener('pointerdown', onPointerDown, true);
    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true);
      document.removeEventListener('keydown', onKeyDown, true);
    };
  }, [state]);

  if (!state) return null;

  const commitNote = (mark: WorkbenchMark) => {
    const trimmed = noteDraft.trim();
    if (trimmed !== (mark.note ?? '').trim()) {
      onNoteChange(mark.id, trimmed);
    }
  };

  const startEditingNote = (mark: WorkbenchMark) => {
    skipBlurCommitRef.current = false;
    setNoteDraft(mark.note ?? '');
    setEditingNoteId(mark.id);
  };

  const handleCopy = async (mark: WorkbenchMark) => {
    try {
      await navigator.clipboard?.writeText(mark.text);
      setCopiedId(mark.id);
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
      copyTimerRef.current = setTimeout(() => setCopiedId(null), 1500);
    } catch {
      /* 忽略无剪贴板权限的场景 */
    }
  };

  const renderStatusPill = (mark: WorkbenchMark) => {
    const st = stackStatusOf(mark, inDraftMarkIds);
    if (st === 'draft') {
      return (
        <span className="sp-st is-draft" data-testid="stack-popover-status">
          <Check size={10} strokeWidth={2.5} aria-hidden="true" />
          {t('workbench.stack.statusDraft')}
        </span>
      );
    }
    if (st === 'used') {
      return (
        <span className="sp-st is-used" data-testid="stack-popover-status">
          {t('workbench.stack.used')}
        </span>
      );
    }
    return (
      <span className="sp-st is-pending" data-testid="stack-popover-status">
        {t('workbench.stack.statusPending')}
      </span>
    );
  };

  const renderRow = (mark: WorkbenchMark, backTarget?: StackPopoverBackTarget) => {
    const st = stackStatusOf(mark, inDraftMarkIds);
    const isUnloaded = unloadedMarkIds?.has(mark.id) ?? false;
    const isSearching = locateState?.[mark.id] === 'searching';
    const isNotFound = locateState?.[mark.id] === 'notFound';
    const title = stackLabelText(mark);
    const snippet = mark.note?.trim() ? cleanQuoteText(mark.text) : '';
    return (
      <div
        key={mark.id}
        data-testid="stack-list-row"
        data-mark-id={mark.id}
        data-status={st}
        className={`sp-row ${st === 'used' ? 'is-used' : ''}`}
      >
        <button
          type="button"
          className="sp-row-main"
          onClick={() => onSwitchToItem?.(mark.id, backTarget)}
        >
          <span className={`sp-row-dot is-${st}`} aria-hidden="true" />
          <span className="sp-row-text">
            <span className="sp-row-title">{title}</span>
            {snippet ? <span className="sp-row-sub">{snippet}</span> : null}
            {isUnloaded ? (
              <span className="sp-unloaded-tag" data-testid="stack-unloaded-badge">
                {t('workbench.stack.unloadedHint')}
              </span>
            ) : null}
            {isNotFound ? (
              <span className="sp-row-warn">{t('workbench.stack.notFound')}</span>
            ) : null}
          </span>
        </button>
        <div className="sp-row-actions">
          <button
            type="button"
            className="sp-mini-btn"
            data-testid="stack-row-locate"
            title={t('workbench.stack.locate')}
            aria-label={t('workbench.stack.locate')}
            disabled={isSearching}
            onClick={() => onLocate(mark)}
          >
            {isSearching ? <Loader2 size={11} className="animate-spin" /> : <Crosshair size={11} />}
          </button>
          {st === 'draft' ? (
            <button
              type="button"
              className="sp-mini-btn is-active"
              data-testid="stack-row-remove-draft"
              onClick={() => onRemoveFromDraft(mark)}
            >
              {t('workbench.stack.removeFromDraftShort')}
            </button>
          ) : (
            <button
              type="button"
              className="sp-mini-btn is-primary"
              data-testid="stack-row-fill"
              onClick={() => onFill(mark)}
            >
              {mark.used ? t('workbench.stack.fillAgain') : t('workbench.stack.fill')}
            </button>
          )}
          {mark.used ? (
            <button
              type="button"
              className="sp-mini-btn is-danger"
              data-testid="stack-row-delete"
              title={t('workbench.stack.delete')}
              aria-label={t('workbench.stack.delete')}
              onClick={() => onDelete(mark)}
            >
              <Trash2 size={11} />
            </button>
          ) : null}
        </div>
      </div>
    );
  };

  const renderContent = () => {
    if (state.mode === 'item') {
      const mark = singleMark;
      if (!mark) {
        return (
          <div className="sp-empty">{t('workbench.stack.itemMissing')}</div>
        );
      }
      const st = stackStatusOf(mark, inDraftMarkIds);
      const isSearching = locateState?.[mark.id] === 'searching';
      const isNotFound = locateState?.[mark.id] === 'notFound';
      const timeLabel = formatShortTime(mark.created_at);
      const isEditingNote = editingNoteId === mark.id;
      const trimmedNote = (mark.note ?? '').trim();

      return (
        <>
          <div className="sp-hd">
            {state.backTo && onBack ? (
              <button
                type="button"
                className="sp-back"
                data-testid="stack-popover-back"
                title={t('workbench.stack.back')}
                aria-label={t('workbench.stack.back')}
                onClick={onBack}
              >
                <ArrowLeft size={13} />
              </button>
            ) : null}
            {renderStatusPill(mark)}
            {timeLabel ? <span className="sp-tm">{timeLabel}</span> : null}
            <button
              type="button"
              className="sp-close"
              data-testid="stack-popover-close"
              aria-label={t('workbench.branch.dismiss')}
              onClick={() => onClose({ restoreFocus: true })}
            >
              <X size={13} />
            </button>
          </div>

          <div className="sp-body">
            <div className="sp-quote-wrap">
              <div className="sp-quote" data-testid="stack-popover-quote">
                {mark.text}
              </div>
              <button
                type="button"
                className="sp-copy-btn"
                data-testid="stack-popover-copy"
                title={t('workbench.stack.copyQuote')}
                aria-label={t('workbench.stack.copyQuote')}
                onClick={() => void handleCopy(mark)}
              >
                {copiedId === mark.id ? <Check size={11} /> : <Copy size={11} />}
                <span>
                  {copiedId === mark.id
                    ? t('workbench.stack.copied')
                    : t('workbench.stack.copy')}
                </span>
              </button>
            </div>

            {!mark.used ? (
              <div className="sp-note-wrap">
                <div className="sp-note-lbl">
                  <label htmlFor={`sp-note-${mark.id}`}>{t('workbench.stack.addNote')}</label>
                  {isEditingNote ? <span>{t('workbench.stack.noteEditHint')}</span> : null}
                </div>
                {isEditingNote ? (
                  <textarea
                    ref={noteTextareaRef}
                    id={`sp-note-${mark.id}`}
                    data-testid="stack-popover-note-input"
                    className="sp-note-ta"
                    value={noteDraft}
                    placeholder={t('workbench.stack.notePlaceholder')}
                    onChange={(e) => setNoteDraft(e.target.value)}
                    onBlur={() => {
                      if (skipBlurCommitRef.current) {
                        skipBlurCommitRef.current = false;
                        return;
                      }
                      commitNote(mark);
                      setEditingNoteId(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        commitNote(mark);
                        skipBlurCommitRef.current = true;
                        setEditingNoteId(null);
                        requestAnimationFrame(() => {
                          noteDisplayRef.current?.focus();
                        });
                      } else if (e.key === 'Escape') {
                        e.preventDefault();
                        e.stopPropagation();
                        skipBlurCommitRef.current = true;
                        setNoteDraft(mark.note ?? '');
                        setEditingNoteId(null);
                        requestAnimationFrame(() => {
                          noteDisplayRef.current?.focus();
                        });
                      }
                    }}
                  />
                ) : (
                  <button
                    ref={noteDisplayRef}
                    id={`sp-note-${mark.id}`}
                    type="button"
                    data-testid="stack-popover-note-display"
                    className={`sp-note-show ${trimmedNote ? '' : 'is-empty'}`}
                    onClick={() => startEditingNote(mark)}
                  >
                    {trimmedNote || t('workbench.stack.noteAddHint')}
                  </button>
                )}
              </div>
            ) : trimmedNote ? (
              <p className="sp-note-ro">{mark.note}</p>
            ) : null}

            {isNotFound ? (
              <p className="sp-locate-warn" data-testid="stack-popover-locate-error">
                {t('workbench.stack.notFound')}
              </p>
            ) : null}
          </div>

          <div className="sp-ft">
            <div className="sp-ft-left">
              <button
                type="button"
                className="sp-btn"
                data-testid="stack-popover-locate"
                disabled={isSearching}
                onClick={() => onLocate(mark)}
              >
                {isSearching ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <Crosshair size={12} />
                )}
                <span>
                  {isSearching ? t('workbench.stack.searching') : t('workbench.stack.locateShort')}
                </span>
              </button>
              <button
                type="button"
                className="sp-btn is-danger"
                data-testid="stack-popover-delete"
                onClick={() => {
                  onDelete(mark);
                  onClose({ restoreFocus: false });
                }}
              >
                <Trash2 size={12} />
                <span>{t('workbench.stack.delete')}</span>
              </button>
            </div>

            {st === 'draft' ? (
              <button
                type="button"
                className="sp-btn is-draft-remove"
                data-testid="stack-popover-remove-draft"
                onClick={() => onRemoveFromDraft(mark)}
              >
                {t('workbench.stack.removeFromDraft')}
              </button>
            ) : (
              <button
                type="button"
                className="sp-btn is-primary"
                data-testid="stack-popover-fill"
                onClick={() => onFill(mark)}
              >
                {mark.used ? t('workbench.stack.fillAgain') : t('workbench.stack.fillIntoBox')}
              </button>
            )}
          </div>
        </>
      );
    }

    if (state.mode === 'cluster') {
      const items = state.markIds
        .map((id) => markById.get(id))
        .filter((m): m is WorkbenchMark => Boolean(m && !m.used));
      const pendingItems = items.filter((m) => stackStatusOf(m, inDraftMarkIds) === 'pending');
      const backTarget: StackPopoverBackTarget = {
        mode: 'cluster',
        clusterId: state.clusterId,
        markIds: state.markIds,
      };

      return (
        <>
          <div className="sp-hd">
            <span className="sp-title">
              {t('workbench.stack.clusterTitle', { count: items.length })}
            </span>
            <button
              type="button"
              className="sp-close"
              data-testid="stack-popover-close"
              aria-label={t('workbench.branch.dismiss')}
              onClick={() => onClose({ restoreFocus: true })}
            >
              <X size={13} />
            </button>
          </div>
          <div className="sp-list">
            {items.length ? (
              items.map((m) => renderRow(m, backTarget))
            ) : (
              <div className="sp-empty">{t('workbench.stack.emptyShort')}</div>
            )}
          </div>
          {pendingItems.length >= 2 && pendingItems.length <= 5 ? (
            <div className="sp-ft sp-ft-end">
              <button
                type="button"
                className="sp-btn is-primary"
                data-testid="stack-popover-fill-all"
                onClick={() => {
                  for (const item of pendingItems) onFill(item);
                  onClose({ restoreFocus: false });
                }}
              >
                {t('workbench.stack.fillAll', { count: pendingItems.length })}
              </button>
            </div>
          ) : null}
        </>
      );
    }

    // mode === 'summary'
    const active = stackMarks.filter((m) => !m.used);
    const used = stackMarks.filter((m) => m.used);
    const unloadedActive = active.filter((m) => unloadedMarkIds?.has(m.id));
    const loadedActive = active.filter((m) => !unloadedMarkIds?.has(m.id));
    const orderedActive = [...unloadedActive, ...loadedActive];
    const backTarget: StackPopoverBackTarget = { mode: 'summary' };

    return (
      <>
        <div className="sp-hd">
          <span className="sp-title">
            {t('workbench.stack.summaryTitle', { count: active.length })}
          </span>
          <button
            type="button"
            className="sp-close"
            data-testid="stack-popover-close"
            aria-label={t('workbench.branch.dismiss')}
            onClick={() => onClose({ restoreFocus: true })}
          >
            <X size={13} />
          </button>
        </div>

        <div className="sp-list">
          {orderedActive.length > 0 ? (
            orderedActive.map((m) => renderRow(m, backTarget))
          ) : (
            <div className="sp-empty">{t('workbench.stack.emptyShort')}</div>
          )}

          {used.length > 0 ? (
            <div className="sp-used-sec">
              <button
                type="button"
                className="sp-used-toggle"
                data-testid="stack-used-toggle"
                aria-expanded={usedExpanded}
                onClick={() => setUsedExpanded((v) => !v)}
              >
                {usedExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                <span>{t('workbench.stack.usedSection', { count: used.length })}</span>
              </button>
              {usedExpanded ? (
                <div className="sp-used-list">
                  {used.map((m) => renderRow(m, backTarget))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </>
    );
  };

  return (
    <div
      ref={popRef}
      role="dialog"
      aria-modal="false"
      aria-label={t('workbench.stack.title')}
      data-testid="stack-popover"
      data-mode={state.mode}
      className="stack-popover"
      style={{
        top: coords ? `${coords.top}px` : `${state.anchorRect.top}px`,
        left: coords ? `${coords.left}px` : `${Math.max(12, state.anchorRect.left - 348)}px`,
      }}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
    >
      {renderContent()}
    </div>
  );
}
