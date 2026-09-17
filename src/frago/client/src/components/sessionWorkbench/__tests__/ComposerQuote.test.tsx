/**
 * 输入区的两件新事：接住记录流引过来的那段话，以及高度跟着内容走。
 *
 * 三条硬要求：
 *
 * 1. 引用落进输入框的形状是三引号包住原话、下面一行 `>>> `，光标停在 `>>> ` 后面，
 *    框当场拿到焦点——按完能直接接着打字，不用再点一下。
 * 2. 同一段话连引两次是两次，接在已有内容后面，一个字都不覆盖。
 * 3. 高度在两行与九行之间随内容走，到九行封顶、框内自己滚。
 *
 * jsdom 不排版，`scrollHeight` 恒为 0，量不出真实高度。这里给它换一个按行数算的替身：
 * 高度契约（两行起、九行封顶、一行 24 像素）本来就是按行数写的，换成行数照样核得住。
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import Composer from '../Composer';
import i18n from '@/i18n';

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const NOOP = () => {};
const LINE_PX = 24;

let restoreScrollHeight: (() => void) | null = null;

beforeAll(async () => {
  await i18n.changeLanguage('zh');
  const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollHeight');
  Object.defineProperty(HTMLTextAreaElement.prototype, 'scrollHeight', {
    configurable: true,
    get(this: HTMLTextAreaElement) {
      return this.value.split('\n').length * LINE_PX;
    },
  });
  restoreScrollHeight = () => {
    delete (HTMLTextAreaElement.prototype as unknown as Record<string, unknown>).scrollHeight;
    if (original) Object.defineProperty(HTMLElement.prototype, 'scrollHeight', original);
  };
});

afterAll(() => {
  restoreScrollHeight?.();
});

function box() {
  return screen.getByTestId('composer-input') as HTMLTextAreaElement;
}

function mount(quote: { text: string; at: number } | null) {
  return render(
    <Composer sessionId={SID} family="claude-code" quote={quote} onSent={NOOP} />
  );
}

describe('引用落进输入框', () => {
  it('形状是三引号包住原话，下一行 >>> ，光标停在它后面，框拿到焦点', () => {
    const view = mount(null);
    view.rerender(
      <Composer sessionId={SID} family="claude-code" quote={{ text: '收尾闸门拦下了', at: 1 }} onSent={NOOP} />
    );
    const el = box();
    expect(el.value).toBe('"""\n收尾闸门拦下了\n"""\n>>> ');
    expect(el.selectionStart).toBe(el.value.length);
    expect(document.activeElement).toBe(el);
  });

  it('接在已有内容后面，同一段话连引两次也算两次', () => {
    const view = mount(null);
    act(() => {
      fireEvent.change(box(), { target: { value: '先说一句' } });
    });
    view.rerender(
      <Composer sessionId={SID} family="claude-code" quote={{ text: '配方', at: 1 }} onSent={NOOP} />
    );
    expect(box().value).toBe('先说一句\n"""\n配方\n"""\n>>> ');
    view.rerender(
      <Composer sessionId={SID} family="claude-code" quote={{ text: '配方', at: 2 }} onSent={NOOP} />
    );
    expect(box().value).toBe('先说一句\n"""\n配方\n"""\n>>> \n"""\n配方\n"""\n>>> ');
  });
});

describe('输入框的高度', () => {
  it('空着是两行', () => {
    mount(null);
    expect(box().style.height).toBe(`${2 * LINE_PX}px`);
  });

  it('打到五行就有五行高，框内不滚', () => {
    mount(null);
    act(() => {
      fireEvent.change(box(), { target: { value: 'a\nb\nc\nd\ne' } });
    });
    expect(box().style.height).toBe(`${5 * LINE_PX}px`);
    expect(box().style.overflowY).toBe('hidden');
  });

  it('超过九行封在九行，多出来的由框内自己滚', () => {
    mount(null);
    act(() => {
      fireEvent.change(box(), {
        target: { value: Array.from({ length: 30 }, (_, i) => `第 ${i} 行`).join('\n') },
      });
    });
    expect(box().style.height).toBe(`${9 * LINE_PX}px`);
    expect(box().style.overflowY).toBe('auto');
  });

  it('删回去要变矮，不许停在长过的那个高度上', () => {
    mount(null);
    act(() => {
      fireEvent.change(box(), { target: { value: 'a\nb\nc\nd\ne\nf' } });
    });
    expect(box().style.height).toBe(`${6 * LINE_PX}px`);
    act(() => {
      fireEvent.change(box(), { target: { value: 'a' } });
    });
    expect(box().style.height).toBe(`${2 * LINE_PX}px`);
  });
});
