/**
 * InitSettings — initialization status, and the way back into the wizard.
 *
 * Two things this panel used to get wrong, both fixed here.
 *
 * It judged readiness on Node.js as well as Claude Code, so a machine with
 * every agent CLI working would still show a warning if Node happened to be
 * absent. The agent CLIs ship as native binaries now — Claude Code's own
 * installer, Homebrew for opencode and codex — and npm is one route among
 * several rather than the way in. The server already stopped counting Node when
 * it computes whether dependencies are satisfied; this panel had not followed.
 * Node is now reported as what it is: present or not, never a problem.
 *
 * And every string was hardcoded English, so switching the interface to Chinese
 * left this panel untranslated.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  RefreshCw,
  PlayCircle,
  Loader2,
  Package,
  Cpu,
  Shield,
  Minus,
} from 'lucide-react';
import type { InitStatus } from '../../api/client';
import { getInitStatus, resetInitStatus } from '../../api/client';

interface InitSettingsProps {
  onOpenWizard: () => void;
}

export function InitSettings({ onOpenWizard }: InitSettingsProps) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<InitStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Wrapped because the fallback message is translated, so this closes over the
  // translator and is not stable across a language switch.
  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getInitStatus();
      setStatus(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.init.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const handleReset = async () => {
    setResetting(true);
    try {
      await resetInitStatus();
      onOpenWizard();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.init.resetFailed'));
    } finally {
      setResetting(false);
    }
  };

  if (loading) {
    return (
      <div className="card p-6">
        <div className="flex items-center gap-3 text-[var(--text-muted)]">
          <Loader2 className="w-5 h-5 animate-spin" />
          {t('settings.init.loading')}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 text-[var(--text-error)]">
            <XCircle className="w-5 h-5" />
            {error}
          </div>
          <button
            type="button"
            onClick={loadStatus}
            className="text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
            aria-label={t('settings.init.refresh')}
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  if (!status) return null;

  // Readiness rests on the agent CLI alone. Node is reported below but never
  // counted: see the note at the top of this file.
  const agentCliOk = status.claude_code.installed && status.claude_code.version_sufficient;
  const nodePresent = status.node.installed && status.node.version_sufficient;

  return (
    <div className="card space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-[var(--accent-primary)]">
          {t('settings.init.title')}
        </h2>
        <button
          type="button"
          onClick={loadStatus}
          className="p-2 text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-subtle)] rounded-lg transition-colors"
          aria-label={t('settings.init.refresh')}
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      <div className="space-y-3">
        {/* Agent CLI — the one that actually gates anything */}
        <div className="flex items-center justify-between p-3 bg-[var(--bg-subtle)] rounded-lg">
          <div className="flex items-center gap-3">
            <Shield className="w-5 h-5 text-[var(--text-muted)]" />
            <div>
              <span className="text-[var(--text-primary)] font-medium">
                {t('settings.init.agentCli')}
              </span>
              <p className="text-sm text-[var(--text-secondary)]">
                {status.claude_code.installed
                  ? t('settings.init.agentCliFound', { version: status.claude_code.version })
                  : t('settings.init.agentCliMissing')}
              </p>
            </div>
          </div>
          {agentCliOk ? (
            <CheckCircle className="w-5 h-5 text-green-600 dark:text-green-400" />
          ) : (
            <AlertTriangle className="w-5 h-5 text-yellow-600 dark:text-yellow-400" />
          )}
        </div>

        {/* Node.js — informational only */}
        <div className="flex items-center justify-between p-3 bg-[var(--bg-subtle)] rounded-lg">
          <div className="flex items-center gap-3">
            <Cpu className="w-5 h-5 text-[var(--text-muted)]" />
            <div>
              <span className="text-[var(--text-primary)] font-medium">
                {t('settings.init.node')}
              </span>
              <p className="text-sm text-[var(--text-secondary)]">
                {nodePresent
                  ? t('settings.init.nodeFound', { version: status.node.version })
                  : t('settings.init.nodeAbsent')}
              </p>
            </div>
          </div>
          {nodePresent ? (
            <CheckCircle className="w-5 h-5 text-green-600 dark:text-green-400" />
          ) : (
            <Minus className="w-5 h-5 text-[var(--text-muted)]" />
          )}
        </div>

        {/* Resources — two different version numbers, each labelled */}
        <div className="flex items-center justify-between p-3 bg-[var(--bg-subtle)] rounded-lg">
          <div className="flex items-center gap-3">
            <Package className="w-5 h-5 text-[var(--text-muted)]" />
            <div>
              <span className="text-[var(--text-primary)] font-medium">
                {t('settings.init.resources')}
              </span>
              <p className="text-sm text-[var(--text-secondary)]">
                {status.resources_installed
                  ? t('settings.init.resourcesInstalled', {
                      version: status.resources_version || t('settings.init.unknownVersion'),
                    })
                  : t('settings.init.resourcesMissing')}
                {status.resources_update_available && (
                  <span className="ml-2 text-blue-600 dark:text-blue-400">
                    {t('settings.init.resourcesUpdate', {
                      version: status.current_frago_version,
                    })}
                  </span>
                )}
              </p>
            </div>
          </div>
          {status.resources_installed ? (
            status.resources_update_available ? (
              <AlertTriangle className="w-5 h-5 text-blue-600 dark:text-blue-400" />
            ) : (
              <CheckCircle className="w-5 h-5 text-green-600 dark:text-green-400" />
            )
          ) : (
            <XCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
          )}
        </div>

        {/* Auth */}
        <div className="flex items-center justify-between p-3 bg-[var(--bg-subtle)] rounded-lg">
          <div className="flex items-center gap-3">
            <Shield className="w-5 h-5 text-[var(--text-muted)]" />
            <div>
              <span className="text-[var(--text-primary)] font-medium">
                {t('settings.init.auth')}
              </span>
              <p className="text-sm text-[var(--text-secondary)]">
                {status.auth_configured
                  ? status.auth_method === 'official'
                    ? t('settings.init.authOfficial')
                    : t('settings.init.authCustom')
                  : t('settings.init.authMissing')}
              </p>
            </div>
          </div>
          {status.auth_configured ? (
            <CheckCircle className="w-5 h-5 text-green-600 dark:text-green-400" />
          ) : (
            <AlertTriangle className="w-5 h-5 text-yellow-600 dark:text-yellow-400" />
          )}
        </div>
      </div>

      <div className="flex items-center justify-between pt-4 border-t border-[var(--border-color)]">
        <span className="text-sm text-[var(--text-muted)]">
          {status.init_completed
            ? t('settings.init.setupDone')
            : t('settings.init.setupPending')}
        </span>

        <button
          type="button"
          onClick={handleReset}
          disabled={resetting}
          className="btn btn-primary btn-sm flex items-center gap-2 disabled:opacity-50"
        >
          {resetting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              {t('settings.init.opening')}
            </>
          ) : (
            <>
              <PlayCircle className="w-4 h-4" />
              {t('settings.init.runWizard')}
            </>
          )}
        </button>
      </div>
    </div>
  );
}
