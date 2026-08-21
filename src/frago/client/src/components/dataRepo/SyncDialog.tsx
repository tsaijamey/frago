/**
 * SyncDialog
 *
 * Stands between "同步到仓库" and an agent that will commit and push the
 * user's entire working directory. Two things have to happen here before that
 * is a reasonable thing to let a button do:
 *
 * 1. Say what does *not* get backed up. Otherwise "同步到仓库" reads as a
 *    promise of a complete backup, and the day someone goes looking for a
 *    browser profile or a media file that was never there is the day they find
 *    out otherwise.
 * 2. Let the user narrow it. Backing up everything is the common case and the
 *    default, but "只把今天的配方传上去" is a legitimate thing to want, and the
 *    honest way to accept it is in their own words — the agent reads them.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { createPortal } from 'react-dom';
import {
  X,
  UploadCloud,
  Loader2,
  AlertCircle,
  ChevronDown,
  ChevronRight,
  FileCode2,
} from 'lucide-react';
import * as api from '@/api';
import type { DataRepoPolicy, DataRepoStatus, SyncTask } from '@/types/api';

type Mode = 'all' | 'selective';

interface SyncDialogProps {
  isOpen: boolean;
  onClose: () => void;
  status: DataRepoStatus | null;
  /** Called once the agent is running, so the page can switch to following it. */
  onStarted: (task: SyncTask | null) => void;
}

export default function SyncDialog({ isOpen, onClose, status, onStarted }: SyncDialogProps) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<Mode>('all');
  const [instruction, setInstruction] = useState('');
  const [policy, setPolicy] = useState<DataRepoPolicy | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPrompt, setShowPrompt] = useState(false);
  const [prompt, setPrompt] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !starting) onClose();
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen, onClose, starting]);

  useEffect(() => {
    if (!isOpen || policy) return;
    api
      .getDataRepoPolicy()
      .then(setPolicy)
      .catch((err) => console.error('Failed to load backup policy:', err));
  }, [isOpen, policy]);

  // The brief is fetched only when someone asks to see it. Nobody should have
  // to read it, but anyone about to hand over their working directory is
  // entitled to.
  const togglePrompt = useCallback(async () => {
    const next = !showPrompt;
    setShowPrompt(next);
    if (next) {
      try {
        const result = await api.getDataRepoSyncPrompt(
          mode,
          mode === 'selective' ? instruction : undefined
        );
        setPrompt(result.prompt);
      } catch (err) {
        console.error('Failed to load sync prompt:', err);
      }
    }
  }, [showPrompt, mode, instruction]);

  const handleStart = useCallback(async () => {
    setStarting(true);
    setError(null);
    try {
      const result = await api.startDataRepoSync(
        mode,
        mode === 'selective' ? instruction.trim() : undefined
      );
      if (result.status === 'ok') {
        onStarted(result.task ?? null);
        onClose();
      } else {
        setError(result.error || t('dataRepo.startFailed'));
      }
    } catch (err) {
      console.error('Failed to start sync:', err);
      setError(String(err));
    } finally {
      setStarting(false);
    }
  }, [mode, instruction, onStarted, onClose, t]);

  if (!isOpen) return null;

  const deletions = status?.counts?.deleted ?? 0;
  // A handful of deletions is routine. Thousands is a cleanup script or a
  // half-finished migration, and committing it would take the repository's copy
  // with it — so it gets said out loud before anyone presses the button.
  const massDeletion = deletions >= 200;
  const canStart = !starting && (mode === 'all' || instruction.trim().length > 0);

  return createPortal(
    <div
      className="fixed inset-0 z-[1100] flex items-start justify-center overflow-y-auto bg-black/50 p-4 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget && !starting) onClose();
      }}
    >
      <div className="my-8 w-full max-w-2xl rounded-lg border border-[var(--border-color)] bg-[var(--bg-base)] shadow-xl">
        <div className="flex items-center justify-between border-b border-[var(--border-color)] p-4">
          <h3 className="flex items-center gap-2 text-lg font-semibold text-[var(--text-primary)]">
            <UploadCloud size={20} className="text-[var(--accent-primary)]" />
            {t('dataRepo.dialogTitle')}
          </h3>
          <button
            type="button"
            onClick={onClose}
            disabled={starting}
            className="text-[var(--text-muted)] transition-colors hover:text-[var(--text-primary)] disabled:opacity-40"
            aria-label={t('dataRepo.close')}
          >
            <X size={20} />
          </button>
        </div>

        <div className="space-y-5 p-5">
          {/* Mode picker */}
          <div className="grid grid-cols-2 gap-2">
            {(['all', 'selective'] as Mode[]).map((option) => {
              const active = mode === option;
              return (
                <button
                  key={option}
                  type="button"
                  onClick={() => setMode(option)}
                  className={
                    active
                      ? 'rounded-lg border-2 border-[var(--accent-primary)] bg-[var(--accent-primary-10)] p-3 text-left shadow-sm'
                      : 'rounded-lg border-2 border-transparent bg-[var(--bg-card)] p-3 text-left ring-1 ring-[var(--border-color)] hover:bg-[var(--bg-tertiary)]'
                  }
                >
                  <p className="text-sm font-medium text-[var(--text-primary)]">
                    {option === 'all' ? t('dataRepo.modeAll') : t('dataRepo.modeSelective')}
                  </p>
                  <p className="mt-1 text-xs text-[var(--text-secondary)]">
                    {option === 'all'
                      ? t('dataRepo.modeAllHint', { count: (status?.pending_total ?? 0).toLocaleString() })
                      : t('dataRepo.modeSelectiveHint')}
                  </p>
                </button>
              );
            })}
          </div>

          {mode === 'selective' && (
            <div>
              <label
                htmlFor="sync-instruction"
                className="mb-1.5 block text-sm font-medium text-[var(--text-primary)]"
              >
                {t('dataRepo.instructionLabel')}
              </label>
              <textarea
                id="sync-instruction"
                rows={3}
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder={t('dataRepo.instructionPlaceholder')}
                className="w-full rounded-md border border-[var(--border-color)] bg-[var(--bg-card)] p-2.5 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent-primary)]"
              />
              <p className="mt-1 text-xs text-[var(--text-muted)]">
                {t('dataRepo.instructionHint')}
              </p>
            </div>
          )}

          {massDeletion && (
            <div className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm">
              <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-500" />
              <div className="min-w-0">
                <p className="font-medium text-[var(--text-primary)]">
                  {t('dataRepo.massDeletionTitle', { count: deletions.toLocaleString() })}
                </p>
                <p className="mt-1 text-[var(--text-secondary)]">
                  {t('dataRepo.massDeletionBody')}
                </p>
              </div>
            </div>
          )}

          {/* What does and does not go up */}
          {policy && (
            <div className="space-y-4">
              <section>
                <h4 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">
                  {t('dataRepo.includedTitle')}
                </h4>
                <ul className="space-y-1">
                  {policy.included.map((area) => (
                    <li key={area.path} className="flex gap-2 text-xs">
                      <code className="shrink-0 font-mono text-[var(--accent-primary)]">
                        {area.path}
                      </code>
                      <span className="text-[var(--text-secondary)]">{area.note}</span>
                    </li>
                  ))}
                </ul>
              </section>

              <section>
                <h4 className="mb-1 text-sm font-semibold text-[var(--text-primary)]">
                  {t('dataRepo.excludedTitle')}
                </h4>
                <p className="mb-2 text-xs text-[var(--text-secondary)]">
                  {t('dataRepo.excludedIntro')}
                </p>
                <ul className="space-y-2">
                  {policy.excluded.map((category) => (
                    <li
                      key={category.key}
                      className="rounded-md border border-[var(--border-color)] bg-[var(--bg-card)] p-2.5"
                    >
                      <p className="text-xs font-medium text-[var(--text-primary)]">
                        {category.title}
                      </p>
                      <p className="mt-0.5 font-mono text-[11px] text-[var(--text-muted)]">
                        {category.examples.join('  ')}
                      </p>
                      <p className="mt-1 text-xs text-[var(--text-secondary)]">{category.why}</p>
                    </li>
                  ))}
                </ul>
              </section>
            </div>
          )}

          {/* The brief, for anyone who wants to read it first */}
          <div>
            <button
              type="button"
              onClick={togglePrompt}
              className="inline-flex items-center gap-1 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            >
              {showPrompt ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <FileCode2 size={14} />
              {t('dataRepo.viewPrompt')}
            </button>
            {showPrompt && (
              <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-md bg-[var(--bg-tertiary)] p-3 text-[11px] leading-relaxed text-[var(--text-secondary)]">
                {prompt ?? t('dataRepo.loadingPrompt')}
              </pre>
            )}
          </div>

          {error && (
            <div className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm">
              <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-500" />
              <p className="min-w-0 break-words text-[var(--text-secondary)]">{error}</p>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-[var(--border-color)] p-4">
          <p className="text-xs text-[var(--text-muted)]">{t('dataRepo.agentNote')}</p>
          <div className="flex shrink-0 gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={starting}
              className="rounded-md border border-[var(--border-color)] px-3 py-1.5 text-sm text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] disabled:opacity-40"
            >
              {t('dataRepo.cancel')}
            </button>
            <button
              type="button"
              onClick={handleStart}
              disabled={!canStart}
              className="inline-flex items-center gap-1.5 rounded-md bg-[var(--accent-primary)] px-4 py-1.5 text-sm font-medium text-[var(--text-on-accent)] hover:opacity-90 disabled:opacity-50"
            >
              {starting ? <Loader2 size={14} className="animate-spin" /> : <UploadCloud size={14} />}
              {starting ? t('dataRepo.starting') : t('dataRepo.confirmSync')}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
