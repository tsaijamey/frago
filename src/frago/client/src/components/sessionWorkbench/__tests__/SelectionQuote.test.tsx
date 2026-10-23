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

const probeSessionPath = vi.fn();
vi.mock('@/api', () => ({
  probeSessionPath: (sid: string, path: string) => probeSessionPath(sid, path),
}));

import SelectionQuote, {
  ECHO_MAX_CHARS,
  HIGHLIGHT_PRIORITY,
  echoRanges,
  paintHighlight,
  findMarkRange,
  markAnchor,
} from '../SelectionQuote';
import { useDataStore } from '@/stores/dataStore';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

/**
 * 探询那条命令每个用例都从零开始。
 *
 * 放在这一层而不是某一个 describe 里：按钮那几组用例分在好几个 describe 下，各自的
 * beforeEach 只管自己那一组，漏掉的那一组会把上一组的调用数带进下一组。
 *
 * 默认答「这台机器上没这份文件」——不关心预览的用例不该被一趟网络惊到。
 */
beforeEach(() => {
  probeSessionPath.mockReset();
  probeSessionPath.mockResolvedValue({
    path: '',
    resolved: null,
    exists: false,
    is_file: false,
    size: null,
  });
});

/**
 * 记录流里此刻摆着的字。同一个词故意在三处出现。
 *
 * 最后那一行是一条路径，给预览那颗按钮用：前三条是人话，圈它们不该冒出第四颗。
 */
const STREAM_TEXT = ['配方 A 跑完了', '配方 B 还没跑', '收尾闸门拦下了配方 C', 'docs/user-guide.md'];

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

function mount(onQuote = vi.fn(), onPreview?: (path: string, size: number | null) => void) {
  const ref = createRef<HTMLDivElement>();
  const view = render(
    <div>
      <div ref={ref} data-testid="stream">
        {STREAM_TEXT.map((line) => (
          <p key={line}>{line}</p>
        ))}
      </div>
      <SelectionQuote
        containerRef={ref}
        sessionId="s-1"
        onQuote={onQuote}
        onPreview={onPreview}
      />
    </div>
  );
  return { view, onQuote, container: screen.getByTestId('stream') };
}

/** 松手之后那一趟探询是异步的，等它落地再断言。 */
async function settle() {
  await act(async () => {
    vi.runOnlyPendingTimers();
  });
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

describe('paintHighlight 分份登记', () => {
  // 会话页与藏起来的 Teams 页各有一块记录流，共用同一个高亮名字。从前 Teams 那块一重涂
  // 就交一份空的，把会话页的引用底色整个撤掉。
  it('一块交空只撤自己那一份，别块涂的照旧留着', () => {
    const box = fakeHighlights();
    const root = document.createElement('div');
    root.innerHTML = '<p>引用这一段</p>';
    const [range] = echoRanges(root, '引用');
    const session = {};
    const teams = {};
    paintHighlight('workbench-mark-quote', [range], HIGHLIGHT_PRIORITY.quote, session);
    paintHighlight('workbench-mark-quote', [], HIGHLIGHT_PRIORITY.quote, teams);
    expect((box.get('workbench-mark-quote') as { ranges: Range[] }).ranges).toEqual([range]);
    paintHighlight('workbench-mark-quote', [], HIGHLIGHT_PRIORITY.quote, session);
    expect(box.has('workbench-mark-quote')).toBe(false);
  });
});

describe('暂存按钮', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    fakeHighlights();
    fakeGeometry();
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
    dropGeometry();
    document.getSelection()?.removeAllRanges();
  });

  /** 记录流里两条正文记录，第二条里「配方」出现两次。 */
  function mountBodies(onStack = vi.fn(), onQuote = vi.fn()) {
    const ref = createRef<HTMLDivElement>();
    render(
      <div>
        <div ref={ref} data-testid="stream">
          <div data-record-id="r1" data-record-body="">
            <p>配方 A 跑完了</p>
          </div>
          <div data-record-id="r2" data-record-body="">
            <p>配方 B 还没跑，配方 C 也没跑</p>
          </div>
          <p>工具输出里的字</p>
        </div>
        <SelectionQuote containerRef={ref} sessionId="s-1" onQuote={onQuote} onStack={onStack} />
      </div>
    );
    return { onStack, onQuote, container: screen.getByTestId('stream') };
  }

  it('两颗按钮都只画图标，名字在悬停时给', () => {
    const { container } = mountBodies();
    pick(container, 0, 0, 7);
    const quote = screen.getByTestId('selection-quote-btn');
    const stack = screen.getByTestId('selection-stack-btn');
    expect(quote.textContent).toBe('');
    expect(stack.textContent).toBe('');
    expect(quote.getAttribute('title')).toBe('引用');
    expect(stack.getAttribute('title')).toBe('暂存');
  });

  it('点暂存、写想法、回车：交出锚点与想法，数得出是第几次出现', () => {
    const { container, onStack } = mountBodies();
    pick(container, 1, 9, 11); // 第二条里第二个「配方」
    act(() => {
      fireEvent.click(screen.getByTestId('selection-stack-btn'));
    });
    const input = screen.getByTestId('selection-stack-input');
    act(() => {
      fireEvent.change(input, { target: { value: '  先放一放 ' } });
      fireEvent.submit(screen.getByTestId('selection-stack-note'));
    });
    expect(onStack).toHaveBeenCalledWith({ record_id: 'r2', text: '配方', occurrence: 1 }, '先放一放');
    expect(screen.queryByTestId('selection-quote')).toBeNull();
  });

  it('Esc 也存，留空就是不写想法', () => {
    const { container, onStack } = mountBodies();
    pick(container, 0, 0, 7);
    act(() => {
      fireEvent.click(screen.getByTestId('selection-stack-btn'));
    });
    act(() => {
      fireEvent.keyDown(screen.getByTestId('selection-stack-input'), { key: 'Escape' });
    });
    expect(onStack).toHaveBeenCalledWith({ record_id: 'r1', text: '配方 A 跑完', occurrence: 0 }, '');
  });

  it('写想法时点外面：不存', () => {
    const { container, onStack } = mountBodies();
    pick(container, 0, 0, 7);
    act(() => {
      fireEvent.click(screen.getByTestId('selection-stack-btn'));
    });
    act(() => {
      fireEvent.pointerDown(container);
    });
    expect(onStack).not.toHaveBeenCalled();
    expect(screen.queryByTestId('selection-quote')).toBeNull();
  });

  it('引用交出锚点', () => {
    const { container, onQuote } = mountBodies();
    pick(container, 0, 0, 2);
    act(() => {
      fireEvent.click(screen.getByTestId('selection-quote-btn'));
    });
    expect(onQuote).toHaveBeenCalledWith('配方', { record_id: 'r1', text: '配方', occurrence: 0 });
  });

  it('选区起点不在正文记录里：只给引用，不给暂存', () => {
    const { container } = mountBodies();
    pick(container, 2, 0, 4);
    expect(screen.getByTestId('selection-quote-btn')).toBeTruthy();
    expect(screen.queryByTestId('selection-stack-btn')).toBeNull();
  });
});

describe('分支按钮', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    fakeHighlights();
    fakeGeometry();
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
    dropGeometry();
    document.getSelection()?.removeAllRanges();
  });

  function mountBodies(onBranch = vi.fn()) {
    const ref = createRef<HTMLDivElement>();
    render(
      <div>
        <div ref={ref} data-testid="stream">
          <div data-record-id="r1" data-record-body="">
            <p>配方 A 跑完了</p>
          </div>
          <p>工具输出里的字</p>
        </div>
        <SelectionQuote
          containerRef={ref}
          sessionId="s-1"
          onQuote={vi.fn()}
          onStack={vi.fn()}
          onBranch={onBranch}
        />
      </div>
    );
    return { onBranch, container: screen.getByTestId('stream') };
  }

  it('第三颗只画分叉图标，悬停给名字', () => {
    const { container } = mountBodies();
    pick(container, 0, 0, 7);
    const btn = screen.getByTestId('selection-branch-btn');
    expect(btn.textContent).toBe('');
    expect(btn.getAttribute('title')).toBe('分支');
    expect(btn.querySelector('svg.lucide-git-branch')).toBeTruthy();
    expect(btn.querySelector('svg.lucide-git-merge')).toBeNull();
  });

  it('写一句话回车：交出锚点与那句话', () => {
    const { container, onBranch } = mountBodies();
    pick(container, 0, 0, 2);
    act(() => {
      fireEvent.click(screen.getByTestId('selection-branch-btn'));
    });
    act(() => {
      fireEvent.change(screen.getByTestId('selection-branch-input'), {
        target: { value: '  这个配方是干什么的 ' },
      });
      fireEvent.submit(screen.getByTestId('selection-branch-note'));
    });
    expect(onBranch).toHaveBeenCalledWith(
      { record_id: 'r1', text: '配方', occurrence: 0 },
      '这个配方是干什么的'
    );
    expect(screen.queryByTestId('selection-quote')).toBeNull();
  });

  it('那句话必填：空着回车只提示，不起会话', () => {
    const { container, onBranch } = mountBodies();
    pick(container, 0, 0, 2);
    act(() => {
      fireEvent.click(screen.getByTestId('selection-branch-btn'));
    });
    act(() => {
      fireEvent.submit(screen.getByTestId('selection-branch-note'));
    });
    expect(onBranch).not.toHaveBeenCalled();
    expect(screen.getByTestId('selection-branch-required')).toBeTruthy();
    // 打了字，提示就收起
    act(() => {
      fireEvent.change(screen.getByTestId('selection-branch-input'), { target: { value: '问' } });
    });
    expect(screen.queryByTestId('selection-branch-required')).toBeNull();
  });

  it('Esc 算作不起', () => {
    const { container, onBranch } = mountBodies();
    pick(container, 0, 0, 2);
    act(() => {
      fireEvent.click(screen.getByTestId('selection-branch-btn'));
    });
    act(() => {
      fireEvent.change(screen.getByTestId('selection-branch-input'), { target: { value: '问一句' } });
      fireEvent.keyDown(screen.getByTestId('selection-branch-input'), { key: 'Escape' });
    });
    expect(onBranch).not.toHaveBeenCalled();
    expect(screen.queryByTestId('selection-quote')).toBeNull();
  });

  it('浮窗内敲 / 弹出技能菜单：挑中 skill 后随分支一并交出，单挑 skill 不写字也能起分支', () => {
    useDataStore.setState({
      skills: [
        {
          name: 'frago-twitter-update',
          description: '撰写并制作 frago 日常更新推文',
          icon: null,
          file_path: '/p/frago-twitter-update/SKILL.md',
        },
      ],
    });
    const { container, onBranch } = mountBodies();
    pick(container, 0, 0, 7);
    act(() => {
      fireEvent.click(screen.getByTestId('selection-branch-btn'));
    });
    const input = screen.getByTestId('selection-branch-input') as HTMLTextAreaElement;
    // 浮窗复用 PromptComposerBox：敲 /frago 弹出 SkillMenu
    act(() => {
      fireEvent.focus(input);
      fireEvent.change(input, { target: { value: '/frago', selectionStart: 6 } });
    });
    expect(screen.getByTestId('skill-menu')).toBeTruthy();

    // 菜单开着时按 Esc 只关菜单，不关浮窗
    act(() => {
      fireEvent.keyDown(input, { key: 'Escape' });
    });
    expect(screen.queryByTestId('skill-menu')).toBeNull();
    expect(screen.getByTestId('selection-branch-note')).toBeTruthy();

    // 重新敲 /frago 并按 Enter 挑中 skill，转为顶部 SkillQuote 签
    act(() => {
      fireEvent.change(input, { target: { value: '/frago ', selectionStart: 7 } });
      fireEvent.change(input, { target: { value: '/frago', selectionStart: 6 } });
    });
    expect(screen.getByTestId('skill-menu')).toBeTruthy();
    act(() => {
      fireEvent.keyDown(input, { key: 'Enter' });
    });
    expect(screen.getByTestId('selection-branch-skills')).toBeTruthy();
    expect(input.value).toBe('');

    // 不写额外文字、只靠挑中的 skill 也能直接 Cmd+Enter 提交分支
    act(() => {
      fireEvent.keyDown(input, { key: 'Enter', metaKey: true });
    });
    expect(onBranch).toHaveBeenCalledWith(
      { record_id: 'r1', text: '配方 A 跑完', occurrence: 0 },
      '',
      {
        images: [],
        documents: [],
        skills: ['frago-twitter-update'],
      }
    );
    expect(screen.queryByTestId('selection-quote')).toBeNull();
  });

  it('选区起点不在正文记录里：不给分支', () => {
    const { container } = mountBodies();
    pick(container, 1, 0, 4);
    expect(screen.getByTestId('selection-quote-btn')).toBeTruthy();
    expect(screen.queryByTestId('selection-branch-btn')).toBeNull();
  });

  it('圈中一条真文件路径：多一颗预览，按下交出服务端解出来的绝对路径', async () => {
    probeSessionPath.mockResolvedValue({
      path: 'docs/user-guide.md',
      resolved: '/Users/frago/Repos/frago/docs/user-guide.md',
      exists: true,
      is_file: true,
      size: 4096,
    });
    const onPreview = vi.fn();
    const { container } = mount(vi.fn(), onPreview);
    pick(container, 3, 0, 'docs/user-guide.md'.length);
    await settle();

    // 相对路径在界面这一侧解不出可信的答案，问的是服务端，用的也是这场会话。
    expect(probeSessionPath).toHaveBeenCalledWith('s-1', 'docs/user-guide.md');

    const btn = screen.getByTestId('selection-preview-btn');
    act(() => {
      fireEvent.mouseDown(btn);
      btn.click();
    });
    expect(onPreview).toHaveBeenCalledWith('/Users/frago/Repos/frago/docs/user-guide.md', 4096);
    // 按完与其余三颗同一个规矩：按钮退场，选区收掉。
    expect(screen.queryByTestId('selection-quote')).toBeNull();
  });

  it('形状像路径但这台机器上没有这么一份：不给预览', async () => {
    probeSessionPath.mockResolvedValue({
      path: 'docs/user-guide.md',
      resolved: '/Users/frago/Repos/frago/docs/user-guide.md',
      exists: false,
      is_file: false,
      size: null,
    });
    const { container } = mount(vi.fn(), vi.fn());
    pick(container, 3, 0, 'docs/user-guide.md'.length);
    await settle();
    expect(screen.getByTestId('selection-quote-btn')).toBeTruthy();
    expect(screen.queryByTestId('selection-preview-btn')).toBeNull();
  });

  it('圈中一句人话：连问都不问服务端', async () => {
    const { container } = mount(vi.fn(), vi.fn());
    pick(container, 0, 0, 7); // 「配方 A 跑完了」
    await settle();
    expect(probeSessionPath).not.toHaveBeenCalled();
    expect(screen.queryByTestId('selection-preview-btn')).toBeNull();
  });
});

describe('标注的锚点', () => {
  function body(html: string): HTMLElement {
    const root = document.createElement('div');
    root.innerHTML = `<div data-record-id="r" data-record-body="">${html}</div>`;
    document.body.appendChild(root);
    return root;
  }

  it('记下与找回用同一把尺子：分段多出来的换行不影响', () => {
    const root = body('<p>第一段结尾</p><p>第二段开头，第二段开头</p>');
    const el = root.querySelector('[data-record-body]') as Element;
    const second = root.querySelectorAll('p')[1].firstChild as Text;
    const range = document.createRange();
    range.setStart(second, 6);
    range.setEnd(second, 11);
    const anchor = markAnchor(root, range, '第二段开头');
    expect(anchor).toEqual({ record_id: 'r', text: '第二段开头', occurrence: 1 });
    const found = findMarkRange(el, '第二段开头', 1) as Range;
    expect(found.startOffset).toBe(6);
    expect(found.toString()).toBe('第二段开头');
    // 选区文本跨段时带着换行，找回照样对得上
    expect(findMarkRange(el, '结尾\n\n第二段', 0)?.toString()).toBe('结尾第二段');
    root.remove();
  });

  it('出现次数不够算找不到', () => {
    const root = body('<p>只有一处配方</p>');
    expect(findMarkRange(root, '配方', 1)).toBeNull();
    root.remove();
  });

  it('跨记录圈的：只着起点那条末尾能对上的那一截', () => {
    const root = body('<p>上一条的最后几个字</p>');
    expect(findMarkRange(root, '最后几个字下一条开头', 0)?.toString()).toBe('最后几个字');
    expect(findMarkRange(root, '完全无关的一段', 0)).toBeNull();
    root.remove();
  });
});
