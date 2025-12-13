/**
 * GitHub Wizard 组件
 * 5步向导：检测gh CLI → 登录GitHub → 创建仓库 → 首次同步 → 完成
 */

import { useState, useEffect } from 'react';
import {
  checkGhCli,
  ghAuthLogin,
  createSyncRepo,
  runFirstSync,
  getSyncResult,
} from '@/api/pywebview';
import { Github, Check, AlertCircle, Loader2, Terminal, FolderGit2, RefreshCw } from 'lucide-react';

interface GitHubWizardProps {
  onComplete: () => void;
  onCancel: () => void;
}

type Step = 1 | 2 | 3 | 4 | 5;

export default function GitHubWizard({ onComplete, onCancel }: GitHubWizardProps) {
  const [currentStep, setCurrentStep] = useState<Step>(1);
  const [ghInstalled, setGhInstalled] = useState(false);
  const [ghVersion, setGhVersion] = useState<string | null>(null);
  const [ghAuthenticated, setGhAuthenticated] = useState(false);
  const [ghUsername, setGhUsername] = useState<string | null>(null);
  const [repoName, setRepoName] = useState('frago-sync');
  const [repoUrl, setRepoUrl] = useState<string | null>(null);
  const [syncOutput, setSyncOutput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [waitingForLogin, setWaitingForLogin] = useState(false);

  // Step 1: 检测 gh CLI
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
      setGhInstalled(status.installed);
      setGhVersion(status.version || null);
      setGhAuthenticated(status.authenticated);
      setGhUsername(status.username || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '检测 gh CLI 失败');
    } finally {
      setLoading(false);
    }
  };

  // Step 2: 登录 GitHub
  const handleLogin = async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await ghAuthLogin();
      if (result.status === 'ok') {
        setWaitingForLogin(true);
      } else {
        setError(result.error || '打开终端失败');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败');
    } finally {
      setLoading(false);
    }
  };

  const handleLoginComplete = async () => {
    const status = await checkGhCli();
    if (status.authenticated) {
      setGhAuthenticated(true);
      setGhUsername(status.username || null);
      setWaitingForLogin(false);
      setCurrentStep(3);
    } else {
      setError('登录未完成，请在终端中完成登录后重试');
    }
  };

  // Step 3: 创建仓库
  const handleCreateRepo = async () => {
    if (!repoName.trim()) {
      setError('请输入仓库名称');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const result = await createSyncRepo(repoName, true);
      if (result.status === 'ok' && result.repo_url) {
        setRepoUrl(result.repo_url);
        setCurrentStep(4);
      } else {
        setError(result.error || '创建仓库失败');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建仓库失败');
    } finally {
      setLoading(false);
    }
  };

  // Step 4: 首次同步
  const handleFirstSync = async () => {
    try {
      setLoading(true);
      setError(null);
      setSyncOutput('正在启动同步...\n');

      const startResult = await runFirstSync();
      if (startResult.status === 'error') {
        setError(startResult.error || '同步失败');
        setLoading(false);
        return;
      }

      // 轮询结果
      const pollInterval = setInterval(async () => {
        const result = await getSyncResult();

        if (result.status === 'running') {
          return;
        }

        clearInterval(pollInterval);
        setLoading(false);

        if (result.status === 'ok') {
          setSyncOutput((prev) => prev + '\n✓ 同步完成\n' + (result.output || ''));
          setCurrentStep(5);
        } else {
          setError(result.error || '同步失败');
          setSyncOutput((prev) => prev + '\n✗ 同步失败\n' + (result.error || ''));
        }
      }, 1000);

      // 超时保护（5 分钟）
      setTimeout(() => {
        clearInterval(pollInterval);
        if (loading) {
          setLoading(false);
          setError('同步超时');
        }
      }, 300000);
    } catch (err) {
      setError(err instanceof Error ? err.message : '同步失败');
      setLoading(false);
    }
  };

  const renderStep1 = () => (
    <div className="space-y-4">
      <div className="flex items-center gap-3 mb-4">
        <Terminal size={24} className="text-[var(--accent-primary)]" />
        <h3 className="text-lg font-semibold text-[var(--text-primary)]">
          步骤 1: 检测 GitHub CLI
        </h3>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-[var(--text-muted)]">
          <Loader2 size={16} className="animate-spin" />
          正在检测...
        </div>
      ) : (
        <>
          {ghInstalled ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-green-600 dark:text-green-400">
                <Check size={16} />
                <span>gh CLI 已安装 (版本: {ghVersion})</span>
              </div>
              {ghAuthenticated ? (
                <div className="flex items-center gap-2 text-green-600 dark:text-green-400">
                  <Check size={16} />
                  <span>已登录 GitHub (用户: {ghUsername})</span>
                </div>
              ) : (
                <div className="flex items-center gap-2 text-yellow-600 dark:text-yellow-400">
                  <AlertCircle size={16} />
                  <span>尚未登录 GitHub</span>
                </div>
              )}
            </div>
          ) : (
            <div className="card bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800">
              <div className="flex items-start gap-2 mb-3">
                <AlertCircle size={16} className="text-yellow-600 dark:text-yellow-400 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-yellow-800 dark:text-yellow-200 mb-2">
                    gh CLI 未安装
                  </p>
                  <p className="text-sm text-yellow-700 dark:text-yellow-300 mb-3">
                    请根据您的操作系统安装 GitHub CLI：
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
                      <span className="text-[var(--text-muted)]"># 其他系统</span>
                      <br />
                      <span className="text-[var(--text-primary)]">https://cli.github.com/</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </>
      )}

      <div className="flex gap-2 pt-4">
        <button onClick={onCancel} className="btn btn-ghost">
          取消
        </button>
        {ghInstalled && (
          <>
            <button onClick={checkGhStatus} className="btn btn-ghost" disabled={loading}>
              重新检测
            </button>
            <button
              onClick={() => setCurrentStep(ghAuthenticated ? 3 : 2)}
              className="btn btn-primary"
            >
              下一步
            </button>
          </>
        )}
      </div>
    </div>
  );

  const renderStep2 = () => (
    <div className="space-y-4">
      <div className="flex items-center gap-3 mb-4">
        <Github size={24} className="text-[var(--accent-primary)]" />
        <h3 className="text-lg font-semibold text-[var(--text-primary)]">
          步骤 2: 登录 GitHub
        </h3>
      </div>

      {waitingForLogin ? (
        <div className="card bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800">
          <div className="space-y-3">
            <p className="text-sm text-blue-700 dark:text-blue-300">
              请在打开的终端窗口中完成 GitHub 登录。
            </p>
            <p className="text-sm text-blue-600 dark:text-blue-400">
              按照终端中的提示选择登录方式（推荐使用浏览器登录）。
            </p>
          </div>
        </div>
      ) : (
        <p className="text-sm text-[var(--text-secondary)]">
          点击下方按钮将打开一个新的终端窗口，请在终端中完成 GitHub 登录。
        </p>
      )}

      <div className="flex gap-2 pt-4">
        <button onClick={() => setCurrentStep(1)} className="btn btn-ghost">
          上一步
        </button>
        {waitingForLogin ? (
          <button onClick={handleLoginComplete} className="btn btn-primary">
            我已完成登录
          </button>
        ) : (
          <button onClick={handleLogin} className="btn btn-primary" disabled={loading}>
            {loading ? '正在打开终端...' : '打开终端登录'}
          </button>
        )}
      </div>
    </div>
  );

  const renderStep3 = () => (
    <div className="space-y-4">
      <div className="flex items-center gap-3 mb-4">
        <FolderGit2 size={24} className="text-[var(--accent-primary)]" />
        <h3 className="text-lg font-semibold text-[var(--text-primary)]">
          步骤 3: 创建同步仓库
        </h3>
      </div>

      <div>
        <label className="block text-sm font-medium text-[var(--text-primary)] mb-2">
          仓库名称
        </label>
        <input
          type="text"
          value={repoName}
          onChange={(e) => setRepoName(e.target.value)}
          placeholder="例如: frago-sync"
          className="w-full px-3 py-2 bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
        />
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          将在你的 GitHub 账号下创建一个私有仓库用于同步 Frago 资源
        </p>
      </div>

      <div className="flex gap-2 pt-4">
        <button onClick={() => setCurrentStep(2)} className="btn btn-ghost">
          上一步
        </button>
        <button
          onClick={handleCreateRepo}
          className="btn btn-primary"
          disabled={loading || !repoName.trim()}
        >
          {loading ? '创建中...' : '创建仓库'}
        </button>
      </div>
    </div>
  );

  const renderStep4 = () => (
    <div className="space-y-4">
      <div className="flex items-center gap-3 mb-4">
        <RefreshCw size={24} className="text-[var(--accent-primary)]" />
        <h3 className="text-lg font-semibold text-[var(--text-primary)]">
          步骤 4: 首次同步
        </h3>
      </div>

      {repoUrl && (
        <div className="mb-4">
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-2">
            同步仓库
          </label>
          <div className="flex items-center gap-2 bg-[var(--bg-subtle)] rounded-md px-3 py-2">
            <Github size={16} className="text-[var(--text-muted)]" />
            <span className="text-sm text-[var(--text-secondary)] font-mono flex-1">
              {repoUrl}
            </span>
          </div>
        </div>
      )}

      <p className="text-sm text-[var(--text-secondary)]">
        现在将进行首次同步，上传本地的 Frago 资源到 GitHub 仓库。
      </p>

      {syncOutput && (
        <div className="p-3 bg-black/5 dark:bg-white/5 rounded-md">
          <pre className="text-xs text-[var(--text-secondary)] whitespace-pre-wrap font-mono">
            {syncOutput}
          </pre>
        </div>
      )}

      <div className="flex gap-2 pt-4">
        {!loading && currentStep === 4 && (
          <button onClick={handleFirstSync} className="btn btn-primary">
            开始同步
          </button>
        )}
        {loading && (
          <div className="flex items-center gap-2 text-[var(--text-muted)]">
            <Loader2 size={16} className="animate-spin" />
            同步中...
          </div>
        )}
      </div>
    </div>
  );

  const renderStep5 = () => (
    <div className="space-y-4">
      <div className="flex items-center gap-3 mb-4">
        <Check size={24} className="text-green-600 dark:text-green-400" />
        <h3 className="text-lg font-semibold text-[var(--text-primary)]">
          配置完成
        </h3>
      </div>

      <div className="card bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800">
        <div className="space-y-2">
          <p className="text-sm font-medium text-green-800 dark:text-green-200">
            GitHub 同步已成功配置！
          </p>
          <p className="text-sm text-green-700 dark:text-green-300">
            你的 Frago 资源（命令、技能、配方）现在可以在多个设备间同步了。
          </p>
        </div>
      </div>

      {syncOutput && (
        <div className="p-3 bg-black/5 dark:bg-white/5 rounded-md">
          <pre className="text-xs text-[var(--text-secondary)] whitespace-pre-wrap font-mono">
            {syncOutput}
          </pre>
        </div>
      )}

      <div className="flex gap-2 pt-4">
        <button onClick={onComplete} className="btn btn-primary">
          完成
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
      case 4:
        return renderStep4();
      case 5:
        return renderStep5();
      default:
        return null;
    }
  };

  return (
    <div className="max-w-2xl">
      {/* 进度指示器 */}
      <div className="mb-8">
        <div className="flex items-center justify-between">
          {[1, 2, 3, 4, 5].map((step) => (
            <div key={step} className="flex items-center">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
                  step < currentStep
                    ? 'bg-green-600 text-white'
                    : step === currentStep
                    ? 'bg-[var(--accent-primary)] text-white'
                    : 'bg-[var(--bg-subtle)] text-[var(--text-muted)]'
                }`}
              >
                {step < currentStep ? <Check size={16} /> : step}
              </div>
              {step < 5 && (
                <div
                  className={`w-12 h-0.5 ${
                    step < currentStep ? 'bg-green-600' : 'bg-[var(--border-color)]'
                  }`}
                />
              )}
            </div>
          ))}
        </div>
        <div className="flex justify-between mt-2 text-xs text-[var(--text-muted)]">
          <span>检测</span>
          <span>登录</span>
          <span>创建仓库</span>
          <span>同步</span>
          <span>完成</span>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="card bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800 mb-4">
          <div className="flex items-start gap-2">
            <AlertCircle size={16} className="text-red-600 dark:text-red-400 mt-0.5" />
            <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
          </div>
        </div>
      )}

      {/* 当前步骤内容 */}
      <div className="card">{renderCurrentStep()}</div>
    </div>
  );
}
