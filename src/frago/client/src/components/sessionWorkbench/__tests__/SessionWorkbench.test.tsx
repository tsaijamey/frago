/** * 三栏的组件测试：左栏清单、中栏记录流、右栏示意面。
 *
 * 重点在四处：视觉归组但不露编号、空会话渲染成引导页而不是报错、左栏底部汇总只有绝对
 * 数、全域禁令在三栏都成立。
 */

import { beforeAll, describe, expect, it, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import RecordStream, {
  buildTalkSegments,
  groupRecords,
  lensOf,
  talkView,
  withTurnDecisionCards,
} from '../RecordStream';
import { DecisionCardContext } from '../DecisionCard';
import { TestRail } from './railTestKit';
import { relativeTime, shortAge } from '../SessionItem';
import { ReportBody } from '../ReportPanel';
import { parseAnsiSegments } from '../SessionTerminal';
import type { ObserverState, SessionObserverView } from '@/hooks/useSessionObserver';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import type { WorkbenchSession, WorkbenchSessionsState } from '@/hooks/useWorkbenchSessions';
import i18n from '@/i18n';
import { useUIStore } from '@/stores/appStore';

/**
 * 界面上的字全部走词表了，用例断言的是中文那一份，所以先把语言切到中文。
 *
 * 这一句顺带把另一件事也核了：`zh.json` 里的字必须与从前写死在组件里的逐字相同，
 * 差一个标点，下面这些断言就红。
 */
beforeAll(async () => {
  await i18n.changeLanguage('zh');
});


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

describe('lensOf 镜头归属', () => {
  it('后台任务通知归对话：agent 读到它才转向，筛掉了对话里就只剩没头没尾的转向', () => {
    const r = record({
      id: 'n',
      seq: 0,
      kind: 'context.inject',
      payload: { channel: 'task-notification', source: 'task-notification', body: 'x' },
    });
    expect(lensOf(r)).toBe('talk');
  });
});

describe('插话队列的入队行', () => {
  const enqueue = (id: string, seq: number, content: string) =>
    record({
      id,
      seq,
      kind: 'session.state',
      payload: {
        field: 'queue-operation',
        pointer: true,
        to: `enqueue ${content}`,
        operation: 'enqueue',
        content,
      },
    });
  const streamProps = (records: WorkbenchRecord[]) => ({
    sessionId: SID,
    records,
    loading: false,
    loadingOlder: false,
    hasOlder: false,
    error: null,
    onLoadOlder: NOOP,
  });

  it('还在排的那句在「对话」档摆出原文与下场；「全部」档同样摆', () => {
    const records = [
      record({ id: 'u', seq: 0, kind: 'user.say', payload: { text: '开工' } }),
      enqueue('q', 1, '本机需要管理什么state？'),
    ];
    render(<RecordStream {...streamProps(records)} />);
    expect(screen.getByTestId('lens-talk').textContent).toContain('2');
    expect(screen.getByText('本机需要管理什么state？')).toBeTruthy();
    expect(screen.getByText(i18n.t('workbench.record.queueState.pending'))).toBeTruthy();

    fireEvent.click(screen.getByTestId('lens-all'));
    expect(screen.getByText('本机需要管理什么state？')).toBeTruthy();
  });

  it('出队之后退出「对话」档——那一轮的「你说」接着站，同一句话不摆两遍', () => {
    const records = [
      enqueue('q', 0, '插一句'),
      record({
        id: 'd',
        seq: 1,
        kind: 'session.state',
        payload: { field: 'queue-operation', pointer: true, to: 'dequeue', operation: 'dequeue', content: '' },
      }),
      record({ id: 'u', seq: 2, kind: 'user.say', payload: { text: '插一句' } }),
    ];
    render(<RecordStream {...streamProps(records)} />);
    expect(screen.getByTestId('lens-talk').textContent).toContain('1');

    // 「全部」档里连续的系统记录压成一行，点开才摊回原卡
    fireEvent.click(screen.getByTestId('lens-all'));
    fireEvent.click(screen.getByTestId('system-run').querySelector('button')!);
    expect(screen.getByText(i18n.t('workbench.record.queueState.submitted'))).toBeTruthy();
  });

  it('后台任务通知也走这条队列，它不是人说的话，不进对话', () => {
    const r = record({
      ...enqueue('n', 0, '<task-notification>x</task-notification>'),
    });
    expect(lensOf({ ...r, payload: { ...r.payload, queue_state: 'pending' } })).toBe('system');
  });
});

describe('talkView 对话档捎带用量', () => {
  it('两段对话之间只留最后一条用量，工具不进来', () => {
    const tick = (id: string, seq: number) =>
      record({ id, seq, kind: 'usage.tick', payload: { context_tokens: seq, total_tokens: seq } });
    const view = talkView([
      record({ id: 'u', seq: 0, kind: 'user.say', payload: { text: '开工' } }),
      tick('t1', 1),
      record({ id: 'c', seq: 2, kind: 'tool.call', payload: { tool_name: 'Bash' } }),
      tick('t2', 3),
      record({ id: 'a', seq: 4, kind: 'agent.say', payload: { text: '好了' } }),
      tick('t3', 5),
    ]);
    expect(view.map((r) => r.id)).toEqual(['u', 't2', 'a', 't3']);
  });

  it('用量仍归系统档，条数不重复计', () => {
    expect(lensOf(record({ id: 't', seq: 0, kind: 'usage.tick', payload: {} }))).toBe('system');
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

  it('同一次回复收进一个容器，容器里没有头，分组编号不露', () => {
    const { container } = render(<RecordStream {...streamProps()} />);
    // 归组只剩间距：同一次回复的几条包在一个容器里，头上不再写模型名与条数，编号一个字不露。
    expect(screen.getAllByTestId('record-group')).toHaveLength(1);
    expect(screen.queryByText(/本组 2 条/)).toBeNull();
    expect(screen.queryByText(/同一次回复/)).toBeNull();
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

    it('打开就落在对话那一档，工具与记账不铺开', () => {
      render(<RecordStream {...streamProps({ records: mixed })} />);
      expect(screen.getByText('开工')).toBeTruthy();
      expect(screen.getByText('好的')).toBeTruthy();
      expect(screen.queryByTestId('hook-inject')).toBeNull();
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

    it('模型与用量读数常驻在档位条右侧，支持窄屏折行与超长省略', () => {
      const { rerender } = render(
        <RecordStream
          {...streamProps({
            records: mixed,
            usage: { model: 'gemini-4-argon-medium', context: 15_200, total: 28_400 },
          })}
        />
      );
      const lensBar = screen.getByTestId('stream-lens');
      expect(lensBar.className).toContain('flex-wrap');
      expect(lensBar.className).toContain('justify-between');

      const usage = screen.getByTestId('stream-lens-usage');
      expect(lensBar.contains(usage)).toBe(true);
      expect(usage.textContent).toBe('gemini-4-argon-medium · 上下文 15k · 累计 28k');
      expect(usage.className).toContain('truncate');

      rerender(
        <RecordStream
          {...streamProps({
            records: mixed,
            usage: { model: 'claude-opus-5', context: 166_518, total: 5_022_011 },
          })}
        />
      );
      expect(screen.getByTestId('stream-lens-usage').textContent).toBe(
        'claude-opus-5 · 上下文 167k · 累计 5.0M'
      );
    });

    it('档位条左侧依次紧贴展示 Watcher 菜单、隔离纯文本 Executor 与现有 All | Talk 等菜单', () => {
      render(<RecordStream {...streamProps({ records: mixed })} />);
      const watcherBtn = screen.getByTestId('lens-watcher');
      const executorLabel = screen.getByTestId('lens-executor-label');
      const allBtn = screen.getByTestId('lens-all');
      expect(watcherBtn.textContent).toContain('Watcher');
      expect(executorLabel.textContent).toBe('Executor');
      expect(allBtn.textContent).toContain('全部');
    });

    it('Talk 视图将每个回复前的多次工具调用与 thinking 叠加为单行自增计数，不刷多行', () => {
      const turnWithMultiToolsAndThinks = [
        record({ id: 'u1', seq: 0, kind: 'user.say', payload: { text: '排查问题' } }),
        record({ id: 'th1', seq: 1, kind: 'agent.think', payload: { text: '第一轮思考' } }),
        record({ id: 'tc1', seq: 2, kind: 'tool.call', payload: { tool_name: 'Read', args: {} } }),
        record({ id: 'tr1', seq: 3, kind: 'tool.result', payload: { tool_name: 'Read', status: 'ok', body: 'ok' } }),
        record({ id: 'th2', seq: 4, kind: 'agent.think', payload: { text: '第二轮思考' } }),
        record({ id: 'tc2', seq: 5, kind: 'tool.call', payload: { tool_name: 'Grep', args: {} } }),
        record({ id: 'tc3', seq: 6, kind: 'tool.call', payload: { tool_name: 'Bash', args: {} } }),
        record({ id: 'th3', seq: 7, kind: 'agent.think', payload: { text: '第三轮思考' } }),
        record({ id: 'th4', seq: 8, kind: 'agent.think', payload: { text: '第四轮思考' } }),
        record({ id: 'th5', seq: 9, kind: 'agent.think', payload: { text: '第五轮思考' } }),
        record({ id: 'a1', seq: 10, kind: 'agent.say', payload: { text: '已定位根因。' } }),
      ];

      const segs = buildTalkSegments(turnWithMultiToolsAndThinks);
      const aggSegs = segs.filter((s) => s.kind === 'talk-agg');
      expect(aggSegs).toHaveLength(1);
      if (aggSegs[0].kind === 'talk-agg') {
        expect(aggSegs[0].toolCalls).toBe(3);
        expect(aggSegs[0].thinkingSteps).toBe(5);
      }

      render(<RecordStream {...streamProps({ records: turnWithMultiToolsAndThinks })} />);
      const aggRows = screen.getAllByTestId('talk-pre-response-agg');
      expect(aggRows).toHaveLength(1);
      expect(aggRows[0].textContent).toContain('3次工具调用');
      expect(aggRows[0].textContent).toContain('5次thinking');
    });

    it('Watcher 视图对每个游标切片外部上方展示观察者总结，下方包裹默认折叠的 Talk 并原样展示可交互决策卡', () => {
      const uiCardJson = JSON.stringify({
        frago_ui_component: 'decision-card',
        component_type: 'single-choice',
        data: {
          type: 'single-choice',
          question: 'Observer 信息结构采用哪种组织方式？',
          options: [
            {
              key: 'A',
              label: '三段式（执行动作 + 背景上下文 + 决策选项）',
              effect: '直接服务于用户拍板',
              recommended: true,
              reversible: true,
            },
            {
              key: 'B',
              label: '双段式（当前进展 + 待决问题）',
              effect: '极简展示',
              recommended: false,
              reversible: true,
            },
          ],
        },
      });
      const recordsWithCard = [
        record({ id: 'u1', seq: 0, kind: 'user.say', payload: { text: '梳理信息结构' } }),
        record({ id: 'tc1', seq: 1, kind: 'tool.call', payload: { tool_name: 'Read', args: {} } }),
        record({ id: 'tr1', seq: 2, kind: 'tool.result', payload: { tool_name: 'Bash', status: 'ok', body: uiCardJson } }),
        record({ id: 'a1', seq: 3, kind: 'agent.say', payload: { text: '请选择信息结构方案。' } }),
      ];
      const observerView: SessionObserverView = {
        state: {
          bound: true,
          anchor: '梳理信息结构',
          tail: { kind: 'output', text: '已完成代码改造，等待选择信息结构' },
          decision: 'Observer 信息结构采用哪种组织方式？',
          happened: ['完成了 Watcher 与 Talk 改造'],
          updated_at: 1_753_800_005_000,
          model: 'deepseek-v4-flash',
          status: 'ok',
          status_detail: null,
          runs: [
            {
              id: 'run-1',
              at: 1_753_800_005_000,
              cursor_from: 0,
              cursor_to: 4,
              tail: { kind: 'output', text: '已完成代码改造，等待选择信息结构' },
              happened_add: ['完成了 Watcher 与 Talk 改造'],
              decision: 'Observer 信息结构采用哪种组织方式？',
              summary: '完成了 Watcher 与 Talk 改造\n已完成代码改造，等待选择信息结构',
            },
          ],
        },
        loading: false,
        error: null,
      };
      const answer = vi.fn();

      render(
        <DecisionCardContext.Provider
          value={{
            canAnswer: true,
            blockedReason: null,
            answerOf: () => null,
            answer,
          }}
        >
          <RecordStream {...streamProps({ records: recordsWithCard, observer: observerView })} />
        </DecisionCardContext.Provider>
      );

      fireEvent.click(screen.getByTestId('lens-watcher'));
      expect(screen.getByTestId('watcher-view')).toBeTruthy();
      expect(screen.getByTestId('watcher-phase-goal-label').textContent).toBe('阶段目标');
      expect(screen.getByTestId('watcher-phase-goal').textContent).toContain('梳理信息结构');
      expect(screen.getByTestId('watcher-summary').textContent).toContain('完成了 Watcher 与 Talk 改造');
      expect(screen.getByTestId('watcher-summary').textContent).not.toContain('。；');
      expect(screen.getByTestId('watcher-part-doing-label').textContent).toBe('当前在做什么');
      expect(screen.getByTestId('watcher-part-doing').textContent).toContain('完成了 Watcher 与 Talk 改造');
      expect(screen.getByTestId('watcher-part-findings-label').textContent).toBe('关键发现或产出');
      expect(screen.getByTestId('watcher-part-findings').textContent).toContain(
        '已完成代码改造，等待选择信息结构'
      );
      expect(screen.getByTestId('watcher-part-decision-label').textContent).toBe('待拍板背景');
      expect(screen.getByTestId('watcher-part-decision').textContent).toContain(
        'Observer 信息结构采用哪种组织方式？'
      );

      // Talk 默认折叠，但决策卡在 Watcher 下原样展示且可直接选择发送
      const toggle = screen.getByTestId('watcher-talk-toggle-0');
      expect(toggle.getAttribute('aria-expanded')).toBe('false');
      expect(screen.queryByTestId('watcher-talk-body-0')).toBeNull();
      expect(screen.getByTestId('decision-card')).toBeTruthy();

      fireEvent.click(screen.getAllByTestId('decision-option')[1]);
      expect(answer).toHaveBeenCalledTimes(1);

      // 点击展开包裹的 Talk，展示内部对话与响应前动作聚合
      fireEvent.click(toggle);
      expect(toggle.getAttribute('aria-expanded')).toBe('true');
      expect(screen.getByTestId('watcher-talk-body-0')).toBeTruthy();
      expect(screen.getByText('请选择信息结构方案。')).toBeTruthy();
    });

    it('Watcher 每段总结严格锁定 [cursor_from, cursor_to) 闭区间，不会把游标之后新发生的回复塞进旧总结槽位', () => {
      const recordsWithTrailing = [
        record({ id: 'u1', seq: 0, kind: 'user.say', payload: { text: '第一问' } }),
        record({ id: 'a1', seq: 1, kind: 'agent.say', payload: { text: '第一答' } }),
        record({ id: 'u2', seq: 2, kind: 'user.say', payload: { text: '浮动按钮上的L和数字是什么含义？' } }),
        record({ id: 'a2', seq: 3, kind: 'agent.say', payload: { text: 'L是行号的缩写，代表起始行号到结束行号。' } }),
      ];
      const observerView: SessionObserverView = {
        state: {
          bound: true,
          anchor: '第一问',
          tail: { kind: 'output', text: '完成了第一问答复' },
          decision: '',
          happened: ['完成了第一问答复'],
          updated_at: 1_753_800_005_000,
          model: 'deepseek-v4-flash',
          status: 'ok',
          status_detail: null,
          runs: [
            {
              id: 'run-1',
              at: 1_753_800_005_000,
              cursor_from: 0,
              cursor_to: 2,
              tail: { kind: 'output', text: '完成了第一问答复' },
              happened_add: ['完成了第一问答复'],
              decision: '',
              summary: '完成了第一问答复',
            },
          ],
        },
        loading: false,
        error: null,
      };

      render(<RecordStream {...streamProps({ records: recordsWithTrailing, observer: observerView })} />);
      fireEvent.click(screen.getByTestId('lens-watcher'));

      // #1 总结严格只包裹 [0, 2) 内的 1 条提问 · 1 条回复，不会把 seq=2,3 的后续问答吞进去
      const toggle = screen.getByTestId('watcher-talk-toggle-0');
      expect(toggle.textContent).toContain('1条提问');
      expect(toggle.textContent).toContain('1条回复');

      // 游标 2 之后尚未总结的新对话独立呈现在尾部，不预设虚假的 #2 总结槽位
      expect(screen.getAllByTestId('watcher-item')).toHaveLength(1);
      const tail = screen.getByTestId('watcher-unsummarized-tail');
      expect(tail.textContent).toContain('浮动按钮上的L和数字是什么含义？');
      expect(tail.textContent).toContain('L是行号的缩写，代表起始行号到结束行号。');
    });

    it('Watcher 小标题独立成行、多条内容逐行分列，且随中英语言切换完整切换小标题与计数词条', async () => {
      const recordsForI18n = [
        record({ id: 'u1', seq: 0, kind: 'user.say', payload: { text: '第一段目标。第二段目标？' } }),
        record({ id: 'tc1', seq: 1, kind: 'tool.call', payload: { tool_name: 'Read', args: {} } }),
        record({ id: 'a1', seq: 2, kind: 'agent.say', payload: { text: '已完成检查' } }),
      ];
      const observerView: SessionObserverView = {
        state: {
          bound: true,
          anchor: '第一段目标。第二段目标？',
          tail: { kind: 'now', text: '正在检查 RecordStream 排版。同步核对语言包词条。' },
          decision: '请选择排版方案',
          happened: [
            '人在写入前新增检查项：先核对本轮改动是否越出用户原话，再查本地成例。',
            'agent 探测目标落在 127.0.0.1:9222 的 Chrome 调试接口；直接跳过无需唤醒桌面。',
          ],
          updated_at: 1_753_800_005_000,
          model: 'deepseek-v4-flash',
          status: 'ok',
          status_detail: null,
          runs: [
            {
              id: 'run-1',
              at: 1_753_800_005_000,
              cursor_from: 0,
              cursor_to: 3,
              tail: { kind: 'now', text: '正在检查 RecordStream 排版。同步核对语言包词条。' },
              happened_add: [
                '人在写入前新增检查项：先核对本轮改动是否越出用户原话，再查本地成例。',
                'agent 探测目标落在 127.0.0.1:9222 的 Chrome 调试接口；直接跳过无需唤醒桌面。',
              ],
              decision: '请选择排版方案',
              summary: '正在检查 RecordStream 排版',
            },
          ],
        },
        loading: false,
        error: null,
      };

      const { rerender } = render(
        <RecordStream {...streamProps({ records: recordsForI18n, observer: observerView })} />
      );
      fireEvent.click(screen.getByTestId('lens-watcher'));

      // 多条内容被拆分为独立的多行条目
      expect(screen.getAllByTestId('watcher-phase-goal-line')).toHaveLength(2);
      expect(screen.getAllByTestId('watcher-part-doing-line')).toHaveLength(2);
      expect(screen.getAllByTestId('watcher-part-findings-line')).toHaveLength(3);

      // 中文状态下：小标题与计数均为中文，且无硬编码冒号
      expect(screen.getByTestId('watcher-phase-goal-label').textContent).toBe('阶段目标');
      expect(screen.getByTestId('watcher-part-doing-label').textContent).toBe('当前在做什么');
      expect(screen.getByTestId('watcher-part-findings-label').textContent).toBe('关键发现或产出');
      expect(screen.getByTestId('watcher-part-decision-label').textContent).toBe('待拍板背景');
      expect(screen.getByTestId('watcher-talk-toggle-0').textContent).toContain('1条提问 · 1次工具调用 · 1条回复');

      // 切换到英文状态：小标题与计数全部切换为纯英文
      await i18n.changeLanguage('en');
      rerender(<RecordStream {...streamProps({ records: recordsForI18n, observer: observerView })} />);
      expect(screen.getByTestId('watcher-phase-goal-label').textContent).toBe('Stage goal');
      expect(screen.getByTestId('watcher-part-doing-label').textContent).toBe("What's happening now");
      expect(screen.getByTestId('watcher-part-findings-label').textContent).toBe('Key findings or output');
      expect(screen.getByTestId('watcher-part-decision-label').textContent).toBe('Decision context');
      expect(screen.getByTestId('watcher-talk-toggle-0').textContent).toContain('1 prompts · 1 tool calls · 1 replies');

      await i18n.changeLanguage('zh');
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
    origin: 'human',
    parent_session_id: null,
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
    todaySessions: sessions,
    loading: false,
    error: null,
    filter: 'all',
    setFilter: NOOP,
    counts: { all: 2, 'for-you': 0 },
    reload: async () => {},
    ...over,
  };
}

describe('SessionRail 左栏', () => {
  it('两家的会话都列出来，卡上不再标来源', () => {
    render(<TestRail state={railState()} selectedId={null} onSelect={NOOP} />);
    expect(screen.getAllByTestId('session-item')).toHaveLength(2);
    // 来源字样随第四轮退场：没挂 For you 的卡只剩一行标题加时间。
    expect(screen.queryByText('Claude Code')).toBeNull();
  });

  it('底部汇总只有已经发生的绝对数', () => {
    const { container } = render(
      <TestRail state={railState()} selectedId={null} onSelect={NOOP} />
    );
    expect(screen.getByText(/共 2 场/)).toBeTruthy();
    const text = container.textContent ?? '';
    expect(text.match(/\d+\s*%/g)).toBeNull();
    expect(text.match(/\d+\s*\/\s*\d+/g)).toBeNull();
    expect(container.querySelectorAll('progress, [role="progressbar"]')).toHaveLength(0);
  });

  it('点一场会话把编号交出去', () => {
    const onSelect = vi.fn();
    render(<TestRail state={railState()} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getAllByTestId('session-item')[0]);
    expect(onSelect).toHaveBeenCalledWith(SID);
  });

  it('选中的那一行整行换状态，不靠单边竖条', () => {
    render(<TestRail state={railState()} selectedId={SID} onSelect={NOOP} />);
    const [first] = screen.getAllByTestId('session-item');
    expect(first.getAttribute('aria-current')).toBe('true');
    const className = first.className;
    // 整行换底加整圈描边。这一条从前钉的是绿淡底——那是当时的实现，不是这条规矩本身。
    // 选中不是动作，现在换成中性底（--sel-bg）加一圈 --sel-border，规矩没变：状态由整行承担。
    expect(className).toContain('bg-[var(--sel-bg)]');
    expect(className).toContain('var(--sel-border)');
    expect(className).not.toContain('accent-primary');
    // 真正的禁令：任何单边色条都不许出现。
    expect(className).not.toMatch(/border-[lrtb]-\d/);
    expect(className).not.toMatch(/\bborder-[lrtb]\b/);
  });

  it('一场都没匹配上时说清楚，不当成坏了', () => {
    render(
      <TestRail
        state={railState({
          visible: [],
          counts: { all: 0, 'for-you': 0 },
        })}
        selectedId={null}
        onSelect={NOOP}
      />
    );
    expect(screen.getByText('没有匹配的会话')).toBeTruthy();
  });

  it('档位只剩 For you 与全部，状态与来源都不再当筛选维度', () => {
    render(<TestRail state={railState()} selectedId={null} onSelect={NOOP} />);
    const ids = screen
      .getAllByTestId(/^list-filter-/)
      .map((el) => el.getAttribute('data-testid'));
    expect(ids).toEqual(['list-filter-for-you', 'list-filter-all']);
    expect(screen.queryByTestId(/^status-filter-/)).toBeNull();
  });

  it('每一档带真实条数，不是摆设', () => {
    render(
      <TestRail
        state={railState({ counts: { all: 12, 'for-you': 3 } })}
        selectedId={null}
        onSelect={NOOP}
      />
    );
    expect(screen.getByTestId('list-filter-for-you').textContent).toContain('3');
    expect(screen.getByTestId('list-filter-all').textContent).toContain('12');
  });

  it('点某一档把它交出去', () => {
    const setFilter = vi.fn();
    render(<TestRail state={railState({ setFilter })} selectedId={null} onSelect={NOOP} />);
    fireEvent.click(screen.getByTestId('list-filter-for-you'));
    expect(setFilter).toHaveBeenCalledWith('for-you');
  });

  it('会话卡不再摆状态与来源；预览行取回复摘要，卡住摘要不上卡', () => {
    const one = session({
      session_id: SID,
      status: 'error',
      digest_done: '把镜头判断追加进了 verdict.jsonl',
      digest_stuck: 'API Error: 连接中断',
    });
    render(
      <TestRail
        state={railState({ sessions: [one], visible: [one] })}
        selectedId={null}
        onSelect={NOOP}
      />
    );
    const item = screen.getAllByTestId('session-item')[0];
    expect(item.getAttribute('data-status')).toBeNull();
    expect(screen.queryByTestId('digest-done')).toBeNull();
    expect(screen.queryByTestId('digest-stuck')).toBeNull();
    expect(item.textContent).not.toContain('Claude Code');
    expect(item.textContent).not.toContain('API Error');
    // 第五轮：所有会话都有预览行，服务端出「回复结尾」之前取最近一条回复的摘要
    expect(item.querySelector('[data-testid=session-preview]')?.textContent).toContain('verdict.jsonl');
  });

  it('没有等你决策那一档', () => {
    const { container } = render(
      <TestRail state={railState()} selectedId={null} onSelect={NOOP} />
    );
    const text = container.textContent ?? '';
    expect(text).not.toContain('等你');
    expect(text).not.toContain('待决策');
    expect(screen.queryByTestId('status-filter-waiting')).toBeNull();
  });

  it('搜索那一行只是入口：点它打开全站的搜会话浮窗，清单不跟着筛', () => {
    useUIStore.getState().setSessionSearchOpen(false);
    render(<TestRail state={railState()} selectedId={null} onSelect={NOOP} />);
    expect(screen.queryByRole('textbox', { name: '搜会话' })).toBeNull();
    fireEvent.click(screen.getByTestId('session-search-trigger'));
    expect(useUIStore.getState().sessionSearchOpen).toBe(true);
    useUIStore.getState().setSessionSearchOpen(false);
  });

  it('左栏摆 Timeline 入口与「只看今天」口径，不再有时间范围档位', () => {
    const onOpenTimeline = vi.fn();
    render(
      <TestRail
        state={railState()}
        selectedId={null}
        onSelect={NOOP}
        onOpenTimeline={onOpenTimeline}
      />
    );
    // 时间范围档位随这一轮退场：左栏只回答「今天」，全部会话去 Timeline 看。
    expect(screen.queryAllByTestId(/^day-filter-/)).toHaveLength(0);
    expect(screen.getByText('只看今天')).toBeTruthy();
    fireEvent.click(screen.getByTestId('open-timeline'));
    expect(onOpenTimeline).toHaveBeenCalledTimes(1);
    // 点 Timeline 不动档位那一维。
    expect(screen.getByTestId('list-filter-all').getAttribute('aria-pressed')).toBe('true');
  });

  it('正在起的那一场先在清单上方占一行，直到它自己长出来', () => {
    const launch = {
      handle: 'launch-1',
      agentName: 'codex',
      cwd: '/Users/frago/Repos/frago',
      text: '起一场新的',
      sessionId: null,
      phase: 'claiming' as const,
      error: null,
      at: Date.now(),
    };
    render(
      <TestRail state={railState()} selectedId={null} onSelect={NOOP} launch={launch} />
    );

    const card = screen.getByTestId('rail-launch');
    expect(card.getAttribute('data-phase')).toBe('claiming');
    expect(card.textContent).toContain('起一场新的');
    expect(card.textContent).toContain('codex');
  });

  it('没有正在起的会话时，清单上方不多出任何东西', () => {
    render(<TestRail state={railState()} selectedId={null} onSelect={NOOP} />);
    expect(screen.queryByTestId('rail-launch')).toBeNull();
  });

  it('新建会话的入口在左栏顶部，交给页面中栏渲染内联起始页（单独摆左栏时仍可内联展开三项决定）', async () => {
    const onToggleNew = vi.fn();
    const { unmount } = render(
      <TestRail
        state={railState()}
        selectedId={null}
        onSelect={NOOP}
        creatingNew={false}
        onToggleNew={onToggleNew}
      />
    );
    const entry = screen.getByTestId('new-session');
    expect(entry.getAttribute('aria-label')).toBe('新建会话');
    expect(entry.className).not.toContain('accent-primary');
    fireEvent.click(entry);
    expect(onToggleNew).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('new-session-inline')).toBeNull();
    unmount();

    render(<TestRail state={railState()} selectedId={null} onSelect={NOOP} />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('new-session'));
    });
    expect(screen.getByTestId('new-session-inline')).toBeTruthy();
    // 三块的标题是三句并列的问话——人读一遍就知道自己在做哪三个决定。
    expect(screen.getByText('这场会话交给哪个 agent 跑？')).toBeTruthy();
    expect(screen.getByText('让它在哪个项目里干活？')).toBeTruthy();
    expect(screen.getByText('你想让它做什么？')).toBeTruthy();
  });

  it('每张卡都能复制恢复命令，两家各按自己的形状', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<TestRail state={railState()} selectedId={null} onSelect={NOOP} />);
    // 复制续接命令收进了「…」菜单第一段
    const [ccMenu, ocMenu] = screen.getAllByTestId('session-menu-button');
    fireEvent.click(ccMenu);
    await act(async () => {
      fireEvent.click(screen.getByTestId('copy-resume'));
    });
    expect(writeText).toHaveBeenCalledWith(`claude --resume ${SID}`);
    fireEvent.click(ocMenu);
    await act(async () => {
      fireEvent.click(screen.getByTestId('copy-resume'));
    });
    expect(writeText).toHaveBeenCalledWith('opencode -s ses_058288655ffeYMxYC1AZKCcv56');
  });

  it('点复制不会顺带把这场会话选中', async () => {
    const onSelect = vi.fn();
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
      configurable: true,
    });
    render(<TestRail state={railState()} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getAllByTestId('session-menu-button')[0]);
    await act(async () => {
      fireEvent.click(screen.getByTestId('copy-resume'));
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

  it('清单上的时间不带「前」', () => {
    const now = 1_753_800_000_000;
    expect(shortAge(now - 30_000, now)).toBe('刚刚');
    expect(shortAge(now - 12 * 60_000, now)).toBe('12 分钟');
    expect(shortAge(now - 3 * 3_600_000, now)).toBe('3 小时');
  });
});

describe('ReportPanel 右栏', () => {
  const view = (
    state: Partial<ObserverState> | null,
    extra: Partial<SessionObserverView> = {},
  ): SessionObserverView => ({
    state: state && {
      bound: true,
      anchor: '把会话记录归一成同一种形状',
      tail: { kind: 'now', text: '在跑测试' },
      decision: '',
      happened: [],
      updated_at: null,
      model: null,
      status: 'ok',
      status_detail: null,
      ...state,
    },
    loading: false,
    error: null,
    ...extra,
  });

  it('没选会话时只说一句该做什么', () => {
    render(<ReportBody sessionId={null} view={view(null)} />);
    expect(screen.getByText(/选一场会话/)).toBeTruthy();
  });

  describe('轮到你了', () => {
    it('有待决时钉在栏顶，排在所有格子前面', () => {
      const { container } = render(
        <ReportBody sessionId="s1" view={view({ decision: '三条改法要人挑一条' })} />,
      );
      expect(screen.getByText('轮到你了')).toBeTruthy();
      expect(screen.getByText('三条改法要人挑一条')).toBeTruthy();

      // 它不在滚动区里面：右栏滚到哪儿它都在。
      const scroller = container.querySelector('.overflow-y-auto');
      expect(scroller?.textContent).not.toContain('三条改法要人挑一条');

      // 顺序上排在第一格前面。
      const body = container.textContent ?? '';
      expect(body.indexOf('轮到你了')).toBeLessThan(body.indexOf('这场在做什么'));
    });

    it('没有待决时整条不存在，不留一个「（无）」占着栏顶', () => {
      render(<ReportBody sessionId="s1" view={view({ decision: '' })} />);
      expect(screen.queryByText('轮到你了')).toBeNull();
      expect(screen.queryByText('需要你决策')).toBeNull();
    });
  });

  it('只剩两块：要干嘛 → 一路走来，「此刻」「产出」不再单独成格', () => {
    const body =
      render(<ReportBody sessionId="s1" view={view({ happened: ['做了一件事'] })} />).container
        .textContent ?? '';
    const order = ['这场在做什么', '已经发生的事'].map((s) => body.indexOf(s));
    expect(order).toEqual([...order].sort((a, b) => a - b));
    expect(order.every((i) => i >= 0)).toBe(true);
    expect(body).not.toContain('此刻在做什么');
    expect(body).not.toContain('最近一次产出');
  });

  it('每块标它自己上次变样的时刻，老槽位文件没有就不标', () => {
    const now = Date.now();
    render(
      <ReportBody
        sessionId="s1"
        view={view({
          anchor_at: now - 5 * 3600_000,
          tail: { kind: 'now', text: '在跑测试' },
          tail_at: now - 3 * 60_000,
        })}
      />,
    );
    expect(screen.getByText('3 分钟前')).toBeTruthy();
    expect(screen.getByText('5 小时前')).toBeTruthy();
  });

  describe('末条就是眼下的状态', () => {
    it('默认只露末条，其余都收在「展开更早的」里', () => {
      const { container } = render(
        <ReportBody
          sessionId="s1"
          view={view({
            happened: ['第三件', '第二件', '第一件'],
            tail: { kind: 'now', text: '在跑测试' },
          })}
        />,
      );
      const items = () =>
        Array.from(container.querySelectorAll('ul li')).map((li) => li.textContent);
      expect(items()).toEqual(['此刻在跑测试']);
      fireEvent.click(screen.getByText('展开更早的 3 条'));
      expect(items()).toEqual(['第一件', '第二件', '第三件', '此刻在跑测试']);
    });

    it('产出出来了，末条标「产出」，没有「此刻」', () => {
      render(
        <ReportBody
          sessionId="s1"
          view={view({ happened: ['读了配方'], tail: { kind: 'output', text: '配方改好' } })}
        />,
      );
      expect(screen.getByText('产出')).toBeTruthy();
      expect(screen.queryByText('此刻')).toBeNull();
      expect(screen.getByText('配方改好')).toBeTruthy();
    });

    it('还没有末条时，最新一条历史就是末条', () => {
      const { container } = render(
        <ReportBody sessionId="s1" view={view({ happened: ['第二件', '第一件'], tail: null })} />,
      );
      expect(Array.from(container.querySelectorAll('ul li')).map((li) => li.textContent)).toEqual([
        '第二件',
      ]);
      expect(screen.getByText('展开更早的 1 条')).toBeTruthy();
    });

    it('什么都没有时写「（无）」', () => {
      render(<ReportBody sessionId="s1" view={view({ happened: [], tail: null, anchor: '目标' })} />);
      expect(screen.getByText('（无）')).toBeTruthy();
    });
  });

  it('旁路 AI 没绑模型时明说', () => {
    render(<ReportBody sessionId="s1" view={view({ bound: false, status: 'unbound' })} />);
    expect(screen.getByText(/还没绑定模型/)).toBeTruthy();
  });

  it('锚槽排最上面，写的是人的原话', () => {
    const { container } = render(<ReportBody sessionId="s1" view={view({})} />);
    const labels = Array.from(container.querySelectorAll('header')).map((h) => h.textContent);
    expect(labels[0]).toContain('这场在做什么');
    expect(screen.getByText('把会话记录归一成同一种形状')).toBeTruthy();
  });

  it('上一次没问到时把原因说出来', () => {
    render(
      <ReportBody sessionId="s1" view={view({ status: 'failed', status_detail: 'WorkBuddy 没登录' })} />,
    );
    expect(screen.getByText(/WorkBuddy 没登录/)).toBeTruthy();
  });

  it('增长型槽位的展开按钮写绝对条数，不写比值', () => {
    const { container } = render(
      <ReportBody
        sessionId="s1"
        view={view({ happened: ['第五件', '第四件', '第三件', '第二件', '第一件'] })}
      />,
    );
    const more = screen.getByText(/展开更早的 \d+ 条/);
    expect(more).toBeTruthy();
    fireEvent.click(more);
    expect(screen.queryByText(/展开更早的/)).toBeNull();
    const text = container.textContent ?? '';
    expect(text.match(/\d+\s*%/g)).toBeNull();
    expect(text.match(/\d+\s*\/\s*\d+/g)).toBeNull();
    expect(container.querySelectorAll('progress, [role="progressbar"]')).toHaveLength(0);
  });

  it('已经发生的事一条一格，条与条之间有分隔线，老的排在上面', () => {
    // 服务端给的是新的在前；整栏是一条从上往下走的时间线，这一格里要是从下往上读，
    // 两个方向打架，人就看不出谁先谁后了。
    const { container } = render(
      <ReportBody
        sessionId="s1"
        view={view({ happened: ['第三件', '第二件', '第一件'], tail: null })}
      />,
    );
    fireEvent.click(screen.getByText(/展开更早的/));
    const list = container.querySelector('ul');
    expect(list?.className).toContain('divide-y');
    expect(Array.from(list?.querySelectorAll('li') ?? []).map((li) => li.textContent)).toEqual([
      '第一件',
      '第二件',
      '第三件',
    ]);
  });

  describe('版面由人来定', () => {
    beforeEach(() => window.localStorage.clear());

    it('内容装不下时给「展开全文」，展开后变成「收起」', () => {
      const own = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollHeight');
      Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
        configurable: true,
        get() {
          return (this as HTMLElement).hasAttribute('data-slot-body') ? 400 : 0;
        },
      });
      try {
        render(<ReportBody sessionId="s1" view={view({})} />);
        fireEvent.click(screen.getAllByText('展开全文')[0]);
        expect(screen.getAllByText('收起').length).toBe(1);
      } finally {
        if (own) Object.defineProperty(HTMLElement.prototype, 'scrollHeight', own);
        else delete (HTMLElement.prototype as unknown as Record<string, unknown>).scrollHeight;
      }
    });

    it('点标题折成只剩标题，重新打开还是折着的', () => {
      const { unmount } = render(<ReportBody sessionId="s1" view={view({})} />);
      fireEvent.click(screen.getByRole('button', { name: /已经发生的事/ }));
      expect(screen.queryByText('在跑测试')).toBeNull();
      unmount();
      render(<ReportBody sessionId="s1" view={view({})} />);
      expect(screen.queryByText('在跑测试')).toBeNull();
    });

    it('分隔线调这一格的高度，双击回默认，调过的记得住', () => {
      render(<ReportBody sessionId="s1" view={view({})} />);
      const handle = screen.getByRole('separator', { name: /这场在做什么/ });
      expect(handle.getAttribute('aria-valuenow')).toBe('112');
      fireEvent.keyDown(handle, { key: 'ArrowDown' });
      expect(handle.getAttribute('aria-valuenow')).toBe('128');
      expect(window.localStorage.getItem('frago.workbench.reportSlots.v1')).toContain('128');
      fireEvent.doubleClick(handle);
      expect(handle.getAttribute('aria-valuenow')).toBe('112');
    });

    it('旧版面里存的「此刻」「产出」两格的折叠，不会把什么藏起来', () => {
      window.localStorage.setItem(
        'frago.workbench.reportSlots.v1',
        JSON.stringify({ heights: { anchor: 112, now: 76, output: 76 }, collapsed: ['now', 'output'] }),
      );
      render(<ReportBody sessionId="s1" view={view({})} />);
      expect(screen.getByText('在跑测试')).toBeTruthy();
    });

    it('最后一块底下没有分隔线', () => {
      // 「已经发生的事」是时间线的终点，底下再画一道线就像下面还有一段。
      render(<ReportBody sessionId="s1" view={view({})} />);
      expect(screen.queryByRole('separator', { name: /已经发生的事/ })).toBeNull();
    });

    it('右栏左边缘调整栏宽度，双击回默认', () => {
      const onWidthChange = vi.fn();
      render(
        <ReportBody sessionId="s1" view={view({})} width={400} onWidthChange={onWidthChange} />,
      );
      const handle = screen.getByRole('separator', { name: /宽度/ });
      fireEvent.keyDown(handle, { key: 'ArrowLeft' });
      expect(onWidthChange).toHaveBeenLastCalledWith(416);
      fireEvent.doubleClick(handle);
      expect(onWidthChange).toHaveBeenLastCalledWith(null);
    });

    it('stackOnly 模式下右栏不再渲染观察者摘要槽位，仅保留暂存面板', () => {
      render(
        <ReportBody
          stackOnly
          sessionId="s1"
          view={view({ decision: '待决问题' })}
          lower={<div data-testid="only-stack">暂存区</div>}
        />,
      );
      expect(screen.getByTestId('only-stack')).toBeTruthy();
      expect(screen.queryByTestId('report-upper')).toBeNull();
      expect(screen.queryByText('这场在做什么')).toBeNull();
      expect(screen.queryByText('轮到你了')).toBeNull();
    });
  });
});

describe('RecordStream 自动跟随的滑法', () => {
  const GROUP2 = 'msg_01SkR7HrxLZ7hTfaLPKgcyQz';

  function rec(over: Partial<WorkbenchRecord> & { id: string; seq: number }): WorkbenchRecord {
    return {
      session_id: '00a02979-7eb4-5c70-94ae-867c8281e3f6',
      group_id: null,
      ts: 1_753_800_000_000,
      kind: 'agent.say',
      agent_path: [],
      payload: { text: '一句', model: 'claude-opus-5' },
      raw_available: true,
      ...over,
    } as WorkbenchRecord;
  }

  const base = [rec({ id: 'a', seq: 0 }), rec({ id: 'b', seq: 1, group_id: GROUP2 })];

  function props(over: Partial<React.ComponentProps<typeof RecordStream>> = {}) {
    return {
      sessionId: '00a02979-7eb4-5c70-94ae-867c8281e3f6',
      records: base,
      loading: false,
      loadingOlder: false,
      hasOlder: false,
      error: null,
      onLoadOlder: () => {},
      ...over,
    };
  }

  /** jsdom 没有 scrollTo，装一个能记账的。 */
  function installScrollTo(el: Element) {
    const calls: ScrollToOptions[] = [];
    Object.defineProperty(el, 'scrollTo', {
      configurable: true,
      value: (opts: ScrollToOptions) => {
        calls.push(opts);
        if (typeof opts.top === 'number') {
          Object.defineProperty(el, 'scrollTop', { value: opts.top, configurable: true });
        }
      },
    });
    return calls;
  }

  function geometry(el: Element, height: number, client: number, top: number) {
    Object.defineProperty(el, 'scrollHeight', { value: height, configurable: true });
    Object.defineProperty(el, 'clientHeight', { value: client, configurable: true });
    Object.defineProperty(el, 'scrollTop', { value: top, configurable: true });
  }

  it('近处追加用动画滑过去，人眼跟得住"又来了一条"', () => {
    const { rerender } = render(<RecordStream {...props()} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    const calls = installScrollTo(scroller);
    geometry(scroller, 2000, 800, 1200); // 已经贴着底

    rerender(<RecordStream {...props({ records: [...base, rec({ id: 'c', seq: 2 })] })} />);
    expect(calls[calls.length - 1]?.behavior).toBe('smooth');
  });

  it('远处直接落位——那种距离拿动画滑等于让人干等半秒还看不清落点', () => {
    const { rerender } = render(<RecordStream {...props()} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    const calls = installScrollTo(scroller);
    geometry(scroller, 40000, 800, 0); // 离底部三万多像素

    rerender(<RecordStream {...props({ records: [...base, rec({ id: 'c', seq: 2 })] })} />);
    expect(calls[calls.length - 1]?.behavior).toBe('auto');
  });

  it('人一伸手，动画余波立刻作废——不许出现「滚着滚着就不跟了」', () => {
    const { rerender } = render(<RecordStream {...props()} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    installScrollTo(scroller);
    geometry(scroller, 2000, 800, 1200);

    // 程序刚滑过（挂载时那次沉底留下的余波窗口还开着），紧接着人自己滚轮往上翻。
    // 这一下必须被认成人滚的：认不出来，自动跟随就永远解除不掉。
    fireEvent.wheel(scroller);
    Object.defineProperty(scroller, 'scrollTop', { value: 100, configurable: true });
    fireEvent.scroll(scroller);

    // 人翻上去了，新条目进来不许把视口拽回底部。
    const calls = installScrollTo(scroller);
    Object.defineProperty(scroller, 'scrollHeight', { value: 2600, configurable: true });
    rerender(<RecordStream {...props({ records: [...base, rec({ id: 'c', seq: 2 })] })} />);
    expect(calls).toHaveLength(0);
    expect(scroller.scrollTop).toBe(100);
  });

  it('页面被藏起来时一律直接落位——后台标签根本不发帧，动画一步都走不了', () => {
    const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
    try {
      const { rerender } = render(<RecordStream {...props()} />);
      const scroller = screen.getByTestId('record-stream-scroll');
      const calls = installScrollTo(scroller);
      geometry(scroller, 2000, 800, 1200); // 贴着底，本来该走动画那一档

      rerender(<RecordStream {...props({ records: [...base, rec({ id: 'c', seq: 2 })] })} />);
      expect(calls[calls.length - 1]?.behavior).toBe('auto');
      expect(scroller.scrollTop).toBe(2000);
    } finally {
      hidden.mockRestore();
    }
  });

  it('刚发完话，那句话下面挂进度与「Agent 在做」，流末尾不再有居中灰字', () => {
    const said = rec({ id: 'u', seq: 2, kind: 'user.say', payload: { text: '都记成 todo。' } });
    const trail = {
      id: 'out-1',
      text: '都记成 todo。',
      attachments: 0,
      recordId: 'u',
      midTurn: false,
      steps: { on_its_way: Date.now() - 3_000, in_the_session: Date.now() - 2_000 },
    };
    render(
      <RecordStream
        {...props({ records: [...base, said], awaitingAgent: true, trails: [trail] })}
      />
    );
    expect(screen.queryByTestId('awaiting-agent')).toBeNull();
    const bubble = screen.getByTestId('trail-bubble');
    expect(bubble.getAttribute('data-fresh')).toBe('true');
    expect(screen.getByTestId('send-progress').getAttribute('data-step')).toBe('in_the_session');
    expect(screen.getByTestId('agent-on-it').textContent).toContain('在想，还没写字');
  });

  it('同回合既有 frago app ask 工具结果又有多条回复或内联 YAML 区块时，去重只渲染一张决策卡', () => {
    const cliCard = JSON.stringify({
      frago_ui_component: 'decision-card',
      component_type: 'single-choice',
      data: {
        type: 'single-choice',
        question: '是否部署？',
        options: [
          { key: 'A', label: '立即部署', effect: '构建并重启服务', recommended: true },
          { key: 'B', label: '暂不部署', effect: '仅保留代码改动' },
        ],
      },
    });
    const inlineYaml = [
      '请在下方卡片点选：',
      '```answer-needed-by-human',
      'type: single-choice',
      'question: 是否部署？',
      'options:',
      '  - key: A',
      '    label: 立即部署',
      '    effect: 构建并重启服务',
      '    recommended: true',
      '  - key: B',
      '    label: 暂不部署',
      '    effect: 仅保留代码改动',
      '```',
    ].join('\n');

    const turnRecords: WorkbenchRecord[] = [
      rec({ id: 'u1', seq: 1, kind: 'user.say', payload: { text: '帮我准备部署' } }),
      rec({
        id: 't1',
        seq: 2,
        kind: 'tool.result',
        payload: { tool_name: 'Bash', status: 'ok', body: cliCard },
      }),
      rec({ id: 'a1', seq: 3, kind: 'agent.say', payload: { text: inlineYaml } }),
      rec({ id: 'a2', seq: 4, kind: 'agent.say', payload: { text: inlineYaml } }),
    ];

    const processed = withTurnDecisionCards(turnRecords);
    // t1 与前一条内联卡片回复 a1 均被标记为 delegated，仅最后一条回复 a2 承载当轮决策卡
    expect(processed[1].payload.ui_component_delegated).toBe(true);
    expect(processed[2].payload.ui_component_delegated).toBe(true);
    expect(processed[3].payload.ui_component).toBe(cliCard);

    render(<RecordStream {...props({ records: turnRecords })} />);
    expect(screen.getAllByTestId('decision-card')).toHaveLength(1);
  });

  it('工具输出同时含前文闭合花括号、注释里的 frago_ui_component 与 image-grid 字样时不发生死循环', () => {
    const diffLikeBody = [
      'fn helper() {}',
      '/// 与页面 `parseUiComponentOutput` 同构：找最后一个 `"frago_ui_component"`',
      '/// 以及 `"image-grid"` 组件标记',
    ].join('\n');
    const turnRecords: WorkbenchRecord[] = [
      rec({ id: 'u1', seq: 1, kind: 'user.say', payload: { text: '检查代码' } }),
      rec({
        id: 't1428',
        seq: 1428,
        kind: 'tool.result',
        payload: { tool_name: 'Bash', status: 'ok', body: diffLikeBody },
      }),
      rec({ id: 'a1', seq: 1429, kind: 'agent.say', payload: { text: '检查完毕。' } }),
    ];

    const processed = withTurnDecisionCards(turnRecords);
    expect(processed).toHaveLength(3);
    render(<RecordStream {...props({ records: turnRecords })} />);
    expect(screen.getByText('检查完毕。')).toBeTruthy();
  });

  it('Executor 栏支持终端档位切换，展开终端视图时不卸载底层记录流，并支持 ANSI 色彩解析', () => {
    const onTerminalOpenChange = vi.fn();
    const onFilesOpenChange = vi.fn();
    const { rerender } = render(
      <RecordStream
        {...props({
          terminalView: <div data-testid="mock-terminal-body">tmux pane output</div>,
          terminalOpen: false,
          onTerminalOpenChange,
          onFilesOpenChange,
          terminalAlive: true,
        })}
      />
    );

    const termBtn = screen.getByTestId('lens-terminal');
    expect(termBtn.textContent).toContain('终端');
    expect(screen.getByTestId('lens-terminal-alive')).toBeTruthy();
    expect(screen.queryByTestId('terminal-panel')).toBeNull();

    fireEvent.click(termBtn);
    expect(onFilesOpenChange).toHaveBeenCalledWith(false);
    expect(onTerminalOpenChange).toHaveBeenCalledWith(true);

    rerender(
      <RecordStream
        {...props({
          terminalView: <div data-testid="mock-terminal-body">tmux pane output</div>,
          terminalOpen: true,
          onTerminalOpenChange,
          onFilesOpenChange,
          terminalAlive: true,
        })}
      />
    );
    expect(screen.getByTestId('terminal-panel')).toBeTruthy();
    expect(screen.getByTestId('mock-terminal-body').textContent).toBe('tmux pane output');
    // 底层滚动容器依旧存在，不因切到终端档位而卸载
    expect(screen.getByTestId('record-stream-scroll')).toBeTruthy();

    // ANSI 色彩与清屏控制序列解析验证
    const spans = parseAnsiSegments('\x1b[2J\x1b[H\x1b[1;32m✔ Turn complete\x1b[0m plain');
    expect(spans).toEqual([
      { text: '✔ Turn complete', fg: '#3fb950', bold: true, dim: undefined },
      { text: ' plain', fg: undefined, bold: undefined, dim: undefined },
    ]);
  });
});

