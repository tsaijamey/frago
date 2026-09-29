/**
 * 左栏只留一个标记「For you」之后的用例。
 *
 * 盯的是摆放与字样：每张卡三行（标题、预览、状态行），For you 与其余同一结构；分区顺序
 * Pinned → For you → Everything else；所有 For you 标签同一画法（品牌绿）；档位只剩
 * For you / All；状态词一个都不出现；可关终端那一行；开在 tmux 里的流光照旧（主人 09-24
 * 定）；点开记一笔看过了、但不撤 For you；选中那张发出后原位不动、切走才归位（第五轮）。
 * 挂不挂的判据由 `useForYou.test.ts` 把关，这里直接给定判定结果。
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { TestRail, fakeForYou, fakeViews } from './railTestKit';
import { placeHeld, slotOf, type RailSections } from '../SessionRail';
import type { WorkbenchSession, WorkbenchSessionsState } from '@/hooks/useWorkbenchSessions';
import type { ForYouInfo } from '@/hooks/useForYou';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('en');
});

const pins = vi.hoisted(() => ({ pinned: [] as string[], collapsed: false }));

vi.mock('@/hooks/useSessionPins', () => ({
  useSessionPins: () => ({
    pinned: pins.pinned,
    isPinned: (id: string) => pins.pinned.includes(id),
    toggle: vi.fn(async () => {}),
    collapsed: pins.collapsed,
    setCollapsed: vi.fn(),
  }),
}));

vi.mock('@/api', () => ({ closeTmuxSessions: vi.fn(async () => ({ results: [], closed: 1, failed: 0 })) }));

const NOOP = () => {};
const NOW = Date.now();

function session(id: string, over: Partial<WorkbenchSession> = {}): WorkbenchSession {
  return {
    session_id: id,
    family: 'claude-code',
    title: `title ${id}`,
    directory: '/Users/frago/Repos/frago',
    created_at: NOW - 3_600_000,
    last_active_at: NOW - 600_000,
    last_reply_at: NOW - 600_000,
    agent_paths: [],
    status: 'done',
    digest_done: 'did a thing',
    digest_stuck: null,
    origin: 'human',
    parent_session_id: null,
    ...over,
  };
}

function railState(rows: WorkbenchSession[]): WorkbenchSessionsState {
  return {
    sessions: rows,
    visible: rows,
    loading: false,
    error: null,
    filter: 'all',
    setFilter: NOOP,
    days: 0,
    setDays: NOOP,
    counts: { all: rows.length, 'for-you': 1 },
    reload: async () => {},
  };
}

function info(over: Partial<ForYouInfo> = {}): ForYouInfo {
  return { waitingSince: NOW - 44 * 60_000, words: 'Want me to log it?', unseen: false, ...over };
}

const rows = [session('a'), session('b'), session('c')];

beforeEach(() => {
  pins.pinned = [];
  pins.collapsed = false;
});

describe('For you 在清单上', () => {
  it('每张卡三行：标题、预览（人人都有）、状态行；For you 与其余同一结构', () => {
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} forYou={fakeForYou({ b: info() })} />);
    const items = screen.getAllByTestId('session-item');
    for (const el of items) {
      expect(el.querySelector('[data-testid=session-title]')).toBeTruthy();
      expect(el.querySelector('[data-testid=session-preview]')).toBeTruthy();
      expect(el.querySelector('[data-testid=session-status] [data-testid=session-menu-button]')).toBeTruthy();
    }
    const waiting = items.find((el) => el.getAttribute('data-for-you') === 'true')!;
    expect(waiting.querySelector('[data-testid=session-status]')?.textContent).toContain('For you');
    expect(waiting.querySelector('[data-testid=session-preview]')?.textContent).toBe('Want me to log it?');
    // 不在 For you 的也有预览：会话清单的回复摘要
    const other = items.find((el) => !el.getAttribute('data-for-you'))!;
    expect(other.querySelector('[data-testid=session-preview]')?.textContent).toBe('did a thing');
    expect(screen.getAllByTestId('for-you-chip')).toHaveLength(1);
    // 摘要、来源、状态词都退场了
    expect(screen.queryByTestId('digest-done')).toBeNull();
    expect(items.some((el) => el.textContent?.includes('Claude Code'))).toBe(false);
  });

  it('分区顺序：Pinned → For you → Everything else', () => {
    pins.pinned = ['c'];
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} forYou={fakeForYou({ b: info() })} />);
    const titles = screen.getAllByTestId('session-item').map((el) => el.textContent ?? '');
    expect(titles[0]).toContain('title c');
    expect(titles[1]).toContain('title b');
    expect(titles[2]).toContain('title a');
    expect(screen.getByTestId('pinned-header').textContent).toContain('Always on top');
    expect(screen.getByTestId('rest-header').textContent).toContain('Everything else');
  });

  it('置顶里也挂着 For you 的，For you 组标题右端注明', () => {
    pins.pinned = ['c'];
    render(
      <TestRail
        state={railState(rows)}
        selectedId={null}
        onSelect={NOOP}
        forYou={fakeForYou({ b: info(), c: info() })}
      />
    );
    expect(screen.getByTestId('for-you-header').textContent).toContain('+ 1 in Pinned above');
  });

  it('For you 组里等得最久的在上', () => {
    render(
      <TestRail
        state={railState(rows)}
        selectedId={null}
        onSelect={NOOP}
        forYou={fakeForYou({
          a: info({ waitingSince: NOW - 60_000 }),
          c: info({ waitingSince: NOW - 3_600_000 }),
        })}
      />
    );
    const titles = screen.getAllByTestId('session-item').map((el) => el.textContent ?? '');
    expect(titles[0]).toContain('title c');
    expect(titles[1]).toContain('title a');
  });

  it('所有 For you 标签同一画法：品牌绿，没有橙色，没有悬停原因', () => {
    render(
      <TestRail
        state={railState(rows)}
        selectedId={null}
        onSelect={NOOP}
        forYou={fakeForYou({
          a: info({ words: 'Reply with one letter: A or B.' }),
          b: info({ words: 'Want me to log it?' }),
          c: info({ words: 'API Error: connection reset' }),
        })}
      />
    );
    const chips = screen.getAllByTestId('for-you-chip');
    expect(chips).toHaveLength(3);
    expect(new Set(chips.map((c) => c.className)).size).toBe(1);
    for (const c of chips) {
      expect(c.className).toContain('text-accent-primary');
      expect(c.className).not.toContain('warning');
      expect(c.getAttribute('title')).toBeNull();
      expect(c.hasAttribute('data-emphasis')).toBe(false);
    }
  });

  it('标题最多两行、悬停看全文；时长只写时长，悬停仍说停在几点', () => {
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} forYou={fakeForYou({ a: info() })} />);
    const item = screen.getAllByTestId('session-item').find((el) => el.getAttribute('data-for-you'))!;
    const title = item.querySelector('[data-testid=session-title]')!;
    expect(title.className).toContain('line-clamp-2');
    expect(title.className).toContain('font-semibold');
    expect(title.getAttribute('title')).toBe('title a');
    const age = item.querySelector('[data-testid=session-age]')!;
    expect(age.textContent).toBe('44 min');
    expect(age.getAttribute('title')).toMatch(/^Stopped at .* has been waiting for you since$/);
  });

  it('清单上没有 Set aside / dismiss 这类手动移出', () => {
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} forYou={fakeForYou({ a: info() })} />);
    fireEvent.click(screen.getAllByTestId('session-menu-button')[0]);
    const text = (document.body.textContent ?? '').toLowerCase();
    expect(text).not.toContain('set aside');
    expect(text).not.toContain('dismiss');
  });

  it('点开一张 For you 不撤它：没有调 suppress，它仍挂着', () => {
    const forYou = fakeForYou({ b: info() });
    const { rerender } = render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} forYou={forYou} />);
    fireEvent.click(screen.getAllByTestId('session-item')[0]);
    rerender(<TestRail state={railState(rows)} selectedId="b" onSelect={NOOP} forYou={forYou} />);
    expect(forYou.suppress).not.toHaveBeenCalled();
    const b = screen.getAllByTestId('session-item').find((el) => el.textContent?.includes('title b'))!;
    expect(b.getAttribute('data-for-you')).toBe('true');
  });

  it('档位只剩 For you / All，清单上搜不到状态词', () => {
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(screen.getByTestId('list-filter-for-you')).toBeTruthy();
    expect(screen.getByTestId('list-filter-all')).toBeTruthy();
    const text = document.body.textContent ?? '';
    for (const word of ['Done', 'Idle', 'Running', 'Working', 'Needs you']) {
      expect(text).not.toContain(word);
    }
  });

  it('时间后面不写 ago', () => {
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(document.body.textContent).not.toContain('ago');
  });

  it('本地刚发出的那一场挂 Sending', () => {
    render(<TestRail state={railState(rows)} selectedId="a" onSelect={NOOP} sendingId="a" />);
    const item = screen.getAllByTestId('session-item')[0];
    expect(item.textContent).toContain('Sending');
  });
});

describe('不瞬移：选中那张发出后原位不动，切走才归位', () => {
  const titles = () => screen.getAllByTestId('session-item').map((el) => el.querySelector('[data-testid=session-title]')?.textContent);

  it('发出之后留在 For you 那一格、状态行 Agent on it；切走后回到 Everything else', () => {
    const before = fakeForYou({ b: info() });
    const { rerender } = render(
      <TestRail state={railState(rows)} selectedId="b" onSelect={NOOP} forYou={before} />
    );
    expect(titles()).toEqual(['title b', 'title a', 'title c']);

    // 发出那一刻：这一场离开 For you（suppress 之后判定里没有它了），页面交出 holdId
    const after = fakeForYou({});
    rerender(
      <TestRail state={railState(rows)} selectedId="b" onSelect={NOOP} forYou={after} holdId="b" busyId="b" />
    );
    expect(titles()).toEqual(['title b', 'title a', 'title c']);
    expect(screen.getByTestId('for-you-header')).toBeTruthy();
    const b = screen.getAllByTestId('session-item')[0];
    expect(b.querySelector('[data-testid=agent-on-it-chip]')).toBeTruthy();
    expect(b.querySelector('[data-testid=for-you-chip]')).toBeNull();

    // 切到别的会话：放开，按时间回到 Everything else
    rerender(<TestRail state={railState(rows)} selectedId="a" onSelect={NOOP} forYou={after} holdId={null} />);
    expect(titles()).toEqual(['title a', 'title b', 'title c']);
    expect(screen.queryByTestId('for-you-header')).toBeNull();
  });

  it('发出时还在路上：状态行 Sending，不写时长', () => {
    render(<TestRail state={railState(rows)} selectedId="a" onSelect={NOOP} sendingId="a" busyId="a" />);
    const item = screen.getAllByTestId('session-item')[0];
    expect(item.querySelector('[data-testid=sending-chip]')).toBeTruthy();
    expect(item.querySelector('[data-testid=session-age]')).toBeNull();
  });
});

describe('原位保留的纯函数', () => {
  const [a, b, c, d] = ['a', 'b', 'c', 'd'].map((id) => session(id));
  const sections: RailSections = { pinned: [], 'for-you': [b, c], rest: [a, d] };

  it('slotOf 记下分区与序位；不在主干里返回 null', () => {
    expect(slotOf(sections, 'c')).toMatchObject({ section: 'for-you', index: 1 });
    expect(slotOf(sections, 'd')).toMatchObject({ section: 'rest', index: 1 });
    expect(slotOf(sections, 'zz')).toBeNull();
  });

  it('placeHeld 把它从新位置拿出来、摆回当时那一格，其余相对次序不变', () => {
    const held = slotOf(sections, 'c')!;
    const moved: RailSections = { pinned: [], 'for-you': [b], rest: [c, a, d] };
    const out = placeHeld(moved, held);
    expect(out['for-you'].map((s) => s.session_id)).toEqual(['b', 'c']);
    expect(out.rest.map((s) => s.session_id)).toEqual(['a', 'd']);
  });

  it('一时找不到它（比如筛在 For you 档）照当时那一份摆回去', () => {
    const held = slotOf(sections, 'b')!;
    const out = placeHeld({ pinned: [], 'for-you': [c], rest: [a, d] }, held);
    expect(out['for-you'].map((s) => s.session_id)).toEqual(['b', 'c']);
  });

  it('没有保留时原样返回', () => {
    expect(placeHeld(sections, null)).toBe(sections);
  });
});

describe('可关的终端', () => {
  const exited = {
    name: 'frago-agent-x',
    session_id: 'x',
    client_alive: false,
    awaiting_input: null,
    stop_reason: null,
    last_stop_at: new Date(NOW - 3_600_000).toISOString(),
    closing_text: '',
  };

  it('一个都没有时这一行不出现', () => {
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} />);
    expect(screen.queryByTestId('closable-terminals')).toBeNull();
  });

  it('有就报几个，点开默认全勾，按钮是中性的', () => {
    render(
      <TestRail
        state={railState(rows)}
        selectedId={null}
        onSelect={NOOP}
        forYou={fakeForYou({}, { closable: [exited] })}
      />
    );
    const line = screen.getByTestId('closable-terminals');
    expect(line.textContent).toContain('1 idle terminal can be closed');
    fireEvent.click(line.querySelector('button')!);
    expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(true);
    const close = screen.getByTestId('close-terminals');
    expect(close.textContent).toContain('Close 1 terminal');
    expect(close.className).not.toContain('bg-accent-primary');
  });
});

describe('另外两个标记', () => {
  it('开在 tmux 里的那一场，卡外面长一圈流光', () => {
    const { container } = render(
      <TestRail state={railState([session('a', { in_tmux: true }), session('b')])} selectedId={null} onSelect={NOOP} />
    );
    const framed = container.querySelectorAll('[data-live-edge="border"]');
    expect(framed).toHaveLength(1);
    expect(framed[0].textContent).toContain('title a');
  });

  it('点开一场会话就记一笔「看过了」', () => {
    const views = fakeViews();
    const onSelect = vi.fn();
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={onSelect} views={views} />);
    fireEvent.click(screen.getAllByTestId('session-item')[0]);
    expect(views.markViewed).toHaveBeenCalledWith('a');
    expect(onSelect).toHaveBeenCalledWith('a');
  });
});
