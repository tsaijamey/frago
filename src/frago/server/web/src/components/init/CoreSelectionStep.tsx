/**
 * CoreSelectionStep - Select Core Type for Init Wizard
 *
 * Select between Claude Code (official) or OpenCode (third-party)
 * OpenCode is currently disabled with "Coming Soon" badge
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Check,
  Sparkles,
  Globe,
  Terminal,
  ChevronRight,
  Clock,
} from 'lucide-react';

type CoreType = 'claude-code' | 'opencode' | null;

interface CoreSelectionStepProps {
  onComplete: (coreType: 'claude-code' | 'opencode') => void;
  onSkip: () => void;
}

export function CoreSelectionStep({ onComplete, onSkip }: CoreSelectionStepProps) {
  const { t } = useTranslation();
  const [coreType, setCoreType] = useState<CoreType>(null);

  const handleCoreSelect = (type: CoreType) => {
    // Only allow claude-code for now
    if (type === 'claude-code') {
      setCoreType(type);
    }
  };

  const handleContinue = () => {
    if (coreType) {
      onComplete(coreType);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h3 className="text-lg font-semibold text-white mb-2 font-mono">
          {t('init.coreSelection.title')}
        </h3>
        <p className="text-gray-400 font-mono text-sm">
          {t('init.coreSelection.description')}
        </p>
      </div>

      {/* Core Type Selection */}
      <div className="grid grid-cols-2 gap-4">
        {/* Claude Code Card */}
        <button
          type="button"
          onClick={() => handleCoreSelect('claude-code')}
          className={`relative p-6 rounded-lg border-2 transition-all text-left ${
            coreType === 'claude-code'
              ? 'border-green-500 bg-green-500/10'
              : 'border-gray-700 bg-gray-800/50 hover:border-gray-600 hover:bg-gray-800'
          }`}
        >
          {/* Recommended badge */}
          <div className="absolute -top-2 -right-2 px-2 py-0.5 bg-green-500 text-black text-xs font-bold rounded font-mono">
            {t('init.coreSelection.recommended')}
          </div>

          <div className="flex items-center gap-3 mb-4">
            <div className="w-12 h-12 rounded-lg bg-gradient-to-br from-orange-400 to-orange-600 flex items-center justify-center">
              <Terminal className="w-6 h-6 text-white" />
            </div>
            <div>
              <h4 className="text-white font-semibold font-mono flex items-center gap-2">
                Claude Code
                {coreType === 'claude-code' && (
                  <Check className="w-4 h-4 text-green-400" />
                )}
              </h4>
              <p className="text-gray-400 text-xs font-mono">Anthropic Official</p>
            </div>
          </div>

          <p className="text-gray-300 text-sm mb-4">
            {t('init.coreSelection.claudeCodeFeatures')}
          </p>

          <div className="flex items-center gap-2 text-green-400 text-sm font-mono">
            <Sparkles className="w-4 h-4" />
            <span>{t('init.coreSelection.fullFeatures')}</span>
          </div>
        </button>

        {/* OpenCode Card - Disabled */}
        <div
          className="relative p-6 rounded-lg border-2 border-gray-700 bg-gray-800/30 text-left opacity-60 cursor-not-allowed"
        >
          {/* Coming Soon badge */}
          <div className="absolute -top-2 -right-2 px-2 py-0.5 bg-gray-600 text-gray-300 text-xs font-bold rounded font-mono flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {t('init.coreSelection.comingSoon')}
          </div>

          <div className="flex items-center gap-3 mb-4">
            <div className="w-12 h-12 rounded-lg bg-gradient-to-br from-blue-400 to-purple-600 flex items-center justify-center">
              <Globe className="w-6 h-6 text-white" />
            </div>
            <div>
              <h4 className="text-gray-400 font-semibold font-mono">OpenCode</h4>
              <p className="text-gray-500 text-xs font-mono">Open Ecosystem</p>
            </div>
          </div>

          <p className="text-gray-500 text-sm mb-4">
            {t('init.coreSelection.openCodeFeatures')}
          </p>

          <div className="flex items-center gap-2 text-gray-500 text-sm font-mono">
            <Globe className="w-4 h-4" />
            <span>{t('init.coreSelection.thirdPartyAPIs')}</span>
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between pt-4 border-t border-gray-800">
        <button
          type="button"
          onClick={onSkip}
          className="text-gray-400 hover:text-gray-300 text-sm font-mono"
        >
          {t('init.skipForNow')}
        </button>

        <button
          type="button"
          onClick={handleContinue}
          disabled={!coreType}
          className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-mono"
        >
          {t('init.continue')}
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
