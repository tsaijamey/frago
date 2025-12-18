/**
 * Sync Settings 组件
 * 同步配置和 GitHub 向导
 */

import { useEffect, useState } from 'react';
import { getMainConfig, runFirstSync, getSyncResult, checkSyncRepoVisibility, checkGhCli } from '@/api/pywebview';
import { Github, RefreshCw, AlertTriangle, Check, X, Loader2, AlertCircle } from 'lucide-react';
import GitHubWizard from './GitHubWizard';

import type { GhCliStatus } from '@/types/pywebview.d';

export default function SyncSettings() {
  const [syncRepoUrl, setSyncRepoUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showWizard, setShowWizard] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncOutput, setSyncOutput] = useState('');
  const [syncError, setSyncError] = useState<string | null>(null);
  const [isPublicRepo, setIsPublicRepo] = useState(false);
  const [visibilityChecked, setVisibilityChecked] = useState(false);
  const [ghStatus, setGhStatus] = useState<GhCliStatus | null>(null);
  const [ghStatusLoading, setGhStatusLoading] = useState(false);

  const checkGhStatus = async () => {
    try {
      setGhStatusLoading(true);
      const status = await checkGhCli();
      setGhStatus(status);
    } catch (err) {
      console.error('检测 gh 状态失败:', err);
    } finally {
      setGhStatusLoading(false);
    }
  };

  useEffect(() => {
    loadConfig();
    checkGhStatus();
  }, []);

  const loadConfig = async () => {
    try {
      setLoading(true);
      const config = await getMainConfig();
      setSyncRepoUrl(config.sync_repo_url || null);

      // 如果有配置仓库，检查可见性
      if (config.sync_repo_url) {
        try {
          const visibilityResult = await checkSyncRepoVisibility();
          if (visibilityResult.status === 'ok') {
            setIsPublicRepo(visibilityResult.is_public || false);
            setVisibilityChecked(true);
          }
        } catch (err) {
          console.error('检查仓库可见性失败:', err);
        }
      }
    } catch (err) {
      console.error('加载配置失败:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSync = async () => {
    try {
      setSyncing(true);
      setSyncError(null);
      setSyncOutput('正在启动同步...\n');

      const startResult = await runFirstSync();
      if (startResult.status === 'error') {
        setSyncError(startResult.error || '同步失败');
        setSyncing(false);
        return;
      }

      // 轮询结果
      const pollInterval = setInterval(async () => {
        const result = await getSyncResult();

        if (result.status === 'running') {
          // 仍在进行中
          return;
        }

        clearInterval(pollInterval);
        setSyncing(false);

        if (result.status === 'ok') {
          setSyncOutput((prev) => prev + '\n✓ 同步完成\n' + (result.output || ''));
        } else {
          setSyncError(result.error || '同步失败');
          setSyncOutput((prev) => prev + '\n✗ 同步失败\n' + (result.error || ''));
        }
      }, 1000);

      // 超时保护（5 分钟）
      setTimeout(() => {
        clearInterval(pollInterval);
        if (syncing) {
          setSyncing(false);
          setSyncError('同步超时');
        }
      }, 300000);

    } catch (err) {
      setSyncError(err instanceof Error ? err.message : '同步失败');
      setSyncing(false);
    }
  };

  const handleWizardComplete = () => {
    setShowWizard(false);
    loadConfig(); // 重新加载配置
  };

  if (loading) {
    return (
      <div className="text-[var(--text-muted)] text-center py-8">
        正在加载配置...
      </div>
    );
  }

  if (showWizard) {
    return <GitHubWizard onComplete={handleWizardComplete} onCancel={() => setShowWizard(false)} />;
  }

  return (
    <div className="space-y-4">
      <div className="card">
        <h2 className="text-lg font-semibold text-[var(--accent-primary)] mb-4">
          多设备同步
        </h2>

        {/* GitHub CLI 状态检测 */}
        <div className="mb-4 p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-md">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-blue-900 dark:text-blue-200">
              GitHub CLI 状态
            </h3>
            <button
              onClick={checkGhStatus}
              disabled={ghStatusLoading}
              className="text-xs text-blue-600 dark:text-blue-400 hover:underline disabled:opacity-50"
            >
              {ghStatusLoading ? '检测中...' : '刷新'}
            </button>
          </div>

          {ghStatusLoading && !ghStatus ? (
            <div className="flex items-center gap-2 text-sm text-blue-700 dark:text-blue-300">
              <Loader2 size={14} className="animate-spin" />
              正在检测...
            </div>
          ) : ghStatus ? (
            <div className="space-y-1 text-sm">
              {/* gh 安装状态 */}
              <div className={`flex items-center gap-2 ${
                ghStatus.installed
                  ? 'text-green-600 dark:text-green-400'
                  : 'text-red-600 dark:text-red-400'
              }`}>
                {ghStatus.installed ? <Check size={14} /> : <X size={14} />}
                <span>
                  {ghStatus.installed
                    ? `gh CLI 已安装 (v${ghStatus.version})`
                    : 'gh CLI 未安装'}
                </span>
              </div>

              {/* 登录状态（仅在已安装时显示） */}
              {ghStatus.installed && (
                <div className={`flex items-center gap-2 ${
                  ghStatus.authenticated
                    ? 'text-green-600 dark:text-green-400'
                    : 'text-yellow-600 dark:text-yellow-400'
                }`}>
                  {ghStatus.authenticated ? <Check size={14} /> : <AlertCircle size={14} />}
                  <span>
                    {ghStatus.authenticated
                      ? `已登录 GitHub (@${ghStatus.username})`
                      : '未登录 GitHub'}
                  </span>
                </div>
              )}

              {/* 操作提示 */}
              {!ghStatus.installed && (
                <p className="mt-2 text-blue-700 dark:text-blue-300">
                  请先安装 GitHub CLI：
                  <a
                    href="https://cli.github.com/"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="ml-1 underline"
                  >
                    https://cli.github.com/
                  </a>
                </p>
              )}
              {ghStatus.installed && !ghStatus.authenticated && (
                <p className="mt-2 text-blue-700 dark:text-blue-300">
                  点击下方"开始配置"按钮登录 GitHub
                </p>
              )}
            </div>
          ) : (
            <p className="text-sm text-blue-700 dark:text-blue-300">
              首次配置需要安装 GitHub CLI (gh) 并登录 GitHub 账号。向导将引导你完成整个流程。
            </p>
          )}
        </div>

        {syncRepoUrl ? (
          <>
            <div className="flex gap-2 mb-4">
              <button
                onClick={handleSync}
                disabled={syncing}
                className="btn btn-primary flex items-center gap-2"
              >
                <RefreshCw size={16} className={syncing ? 'animate-spin' : ''} />
                {syncing ? '同步中...' : '立即同步'}
              </button>
              <button
                onClick={() => setShowWizard(true)}
                className="btn btn-ghost"
              >
                重新配置
              </button>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-[var(--text-primary)] mb-2">
                同步仓库
              </label>
              <div className="flex items-center gap-2 bg-[var(--bg-subtle)] rounded-md px-3 py-2">
                <Github size={16} className="text-[var(--text-muted)]" />
                <span className="text-sm text-[var(--text-secondary)] font-mono flex-1">
                  {syncRepoUrl}
                </span>
              </div>
            </div>

            {/* Public 仓库警告 */}
            {visibilityChecked && isPublicRepo && (
              <div className="mb-4 p-3 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-md">
                <div className="flex items-start gap-2">
                  <AlertTriangle size={16} className="text-yellow-600 dark:text-yellow-400 mt-0.5 flex-shrink-0" />
                  <div>
                    <h3 className="text-sm font-medium text-yellow-800 dark:text-yellow-200 mb-1">
                      安全提醒
                    </h3>
                    <p className="text-sm text-yellow-700 dark:text-yellow-300">
                      当前同步仓库是 <strong>public</strong> 仓库，任何人都可以访问。
                      建议将仓库改为 private 以保护您的配置和敏感信息。
                    </p>
                    <p className="text-xs text-yellow-600 dark:text-yellow-400 mt-2">
                      .env 文件已自动添加到 .gitignore，不会被同步。
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* 同步输出 */}
            {syncOutput && (
              <div className="mt-4 p-3 bg-black/5 dark:bg-white/5 rounded-md">
                <pre className="text-xs text-[var(--text-secondary)] whitespace-pre-wrap font-mono">
                  {syncOutput}
                </pre>
              </div>
            )}

            {/* 同步错误 */}
            {syncError && (
              <div className="mt-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md">
                <p className="text-sm text-red-700 dark:text-red-400">{syncError}</p>
              </div>
            )}
          </>
        ) : (
          <>
            <p className="text-sm text-[var(--text-muted)] mb-4">
              使用 GitHub 私有仓库同步 Frago 资源（命令、技能、配方）到多个设备。
            </p>
            <button
              onClick={() => setShowWizard(true)}
              className="btn btn-primary flex items-center gap-2"
            >
              <Github size={16} />
              开始配置 GitHub 同步
            </button>
          </>
        )}
      </div>
    </div>
  );
}
