/**
 * GitHubSetupModal
 *
 * The explaining window behind the GitHub banner. Two jobs, picked by what is
 * actually missing:
 *
 * - gh not installed: say what frago loses without it, show what this machine
 *   is about to run, then run it and stream the output.
 * - gh installed but not logged in: walk through GitHub's device-code login
 *   step by step *before* the code appears, so nobody is staring at an
 *   eight-character string wondering what it authorizes.
 *
 * The step-by-step matters more than it looks. Device login sends people to
 * github.com to type a code into a page they did not open themselves — that is
 * the exact shape of a phishing flow, and a user who cannot tell the two apart
 * either bails out or, worse, learns to click through prompts like it.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { createPortal } from 'react-dom';
import {
  X,
  ShieldCheck,
  Download,
  ExternalLink,
  Copy,
  Check,
  Loader2,
  AlertCircle,
  Terminal,
} from 'lucide-react';
import * as api from '@/api';
import type {
  GhCliStatus,
  GhInstallPlan,
  GhInstallStatus,
  GhDeviceLogin,
} from '@/types/api';

interface GitHubSetupModalProps {
  isOpen: boolean;
  onClose: () => void;
  ghStatus: GhCliStatus | null;
  /** Re-runs the gh check upstream so the banner disappears the moment it can. */
  onStatusChange: () => void;
}

/** Copy that still works on a plain-http page, where navigator.clipboard is undefined. */
async function copyText(value: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // Fall through to the textarea trick below.
  }
  try {
    const scratch = document.createElement('textarea');
    scratch.value = value;
    scratch.setAttribute('readonly', '');
    scratch.style.position = 'fixed';
    scratch.style.opacity = '0';
    document.body.appendChild(scratch);
    scratch.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(scratch);
    return ok;
  } catch {
    return false;
  }
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="text-sm font-semibold text-[var(--text-primary)] mb-2">{children}</h4>
  );
}

function CodeLine({ value }: { value: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (await copyText(value)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <div className="flex items-center gap-2 rounded-md bg-[var(--bg-tertiary)] px-3 py-2">
      <code className="flex-1 min-w-0 overflow-x-auto whitespace-pre text-xs font-mono text-[var(--text-primary)]">
        {value}
      </code>
      <button
        type="button"
        onClick={handleCopy}
        className="shrink-0 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
        aria-label={t('githubGuard.copyCode')}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
    </div>
  );
}

export default function GitHubSetupModal({
  isOpen,
  onClose,
  ghStatus,
  onStatusChange,
}: GitHubSetupModalProps) {
  const { t } = useTranslation();
  const needsInstall = !ghStatus?.installed;

  // ---- install state ----
  const [plan, setPlan] = useState<GhInstallPlan | null>(null);
  const [install, setInstall] = useState<GhInstallStatus | null>(null);
  const [installStarting, setInstallStarting] = useState(false);

  // ---- login state ----
  const [login, setLogin] = useState<GhDeviceLogin | null>(null);
  const [loginStarting, setLoginStarting] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loggedInAs, setLoggedInAs] = useState<string | null>(null);
  const [codeCopied, setCodeCopied] = useState(false);

  const logRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen, onClose]);

  // What would this machine do? Asked on open so the user sees the plan before
  // agreeing to it, not after.
  useEffect(() => {
    if (!isOpen || !needsInstall) return;
    let cancelled = false;
    api
      .getGhInstallPlan()
      .then((result) => {
        if (!cancelled) setPlan(result);
      })
      .catch((err) => console.error('Failed to read gh install plan:', err));
    api
      .getGhInstallStatus()
      .then((result) => {
        // Picks up an install that is already running — e.g. the user closed
        // this window and reopened it.
        if (!cancelled && result.status !== 'idle') setInstall(result);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [isOpen, needsInstall]);

  // Poll the install while it runs. The first read happens straight away —
  // waiting out a full interval before the first line of output appears reads
  // as "nothing happened" to whoever just pressed the button.
  useEffect(() => {
    if (!isOpen || install?.status !== 'running') return;
    let cancelled = false;
    const poll = async () => {
      try {
        const result = await api.getGhInstallStatus();
        if (cancelled) return;
        setInstall(result);
        if (result.status === 'success') onStatusChange();
      } catch (err) {
        console.error('Failed to poll gh install status:', err);
      }
    };
    poll();
    const timer = setInterval(poll, 1500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [isOpen, install?.status, onStatusChange]);

  // Keep the newest install output in view.
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [install?.log]);

  // Poll the device login while GitHub waits for the user.
  useEffect(() => {
    if (!isOpen || !login?.code || loggedInAs) return;
    const timer = setInterval(async () => {
      try {
        const result = await api.getGhDeviceLoginStatus();
        if (result.authenticated) {
          setLoggedInAs(result.username || 'GitHub');
          setLogin(null);
          onStatusChange();
        } else if (result.completed && result.status === 'error') {
          setLoginError(result.error || t('githubGuard.loginFailed'));
          setLogin(null);
        }
      } catch (err) {
        console.error('Failed to poll gh login status:', err);
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [isOpen, login?.code, loggedInAs, onStatusChange, t]);

  const handleInstall = useCallback(async () => {
    // The running state is only claimed once the server has actually taken the
    // job. Claiming it first would let the poller read back "idle" — the state
    // before the request landed — and quietly stop polling a live install.
    setInstallStarting(true);
    try {
      await api.startGhInstall();
      setInstall({ status: 'running', message: t('githubGuard.installRunning'), log: [] });
    } catch (err) {
      console.error('Failed to start gh install:', err);
      setInstall({
        status: 'error',
        message: t('githubGuard.installFailed'),
        error: String(err),
        log: [],
      });
    } finally {
      setInstallStarting(false);
    }
  }, [t]);

  const handleLogin = useCallback(async () => {
    setLoginStarting(true);
    setLoginError(null);
    try {
      const result = await api.startGhDeviceLogin();
      if (result.status === 'ok' && result.code) {
        setLogin(result);
      } else {
        setLoginError(result.error || t('githubGuard.loginFailed'));
      }
    } catch (err) {
      console.error('Failed to start gh device login:', err);
      setLoginError(String(err));
    } finally {
      setLoginStarting(false);
    }
  }, [t]);

  const handleCancelLogin = useCallback(async () => {
    try {
      await api.cancelGhDeviceLogin();
    } catch (err) {
      console.error('Failed to cancel gh login:', err);
    }
    setLogin(null);
  }, []);

  const handleCopyCode = useCallback(async () => {
    if (!login?.code) return;
    if (await copyText(login.code)) {
      setCodeCopied(true);
      setTimeout(() => setCodeCopied(false), 1500);
    }
  }, [login?.code]);

  if (!isOpen) return null;

  const planText =
    plan?.method === 'brew'
      ? t('githubGuard.planBrew')
      : plan?.method === 'winget'
        ? t('githubGuard.planWinget')
        : t('githubGuard.planBinary');

  return createPortal(
    <div
      className="fixed inset-0 z-[1100] flex items-start justify-center overflow-y-auto bg-black/50 p-4 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="my-8 w-full max-w-2xl rounded-lg border border-[var(--border-color)] bg-[var(--bg-base)] shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--border-color)] p-4">
          <h3 className="flex items-center gap-2 text-lg font-semibold text-[var(--text-primary)]">
            <ShieldCheck size={20} className="text-[var(--accent-primary)]" />
            {needsInstall ? t('githubGuard.installTitle') : t('githubGuard.loginTitle')}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="text-[var(--text-muted)] transition-colors hover:text-[var(--text-primary)]"
            aria-label={t('githubGuard.close')}
          >
            <X size={20} />
          </button>
        </div>

        <div className="space-y-5 p-5">
          {/* Why frago wants this at all — the same answer whichever half is missing. */}
          <section>
            <SectionTitle>{t('githubGuard.whyTitle')}</SectionTitle>
            <ul className="space-y-2 text-sm text-[var(--text-secondary)]">
              {[t('githubGuard.why1'), t('githubGuard.why2'), t('githubGuard.why3')].map(
                (line) => (
                  <li key={line} className="flex gap-2">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--accent-primary)]" />
                    <span>{line}</span>
                  </li>
                )
              )}
            </ul>
          </section>

          {needsInstall ? (
            <>
              {/* What is about to run on this machine */}
              <section>
                <SectionTitle>{t('githubGuard.planTitle')}</SectionTitle>
                <p className="mb-2 text-sm text-[var(--text-secondary)]">{planText}</p>
                {plan?.command && <CodeLine value={plan.command} />}
              </section>

              {install?.status === 'success' ? (
                <div className="flex items-start gap-2 rounded-md border border-green-500/30 bg-green-500/10 p-3 text-sm text-[var(--text-primary)]">
                  <Check size={16} className="mt-0.5 shrink-0 text-green-500" />
                  <div className="min-w-0 flex-1">
                    <p>{t('githubGuard.installDone', { version: install.message })}</p>
                    {install.path_hint && (
                      <div className="mt-3">
                        <SectionTitle>{t('githubGuard.pathHintTitle')}</SectionTitle>
                        <p className="mb-2 text-sm text-[var(--text-secondary)]">
                          {t('githubGuard.pathHintText')}
                        </p>
                        <CodeLine value={install.path_hint} />
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={handleInstall}
                  disabled={installStarting || install?.status === 'running'}
                  className="inline-flex items-center gap-2 rounded-md bg-[var(--accent-primary)] px-4 py-2 text-sm font-medium text-[var(--text-on-accent)] transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  {installStarting || install?.status === 'running' ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Download size={16} />
                  )}
                  {installStarting || install?.status === 'running'
                    ? t('githubGuard.installing')
                    : t('githubGuard.startInstall')}
                </button>
              )}

              {install?.status === 'running' && (
                <p className="text-sm text-[var(--text-secondary)]">
                  {t('githubGuard.installRunning')}
                </p>
              )}

              {install?.status === 'error' && (
                <div className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm">
                  <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-500" />
                  <div className="min-w-0">
                    <p className="font-medium text-[var(--text-primary)]">
                      {t('githubGuard.installFailed')}
                    </p>
                    <p className="mt-1 break-words text-[var(--text-secondary)]">
                      {install.error}
                    </p>
                  </div>
                </div>
              )}

              {install && install.log.length > 0 && (
                <section>
                  <SectionTitle>
                    <span className="inline-flex items-center gap-1">
                      <Terminal size={14} />
                      {t('githubGuard.installLogTitle')}
                    </span>
                  </SectionTitle>
                  <pre
                    ref={logRef}
                    className="max-h-40 overflow-auto rounded-md bg-[var(--bg-tertiary)] p-3 text-xs font-mono leading-relaxed text-[var(--text-secondary)]"
                  >
                    {install.log.join('\n')}
                  </pre>
                </section>
              )}

              {/* Two escape hatches: install it by hand, or get an account first. */}
              <section className="border-t border-[var(--border-color)] pt-4">
                <SectionTitle>{t('githubGuard.manualTitle')}</SectionTitle>
                <p className="mb-2 text-sm text-[var(--text-secondary)]">
                  {t('githubGuard.manualDownload')}
                </p>
                <a
                  href={plan?.manual_url || 'https://cli.github.com/'}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-sm text-[var(--accent-primary)] hover:underline"
                >
                  cli.github.com
                  <ExternalLink size={14} />
                </a>
              </section>

              <section className="border-t border-[var(--border-color)] pt-4">
                <SectionTitle>{t('githubGuard.noAccountTitle')}</SectionTitle>
                <p className="mb-2 text-sm text-[var(--text-secondary)]">
                  {t('githubGuard.noAccountText')}
                </p>
                <a
                  href="https://github.com/signup"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-sm text-[var(--accent-primary)] hover:underline"
                >
                  {t('githubGuard.registerLink')}
                  <ExternalLink size={14} />
                </a>
              </section>
            </>
          ) : (
            <>
              {/* The four steps, spelled out before any code appears. */}
              <section>
                <SectionTitle>{t('githubGuard.stepsTitle')}</SectionTitle>
                <ol className="space-y-3">
                  {[
                    [t('githubGuard.step1Title'), t('githubGuard.step1Text')],
                    [t('githubGuard.step2Title'), t('githubGuard.step2Text')],
                    [t('githubGuard.step3Title'), t('githubGuard.step3Text')],
                    [t('githubGuard.step4Title'), t('githubGuard.step4Text')],
                  ].map(([title, text]) => (
                    <li
                      key={title}
                      className="rounded-md border border-[var(--border-color)] bg-[var(--bg-card)] p-3"
                    >
                      <p className="text-sm font-medium text-[var(--text-primary)]">{title}</p>
                      <p className="mt-1 text-sm text-[var(--text-secondary)]">{text}</p>
                    </li>
                  ))}
                </ol>
              </section>

              {loggedInAs ? (
                <div className="flex items-center gap-2 rounded-md border border-green-500/30 bg-green-500/10 p-3 text-sm text-[var(--text-primary)]">
                  <Check size={16} className="shrink-0 text-green-500" />
                  {t('githubGuard.loginSuccess', { username: loggedInAs })}
                </div>
              ) : login?.code ? (
                <section className="rounded-md border border-[var(--accent-primary-20)] bg-[var(--accent-primary-10)] p-4">
                  <SectionTitle>{t('githubGuard.codeLabel')}</SectionTitle>
                  <div className="flex flex-wrap items-center gap-3">
                    <code className="rounded-md bg-[var(--bg-base)] px-4 py-2 text-2xl font-mono tracking-[0.2em] text-[var(--text-primary)]">
                      {login.code}
                    </code>
                    <button
                      type="button"
                      onClick={handleCopyCode}
                      className="inline-flex items-center gap-1 rounded-md border border-[var(--border-color)] px-3 py-2 text-sm text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]"
                    >
                      {codeCopied ? <Check size={14} /> : <Copy size={14} />}
                      {codeCopied ? t('githubGuard.codeCopied') : t('githubGuard.copyCode')}
                    </button>
                    <a
                      href={login.url || 'https://github.com/login/device'}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 rounded-md bg-[var(--accent-primary)] px-3 py-2 text-sm font-medium text-[var(--text-on-accent)] hover:opacity-90"
                    >
                      {t('githubGuard.openGitHub')}
                      <ExternalLink size={14} />
                    </a>
                  </div>
                  <p className="mt-3 flex items-center gap-2 text-sm text-[var(--text-secondary)]">
                    <Loader2 size={14} className="animate-spin" />
                    {t('githubGuard.waiting')}
                  </p>
                  <button
                    type="button"
                    onClick={handleCancelLogin}
                    className="mt-2 text-sm text-[var(--text-muted)] hover:underline"
                  >
                    {t('githubGuard.cancelLogin')}
                  </button>
                </section>
              ) : (
                <button
                  type="button"
                  onClick={handleLogin}
                  disabled={loginStarting}
                  className="inline-flex items-center gap-2 rounded-md bg-[var(--accent-primary)] px-4 py-2 text-sm font-medium text-[var(--text-on-accent)] transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  {loginStarting && <Loader2 size={16} className="animate-spin" />}
                  {loginStarting ? t('githubGuard.starting') : t('githubGuard.startLogin')}
                </button>
              )}

              {loginError && (
                <div className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm">
                  <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-500" />
                  <p className="min-w-0 break-words text-[var(--text-secondary)]">{loginError}</p>
                </div>
              )}

              <section className="border-t border-[var(--border-color)] pt-4">
                <SectionTitle>{t('githubGuard.noAccountTitle')}</SectionTitle>
                <p className="mb-2 text-sm text-[var(--text-secondary)]">
                  {t('githubGuard.noAccountText')}
                </p>
                <a
                  href="https://github.com/signup"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-sm text-[var(--accent-primary)] hover:underline"
                >
                  {t('githubGuard.registerLink')}
                  <ExternalLink size={14} />
                </a>
              </section>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
