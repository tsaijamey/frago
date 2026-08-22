/**
 * AuthMethodStep - Select Authentication Method
 *
 * For Claude Code users:
 * - Official Login (user manages their own Claude login)
 * - Custom API Endpoint (use third-party API providers)
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ArrowLeft,
  Check,
  Terminal,
  Server,
  Key,
  ChevronRight,
  Eye,
  EyeOff,
} from 'lucide-react';
import { getEndpointPresets } from '@/api';

/**
 * This grid used to be a hand-written copy of the backend's endpoint table,
 * and it had gone wrong in both directions: the Tencent endpoints were absent,
 * and every model name under a provider tile named a model that had since been
 * replaced. The names now come from the backend, which is the same place the
 * settings file is built from, so the tile can no longer promise one model and
 * configure another. Only the tile colours stay local — they are decoration.
 */
const PRESET_COLORS: Record<string, string> = {
  deepseek: '#4B7BF5',
  aliyun: '#FF6A00',
  kimi: '#00D4AA',
  minimax: '#9B59B6',
  tencent_maas: '#00A4FF',
  tencent_tokenplan: '#0052D9',
  custom: '#6B7280',
};

interface EndpointChoice {
  id: string;
  name: string;
  model: string;
}

type AuthMethod = 'official' | 'custom' | null;
type EndpointType = string | null;

interface ApiConfig {
  apiKey: string;
  url?: string;
  defaultModel?: string;
}

interface AuthMethodStepProps {
  coreType: 'claude-code' | 'opencode';
  onComplete: (authMethod: 'official' | 'custom', endpointType?: string, apiConfig?: ApiConfig) => void;
  onBack: () => void;
  onSkip: () => void;
}

export function AuthMethodStep({ coreType, onComplete, onBack, onSkip }: AuthMethodStepProps) {
  const { t } = useTranslation();
  const [authMethod, setAuthMethod] = useState<AuthMethod>(null);
  const [endpointType, setEndpointType] = useState<EndpointType>(null);

  // API key configuration state
  const [apiKey, setApiKey] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);
  const [customUrl, setCustomUrl] = useState('');
  const [defaultModel, setDefaultModel] = useState('');
  const [configLater, setConfigLater] = useState(false);
  const [endpoints, setEndpoints] = useState<EndpointChoice[]>([]);

  useEffect(() => {
    getEndpointPresets()
      .then((data) =>
        setEndpoints([
          ...data.presets.map((p) => ({
            id: p.id,
            name: p.display_name,
            model: p.default_model,
          })),
          { id: 'custom', name: 'Custom', model: t('init.authMethod.customEndpointHint') },
        ]),
      )
      // Custom is always available and needs no table to describe it, so a
      // failed fetch still leaves the wizard completable.
      .catch(() =>
        setEndpoints([
          { id: 'custom', name: 'Custom', model: t('init.authMethod.customEndpointHint') },
        ]),
      );
  }, [t]);

  // For OpenCode, only custom API is available
  const showOfficialOption = coreType === 'claude-code';

  const handleAuthMethodSelect = (method: AuthMethod) => {
    setAuthMethod(method);
    if (method === 'official') {
      setEndpointType(null);
    }
  };

  const handleEndpointSelect = (endpoint: string) => {
    setEndpointType(endpoint);
    // Reset API config when switching endpoints
    setApiKey('');
    setCustomUrl('');
    setDefaultModel('');
    setConfigLater(false);
  };

  const handleContinue = () => {
    if (authMethod === 'official') {
      onComplete('official');
    } else if (authMethod === 'custom' && endpointType) {
      const apiConfig: ApiConfig | undefined = configLater
        ? undefined
        : {
            apiKey: apiKey.trim(),
            url: endpointType === 'custom' ? customUrl.trim() : undefined,
            defaultModel: endpointType === 'custom' ? defaultModel.trim() : undefined,
          };
      onComplete('custom', endpointType, apiConfig);
    }
  };

  const canContinue =
    authMethod === 'official' ||
    (authMethod === 'custom' && endpointType && (
      configLater ||
      (apiKey.trim() && (
        endpointType !== 'custom' ||
        (customUrl.trim() && defaultModel.trim())
      ))
    ));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h3 className="text-lg font-semibold text-white mb-2 font-mono">
          {t('init.authMethod.title')}
        </h3>
        <p className="text-gray-400 font-mono text-sm">
          {t('init.authMethod.description')}
        </p>
      </div>

      {/* Auth Method Selection */}
      <div className="space-y-3">
        {/* Official Login Option (only for Claude Code) */}
        {showOfficialOption && (
          <button
            type="button"
            onClick={() => handleAuthMethodSelect('official')}
            className={`w-full p-4 rounded-lg border-2 transition-all text-left ${
              authMethod === 'official'
                ? 'border-green-500 bg-green-500/10'
                : 'border-gray-700 bg-gray-800/50 hover:border-gray-600 hover:bg-gray-800'
            }`}
          >
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-orange-400 to-orange-600 flex items-center justify-center">
                <Terminal className="w-5 h-5 text-white" />
              </div>
              <div className="flex-1">
                <h4 className="text-white font-semibold font-mono flex items-center gap-2">
                  {t('init.authMethod.officialLogin')}
                  {authMethod === 'official' && (
                    <Check className="w-4 h-4 text-green-400" />
                  )}
                </h4>
                <p className="text-gray-400 text-sm">
                  {t('init.authMethod.officialLoginDesc')}
                </p>
              </div>
            </div>

            {authMethod === 'official' && (
              <div className="mt-3 p-3 bg-gray-900/50 rounded font-mono text-sm">
                <p className="text-gray-400 mb-2">{t('init.authMethod.loginHint')}</p>
                <code className="text-green-400">$ claude</code>
              </div>
            )}
          </button>
        )}

        {/* Custom API Option */}
        <button
          type="button"
          onClick={() => handleAuthMethodSelect('custom')}
          className={`w-full p-4 rounded-lg border-2 transition-all text-left ${
            authMethod === 'custom'
              ? 'border-blue-500 bg-blue-500/10'
              : 'border-gray-700 bg-gray-800/50 hover:border-gray-600 hover:bg-gray-800'
          }`}
        >
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-400 to-purple-600 flex items-center justify-center">
              <Server className="w-5 h-5 text-white" />
            </div>
            <div className="flex-1">
              <h4 className="text-white font-semibold font-mono flex items-center gap-2">
                {t('init.authMethod.customApi')}
                {authMethod === 'custom' && (
                  <Check className="w-4 h-4 text-blue-400" />
                )}
              </h4>
              <p className="text-gray-400 text-sm">
                {t('init.authMethod.customApiDesc')}
              </p>
            </div>
          </div>
        </button>
      </div>

      {/* API Provider Grid (shown when custom is selected) */}
      {authMethod === 'custom' && (
        <div className="space-y-4">
          <p className="text-sm text-gray-400 font-mono">
            {t('init.authMethod.selectProvider')}
          </p>
          <div className="grid grid-cols-3 gap-3">
            {endpoints.map((endpoint) => {
              const color = PRESET_COLORS[endpoint.id] ?? PRESET_COLORS.custom;
              return (
              <button
                key={endpoint.id}
                type="button"
                onClick={() => handleEndpointSelect(endpoint.id)}
                className={`p-4 rounded-lg border-2 transition-all text-left ${
                  endpointType === endpoint.id
                    ? 'border-blue-500 bg-blue-500/10'
                    : 'border-gray-700 bg-gray-800/50 hover:border-gray-600 hover:bg-gray-800'
                }`}
              >
                <div className="flex items-center gap-2 mb-2">
                  <div
                    className="w-8 h-8 rounded flex items-center justify-center"
                    style={{ backgroundColor: `${color}20` }}
                  >
                    {endpoint.id === 'custom' ? (
                      <Key className="w-4 h-4" style={{ color }} />
                    ) : (
                      <Server className="w-4 h-4" style={{ color }} />
                    )}
                  </div>
                  {endpointType === endpoint.id && (
                    <Check className="w-4 h-4 text-blue-400 ml-auto" />
                  )}
                </div>
                <h5 className="text-white font-medium font-mono text-sm">{endpoint.name}</h5>
                <p className="text-gray-500 text-xs font-mono truncate">{endpoint.model}</p>
              </button>
              );
            })}
          </div>

          {/* API Key Configuration Form */}
          {endpointType && (
            <div className="p-4 bg-gray-900/50 rounded-lg border border-gray-700 space-y-4">
              <h5 className="text-white font-medium font-mono text-sm">
                {t('init.authMethod.apiKeyConfig')}
              </h5>

              {/* API Key Input */}
              <div className="space-y-2">
                <label htmlFor="api-key" className="text-gray-400 text-sm font-mono">
                  API Key
                </label>
                <div className="relative">
                  <input
                    id="api-key"
                    type={showApiKey ? 'text' : 'password'}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={t('init.authMethod.enterApiKey')}
                    disabled={configLater}
                    className="w-full px-3 py-2 pr-16 bg-gray-800 border border-gray-600 rounded text-white font-mono text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
                  />
                  <button
                    type="button"
                    onClick={() => setShowApiKey(!showApiKey)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-300 px-2 py-1 text-xs font-mono"
                  >
                    {showApiKey ? (
                      <EyeOff className="w-4 h-4" />
                    ) : (
                      <Eye className="w-4 h-4" />
                    )}
                  </button>
                </div>
              </div>

              {/* Custom endpoint specific fields */}
              {endpointType === 'custom' && (
                <>
                  <div className="space-y-2">
                    <label htmlFor="api-url" className="text-gray-400 text-sm font-mono">
                      {t('init.authMethod.apiUrl')} *
                    </label>
                    <input
                      id="api-url"
                      type="text"
                      value={customUrl}
                      onChange={(e) => setCustomUrl(e.target.value)}
                      placeholder={t('init.authMethod.enterApiUrl')}
                      disabled={configLater}
                      className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded text-white font-mono text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
                    />
                  </div>

                  <div className="space-y-2">
                    <label htmlFor="default-model" className="text-gray-400 text-sm font-mono">
                      {t('init.authMethod.defaultModel')} *
                    </label>
                    <input
                      id="default-model"
                      type="text"
                      value={defaultModel}
                      onChange={(e) => setDefaultModel(e.target.value)}
                      placeholder={t('init.authMethod.enterDefaultModel')}
                      disabled={configLater}
                      className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded text-white font-mono text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
                    />
                  </div>
                </>
              )}

              {/* Configure later checkbox */}
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={configLater}
                  onChange={(e) => setConfigLater(e.target.checked)}
                  className="w-4 h-4 rounded border-gray-600 bg-gray-800 text-blue-500 focus:ring-blue-500 focus:ring-offset-0"
                />
                <span className="text-gray-400 text-sm font-mono">
                  {t('init.authMethod.configLater')}
                </span>
              </label>
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center justify-between pt-4 border-t border-gray-800">
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-2 text-gray-400 hover:text-gray-300 text-sm font-mono"
        >
          <ArrowLeft className="w-4 h-4" />
          {t('init.back')}
        </button>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onSkip}
            className="text-gray-400 hover:text-gray-300 text-sm font-mono"
          >
            {t('init.skip')}
          </button>

          <button
            type="button"
            onClick={handleContinue}
            disabled={!canContinue}
            className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-mono"
          >
            {t('init.continue')}
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
