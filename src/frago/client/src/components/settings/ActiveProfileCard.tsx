/**
 * Active Profile Card Component
 * Displays details of the currently active API profile
 */

import { useTranslation } from 'react-i18next';
import { Check, KeyRound, RefreshCw } from 'lucide-react';
import type { ProfileItem } from '@/api';

interface ActiveProfileCardProps {
  profile: ProfileItem;
  /** Display names of the agent CLIs this profile was written into. */
  activeTargets?: string[];
  onChangeTargets?: () => void;
  onSwitch: () => void;
  onDeactivate: () => void;
}

export default function ActiveProfileCard({
  profile,
  activeTargets = [],
  onChangeTargets,
  onSwitch,
  onDeactivate,
}: ActiveProfileCardProps) {
  const { t } = useTranslation();

  // Get endpoint type display name
  const getEndpointTypeName = (type: string): string => {
    const typeNames: Record<string, string> = {
      deepseek: 'DeepSeek API',
      aliyun: 'Aliyun API',
      kimi: 'Kimi API',
      minimax: 'MiniMax API',
      custom: 'Custom URL',
    };
    return typeNames[type] || type;
  };

  const anthropicChannel = profile.channels?.find((c) => c.protocol === 'anthropic' && !!c.url);
  const responsesChannel = profile.channels?.find((c) => c.protocol === 'responses' && !!c.url);
  const codexReady = Boolean(responsesChannel);
  const endpointDisplay =
    profile.url || anthropicChannel?.url || getEndpointTypeName(profile.endpoint_type);
  const defaultModel = profile.default_model || profile.sonnet_model || null;
  const haikuModel = profile.haiku_model || defaultModel;

  return (
    <div className="s-card sel">
      <div className="hd">
        <span className="ico">
          <KeyRound size={15} />
        </span>
        <div>
          <div className="nm">
            <span>{profile.name}</span>
            {codexReady && (
              <span className="s-kind">{t('settings.profiles.codexReady')}</span>
            )}
          </div>
          <div className="ds">{t('settings.profiles.activeProfileDesc')}</div>
        </div>
        <span className="s-pill">
          <Check size={12} />
          {activeTargets.length > 0
            ? `${t('settings.profiles.activeOn')} ${activeTargets.join(', ')}`
            : t('settings.profiles.active')}
        </span>
      </div>

      <div className="bd">
        <div className="kvgrid">
          <div className="k">{t('settings.general.endpoint')}</div>
          <div className="v mono">{endpointDisplay}</div>

          {responsesChannel?.url && (
            <>
              <div className="k">{t('settings.profiles.responsesUrl')}</div>
              <div className="v mono">
                {responsesChannel.url}
                {responsesChannel.models?.[0] ? ` (${responsesChannel.models[0]})` : ''}
              </div>
            </>
          )}

          {profile.api_key_masked && (
            <>
              <div className="k">{t('settings.profiles.apiKey')}</div>
              <div className="v mono">{profile.api_key_masked}</div>
            </>
          )}

          {defaultModel && (
            <>
              <div className="k">{t('settings.profiles.defaultAndHaiku')}</div>
              <div className="v mono">
                {haikuModel && haikuModel !== defaultModel
                  ? `${defaultModel} · ${haikuModel}`
                  : `${defaultModel} · ${defaultModel}`}
              </div>
            </>
          )}

          {profile.context_window != null && (
            <>
              <div className="k">{t('settings.profiles.contextWindowLabel')}</div>
              <div className="v mono">
                {t('settings.profiles.tokensUnit', {
                  value: profile.context_window.toLocaleString(),
                })}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="row" style={{ justifyContent: 'flex-end', gap: '8px' }}>
        {onChangeTargets && (
          <button type="button" onClick={onChangeTargets} className="btn btn-sm">
            {t('settings.profiles.changeTargets')}
          </button>
        )}
        <button type="button" onClick={onSwitch} className="btn btn-sm">
          <RefreshCw size={13} />
          {t('settings.profiles.switchProfile')}
        </button>
        <button
          type="button"
          onClick={onDeactivate}
          className="btn btn-sm btn-danger-outline"
        >
          {t('settings.profiles.deactivate')}
        </button>
      </div>
    </div>
  );
}
