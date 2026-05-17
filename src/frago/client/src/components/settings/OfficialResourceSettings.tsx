/**
 * Official Resource Settings Component
 *
 * Pulls commands/skills from the official frago repository.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  getOfficialSyncStatus,
  runOfficialSync,
  getOfficialSyncResult,
  setOfficialSyncEnabled,
} from '@/api';
import { Github, Check, Loader2, Download } from 'lucide-react';
import type { OfficialSyncStatus, OfficialSyncResult } from '@/api/client';

export default function OfficialResourceSettings() {
  const { t } = useTranslation();

  const [officialStatus, setOfficialStatus] = useState<OfficialSyncStatus | null>(null);
  const [officialSyncing, setOfficialSyncing] = useState(false);
  const [officialResult, setOfficialResult] = useState<OfficialSyncResult | null>(null);
  const [officialError, setOfficialError] = useState<string | null>(null);

  const loadOfficialStatus = async () => {
    try {
      const status = await getOfficialSyncStatus();
      setOfficialStatus(status);
    } catch (err) {
      console.error('Failed to load official sync status:', err);
    }
  };

  const handleOfficialSync = async () => {
    try {
      setOfficialSyncing(true);
      setOfficialError(null);
      setOfficialResult(null);

      const startResult = await runOfficialSync();
      if (startResult.status === 'error') {
        setOfficialError(startResult.error || t('settings.officialSync.syncFailed'));
        setOfficialSyncing(false);
        return;
      }

      const pollInterval = setInterval(async () => {
        const result = await getOfficialSyncResult();

        if (result.status === 'running') {
          return;
        }

        clearInterval(pollInterval);
        setOfficialSyncing(false);
        setOfficialResult(result);

        if (result.status === 'error' || result.status === 'partial') {
          setOfficialError(result.error || null);
        }

        loadOfficialStatus();
      }, 1000);

      setTimeout(() => {
        clearInterval(pollInterval);
        if (officialSyncing) {
          setOfficialSyncing(false);
          setOfficialError(t('settings.officialSync.timeout'));
        }
      }, 120000);
    } catch (err) {
      setOfficialError(err instanceof Error ? err.message : t('settings.officialSync.syncFailed'));
      setOfficialSyncing(false);
    }
  };

  const handleToggleAutoSync = async (enabled: boolean) => {
    try {
      await setOfficialSyncEnabled(enabled);
      setOfficialStatus((prev) => (prev ? { ...prev, enabled } : null));
    } catch (err) {
      console.error('Failed to toggle auto-sync:', err);
    }
  };

  useEffect(() => {
    loadOfficialStatus();
  }, []);

  return (
    <div className="card">
      <h2 className="text-lg font-semibold text-[var(--text-primary)] mb-4">
        {t('settings.officialSync.title')}
      </h2>

      {/* Auto-sync Toggle */}
      <div className="flex items-center justify-between mb-4 py-3 border-b border-[var(--border-color)]">
        <div>
          <label className="text-sm font-medium text-[var(--text-primary)]">
            {t('settings.officialSync.autoSync')}
          </label>
          <p className="text-xs text-[var(--text-muted)]">
            {t('settings.officialSync.autoSyncDesc')}
          </p>
        </div>
        <label className="relative inline-flex items-center cursor-pointer">
          <input
            type="checkbox"
            className="sr-only peer"
            checked={officialStatus?.enabled || false}
            onChange={(e) => handleToggleAutoSync(e.target.checked)}
            aria-label={t('settings.officialSync.autoSync')}
          />
          <div className="w-11 h-6 bg-[var(--bg-elevated)] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-[var(--text-muted)] after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[var(--accent-primary)] peer-checked:after:bg-[var(--text-on-accent)]"></div>
        </label>
      </div>

      {/* Source Info */}
      {officialStatus && (
        <div className="mb-4 text-sm text-[var(--text-secondary)]">
          <div className="flex items-center gap-2 mb-1">
            <Github size={14} className="text-[var(--text-muted)]" />
            <span className="font-mono">{officialStatus.repo} ({officialStatus.branch})</span>
          </div>
          {officialStatus.last_sync && (
            <p className="text-xs text-[var(--text-muted)]">
              {t('settings.officialSync.lastSync')}: {new Date(officialStatus.last_sync).toLocaleString()}
            </p>
          )}
        </div>
      )}

      {/* Sync Button */}
      <button
        onClick={handleOfficialSync}
        disabled={officialSyncing}
        className="btn btn-primary flex items-center gap-2"
      >
        {officialSyncing ? (
          <Loader2 size={16} className="animate-spin" />
        ) : (
          <Download size={16} />
        )}
        {officialSyncing ? t('settings.officialSync.syncing') : t('settings.officialSync.syncNow')}
      </button>

      {/* Sync Result */}
      {officialResult && officialResult.status !== 'idle' && (
        <div className="mt-4 p-3 bg-black/5 dark:bg-white/5 rounded-md">
          <div className="text-sm">
            {officialResult.status === 'ok' && (
              <div className="flex items-center gap-2 text-green-600 dark:text-green-400 mb-2">
                <Check size={14} />
                <span>{t('settings.officialSync.syncComplete')}</span>
              </div>
            )}
            {officialResult.commands && (
              <p className="text-xs text-[var(--text-secondary)]">
                Commands: {officialResult.commands.files_synced} {t('settings.officialSync.filesSynced')}
              </p>
            )}
            {officialResult.skills && (
              <p className="text-xs text-[var(--text-secondary)]">
                Skills: {officialResult.skills.files_synced} {t('settings.officialSync.filesSynced')}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Sync Error */}
      {officialError && (
        <div className="mt-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md">
          <p className="text-sm text-red-700 dark:text-red-400">{officialError}</p>
        </div>
      )}
    </div>
  );
}
