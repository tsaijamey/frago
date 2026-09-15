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
 * 存在浏览器里，跨会话记住。存不下只影响下次打开时菜单里还有没有这几行。
 */

import { create } from 'zustand';

const STORAGE_KEY = 'recipe-app-pins';

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
    if (seen.has(name)) return false;
    seen.add(name);
    return true;
  });
}

function readPins(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    const ids = Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : [];
    return onePerRecipe(ids);
  } catch {
    return [];
  }
}

function writePins(pins: string[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(pins));
  } catch {
    // 存不下就只在这次打开的界面里有效
  }
}

interface RecipeAppPinsState {
  pins: string[];
  /**
   * 要打开这一项。返回菜单里真正指着它的那一项：这个配方已经开着就是已开的那一项
   * （地址不变），没开着就是刚 pin 上的这一项。调用方拿返回值去切页面。
   */
  pin: (id: string) => string;
  unpin: (id: string) => void;
}

export const useRecipeAppPins = create<RecipeAppPinsState>((set, get) => ({
  pins: readPins(),

  pin: (id) => {
    const { name } = splitRecipeAppId(id);
    const existing = get().pins.find((p) => splitRecipeAppId(p).name === name);
    if (existing) return existing;
    const pins = [...get().pins, id];
    writePins(pins);
    set({ pins });
    return id;
  },

  unpin: (id) => {
    const pins = get().pins.filter((p) => p !== id);
    writePins(pins);
    set({ pins });
  },
}));
