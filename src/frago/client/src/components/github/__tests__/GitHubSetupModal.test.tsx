/**
 * 这个窗口存在的理由：设备码登录长得和钓鱼一模一样。
 *
 * 它让人去 github.com 输一串自己没申请过的码，再点「授权」。分不清真假的用户
 * 要么中途放弃，要么养成闭眼点授权的习惯——两种都比不登录更糟。所以四步说明
 * 必须在码出现之前就摆在那儿，而不是出了码再补解释。
 *
 * 装的那一半同理：先说清这台机器打算跑什么，再让人按下去。
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { GhCliStatus } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // 带插值的键回成 "key(参数)"，好断言值真的传进去了。
    t: (key: string, vars?: Record<string, unknown>) =>
      vars ? `${key}(${Object.values(vars).join(',')})` : key,
  }),
}));

const getGhInstallPlan = vi.fn();
const getGhInstallStatus = vi.fn();
const startGhInstall = vi.fn();
const startGhDeviceLogin = vi.fn();
const getGhDeviceLoginStatus = vi.fn();
const cancelGhDeviceLogin = vi.fn();

vi.mock('@/api', () => ({
  getGhInstallPlan: () => getGhInstallPlan(),
  getGhInstallStatus: () => getGhInstallStatus(),
  startGhInstall: () => startGhInstall(),
  startGhDeviceLogin: () => startGhDeviceLogin(),
  getGhDeviceLoginStatus: () => getGhDeviceLoginStatus(),
  cancelGhDeviceLogin: () => cancelGhDeviceLogin(),
  checkGhCli: vi.fn(),
  getApiMode: () => 'http',
}));

import GitHubSetupModal from '../GitHubSetupModal';

const NOT_INSTALLED: GhCliStatus = { installed: false, authenticated: false };
const NOT_LOGGED_IN: GhCliStatus = { installed: true, authenticated: false };

const BREW_PLAN = {
  method: 'brew',
  command: 'brew install gh',
  needs_path_hint: false,
  manual_url: 'https://cli.github.com/',
};

function renderModal(ghStatus: GhCliStatus) {
  const onStatusChange = vi.fn();
  const result = render(
    <GitHubSetupModal
      isOpen
      onClose={vi.fn()}
      ghStatus={ghStatus}
      onStatusChange={onStatusChange}
    />
  );
  return { ...result, onStatusChange };
}

describe('GitHubSetupModal 的安装那一半', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getGhInstallPlan.mockResolvedValue(BREW_PLAN);
    getGhInstallStatus.mockResolvedValue({ status: 'idle', message: '', log: [] });
    startGhInstall.mockResolvedValue({ status: 'ok', already_running: false, method: 'brew' });
  });

  it('先摆出这台机器打算跑的命令，再给按钮', async () => {
    renderModal(NOT_INSTALLED);

    await waitFor(() => expect(screen.getByText('brew install gh')).toBeTruthy());
    expect(screen.getByText('githubGuard.planBrew')).toBeTruthy();
    expect(screen.getByText('githubGuard.startInstall')).toBeTruthy();
  });

  it('三条理由一条都不少——这是用户唯一能判断值不值的依据', async () => {
    renderModal(NOT_INSTALLED);

    await waitFor(() => expect(screen.getByText('githubGuard.why1')).toBeTruthy());
    expect(screen.getByText('githubGuard.why2')).toBeTruthy();
    expect(screen.getByText('githubGuard.why3')).toBeTruthy();
  });

  it('按下去才开装，装的时候把输出显出来', async () => {
    renderModal(NOT_INSTALLED);

    await waitFor(() => expect(screen.getByText('githubGuard.startInstall')).toBeTruthy());
    expect(startGhInstall).not.toHaveBeenCalled();

    getGhInstallStatus.mockResolvedValue({
      status: 'running',
      method: 'brew',
      message: '',
      log: ['$ brew install gh', '==> Downloading'],
    });
    fireEvent.click(screen.getByText('githubGuard.startInstall'));

    expect(startGhInstall).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.getByText(/==> Downloading/)).toBeTruthy());
  });

  it('没账号的人有去处，不是死路', async () => {
    renderModal(NOT_INSTALLED);

    await waitFor(() => expect(screen.getByText('githubGuard.registerLink')).toBeTruthy());
    const link = screen.getByText('githubGuard.registerLink').closest('a');
    expect(link?.getAttribute('href')).toBe('https://github.com/signup');
  });
});

describe('GitHubSetupModal 的登录那一半', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getGhDeviceLoginStatus.mockResolvedValue({
      status: 'ok',
      completed: false,
      authenticated: false,
    });
  });

  it('四步说明在码出现之前就在那儿', async () => {
    renderModal(NOT_LOGGED_IN);

    // 还没点登录，说明已经全文可见。
    expect(startGhDeviceLogin).not.toHaveBeenCalled();
    for (const step of ['step1', 'step2', 'step3', 'step4']) {
      expect(screen.getByText(`githubGuard.${step}Title`)).toBeTruthy();
      expect(screen.getByText(`githubGuard.${step}Text`)).toBeTruthy();
    }
  });

  it('码和 GitHub 链接一起摆出来——少一样这一步就走不完', async () => {
    startGhDeviceLogin.mockResolvedValue({
      status: 'ok',
      code: '2741-EE59',
      url: 'https://github.com/login/device',
    });
    renderModal(NOT_LOGGED_IN);

    fireEvent.click(screen.getByText('githubGuard.startLogin'));

    await waitFor(() => expect(screen.getByText('2741-EE59')).toBeTruthy());
    const link = screen.getByText('githubGuard.openGitHub').closest('a');
    expect(link?.getAttribute('href')).toBe('https://github.com/login/device');
  });

  it('对面授权完，这里自己变成已登录', async () => {
    startGhDeviceLogin.mockResolvedValue({
      status: 'ok',
      code: '2741-EE59',
      url: 'https://github.com/login/device',
    });
    const { onStatusChange } = renderModal(NOT_LOGGED_IN);

    fireEvent.click(screen.getByText('githubGuard.startLogin'));
    await waitFor(() => expect(screen.getByText('2741-EE59')).toBeTruthy());

    getGhDeviceLoginStatus.mockResolvedValue({
      status: 'ok',
      completed: true,
      authenticated: true,
      username: 'octocat',
    });

    await waitFor(
      () => expect(screen.getByText('githubGuard.loginSuccess(octocat)')).toBeTruthy(),
      { timeout: 4000 }
    );
    expect(onStatusChange).toHaveBeenCalled();
  });

  it('起不来就说为什么，不留个转圈的按钮', async () => {
    startGhDeviceLogin.mockResolvedValue({
      status: 'error',
      error: 'gh CLI not found. Please install GitHub CLI first.',
    });
    renderModal(NOT_LOGGED_IN);

    fireEvent.click(screen.getByText('githubGuard.startLogin'));

    await waitFor(() =>
      expect(screen.getByText(/gh CLI not found/)).toBeTruthy()
    );
  });

  it('半路走开的登录能撤掉，不把 gh 进程挂在那儿轮询到码过期', async () => {
    startGhDeviceLogin.mockResolvedValue({
      status: 'ok',
      code: '2741-EE59',
      url: 'https://github.com/login/device',
    });
    cancelGhDeviceLogin.mockResolvedValue({ status: 'ok' });
    renderModal(NOT_LOGGED_IN);

    fireEvent.click(screen.getByText('githubGuard.startLogin'));
    await waitFor(() => expect(screen.getByText('2741-EE59')).toBeTruthy());

    fireEvent.click(screen.getByText('githubGuard.cancelLogin'));

    expect(cancelGhDeviceLogin).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByText('2741-EE59')).toBeNull());
  });
});
