/**
 * 记录流右侧的缩略滚动条，以及它身后的标注着色。
 *
 * 盯三件事：只在「全部」「对话」两档出现；绿条对人发言、灰条对代理回复，其余记录不画；
 * 刻度颜色按标注状态出（没用过的暂存橙、没收口的分支正文色、其余中性——spec
 * 20260928-webui-session-branch 的配色表），与交给浏览器的分组一致。另外钉住取色规矩：
 * 重叠处「暂存 > 没收口的分支 > 中性底」、找不到的标注不画也不报错、界面上不再有蓝。
 *
 * jsdom 里没有几何，所有位置都是 0——这里只核对画了什么、画成什么颜色，不核对画在哪。
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import StreamMinimap from '../StreamMinimap';

import RecordStream from '../RecordStream';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import type { WorkbenchMark } from '@/hooks/useSessionMarks';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const SID = 'sid-minimap';
let seq = 0;

function rec(over: Partial<WorkbenchRecord> & Pick<WorkbenchRecord, 'kind'>): WorkbenchRecord {
  seq += 1;
  return {
    id: `m${seq}`,
    session_id: SID,
    group_id: null,
    seq,
    ts: 1_753_800_000_000 + seq * 1000,
    agent_path: [],
    payload: {},
    raw_available: false,
    ...over,
  };
}

function mark(id: string, recordId: string, text: string, fields: Partial<WorkbenchMark> = {}) {
  return {
    id,
    kind: 'stack',
    record_id: recordId,
    text,
    occurrence: 0,
    note: '',
    used: false,
    created_at: 1,
    used_at: null,
    ...fields,
  } as WorkbenchMark;
}

/** 浏览器那本高亮账，由替身记下都标了些什么。 */
function fakeHighlights() {
  const box = new Map<string, { ranges: Range[]; priority?: number }>();
  Object.defineProperty(CSS, 'highlights', {
    configurable: true,
    value: {
      set: (name: string, value: { ranges: Range[] }) => box.set(name, value),
      delete: (name: string) => box.delete(name),
    },
  });
  (window as unknown as { Highlight: unknown }).Highlight = class {
    ranges: Range[];
    priority = 0;
    constructor(...ranges: Range[]) {
      this.ranges = ranges;
    }
  };
  return box;
}

const user = rec({ kind: 'user.say', payload: { text: '先看第一个决策点' } });
const call = rec({
  kind: 'tool.call',
  payload: { call_id: 'c1', tool_name: 'Read', tool_family: 'file-read', args: { file_path: '/x' } },
});
const result = rec({ kind: 'tool.result', payload: { call_id: 'c1', tool_name: 'Read', status: 'ok', body: 'ok' } });
const reply = rec({ kind: 'agent.say', payload: { text: '第一点选甲，第二点选乙，第三点待定' } });
const RECORDS = [user, call, result, reply];

function mount(marks: WorkbenchMark[] = []) {
  return render(
    <RecordStream
      sessionId={SID}
      records={RECORDS}
      loading={false}
      loadingOlder={false}
      hasOlder={false}
      error={null}
      onLoadOlder={() => {}}
      marks={marks}
      minimap
    />
  );
}

describe('StreamMinimap', () => {
  let painted: Map<string, { ranges: Range[]; priority?: number }>;

  beforeEach(() => {
    painted = fakeHighlights();
  });

  afterEach(() => {
    delete (CSS as unknown as Record<string, unknown>).highlights;
  });

  it('默认不挂：Teams 页也用这条记录流，只有会话页打开它', () => {
    render(
      <RecordStream
        sessionId={SID}
        records={RECORDS}
        loading={false}
        loadingOlder={false}
        hasOlder={false}
        error={null}
        onLoadOlder={() => {}}
      />
    );
    expect(screen.queryByTestId('stream-minimap')).toBeNull();
  });

  it('只在「全部」「对话」两档出现', () => {
    mount();
    // 默认落在对话档
    expect(screen.getByTestId('stream-minimap')).toBeTruthy();
    fireEvent.click(screen.getByTestId('lens-all'));
    expect(screen.getByTestId('stream-minimap')).toBeTruthy();
    fireEvent.click(screen.getByTestId('lens-inspect-toggle'));
    fireEvent.click(screen.getByTestId('lens-tool'));
    expect(screen.queryByTestId('stream-minimap')).toBeNull();
    fireEvent.click(screen.getByTestId('lens-talk'));
    expect(screen.getByTestId('stream-minimap')).toBeTruthy();
  });

  it('区段条在时藏原生竖条，不在时竖条照旧', () => {
    mount();
    const scroll = () => screen.getByTestId('record-stream-scroll');
    expect(scroll().classList.contains('record-stream-no-bar')).toBe(true);
    fireEvent.click(screen.getByTestId('lens-inspect-toggle'));
    fireEvent.click(screen.getByTestId('lens-tool'));
    expect(scroll().classList.contains('record-stream-no-bar')).toBe(false);
    fireEvent.click(screen.getByTestId('lens-all'));
    expect(scroll().classList.contains('record-stream-no-bar')).toBe(true);
  });

  it('绿条对人发言、灰条对代理回复，工具记录不画', () => {
    mount();
    fireEvent.click(screen.getByTestId('lens-all'));
    const bars = [...screen.getByTestId('stream-minimap').querySelectorAll('[data-minimap-bar]')];
    expect(bars.map((b) => b.getAttribute('data-minimap-bar'))).toEqual(['user', 'agent']);
    expect(bars[0].className).toContain('bg-accent-primary');
    expect(bars[1].className).not.toContain('bg-accent-primary');
  });

  it('纯 <frago-async-callback> 回传记录标为 async.callback，在缩略滚动条画成中性灰条（agent）而不留白或画成绿条', () => {
    const pureCallback = rec({
      kind: 'user.say',
      payload: {
        text: '<frago-async-callback kind="worker" mode="new" job_id="disp-1" worker_session_id="core_1" status="completed">\n### Worker 交付结果\n已完成\n</frago-async-callback>',
      },
    });
    const { container } = render(
      <RecordStream
        sessionId={SID}
        records={[user, pureCallback, reply]}
        loading={false}
        loadingOlder={false}
        hasOlder={false}
        error={null}
        onLoadOlder={() => {}}
        minimap
      />
    );
    const bodyWrap = container.querySelector(`[data-record-id="${pureCallback.id}"][data-record-body]`);
    expect(bodyWrap?.getAttribute('data-record-kind')).toBe('async.callback');
    const bars = [...screen.getByTestId('stream-minimap').querySelectorAll('[data-minimap-bar]')];
    expect(bars.map((b) => b.getAttribute('data-minimap-bar'))).toEqual(['user', 'agent', 'agent']);
    expect(bars[1].className).toContain('bg-text-muted');
    expect(bars[1].className).not.toContain('bg-accent-primary');
  });

  it('混合记录（异步回传块 + 人类提问）在缩略滚动条上分别画成上灰条（agent）与下绿条（user）', () => {
    const mixedRecord = rec({
      kind: 'user.say',
      payload: {
        text: '<frago-async-callback kind="worker" mode="new" job_id="disp-2" worker_session_id="core_2" status="completed">\n### Worker 交付结果\n已完成\n</frago-async-callback>\n查一下本地workbuddy proxy是不是被误关了',
      },
    });
    render(
      <RecordStream
        sessionId={SID}
        records={[mixedRecord, reply]}
        loading={false}
        loadingOlder={false}
        hasOlder={false}
        error={null}
        onLoadOlder={() => {}}
        minimap
      />
    );
    const bars = [...screen.getByTestId('stream-minimap').querySelectorAll('[data-minimap-bar]')];
    expect(bars.map((b) => b.getAttribute('data-minimap-bar'))).toEqual(['agent', 'user', 'agent']);
    expect(bars[0].className).toContain('bg-text-muted');
    expect(bars[1].className).toContain('bg-accent-primary');
    expect(bars[2].className).toContain('bg-text-muted');
  });

  it('可视区滑块用半透明中性底色与中性描边，不复用不透明的选中态实色底', () => {
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => 200 });
    try {
      mount();
      const thumb = screen.getByTestId('stream-minimap-thumb');
      expect(thumb.className).toContain('bg-[var(--bg-active)]');
      expect(thumb.className).toContain('border-[var(--border-strong)]');
      expect(thumb.className).not.toContain('--sel-bg');
      expect(thumb.className).not.toContain('--sel-border');
    } finally {
      delete (HTMLElement.prototype as { clientHeight?: number }).clientHeight;
    }
  });

  it('刻度颜色按标注状态出：没用过的暂存橙，没收口的分支正文色，其余中性', () => {
    mount([
      mark('s1', reply.id, '第三点待定'),
      mark('s2', reply.id, '第一点选甲', { used: true, used_at: 2 }),
      mark('q1', user.id, '第一个决策点', { kind: 'quote' }),
      mark('b1', reply.id, '第二点选乙', { kind: 'branch', child_session_id: 'kid', closed: false }),
      mark('b2', user.id, '先看', { kind: 'branch', child_session_id: 'kid2', closed: true }),
    ]);
    const ticks = [...screen.getByTestId('stream-minimap').querySelectorAll('[data-minimap-tick]')];
    const tones = ticks.map((el) => el.getAttribute('data-minimap-tick')).sort();
    expect(tones).toEqual(['branch', 'quote', 'quote', 'quote', 'stack']);
    const cls = (tone: string) =>
      ticks.filter((el) => el.getAttribute('data-minimap-tick') === tone).map((el) => el.className);
    expect(cls('stack').every((c) => c.includes('bg-accent-warning'))).toBe(true);
    expect(cls('branch').every((c) => c.includes('bg-text-primary'))).toBe(true);
    expect(cls('quote').every((c) => c.includes('bg-text-muted'))).toBe(true);
    // 原型配色里没有蓝：刻度一道都不许是蓝的。
    expect(ticks.some((el) => el.className.includes('accent-info'))).toBe(false);
    // 正文的分组与刻度同一套
    expect(painted.get('workbench-mark-stack')?.ranges.map((r) => r.toString())).toEqual(['第三点待定']);
    expect(painted.get('workbench-mark-branch')?.ranges.map((r) => r.toString())).toEqual(['第二点选乙']);
    expect(painted.get('workbench-mark-quote')?.ranges.map((r) => r.toString()).sort()).toEqual(
      ['第一个决策点', '第一点选甲', '先看'].sort()
    );
  });

  it('重叠优先级：暂存 > 没收口的分支 > 中性底', () => {
    mount([
      mark('q', reply.id, '第一点选甲，第二点选乙，第三点', { kind: 'quote' }),
      mark('b', reply.id, '第二点选乙，第三点待定', { kind: 'branch', child_session_id: 'kid' }),
      mark('s', reply.id, '第三点待定'),
    ]);
    expect(painted.get('workbench-mark-stack')?.ranges.map((r) => r.toString())).toEqual(['第三点待定']);
    expect(painted.get('workbench-mark-branch')?.ranges.map((r) => r.toString())).toEqual(['第二点选乙，']);
    expect(painted.get('workbench-mark-quote')?.ranges.map((r) => r.toString())).toEqual(['第一点选甲，']);
    const pr = (name: string) => painted.get(name)?.priority ?? 0;
    expect(pr('workbench-mark-stack')).toBeGreaterThan(pr('workbench-mark-branch'));
    expect(pr('workbench-mark-branch')).toBeGreaterThan(pr('workbench-mark-quote'));
  });

  it('重叠处暂存压过引用：引用那一段挖掉被暂存盖住的部分', () => {
    mount([
      mark('q', reply.id, '第二点选乙，第三点', { kind: 'quote' }),
      mark('s', reply.id, '第三点待定'),
    ]);
    expect(painted.get('workbench-mark-stack')?.ranges.map((r) => r.toString())).toEqual(['第三点待定']);
    expect(painted.get('workbench-mark-quote')?.ranges.map((r) => r.toString())).toEqual(['第二点选乙，']);
    expect(painted.get('workbench-mark-stack')?.priority).toBeGreaterThan(
      painted.get('workbench-mark-quote')?.priority ?? 0
    );
  });

  it('找不到的标注不画刻度、不着色，也不报错', () => {
    mount([mark('gone', reply.id, '这段话已经不在了'), mark('nobody', 'no-such-record', '随便')]);
    expect(screen.getByTestId('stream-minimap').querySelectorAll('[data-minimap-tick]')).toHaveLength(0);
    expect(painted.has('workbench-mark-stack')).toBe(false);
  });
});

describe('跳回原处：往前翻页没取回来', () => {
  it('翻完一页最早那条没变，报「没找到原处」，不原地连着重翻', () => {
    const target = mark('old', 'not-loaded-yet', '更早的一段');
    const results: string[] = [];
    let loads = 0;
    const props = {
      sessionId: SID,
      records: RECORDS,
      loading: false,
      hasOlder: true,
      error: null,
      onLoadOlder: () => {
        loads += 1;
      },
      marks: [target],
      locateTarget: { mark: target, at: 1 },
      onLocateResult: (_id: string, r: string) => results.push(r),
    };
    const { rerender } = render(<RecordStream {...props} loadingOlder={false} />);
    expect(loads).toBe(1);
    expect(results.at(-1)).toBe('searching');
    // 这一页在路上
    rerender(<RecordStream {...props} loadingOlder />);
    expect(results.at(-1)).toBe('searching');
    // 回来了，但什么也没取到（接口失败）
    rerender(<RecordStream {...props} loadingOlder={false} />);
    expect(loads).toBe(1);
    expect(results.at(-1)).toBe('notFound');
    // 人再点一次原文：从头再找
    rerender(<RecordStream {...props} loadingOlder={false} locateTarget={{ mark: target, at: 2 }} />);
    expect(loads).toBe(2);
    expect(results.at(-1)).toBe('searching');
  });
});

describe('点没收口的分支标注：打开分支 / 标记已收口', () => {
  const realRects = Range.prototype.getClientRects;
  beforeEach(() => {
    fakeHighlights();
    // jsdom 量不出文字的位置：每段文字都当成落在 (0,0)–(100,20) 这一块里。
    Range.prototype.getClientRects = function () {
      return [{ left: 0, right: 100, top: 0, bottom: 20 }] as unknown as DOMRectList;
    };
  });
  afterEach(() => {
    Range.prototype.getClientRects = realRects;
    delete (CSS as unknown as Record<string, unknown>).highlights;
  });

  function mountWith(marks: WorkbenchMark[], handlers: { open?: (c: string) => void; close?: (m: WorkbenchMark) => void }) {
    return render(
      <RecordStream
        sessionId={SID}
        records={RECORDS}
        loading={false}
        loadingOlder={false}
        hasOlder={false}
        error={null}
        onLoadOlder={() => {}}
        marks={marks}
        onOpenBranch={handlers.open}
        onCloseBranch={handlers.close}
      />
    );
  }

  it('点在虚线上弹菜单，两项各交出对的东西', () => {
    const opened: string[] = [];
    const closed: string[] = [];
    const branch = mark('b1', reply.id, '第二点选乙', { kind: 'branch', child_session_id: 'kid' });
    mountWith([branch], { open: (c) => opened.push(c), close: (m) => closed.push(m.id) });
    fireEvent.click(screen.getByTestId('record-stream-scroll'), { clientX: 10, clientY: 10 });
    fireEvent.click(screen.getByTestId('branch-mark-open'));
    expect(opened).toEqual(['kid']);
    expect(screen.queryByTestId('branch-mark-menu')).toBeNull();

    fireEvent.click(screen.getByTestId('record-stream-scroll'), { clientX: 10, clientY: 10 });
    fireEvent.click(screen.getByTestId('branch-mark-close'));
    expect(closed).toEqual(['b1']);
  });

  it('点在别处不弹；收了口的分支不弹', () => {
    const branch = mark('b1', reply.id, '第二点选乙', { kind: 'branch', child_session_id: 'kid' });
    const { unmount } = mountWith([branch], { open: () => {}, close: () => {} });
    fireEvent.click(screen.getByTestId('record-stream-scroll'), { clientX: 400, clientY: 400 });
    expect(screen.queryByTestId('branch-mark-menu')).toBeNull();
    unmount();

    mountWith([{ ...branch, closed: true }], { open: () => {}, close: () => {} });
    fireEvent.click(screen.getByTestId('record-stream-scroll'), { clientX: 10, clientY: 10 });
    expect(screen.queryByTestId('branch-mark-menu')).toBeNull();
  });

  it('Esc 收起菜单', () => {
    const branch = mark('b1', reply.id, '第二点选乙', { kind: 'branch', child_session_id: 'kid' });
    mountWith([branch], { open: () => {}, close: () => {} });
    fireEvent.click(screen.getByTestId('record-stream-scroll'), { clientX: 10, clientY: 10 });
    expect(screen.getByTestId('branch-mark-menu')).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByTestId('branch-mark-menu')).toBeNull();
  });
});

describe('方案 4A：过程旁白过滤、滚动条暂存轨、180ms 悬停提示与键盘滚动', () => {
  let painted: Map<string, { ranges: Range[]; priority?: number }>;

  beforeEach(() => {
    painted = fakeHighlights();
  });

  afterEach(() => {
    vi.useRealTimers();
    delete (CSS as unknown as Record<string, unknown>).highlights;
    delete (HTMLElement.prototype as { clientHeight?: number }).clientHeight;
  });

  it('tool.call 之前的中间过程旁白带有 data-minimap-exclude 且不画进缩略条，只保留用户提问与最终回复', () => {
    const u1 = rec({ kind: 'user.say', payload: { text: '查一下配置' } });
    const midNarration = rec({ kind: 'agent.say', payload: { text: '我先看下文件' } });
    const tc = rec({
      kind: 'tool.call',
      payload: { call_id: 'c-nar', tool_name: 'Read', tool_family: 'file-read', args: { file_path: '/a' } },
    });
    const tr = rec({ kind: 'tool.result', payload: { call_id: 'c-nar', tool_name: 'Read', status: 'ok', body: 'ok' } });
    const finalSay = rec({ kind: 'agent.say', payload: { text: '查完了，结论如下' } });

    const { container } = render(
      <RecordStream
        sessionId={SID}
        records={[u1, midNarration, tc, tr, finalSay]}
        loading={false}
        loadingOlder={false}
        hasOlder={false}
        error={null}
        onLoadOlder={() => {}}
        minimap
      />
    );

    // 切到全部镜头检验：即使中栏展示中间旁白 DOM，仍带有 data-minimap-exclude="true"
    fireEvent.click(screen.getByTestId('lens-all'));
    const midBody = container.querySelector(`[data-record-id="${midNarration.id}"][data-record-body]`);
    const finalBody = container.querySelector(`[data-record-id="${finalSay.id}"][data-record-body]`);
    expect(midBody?.getAttribute('data-minimap-exclude')).toBe('true');
    expect(finalBody?.hasAttribute('data-minimap-exclude')).toBe(false);

    const bars = [...screen.getByTestId('stream-minimap').querySelectorAll('[data-minimap-bar]')];
    expect(bars.map((b) => b.getAttribute('data-minimap-bar'))).toEqual(['user', 'agent']);
    expect(painted.size).toBe(0);
  });

  it('展示滚动条暂存轨标签与顶部汇总胶囊、支持 180ms 悬停提示与 stackFreeze 冻结', () => {
    vi.useFakeTimers();
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => 480 });

    const unloaded = mark('s-old', 'missing-record-id', '更早的决策');
    const activeLoaded = mark('s-now', reply.id, '第三点待定', { note: '先核对配置' });
    const usedMark = mark('s-used', user.id, '先看', { used: true, used_at: 10 });
    const onOpenPopover = vi.fn();
    const onFreezeChange = vi.fn();
    const onUserScroll = vi.fn();

    const scrollBox = document.createElement('div');
    Object.defineProperty(scrollBox, 'scrollHeight', { configurable: true, value: 1200 });
    Object.defineProperty(scrollBox, 'clientHeight', { configurable: true, value: 480 });
    scrollBox.scrollTop = 100;
    const recEl = document.createElement('div');
    recEl.setAttribute('data-record-id', reply.id);
    recEl.getBoundingClientRect = () => ({ top: 240, left: 0, right: 200, bottom: 300 } as DOMRect);
    scrollBox.appendChild(recEl);
    document.body.appendChild(scrollBox);

    try {
      const scrollRef = { current: scrollBox };
      const { rerender } = render(
        <StreamMinimap
          scrollRef={scrollRef}
          ticks={[]}
          version={1}
          onUserScroll={onUserScroll}
          marks={[unloaded, activeLoaded, usedMark]}
          onOpenPopover={onOpenPopover}
          onFreezeChange={onFreezeChange}
        />
      );

      // 顶部汇总胶囊与轨侧标签同时渲染
      expect(screen.getByTestId('stack-top-summary')).toBeTruthy();
      const label = screen.getByTestId('stack-rail-label');
      expect(label.getAttribute('data-mark-id')).toBe('s-now');
      expect(label.textContent).toContain('先核对配置');

      // 悬停在标签层触发 stackFreeze，180ms 后出现 tooltip
      const layer = screen.getByTestId('stack-labels-layer');
      fireEvent.mouseEnter(layer);
      expect(screen.getByTestId('stream-minimap-dock').getAttribute('data-frozen')).toBe('true');
      expect(onFreezeChange).toHaveBeenLastCalledWith(true);

      fireEvent.mouseEnter(label);
      expect(screen.queryByTestId('stack-hover-tip')).toBeNull();
      act(() => {
        vi.advanceTimersByTime(185);
      });
      expect(screen.getByTestId('stack-hover-tip').textContent).toContain('先核对配置');

      // 点击标签触发 onOpenPopover
      fireEvent.click(label);
      expect(onOpenPopover).toHaveBeenCalledTimes(1);
      expect(onOpenPopover.mock.calls[0][0].mode).toBe('item');
      expect(onOpenPopover.mock.calls[0][0].markId).toBe('s-now');

      // 离开标签层，若 popoverOpen 为 true 仍保持冻结
      fireEvent.mouseLeave(layer);
      rerender(
        <StreamMinimap
          scrollRef={scrollRef}
          ticks={[]}
          version={1}
          onUserScroll={onUserScroll}
          marks={[unloaded, activeLoaded, usedMark]}
          popoverOpen
          onOpenPopover={onOpenPopover}
          onFreezeChange={onFreezeChange}
        />
      );
      expect(screen.getByTestId('stream-minimap-dock').getAttribute('data-frozen')).toBe('true');

      // 键盘方向键滚动触发 onUserScroll 并更新 scrollTop
      const track = screen.getByTestId('stream-minimap');
      fireEvent.keyDown(track, { key: 'ArrowDown' });
      expect(onUserScroll).toHaveBeenCalledTimes(1);
      expect(scrollBox.scrollTop).toBe(148);

      fireEvent.keyDown(track, { key: 'End' });
      expect(scrollBox.scrollTop).toBe(720);

      fireEvent.keyDown(track, { key: 'Home' });
      expect(scrollBox.scrollTop).toBe(0);
    } finally {
      scrollBox.remove();
    }
  });

  it('矮视口（railHeight < 480px）下 SVG viewBox 高度与实测轨道高度一致，折线与标签中点对齐', () => {
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => 300 });
    const active = mark('s-short', reply.id, '矮视口标签', { note: '短窗口校验' });

    const scrollBox = document.createElement('div');
    Object.defineProperty(scrollBox, 'scrollHeight', { configurable: true, value: 900 });
    Object.defineProperty(scrollBox, 'clientHeight', { configurable: true, value: 300 });
    scrollBox.scrollTop = 0;
    const recEl = document.createElement('div');
    recEl.setAttribute('data-record-id', reply.id);
    recEl.getBoundingClientRect = () => ({ top: 150, left: 0, right: 200, bottom: 210 } as DOMRect);
    scrollBox.appendChild(recEl);
    document.body.appendChild(scrollBox);

    try {
      render(
        <StreamMinimap
          scrollRef={{ current: scrollBox }}
          ticks={[]}
          version={1}
          onUserScroll={vi.fn()}
          marks={[active]}
          onOpenPopover={vi.fn()}
          onFreezeChange={vi.fn()}
        />
      );

      const layer = screen.getByTestId('stack-labels-layer');
      const svg = layer.querySelector('svg.mm-leader-svg');
      expect(svg).not.toBeNull();
      const viewBoxParts = (svg!.getAttribute('viewBox') || '').split(' ').map(Number);
      expect(viewBoxParts[3]).toBe(300);

      const label = screen.getByTestId('stack-rail-label');
      const labelTop = Number.parseFloat(label.style.top);
      const labelMidY = labelTop + 11; // STACK_LABEL_H (22) / 2
      const pathD = svg!.querySelector('path')?.getAttribute('d') || '';
      const startY = Number.parseFloat(pathD.split(' ')[2]);
      expect(Math.abs(startY - labelMidY)).toBeLessThan(0.2);
    } finally {
      scrollBox.remove();
    }
  });
});
