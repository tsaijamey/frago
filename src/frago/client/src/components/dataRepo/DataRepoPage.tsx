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
import PageHeader from '@/components/layout/PageHeader';
import {
  UploadCloud,
  RefreshCw,
  Loader2,
  ShieldAlert,
  CheckCircle2,
  AlertCircle,
  GitBranch,
  ExternalLink,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import * as api from '@/api';
import { useAppStore } from '@/stores/appStore';
import type { AreaCount, DataRepoStatus, GhCliStatus, PendingFile, SyncTask } from '@/types/api';
import GitHubSetupModal from '@/components/github/GitHubSetupModal';
import SyncDialog from './SyncDialog';

/** While a sync runs, pending counts change under us; follow along. */
const POLL_RUNNING_MS = 5_000;
const POLL_IDLE_MS = 60_000;

/**
 * Kind of change is a neutral fact, so it is told apart by text weight alone.
 * Orange reads as a warning and green as "act" or "running"; either would make
 * a routine edit look like something to deal with. The real risk — a mass
 * deletion — has its own red notice further up.
 */
const STATUS_STYLES: Record<string, string> = {
  modified: 'text-[var(--text-secondary)]',
  deleted: 'text-[var(--text-secondary)]',
  conflicted: 'text-[var(--text-secondary)]',
};
const STATUS_MUTED = 'text-[var(--text-muted)]';

/** Order the breakdown is spelled out in, under "Files pending" and on group heads. */
const KIND_ORDER = ['modified', 'added', 'untracked', 'deleted', 'renamed', 'copied', 'conflicted'] as const;

/** Rows listed per directory group before "N more in …". */
const GROUP_ROWS = 8;
/** The two biggest directories open by default; the rest start folded. */
const GROUPS_OPEN_BY_DEFAULT = 2;

/**
 * The area a path belongs to. Must match `_top_level` in
 * services/data_repo_service.py exactly — the rollup is keyed by it, and a
 * path that maps to a different key silently falls out of every group.
 */
function areaOf(path: string): string {
  const slash = path.indexOf('/');
  if (slash < 0) return path;
  const head = path.slice(0, slash);
  return slash < path.length - 1 ? `${head}/` : head;
}

interface FileGroup {
  area: string;
  /** From the rollup, which counts everything — never from the sample. */
  total: number;
  rows: PendingFile[];
  /** Per-kind counts, only when they are known to cover the whole area. */
  counts: Record<string, number> | null;
}

/**
 * Group heads take their number from the rollup (the full count); rows come
 * from a sample. Newer servers send each area its own sample and breakdown.
 * Older ones only send the flat `files` sample, capped at 500 in git's order,
 * so a large repository leaves some areas short: those keep the true total on
 * the head but show no breakdown rather than a number that is too small.
 */
function buildGroups(rollup: AreaCount[], files: PendingFile[]): FileGroup[] {
  const fromFlat = new Map<string, PendingFile[]>();
  for (const file of files) {
    const area = areaOf(file.path);
    const bucket = fromFlat.get(area);
    if (bucket) bucket.push(file);
    else fromFlat.set(area, [file]);
  }
  if (import.meta.env.DEV) {
    const known = new Set(rollup.map((a) => a.area));
    const stray = [...fromFlat.keys()].filter((area) => !known.has(area));
    if (stray.length) console.warn('DataRepoPage: sample paths outside the rollup', stray);
  }

  return rollup.map((a) => {
    if (a.sample && a.counts) {
      return { area: a.area, total: a.count, rows: a.sample, counts: a.counts };
    }
    const rows = fromFlat.get(a.area) ?? [];
    let counts: Record<string, number> | null = null;
    if (rows.length === a.count) {
      counts = {};
      for (const row of rows) counts[row.status] = (counts[row.status] ?? 0) + 1;
    }
    return { area: a.area, total: a.count, rows, counts };
  });
}

export default function DataRepoPage() {
  const { t, i18n } = useTranslation();
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

  // Keyed by area. Survives every re-count (60 s idle, 5 s while syncing);
  // not persisted — a reload goes back to the two biggest open.
  const [openAreas, setOpenAreas] = useState<Record<string, boolean>>({});

  const counts = useMemo(() => status?.counts ?? {}, [status?.counts]);
  const deletions = counts.deleted ?? 0;
  const describeCounts = useCallback(
    (source: Record<string, number>) =>
      KIND_ORDER.filter((key) => source[key])
        .map((key) => `${source[key].toLocaleString()} ${t(`dataRepo.status.${key}`)}`)
        .join(' · '),
    [t]
  );

  const groups = useMemo(
    () => (status ? buildGroups(status.rollup, status.files) : []),
    [status]
  );
  const maxArea = useMemo(
    () => (status ? Math.max(0, ...status.rollup.map((a) => a.count)) : 0),
    [status]
  );
  const lastCommitAt = useMemo(() => {
    const when = status?.last_commit?.committed_at;
    if (!when) return null;
    const date = new Date(when);
    if (Number.isNaN(date.getTime())) return null;
    return new Intl.DateTimeFormat(i18n?.language, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(date);
  }, [status?.last_commit?.committed_at, i18n?.language]);

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
      {/* 标题前的绿色数据库图标去掉了：绿只给主动作，这一屏的绿留给「同步」。
          仓库链接占页头短计数的位置，中性弱色。 */}
      <PageHeader
        title={t('dataRepo.title')}
        meta={
          status?.remote_url ? (
            <a
              href={status.remote_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 !text-inherit hover:underline"
            >
              {status.remote_url.replace(/^https:\/\/github\.com\//, '')}
              <ExternalLink size={11} />
            </a>
          ) : undefined
        }
        secondary={
          <button
            type="button"
            onClick={loadStatus}
            disabled={refreshing}
            className="page-header-btn page-header-btn--icon page-header-btn--ghost"
            aria-label={t('dataRepo.refresh')}
            title={t('dataRepo.refresh')}
          >
            <RefreshCw size={14} className={refreshing ? 'animate-spin' : undefined} />
          </button>
        }
        primary={{
          label: running ? t('dataRepo.syncing') : t('dataRepo.syncButton'),
          icon: running ? <Loader2 size={14} className="animate-spin" /> : <UploadCloud size={14} />,
          onClick: () => setSyncDialogOpen(true),
          disabled: running || !status?.configured,
        }}
      />

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

            {/* Headline numbers: one strip, hairlines between cells, no card per number. */}
            <div className="grid grid-cols-2 rounded-[10px] border border-[var(--border-color)] md:grid-cols-[1.2fr_0.8fr_0.8fr_1.6fr] [&>*]:min-w-0 [&>*]:border-[var(--border-color)] [&>*]:px-3.5 [&>*]:py-2.5 [&>*:nth-child(2n)]:border-l max-md:[&>*:nth-child(n+3)]:border-t md:[&>*:nth-child(n+2)]:border-l">
              <div>
                <p className="text-[11px] text-[var(--text-muted)]">{t('dataRepo.pending')}</p>
                <p className="text-[20px] font-semibold leading-[1.3] tabular-nums text-[var(--text-primary)]">
                  {status.pending_total.toLocaleString()}
                </p>
                {status.pending_total > 0 && (
                  <p className="truncate text-[11px] text-[var(--text-muted)]">{describeCounts(counts)}</p>
                )}
              </div>
              <div>
                <p className="text-[11px] text-[var(--text-muted)]">{t('dataRepo.unpushed')}</p>
                <p className="text-[20px] font-semibold leading-[1.3] tabular-nums text-[var(--text-primary)]">
                  {status.ahead.toLocaleString()}
                </p>
                <p className="text-[11px] text-[var(--text-muted)]">
                  {t('dataRepo.behind', { count: status.behind })}
                </p>
              </div>
              <div>
                <p className="text-[11px] text-[var(--text-muted)]">{t('dataRepo.branch')}</p>
                <p
                  className="flex items-center gap-1.5 text-sm font-medium leading-[30px] text-[var(--text-primary)]"
                  title={status.branch ?? undefined}
                >
                  <GitBranch size={13} className="shrink-0 text-[var(--text-muted)]" />
                  <span className="truncate">{status.branch}</span>
                </p>
              </div>
              <div>
                <p className="truncate text-[11px] text-[var(--text-muted)]">
                  {status.last_commit && lastCommitAt
                    ? t('dataRepo.lastCommitAt', { when: lastCommitAt })
                    : t('dataRepo.lastCommit')}
                </p>
                <p
                  className="truncate text-sm font-medium leading-[30px] text-[var(--text-primary)]"
                  title={status.last_commit?.subject}
                >
                  {status.last_commit?.subject || '—'}
                </p>
                {status.last_commit?.sha && (
                  <p className="truncate font-mono text-[11px] text-[var(--text-muted)]">
                    {status.last_commit.sha}
                  </p>
                )}
              </div>
            </div>

            {status.pending_total === 0 && status.ahead === 0 ? (
              /* Success is a fact, not an action: neutral, with the check doing the talking. */
              <div className="flex items-center gap-2 rounded-md border border-[var(--border-color)] bg-[var(--bg-hover)] p-4 text-sm text-[var(--text-primary)]">
                <CheckCircle2 size={16} className="shrink-0 text-[var(--text-secondary)]" />
                {t('dataRepo.allBackedUp')}
              </div>
            ) : (
              <>
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

                {/* The rollup: the only view that makes five figures legible.
                    Two columns, bars scaled to the largest area so the longest
                    one fills its track. */}
                {status.rollup.length > 0 && (
                  <section>
                    <h3 className="mb-2 flex items-baseline gap-2 text-sm font-semibold text-[var(--text-primary)]">
                      {t('dataRepo.byArea')}
                      <span className="text-xs font-normal text-[var(--text-muted)]">
                        {status.rollup.length}
                      </span>
                    </h3>
                    <div className="grid gap-x-7 md:grid-cols-2">
                      {[
                        status.rollup.slice(0, Math.ceil(status.rollup.length / 2)),
                        status.rollup.slice(Math.ceil(status.rollup.length / 2)),
                      ].map((column, i) => (
                        <div key={i}>
                          {column.map((area) => (
                            <div
                              key={area.area}
                              className="grid h-6 grid-cols-[130px_1fr_48px] items-center gap-2.5 text-xs"
                            >
                              <code className="truncate font-mono text-[11px] text-[var(--text-secondary)]" title={area.area}>
                                {area.area}
                              </code>
                              <div className="h-1 overflow-hidden rounded-[3px] bg-[var(--usage-track)]">
                                <div
                                  className="h-full rounded-[3px] bg-[var(--text-muted)]"
                                  style={{
                                    width: `${maxArea ? Math.max(2, (area.count / maxArea) * 100) : 0}%`,
                                  }}
                                />
                              </div>
                              <span className="text-right tabular-nums text-[var(--text-muted)]">
                                {area.count.toLocaleString()}
                              </span>
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                {/* Files, grouped by the same areas as the bars. Group heads carry
                    the full count; rows are a sample of at most GROUP_ROWS. */}
                {groups.length > 0 && (
                  <section>
                    <h3 className="mb-2 flex items-baseline gap-2 text-sm font-semibold text-[var(--text-primary)]">
                      {t('dataRepo.fileList')}
                      <span className="text-xs font-normal text-[var(--text-muted)]">
                        {t('dataRepo.filesGrouped', { total: status.pending_total.toLocaleString() })}
                      </span>
                    </h3>
                    <div className="space-y-2">
                      {groups.map((group, i) => {
                        const open = openAreas[group.area] ?? i < GROUPS_OPEN_BY_DEFAULT;
                        const shown = open ? group.rows.slice(0, GROUP_ROWS) : [];
                        const more = group.total - shown.length;
                        const prefix = group.area.endsWith('/') ? group.area.length : 0;
                        return (
                          <div
                            key={group.area}
                            data-area-group={group.area}
                            className="overflow-hidden rounded-[10px] border border-[var(--border-color)]"
                          >
                            <button
                              type="button"
                              onClick={() =>
                                setOpenAreas((prev) => ({ ...prev, [group.area]: !open }))
                              }
                              aria-expanded={open}
                              className="flex w-full items-center gap-2 bg-[var(--bg-hover)] px-3 py-[7px] text-left text-xs"
                            >
                              {open ? (
                                <ChevronDown size={12} className="shrink-0 text-[var(--text-muted)]" />
                              ) : (
                                <ChevronRight size={12} className="shrink-0 text-[var(--text-muted)]" />
                              )}
                              <span className="truncate font-mono font-medium text-[var(--text-primary)]">
                                {group.area}
                              </span>
                              <span className="tabular-nums text-[var(--text-muted)]">
                                {group.total.toLocaleString()}
                              </span>
                              {group.counts && (
                                <span className="ml-auto truncate text-[11px] text-[var(--text-muted)]">
                                  {describeCounts(group.counts)}
                                </span>
                              )}
                            </button>
                            {shown.map((file) => (
                              <div
                                key={`${file.status}:${file.path}`}
                                data-file-row
                                className="flex min-w-0 items-center gap-2.5 border-t border-[var(--border-color)] px-3 py-1"
                              >
                                <span
                                  className={`w-[58px] shrink-0 text-[11px] ${STATUS_STYLES[file.status] ?? STATUS_MUTED}`}
                                >
                                  {t(`dataRepo.status.${file.status}`)}
                                </span>
                                <code className="min-w-0 flex-1 truncate font-mono text-[11px] text-[var(--text-secondary)]" title={file.path}>
                                  {file.path.slice(prefix) || file.path}
                                </code>
                              </div>
                            ))}
                            {open && more > 0 && (
                              <div className="border-t border-[var(--border-color)] px-3 py-[5px] text-[11px] text-[var(--text-muted)]">
                                {t('dataRepo.moreInArea', {
                                  n: more.toLocaleString(),
                                  area: group.area,
                                })}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </section>
                )}
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
