/**
 * 这一页开头那一瞬间，不许说错话。
 *
 * gh 的检查是一次异步请求。在它回来之前，页面对「你连没连上 GitHub」一无所知——
 * 此时若按「没连上」渲染，每一个已经登录的用户每次点进来都会先被闪一下登录引导，
 * 再被换成真页面。那句提示不只是难看，它说的还是假话。
 *
 * 所以这里把「还没问」和「问过了，没有」当成两件事，各走各的画面。
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import type { DataRepoStatus, GhCliStatus } from '@/types/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, vars?: Record<string, unknown>) =>
      vars ? `${key}(${Object.values(vars).join(',')})` : key,
  }),
}));

const checkGhCli = vi.fn();
const getDataRepoStatus = vi.fn();
const getDataRepoSyncStatus = vi.fn();

vi.mock('@/api', () => ({
  checkGhCli: () => checkGhCli(),
  getDataRepoStatus: () => getDataRepoStatus(),
  getDataRepoSyncStatus: () => getDataRepoSyncStatus(),
  getDataRepoPolicy: vi.fn(),
  getDataRepoSyncPrompt: vi.fn(),
  startDataRepoSync: vi.fn(),
  getGhInstallPlan: vi.fn(),
  getGhInstallStatus: vi.fn(),
  startGhInstall: vi.fn(),
  startGhDeviceLogin: vi.fn(),
  getGhDeviceLoginStatus: vi.fn(),
  cancelGhDeviceLogin: vi.fn(),
  getApiMode: () => 'http',
}));

vi.mock('@/stores/appStore', () => ({
  useAppStore: (selector: (s: unknown) => unknown) => selector({ switchPage: vi.fn() }),
}));

import DataRepoPage from '../DataRepoPage';

const READY: GhCliStatus = {
  installed: true,
  authenticated: true,
  verified: true,
  username: 'octocat',
};
const NOT_INSTALLED: GhCliStatus = { installed: false, authenticated: false };

const STATUS: DataRepoStatus = {
  configured: true,
  repo_path: '/home/someone/.frago',
  remote_url: 'https://github.com/someone/frago-working-dir',
  branch: 'main',
  ahead: 4,
  behind: 0,
  pending_total: 26062,
  counts: { modified: 351, deleted: 23710, untracked: 2001 },
  rollup: [
    { area: 'sessions/', count: 23700 },
    { area: 'data/', count: 1915 },
  ],
  files: [{ path: 'books/registry.json', status: 'modified' }],
  truncated: true,
  last_commit: { sha: 'abc123', subject: '上一次备份', committed_at: '2026-08-20T23:49:52+08:00' },
  error: null,
};

/** 一个由测试决定何时兑现的 promise，用来把「还没问回来」那一瞬间定住。 */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe('DataRepoPage 打开的那一瞬间', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getDataRepoStatus.mockResolvedValue(STATUS);
    getDataRepoSyncStatus.mockResolvedValue({ running: false });
  });

  it('gh 还没查回来时，不许出现登录引导', async () => {
    const pending = deferred<GhCliStatus>();
    checkGhCli.mockReturnValue(pending.promise);

    render(<DataRepoPage />);

    // 这一刻我们对登录状态一无所知，任何断言都是猜的。
    expect(screen.queryByText('dataRepo.ghGateTitle')).toBeNull();
    expect(screen.queryByText('dataRepo.ghGateLogin')).toBeNull();
    expect(screen.queryByText('dataRepo.ghGateInstall')).toBeNull();
    // 给的是一句「正在看」，不是一句错的结论。
    expect(screen.getByText('dataRepo.loading')).toBeTruthy();

    pending.resolve(READY);
    await waitFor(() => expect(screen.getByText('dataRepo.title')).toBeTruthy());
  });

  it('已登录的人从头到尾看不到登录引导', async () => {
    checkGhCli.mockResolvedValue(READY);

    render(<DataRepoPage />);

    await waitFor(() => expect(screen.getByText('dataRepo.title')).toBeTruthy());
    expect(screen.queryByText('dataRepo.ghGateTitle')).toBeNull();
  });

  it('确实没装 gh 时，引导照常出来', async () => {
    checkGhCli.mockResolvedValue(NOT_INSTALLED);

    render(<DataRepoPage />);

    await waitFor(() => expect(screen.getByText('dataRepo.ghGateTitle')).toBeTruthy());
    expect(screen.getByText('dataRepo.ghGateInstall')).toBeTruthy();
    // 没连上 GitHub 就不该去问一个两万六千文件的仓库状态。
    expect(getDataRepoStatus).not.toHaveBeenCalled();
  });

  it('gh 查询本身失败，也不谎称已连上', async () => {
    checkGhCli.mockRejectedValue(new Error('network down'));
    const errors = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    render(<DataRepoPage />);

    await waitFor(() => expect(screen.getByText('dataRepo.ghGateTitle')).toBeTruthy());
    errors.mockRestore();
  });
});

describe('DataRepoPage 的正文', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    checkGhCli.mockResolvedValue(READY);
    getDataRepoStatus.mockResolvedValue(STATUS);
    getDataRepoSyncStatus.mockResolvedValue({ running: false });
  });

  it('两万六千个文件靠按目录归并才看得懂，数字要带千分位', async () => {
    render(<DataRepoPage />);

    await waitFor(() => expect(screen.getByText('26,062')).toBeTruthy());
    expect(screen.getByText('sessions/')).toBeTruthy();
    expect(screen.getByText('23,700')).toBeTruthy();
  });

  it('成规模的删除单独示警，不混在普通改动里', async () => {
    render(<DataRepoPage />);

    await waitFor(() =>
      expect(screen.getByText('dataRepo.massDeletionTitle(23,710)')).toBeTruthy()
    );
  });

  it('凭据核验不通时轻声说明，而不是把人赶去重新登录', async () => {
    checkGhCli.mockResolvedValue({ ...READY, verified: false, verify_error: '连不上 github.com' });

    render(<DataRepoPage />);

    await waitFor(() => expect(screen.getByText('连不上 github.com')).toBeTruthy());
    // 关键：这不是登录引导。
    expect(screen.queryByText('dataRepo.ghGateTitle')).toBeNull();
    expect(screen.getByText('dataRepo.title')).toBeTruthy();
  });
});
