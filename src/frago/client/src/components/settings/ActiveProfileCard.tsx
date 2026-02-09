/**
 * Active Profile Card Component
 * Displays details of the currently active API profile
 */

import { useTranslation } from 'react-i18next';
import { RefreshCw, XCircle } from 'lucide-react';
import type { ProfileItem } from '@/api';

interface ActiveProfileCardProps {
  profile: ProfileItem;
  onSwitch: () => void;
  onDeactivate: () => void;
}

export default function ActiveProfileCard({ profile, onSwitch, onDeactivate }: ActiveProfileCardProps) {
  const { t } = useTranslation();

  // Get endpoint type display name
  const getEndpointTypeName = (type: string): string => {
    const typeNames: Record<string, string> = {
      'deepseek': 'DeepSeek API',
      'aliyun': 'Aliyun API',
      'kimi': 'Kimi API',
      'minimax': 'MiniMax API',
      'custom': 'Custom URL'
    };
    return typeNames[type] || type;
  };

  return (
    <div className="bg-[var(--bg-card)] rounded-lg border-2 border-[var(--accent-success)] p-4">
      <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3 flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-[var(--accent-success)]" />
        {t('settings.profiles.activeProfileTitle')}
      </h3>

      <div className="space-y-2 mb-4">
        <div className="flex items-center gap-2">
          <p className="text-base font-medium text-[var(--text-primary)]">
            {profile.name}
          </p>
          <span className="px-2 py-0.5 bg-[var(--accent-success)] bg-opacity-10 text-[var(--accent-success)] text-xs font-medium rounded">
            {t('settings.profiles.active')}
          </span>
        </div>

        <div className="space-y-1 text-xs text-[var(--text-secondary)]">
          <p>
            <span className="font-medium">{t('settings.general.endpoint')}:</span>{' '}
            {getEndpointTypeName(profile.endpoint_type)}
          </p>
          <p>
            <span className="font-medium">{t('settings.profiles.apiKey')}:</span>{' '}
            <span className="font-mono">{profile.api_key_masked}</span>
          </p>
          {profile.sonnet_model && (
            <p>
              <span className="font-medium">{t('settings.general.model')}:</span>{' '}
              {profile.sonnet_model}
            </p>
          )}
        </div>
      </div>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={onSwitch}
          className="btn btn-ghost btn-sm flex items-center gap-1"
        >
          <RefreshCw size={16} />
          {t('settings.profiles.switchProfile')}
        </button>
        <button
          type="button"
          onClick={onDeactivate}
          className="btn btn-ghost btn-sm flex items-center gap-1 text-[var(--text-error)]"
        >
          <XCircle size={16} />
          {t('settings.profiles.deactivate')}
        </button>
      </div>
    </div>
  );
}
