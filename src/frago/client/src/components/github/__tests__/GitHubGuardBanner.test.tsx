/**
 * 这条横幅的意义全在「关不掉」上。
 *
 * 它警告的事情是：工作目录此刻没有任何备份。这件事不会因为用户点过一次叉就
 * 不成立，而代价要等到硬盘坏掉那天才显形——所以这里锁死四条：装好之前一直在、
 * 登录之前一直在、两样齐了自己消失、任何时候都不给「忽略／下次别提醒」的出口。
 *
 * 另加一条边界：桌面壳（pywebview）走自己的原生路径，不碰这些接口，横幅不该出现。
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import type { GhCliStatus } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const checkGhCli = vi.fn();
const getGhInstallStatus = vi.fn();
const getApiMode = vi.fn();

vi.mock('@/api', () => ({
  checkGhCli: (...args: unknown[]) => checkGhCli(...args),
  getGhInstallStatus: (...args: unknown[]) => getGhInstallStatus(...args),
  getGhInstallPlan: vi.fn(),
  startGhInstall: vi.fn(),
  startGhDeviceLogin: vi.fn(),
  getGhDeviceLoginStatus: vi.fn(),
  cancelGhDeviceLogin: vi.fn(),
  getApiMode: () => getApiMode(),
}));

import GitHubGuardBanner from '../GitHubGuardBanner';

const NOT_INSTALLED: GhCliStatus = { installed: false, authenticated: false };
const NOT_LOGGED_IN: GhCliStatus = { installed: true, authenticated: false, version: '2.63.2' };
const READY: GhCliStatus = {
  installed: true,
  authenticated: true,
  version: '2.63.2',
  username: 'octocat',
};

describe('GitHubGuardBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getApiMode.mockReturnValue('http');
    getGhInstallStatus.mockResolvedValue({ status: 'idle', message: '', log: [] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('没装 gh 时催装', async () => {
    checkGhCli.mockResolvedValue(NOT_INSTALLED);
    render(<GitHubGuardBanner />);

    await waitFor(() =>
      expect(screen.getByText('githubGuard.bannerNotInstalledTitle')).toBeTruthy()
    );
    expect(screen.getByText('githubGuard.installNow')).toBeTruthy();
  });

  it('装了没登录时催登录', async () => {
    checkGhCli.mockResolvedValue(NOT_LOGGED_IN);
    render(<GitHubGuardBanner />);

    await waitFor(() =>
      expect(screen.getByText('githubGuard.bannerNotAuthTitle')).toBeTruthy()
    );
    expect(screen.getByText('githubGuard.loginNow')).toBeTruthy();
  });

  it('两样齐了就自己消失', async () => {
    checkGhCli.mockResolvedValue(READY);
    const { container } = render(<GitHubGuardBanner />);

    await waitFor(() => expect(checkGhCli).toHaveBeenCalled());
    expect(container.innerHTML).toBe('');
  });

  it('不提供关闭/忽略/下次别提醒的出口', async () => {
    checkGhCli.mockResolvedValue(NOT_INSTALLED);
    const { container } = render(<GitHubGuardBanner />);

    await waitFor(() =>
      expect(screen.getByText('githubGuard.bannerNotInstalledTitle')).toBeTruthy()
    );

    // 横幅上只该有三个按钮：主行动、看说明、重新检测。多出来的一定是退出口。
    const labels = Array.from(container.querySelectorAll('button')).map(
      (button) => button.getAttribute('aria-label') || button.textContent || ''
    );
    expect(labels).toHaveLength(3);
    expect(labels).toEqual(
      expect.arrayContaining([
        'githubGuard.installNow',
        'githubGuard.learnMore',
        'githubGuard.recheck',
      ])
    );
  });

  it('桌面壳里不出现', async () => {
    getApiMode.mockReturnValue('pywebview');
    checkGhCli.mockResolvedValue(NOT_INSTALLED);
    const { container } = render(<GitHubGuardBanner />);

    expect(container.innerHTML).toBe('');
    expect(checkGhCli).not.toHaveBeenCalled();
  });

  it('查不通时不乱报警，保持上一次的判断', async () => {
    checkGhCli.mockRejectedValue(new Error('network down'));
    const errors = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const { container } = render(<GitHubGuardBanner />);

    await waitFor(() => expect(checkGhCli).toHaveBeenCalled());
    expect(container.innerHTML).toBe('');
    errors.mockRestore();
  });
});
