/**
 * General Settings 组件
 * 主配置管理：API endpoint、工作目录、CCR 状态
 */

import { useEffect, useState } from 'react';
import { getMainConfig, updateAuthMethod, openWorkingDirectory } from '@/api/pywebview';
import type { MainConfig } from '@/types/pywebview.d';
import { Eye, EyeOff, FolderOpen } from 'lucide-react';
import Modal from '@/components/ui/Modal';

export default function GeneralSettings() {
  const [config, setConfig] = useState<MainConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // API 端点编辑状态
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

      // 初始化 API 端点状态
      setAuthMethod(data.auth_method);
      if (data.api_endpoint) {
        setEndpointType(data.api_endpoint.type);
        setEndpointUrl(data.api_endpoint.url || '');
        setApiKey(data.api_endpoint.api_key);
      }

      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载配置失败');
    } finally {
      setLoading(false);
    }
  };

  // API key 掩码显示
  const maskApiKey = (key: string): string => {
    if (key.length <= 8) {
      return '••••••••';
    }
    return key.slice(0, 4) + '••••' + key.slice(-4);
  };

  // 处理认证方式切换
  const handleAuthMethodChange = (method: 'official' | 'custom') => {
    // 从 custom 切换到 official 需要确认
    if (authMethod === 'custom' && method === 'official') {
      setShowConfirmDialog(true);
      return;
    }
    setAuthMethod(method);
  };

  // 确认切换到 official
  const confirmSwitchToOfficial = () => {
    setAuthMethod('official');
    setShowConfirmDialog(false);
    // 清空自定义端点数据
    setEndpointType('deepseek');
    setEndpointUrl('');
    setApiKey('');
  };

  // 保存认证配置
  const handleSaveAuth = async () => {
    if (!config) return;

    // 验证
    if (authMethod === 'custom') {
      if (!apiKey.trim()) {
        setError('API Key 不能为空');
        return;
      }
      if (endpointType === 'custom' && !endpointUrl.trim()) {
        setError('自定义端点需要提供 URL');
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
        // 更新本地状态（API key 会被掩码）
        if (result.config.api_endpoint) {
          setApiKey(result.config.api_endpoint.api_key);
        }
        setError(null);
      } else {
        setError(result.error || '保存失败');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  // 打开工作目录
  const handleOpenWorkingDirectory = async () => {
    try {
      const result = await openWorkingDirectory();
      if (result.status === 'error') {
        setError(result.error || '打开目录失败');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '打开目录失败');
    }
  };

  if (loading) {
    return (
      <div className="text-[var(--text-muted)] text-center py-8">
        正在加载配置...
      </div>
    );
  }

  if (!config) {
    return (
      <div className="text-[var(--text-error)] text-center py-8">
        加载配置失败
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="card">
        <h2 className="text-lg font-semibold text-[var(--accent-primary)] mb-4">
          通用配置
        </h2>

        {error && (
          <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md">
            <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
          </div>
        )}

        {/* API Endpoint */}
        <div className="border-b border-[var(--border-color)] pb-4 mb-4">
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-3">
            API 端点
          </label>

          {/* 认证方式选择 */}
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
              <span className="text-sm text-[var(--text-primary)]">官方 Claude API</span>
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
              <span className="text-sm text-[var(--text-primary)]">自定义 API 端点</span>
            </label>
          </div>

          {/* Custom 端点配置 */}
          {authMethod === 'custom' && (
            <div className="space-y-3 ml-6 pl-4 border-l-2 border-[var(--border-color)]">
              {/* 端点类型 */}
              <div>
                <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
                  端点类型
                </label>
                <select
                  value={endpointType}
                  onChange={(e) => setEndpointType(e.target.value as any)}
                  className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
                >
                  <option value="deepseek">DeepSeek API</option>
                  <option value="aliyun">阿里云 API</option>
                  <option value="kimi">Kimi API</option>
                  <option value="minimax">MiniMax API</option>
                  <option value="custom">自定义 URL</option>
                </select>
              </div>

              {/* URL（仅 custom 类型显示） */}
              {endpointType === 'custom' && (
                <div>
                  <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
                    API URL
                  </label>
                  <input
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
                <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
                  API Key
                </label>
                <div className="flex gap-2">
                  <input
                    type={showApiKey ? "text" : "password"}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="输入 API Key"
                    className="flex-1 px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
                  />
                  <button
                    onClick={() => setShowApiKey(!showApiKey)}
                    className="btn btn-ghost btn-sm p-2"
                    title={showApiKey ? "隐藏" : "显示"}
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

          {/* 保存按钮 */}
          <button
            onClick={handleSaveAuth}
            disabled={saving}
            className="mt-3 btn btn-primary btn-sm disabled:opacity-50"
          >
            {saving ? '保存中...' : '保存配置'}
          </button>
        </div>

        {/* 工作目录 */}
        <div>
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-2">
            工作目录
          </label>
          <div className="flex gap-2 items-center">
            <div className="flex-1 bg-[var(--bg-subtle)] rounded-md px-3 py-2">
              <span className="text-[var(--text-secondary)]">
                {config.working_directory || '~/.frago/projects 的父目录'}
              </span>
            </div>
            <button
              onClick={handleOpenWorkingDirectory}
              className="btn btn-ghost btn-sm flex items-center gap-1"
              title="在文件管理器中打开"
            >
              <FolderOpen size={16} />
              打开
            </button>
          </div>
        </div>
      </div>

      {/* 资源状态 */}
      <div className="card">
        <h2 className="text-lg font-semibold text-[var(--accent-primary)] mb-4">
          资源状态
        </h2>

        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-[var(--text-secondary)]">资源已安装</span>
            <span className={config.resources_installed ? 'text-green-600 dark:text-green-400' : 'text-[var(--text-muted)]'}>
              {config.resources_installed ? '✓ 是' : '否'}
            </span>
          </div>
          {config.resources_version && (
            <div>
              <div className="flex justify-between mb-1">
                <span className="text-[var(--text-secondary)]">资源版本</span>
                <span className="text-[var(--text-primary)]">{config.resources_version}</span>
              </div>
              <p className="text-xs text-[var(--text-muted)] text-right">
                资源安装时的 frago 版本，非当前包版本
              </p>
            </div>
          )}
          <div className="flex justify-between">
            <span className="text-[var(--text-secondary)]">初始化完成</span>
            <span className={config.init_completed ? 'text-green-600 dark:text-green-400' : 'text-[var(--text-muted)]'}>
              {config.init_completed ? '✓ 是' : '否'}
            </span>
          </div>
        </div>
      </div>

      {/* 确认对话框 */}
      <Modal
        isOpen={showConfirmDialog}
        onClose={() => setShowConfirmDialog(false)}
        title="确认切换到官方 API"
        footer={
          <>
            <button
              onClick={() => setShowConfirmDialog(false)}
              className="btn btn-ghost"
            >
              取消
            </button>
            <button
              onClick={confirmSwitchToOfficial}
              className="btn btn-primary"
            >
              确定切换
            </button>
          </>
        }
      >
        <p className="text-sm text-[var(--text-secondary)]">
          切换到官方 Claude API 将会清除当前的自定义端点配置（包括 API Key）。此操作不可撤销，确定要继续吗？
        </p>
      </Modal>
    </div>
  );
}
