/**
 * InitSettings - Initialization status card for Settings page
 *
 * Shows current init status and allows re-running the wizard.
 */

import { useEffect, useState } from 'react';
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
} from 'lucide-react';
import type { InitStatus } from '../../api/client';
import { getInitStatus, resetInitStatus } from '../../api/client';

interface InitSettingsProps {
  onOpenWizard: () => void;
}

export function InitSettings({ onOpenWizard }: InitSettingsProps) {
  const [status, setStatus] = useState<InitStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadStatus();
  }, []);

  const loadStatus = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getInitStatus();
      setStatus(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load status');
    } finally {
      setLoading(false);
    }
  };

  const handleReset = async () => {
    setResetting(true);
    try {
      await resetInitStatus();
      onOpenWizard();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reset');
    } finally {
      setResetting(false);
    }
  };

  if (loading) {
    return (
      <div className="card p-6">
        <div className="flex items-center gap-3 text-[var(--text-muted)]">
          <Loader2 className="w-5 h-5 animate-spin" />
          Loading initialization status...
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
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  if (!status) return null;

  const depsOk =
    status.node.installed &&
    status.node.version_sufficient &&
    status.claude_code.installed &&
    status.claude_code.version_sufficient;

  return (
    <div className="card space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-[var(--accent-primary)]">Initialization Status</h2>
        <button
          type="button"
          onClick={loadStatus}
          className="p-2 text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-subtle)] rounded-lg transition-colors"
          aria-label="Refresh status"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Status items */}
      <div className="space-y-3">
        {/* Dependencies */}
        <div className="flex items-center justify-between p-3 bg-[var(--bg-subtle)] rounded-lg">
          <div className="flex items-center gap-3">
            <Cpu className="w-5 h-5 text-[var(--text-muted)]" />
            <div>
              <span className="text-[var(--text-primary)] font-medium">Dependencies</span>
              <p className="text-sm text-[var(--text-secondary)]">
                Node.js {status.node.version || 'N/A'}, Claude Code {status.claude_code.version || 'N/A'}
              </p>
            </div>
          </div>
          {depsOk ? (
            <CheckCircle className="w-5 h-5 text-green-600 dark:text-green-400" />
          ) : (
            <AlertTriangle className="w-5 h-5 text-yellow-600 dark:text-yellow-400" />
          )}
        </div>

        {/* Resources */}
        <div className="flex items-center justify-between p-3 bg-[var(--bg-subtle)] rounded-lg">
          <div className="flex items-center gap-3">
            <Package className="w-5 h-5 text-[var(--text-muted)]" />
            <div>
              <span className="text-[var(--text-primary)] font-medium">Resources</span>
              <p className="text-sm text-[var(--text-secondary)]">
                {status.resources_installed
                  ? `v${status.resources_version || 'unknown'}`
                  : 'Not installed'}
                {status.resources_update_available && (
                  <span className="ml-2 text-blue-600 dark:text-blue-400">
                    (update available: v{status.current_frago_version})
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
              <span className="text-[var(--text-primary)] font-medium">Authentication</span>
              <p className="text-sm text-[var(--text-secondary)]">
                {status.auth_configured
                  ? status.auth_method === 'official'
                    ? 'Official (user-managed)'
                    : 'Custom API endpoint'
                  : 'Not configured'}
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

      {/* Actions */}
      <div className="flex items-center justify-between pt-4 border-t border-[var(--border-color)]">
        <span className="text-sm text-[var(--text-muted)]">
          {status.init_completed
            ? 'Setup completed'
            : 'Setup not completed'}
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
              Opening...
            </>
          ) : (
            <>
              <PlayCircle className="w-4 h-4" />
              Run Setup Wizard
            </>
          )}
        </button>
      </div>
    </div>
  );
}
