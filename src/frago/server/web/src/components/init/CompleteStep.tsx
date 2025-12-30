/**
 * CompleteStep - Final step to finish initialization
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CheckCircle,
  XCircle,
  ArrowLeft,
  Loader2,
  PartyPopper,
  AlertTriangle,
} from 'lucide-react';
import type { InitStatus } from '../../api/client';
import { markInitComplete } from '../../api/client';

interface CompleteStepProps {
  initStatus: InitStatus;
  stepsCompleted: {
    dependencies: boolean;
    resources: boolean;
    auth: boolean;
    complete: boolean;
  };
  onComplete: () => void;
  onBack: () => void;
}

export function CompleteStep({
  initStatus,
  stepsCompleted,
  onComplete,
  onBack,
}: CompleteStepProps) {
  const { t } = useTranslation();
  const [completing, setCompleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allStepsComplete =
    stepsCompleted.dependencies &&
    stepsCompleted.resources &&
    stepsCompleted.auth;

  const handleComplete = async () => {
    setCompleting(true);
    setError(null);

    try {
      const result = await markInitComplete();
      if (result.status === 'ok') {
        onComplete();
      } else {
        setError(result.message || 'Failed to complete initialization');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to complete initialization');
    } finally {
      setCompleting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="text-center">
        <PartyPopper className="w-12 h-12 text-yellow-400 mx-auto mb-4" />
        <h3 className="text-xl font-semibold text-white mb-2">
          {allStepsComplete ? t('init.allSet') : t('init.almostThere')}
        </h3>
        <p className="text-gray-400">
          {allStepsComplete
            ? t('init.readyToUse')
            : t('init.reviewSummary')}
        </p>
      </div>

      {/* Setup summary */}
      <div className="bg-gray-800 rounded-lg p-4 space-y-3">
        <h4 className="font-medium text-white mb-3">{t('init.compSummary')}</h4>

        {/* Dependencies */}
        <div className="flex items-center gap-3">
          {stepsCompleted.dependencies ? (
            <CheckCircle className="w-5 h-5 text-green-400 flex-shrink-0" />
          ) : (
            <XCircle className="w-5 h-5 text-red-400 flex-shrink-0" />
          )}
          <div>
            <span className="text-white">{t('settings.init.dependencies')}</span>
            <span className="text-gray-400 text-sm ml-2">
              {stepsCompleted.dependencies
                ? `Node.js ${initStatus.node.version}, Claude Code ${initStatus.claude_code.version}`
                : t('init.notFullyConfigured')}
            </span>
          </div>
        </div>

        {/* Resources */}
        <div className="flex items-center gap-3">
          {stepsCompleted.resources ? (
            <CheckCircle className="w-5 h-5 text-green-400 flex-shrink-0" />
          ) : (
            <XCircle className="w-5 h-5 text-red-400 flex-shrink-0" />
          )}
          <div>
            <span className="text-white">{t('settings.init.resources')}</span>
            <span className="text-gray-400 text-sm ml-2">
              {stepsCompleted.resources
                ? `v${initStatus.resources_version || initStatus.current_frago_version}`
                : t('init.notInstalled')}
            </span>
          </div>
        </div>

        {/* Auth */}
        <div className="flex items-center gap-3">
          {stepsCompleted.auth ? (
            <CheckCircle className="w-5 h-5 text-green-400 flex-shrink-0" />
          ) : (
            <AlertTriangle className="w-5 h-5 text-yellow-400 flex-shrink-0" />
          )}
          <div>
            <span className="text-white">{t('settings.init.auth')}</span>
            <span className="text-gray-400 text-sm ml-2">
              {stepsCompleted.auth
                ? initStatus.auth_method === 'official'
                  ? t('init.officialUserManaged')
                  : t('init.customEndpoint')
                : t('init.configureInSettings')}
            </span>
          </div>
        </div>
      </div>

      {/* Warning if not all complete */}
      {!allStepsComplete && (
        <div className="bg-yellow-900/20 border border-yellow-800/50 rounded-lg p-4 text-sm text-yellow-300 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 flex-shrink-0 mt-0.5" />
          <div>
            <p className="font-medium mb-1">{t('init.stepsSkippedTitle')}</p>
            <p>{t('init.stepsSkippedDesc')}</p>
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

        <button
          type="button"
          onClick={handleComplete}
          disabled={completing}
          className="flex items-center gap-2 px-6 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium"
        >
          {completing ? (
            <>
              <Loader2 className="w-5 h-5 animate-spin" />
              {t('init.finishing')}
            </>
          ) : (
            <>
              <CheckCircle className="w-5 h-5" />
              {t('init.finishSetup')}
            </>
          )}
        </button>
      </div>
    </div>
  );
}
