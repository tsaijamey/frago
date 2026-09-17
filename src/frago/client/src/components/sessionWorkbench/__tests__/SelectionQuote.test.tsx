/**
 * 圈选之后那个「引用」按钮，以及短选区的同字标绿。
 *
 * 三条硬要求各测最容易破的那一面：
 *
 * 1. 圈中的字够长，只给按钮，不许去标绿——长句在别处不会原样重现，标出来只有自己那一处。
 * 2. 圈中不到五个字，按钮照给，同时把记录流里所有一模一样的文字交给浏览器涂绿。
 * 3. 按下「引用」交出去的是圈中的原文，交完按钮与绿字一起退场。
 *
 * jsdom 里没有几何也没有 CSS 自定义高亮：屏幕矩形由替身给（否则一切都是 0×0，按钮
 * 会被当成滚出视野而不显示），`CSS.highlights` 也由替身接管，用它核对到底标没标。
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { createRef } from 'react';
import SelectionQuote, { ECHO_MAX_CHARS, echoRanges } from '../SelectionQuote';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

/** 记录流里此刻摆着的字。同一个词故意在三处出现。 */
const STREAM_TEXT = ['配方 A 跑完了', '配方 B 还没跑', '收尾闸门拦下了配方 C'];

/** 浏览器那本高亮账。真浏览器里是 `CSS.highlights`，这里由替身记下都标了些什么。 */
function fakeHighlights() {
  const box = new Map<string, unknown>();
  Object.defineProperty(CSS, 'highlights', {
    configurable: true,
    value: {
      set: (name: string, value: unknown) => box.set(name, value),
      delete: (name: string) => box.delete(name),
    },
  });
  (window as unknown as { Highlight: unknown }).Highlight = class {
    ranges: Range[];
    constructor(...ranges: Range[]) {
      this.ranges = ranges;
    }
  };
  return box;
}

/** 有几何的屏幕：容器铺满视口，选区落在中间。 */
function fakeGeometry() {
  const view = { top: 0, bottom: 600, left: 0, right: 800, width: 800, height: 600 };
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
    ...view,
    x: 0,
    y: 0,
    toJSON: () => view,
  } as DOMRect);
  const spot = { top: 200, bottom: 220, left: 100, right: 180, width: 80, height: 20 };
  // jsdom 的 Range 压根没有这个方法，只能自己安一个——spyOn 要求属性本来就在。
  Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
    configurable: true,
    value: () => ({ ...spot, x: 100, y: 200, toJSON: () => spot }) as DOMRect,
  });
}

/** 把安上去的那个方法拆掉，别留给别的用例。 */
function dropGeometry() {
  delete (Range.prototype as unknown as Record<string, unknown>).getBoundingClientRect;
}

/** 把容器里第 `line` 行的第 `from`..`to` 个字圈起来，再松手。 */
function pick(container: HTMLElement, line: number, from: number, to: number) {
  const node = container.querySelectorAll('p')[line].firstChild as Text;
  const range = document.createRange();
  range.setStart(node, from);
  range.setEnd(node, to);
  const selection = document.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  act(() => {
    fireEvent.pointerUp(document);
    vi.runOnlyPendingTimers();
  });
}

function mount(onQuote = vi.fn()) {
  const ref = createRef<HTMLDivElement>();
  const view = render(
    <div>
      <div ref={ref} data-testid="stream">
        {STREAM_TEXT.map((line) => (
          <p key={line}>{line}</p>
        ))}
      </div>
      <SelectionQuote containerRef={ref} sessionId="s-1" onQuote={onQuote} />
    </div>
  );
  return { view, onQuote, container: screen.getByTestId('stream') };
}

describe('SelectionQuote', () => {
  let marks: Map<string, unknown>;

  beforeEach(() => {
    vi.useFakeTimers();
    marks = fakeHighlights();
    fakeGeometry();
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
    dropGeometry();
    document.getSelection()?.removeAllRanges();
  });

  it('圈中五个字及以上：只给引用按钮，一个字都不标绿', () => {
    const { container } = mount();
    pick(container, 0, 0, 7); // 「配方 A 跑完了」
    expect(screen.getByTestId('selection-quote-btn')).toBeTruthy();
    expect(marks.size).toBe(0);
  });

  it('圈中不到五个字：按钮照给，记录流里所有同字一起交给浏览器涂绿', () => {
    const { container } = mount();
    pick(container, 0, 0, 2); // 「配方」
    expect(screen.getByTestId('selection-quote-btn')).toBeTruthy();
    const painted = marks.get('workbench-quote-echo') as { ranges: Range[] };
    // 三行里各有一个「配方」。
    expect(painted.ranges).toHaveLength(3);
  });

  it('按下引用：交出圈中的原文，按钮与绿字一起退场', () => {
    const { container, onQuote } = mount();
    pick(container, 1, 0, 2);
    const btn = screen.getByTestId('selection-quote-btn');
    // **照真实顺序来：手先按下，抬起，浏览器才送出点击。** 只发点击会漏掉按下那一刻，
    // 而「按了引用什么都没发生」正是坏在那一刻——按钮在点击送达之前就被收掉了。
    act(() => {
      fireEvent.pointerDown(btn);
    });
    expect(screen.getByTestId('selection-quote-btn')).toBeTruthy();
    act(() => {
      fireEvent.pointerUp(btn);
      fireEvent.click(btn);
      vi.runOnlyPendingTimers();
    });
    expect(onQuote).toHaveBeenCalledWith('配方');
    expect(screen.queryByTestId('selection-quote')).toBeNull();
    expect(marks.size).toBe(0);
  });

  it('手按在正文别处：这一轮的按钮与绿字当场收掉', () => {
    const { container } = mount();
    pick(container, 1, 0, 2);
    expect(screen.getByTestId('selection-quote-btn')).toBeTruthy();
    act(() => {
      fireEvent.pointerDown(container);
    });
    expect(screen.queryByTestId('selection-quote')).toBeNull();
  });

  it('选区落在记录流外面：不理它', () => {
    mount();
    const outside = document.createElement('p');
    outside.textContent = '左栏里的字';
    document.body.appendChild(outside);
    const range = document.createRange();
    range.setStart(outside.firstChild as Text, 0);
    range.setEnd(outside.firstChild as Text, 3);
    document.getSelection()?.removeAllRanges();
    document.getSelection()?.addRange(range);
    act(() => {
      fireEvent.pointerUp(document);
      vi.runOnlyPendingTimers();
    });
    expect(screen.queryByTestId('selection-quote')).toBeNull();
    outside.remove();
  });
});

describe('echoRanges', () => {
  it('逐个文本节点找，同一节点里重复出现的每一处都算', () => {
    const root = document.createElement('div');
    root.innerHTML = '<p>配方配方</p><p>别的</p><p>配方</p>';
    expect(echoRanges(root, '配方')).toHaveLength(3);
    expect(echoRanges(root, '没有这个词')).toHaveLength(0);
  });

  it('分野写死在常量上：不到五个字才标绿', () => {
    expect(ECHO_MAX_CHARS).toBe(5);
  });
});
