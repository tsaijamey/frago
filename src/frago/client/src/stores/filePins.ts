/**
 * pin 在 files 菜单下面的目录与文件。
 *
 * 常去的那几个目录或常看的那几份文件钉在左侧菜单 Files 下方，点一下直接切进那个目录
 * 或在右侧摆出那份文件，不用每次从主目录一层层往下翻。
 *
 * 唯一真源位于服务端 `~/.frago/workbench_pins.json`（`/api/workbench/file-pins`），
 * 跨浏览器、跨访问源（localhost vs 127.0.0.1）、多标签页共享同一份名单。
 * 浏览器本地遗留键 `file-browser-pins` 仅在首次加载时执行一次性幂等迁移并清除，
 * 避免旧缓存「死灰复燃」覆盖服务端最新的取消 Pin 操作。
 */

import { create } from 'zustand';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';
export const LEGACY_FILE_PINS_KEY = 'file-browser-pins';
export const FILE_PINS_MIGRATED_KEY = 'file-browser-pins-migrated-v1';
export const FILE_PINS_SYNC_TICK_KEY = 'frago-file-pins-sync-tick';

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
  if (/^[A-Za-z]:[\\/]$/.test(trimmed)) return trimmed;
  return trimmed.replace(/\/+$/, '') || '/';
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

function readLegacyLocalPins(): { hasKey: boolean; items: FilePinItem[] } {
  try {
    const raw = localStorage.getItem(LEGACY_FILE_PINS_KEY);
    if (raw === null) return { hasKey: false, items: [] };
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return { hasKey: true, items: [] };
    return { hasKey: true, items: dedupFilePins(parsed as FilePinItem[]) };
  } catch {
    return { hasKey: false, items: [] };
  }
}

function markMigratedAndClearLegacy(): void {
  try {
    localStorage.setItem(FILE_PINS_MIGRATED_KEY, '1');
    localStorage.removeItem(LEGACY_FILE_PINS_KEY);
  } catch {
    // 隐私模式或存储受限时忽略，内存仍以服务端为准
  }
}

function isMigrated(): boolean {
  try {
    return localStorage.getItem(FILE_PINS_MIGRATED_KEY) === '1';
  } catch {
    return true;
  }
}

function broadcastSyncTick(): void {
  try {
    localStorage.setItem(FILE_PINS_SYNC_TICK_KEY, String(Date.now()));
  } catch {
    // 忽略同源通知写入失败
  }
}

class HttpRejectionError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function fetchJsonPins(url: string, init?: RequestInit): Promise<FilePinItem[]> {
  if (typeof fetch !== 'function') {
    throw new TypeError('fetch is unavailable');
  }
  const res = await fetch(url, init);
  if (!res) {
    throw new TypeError('empty fetch response');
  }
  if (!res.ok) {
    throw new HttpRejectionError(res.status, `HTTP ${res.status}`);
  }
  const body = (await res.json()) as { pins?: unknown };
  return dedupFilePins(Array.isArray(body?.pins) ? (body.pins as FilePinItem[]) : []);
}

let targetSeq = 0;
let writeTicketSeq = 0;
let writeChain: Promise<void> = Promise.resolve();
let inFlightLoad: Promise<void> | null = null;

interface FilePinsState {
  pins: FilePinItem[];
  loaded: boolean;
  /** 文件页当前停在哪个目录或选着哪份文件，供侧栏子菜单高亮对应行。 */
  activePath: string | null;
  /** 从侧栏子菜单点过来的目标项，由文件页消费并跳转。 */
  pendingTarget: FilePinTarget | null;
  load: () => Promise<void>;
  pin: (item: FilePinItem) => void;
  unpin: (path: string) => void;
  togglePin: (item: FilePinItem) => boolean;
  isPinned: (path: string) => boolean;
  openPin: (item: FilePinItem) => void;
  consumeTarget: (seq: number) => void;
  setActivePath: (path: string | null) => void;
}

export const useFilePins = create<FilePinsState>((set, get) => {
  const enqueueWrite = (
    ticket: number,
    op: () => Promise<FilePinItem[]>,
    rollbackPins: FilePinItem[]
  ) => {
    writeChain = writeChain
      .then(async () => {
        try {
          const authoritative = await op();
          if (ticket === writeTicketSeq) {
            set({ pins: authoritative, loaded: true });
            broadcastSyncTick();
          }
        } catch (err) {
          // 仅当后端明确返回 HTTP 错误（如 400 非法路径 / 500）且没有更新的操作覆盖时回滚；
          // 网络异常或无后端测试环境保留当前乐观状态。
          if (err instanceof HttpRejectionError && ticket === writeTicketSeq) {
            set({ pins: rollbackPins });
          }
        }
      })
      .catch(() => {
        // 保持写入链不断裂
      });
  };

  return {
    pins: [],
    loaded: false,
    activePath: null,
    pendingTarget: null,

    load: async () => {
      if (inFlightLoad) return inFlightLoad;
      const ticketAtStart = writeTicketSeq;
      const run = async () => {
        try {
          if (typeof fetch !== 'function') return;
          let serverPins: FilePinItem[];
          if (!isMigrated()) {
            const legacy = readLegacyLocalPins();
            if (legacy.items.length > 0) {
              serverPins = await fetchJsonPins(`${API_BASE_URL}/api/workbench/file-pins/merge`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pins: legacy.items }),
              });
            } else {
              serverPins = await fetchJsonPins(`${API_BASE_URL}/api/workbench/file-pins`);
            }
            markMigratedAndClearLegacy();
          } else {
            serverPins = await fetchJsonPins(`${API_BASE_URL}/api/workbench/file-pins`);
          }
          if (ticketAtStart === writeTicketSeq) {
            set({ pins: serverPins, loaded: true });
          }
        } catch {
          // 服务端暂不可用或处于测试环境时静默保留现有状态
        } finally {
          inFlightLoad = null;
        }
      };
      inFlightLoad = run();
      return inFlightLoad;
    },

    pin: (item) => {
      const path = normalizePinPath(item.path);
      const before = get().pins;
      const existing = before.find((p) => p.path === path);
      if (existing) return;
      const next = [...before, { path, is_dir: Boolean(item.is_dir) }];
      const ticket = ++writeTicketSeq;
      set({ pins: next });
      enqueueWrite(
        ticket,
        () =>
          fetchJsonPins(`${API_BASE_URL}/api/workbench/file-pins`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path, is_dir: Boolean(item.is_dir) }),
          }),
        before
      );
    },

    unpin: (rawPath) => {
      const path = normalizePinPath(rawPath);
      const before = get().pins;
      const next = before.filter((p) => p.path !== path);
      if (next.length === before.length) return;
      const ticket = ++writeTicketSeq;
      set({ pins: next });
      enqueueWrite(
        ticket,
        () =>
          fetchJsonPins(
            `${API_BASE_URL}/api/workbench/file-pins?path=${encodeURIComponent(path)}`,
            { method: 'DELETE' }
          ),
        before
      );
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
  };
});
