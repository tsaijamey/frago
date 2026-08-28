/**
 * DataRepoPage — 数据仓库
 *
 * Answers one question: is my work backed up, and if not, how much is waiting?
 * Then offers the one action that changes the answer.
 *
 * Two things shape the design more than anything else:
 *
 * - **Scale.** A working directory in daily use accumulates tens of thousands
 *   of pending files. A flat list of them is not information, it is a wall.
 *   The rollup by area is the primary view — "sessions/ 23,700" is what tells
 *   someone what is going on; the file list is a sample underneath it.
 * - **The GitHub prerequisite.** Without gh installed and signed in there is
 *   no repository to push to, so the page does not pretend otherwise: it shows
 *   the setup path and nothing else, handing off to the same flow the banner
 *   uses rather than inventing a second one.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Database,
  UploadCloud,
  RefreshCw,
  Loader2,
  ShieldAlert,
  CheckCircle2,
  AlertCircle,
  GitBranch,
  ExternalLink,
  ArrowUp,
  ArrowDown,
} from 'lucide-react';
import * as api from '@/api';
import { useAppStore } from '@/stores/appStore';
import type { DataRepoStatus, GhCliStatus, SyncTask } from '@/types/api';
import GitHubSetupModal from '@/components/github/GitHubSetupModal';
import SyncDialog from './SyncDialog';

/** While a sync runs, pending counts change under us; follow along. */
const POLL_RUNNING_MS = 5_000;
const POLL_IDLE_MS = 60_000;

const STATUS_STYLES: Record<string, string> = {
  modified: 'text-amber-500',
  added: 'text-green-500',
  untracked: 'text-green-500',
  deleted: 'text-red-500',
  renamed: 'text-blue-500',
  copied: 'text-blue-500',
  conflicted: 'text-red-500',
};

export default function DataRepoPage() {
  const { t } = useTranslation();
  const switchPage = useAppStore((state) => state.switchPage);

  const [gh, setGh] = useState<GhCliStatus | null>(null);
  // Whether the gh check has come back at all. Distinct from `gh` being null:
  // "not asked yet" and "asked, nothing there" lead to opposite screens, and
  // conflating them is what made the login prompt flash past on every visit.
  const [ghChecked, setGhChecked] = useState(false);
  const [status, setStatus] = useState<DataRepoStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [running, setRunning] = useState(false);
  const [task, setTask] = useState<SyncTask | null>(null);
  const [ghModalOpen, setGhModalOpen] = useState(false);
  const [syncDialogOpen, setSyncDialogOpen] = useState(false);

  const ghReady = !!gh?.installed && !!gh?.authenticated;

  const loadGh = useCallback(async () => {
    try {
      setGh(await api.checkGhCli());
    } catch (err) {
      console.error('Failed to check gh status:', err);
    } finally {
      setGhChecked(true);
    }
  }, []);

  const loadStatus = useCallback(async () => {
    setRefreshing(true);
    try {
      const [repo, sync] = await Promise.all([
        api.getDataRepoStatus(),
        api.getDataRepoSyncStatus(),
      ]);
      setStatus(repo);
      setRunning(sync.running);
      if (sync.task) setTask(sync.task);
    } catch (err) {
      console.error('Failed to load data repo status:', err);
    } finally {
      setRefreshing(false);
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadGh();
  }, [loadGh]);

  // Nothing here is meaningful until GitHub is connected, and asking git about
  // 26,000 paths on a loop while the page shows a setup prompt is pure waste.
  useEffect(() => {
    if (!ghReady) {
      setLoading(false);
      return;
    }
    loadStatus();
    const timer = setInterval(loadStatus, running ? POLL_RUNNING_MS : POLL_IDLE_MS);
    return () => clearInterval(timer);
  }, [ghReady, running, loadStatus]);

  const handleStarted = useCallback((started: SyncTask | null) => {
    setTask(started);
    setRunning(true);
  }, []);

  const counts = useMemo(() => status?.counts ?? {}, [status?.counts]);
  const deletions = counts.deleted ?? 0;
  const orderedCounts = useMemo(
    () =>
      (['modified', 'added', 'untracked', 'deleted', 'renamed', 'conflicted'] as const)
        .filter((key) => counts[key])
        .map((key) => ({ key, count: counts[key] })),
    [counts]
  );

  // Until the gh check comes back, this page has nothing true to say. Guessing
  // "not connected" and correcting a moment later flashes a login prompt at
  // people who are already logged in — every single visit.
  if (!ghChecked) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <span className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
          <Loader2 size={16} className="animate-spin" />
          {t('dataRepo.loading')}
        </span>
      </div>
    );
  }

  // ---- gate: no GitHub, no backup ----
  if (!ghReady) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center p-8">
        <div className="w-full max-w-lg rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-6 text-center">
          <ShieldAlert size={32} className="mx-auto mb-3 text-amber-500" />
          <h2 className="text-lg font-semibold text-[var(--text-primary)]">
            {t('dataRepo.ghGateTitle')}
          </h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-[var(--text-secondary)]">
            {gh && !gh.installed
              ? t('dataRepo.ghGateNotInstalled')
              : t('dataRepo.ghGateNotAuthenticated')}
          </p>
          <button
            type="button"
            onClick={() => setGhModalOpen(true)}
            className="mt-4 inline-flex items-center gap-1.5 rounded-md bg-[var(--accent-primary)] px-4 py-2 text-sm font-medium text-[var(--text-on-accent)] hover:opacity-90"
          >
            <UploadCloud size={16} />
            {gh && !gh.installed ? t('dataRepo.ghGateInstall') : t('dataRepo.ghGateLogin')}
          </button>
        </div>

        <GitHubSetupModal
          isOpen={ghModalOpen}
          onClose={() => setGhModalOpen(false)}
          ghStatus={gh}
          onStatusChange={loadGh}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-color)] px-5 py-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--text-primary)]">
            <Database size={18} className="text-[var(--accent-primary)]" />
            {t('dataRepo.title')}
          </h2>
          {status?.remote_url && (
            <a
              href={status.remote_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-0.5 inline-flex items-center gap-1 text-xs text-[var(--text-secondary)] hover:underline"
            >
              {status.remote_url.replace(/^https:\/\/github\.com\//, '')}
              <ExternalLink size={11} />
            </a>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={loadStatus}
            disabled={refreshing}
            className="text-[var(--text-muted)] hover:text-[var(--text-primary)] disabled:opacity-50"
            aria-label={t('dataRepo.refresh')}
            title={t('dataRepo.refresh')}
          >
            <RefreshCw size={15} className={refreshing ? 'animate-spin' : undefined} />
          </button>
          <button
            type="button"
            onClick={() => setSyncDialogOpen(true)}
            disabled={running || !status?.configured}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--accent-primary)] px-4 py-2 text-sm font-medium text-[var(--text-on-accent)] hover:opacity-90 disabled:opacity-50"
          >
            {running ? <Loader2 size={15} className="animate-spin" /> : <UploadCloud size={15} />}
            {running ? t('dataRepo.syncing') : t('dataRepo.syncButton')}
          </button>
        </div>
      </div>

      <div className="page-scroll flex-1 space-y-4 p-5">
        {loading && !status ? (
          <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
            <Loader2 size={16} className="animate-spin" />
            {t('dataRepo.loading')}
          </div>
        ) : !status?.configured ? (
          <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-4 text-sm">
            <AlertCircle size={16} className="mt-0.5 shrink-0 text-amber-500" />
            <div>
              <p className="font-medium text-[var(--text-primary)]">
                {t('dataRepo.notConfiguredTitle')}
              </p>
              <p className="mt-1 text-[var(--text-secondary)]">
                {t('dataRepo.notConfiguredBody', { path: status?.repo_path })}
              </p>
            </div>
          </div>
        ) : (
          <>
            {running && (
              <div className="flex items-start gap-2 rounded-md border border-[var(--accent-primary-20)] bg-[var(--accent-primary-10)] p-3 text-sm">
                <Loader2 size={16} className="mt-0.5 shrink-0 animate-spin text-[var(--accent-primary)]" />
                <div className="min-w-0">
                  <p className="font-medium text-[var(--text-primary)]">
                    {t('dataRepo.runningTitle')}
                  </p>
                  <p className="mt-1 text-[var(--text-secondary)]">
                    {t('dataRepo.runningBody')}
                  </p>
                  {task?.instruction && (
                    <p className="mt-1 text-xs text-[var(--text-muted)]">
                      {t('dataRepo.runningInstruction', { instruction: task.instruction })}
                    </p>
                  )}
                  <button
                    type="button"
                    onClick={() => switchPage('session_workbench')}
                    className="mt-2 text-xs text-[var(--accent-primary)] hover:underline"
                  >
                    {t('dataRepo.openWorkbench')}
                  </button>
                </div>
              </div>
            )}

            {/* A stored credential we could not confirm. Said quietly here
                rather than as a login prompt: the user is not logged out, and
                treating a network blip as one would send them re-authenticating
                for no reason. */}
            {gh && gh.verified === false && (
              <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
                <AlertCircle size={16} className="mt-0.5 shrink-0 text-amber-500" />
                <p className="min-w-0 text-[var(--text-secondary)]">
                  {gh.verify_error || t('dataRepo.unverified')}
                </p>
              </div>
            )}

            {status.error && (
              <div className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm">
                <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-500" />
                <p className="min-w-0 break-words text-[var(--text-secondary)]">{status.error}</p>
              </div>
            )}

            {/* Headline numbers */}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-3">
                <p className="text-xs text-[var(--text-secondary)]">{t('dataRepo.pending')}</p>
                <p className="mt-1 text-2xl font-semibold text-[var(--text-primary)]">
                  {status.pending_total.toLocaleString()}
                </p>
              </div>
              <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-3">
                <p className="text-xs text-[var(--text-secondary)]">{t('dataRepo.unpushed')}</p>
                <p className="mt-1 flex items-center gap-1 text-2xl font-semibold text-[var(--text-primary)]">
                  <ArrowUp size={16} className="text-[var(--text-muted)]" />
                  {status.ahead}
                  {status.behind > 0 && (
                    <span className="ml-2 flex items-center gap-1 text-base text-[var(--text-secondary)]">
                      <ArrowDown size={14} />
                      {status.behind}
                    </span>
                  )}
                </p>
              </div>
              <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-3">
                <p className="text-xs text-[var(--text-secondary)]">{t('dataRepo.branch')}</p>
                <p className="mt-1 flex items-center gap-1 truncate text-sm font-medium text-[var(--text-primary)]">
                  <GitBranch size={14} className="shrink-0 text-[var(--text-muted)]" />
                  {status.branch}
                </p>
              </div>
              <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-3">
                <p className="text-xs text-[var(--text-secondary)]">{t('dataRepo.lastCommit')}</p>
                <p className="mt-1 truncate text-sm text-[var(--text-primary)]" title={status.last_commit?.subject}>
                  {status.last_commit?.subject || '—'}
                </p>
              </div>
            </div>

            {status.pending_total === 0 && status.ahead === 0 ? (
              <div className="flex items-center gap-2 rounded-md border border-green-500/30 bg-green-500/10 p-4 text-sm text-[var(--text-primary)]">
                <CheckCircle2 size={18} className="shrink-0 text-green-500" />
                {t('dataRepo.allBackedUp')}
              </div>
            ) : (
              <>
                {/* Breakdown by kind of change */}
                {orderedCounts.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {orderedCounts.map(({ key, count }) => (
                      <span
                        key={key}
                        className="rounded-full bg-[var(--bg-tertiary)] px-3 py-1 text-xs text-[var(--text-secondary)]"
                      >
                        <span className={STATUS_STYLES[key]}>●</span>{' '}
                        {t(`dataRepo.status.${key}`)} {count.toLocaleString()}
                      </span>
                    ))}
                  </div>
                )}

                {deletions >= 200 && (
                  <div className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm">
                    <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-500" />
                    <div className="min-w-0">
                      <p className="font-medium text-[var(--text-primary)]">
                        {t('dataRepo.massDeletionTitle', { total: deletions.toLocaleString() })}
                      </p>
                      <p className="mt-1 text-[var(--text-secondary)]">
                        {t('dataRepo.massDeletionBody')}
                      </p>
                    </div>
                  </div>
                )}

                {/* The rollup: the only view that makes five figures legible */}
                <section>
                  <h3 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">
                    {t('dataRepo.byArea')}
                  </h3>
                  <div className="space-y-1.5">
                    {status.rollup.map((area) => {
                      const share = status.pending_total
                        ? Math.max(2, Math.round((area.count / status.pending_total) * 100))
                        : 0;
                      return (
                        <div key={area.area} className="flex items-center gap-3">
                          <code className="w-56 shrink-0 truncate font-mono text-xs text-[var(--text-primary)]">
                            {area.area}
                          </code>
                          <div className="h-2 flex-1 overflow-hidden rounded-full bg-[var(--bg-tertiary)]">
                            <div
                              className="h-full rounded-full bg-[var(--accent-primary)]"
                              style={{ width: `${share}%` }}
                            />
                          </div>
                          <span className="w-20 shrink-0 text-right text-xs tabular-nums text-[var(--text-secondary)]">
                            {area.count.toLocaleString()}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </section>

                {/* A sample of real paths */}
                <section>
                  <h3 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">
                    {t('dataRepo.fileList')}
                    {status.truncated && (
                      <span className="ml-2 font-normal text-xs text-[var(--text-muted)]">
                        {t('dataRepo.truncated', {
                          shown: status.files.length.toLocaleString(),
                          total: status.pending_total.toLocaleString(),
                        })}
                      </span>
                    )}
                  </h3>
                  <div className="max-h-96 overflow-auto rounded-md border border-[var(--border-color)] bg-[var(--bg-card)]">
                    {status.files.map((file) => (
                      <div
                        key={`${file.status}:${file.path}`}
                        className="flex items-center gap-2 border-b border-[var(--border-color)] px-3 py-1.5 last:border-b-0"
                      >
                        <span
                          className={`w-16 shrink-0 text-[11px] ${STATUS_STYLES[file.status] || 'text-[var(--text-muted)]'}`}
                        >
                          {t(`dataRepo.status.${file.status}`)}
                        </span>
                        <code className="min-w-0 flex-1 truncate font-mono text-xs text-[var(--text-secondary)]">
                          {file.path}
                        </code>
                      </div>
                    ))}
                  </div>
                </section>
              </>
            )}
          </>
        )}
      </div>

      <SyncDialog
        isOpen={syncDialogOpen}
        onClose={() => setSyncDialogOpen(false)}
        status={status}
        onStarted={handleStarted}
      />
    </div>
  );
}
