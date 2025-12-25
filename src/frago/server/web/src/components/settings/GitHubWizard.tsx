/**
 * GitHub Wizard Component
 * 5-step wizard: Detect gh CLI → Login GitHub → Create repository → First sync → Complete
 */

import { useState, useEffect } from 'react';
import {
  checkGhCli,
  ghAuthLogin,
  createSyncRepo,
  runFirstSync,
  getSyncResult,
  listUserRepos,
  selectExistingRepo,
} from '@/api';
import type { GithubRepo } from '@/types/pywebview';
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
  // Step 3: Repository mode selection
  const [repoMode, setRepoMode] = useState<'create' | 'select'>('create');
  const [existingRepos, setExistingRepos] = useState<GithubRepo[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string | null>(null);
  const [loadingRepos, setLoadingRepos] = useState(false);

  // Step 1: Detect gh CLI
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
      setError(err instanceof Error ? err.message : 'Failed to detect gh CLI');
    } finally {
      setLoading(false);
    }
  };

  // Step 2: Login to GitHub
  const handleLogin = async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await ghAuthLogin();
      if (result.status === 'ok') {
        setWaitingForLogin(true);
      } else {
        setError(result.error || 'Failed to open terminal');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
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
      setError('Login not completed. Please complete the login in the terminal and try again');
    }
  };

  // Step 3: Load existing repository list
  const loadExistingRepos = async () => {
    try {
      setLoadingRepos(true);
      setError(null);
      const result = await listUserRepos(100);
      if (result.status === 'ok' && result.repos) {
        setExistingRepos(result.repos);
      } else {
        setError(result.error || 'Failed to get repository list');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to get repository list');
    } finally {
      setLoadingRepos(false);
    }
  };

  // Load repository list when switching to select mode
  useEffect(() => {
    if (repoMode === 'select' && existingRepos.length === 0 && currentStep === 3) {
      loadExistingRepos();
    }
  }, [repoMode, currentStep]);

  // Step 3: Select existing repository
  const handleSelectRepo = async () => {
    if (!selectedRepo) {
      setError('Please select a repository');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const result = await selectExistingRepo(selectedRepo);
      if (result.status === 'ok' && result.repo_url) {
        setRepoUrl(result.repo_url);
        setCurrentStep(4);
      } else {
        setError(result.error || 'Failed to select repository');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to select repository');
    } finally {
      setLoading(false);
    }
  };

  // Step 3: Create repository
  const handleCreateRepo = async () => {
    if (!repoName.trim()) {
      setError('Please enter repository name');
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
        setError(result.error || 'Failed to create repository');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create repository');
    } finally {
      setLoading(false);
    }
  };

  // Step 4: First sync
  const handleFirstSync = async () => {
    try {
      setLoading(true);
      setError(null);
      setSyncOutput('Starting sync...\n');

      const startResult = await runFirstSync();
      if (startResult.status === 'error') {
        setError(startResult.error || 'Sync failed');
        setLoading(false);
        return;
      }

      // Poll for results
      const pollInterval = setInterval(async () => {
        const result = await getSyncResult();

        if (result.status === 'running') {
          return;
        }

        clearInterval(pollInterval);
        setLoading(false);

        if (result.status === 'ok') {
          setSyncOutput((prev) => prev + '\n✓ Sync completed\n' + (result.output || ''));
          setCurrentStep(5);
        } else {
          setError(result.error || 'Sync failed');
          setSyncOutput((prev) => prev + '\n✗ Sync failed\n' + (result.error || ''));
        }
      }, 1000);

      // Timeout protection (5 minutes)
      setTimeout(() => {
        clearInterval(pollInterval);
        if (loading) {
          setLoading(false);
          setError('Sync timeout');
        }
      }, 300000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sync failed');
      setLoading(false);
    }
  };

  const renderStep1 = () => (
    <div className="space-y-4">
      <div className="flex items-center gap-3 mb-4">
        <Terminal size={24} className="text-[var(--accent-primary)]" />
        <h3 className="text-lg font-semibold text-[var(--text-primary)]">
          Step 1: Detect GitHub CLI
        </h3>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-[var(--text-muted)]">
          <Loader2 size={16} className="animate-spin" />
          Detecting...
        </div>
      ) : (
        <>
          {ghInstalled ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-green-600 dark:text-green-400">
                <Check size={16} />
                <span>gh CLI installed (version: {ghVersion})</span>
              </div>
              {ghAuthenticated ? (
                <div className="flex items-center gap-2 text-green-600 dark:text-green-400">
                  <Check size={16} />
                  <span>Logged in to GitHub (user: {ghUsername})</span>
                </div>
              ) : (
                <div className="flex items-center gap-2 text-yellow-600 dark:text-yellow-400">
                  <AlertCircle size={16} />
                  <span>Not logged in to GitHub</span>
                </div>
              )}
            </div>
          ) : (
            <div className="card bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800">
              <div className="flex items-start gap-2 mb-3">
                <AlertCircle size={16} className="text-yellow-600 dark:text-yellow-400 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-yellow-800 dark:text-yellow-200 mb-2">
                    gh CLI not installed
                  </p>
                  <p className="text-sm text-yellow-700 dark:text-yellow-300 mb-3">
                    Please install GitHub CLI based on your operating system:
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
                      <span className="text-[var(--text-muted)]"># Other systems</span>
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
          Cancel
        </button>
        {ghInstalled && (
          <>
            <button onClick={checkGhStatus} className="btn btn-ghost" disabled={loading}>
              Re-detect
            </button>
            <button
              onClick={() => setCurrentStep(ghAuthenticated ? 3 : 2)}
              className="btn btn-primary"
            >
              Next
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
          Step 2: Login to GitHub
        </h3>
      </div>

      {waitingForLogin ? (
        <div className="card bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800">
          <div className="space-y-3">
            <p className="text-sm text-blue-700 dark:text-blue-300">
              Please complete GitHub login in the opened terminal window.
            </p>
            <p className="text-sm text-blue-600 dark:text-blue-400">
              Follow the prompts in the terminal to choose a login method (browser login recommended).
            </p>
          </div>
        </div>
      ) : (
        <p className="text-sm text-[var(--text-secondary)]">
          Clicking the button below will open a new terminal window. Please complete GitHub login in the terminal.
        </p>
      )}

      <div className="flex gap-2 pt-4">
        <button onClick={() => setCurrentStep(1)} className="btn btn-ghost">
          Previous
        </button>
        {waitingForLogin ? (
          <button onClick={handleLoginComplete} className="btn btn-primary">
            I've Completed Login
          </button>
        ) : (
          <button onClick={handleLogin} className="btn btn-primary" disabled={loading}>
            {loading ? 'Opening terminal...' : 'Open Terminal to Login'}
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
          Step 3: Configure Sync Repository
        </h3>
      </div>

      {/* Mode toggle */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setRepoMode('create')}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            repoMode === 'create'
              ? 'bg-[var(--accent-primary)] text-white'
              : 'bg-[var(--bg-subtle)] text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)]'
          }`}
        >
          Create New Repository
        </button>
        <button
          onClick={() => setRepoMode('select')}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            repoMode === 'select'
              ? 'bg-[var(--accent-primary)] text-white'
              : 'bg-[var(--bg-subtle)] text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)]'
          }`}
        >
          Use Existing Repository
        </button>
      </div>

      {repoMode === 'create' ? (
        /* Create new repository mode */
        <div>
          <label htmlFor="repo-name" className="block text-sm font-medium text-[var(--text-primary)] mb-2">
            Repository Name
          </label>
          <input
            id="repo-name"
            type="text"
            value={repoName}
            onChange={(e) => setRepoName(e.target.value)}
            placeholder="e.g., frago-sync"
            className="w-full px-3 py-2 bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
          />
          <p className="mt-2 text-sm text-[var(--text-muted)]">
            A private repository will be created under your GitHub account to sync frago resources
          </p>
        </div>
      ) : (
        /* Select existing repository mode */
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="block text-sm font-medium text-[var(--text-primary)]">
              Select Repository
            </label>
            <button
              onClick={loadExistingRepos}
              disabled={loadingRepos}
              className="text-xs text-[var(--accent-primary)] hover:underline disabled:opacity-50"
            >
              {loadingRepos ? 'Loading...' : 'Refresh List'}
            </button>
          </div>

          {loadingRepos && existingRepos.length === 0 ? (
            <div className="flex items-center gap-2 text-[var(--text-muted)] py-4">
              <Loader2 size={16} className="animate-spin" />
              Loading repository list...
            </div>
          ) : existingRepos.length === 0 ? (
            <p className="text-sm text-[var(--text-muted)] py-4">
              No repositories found. Please create a new repository
            </p>
          ) : (
            <div className="max-h-60 overflow-y-auto border border-[var(--border-color)] rounded-md">
              {existingRepos.map((repo) => (
                <div
                  key={repo.ssh_url}
                  onClick={() => setSelectedRepo(repo.ssh_url)}
                  className={`px-3 py-2 cursor-pointer flex items-center justify-between hover:bg-[var(--bg-subtle)] ${
                    selectedRepo === repo.ssh_url
                      ? 'bg-[var(--accent-primary)]/10 border-l-2 border-[var(--accent-primary)]'
                      : ''
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <Github size={16} className="text-[var(--text-muted)]" />
                    <div>
                      <span className="text-sm font-medium text-[var(--text-primary)]">
                        {repo.name}
                      </span>
                      {repo.description && (
                        <p className="text-xs text-[var(--text-muted)] truncate max-w-[300px]">
                          {repo.description}
                        </p>
                      )}
                    </div>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    repo.private
                      ? 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400'
                      : 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'
                  }`}>
                    {repo.private ? 'Private' : 'Public'}
                  </span>
                </div>
              ))}
            </div>
          )}

          <p className="mt-2 text-sm text-[var(--text-muted)]">
            Select an existing repository to sync frago resources (private repository recommended)
          </p>
        </div>
      )}

      <div className="flex gap-2 pt-4">
        <button onClick={() => setCurrentStep(2)} className="btn btn-ghost">
          Previous
        </button>
        {repoMode === 'create' ? (
          <button
            onClick={handleCreateRepo}
            className="btn btn-primary"
            disabled={loading || !repoName.trim()}
          >
            {loading ? 'Creating...' : 'Create Repository'}
          </button>
        ) : (
          <button
            onClick={handleSelectRepo}
            className="btn btn-primary"
            disabled={loading || !selectedRepo}
          >
            {loading ? 'Configuring...' : 'Use This Repository'}
          </button>
        )}
      </div>
    </div>
  );

  const renderStep4 = () => (
    <div className="space-y-4">
      <div className="flex items-center gap-3 mb-4">
        <RefreshCw size={24} className="text-[var(--accent-primary)]" />
        <h3 className="text-lg font-semibold text-[var(--text-primary)]">
          Step 4: First Sync
        </h3>
      </div>

      {repoUrl && (
        <div className="mb-4">
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-2">
            Sync Repository
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
        Now performing the first sync to upload local frago resources to the GitHub repository.
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
            Start Sync
          </button>
        )}
        {loading && (
          <div className="flex items-center gap-2 text-[var(--text-muted)]">
            <Loader2 size={16} className="animate-spin" />
            Syncing...
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
          Configuration Complete
        </h3>
      </div>

      <div className="card bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800">
        <div className="space-y-2">
          <p className="text-sm font-medium text-green-800 dark:text-green-200">
            GitHub sync successfully configured!
          </p>
          <p className="text-sm text-green-700 dark:text-green-300">
            Your frago resources (commands, skills, recipes) can now be synced across multiple devices.
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
          Complete
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
      {/* Progress indicator */}
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
          <span>Detect</span>
          <span>Login</span>
          <span>Configure</span>
          <span>Sync</span>
          <span>Complete</span>
        </div>
      </div>

      {/* Error message */}
      {error && (
        <div className="card bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800 mb-4">
          <div className="flex items-start gap-2">
            <AlertCircle size={16} className="text-red-600 dark:text-red-400 mt-0.5" />
            <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
          </div>
        </div>
      )}

      {/* Current step content */}
      <div className="card">{renderCurrentStep()}</div>
    </div>
  );
}
