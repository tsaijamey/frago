import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  dedupFilePins,
  FILE_PINS_MIGRATED_KEY,
  filePinLabel,
  LEGACY_FILE_PINS_KEY,
  normalizePinPath,
  parentDirOf,
  useFilePins,
} from '@/stores/filePins';

describe('filePins 路径辅助', () => {
  it('去掉末尾多余斜杠并取短名与父目录', () => {
    expect(normalizePinPath('/Users/frago/Repos/')).toBe('/Users/frago/Repos');
    expect(normalizePinPath('/')).toBe('/');
    expect(filePinLabel('/Users/frago/Repos/frago')).toBe('frago');
    expect(filePinLabel('/')).toBe('/');
    expect(parentDirOf('/Users/frago/Repos/notes.md')).toBe('/Users/frago/Repos');
    expect(parentDirOf('/notes.md')).toBe('/');
  });

  it('同一个路径去重只留第一项', () => {
    expect(
      dedupFilePins([
        { path: '/Users/frago/Repos/', is_dir: true },
        { path: '/Users/frago/Repos', is_dir: true },
        { path: '/Users/frago/notes.md', is_dir: false },
      ])
    ).toEqual([
      { path: '/Users/frago/Repos', is_dir: true },
      { path: '/Users/frago/notes.md', is_dir: false },
    ]);
  });
});

describe('useFilePins', () => {
  beforeEach(() => {
    localStorage.clear();
    useFilePins.setState({ pins: [], loaded: false, activePath: null, pendingTarget: null });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('pin 与 unpin 目录和文件', () => {
    const { pin, unpin, isPinned } = useFilePins.getState();
    pin({ path: '/Users/frago/Repos/', is_dir: true });
    pin({ path: '/Users/frago/notes.md', is_dir: false });

    expect(useFilePins.getState().pins).toEqual([
      { path: '/Users/frago/Repos', is_dir: true },
      { path: '/Users/frago/notes.md', is_dir: false },
    ]);
    expect(isPinned('/Users/frago/Repos')).toBe(true);

    unpin('/Users/frago/Repos');
    expect(isPinned('/Users/frago/Repos')).toBe(false);
    expect(useFilePins.getState().pins).toEqual([
      { path: '/Users/frago/notes.md', is_dir: false },
    ]);
  });

  it('openPin 记下目标并支持消费', () => {
    const { openPin, consumeTarget } = useFilePins.getState();
    openPin({ path: '/Users/frago/notes.md', is_dir: false });

    const target = useFilePins.getState().pendingTarget;
    expect(target?.path).toBe('/Users/frago/notes.md');
    expect(target?.is_dir).toBe(false);
    expect(useFilePins.getState().activePath).toBe('/Users/frago/notes.md');

    if (target) consumeTarget(target.seq);
    expect(useFilePins.getState().pendingTarget).toBeNull();
  });

  it('首次加载执行一次性迁移并清理旧 localStorage，防止取消 Pin 后死灰复燃', async () => {
    localStorage.setItem(
      LEGACY_FILE_PINS_KEY,
      JSON.stringify([{ path: '/Users/frago/legacy.md', is_dir: false }])
    );
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          pins: [
            { path: '/Users/frago/server.md', is_dir: false },
            { path: '/Users/frago/legacy.md', is_dir: false },
          ],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          pins: [{ path: '/Users/frago/server.md', is_dir: false }],
        }),
      });
    vi.stubGlobal('fetch', fetchMock);

    await useFilePins.getState().load();
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/workbench/file-pins/merge',
      expect.objectContaining({ method: 'POST' })
    );
    expect(localStorage.getItem(FILE_PINS_MIGRATED_KEY)).toBe('1');
    expect(localStorage.getItem(LEGACY_FILE_PINS_KEY)).toBeNull();
    expect(useFilePins.getState().pins).toEqual([
      { path: '/Users/frago/server.md', is_dir: false },
      { path: '/Users/frago/legacy.md', is_dir: false },
    ]);

    // 模拟另一端删除了 legacy.md；再次 load 只走 GET，不再把旧数据 merge 回去
    await useFilePins.getState().load();
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/workbench/file-pins', undefined);
    expect(useFilePins.getState().pins).toEqual([
      { path: '/Users/frago/server.md', is_dir: false },
    ]);
  });

  it('后端明确返回 HTTP 400 拒绝写入时自动回滚乐观更新', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
    });
    vi.stubGlobal('fetch', fetchMock);

    useFilePins.getState().pin({ path: 'relative-only.md', is_dir: false });
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(useFilePins.getState().pins).toEqual([]);
    });
  });
});
