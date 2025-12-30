/**
 * General Settings Component
 * Main configuration: API endpoint, working directory, CCR status
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getMainConfig, updateAuthMethod, openWorkingDirectory, checkVSCode, openConfigInVSCode } from '@/api';
import type { MainConfig } from '@/types/pywebview';
import { Eye, EyeOff, FolderOpen, Code } from 'lucide-react';
import Modal from '@/components/ui/Modal';

export default function GeneralSettings() {
  const { t } = useTranslation();
  const [config, setConfig] = useState<MainConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // API endpoint editing state
  const [authMethod, setAuthMethod] = useState<'official' | 'custom'>('official');
  const [endpointType, setEndpointType] = useState<'deepseek' | 'aliyun' | 'kimi' | 'minimax' | 'custom'>('deepseek');
  const [endpointUrl, setEndpointUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [defaultModel, setDefaultModel] = useState('');
  const [sonnetModel, setSonnetModel] = useState('');
  const [haikuModel, setHaikuModel] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);
  const [vscodeInstalled, setVscodeInstalled] = useState(false);

  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async () => {
    try {
      setLoading(true);
      const data = await getMainConfig();
      setConfig(data);

      // Initialize API endpoint state
      setAuthMethod(data.auth_method);
      if (data.api_endpoint) {
        setEndpointType(data.api_endpoint.type);
        setEndpointUrl(data.api_endpoint.url || '');
        setApiKey(data.api_endpoint.api_key);
        setDefaultModel(data.api_endpoint.default_model || '');
        setSonnetModel(data.api_endpoint.sonnet_model || '');
        setHaikuModel(data.api_endpoint.haiku_model || '');
      }

      // Check VSCode availability (requires VSCode + ~/.claude/settings.json)
      try {
        const vscodeStatus = await checkVSCode();
        setVscodeInstalled(vscodeStatus.available);
      } catch {
        // Ignore errors, just don't show the button
        setVscodeInstalled(false);
      }

      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.general.failedToLoadConfig'));
    } finally {
      setLoading(false);
    }
  };

  // API key mask display
  const maskApiKey = (key: string): string => {
    if (key.length <= 8) {
      return '••••••••';
    }
    return key.slice(0, 4) + '••••' + key.slice(-4);
  };

  // Handle auth method change
  const handleAuthMethodChange = (method: 'official' | 'custom') => {
    // Switching from custom to official requires confirmation
    if (authMethod === 'custom' && method === 'official') {
      setShowConfirmDialog(true);
      return;
    }
    setAuthMethod(method);
  };

  // Confirm switch to official
  const confirmSwitchToOfficial = () => {
    setAuthMethod('official');
    setShowConfirmDialog(false);
    // Clear custom endpoint data
    setEndpointType('deepseek');
    setEndpointUrl('');
    setApiKey('');
    setDefaultModel('');
    setSonnetModel('');
    setHaikuModel('');
  };

  // Save auth configuration
  const handleSaveAuth = async () => {
    if (!config) return;

    // Validation
    if (authMethod === 'custom') {
      if (!apiKey.trim()) {
        setError(t('errors.apiKeyEmpty'));
        return;
      }
      if (endpointType === 'custom') {
        if (!endpointUrl.trim()) {
          setError(t('errors.customEndpointRequired'));
          return;
        }
        if (!sonnetModel.trim()) {
          setError(t('errors.customEndpointModelRequired'));
          return;
        }
      }
    }

    try {
      setSaving(true);
      const authData: any = {
        auth_method: authMethod
      };

      if (authMethod === 'custom') {
        authData.api_endpoint = {
          type: endpointType,
          api_key: apiKey,
          ...(endpointType === 'custom' && { url: endpointUrl }),
          // Include model overrides (for all types, including presets)
          ...(defaultModel.trim() && { default_model: defaultModel.trim() }),
          ...(sonnetModel.trim() && { sonnet_model: sonnetModel.trim() }),
          ...(haikuModel.trim() && { haiku_model: haikuModel.trim() })
        };
      }

      const result = await updateAuthMethod(authData);
      if (result.status === 'ok' && result.config) {
        setConfig(result.config);
        // Update local state (API key will be masked)
        if (result.config.api_endpoint) {
          setApiKey(result.config.api_endpoint.api_key);
          setDefaultModel(result.config.api_endpoint.default_model || '');
          setSonnetModel(result.config.api_endpoint.sonnet_model || '');
          setHaikuModel(result.config.api_endpoint.haiku_model || '');
        }
        setError(null);

        // Re-check VSCode availability (settings.json may have been created/deleted)
        try {
          const vscodeStatus = await checkVSCode();
          setVscodeInstalled(vscodeStatus.available);
        } catch {
          // Ignore errors
        }
      } else {
        setError(result.error || t('errors.saveFailed'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('errors.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  // Open working directory
  const handleOpenWorkingDirectory = async () => {
    try {
      const result = await openWorkingDirectory();
      if (result.status === 'error') {
        setError(result.error || t('settings.general.failedToOpenDir'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.general.failedToOpenDir'));
    }
  };

  // Open config in VSCode
  const handleOpenInVSCode = async () => {
    try {
      const result = await openConfigInVSCode();
      if (result.status === 'error') {
        setError(result.error || t('settings.general.failedToOpenVSCode'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.general.failedToOpenVSCode'));
    }
  };

  if (loading) {
    return (
      <div className="text-[var(--text-muted)] text-center py-8">
        {t('common.loadingConfiguration')}
      </div>
    );
  }

  if (!config) {
    return (
      <div className="text-[var(--text-error)] text-center py-8">
        {t('settings.general.failedToLoadConfig')}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="card">
        <h2 className="text-lg font-semibold text-[var(--accent-primary)] mb-4">
          {t('settings.general.title')}
        </h2>

        {error && (
          <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md">
            <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
          </div>
        )}

        {/* API Endpoint */}
        <div className="border-b border-[var(--border-color)] pb-4 mb-4">
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-3">
            {t('settings.general.apiEndpoint')}
          </label>

          {/* Auth method selection */}
          <div className="space-y-2 mb-3">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="auth_method"
                value="official"
                checked={authMethod === 'official'}
                onChange={() => handleAuthMethodChange('official')}
                className="w-4 h-4 text-[var(--accent-primary)]"
              />
              <span className="text-sm text-[var(--text-primary)]">{t('settings.general.officialApi')}</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="auth_method"
                value="custom"
                checked={authMethod === 'custom'}
                onChange={() => handleAuthMethodChange('custom')}
                className="w-4 h-4 text-[var(--accent-primary)]"
              />
              <span className="text-sm text-[var(--text-primary)]">{t('settings.general.customEndpoint')}</span>
            </label>
          </div>

          {/* Custom endpoint configuration */}
          {authMethod === 'custom' && (
            <div className="space-y-3 ml-6 pl-4 border-l-2 border-[var(--border-color)]">
              {/* Endpoint type */}
              <div>
                <label htmlFor="endpoint-type" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
                  {t('settings.general.endpointType')}
                </label>
                <select
                  id="endpoint-type"
                  value={endpointType}
                  onChange={(e) => setEndpointType(e.target.value as any)}
                  className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
                >
                  <option value="deepseek">DeepSeek API</option>
                  <option value="aliyun">Aliyun API</option>
                  <option value="kimi">Kimi API</option>
                  <option value="minimax">MiniMax API</option>
                  <option value="custom">Custom URL</option>
                </select>
              </div>

              {/* URL (only shown for custom type) */}
              {endpointType === 'custom' && (
                <div>
                  <label htmlFor="api-url" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
                    {t('settings.general.apiUrl')}
                  </label>
                  <input
                    id="api-url"
                    type="text"
                    value={endpointUrl}
                    onChange={(e) => setEndpointUrl(e.target.value)}
                    placeholder="https://api.example.com/v1/chat"
                    className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
                  />
                </div>
              )}

              {/* API Key */}
              <div>
                <label htmlFor="api-key" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
                  {t('settings.general.apiKey')}
                </label>
                <div className="flex gap-2">
                  <input
                    id="api-key"
                    type={showApiKey ? "text" : "password"}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={t('settings.general.enterApiKey')}
                    className="flex-1 px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => setShowApiKey(!showApiKey)}
                    className="btn btn-ghost btn-sm p-2"
                    title={showApiKey ? t('settings.general.hide') : t('settings.general.show')}
                  >
                    {showApiKey ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
                {apiKey && !showApiKey && (
                  <p className="mt-1 text-xs text-[var(--text-muted)] font-mono">
                    {maskApiKey(apiKey)}
                  </p>
                )}
              </div>

              {/* Model Configuration */}
              <div>
                <label htmlFor="default-model" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
                  {t('settings.general.defaultModel')} {endpointType !== 'custom' && <span className="text-[var(--text-muted)]">- {t('settings.general.optionalOverride')}</span>}
                </label>
                <input
                  id="default-model"
                  type="text"
                  value={defaultModel}
                  onChange={(e) => setDefaultModel(e.target.value)}
                  placeholder={endpointType === 'custom' ? 'e.g., gpt-4' : t('settings.general.leaveEmptyDefault')}
                  className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
                />
                <p className="mt-1 text-xs text-[var(--text-muted)]">ANTHROPIC_MODEL</p>
              </div>

              <div>
                <label htmlFor="sonnet-model" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
                  {t('settings.general.sonnetModel')} {endpointType !== 'custom' && <span className="text-[var(--text-muted)]">- {t('settings.general.optionalOverride')}</span>}
                </label>
                <input
                  id="sonnet-model"
                  type="text"
                  value={sonnetModel}
                  onChange={(e) => setSonnetModel(e.target.value)}
                  placeholder={endpointType === 'custom' ? 'e.g., gpt-4' : t('settings.general.leaveEmptyDefault')}
                  className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
                />
                <p className="mt-1 text-xs text-[var(--text-muted)]">ANTHROPIC_DEFAULT_SONNET_MODEL</p>
              </div>

              <div>
                <label htmlFor="haiku-model" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
                  {t('settings.general.haikuModel')} <span className="text-[var(--text-muted)]">- {t('settings.general.optional')}</span>
                </label>
                <input
                  id="haiku-model"
                  type="text"
                  value={haikuModel}
                  onChange={(e) => setHaikuModel(e.target.value)}
                  placeholder={t('settings.general.leaveEmptySonnet')}
                  className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
                />
                <p className="mt-1 text-xs text-[var(--text-muted)]">ANTHROPIC_DEFAULT_HAIKU_MODEL</p>
              </div>
            </div>
          )}

          {/* Save button and Edit button */}
          <div className="mt-3 flex gap-2 items-center">
            <button
              type="button"
              onClick={handleSaveAuth}
              disabled={saving}
              className="btn btn-primary btn-sm disabled:opacity-50"
            >
              {saving ? t('settings.general.saving') : t('settings.general.saveConfiguration')}
            </button>
            {vscodeInstalled && (
              <button
                type="button"
                onClick={handleOpenInVSCode}
                className="btn btn-ghost btn-sm flex items-center gap-1"
                title="Edit ~/.claude/settings.json in VSCode"
              >
                <Code size={16} />
                {t('settings.general.edit')}
              </button>
            )}
          </div>
        </div>

        {/* Working directory (read-only) */}
        <div>
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-2">
            {t('settings.general.workingDirectory')}
          </label>
          <div className="flex gap-2 items-center">
            <div className="flex-1 bg-[var(--bg-subtle)] rounded-md px-3 py-2 overflow-x-auto">
              <span className="text-[var(--text-secondary)] font-mono text-sm whitespace-nowrap">
                {config.working_directory_display || '~/.frago/projects'}
              </span>
            </div>
            <button
              onClick={handleOpenWorkingDirectory}
              className="btn btn-ghost btn-sm flex items-center gap-1 shrink-0"
              title="Open in file manager"
            >
              <FolderOpen size={16} />
              {t('settings.general.open')}
            </button>
          </div>
        </div>
      </div>


      {/* Confirmation dialog */}
      <Modal
        isOpen={showConfirmDialog}
        onClose={() => setShowConfirmDialog(false)}
        title={t('settings.general.confirmSwitch')}
        footer={
          <>
            <button
              onClick={() => setShowConfirmDialog(false)}
              className="btn btn-ghost"
            >
              {t('settings.general.cancel')}
            </button>
            <button
              onClick={confirmSwitchToOfficial}
              className="btn btn-primary"
            >
              {t('settings.general.confirmSwitchBtn')}
            </button>
          </>
        }
      >
        <p className="text-sm text-[var(--text-secondary)]">
          {t('settings.general.confirmSwitchFullDesc')}
        </p>
      </Modal>
    </div>
  );
}
