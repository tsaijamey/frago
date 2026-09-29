/**
 * 左栏只留一个标记「For you」之后的用例。
 *
 * 盯的是摆放与字样：For you 的两行、其余一行；分区顺序 Pinned → For you → Everything
 * else；档位只剩 For you / All；状态词一个都不出现；可关终端那一行；开在 tmux 里的流光
 * 照旧（主人 09-24 定）；点开记一笔看过了。挂不挂的判据由 `useForYou.test.ts` 把关，
 * 这里直接给定判定结果。
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { TestRail, fakeForYou, fakeViews } from './railTestKit';
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
  return { emphasis: null, waitingSince: NOW - 44 * 60_000, words: 'Want me to log it?', unseen: false, ...over };
}

const rows = [session('a'), session('b'), session('c')];

beforeEach(() => {
  pins.pinned = [];
  pins.collapsed = false;
});

describe('For you 在清单上', () => {
  it('挂着的两行：标签加收尾原话；其余只剩一行', () => {
    render(<TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} forYou={fakeForYou({ b: info() })} />);
    const items = screen.getAllByTestId('session-item');
    const waiting = items.find((el) => el.getAttribute('data-for-you') === 'true')!;
    expect(waiting.textContent).toContain('For you');
    expect(waiting.textContent).toContain('Want me to log it?');
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

  it('加重的换告警橙，悬停说明原因；中性的没有颜色', () => {
    render(
      <TestRail
        state={railState(rows)}
        selectedId={null}
        onSelect={NOOP}
        forYou={fakeForYou({ a: info({ emphasis: 'pick-one' }), b: info() })}
      />
    );
    const chips = screen.getAllByTestId('for-you-chip');
    const loud = chips.find((c) => c.getAttribute('data-emphasis') === 'pick-one')!;
    expect(loud.className).toContain('accent-warning');
    expect(loud.getAttribute('title')).toBe('It wants you to pick one');
    const quiet = chips.find((c) => c.getAttribute('data-emphasis') === 'none')!;
    expect(quiet.className).not.toContain('accent');
  });

  it('停下之后没点开过的，标题加粗', () => {
    render(
      <TestRail state={railState(rows)} selectedId={null} onSelect={NOOP} forYou={fakeForYou({ a: info({ unseen: true }) })} />
    );
    const item = screen.getAllByTestId('session-item').find((el) => el.getAttribute('data-for-you'))!;
    expect(item.querySelector('.font-semibold')).toBeTruthy();
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
