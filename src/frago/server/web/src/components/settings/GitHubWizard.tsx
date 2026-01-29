/**
 * GitHub Wizard Component
 * 3-step wizard: Detect & Login → Configure Repository → Complete
 */

import { useState, useEffect, useCallback } from 'react';
import {
  checkGhCli,
  startWebLogin,
  checkAuthStatus,
  cancelWebLogin,
  setupSyncRepo,
  getSetupStatus,
  checkSyncRepo,
} from '@/api';
import type { GhCliStatus } from '@/types/pywebview';
import { Github, Check, AlertCircle, Loader2, Terminal, FolderGit2, Info, User, GitBranch, FolderSync, CheckCircle } from 'lucide-react';

interface GitHubWizardProps {
  onComplete: () => void;
  onCancel: () => void;
}

type Step = 1 | 2 | 3;

// Default repository name
const DEFAULT_REPO_NAME = 'frago-working-dir';

export default function GitHubWizard({ onComplete, onCancel }: GitHubWizardProps) {
  const [currentStep, setCurrentStep] = useState<Step>(1);

  // Step 1 state
  const [ghStatus, setGhStatus] = useState<GhCliStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loginCode, setLoginCode] = useState<string | null>(null);
  const [waitingForAuth, setWaitingForAuth] = useState(false);

  // Step 2 state
  const [repoExists, setRepoExists] = useState<boolean | null>(null);
  const [setupRunning, setSetupRunning] = useState(false);
  const [setupStatus, setSetupStatus] = useState<string>('');

  // Step 3 state
  const [completedData, setCompletedData] = useState<{
    username: string | null;
    repoUrl: string | null;
    created: boolean;
    localChanges: number;
    remoteUpdates: number;
  } | null>(null);

  // Step 1: Check gh CLI status on mount
  useEffect(() => {
    if (currentStep === 1) {
      checkGhStatus();
    }
  }, [currentStep]);

  const checkGhStatus = async () => {
    try {
      setLoading(true);
      setError(null);
      const status = await checkGhCli();
      setGhStatus(status);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to detect gh CLI');
    } finally {
      setLoading(false);
    }
  };

  // Step 1: Start web login
  const handleStartLogin = async () => {
    try {
      setLoading(true);
      setError(null);
      setLoginCode(null);
      
      const result = await startWebLogin();

      if (result.status === 'ok' && result.code) {
        setLoginCode(result.code);
        setWaitingForAuth(true);
        // Start polling for auth completion
        pollAuthStatus();
      } else {
        setError(result.error || 'Failed to start login');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  // Poll for authentication completion
  const pollAuthStatus = useCallback(async () => {
    const pollInterval = setInterval(async () => {
      try {
        const status = await checkAuthStatus();

        if (status.completed) {
          clearInterval(pollInterval);
          setWaitingForAuth(false);

          if (status.authenticated) {
            // Login successful, update gh status and move to step 2
            setGhStatus((prev) => prev ? {
              ...prev,
              authenticated: true,
              username: status.username || undefined,
            } : null);
            setLoginCode(null);
                        setCurrentStep(2);
          } else {
            setError(status.error || 'Login was cancelled or failed');
            setLoginCode(null);
                      }
        }
      } catch (err) {
        // Continue polling on error
        console.error('Auth status check failed:', err);
      }
    }, 2000);

    // Timeout after 5 minutes
    setTimeout(() => {
      clearInterval(pollInterval);
      if (waitingForAuth) {
        setWaitingForAuth(false);
        setError('Login timed out. Please try again.');
        setLoginCode(null);
              }
    }, 300000);
  }, [waitingForAuth]);

  // Handle cancel login
  const handleCancelLogin = async () => {
    setWaitingForAuth(false);
    setLoginCode(null);
        await cancelWebLogin();
  };

  // Step 2: Check repo and start setup
  useEffect(() => {
    if (currentStep === 2) {
      checkRepoStatus();
    }
  }, [currentStep]);

  const checkRepoStatus = async () => {
    try {
      setLoading(true);
      setSetupStatus('正在检查仓库是否存在...');
      const result = await checkSyncRepo();

      if (result.status === 'ok') {
        setRepoExists(result.exists || false);
        if (result.exists) {
          setSetupStatus(`仓库已存在: ${result.repo_url}`);
        } else {
          setSetupStatus('仓库不存在，将自动创建');
        }
      } else {
        setError(result.error || 'Failed to check repository');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to check repository');
    } finally {
      setLoading(false);
    }
  };

  // Step 2: Start setup
  const handleStartSetup = async () => {
    try {
      setSetupRunning(true);
      setError(null);

      const result = await setupSyncRepo();

      if (result.status === 'ok') {
        // Start polling for setup completion
        pollSetupStatus();
      } else {
        setError(result.error || 'Failed to start setup');
        setSetupRunning(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Setup failed');
      setSetupRunning(false);
    }
  };

  // Poll for setup completion
  const pollSetupStatus = useCallback(async () => {
    const pollInterval = setInterval(async () => {
      try {
        const status = await getSetupStatus();

        if (status.status === 'running') {
          setSetupStatus('配置中...');
        } else if (status.status === 'syncing') {
          setSetupStatus('正在执行首次同步...');
        } else if (status.status === 'ok') {
          clearInterval(pollInterval);
          setSetupRunning(false);

          // Store completion data and move to step 3
          setCompletedData({
            username: status.username || null,
            repoUrl: status.repo_url || null,
            created: status.created || false,
            localChanges: status.local_changes || 0,
            remoteUpdates: status.remote_updates || 0,
          });
          setCurrentStep(3);
        } else if (status.status === 'error') {
          clearInterval(pollInterval);
          setSetupRunning(false);
          setError(status.error || 'Setup failed');
        }
      } catch (err) {
        console.error('Setup status check failed:', err);
      }
    }, 1000);

    // Timeout after 5 minutes
    setTimeout(() => {
      clearInterval(pollInterval);
      if (setupRunning) {
        setSetupRunning(false);
        setError('Setup timed out. Please try again.');
      }
    }, 300000);
  }, [setupRunning]);

  // Progress bar component
  const ProgressBar = () => {
    const steps = [
      { num: 1, label: '检测 & 登录' },
      { num: 2, label: '配置仓库' },
      { num: 3, label: '完成' },
    ];

    return (
      <div className="mb-8">
        {/* Circles and lines */}
        <div className="flex items-center justify-center">
          {steps.map((step, index) => (
            <div key={step.num} className="flex items-center">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold transition-colors ${
                  step.num < currentStep
                    ? 'bg-[var(--accent-success)] text-white'
                    : step.num === currentStep
                    ? 'bg-[var(--accent-primary)] text-[var(--text-on-accent)]'
                    : 'bg-[var(--bg-elevated)] text-[var(--text-muted)]'
                }`}
              >
                {step.num < currentStep ? <Check size={16} /> : step.num}
              </div>
              {index < steps.length - 1 && (
                <div
                  className={`w-20 h-0.5 transition-colors ${
                    step.num < currentStep ? 'bg-[var(--accent-success)]' : 'bg-[var(--border-color)]'
                  }`}
                />
              )}
            </div>
          ))}
        </div>
        {/* Labels */}
        <div className="flex justify-between mt-3 w-80 mx-auto">
          {steps.map((step) => (
            <span
              key={step.num}
              className={`text-xs transition-colors ${
                step.num < currentStep
                  ? 'text-[var(--accent-success)]'
                  : step.num === currentStep
                  ? 'text-[var(--text-primary)] font-medium'
                  : 'text-[var(--text-muted)]'
              }`}
            >
              {step.label}
            </span>
          ))}
        </div>
      </div>
    );
  };

  // Step 1: Detect & Login
  const renderStep1 = () => (
    <div className="space-y-5">
      <div className="flex items-center gap-3 mb-4">
        <Terminal size={24} className="text-[var(--accent-primary)]" />
        <h3 className="text-lg font-semibold text-[var(--text-primary)]">
          Step 1: 环境检测 & GitHub 登录
        </h3>
      </div>

      {/* Status box */}
      <div className="bg-[var(--bg-elevated)] rounded-lg p-4 space-y-3">
        {loading && !ghStatus ? (
          <div className="flex items-center gap-2 text-[var(--text-muted)]">
            <Loader2 size={18} className="animate-spin" />
            <span className="text-sm">正在检测...</span>
          </div>
        ) : ghStatus ? (
          <>
            {/* gh CLI status */}
            <div className="flex items-center gap-2.5">
              {ghStatus.installed ? (
                <CheckCircle size={18} className="text-[var(--accent-success)] flex-shrink-0" />
              ) : (
                <AlertCircle size={18} className="text-[var(--accent-error)] flex-shrink-0" />
              )}
              <span className="text-sm text-[var(--text-secondary)]">
                {ghStatus.installed
                  ? `gh CLI 已安装 (v${ghStatus.version})`
                  : 'gh CLI 未安装'}
              </span>
            </div>

            {/* Login status */}
            {ghStatus.installed && (
              <div className="flex items-center gap-2.5">
                {ghStatus.authenticated ? (
                  <CheckCircle size={18} className="text-[var(--accent-success)] flex-shrink-0" />
                ) : waitingForAuth ? (
                  <Loader2 size={18} className="text-[var(--accent-warning)] flex-shrink-0 animate-spin" />
                ) : (
                  <AlertCircle size={18} className="text-[var(--accent-warning)] flex-shrink-0" />
                )}
                <span className={`text-sm ${waitingForAuth ? 'text-[var(--accent-warning)]' : 'text-[var(--text-secondary)]'}`}>
                  {ghStatus.authenticated
                    ? `已登录 GitHub (username: ${ghStatus.username})`
                    : waitingForAuth
                    ? '正在登录 GitHub...'
                    : '未登录 GitHub'}
                </span>
              </div>
            )}
          </>
        ) : null}
      </div>

      {/* Installation guide (when not installed) */}
      {ghStatus && !ghStatus.installed && (
        <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4">
          <div className="flex items-start gap-2 mb-3">
            <AlertCircle size={16} className="text-yellow-600 dark:text-yellow-400 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-yellow-800 dark:text-yellow-200 mb-2">
                请先安装 GitHub CLI
              </p>
              <div className="space-y-2 text-sm font-mono bg-black/10 dark:bg-white/10 rounded p-3">
                <div>
                  <span className="text-[var(--text-muted)]"># macOS</span>
                  <br />
                  <span className="text-[var(--text-primary)]">brew install gh</span>
                </div>
                <div>
                  <span className="text-[var(--text-muted)]"># Ubuntu/Debian</span>
                  <br />
                  <span className="text-[var(--text-primary)]">sudo apt install gh</span>
                </div>
                <div>
                  <span className="text-[var(--text-muted)]"># Windows</span>
                  <br />
                  <span className="text-[var(--text-primary)]">winget install GitHub.cli</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Device code display (during login) */}
      {loginCode && (
        <div className="bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-700/50 rounded-lg p-5 text-center space-y-4">
          <p className="text-sm font-medium text-blue-700 dark:text-blue-300">
            请在浏览器中输入以下验证码
          </p>
          <div className="bg-[var(--bg-primary)] rounded-lg py-4 px-8 inline-block">
            <span className="text-3xl font-bold font-mono text-[var(--accent-primary)] tracking-widest">
              {loginCode}
            </span>
          </div>
          <p className="text-sm text-blue-600 dark:text-blue-400 leading-relaxed">
            浏览器已自动打开 GitHub 登录页面，请粘贴上方验证码完成授权
          </p>
        </div>
      )}

      {/* Login hint (when installed but not logged in, not in login process) */}
      {ghStatus?.installed && !ghStatus.authenticated && !waitingForAuth && !loginCode && (
        <div className="bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-700/50 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <Info size={16} className="text-blue-500 dark:text-blue-400" />
            <span className="text-sm font-medium text-blue-700 dark:text-blue-300">未登录？点击下方按钮一键登录</span>
          </div>
          <p className="text-sm text-blue-600 dark:text-blue-400 leading-relaxed">
            后端将自动执行 gh auth login --web，打开浏览器并显示验证码。你只需将验证码粘贴到打开的页面即可完成登录。
          </p>
        </div>
      )}

      {/* Buttons */}
      <div className="flex gap-3 pt-2">
        <button
          type="button"
          onClick={onCancel}
          className="btn btn-ghost"
          disabled={waitingForAuth}
        >
          取消
        </button>
        {ghStatus?.installed && !ghStatus.authenticated && !waitingForAuth && (
          <button
            type="button"
            onClick={handleStartLogin}
            className="btn btn-primary flex items-center gap-2"
            disabled={loading}
          >
            <Github size={16} />
            开始登录
          </button>
        )}
        {waitingForAuth && (
          <button
            type="button"
            onClick={handleCancelLogin}
            className="btn btn-ghost flex items-center gap-2"
          >
            <Loader2 size={16} className="animate-spin" />
            等待授权完成...
          </button>
        )}
        {ghStatus?.installed && ghStatus.authenticated && (
          <button
            type="button"
            onClick={() => setCurrentStep(2)}
            className="btn btn-primary"
          >
            下一步
          </button>
        )}
      </div>
    </div>
  );

  // Step 2: Configure Repository
  const renderStep2 = () => (
    <div className="space-y-5">
      <div className="flex items-center gap-3 mb-4">
        <FolderGit2 size={24} className="text-[var(--accent-primary)]" />
        <h3 className="text-lg font-semibold text-[var(--text-primary)]">
          Step 2: 配置同步仓库
        </h3>
      </div>

      {/* Repository config box */}
      <div className="bg-[var(--bg-elevated)] rounded-lg p-4 space-y-4">
        <div className="flex items-center gap-3">
          <GitBranch size={20} className="text-[var(--accent-primary)]" />
          <div className="flex-1">
            <p className="text-sm font-medium font-mono text-[var(--text-primary)]">
              {DEFAULT_REPO_NAME}
            </p>
            <p className="text-xs text-[var(--text-muted)]">
              默认仓库名（私有仓库，自动创建）
            </p>
          </div>
        </div>

        {/* Status */}
        <div className="flex items-center gap-2.5">
          {loading || setupRunning ? (
            <Loader2 size={16} className="text-[var(--accent-warning)] animate-spin" />
          ) : repoExists ? (
            <CheckCircle size={16} className="text-[var(--accent-success)]" />
          ) : (
            <Info size={16} className="text-[var(--accent-primary)]" />
          )}
          <span className="text-sm text-[var(--text-secondary)]">
            {setupStatus || '准备配置...'}
          </span>
        </div>
      </div>

      {/* Auto configuration flow info */}
      <div className="bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-700/50 rounded-lg p-4">
        <p className="text-sm font-medium text-blue-700 dark:text-blue-300 mb-3">自动配置流程</p>
        <div className="space-y-2 text-sm text-blue-600 dark:text-blue-400">
          <div className="flex items-center gap-2">
            <span className="font-medium">1.</span>
            <span>检查 GitHub 账号下是否存在 {DEFAULT_REPO_NAME} 仓库</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="font-medium">2.</span>
            <span>如已存在 → 直接使用该仓库</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="font-medium">3.</span>
            <span>如不存在 → 自动创建私有仓库</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="font-medium">4.</span>
            <span>执行首次同步，上传本地 frago 资源</span>
          </div>
        </div>
      </div>

      {/* Buttons */}
      <div className="flex gap-3 pt-2">
        <button
          type="button"
          onClick={() => setCurrentStep(1)}
          className="btn btn-ghost"
          disabled={setupRunning}
        >
          上一步
        </button>
        <button
          type="button"
          onClick={handleStartSetup}
          className="btn btn-primary flex items-center gap-2"
          disabled={loading || setupRunning}
        >
          {setupRunning ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              配置中...
            </>
          ) : (
            <>
              <FolderGit2 size={16} />
              开始配置
            </>
          )}
        </button>
      </div>
    </div>
  );

  // Step 3: Complete
  const renderStep3 = () => (
    <div className="space-y-5">
      <div className="flex items-center gap-3 mb-4">
        <CheckCircle size={24} className="text-[var(--accent-success)]" />
        <h3 className="text-lg font-semibold text-[var(--text-primary)]">
          配置完成
        </h3>
      </div>

      {/* Success message */}
      <div className="bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-700/50 rounded-lg p-4">
        <p className="text-base font-semibold text-green-700 dark:text-green-300 mb-2">
          🎉 GitHub 同步已成功配置！
        </p>
        <p className="text-sm text-green-600 dark:text-green-400 leading-relaxed">
          你的 frago 资源（commands、skills、recipes）现在可以在多个设备间同步了。
        </p>
      </div>

      {/* Configuration summary */}
      <div className="bg-[var(--bg-elevated)] rounded-lg p-4">
        <p className="text-sm font-semibold text-[var(--text-primary)] mb-3">配置摘要</p>
        <div className="space-y-2">
          <div className="flex items-center gap-2.5">
            <User size={16} className="text-[var(--text-muted)]" />
            <span className="text-sm text-[var(--text-secondary)]">
              GitHub 账号: {completedData?.username || ghStatus?.username || 'unknown'}
            </span>
          </div>
          <div className="flex items-center gap-2.5">
            <GitBranch size={16} className="text-[var(--text-muted)]" />
            <span className="text-sm text-[var(--text-secondary)]">
              同步仓库: {DEFAULT_REPO_NAME} (私有)
            </span>
          </div>
          <div className="flex items-center gap-2.5">
            <FolderSync size={16} className="text-[var(--text-muted)]" />
            <span className="text-sm text-[var(--text-secondary)]">
              同步内容: commands, skills, recipes
            </span>
          </div>
          <div className="flex items-center gap-2.5">
            <CheckCircle size={16} className="text-[var(--text-muted)]" />
            <span className="text-sm text-[var(--accent-success)]">
              首次同步: 已完成
            </span>
          </div>
        </div>
      </div>

      {/* Tip */}
      <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700/30 rounded-lg p-3 flex items-center gap-2.5">
        <Info size={18} className="text-blue-500 dark:text-blue-400 flex-shrink-0" />
        <p className="text-sm text-blue-600 dark:text-blue-300 leading-relaxed">
          提示：在其他设备上登录同一 GitHub 账号，即可自动同步这些资源。
        </p>
      </div>

      {/* Complete button */}
      <div className="flex gap-3 pt-2">
        <button
          type="button"
          onClick={onComplete}
          className="btn btn-primary flex items-center gap-2"
        >
          <Check size={16} />
          完成设置
        </button>
      </div>
    </div>
  );

  const renderCurrentStep = () => {
    switch (currentStep) {
      case 1:
        return renderStep1();
      case 2:
        return renderStep2();
      case 3:
        return renderStep3();
      default:
        return null;
    }
  };

  return (
    <div className="max-w-2xl">
      {/* Progress bar */}
      <ProgressBar />

      {/* Error message */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-4">
          <div className="flex items-start gap-2">
            <AlertCircle size={16} className="text-red-600 dark:text-red-400 mt-0.5 flex-shrink-0" />
            <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
          </div>
        </div>
      )}

      {/* Current step content */}
      <div className="card">{renderCurrentStep()}</div>
    </div>
  );
}
