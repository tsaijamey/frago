/**
 * pin 在 recipes 菜单下面的配方页面。
 *
 * 配方页面过去开在系统浏览器的新标签里，跑一次开一个，关不关得掉全看人记不记得。
 * 现在它开在界面右侧，菜单里留一行子菜单指着它：点一下回到那一页，点 × 摘掉。
 *
 * **一个配方只占一行。** 一项的写法跟地址栏那一段相同：`<配方名>`，非默认槽位是
 * `<配方名>/<槽位>`。但同一个配方已经开着时，再要求打开它（换了槽位也一样）不会
 * 多出一行，也不会换掉已开那一页的地址——只是回到那一页。原因是那一页上可能有人
 * 还没保存的输入：配方跑完一次就把它重新载入，等于替人把没存的东西扔了。
 * 真要换一份看，先 × 摘掉再开。
 *
 * 唯一真源位于服务端 `~/.frago/workbench_pins.json`（`/api/workbench/recipe-app-pins`），
 * 跨浏览器、跨访问源、多标签页共享同一份名单。浏览器本地遗留键 `recipe-app-pins`
 * 仅执行一次性幂等迁移并清除，防止旧缓存反复死灰复燃。
 */

import { create } from 'zustand';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';
export const LEGACY_RECIPE_APP_PINS_KEY = 'recipe-app-pins';
export const RECIPE_APP_PINS_MIGRATED_KEY = 'recipe-app-pins-migrated-v1';
export const RECIPE_APP_PINS_SYNC_TICK_KEY = 'frago-recipe-app-pins-sync-tick';

/** `<配方名>[/<槽位>]` 拆成两半。 */
export function splitRecipeAppId(id: string): { name: string; slot: string | null } {
  const at = id.indexOf('/');
  return at < 0 ? { name: id, slot: null } : { name: id.slice(0, at), slot: id.slice(at + 1) || null };
}

/** 两半拼回 `<配方名>[/<槽位>]`。默认槽位不写，地址短一截，也跟不带槽位的那一项是同一项。 */
export function recipeAppId(name: string, slot?: string | null): string {
  return slot && slot !== 'default' ? `${name}/${slot}` : name;
}

/** 同一个配方只留第一次出现的那一项。旧版本允许一个配方占几行，读进来时收拢。 */
export function onePerRecipe(ids: string[]): string[] {
  const seen = new Set<string>();
  return ids.filter((id) => {
    const { name } = splitRecipeAppId(id);
    if (!name || seen.has(name)) return false;
    seen.add(name);
    return true;
  });
}

function readLegacyLocalPins(): string[] {
  try {
    const raw = localStorage.getItem(LEGACY_RECIPE_APP_PINS_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    const ids = Array.isArray(parsed)
      ? parsed.filter((v): v is string => typeof v === 'string' && v.trim().length > 0)
      : [];
    return onePerRecipe(ids);
  } catch {
    return [];
  }
}

function isMigrated(): boolean {
  try {
    return localStorage.getItem(RECIPE_APP_PINS_MIGRATED_KEY) === '1';
  } catch {
    return true;
  }
}

function markMigratedAndClearLegacy(): void {
  try {
    localStorage.setItem(RECIPE_APP_PINS_MIGRATED_KEY, '1');
    localStorage.removeItem(LEGACY_RECIPE_APP_PINS_KEY);
  } catch {
    // 忽略存储受限错误
  }
}

function broadcastSyncTick(): void {
  try {
    localStorage.setItem(RECIPE_APP_PINS_SYNC_TICK_KEY, String(Date.now()));
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

async function fetchJsonRecipePins(url: string, init?: RequestInit): Promise<string[]> {
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
  const rawList = Array.isArray(body?.pins)
    ? body.pins.filter((v): v is string => typeof v === 'string' && v.trim().length > 0)
    : [];
  return onePerRecipe(rawList);
}

let writeTicketSeq = 0;
let writeChain: Promise<void> = Promise.resolve();
let inFlightLoad: Promise<void> | null = null;

interface RecipeAppPinsState {
  pins: string[];
  loaded: boolean;
  load: () => Promise<void>;
  /**
   * 要打开这一项。返回菜单里真正指着它的那一项：这个配方已经开着就是已开的那一项
   * （地址不变），没开着就是刚 pin 上的这一项。调用方拿返回值去切页面。
   */
  pin: (id: string) => string;
  unpin: (id: string) => void;
  toggle: (id: string) => boolean;
  isPinned: (id: string) => boolean;
}

export const useRecipeAppPins = create<RecipeAppPinsState>((set, get) => {
  const enqueueWrite = (
    ticket: number,
    op: () => Promise<string[]>,
    rollbackPins: string[]
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

    load: async () => {
      if (inFlightLoad) return inFlightLoad;
      const ticketAtStart = writeTicketSeq;
      const run = async () => {
        try {
          if (typeof fetch !== 'function') return;
          let serverPins: string[];
          if (!isMigrated()) {
            const legacy = readLegacyLocalPins();
            if (legacy.length > 0) {
              serverPins = await fetchJsonRecipePins(
                `${API_BASE_URL}/api/workbench/recipe-app-pins/merge`,
                {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ pins: legacy }),
                }
              );
            } else {
              serverPins = await fetchJsonRecipePins(
                `${API_BASE_URL}/api/workbench/recipe-app-pins`
              );
            }
            markMigratedAndClearLegacy();
          } else {
            serverPins = await fetchJsonRecipePins(
              `${API_BASE_URL}/api/workbench/recipe-app-pins`
            );
          }
          if (ticketAtStart === writeTicketSeq) {
            set({ pins: serverPins, loaded: true });
          }
        } catch {
          // 服务端暂不可用或测试环境静默保留当前状态
        } finally {
          inFlightLoad = null;
        }
      };
      inFlightLoad = run();
      return inFlightLoad;
    },

    pin: (id) => {
      const { name, slot } = splitRecipeAppId(id.trim());
      const normalized = recipeAppId(name, slot);
      const before = get().pins;
      const existing = before.find((p) => splitRecipeAppId(p).name === name);
      if (existing) return existing;
      const next = [...before, normalized];
      const ticket = ++writeTicketSeq;
      set({ pins: next });
      enqueueWrite(
        ticket,
        () =>
          fetchJsonRecipePins(`${API_BASE_URL}/api/workbench/recipe-app-pins`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: normalized }),
          }),
        before
      );
      return normalized;
    },

    unpin: (id) => {
      const target = id.trim();
      const { name, slot } = splitRecipeAppId(target);
      const normalized = recipeAppId(name, slot);
      const before = get().pins;
      const next = before.filter((p) => p !== target && p !== normalized);
      if (next.length === before.length) return;
      const ticket = ++writeTicketSeq;
      set({ pins: next });
      enqueueWrite(
        ticket,
        () =>
          fetchJsonRecipePins(
            `${API_BASE_URL}/api/workbench/recipe-app-pins?id=${encodeURIComponent(target)}`,
            { method: 'DELETE' }
          ),
        before
      );
    },

    toggle: (id) => {
      const target = id.trim();
      const { name } = splitRecipeAppId(target);
      const exists = get().pins.some((p) => splitRecipeAppId(p).name === name);
      if (exists) {
        const existingId = get().pins.find((p) => splitRecipeAppId(p).name === name) ?? target;
        get().unpin(existingId);
        return false;
      }
      get().pin(target);
      return true;
    },

    isPinned: (id) => {
      const { name } = splitRecipeAppId(id.trim());
      return get().pins.some((p) => splitRecipeAppId(p).name === name);
    },
  };
});
