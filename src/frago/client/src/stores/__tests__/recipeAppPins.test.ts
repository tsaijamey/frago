/**
 * 一个配方在菜单里只占一行。
 *
 * 已经开着的配方再被要求打开（换了槽位也一样），回到已开的那一行，地址不变——
 * 那张页面上可能有人没保存的输入，换地址就是重新载入。
 */

import { beforeEach, describe, expect, it } from 'vitest';
import { onePerRecipe, recipeAppId, splitRecipeAppId, useRecipeAppPins } from '@/stores/recipeAppPins';

describe('onePerRecipe', () => {
  it('同一个配方只留第一次出现的那一项', () => {
    expect(
      onePerRecipe(['kline', 'ledger', 'kline/071ba7', 'ledger/x', 'board'])
    ).toEqual(['kline', 'ledger', 'board']);
  });
});

describe('pin', () => {
  beforeEach(() => {
    useRecipeAppPins.setState({ pins: [] });
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
});

describe('地址两半', () => {
  it('默认槽位不写进地址', () => {
    expect(recipeAppId('kline', 'default')).toBe('kline');
    expect(recipeAppId('kline', 'r1')).toBe('kline/r1');
    expect(splitRecipeAppId('kline/r1')).toEqual({ name: 'kline', slot: 'r1' });
  });
});
