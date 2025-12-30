/**
 * DependencyStep - Check and install Node.js and Claude Code
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  Loader2,
  Download,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  ArrowRight,
} from 'lucide-react';
import type { InitStatus, DependencyStatus } from '../../api/client';
import { installDependency, checkDependencies } from '../../api/client';

interface DependencyStepProps {
  initStatus: InitStatus;
  onComplete: () => void;
  onSkip: () => void;
  onRefresh: () => void;
}

interface DependencyCardProps {
  dep: DependencyStatus;
  onInstall: () => Promise<void>;
  installing: boolean;
  t: (key: string, options?: Record<string, unknown>) => string;
}

function DependencyCard({ dep, onInstall, installing, t }: DependencyCardProps) {
  const [showGuide, setShowGuide] = useState(false);
  const [installError, setInstallError] = useState<string | null>(null);

  const isOk = dep.installed && dep.version_sufficient;
  const needsUpgrade = dep.installed && !dep.version_sufficient;

  const handleInstall = async () => {
    setInstallError(null);
    try {
      await onInstall();
    } catch (err) {
      setInstallError(err instanceof Error ? err.message : 'Installation failed');
    }
  };

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          {isOk ? (
            <CheckCircle className="w-5 h-5 text-green-400" />
          ) : needsUpgrade ? (
            <AlertTriangle className="w-5 h-5 text-yellow-400" />
          ) : (
            <XCircle className="w-5 h-5 text-red-400" />
          )}
          <div>
            <h4 className="font-medium text-white capitalize">
              {dep.name === 'claude-code' ? 'Claude Code' : 'Node.js'}
            </h4>
            <p className="text-sm text-gray-400">
              {dep.installed
                ? t('init.versionCurrent', { version: dep.version })
                : t('init.notInstalled')}
              {dep.installed && !dep.version_sufficient && (
                <span className="text-yellow-400 ml-2">
                  ({t('init.versionRequired', { version: dep.required_version })})
                </span>
              )}
            </p>
          </div>
        </div>

        {!isOk && (
          <button
            type="button"
            onClick={handleInstall}
            disabled={installing}
            className="flex items-center gap-2 px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm"
          >
            {installing ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {t('init.installing')}
              </>
            ) : (
              <>
                <Download className="w-4 h-4" />
                {t('init.install')}
              </>
            )}
          </button>
        )}
      </div>

      {/* Error message */}
      {installError && (
        <div className="mt-2 p-2 bg-red-900/30 border border-red-800 rounded text-red-300 text-sm">
          {installError}
        </div>
      )}

      {/* Install guide toggle */}
      {!isOk && dep.install_guide && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setShowGuide(!showGuide)}
            className="flex items-center gap-1 text-sm text-gray-400 hover:text-gray-300"
          >
            {showGuide ? (
              <ChevronUp className="w-4 h-4" />
            ) : (
              <ChevronDown className="w-4 h-4" />
            )}
            {t('init.manualGuide')}
          </button>

          {showGuide && (
            <pre className="mt-2 p-3 bg-gray-900 rounded text-sm text-gray-300 overflow-x-auto whitespace-pre-wrap">
              {dep.install_guide}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

export function DependencyStep({
  initStatus,
  onComplete,
  onSkip,
  onRefresh,
}: DependencyStepProps) {
  const { t } = useTranslation();
  const [checking, setChecking] = useState(false);
  const [installingNode, setInstallingNode] = useState(false);
  const [installingClaude, setInstallingClaude] = useState(false);

  const nodeOk =
    initStatus.node.installed && initStatus.node.version_sufficient;
  const claudeOk =
    initStatus.claude_code.installed && initStatus.claude_code.version_sufficient;
  const allOk = nodeOk && claudeOk;

  const handleRefreshCheck = async () => {
    setChecking(true);
    try {
      await checkDependencies();
      onRefresh();
    } finally {
      setChecking(false);
    }
  };

  const handleInstallNode = async () => {
    setInstallingNode(true);
    try {
      const result = await installDependency('node');
      if (result.status === 'ok') {
        onRefresh();
      } else {
        throw new Error(result.message);
      }
    } finally {
      setInstallingNode(false);
    }
  };

  const handleInstallClaude = async () => {
    setInstallingClaude(true);
    try {
      const result = await installDependency('claude-code');
      if (result.status === 'ok') {
        onRefresh();
      } else {
        throw new Error(result.message);
      }
    } finally {
      setInstallingClaude(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h3 className="text-lg font-semibold text-white mb-2">
          {t('init.systemDeps')}
        </h3>
        <p className="text-gray-400">
          {t('init.systemDepsDesc')}
        </p>
      </div>

      {/* Dependency cards */}
      <div className="space-y-3">
        <DependencyCard
          dep={initStatus.node}
          onInstall={handleInstallNode}
          installing={installingNode}
          t={t}
        />
        <DependencyCard
          dep={initStatus.claude_code}
          onInstall={handleInstallClaude}
          installing={installingClaude}
          t={t}
        />
      </div>

      {/* Refresh button */}
      <button
        type="button"
        onClick={handleRefreshCheck}
        disabled={checking}
        className="flex items-center gap-2 text-sm text-gray-400 hover:text-gray-300"
      >
        <RefreshCw className={`w-4 h-4 ${checking ? 'animate-spin' : ''}`} />
        {checking ? t('init.checking') : t('init.refreshStatus')}
      </button>

      {/* Actions */}
      <div className="flex items-center justify-between pt-4 border-t border-gray-800">
        <button
          type="button"
          onClick={onSkip}
          className="text-gray-400 hover:text-gray-300 text-sm"
        >
          {t('init.skipForNow')}
        </button>

        <button
          type="button"
          onClick={onComplete}
          disabled={!allOk}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {t('init.continue')}
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>

      {/* Warning if skipping */}
      {!allOk && (
        <p className="text-sm text-yellow-400 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" />
          {t('init.skipWarning')}
        </p>
      )}
    </div>
  );
}
