/**
 * 文件这一页：左边走目录，右边看文件。
 *
 * 盯四件事：进来先落在主目录并把内容列出来、点一条目录就往下走一层（且清掉右边的选中，
 * 免得右边还摆着上一层那份文件）、点一份文件右边摆出来、还没选东西时右栏说的是那句
 * 「左边选一份」而不是一片空白。
 *
 * 一个来回都不碰真的文件系统：`listDirectory` 与 `getSystemDirectories` 都是替身，
 * 这一页要验的是它拿着服务端给的清单做了什么，不是服务端读得对不对。
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { FileListing } from '@/types/api';

const listDirectory = vi.fn();
const revealPath = vi.fn();
const prepareFileView = vi.fn();
const getSystemDirectories = vi.fn();

vi.mock('@/api', () => ({
  listDirectory: (path?: string) => listDirectory(path),
  revealPath: (path: string) => revealPath(path),
  prepareFileView: (path: string) => prepareFileView(path),
  rawFileUrl: (path: string) => `/api/file?disposition=inline&path=${encodeURIComponent(path)}`,
  absoluteUrl: (path: string) => path,
}));

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getSystemDirectories: () => getSystemDirectories(),
}));

import FileBrowserPage from '../FileBrowserPage';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const HOME: FileListing = {
  path: '/Users/frago',
  entries: [
    { name: 'Repos', is_dir: true, size: null, modified: '2026-10-13T09:00:00' },
    { name: 'notes.md', is_dir: false, size: 2048, modified: '2026-10-12T18:30:00' },
  ],
};

const REPOS: FileListing = {
  path: '/Users/frago/Repos',
  entries: [{ name: 'frago', is_dir: true, size: null, modified: '2026-10-13T09:05:00' }],
};

beforeEach(() => {
  listDirectory.mockReset();
  revealPath.mockReset();
  prepareFileView.mockReset();
  getSystemDirectories.mockReset();

  getSystemDirectories.mockResolvedValue({ home: '/Users/frago', cwd: '/Users/frago/Repos/frago' });
  // markdown 与 html 都交给服务端渲染，这一页嵌的是它回的那个地址。
  prepareFileView.mockResolvedValue({
    content_id: 'abc',
    url: '/viewer/content/abc/index.html',
    title: 'notes.md',
  });
  listDirectory.mockImplementation(async (path?: string) => (path === REPOS.path ? REPOS : HOME));
  // 这一页要摆的那几份都是文本，读它走 `fetch`；替成一份空正文，测试不管内容长什么样。
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('', { status: 200 }))
  );
});

describe('文件页', () => {
  it('进来落在主目录，把清单摆出来', async () => {
    render(<FileBrowserPage />);

    expect(await screen.findByText('Repos')).toBeTruthy();
    expect(screen.getByText('notes.md')).toBeTruthy();
    expect(screen.getByText('2.0 KB')).toBeTruthy();
    // 服务端不认路径时就自己回主目录，页面这一侧第一次不带路径去问。
    expect(listDirectory).toHaveBeenCalledWith(undefined);
    // **只问一次。** 把服务端解析出来的路径写回「想去哪儿」那个状态会让它变成这条请求
    // 的依赖，挂载一次问两次、列表中间闪回一次「读这个目录…」。
    expect(listDirectory).toHaveBeenCalledTimes(1);
  });

  it('点一条目录往下走一层，并清掉右边还摆着的那份文件', async () => {
    render(<FileBrowserPage />);

    fireEvent.click(await screen.findByText('notes.md'));
    // 右边摆出来的标志是那一条路径与它的两颗按钮；清单里那一行没有这些。
    await waitFor(() => expect(screen.getByLabelText('复制路径')).toBeTruthy());

    fireEvent.click(screen.getByText('Repos'));

    await waitFor(() => expect(listDirectory).toHaveBeenCalledWith('/Users/frago/Repos'));
    expect(await screen.findByText('frago')).toBeTruthy();
    // 上一层的文件不该还留在右边。
    expect(screen.queryByLabelText('复制路径')).toBeNull();
  });

  it('重读那一颗按钮读的是现在这个目录，不是把人弹回主目录', async () => {
    render(<FileBrowserPage />);

    fireEvent.click(await screen.findByText('Repos'));
    await waitFor(() => expect(listDirectory).toHaveBeenCalledWith('/Users/frago/Repos'));
    listDirectory.mockClear();

    fireEvent.click(screen.getByLabelText('重新读一次这个目录'));

    await waitFor(() => expect(listDirectory).toHaveBeenCalledWith('/Users/frago/Repos'));
  });

  it('还没选东西时右栏说的是那句「左边选一份」', async () => {
    render(<FileBrowserPage />);

    await screen.findByText('Repos');
    expect(screen.getByText('左边选一份文件，这里就会显示它')).toBeTruthy();
  });

  it('列目录出错时照实说，不摆一张空清单', async () => {
    listDirectory.mockRejectedValue(new Error('HTTP 403'));

    render(<FileBrowserPage />);

    expect(await screen.findByText('读不了这个目录')).toBeTruthy();
    expect(screen.getByText('HTTP 403')).toBeTruthy();
  });
});
