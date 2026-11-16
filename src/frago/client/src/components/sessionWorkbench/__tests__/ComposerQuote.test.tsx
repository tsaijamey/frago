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

  it('暂存列表填入的那一份带着想法：接在 >>> 后面，光标停在想法末尾', () => {
    const view = mount(null);
    view.rerender(
      <Composer
        sessionId={SID}
        family="claude-code"
        quote={{ text: '第二个决策点', note: '倾向选乙', at: 1 }}
        onSent={NOOP}
      />
    );
    const el = box();
    expect(el.value).toBe('"""\n第二个决策点\n"""\n>>> 倾向选乙');
    expect(el.selectionStart).toBe(el.value.length);
  });
});

describe('输入框的高度', () => {
  it('compact 静默空态是单行胶囊（24px）', () => {
    mount(null);
    expect(box().style.height).toBe(`${1 * LINE_PX}px`);
    expect(screen.getByTestId('composer-shell').getAttribute('data-expanded')).toBe('no');
  });

  it('打到五行就有五行高并进入展开态，框内不滚', () => {
    mount(null);
    act(() => {
      fireEvent.change(box(), { target: { value: 'a\nb\nc\nd\ne' } });
    });
    expect(box().style.height).toBe(`${5 * LINE_PX}px`);
    expect(box().style.overflowY).toBe('hidden');
    expect(screen.getByTestId('composer-shell').getAttribute('data-expanded')).toBe('yes');
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

  it('删回单行安全阈值后要回缩回 24px 胶囊态，不许停在长过的那个高度上', () => {
    mount(null);
    act(() => {
      fireEvent.change(box(), { target: { value: 'a\nb\nc\nd\ne\nf' } });
    });
    expect(box().style.height).toBe(`${6 * LINE_PX}px`);
    act(() => {
      fireEvent.change(box(), { target: { value: 'a' } });
    });
    expect(box().style.height).toBe(`${1 * LINE_PX}px`);
    expect(screen.getByTestId('composer-shell').getAttribute('data-expanded')).toBe('no');
  });

  it('单行胶囊与展开态切换时保持同一个 textarea DOM 节点与焦点不丢失', () => {
    mount(null);
    const elBefore = box();
    act(() => {
      elBefore.focus();
      fireEvent.change(elBefore, { target: { value: '第一行\n第二行' } });
    });
    expect(screen.getByTestId('composer-shell').getAttribute('data-expanded')).toBe('yes');
    expect(box()).toBe(elBefore);
    expect(document.activeElement).toBe(elBefore);

    act(() => {
      fireEvent.change(elBefore, { target: { value: '' } });
    });
    expect(screen.getByTestId('composer-shell').getAttribute('data-expanded')).toBe('no');
    expect(box()).toBe(elBefore);
    expect(document.activeElement).toBe(elBefore);
  });

  it('IME 合成期间冻结形态切换，compositionEnd 后再结算展开态', () => {
    // 临时让长单行（无换行）在非合成态下触发折行展开
    const prevDesc = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'scrollHeight');
    Object.defineProperty(HTMLTextAreaElement.prototype, 'scrollHeight', {
      configurable: true,
      get(this: HTMLTextAreaElement) {
        return this.value.length > 12 ? 2 * LINE_PX : LINE_PX;
      },
    });
    try {
      mount(null);
      const el = box();
      act(() => {
        fireEvent.compositionStart(el);
        fireEvent.change(el, { target: { value: 'nihaozhongwenpinyinshuruchangdu' } });
      });
      // 合成过程中禁止切换形态
      expect(screen.getByTestId('composer-shell').getAttribute('data-expanded')).toBe('no');

      act(() => {
        fireEvent.compositionEnd(el);
      });
      expect(screen.getByTestId('composer-shell').getAttribute('data-expanded')).toBe('yes');
    } finally {
      if (prevDesc) Object.defineProperty(HTMLTextAreaElement.prototype, 'scrollHeight', prevDesc);
    }
  });

  it('滞回锁防抖：因折行展开后，删回 12 字（单行）仍保持展开，缩至 <=10 字或清空后回缩', () => {
    const prevDesc = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'scrollHeight');
    Object.defineProperty(HTMLTextAreaElement.prototype, 'scrollHeight', {
      configurable: true,
      get(this: HTMLTextAreaElement) {
        return this.value.length > 20 ? 2 * LINE_PX : LINE_PX;
      },
    });
    try {
      mount(null);
      const el = box();
      act(() => {
        fireEvent.change(el, { target: { value: '超过二十个字符从而触发单行溢出折入第二行再多加几个字' } });
      });
      expect(screen.getByTestId('composer-shell').getAttribute('data-expanded')).toBe('yes');

      // 删回 12 字（此时 scrollHeight 为 24，但仍在滞回缓冲区 > 10 字内，不许震荡回缩）
      act(() => {
        fireEvent.change(el, { target: { value: '十二个字滞回缓冲测试文本' } });
      });
      expect(screen.getByTestId('composer-shell').getAttribute('data-expanded')).toBe('yes');

      // 进一步缩减到 6 字（<= 10 字安全阈值），平滑回缩回单行胶囊
      act(() => {
        fireEvent.change(el, { target: { value: '缩到六个字符' } });
      });
      expect(screen.getByTestId('composer-shell').getAttribute('data-expanded')).toBe('no');
      expect(el.style.height).toBe(`${1 * LINE_PX}px`);
    } finally {
      if (prevDesc) Object.defineProperty(HTMLTextAreaElement.prototype, 'scrollHeight', prevDesc);
    }
  });
});
