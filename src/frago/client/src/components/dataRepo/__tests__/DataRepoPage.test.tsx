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
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { DataRepoStatus, GhCliStatus, PendingFile } from '@/types/api';

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
    // 目录名与数量同时出现在柱状图和文件分组的组头
    expect(screen.getAllByText('sessions/').length).toBeGreaterThan(0);
    expect(screen.getAllByText('23,700').length).toBeGreaterThan(0);
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

/** 样本里造 n 条同一目录下的路径。 */
function paths(area: string, n: number, status: PendingFile['status'] = 'modified'): PendingFile[] {
  return Array.from({ length: n }, (_, i) => ({ path: `${area}f${i}.md`, status }));
}

function groupOf(area: string): HTMLElement {
  const el = document.querySelector<HTMLElement>(`[data-area-group="${area}"]`);
  if (!el) throw new Error(`no group ${area}`);
  return el;
}

function rowsIn(area: string): number {
  return groupOf(area).querySelectorAll('[data-file-row]').length;
}

describe('DataRepoPage 的统计条', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    checkGhCli.mockResolvedValue(READY);
    getDataRepoStatus.mockResolvedValue(STATUS);
    getDataRepoSyncStatus.mockResolvedValue({ running: false });
  });

  it('各类改动数并进「Files pending」下的一行小字，不再有彩色小胶囊', async () => {
    render(<DataRepoPage />);

    await waitFor(() =>
      expect(
        screen.getByText(
          '351 dataRepo.status.modified · 2,001 dataRepo.status.untracked · 23,710 dataRepo.status.deleted'
        )
      ).toBeTruthy()
    );
    expect(screen.queryByText('●')).toBeNull();
  });

  it('落后数为 0 也照样写出来', async () => {
    render(<DataRepoPage />);

    await waitFor(() => expect(screen.getByText('dataRepo.behind(0)')).toBeTruthy());
  });

  it('最近一次提交带提交号', async () => {
    render(<DataRepoPage />);

    await waitFor(() => expect(screen.getByText('abc123')).toBeTruthy());
    expect(screen.getByText('上一次备份')).toBeTruthy();
  });

  it('全部备份完毕是中性提示，不是绿框', async () => {
    getDataRepoStatus.mockResolvedValue({
      ...STATUS,
      pending_total: 0,
      ahead: 0,
      counts: {},
      rollup: [],
      files: [],
      truncated: false,
    });

    render(<DataRepoPage />);

    const note = await screen.findByText('dataRepo.allBackedUp');
    expect(note.className).not.toMatch(/green/);
  });
});

describe('DataRepoPage 的文件分组', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    checkGhCli.mockResolvedValue(READY);
    getDataRepoSyncStatus.mockResolvedValue({ running: false });
  });

  // 旧形状：rollup 只有总数，明细只有封顶的平铺样本。todo/ 实有 71 条，样本里只进了 61 条。
  const TRUNCATED: DataRepoStatus = {
    ...STATUS,
    pending_total: 71 + 20 + 3 + 1,
    counts: { modified: 80, untracked: 15 },
    rollup: [
      { area: 'todo/', count: 71 },
      { area: 'data/', count: 20 },
      { area: 'books/', count: 3 },
      { area: 'workbench_titles.json', count: 1 },
    ],
    files: [
      ...paths('todo/', 61),
      ...paths('data/', 15),
      ...paths('data/', 5, 'untracked').map((f, i) => ({ ...f, path: `data/n${i}.md` })),
      ...paths('books/', 3),
    ],
  };

  it('组头计数取目录汇总，样本不全也不少报', async () => {
    getDataRepoStatus.mockResolvedValue(TRUNCATED);
    render(<DataRepoPage />);

    await waitFor(() => expect(groupOf('todo/')).toBeTruthy());
    expect(within(groupOf('todo/')).getByText('71')).toBeTruthy();
    expect(within(groupOf('todo/')).getByText('dataRepo.moreInArea(63,todo/)')).toBeTruthy();
  });

  it('样本不全的组不报细分，样本齐全的组照报', async () => {
    getDataRepoStatus.mockResolvedValue(TRUNCATED);
    render(<DataRepoPage />);

    await waitFor(() => expect(groupOf('data/')).toBeTruthy());
    expect(within(groupOf('todo/')).getByRole('button').textContent).not.toMatch(/dataRepo\.status/);
    expect(
      within(groupOf('data/')).getByText('15 dataRepo.status.modified · 5 dataRepo.status.untracked')
    ).toBeTruthy();
  });

  it('每组至多列 8 条，默认只展开前两组', async () => {
    getDataRepoStatus.mockResolvedValue(TRUNCATED);
    render(<DataRepoPage />);

    await waitFor(() => expect(groupOf('todo/')).toBeTruthy());
    expect(rowsIn('todo/')).toBe(8);
    expect(rowsIn('data/')).toBe(8);
    expect(rowsIn('books/')).toBe(0);
    expect(rowsIn('workbench_titles.json')).toBe(0);
  });

  it('点组头展开，再点收起；路径去掉目录前缀', async () => {
    getDataRepoStatus.mockResolvedValue(TRUNCATED);
    render(<DataRepoPage />);

    await waitFor(() => expect(groupOf('books/')).toBeTruthy());
    fireEvent.click(within(groupOf('books/')).getByRole('button'));
    expect(rowsIn('books/')).toBe(3);
    expect(within(groupOf('books/')).getByText('f0.md')).toBeTruthy();
    fireEvent.click(within(groupOf('books/')).getByRole('button'));
    expect(rowsIn('books/')).toBe(0);
  });

  it('样本里一条都没有的组，展开后只有尾行', async () => {
    getDataRepoStatus.mockResolvedValue(TRUNCATED);
    render(<DataRepoPage />);

    await waitFor(() => expect(groupOf('workbench_titles.json')).toBeTruthy());
    fireEvent.click(within(groupOf('workbench_titles.json')).getByRole('button'));
    expect(rowsIn('workbench_titles.json')).toBe(0);
    expect(
      within(groupOf('workbench_titles.json')).getByText(
        'dataRepo.moreInArea(1,workbench_titles.json)'
      )
    ).toBeTruthy();
  });

  it('重新清点不打乱手动展开的组', async () => {
    getDataRepoStatus.mockResolvedValue(TRUNCATED);
    render(<DataRepoPage />);

    await waitFor(() => expect(groupOf('books/')).toBeTruthy());
    fireEvent.click(within(groupOf('books/')).getByRole('button'));
    fireEvent.click(within(groupOf('todo/')).getByRole('button'));

    fireEvent.click(screen.getByLabelText('dataRepo.refresh'));
    await waitFor(() => expect(getDataRepoStatus).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(rowsIn('books/')).toBe(3));
    expect(rowsIn('todo/')).toBe(0);
  });

  it('服务端按目录给了样本与细分时优先用，组内明细与细分恒完整', async () => {
    getDataRepoStatus.mockResolvedValue({
      ...TRUNCATED,
      rollup: [
        {
          area: 'todo/',
          count: 71,
          counts: { modified: 70, deleted: 1 },
          sample: paths('todo/', 8),
        },
        {
          area: 'workbench_titles.json',
          count: 1,
          counts: { modified: 1 },
          sample: [{ path: 'workbench_titles.json', status: 'modified' }],
        },
      ],
      files: [],
    });
    render(<DataRepoPage />);

    await waitFor(() => expect(groupOf('todo/')).toBeTruthy());
    expect(
      within(groupOf('todo/')).getByText('70 dataRepo.status.modified · 1 dataRepo.status.deleted')
    ).toBeTruthy();
    expect(rowsIn('todo/')).toBe(8);
    // 根目录单文件：组头与行都是原名
    expect(rowsIn('workbench_titles.json')).toBe(1);
    expect(within(groupOf('workbench_titles.json')).getAllByText('workbench_titles.json')).toHaveLength(2);
  });

  it('改动类型不带橙绿', async () => {
    getDataRepoStatus.mockResolvedValue(TRUNCATED);
    render(<DataRepoPage />);

    await waitFor(() => expect(groupOf('data/')).toBeTruthy());
    for (const label of within(groupOf('data/')).getAllByText(/^dataRepo\.status\./)) {
      expect(label.className).not.toMatch(/amber|green/);
    }
  });
});
