import { describe, expect, it } from 'vitest';
import { refusalOf } from '../recipeOutcome';

describe('refusalOf', () => {
  it('结果里写了拒绝，就拿出原因代号和给人看的话', () => {
    expect(refusalOf({ refused: 'open_session', message: '你还有一局没打完' })).toEqual({
      code: 'open_session',
      message: '你还有一局没打完',
    });
  });

  it('没写原因也还是拒绝，不能退回「执行成功」', () => {
    expect(refusalOf({ refused: 'no_cash' })).toEqual({ code: 'no_cash', message: 'no_cash' });
  });

  it('普通结果、空结果、形状不对的，都不是拒绝', () => {
    expect(refusalOf({ session_id: 'x' })).toBeNull();
    expect(refusalOf(null)).toBeNull();
    expect(refusalOf('refused')).toBeNull();
    expect(refusalOf([{ refused: 'x' }])).toBeNull();
    expect(refusalOf({ refused: '' })).toBeNull();
    expect(refusalOf({ refused: true })).toBeNull();
  });
});
