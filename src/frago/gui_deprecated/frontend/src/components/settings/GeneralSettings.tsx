/**
 * General Settings Component
 * Main configuration: API endpoint, working directory, CCR status
 */

import { useEffect, useState } from 'react';
import { getMainConfig, updateAuthMethod, openWorkingDirectory } from '@/api';
import type { MainConfig } from '@/types/pywebview.d';
import { Eye, EyeOff, FolderOpen } from 'lucide-react';
import Modal from '@/components/ui/Modal';

export default function GeneralSettings() {
  const [config, setConfig] = useState<MainConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // API endpoint editing state
  const [authMethod, setAuthMethod] = useState<'official' | 'custom'>('official');
  const [endpointType, setEndpointType] = useState<'deepseek' | 'aliyun' | 'kimi' | 'minimax' | 'custom'>('deepseek');
  const [endpointUrl, setEndpointUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);

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
      }

      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load config');
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
  };

  // Save auth configuration
  const handleSaveAuth = async () => {
    if (!config) return;

    // Validation
    if (authMethod === 'custom') {
      if (!apiKey.trim()) {
        setError('API Key cannot be empty');
        return;
      }
      if (endpointType === 'custom' && !endpointUrl.trim()) {
        setError('Custom endpoint requires a URL');
        return;
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
          ...(endpointType === 'custom' && { url: endpointUrl })
        };
      }

      const result = await updateAuthMethod(authData);
      if (result.status === 'ok' && result.config) {
        setConfig(result.config);
        // Update local state (API key will be masked)
        if (result.config.api_endpoint) {
          setApiKey(result.config.api_endpoint.api_key);
        }
        setError(null);
      } else {
        setError(result.error || 'Save failed');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  // Open working directory
  const handleOpenWorkingDirectory = async () => {
    try {
      const result = await openWorkingDirectory();
      if (result.status === 'error') {
        setError(result.error || 'Failed to open directory');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to open directory');
    }
  };

  if (loading) {
    return (
      <div className="text-[var(--text-muted)] text-center py-8">
        Loading configuration...
      </div>
    );
  }

  if (!config) {
    return (
      <div className="text-[var(--text-error)] text-center py-8">
        Failed to load configuration
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="card">
        <h2 className="text-lg font-semibold text-[var(--accent-primary)] mb-4">
          General Configuration
        </h2>

        {error && (
          <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md">
            <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
          </div>
        )}

        {/* API Endpoint */}
        <div className="border-b border-[var(--border-color)] pb-4 mb-4">
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-3">
            API Endpoint
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
              <span className="text-sm text-[var(--text-primary)]">Official Claude API</span>
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
              <span className="text-sm text-[var(--text-primary)]">Custom API Endpoint</span>
            </label>
          </div>

          {/* Custom endpoint configuration */}
          {authMethod === 'custom' && (
            <div className="space-y-3 ml-6 pl-4 border-l-2 border-[var(--border-color)]">
              {/* Endpoint type */}
              <div>
                <label htmlFor="endpoint-type" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
                  Endpoint Type
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
                    API URL
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
                  API Key
                </label>
                <div className="flex gap-2">
                  <input
                    id="api-key"
                    type={showApiKey ? "text" : "password"}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="Enter API Key"
                    className="flex-1 px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
                  />
                  <button
                    onClick={() => setShowApiKey(!showApiKey)}
                    className="btn btn-ghost btn-sm p-2"
                    title={showApiKey ? "Hide" : "Show"}
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
            </div>
          )}

          {/* Save button */}
          <button
            onClick={handleSaveAuth}
            disabled={saving}
            className="mt-3 btn btn-primary btn-sm disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save Configuration'}
          </button>
        </div>

        {/* Working directory (read-only) */}
        <div>
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-2">
            Working Directory
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
              Open
            </button>
          </div>
        </div>
      </div>

      {/* Resource status */}
      <div className="card">
        <h2 className="text-lg font-semibold text-[var(--accent-primary)] mb-4">
          Resource Status
        </h2>

        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-[var(--text-secondary)]">Resources Installed</span>
            <span className={config.resources_installed ? 'text-green-600 dark:text-green-400' : 'text-[var(--text-muted)]'}>
              {config.resources_installed ? '✓ Yes' : 'No'}
            </span>
          </div>
          {config.resources_version && (
            <div>
              <div className="flex justify-between mb-1">
                <span className="text-[var(--text-secondary)]">Resources Version</span>
                <span className="text-[var(--text-primary)]">{config.resources_version}</span>
              </div>
              <p className="text-xs text-[var(--text-muted)] text-right">
                Frago version when resources were installed, not the current package version
              </p>
            </div>
          )}
          <div className="flex justify-between">
            <span className="text-[var(--text-secondary)]">Initialization Complete</span>
            <span className={config.init_completed ? 'text-green-600 dark:text-green-400' : 'text-[var(--text-muted)]'}>
              {config.init_completed ? '✓ Yes' : 'No'}
            </span>
          </div>
        </div>
      </div>

      {/* Confirmation dialog */}
      <Modal
        isOpen={showConfirmDialog}
        onClose={() => setShowConfirmDialog(false)}
        title="Confirm Switch to Official API"
        footer={
          <>
            <button
              onClick={() => setShowConfirmDialog(false)}
              className="btn btn-ghost"
            >
              Cancel
            </button>
            <button
              onClick={confirmSwitchToOfficial}
              className="btn btn-primary"
            >
              Confirm Switch
            </button>
          </>
        }
      >
        <p className="text-sm text-[var(--text-secondary)]">
          Switching to official Claude API will clear your current custom endpoint configuration (including API Key). This action cannot be undone. Are you sure you want to continue?
        </p>
      </Modal>
    </div>
  );
}
