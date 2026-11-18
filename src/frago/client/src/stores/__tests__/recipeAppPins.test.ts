/**
 * 一个配方在菜单里只占一行。
 *
 * 已经开着的配方再被要求打开（换了槽位也一样），回到已开的那一行，地址不变——
 * 那张页面上可能有人没保存的输入，换地址就是重新载入。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  LEGACY_RECIPE_APP_PINS_KEY,
  onePerRecipe,
  RECIPE_APP_PINS_MIGRATED_KEY,
  recipeAppId,
  splitRecipeAppId,
  useRecipeAppPins,
} from '@/stores/recipeAppPins';

describe('onePerRecipe', () => {
  it('同一个配方只留第一次出现的那一项', () => {
    expect(
      onePerRecipe(['kline', 'ledger', 'kline/071ba7', 'ledger/x', 'board'])
    ).toEqual(['kline', 'ledger', 'board']);
  });
});

describe('pin', () => {
  beforeEach(() => {
    localStorage.clear();
    useRecipeAppPins.setState({ pins: [], loaded: false });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('没开着就 pin 上，返回它自己', () => {
    expect(useRecipeAppPins.getState().pin('kline/r1')).toBe('kline/r1');
    expect(useRecipeAppPins.getState().pins).toEqual(['kline/r1']);
  });

  it('已经开着，换个槽位来要，也回到已开的那一项，不多一行', () => {
    const { pin } = useRecipeAppPins.getState();
    pin('kline');
    expect(pin('kline/r2')).toBe('kline');
    expect(pin('kline')).toBe('kline');
    expect(useRecipeAppPins.getState().pins).toEqual(['kline']);
  });

  it('不同配方各占一行', () => {
    const { pin } = useRecipeAppPins.getState();
    pin('kline');
    pin('ledger');
    expect(useRecipeAppPins.getState().pins).toEqual(['kline', 'ledger']);
  });

  it('摘掉之后再开，按新的地址 pin', () => {
    const { pin, unpin } = useRecipeAppPins.getState();
    pin('kline');
    unpin('kline');
    expect(useRecipeAppPins.getState().pin('kline/r3')).toBe('kline/r3');
  });

  it('支持 toggle 与 isPinned 对外接口', () => {
    const { toggle, isPinned } = useRecipeAppPins.getState();
    expect(toggle('kline/r1')).toBe(true);
    expect(isPinned('kline')).toBe(true);
    expect(toggle('kline/r2')).toBe(false);
    expect(isPinned('kline')).toBe(false);
  });

  it('首次加载执行一次性迁移并清理旧 localStorage，再加载直接读服务端', async () => {
    localStorage.setItem(LEGACY_RECIPE_APP_PINS_KEY, JSON.stringify(['colab_compute_console']));
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ pins: ['gold_silver_price_board', 'colab_compute_console'] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ pins: ['gold_silver_price_board'] }),
      });
    vi.stubGlobal('fetch', fetchMock);

    await useRecipeAppPins.getState().load();
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/workbench/recipe-app-pins/merge',
      expect.objectContaining({ method: 'POST' })
    );
    expect(localStorage.getItem(RECIPE_APP_PINS_MIGRATED_KEY)).toBe('1');
    expect(localStorage.getItem(LEGACY_RECIPE_APP_PINS_KEY)).toBeNull();
    expect(useRecipeAppPins.getState().pins).toEqual([
      'gold_silver_price_board',
      'colab_compute_console',
    ]);

    await useRecipeAppPins.getState().load();
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/workbench/recipe-app-pins', undefined);
    expect(useRecipeAppPins.getState().pins).toEqual(['gold_silver_price_board']);
  });
});

describe('地址两半', () => {
  it('默认槽位不写进地址', () => {
    expect(recipeAppId('kline', 'default')).toBe('kline');
    expect(recipeAppId('kline', 'r1')).toBe('kline/r1');
    expect(splitRecipeAppId('kline/r1')).toEqual({ name: 'kline', slot: 'r1' });
  });
});
