/**
 * pin 在 files 菜单下面的目录与文件。
 *
 * 常去的那几个目录或常看的那几份文件钉在左侧菜单 Files 下方，点一下直接切进那个目录
 * 或在右侧摆出那份文件，不用每次从主目录一层层往下翻。
 *
 * 与 `recipeAppPins` 同一个做法：存在浏览器里，跨会话记住；同一个绝对路径只占一行。
 */

import { create } from 'zustand';

const STORAGE_KEY = 'file-browser-pins';

export interface FilePinItem {
  /** 绝对路径，唯一键。 */
  path: string;
  /** 目录还是文件：决定子菜单画文件夹还是文件图标，以及点开时是进目录还是选中文件。 */
  is_dir: boolean;
}

export interface FilePinTarget extends FilePinItem {
  /** 每次从侧栏点选时递增，保证重复点同一项也能把文件页切过去。 */
  seq: number;
}

/** 去掉末尾多余的 `/`（根目录 `/` 除外），免得同一个目录因为末尾斜杠占两行。 */
export function normalizePinPath(path: string): string {
  const trimmed = path.trim();
  if (!trimmed || trimmed === '/') return '/';
  return trimmed.replace(/\/+$/, '');
}

/** 子菜单行里摆的短名字：取路径最后一段，根目录显示 `/`。完整路径放在 tooltip 里。 */
export function filePinLabel(path: string): string {
  const clean = normalizePinPath(path);
  if (clean === '/') return '/';
  const idx = clean.lastIndexOf('/');
  return idx >= 0 ? clean.slice(idx + 1) : clean;
}

/** 取一个路径的上一级目录。 */
export function parentDirOf(path: string): string {
  const clean = normalizePinPath(path);
  const idx = clean.lastIndexOf('/');
  if (idx <= 0) return '/';
  return clean.slice(0, idx);
}

/** 同一个路径只留第一次出现的那一项。 */
export function dedupFilePins(items: FilePinItem[]): FilePinItem[] {
  const seen = new Set<string>();
  const out: FilePinItem[] = [];
  for (const item of items) {
    if (!item || typeof item.path !== 'string' || !item.path.trim()) continue;
    const path = normalizePinPath(item.path);
    if (seen.has(path)) continue;
    seen.add(path);
    out.push({ path, is_dir: Boolean(item.is_dir) });
  }
  return out;
}

function readPins(): FilePinItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return dedupFilePins(parsed as FilePinItem[]);
  } catch {
    return [];
  }
}

function writePins(pins: FilePinItem[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(pins));
  } catch {
    // 存不下就只在这次打开的界面里有效
  }
}

let targetSeq = 0;

interface FilePinsState {
  pins: FilePinItem[];
  /** 文件页当前停在哪个目录或选着哪份文件，供侧栏子菜单高亮对应行。 */
  activePath: string | null;
  /** 从侧栏子菜单点过来的目标项，由文件页消费并跳转。 */
  pendingTarget: FilePinTarget | null;
  pin: (item: FilePinItem) => void;
  unpin: (path: string) => void;
  togglePin: (item: FilePinItem) => boolean;
  isPinned: (path: string) => boolean;
  openPin: (item: FilePinItem) => void;
  consumeTarget: (seq: number) => void;
  setActivePath: (path: string | null) => void;
}

export const useFilePins = create<FilePinsState>((set, get) => ({
  pins: readPins(),
  activePath: null,
  pendingTarget: null,

  pin: (item) => {
    const path = normalizePinPath(item.path);
    const existing = get().pins.find((p) => p.path === path);
    if (existing) return;
    const pins = [...get().pins, { path, is_dir: item.is_dir }];
    writePins(pins);
    set({ pins });
  },

  unpin: (rawPath) => {
    const path = normalizePinPath(rawPath);
    const pins = get().pins.filter((p) => p.path !== path);
    writePins(pins);
    set({ pins });
  },

  togglePin: (item) => {
    const path = normalizePinPath(item.path);
    const exists = get().pins.some((p) => p.path === path);
    if (exists) {
      get().unpin(path);
      return false;
    }
    get().pin({ path, is_dir: item.is_dir });
    return true;
  },

  isPinned: (rawPath) => {
    const path = normalizePinPath(rawPath);
    return get().pins.some((p) => p.path === path);
  },

  openPin: (item) => {
    const path = normalizePinPath(item.path);
    const seq = ++targetSeq;
    set({
      activePath: path,
      pendingTarget: { path, is_dir: item.is_dir, seq },
    });
  },

  consumeTarget: (seq) => {
    if (get().pendingTarget?.seq === seq) {
      set({ pendingTarget: null });
    }
  },

  setActivePath: (rawPath) => {
    const path = rawPath ? normalizePinPath(rawPath) : null;
    if (get().activePath !== path) {
      set({ activePath: path });
    }
  },
}));
