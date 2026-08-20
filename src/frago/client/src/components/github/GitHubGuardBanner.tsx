/**
 * GitHubGuardBanner
 *
 * Sits above everything else on the 8093 page whenever the GitHub CLI is
 * missing or logged out. There is deliberately no dismiss button and no
 * "don't show again": the thing it is warning about — a working directory
 * with no backup anywhere — does not stop being true because the notice was
 * closed once, and the user only finds out it mattered after a disk dies.
 *
 * It disappears on its own the moment gh is installed and authenticated.
 *
 * Server mode only. The desktop shell talks to gh through its own native
 * path and never reaches these endpoints.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ShieldAlert, Download, LogIn, Loader2, RefreshCw } from 'lucide-react';
import * as api from '@/api';
import { getApiMode } from '@/api';
import type { GhCliStatus } from '@/types/api';
import GitHubSetupModal from './GitHubSetupModal';

/** How often to re-check, so a login finished in a terminal clears the banner too. */
const POLL_INTERVAL_MS = 30_000;

export default function GitHubGuardBanner() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<GhCliStatus | null>(null);
  const [checking, setChecking] = useState(false);
  const [installRunning, setInstallRunning] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  const serverMode = getApiMode() === 'http';

  const refresh = useCallback(async () => {
    setChecking(true);
    try {
      setStatus(await api.checkGhCli());
    } catch (err) {
      // A failed check is not evidence of anything: leave the last known
      // answer alone rather than flashing a warning at someone who is fine.
      console.error('Failed to check gh CLI status:', err);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    if (!serverMode) return;
    refresh();
    const timer = setInterval(refresh, POLL_INTERVAL_MS);
    // Coming back to the tab is the usual moment after installing or logging
    // in elsewhere, so check then rather than waiting out the interval.
    const onFocus = () => refresh();
    window.addEventListener('focus', onFocus);
    return () => {
      clearInterval(timer);
      window.removeEventListener('focus', onFocus);
    };
  }, [serverMode, refresh]);

  // While an install runs, the button says so even if the user closed the
  // window it was started from.
  useEffect(() => {
    if (!serverMode || !status || status.installed) {
      setInstallRunning(false);
      return;
    }
    let cancelled = false;
    const poll = async () => {
      try {
        const result = await api.getGhInstallStatus();
        if (cancelled) return;
        setInstallRunning(result.status === 'running');
        if (result.status === 'success') refresh();
      } catch {
        // Nothing to do — the banner still shows the un-installed state.
      }
    };
    poll();
    const timer = setInterval(poll, 3000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [serverMode, status, refresh]);

  const handlePrimary = useCallback(() => {
    // Both paths open the explaining window rather than firing straight off.
    // Installing software and authorizing an account are things a user should
    // see coming, and the window is where the "why" lives.
    setModalOpen(true);
  }, []);

  if (!serverMode || !status) return null;
  if (status.installed && status.authenticated) return null;

  const needsInstall = !status.installed;

  return (
    <>
      <div className="flex flex-shrink-0 flex-wrap items-center justify-between gap-3 border-b border-amber-500/40 bg-amber-500/10 px-4 py-2.5">
        <div className="flex min-w-0 items-start gap-3">
          <ShieldAlert size={18} className="mt-0.5 shrink-0 text-amber-500" />
          <div className="min-w-0">
            <p className="text-sm font-medium text-[var(--text-primary)]">
              {needsInstall
                ? t('githubGuard.bannerNotInstalledTitle')
                : t('githubGuard.bannerNotAuthTitle')}
            </p>
            <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
              {needsInstall
                ? t('githubGuard.bannerNotInstalledText')
                : t('githubGuard.bannerNotAuthText')}
            </p>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={handlePrimary}
            disabled={installRunning}
            className="inline-flex items-center gap-1.5 rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-amber-700 disabled:opacity-60"
          >
            {installRunning ? (
              <Loader2 size={14} className="animate-spin" />
            ) : needsInstall ? (
              <Download size={14} />
            ) : (
              <LogIn size={14} />
            )}
            {installRunning
              ? t('githubGuard.installing')
              : needsInstall
                ? t('githubGuard.installNow')
                : t('githubGuard.loginNow')}
          </button>
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="text-xs text-[var(--text-secondary)] underline-offset-2 hover:underline"
          >
            {t('githubGuard.learnMore')}
          </button>
          <button
            type="button"
            onClick={refresh}
            disabled={checking}
            className="text-[var(--text-muted)] transition-colors hover:text-[var(--text-primary)] disabled:opacity-50"
            aria-label={t('githubGuard.recheck')}
            title={t('githubGuard.recheck')}
          >
            <RefreshCw size={14} className={checking ? 'animate-spin' : undefined} />
          </button>
        </div>
      </div>

      <GitHubSetupModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        ghStatus={status}
        onStatusChange={refresh}
      />
    </>
  );
}
