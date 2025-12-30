/**
 * ResourceStep - Install commands, skills, and recipes
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CheckCircle,
  XCircle,
  Loader2,
  Download,
  RefreshCw,
  ArrowRight,
  ArrowLeft,
  Package,
  Zap,
  BookOpen,
} from 'lucide-react';
import type { InitStatus, ResourceInstallResult } from '../../api/client';
import { installResources } from '../../api/client';

interface ResourceStepProps {
  initStatus: InitStatus;
  onComplete: () => void;
  onSkip: () => void;
  onBack: () => void;
  onRefresh: () => void;
}

export function ResourceStep({
  initStatus,
  onComplete,
  onSkip,
  onBack,
  onRefresh,
}: ResourceStepProps) {
  const { t } = useTranslation();
  const [installing, setInstalling] = useState(false);
  const [installResult, setInstallResult] = useState<ResourceInstallResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [forceUpdate, setForceUpdate] = useState(false);

  const resourcesInstalled = initStatus.resources_installed;
  const updateAvailable = initStatus.resources_update_available;

  const handleInstall = async () => {
    setInstalling(true);
    setError(null);
    setInstallResult(null);

    try {
      const result = await installResources(forceUpdate);
      setInstallResult(result);

      if (result.status === 'ok' || result.status === 'partial') {
        onRefresh();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Installation failed');
    } finally {
      setInstalling(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h3 className="text-lg font-semibold text-white mb-2">
          {t('init.resTitle')}
        </h3>
        <p className="text-gray-400">
          {t('init.resDesc')}
        </p>
      </div>

      {/* Current status */}
      <div className="bg-gray-800 rounded-lg p-4 space-y-3">
        <div className="flex items-center gap-3">
          {resourcesInstalled ? (
            <CheckCircle className="w-5 h-5 text-green-400" />
          ) : (
            <XCircle className="w-5 h-5 text-gray-500" />
          )}
          <div>
            <h4 className="font-medium text-white">{t('init.resourcesStatus')}</h4>
            <p className="text-sm text-gray-400">
              {resourcesInstalled
                ? t('init.resourcesInstalled', { version: initStatus.resources_version || 'unknown' })
                : t('init.resourcesNotInstalled')}
              {updateAvailable && (
                <span className="ml-2 text-blue-400">
                  {t('init.updateAvailable', { version: initStatus.current_frago_version })}
                </span>
              )}
            </p>
          </div>
        </div>

        {/* Resource types */}
        <div className="grid grid-cols-3 gap-3 mt-4">
          <div className="flex items-center gap-2 text-gray-400">
            <Package className="w-4 h-4" />
            <span className="text-sm">
              {initStatus.resources_info?.commands?.installed || 0} {t('init.commands')}
            </span>
          </div>
          <div className="flex items-center gap-2 text-gray-400">
            <Zap className="w-4 h-4" />
            <span className="text-sm">{t('skills.title')}</span>
          </div>
          <div className="flex items-center gap-2 text-gray-400">
            <BookOpen className="w-4 h-4" />
            <span className="text-sm">
              {initStatus.resources_info?.recipes?.installed || 0} {t('recipes.title')}
            </span>
          </div>
        </div>
      </div>

      {/* Force update option */}
      {resourcesInstalled && (
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={forceUpdate}
            onChange={(e) => setForceUpdate(e.target.checked)}
            className="w-4 h-4 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-blue-500"
          />
          <span className="text-sm text-gray-400">
            {t('init.forceUpdate')}
          </span>
        </label>
      )}

      {/* Install button */}
      <button
        type="button"
        onClick={handleInstall}
        disabled={installing}
        className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors w-full justify-center"
      >
        {installing ? (
          <>
            <Loader2 className="w-5 h-5 animate-spin" />
            {t('init.installingResources')}
          </>
        ) : resourcesInstalled && !updateAvailable ? (
          <>
            <RefreshCw className="w-5 h-5" />
            {t('init.reinstallResources')}
          </>
        ) : updateAvailable ? (
          <>
            <Download className="w-5 h-5" />
            {t('init.updateResources')}
          </>
        ) : (
          <>
            <Download className="w-5 h-5" />
            {t('init.installResources')}
          </>
        )}
      </button>

      {/* Install result */}
      {installResult && (
        <div
          className={`p-4 rounded-lg ${
            installResult.status === 'ok'
              ? 'bg-green-900/30 border border-green-800'
              : installResult.status === 'partial'
                ? 'bg-yellow-900/30 border border-yellow-800'
                : 'bg-red-900/30 border border-red-800'
          }`}
        >
          <div className="flex items-center gap-2 mb-2">
            {installResult.status === 'ok' ? (
              <CheckCircle className="w-5 h-5 text-green-400" />
            ) : installResult.status === 'partial' ? (
              <RefreshCw className="w-5 h-5 text-yellow-400" />
            ) : (
              <XCircle className="w-5 h-5 text-red-400" />
            )}
            <span
              className={`font-medium ${
                installResult.status === 'ok'
                  ? 'text-green-300'
                  : installResult.status === 'partial'
                    ? 'text-yellow-300'
                    : 'text-red-300'
              }`}
            >
              {installResult.status === 'ok'
                ? t('init.installComplete')
                : installResult.status === 'partial'
                  ? t('init.installPartial')
                  : t('init.installFailed')}
            </span>
          </div>

          <div className="text-sm text-gray-300 space-y-1">
            <p>{t('init.filesInstalled', { count: installResult.total_installed })}</p>
            {installResult.total_skipped > 0 && (
              <p>{t('init.filesSkipped', { count: installResult.total_skipped })}</p>
            )}
            {installResult.errors.length > 0 && (
              <div className="mt-2">
                <p className="text-red-400">{t('init.errorsLabel')}</p>
                <ul className="list-disc list-inside text-red-300">
                  {installResult.errors.map((err, i) => (
                    <li key={i}>{err}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="p-4 bg-red-900/30 border border-red-800 rounded-lg text-red-300">
          {error}
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center justify-between pt-4 border-t border-gray-800">
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-2 text-gray-400 hover:text-gray-300"
        >
          <ArrowLeft className="w-4 h-4" />
          {t('init.back')}
        </button>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onSkip}
            className="text-gray-400 hover:text-gray-300 text-sm"
          >
            {t('init.skip')}
          </button>

          <button
            type="button"
            onClick={onComplete}
            disabled={!resourcesInstalled && !installResult}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {t('init.continue')}
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
