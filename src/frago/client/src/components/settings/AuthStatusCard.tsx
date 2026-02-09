/**
 * Authentication Status Card Component
 * Displays current authentication method and API endpoint configuration
 */

import { useTranslation } from 'react-i18next';
import { Layers } from 'lucide-react';

interface APIEndpointConfig {
  type: string;
  url?: string;
  api_key?: string;
  default_model?: string;
  sonnet_model?: string;
  haiku_model?: string;
}

interface AuthStatusCardProps {
  authMethod: 'official' | 'custom';
  apiEndpoint?: APIEndpointConfig | null;
  onManageProfiles: () => void;
}

export default function AuthStatusCard({ authMethod, apiEndpoint, onManageProfiles }: AuthStatusCardProps) {
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
    <div className="bg-[var(--bg-card)] rounded-lg border border-[var(--border-color)] p-4">
      <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
        {t('settings.general.authenticationStatus')}
      </h3>

      <div className="space-y-2 mb-4">
        {authMethod === 'official' ? (
          <div className="flex items-start gap-2">
            <div className="w-2 h-2 rounded-full bg-[var(--accent-primary)] mt-1.5 shrink-0" />
            <p className="text-sm text-[var(--text-primary)]">
              {t('settings.general.usingOfficialApi')}
            </p>
          </div>
        ) : (
          <>
            <div className="flex items-start gap-2">
              <div className="w-2 h-2 rounded-full bg-[var(--accent-primary)] mt-1.5 shrink-0" />
              <p className="text-sm text-[var(--text-primary)]">
                {t('settings.general.usingCustomApi')}
              </p>
            </div>
            {apiEndpoint && (
              <div className="ml-4 space-y-1 text-xs text-[var(--text-secondary)]">
                <p>
                  <span className="font-medium">{t('settings.general.endpoint')}:</span>{' '}
                  {getEndpointTypeName(apiEndpoint.type)}
                </p>
                {apiEndpoint.sonnet_model && (
                  <p>
                    <span className="font-medium">{t('settings.general.model')}:</span>{' '}
                    {apiEndpoint.sonnet_model}
                  </p>
                )}
              </div>
            )}
          </>
        )}
      </div>

      <button
        type="button"
        onClick={onManageProfiles}
        className="btn btn-ghost btn-sm flex items-center gap-1"
      >
        <Layers size={16} />
        {t('settings.general.manageProfiles')}
      </button>
    </div>
  );
}
