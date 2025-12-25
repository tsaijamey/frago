/**
 * Sync Settings Component
 * Sync configuration and GitHub wizard
 */

import { useEffect, useState } from 'react';
import { getMainConfig, runFirstSync, getSyncResult, checkSyncRepoVisibility, checkGhCli } from '@/api';
import { Github, RefreshCw, AlertTriangle, Check, X, Loader2, AlertCircle } from 'lucide-react';
import GitHubWizard from './GitHubWizard';

import type { GhCliStatus } from '@/types/pywebview';

export default function SyncSettings() {
  const [syncRepoUrl, setSyncRepoUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showWizard, setShowWizard] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncOutput, setSyncOutput] = useState('');
  const [syncError, setSyncError] = useState<string | null>(null);
  const [isPublicRepo, setIsPublicRepo] = useState(false);
  const [visibilityChecked, setVisibilityChecked] = useState(false);
  const [ghStatus, setGhStatus] = useState<GhCliStatus | null>(null);
  const [ghStatusLoading, setGhStatusLoading] = useState(false);

  const checkGhStatus = async () => {
    try {
      setGhStatusLoading(true);
      const status = await checkGhCli();
      setGhStatus(status);
    } catch (err) {
      console.error('Failed to check gh status:', err);
    } finally {
      setGhStatusLoading(false);
    }
  };

  useEffect(() => {
    loadConfig();
    checkGhStatus();
  }, []);

  const loadConfig = async () => {
    try {
      setLoading(true);
      const config = await getMainConfig();
      setSyncRepoUrl(config.sync_repo_url || null);

      // If repository is configured, check visibility
      if (config.sync_repo_url) {
        try {
          const visibilityResult = await checkSyncRepoVisibility();
          if (visibilityResult.status === 'ok') {
            setIsPublicRepo(visibilityResult.is_public || false);
            setVisibilityChecked(true);
          }
        } catch (err) {
          console.error('Failed to check repository visibility:', err);
        }
      }
    } catch (err) {
      console.error('Failed to load configuration:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSync = async () => {
    try {
      setSyncing(true);
      setSyncError(null);
      setSyncOutput('Starting sync...\n');

      const startResult = await runFirstSync();
      if (startResult.status === 'error') {
        setSyncError(startResult.error || 'Sync failed');
        setSyncing(false);
        return;
      }

      // Poll for results
      const pollInterval = setInterval(async () => {
        const result = await getSyncResult();

        if (result.status === 'running') {
          // Still running
          return;
        }

        clearInterval(pollInterval);
        setSyncing(false);

        if (result.status === 'ok') {
          setSyncOutput((prev) => prev + '\n✓ Sync completed\n' + (result.output || ''));
        } else {
          setSyncError(result.error || 'Sync failed');
          setSyncOutput((prev) => prev + '\n✗ Sync failed\n' + (result.error || ''));
        }
      }, 1000);

      // Timeout protection (5 minutes)
      setTimeout(() => {
        clearInterval(pollInterval);
        if (syncing) {
          setSyncing(false);
          setSyncError('Sync timeout');
        }
      }, 300000);

    } catch (err) {
      setSyncError(err instanceof Error ? err.message : 'Sync failed');
      setSyncing(false);
    }
  };

  const handleWizardComplete = () => {
    setShowWizard(false);
    loadConfig(); // Reload configuration
  };

  if (loading) {
    return (
      <div className="text-[var(--text-muted)] text-center py-8">
        Loading configuration...
      </div>
    );
  }

  if (showWizard) {
    return <GitHubWizard onComplete={handleWizardComplete} onCancel={() => setShowWizard(false)} />;
  }

  return (
    <div className="space-y-4">
      <div className="card">
        <h2 className="text-lg font-semibold text-[var(--accent-primary)] mb-4">
          Multi-Device Sync
        </h2>

        {/* GitHub CLI Status Detection */}
        <div className="mb-4 p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-md">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-blue-900 dark:text-blue-200">
              GitHub CLI Status
            </h3>
            <button
              onClick={checkGhStatus}
              disabled={ghStatusLoading}
              className="text-xs text-blue-600 dark:text-blue-400 hover:underline disabled:opacity-50"
            >
              {ghStatusLoading ? 'Checking...' : 'Refresh'}
            </button>
          </div>

          {ghStatusLoading && !ghStatus ? (
            <div className="flex items-center gap-2 text-sm text-blue-700 dark:text-blue-300">
              <Loader2 size={14} className="animate-spin" />
              Checking...
            </div>
          ) : ghStatus ? (
            <div className="space-y-1 text-sm">
              {/* gh installation status */}
              <div className={`flex items-center gap-2 ${
                ghStatus.installed
                  ? 'text-green-600 dark:text-green-400'
                  : 'text-red-600 dark:text-red-400'
              }`}>
                {ghStatus.installed ? <Check size={14} /> : <X size={14} />}
                <span>
                  {ghStatus.installed
                    ? `gh CLI installed (v${ghStatus.version})`
                    : 'gh CLI not installed'}
                </span>
              </div>

              {/* Login status (only shown when installed) */}
              {ghStatus.installed && (
                <div className={`flex items-center gap-2 ${
                  ghStatus.authenticated
                    ? 'text-green-600 dark:text-green-400'
                    : 'text-yellow-600 dark:text-yellow-400'
                }`}>
                  {ghStatus.authenticated ? <Check size={14} /> : <AlertCircle size={14} />}
                  <span>
                    {ghStatus.authenticated
                      ? `Logged in to GitHub (@${ghStatus.username})`
                      : 'Not logged in to GitHub'}
                  </span>
                </div>
              )}

              {/* Action hints */}
              {!ghStatus.installed && (
                <p className="mt-2 text-blue-700 dark:text-blue-300">
                  Please install GitHub CLI first:
                  <a
                    href="https://cli.github.com/"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="ml-1 underline"
                  >
                    https://cli.github.com/
                  </a>
                </p>
              )}
              {ghStatus.installed && !ghStatus.authenticated && (
                <p className="mt-2 text-blue-700 dark:text-blue-300">
                  Click "Start Setup" button below to log in to GitHub
                </p>
              )}
            </div>
          ) : (
            <p className="text-sm text-blue-700 dark:text-blue-300">
              First-time setup requires installing GitHub CLI (gh) and logging in to your GitHub account. The wizard will guide you through the process.
            </p>
          )}
        </div>

        {syncRepoUrl ? (
          <>
            <div className="flex gap-2 mb-4">
              <button
                onClick={handleSync}
                disabled={syncing}
                className="btn btn-primary flex items-center gap-2"
              >
                <RefreshCw size={16} className={syncing ? 'animate-spin' : ''} />
                {syncing ? 'Syncing...' : 'Sync Now'}
              </button>
              <button
                onClick={() => setShowWizard(true)}
                className="btn btn-ghost"
              >
                Reconfigure
              </button>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-[var(--text-primary)] mb-2">
                Sync Repository
              </label>
              <div className="flex items-center gap-2 bg-[var(--bg-subtle)] rounded-md px-3 py-2">
                <Github size={16} className="text-[var(--text-muted)]" />
                <span className="text-sm text-[var(--text-secondary)] font-mono flex-1">
                  {syncRepoUrl}
                </span>
              </div>
            </div>

            {/* Public repository warning */}
            {visibilityChecked && isPublicRepo && (
              <div className="mb-4 p-3 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-md">
                <div className="flex items-start gap-2">
                  <AlertTriangle size={16} className="text-yellow-600 dark:text-yellow-400 mt-0.5 flex-shrink-0" />
                  <div>
                    <h3 className="text-sm font-medium text-yellow-800 dark:text-yellow-200 mb-1">
                      Security Warning
                    </h3>
                    <p className="text-sm text-yellow-700 dark:text-yellow-300">
                      The current sync repository is <strong>public</strong> and accessible to anyone.
                      We recommend changing it to private to protect your configuration and sensitive information.
                    </p>
                    <p className="text-xs text-yellow-600 dark:text-yellow-400 mt-2">
                      .env files are automatically added to .gitignore and will not be synced.
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Sync output */}
            {syncOutput && (
              <div className="mt-4 p-3 bg-black/5 dark:bg-white/5 rounded-md">
                <pre className="text-xs text-[var(--text-secondary)] whitespace-pre-wrap font-mono">
                  {syncOutput}
                </pre>
              </div>
            )}

            {/* Sync error */}
            {syncError && (
              <div className="mt-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md">
                <p className="text-sm text-red-700 dark:text-red-400">{syncError}</p>
              </div>
            )}
          </>
        ) : (
          <>
            <p className="text-sm text-[var(--text-muted)] mb-4">
              Use a GitHub private repository to sync frago resources (commands, skills, recipes) across multiple devices.
            </p>
            <button
              onClick={() => setShowWizard(true)}
              className="btn btn-primary flex items-center gap-2"
            >
              <Github size={16} />
              Start GitHub Sync Setup
            </button>
          </>
        )}
      </div>
    </div>
  );
}
