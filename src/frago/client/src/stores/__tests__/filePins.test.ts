import { beforeEach, describe, expect, it } from 'vitest';
import {
  dedupFilePins,
  filePinLabel,
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
    useFilePins.setState({ pins: [], activePath: null, pendingTarget: null });
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
});
