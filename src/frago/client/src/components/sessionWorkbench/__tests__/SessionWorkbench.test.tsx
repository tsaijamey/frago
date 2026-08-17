/**
 * 三栏的组件测试：左栏清单、中栏记录流、右栏示意面。
 *
 * 重点在四处：视觉归组但不露编号、空会话渲染成引导页而不是报错、左栏底部汇总只有绝对
 * 数、全域禁令在三栏都成立。
 */

import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import RecordStream, { groupRecords } from '../RecordStream';
import SessionRail from '../SessionRail';
import { relativeTime } from '../SessionItem';
import ReportPanel from '../ReportPanel';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import type { WorkbenchSession, WorkbenchSessionsState } from '@/hooks/useWorkbenchSessions';

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const GROUP = 'msg_0193abcdef0123456789abcdef012345';

function record(over: Partial<WorkbenchRecord> & Pick<WorkbenchRecord, 'id' | 'seq'>): WorkbenchRecord {
  return {
    session_id: SID,
    group_id: null,
    ts: 1_753_800_000_000,
    kind: 'agent.say',
    agent_path: [],
    payload: { text: '好的' },
    raw_available: true,
    ...over,
  };
}

const NOOP = () => {};

// 新建会话的弹窗一打开就去问系统有哪些目录。测试里给它一份定值，免得跑去碰真的网络，
// 那会让状态在断言之后才落下来，报成 act 警告。
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getSystemDirectories: async () => ({ home: '/Users/frago', cwd: '/Users/frago/Repos/frago' }),
}));

describe('groupRecords 视觉归组', () => {
  it('相邻且同一次回复的并成一段，用户输入各自独立', () => {
    const groups = groupRecords([
      record({ id: 'a', seq: 0, kind: 'user.say', payload: { text: '开工' } }),
      record({ id: 'b', seq: 1, group_id: GROUP, kind: 'agent.think' }),
      record({ id: 'c', seq: 2, group_id: GROUP, kind: 'agent.say' }),
      record({ id: 'd', seq: 3, group_id: 'msg_two', kind: 'agent.say' }),
    ]);
    expect(groups.map((g) => g.records.length)).toEqual([1, 2, 1]);
  });

  it('不跨段回收——中间隔了别的分组就不再并回去', () => {
    const groups = groupRecords([
      record({ id: 'a', seq: 0, group_id: GROUP }),
      record({ id: 'b', seq: 1, group_id: 'msg_two' }),
      record({ id: 'c', seq: 2, group_id: GROUP }),
    ]);
    expect(groups).toHaveLength(3);
  });
});

describe('RecordStream 中栏', () => {
  const twoInAGroup = [
    record({ id: 'b', seq: 1, group_id: GROUP, kind: 'agent.think', payload: { text: '想想' } }),
    record({
      id: 'c',
      seq: 2,
      group_id: GROUP,
      kind: 'agent.say',
      payload: { text: '做完了', model: 'claude-opus-5' },
    }),
  ];

  function streamProps(over: Partial<Parameters<typeof RecordStream>[0]> = {}) {
    return {
      sessionId: SID,
      records: twoInAGroup,
      loading: false,
      loadingOlder: false,
      hasOlder: false,
      error: null,
      onLoadOlder: NOOP,
      ...over,
    };
  }

  /** jsdom 没有布局，滚动几何得手摆。 */
  function setGeometry(scroller: Element, height: number, client: number) {
    Object.defineProperty(scroller, 'scrollHeight', { value: height, configurable: true });
    Object.defineProperty(scroller, 'clientHeight', { value: client, configurable: true });
  }

  it('同一次回复包进一个容器，容器头写模型名与本组条数，编号不露', () => {
    const { container } = render(<RecordStream {...streamProps()} />);
    expect(screen.getAllByTestId('record-group')).toHaveLength(1);
    expect(screen.getByText('本组 2 条')).toBeTruthy();
    // 模型名在容器头与那条回复上各出现一次，这里只确认它露了脸。
    expect(screen.getAllByText('claude-opus-5').length).toBeGreaterThan(0);
    expect(container.textContent ?? '').not.toContain(GROUP);
  });

  it('一条会话都没选时给引导，不报错', () => {
    render(<RecordStream {...streamProps({ sessionId: null, records: [] })} />);
    expect(screen.getByText(/从左边挑一场会话/)).toBeTruthy();
  });

  it('空壳会话渲染成引导页而不是报错', () => {
    render(<RecordStream {...streamProps({ records: [] })} />);
    expect(screen.getByText(/一条记录都没留下/)).toBeTruthy();
    expect(screen.getByText(/不是坏了/)).toBeTruthy();
  });

  it('打开会话落在最新内容上，而不是开头', () => {
    const { rerender } = render(<RecordStream {...streamProps({ records: [], loading: true })} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    setGeometry(scroller, 2000, 800);
    rerender(<RecordStream {...streamProps()} />);
    expect(scroller.scrollTop).toBe(2000);
  });

  it('翻到顶才要更早的一页，没到顶不要', () => {
    const onLoadOlder = vi.fn();
    render(<RecordStream {...streamProps({ hasOlder: true, onLoadOlder })} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    setGeometry(scroller, 2000, 800);

    scroller.scrollTop = 600;
    fireEvent.scroll(scroller);
    expect(onLoadOlder).not.toHaveBeenCalled();

    scroller.scrollTop = 100;
    fireEvent.scroll(scroller);
    expect(onLoadOlder).toHaveBeenCalledTimes(1);
  });

  it('前插旧页后视口钉在原来那张卡，不跳', () => {
    const onLoadOlder = vi.fn();
    const { rerender } = render(<RecordStream {...streamProps({ hasOlder: true, onLoadOlder })} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    setGeometry(scroller, 2000, 800);

    // 人翻到顶附近，触发前插；此刻的几何被记下。
    scroller.scrollTop = 100;
    fireEvent.scroll(scroller);
    expect(onLoadOlder).toHaveBeenCalledTimes(1);

    // 旧页插进来，内容长高了一千。视口该钉在原来那张卡上：100 + (3000 - 2000)。
    const older = record({ id: 'a', seq: 0, kind: 'user.say', payload: { text: '更早的' } });
    setGeometry(scroller, 3000, 800);
    rerender(<RecordStream {...streamProps({ records: [older, ...twoInAGroup], hasOlder: true, onLoadOlder })} />);
    expect(scroller.scrollTop).toBe(1100);
  });

  it('人手动离开底部后，新条目进来不再把视口拽到底', () => {
    const { rerender } = render(<RecordStream {...streamProps()} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    setGeometry(scroller, 2000, 800);

    // 人手动往上翻：先滚轮（滚动意图），位置离开底部。
    fireEvent.wheel(scroller);
    scroller.scrollTop = 1000;
    fireEvent.scroll(scroller);

    // 新条目进来，内容长高了，视口不许动。
    setGeometry(scroller, 2600, 800);
    const appended = record({ id: 'd', seq: 3, kind: 'agent.say', payload: { text: '新的' } });
    rerender(<RecordStream {...streamProps({ records: [...twoInAGroup, appended] })} />);
    expect(scroller.scrollTop).toBe(1000);
  });

  it('人手动回到底部，新条目进来立刻又跟到底', () => {
    const { rerender } = render(<RecordStream {...streamProps()} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    setGeometry(scroller, 2000, 800);

    fireEvent.wheel(scroller);
    scroller.scrollTop = 1000;
    fireEvent.scroll(scroller);

    // 回到底部：距底 0，自动滚动立即复活。
    fireEvent.wheel(scroller);
    scroller.scrollTop = 1200;
    fireEvent.scroll(scroller);

    setGeometry(scroller, 2600, 800);
    const appended = record({ id: 'd', seq: 3, kind: 'agent.say', payload: { text: '新的' } });
    rerender(<RecordStream {...streamProps({ records: [...twoInAGroup, appended] })} />);
    expect(scroller.scrollTop).toBe(2600);
  });

  it('解除后十秒没再手动滚动，新条目进来自动滚动复活', () => {
    vi.useFakeTimers();
    try {
      const { rerender } = render(<RecordStream {...streamProps()} />);
      const scroller = screen.getByTestId('record-stream-scroll');
      setGeometry(scroller, 2000, 800);

      fireEvent.wheel(scroller);
      scroller.scrollTop = 1000;
      fireEvent.scroll(scroller);

      // 十一秒没再碰，新条目进来时自动滚动复活。
      vi.setSystemTime(Date.now() + 11_000);
      setGeometry(scroller, 2600, 800);
      const appended = record({ id: 'd', seq: 3, kind: 'agent.say', payload: { text: '新的' } });
      rerender(<RecordStream {...streamProps({ records: [...twoInAGroup, appended] })} />);
      expect(scroller.scrollTop).toBe(2600);
    } finally {
      vi.useRealTimers();
    }
  });

  it('到顶了只说这是开头，报已经拿到的绝对条数，没有分母', () => {
    const { container } = render(<RecordStream {...streamProps()} />);
    expect(screen.getByText(/这是这场会话的开头，共 2 条记录/)).toBeTruthy();
    const text = container.textContent ?? '';
    expect(text.match(/\d+\s*%/g)).toBeNull();
    expect(text.match(/\d+\s*\/\s*\d+/g)).toBeNull();
  });

  it('前插旧页时在顶部说一声，不把整栏打回装载态', () => {
    render(<RecordStream {...streamProps({ loadingOlder: true, hasOlder: true })} />);
    expect(screen.getByText(/取更早的记录/)).toBeTruthy();
    // 已有的记录还在，没有被装载态盖掉。
    expect(screen.getByText('做完了')).toBeTruthy();
  });

  describe('镜头', () => {
    const mixed = [
      record({ id: 'u', seq: 0, kind: 'user.say', payload: { text: '开工' } }),
      record({ id: 'a', seq: 1, kind: 'agent.say', payload: { text: '好的' } }),
      record({
        id: 'h',
        seq: 2,
        kind: 'context.inject',
        payload: { source: 'hook', hook_event: 'PreToolUse', blocks: ['先查现成落点'] },
      }),
      record({
        id: 't',
        seq: 3,
        kind: 'tool.call',
        payload: { tool_name: 'Bash', tool_family: 'shell', args: {} },
      }),
      record({ id: 'e', seq: 4, kind: 'call.envelope', payload: { duration_ms: 100 } }),
    ];

    it('每一档带真实条数——筛掉的东西必须在条数上看得见', () => {
      render(<RecordStream {...streamProps({ records: mixed })} />);
      expect(screen.getByTestId('lens-all').textContent).toContain('5');
      expect(screen.getByTestId('lens-talk').textContent).toContain('2');
      expect(screen.getByTestId('lens-hook').textContent).toContain('1');
      expect(screen.getByTestId('lens-tool').textContent).toContain('1');
      expect(screen.getByTestId('lens-system').textContent).toContain('1');
    });

    it('挑一档就只剩那一档', () => {
      render(<RecordStream {...streamProps({ records: mixed })} />);
      fireEvent.click(screen.getByTestId('lens-hook'));
      expect(screen.getByTestId('hook-inject')).toBeTruthy();
      expect(screen.queryByText('开工')).toBeNull();
      expect(screen.queryByText('好的')).toBeNull();
    });

    it('一条记录都没有时不摆镜头——没有可挑的', () => {
      render(<RecordStream {...streamProps({ records: [] })} />);
      expect(screen.queryByTestId('stream-lens')).toBeNull();
    });
  });
});

// ── 左栏 ──────────────────────────────────────────────────────────────
function session(over: Partial<WorkbenchSession> & Pick<WorkbenchSession, 'session_id'>): WorkbenchSession {
  return {
    family: 'claude-code',
    title: '会话工作台 webUI',
    directory: '/Users/frago/Repos/frago',
    created_at: 1_753_700_000_000,
    last_active_at: 1_753_800_000_000,
    last_reply_at: null,
    agent_paths: [],
    status: 'done',
    digest_done: null,
    digest_stuck: null,
    ...over,
  };
}

function railState(over: Partial<WorkbenchSessionsState> = {}): WorkbenchSessionsState {
  const sessions = [
    session({ session_id: SID }),
    session({
      session_id: 'ses_058288655ffeYMxYC1AZKCcv56',
      family: 'opencode',
      title: '另一家',
      status: 'idle',
    }),
  ];
  return {
    sessions,
    visible: sessions,
    loading: false,
    error: null,
    search: '',
    setSearch: NOOP,
    status: 'all',
    setStatus: NOOP,
    days: 0,
    setDays: NOOP,
    counts: { all: 2, running: 0, error: 0, done: 1, idle: 1 },
    content: { query: '', matches: new Map(), searching: false, warnings: [], error: null },
    reload: async () => {},
    ...over,
  };
}

describe('SessionRail 左栏', () => {
  it('两家的会话都列出来，各自标出来源', () => {
    render(<SessionRail state={railState()} selectedId={null} onSelect={NOOP} />);
    expect(screen.getAllByTestId('session-item')).toHaveLength(2);
    // 来源不再是筛选维度，所以每家只在自己那张卡上露一次脸。
    expect(screen.getAllByText('Claude Code')).toHaveLength(1);
    expect(screen.getAllByText('opencode')).toHaveLength(1);
  });

  it('底部汇总只有已经发生的绝对数', () => {
    const { container } = render(
      <SessionRail state={railState()} selectedId={null} onSelect={NOOP} />
    );
    expect(screen.getByText(/共 2 场/)).toBeTruthy();
    const text = container.textContent ?? '';
    expect(text.match(/\d+\s*%/g)).toBeNull();
    expect(text.match(/\d+\s*\/\s*\d+/g)).toBeNull();
    expect(container.querySelectorAll('progress, [role="progressbar"]')).toHaveLength(0);
  });

  it('点一场会话把编号交出去', () => {
    const onSelect = vi.fn();
    render(<SessionRail state={railState()} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getAllByTestId('session-item')[0]);
    expect(onSelect).toHaveBeenCalledWith(SID);
  });

  it('选中的那张卡整卡换状态，不靠单边竖条', () => {
    render(<SessionRail state={railState()} selectedId={SID} onSelect={NOOP} />);
    const [first] = screen.getAllByTestId('session-item');
    expect(first.getAttribute('aria-current')).toBe('true');
    const className = first.className;
    expect(className).toContain('ring-');
    expect(className).not.toMatch(/border-[lrtb]-\d/);
  });

  it('一场都没匹配上时说清楚，不当成坏了', () => {
    render(
      <SessionRail
        state={railState({
          visible: [],
          counts: { all: 0, running: 0, error: 0, done: 0, idle: 0 },
        })}
        selectedId={null}
        onSelect={NOOP}
      />
    );
    expect(screen.getByText('没有匹配的会话')).toBeTruthy();
  });

  it('筛选是四档状态加全部，来源不再当筛选维度', () => {
    render(<SessionRail state={railState()} selectedId={null} onSelect={NOOP} />);
    for (const id of ['all', 'running', 'error', 'done', 'idle']) {
      expect(screen.getByTestId(`status-filter-${id}`)).toBeTruthy();
    }
    // 来源仍在卡片上看得见，但没有一个按来源筛的按钮。
    expect(screen.queryByTestId('status-filter-claude-code')).toBeNull();
    expect(screen.getAllByText('Claude Code').length).toBeGreaterThanOrEqual(1);
  });

  it('每一档带真实条数，不是摆设', () => {
    render(
      <SessionRail
        state={railState({ counts: { all: 12, running: 1, error: 3, done: 6, idle: 2 } })}
        selectedId={null}
        onSelect={NOOP}
      />
    );
    expect(screen.getByTestId('status-filter-error').textContent).toContain('3');
    expect(screen.getByTestId('status-filter-done').textContent).toContain('6');
    expect(screen.getByTestId('status-filter-all').textContent).toContain('12');
  });

  it('点某一档把它交出去', () => {
    const setStatus = vi.fn();
    render(<SessionRail state={railState({ setStatus })} selectedId={null} onSelect={NOOP} />);
    fireEvent.click(screen.getByTestId('status-filter-error'));
    expect(setStatus).toHaveBeenCalledWith('error');
  });

  it('会话卡带状态与两格摘要', () => {
    const one = session({
      session_id: SID,
      status: 'error',
      digest_done: '把镜头判断追加进了 verdict.jsonl',
      digest_stuck: 'API Error: 连接中断',
    });
    render(
      <SessionRail
        state={railState({ sessions: [one], visible: [one] })}
        selectedId={null}
        onSelect={NOOP}
      />
    );
    expect(screen.getAllByTestId('session-item')[0].getAttribute('data-status')).toBe('error');
    expect(screen.getByTestId('digest-done').textContent).toContain('verdict.jsonl');
    expect(screen.getByTestId('digest-stuck').textContent).toContain('连接中断');
  });

  it('内容命中时把命中的原话摆到卡上，并顶掉「已完成」那一格', () => {
    const one = session({ session_id: SID, digest_done: '把镜头判断追加进了 verdict.jsonl' });
    render(
      <SessionRail
        state={railState({
          sessions: [one],
          visible: [one],
          search: '飞书',
          content: {
            query: '飞书',
            searching: false,
            warnings: [],
            error: null,
            matches: new Map([
              [
                SID,
                {
                  session_id: SID,
                  family: 'claude-code' as const,
                  hit_count: 3,
                  capped: false,
                  hits: [
                    {
                      record_id: 'r1',
                      kind: 'user.say' as const,
                      ts: 1,
                      snippet: '…把飞书那条推送修一下…',
                    },
                  ],
                },
              ],
            ]),
          },
        })}
        selectedId={null}
        onSelect={NOOP}
      />
    );
    expect(screen.getByTestId('content-hits').textContent).toContain('把飞书那条推送修一下');
    expect(screen.getByTestId('content-hits').textContent).toContain('这场还有 2 处');
    expect(screen.queryByTestId('digest-done')).toBeNull();
  });

  it('内容检索慢一拍，所以它自己报进度，也报哪里没搜全', () => {
    const { rerender } = render(
      <SessionRail
        state={railState({
          search: '飞书',
          content: {
            query: '',
            searching: true,
            warnings: [],
            error: null,
            matches: new Map(),
          },
        })}
        selectedId={null}
        onSelect={NOOP}
      />
    );
    expect(screen.getByTestId('content-search-status').textContent).toContain('正在会话内容里找');

    rerender(
      <SessionRail
        state={railState({
          search: '飞书',
          content: {
            query: '飞书',
            searching: false,
            warnings: ['ripgrep 不在 PATH 上'],
            error: null,
            matches: new Map(),
          },
        })}
        selectedId={null}
        onSelect={NOOP}
      />
    );
    expect(screen.getByTestId('content-search-status').textContent).toContain('命中 0 场');
    expect(screen.getByText('ripgrep 不在 PATH 上')).toBeTruthy();
  });

  it('摘要取不到时整行不出现，不留一句占位的话', () => {
    render(<SessionRail state={railState()} selectedId={null} onSelect={NOOP} />);
    expect(screen.queryByTestId('digest-done')).toBeNull();
    expect(screen.queryByTestId('digest-stuck')).toBeNull();
  });

  it('没有等你决策那一档', () => {
    const { container } = render(
      <SessionRail state={railState()} selectedId={null} onSelect={NOOP} />
    );
    const text = container.textContent ?? '';
    expect(text).not.toContain('等你');
    expect(text).not.toContain('待决策');
    expect(screen.queryByTestId('status-filter-waiting')).toBeNull();
  });

  it('搜索框能改词，也能一键清空', () => {
    const setSearch = vi.fn();
    render(
      <SessionRail state={railState({ search: '镜头', setSearch })} selectedId={null} onSelect={NOOP} />
    );
    fireEvent.change(screen.getByLabelText('搜会话'), { target: { value: '旁白' } });
    expect(setSearch).toHaveBeenCalledWith('旁白');
    fireEvent.click(screen.getByLabelText('清空搜索'));
    expect(setSearch).toHaveBeenCalledWith('');
  });

  it('时间范围四档与不限并排，且与状态筛选各管各的', () => {
    const setDays = vi.fn();
    render(<SessionRail state={railState({ setDays })} selectedId={null} onSelect={NOOP} />);
    for (const d of [0, 1, 7, 14, 30]) {
      expect(screen.getByTestId(`day-filter-${d}`)).toBeTruthy();
    }
    // 默认不限：一千多场会话不该被一个默认值挡在外面。
    expect(screen.getByTestId('day-filter-0').getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByTestId('day-filter-7'));
    expect(setDays).toHaveBeenCalledWith(7);
    // 点时间范围不动状态那一维。
    expect(screen.getByTestId('status-filter-all').getAttribute('aria-pressed')).toBe('true');
  });

  it('新建会话的入口在左栏顶部，点开是弹窗不是跳页', async () => {
    render(<SessionRail state={railState()} selectedId={null} onSelect={NOOP} />);
    expect(screen.queryByText('起始目录')).toBeNull();
    await act(async () => {
      fireEvent.click(screen.getByTestId('new-session'));
    });
    expect(screen.getByText('起始目录')).toBeTruthy();
    expect(screen.getByText('第一句话')).toBeTruthy();
  });

  it('每张卡都能复制恢复命令，两家各按自己的形状', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<SessionRail state={railState()} selectedId={null} onSelect={NOOP} />);
    const [cc, oc] = screen.getAllByTestId('copy-resume');
    await act(async () => {
      fireEvent.click(cc);
    });
    expect(writeText).toHaveBeenCalledWith(`claude --resume ${SID}`);
    await act(async () => {
      fireEvent.click(oc);
    });
    expect(writeText).toHaveBeenCalledWith('opencode -s ses_058288655ffeYMxYC1AZKCcv56');
  });

  it('点复制不会顺带把这场会话选中', async () => {
    const onSelect = vi.fn();
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
      configurable: true,
    });
    render(<SessionRail state={railState()} selectedId={null} onSelect={onSelect} />);
    await act(async () => {
      fireEvent.click(screen.getAllByTestId('copy-resume')[0]);
    });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('相对时刻只说已经过去了多久', () => {
    const now = 1_753_800_000_000;
    expect(relativeTime(now - 30_000, now)).toBe('刚刚');
    expect(relativeTime(now - 12 * 60_000, now)).toBe('12 分钟前');
    expect(relativeTime(now - 3 * 3_600_000, now)).toBe('3 小时前');
    expect(relativeTime(0, now)).toBe('');
  });
});

describe('ReportPanel 右栏', () => {
  it('明写速记员尚未接入', () => {
    render(<ReportPanel />);
    expect(screen.getByText(/速记员尚未接入/)).toBeTruthy();
  });

  it('增长型槽位的展开按钮写绝对条数，不写比值', () => {
    const { container } = render(<ReportPanel />);
    const more = screen.getByText(/展开更早的 \d+ 条/);
    expect(more).toBeTruthy();
    fireEvent.click(more);
    expect(screen.queryByText(/展开更早的/)).toBeNull();
    const text = container.textContent ?? '';
    expect(text.match(/\d+\s*%/g)).toBeNull();
    expect(text.match(/\d+\s*\/\s*\d+/g)).toBeNull();
    expect(container.querySelectorAll('progress, [role="progressbar"]')).toHaveLength(0);
  });
});
