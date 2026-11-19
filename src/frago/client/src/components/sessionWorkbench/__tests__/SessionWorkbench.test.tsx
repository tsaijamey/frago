/**
 * 三栏的组件测试：左栏清单、中栏记录流、右栏示意面。
 *
 * 重点在四处：视觉归组但不露编号、空会话渲染成引导页而不是报错、左栏底部汇总只有绝对
 * 数、全域禁令在三栏都成立。
 */

import { beforeAll, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import RecordStream, {
  buildTalkSegments,
  groupRecords,
  lensOf,
  normalizeStreamLensParam,
  talkView,
  withTurnDecisionCards,
} from '../RecordStream';
import { DecisionCardContext } from '../DecisionCard';
import { TestRail } from './railTestKit';
import { relativeTime, sessionLifecycleOf, sessionOriginOf, shortAge } from '../SessionItem';
import { ReportBody, jumpToPendingCard } from '../ReportPanel';
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

describe('talkView 对话档用量内联至回复卡头', () => {
  it('talkView 不再在对话之间独立插入用量行，用量上下文内联挂载到回复中', () => {
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
    expect(view.map((r) => r.id)).toEqual(['u', 'a']);
    expect(view[1].payload.context_tokens).toBe(5);
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

  it('没挑会话时仅渲染简洁空态提示，不渲染最近会话快捷按钮列表', () => {
    render(<RecordStream {...streamProps({ sessionId: null, records: [] })} />);
    expect(screen.getByText(/从左边挑一场会话/)).toBeTruthy();
    expect(screen.queryByTestId('stream-empty-recent')).toBeNull();
    expect(screen.queryByTestId('stream-empty-recent-item')).toBeNull();
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

  it('短内容天然覆盖底部 100px 时新消息自动滚底', () => {
    const { rerender } = render(<RecordStream {...streamProps({ records: [], loading: true })} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    // 短内容 850px，可视区 800px，视口天然覆盖底部热区
    setGeometry(scroller, 850, 800);
    rerender(<RecordStream {...streamProps()} />);
    // 短内容天然覆盖底部，武装贴底；新消息到来撑高到 1200px 时自动滚底
    setGeometry(scroller, 1200, 800);
    const appended = record({ id: 'd', seq: 3, kind: 'agent.say', payload: { text: '短内容新消息' } });
    rerender(<RecordStream {...streamProps({ records: [...twoInAGroup, appended] })} />);
    expect(scroller.scrollTop).toBe(1200);
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

  it('翻上去之后右下角亮「跳到最新」，点了沉底、按钮熄灭', () => {
    render(<RecordStream {...streamProps()} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    setGeometry(scroller, 2000, 800);

    // 初装沉底：人就在底部，按钮没有可干的事，不出现。
    expect(screen.queryByTestId('jump-to-latest')).toBeNull();

    // 人翻到顶（离底 2000px）：按钮亮。
    fireEvent.wheel(scroller);
    scroller.scrollTop = 0;
    fireEvent.scroll(scroller);
    expect(screen.getByTestId('jump-to-latest')).toBeTruthy();

    // 点它：沉底、按钮熄灭。
    fireEvent.click(screen.getByTestId('jump-to-latest'));
    expect(scroller.scrollTop).toBe(2000);
    expect(screen.queryByTestId('jump-to-latest')).toBeNull();

    // 再次翻到顶亮起按钮后，切换顶栏镜头自动沉底，按钮同步熄灭不残留。
    fireEvent.wheel(scroller);
    scroller.scrollTop = 0;
    fireEvent.scroll(scroller);
    expect(screen.getByTestId('jump-to-latest')).toBeTruthy();
    fireEvent.click(screen.getByTestId('lens-all'));
    expect(screen.queryByTestId('jump-to-latest')).toBeNull();
  });

  it('离底不到一屏之远时「跳到最新」不出现——随手一滚就回去，不打扰', () => {
    render(<RecordStream {...streamProps()} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    setGeometry(scroller, 2000, 800);

    // 离底 200px（< 240 的门槛）：不亮。
    fireEvent.wheel(scroller);
    scroller.scrollTop = 1000;
    fireEvent.scroll(scroller);
    expect(screen.queryByTestId('jump-to-latest')).toBeNull();
  });

  it('距底 100px 内遇到单次 >100px 高新内容仍持续自动滚底', () => {
    const { rerender } = render(<RecordStream {...streamProps()} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    setGeometry(scroller, 2000, 800);

    // 用户滚动到距底 50px（2000 - 1150 - 800 = 50 <= 100px），进入热区武装
    fireEvent.wheel(scroller);
    scroller.scrollTop = 1150;
    fireEvent.scroll(scroller);

    // 单次插入大段内容（如工具输出），高度瞬间暴增 600px（远超 100px 阈值）到 2600px
    setGeometry(scroller, 2600, 800);
    const appended = record({ id: 'd', seq: 3, kind: 'agent.say', payload: { text: '大段长内容' } });
    rerender(<RecordStream {...streamProps({ records: [...twoInAGroup, appended] })} />);
    // 依据内容插入前的武装状态，依然持续自动滚到底部
    expect(scroller.scrollTop).toBe(2600);
  });

  it('上翻至 101px+ 后新内容绝不抢滚', () => {
    const { rerender } = render(<RecordStream {...streamProps()} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    setGeometry(scroller, 2000, 800);

    // 距底 101px：2000 - 1099 - 800 = 101px > 100px，脱离底部热区解除武装
    fireEvent.wheel(scroller);
    scroller.scrollTop = 1099;
    fireEvent.scroll(scroller);

    // 新条目到来，内容增加到 2600px，视口绝对不动，严禁抢滚
    setGeometry(scroller, 2600, 800);
    const appended = record({ id: 'd', seq: 3, kind: 'agent.say', payload: { text: '新的' } });
    rerender(<RecordStream {...streamProps({ records: [...twoInAGroup, appended] })} />);
    expect(scroller.scrollTop).toBe(1099);
  });

  it('再下滚回 <=100px 后恢复自动滚底', () => {
    const { rerender } = render(<RecordStream {...streamProps()} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    setGeometry(scroller, 2000, 800);

    // 先上翻到上面解除武装
    fireEvent.wheel(scroller);
    scroller.scrollTop = 800;
    fireEvent.scroll(scroller);

    // 再下滚回距底刚好 100px：2000 - 1100 - 800 = 100px <= 100px，恢复武装
    fireEvent.wheel(scroller);
    scroller.scrollTop = 1100;
    fireEvent.scroll(scroller);

    setGeometry(scroller, 2600, 800);
    const appended = record({ id: 'd', seq: 3, kind: 'agent.say', payload: { text: '恢复后新消息' } });
    rerender(<RecordStream {...streamProps({ records: [...twoInAGroup, appended] })} />);
    expect(scroller.scrollTop).toBe(2600);
  });

  it('解除后即使经过十秒，新条目进来也绝不抢滚（彻底根除十秒静默复活）', () => {
    vi.useFakeTimers();
    try {
      const { rerender } = render(<RecordStream {...streamProps()} />);
      const scroller = screen.getByTestId('record-stream-scroll');
      setGeometry(scroller, 2000, 800);

      // 上翻离开底部 100px 热区
      fireEvent.wheel(scroller);
      scroller.scrollTop = 1000;
      fireEvent.scroll(scroller);

      // 无论经过 11 秒还是更久，新条目进来都绝不抢滚
      vi.setSystemTime(Date.now() + 11_000);
      setGeometry(scroller, 2600, 800);
      const appended = record({ id: 'd', seq: 3, kind: 'agent.say', payload: { text: '新内容' } });
      rerender(<RecordStream {...streamProps({ records: [...twoInAGroup, appended] })} />);
      expect(scroller.scrollTop).toBe(1000);
    } finally {
      vi.useRealTimers();
    }
  });

  it('首尾 ID 不变但最后一条单条消息流式变长时，武装着持续自动滚底', () => {
    const { rerender } = render(<RecordStream {...streamProps()} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    setGeometry(scroller, 2000, 800);
    scroller.scrollTop = 1200; // 处于贴底武装状态

    // 流式增量到来：最后一条记录变长，但首尾 ID 均未变（first === prev.first && last === prev.last）
    setGeometry(scroller, 2500, 800);
    const updatedLast = {
      ...twoInAGroup[1],
      payload: { ...twoInAGroup[1].payload, text: '流式输出增长了内容长高500px' },
    };
    rerender(<RecordStream {...streamProps({ records: [twoInAGroup[0], updatedLast] })} />);
    // 持续自动贴底滚动到底部
    expect(scroller.scrollTop).toBe(2500);
  });

  it('首尾 ID 不变且最后一条流式变长时，若用户已离开底部 100px 热区则绝不抢滚', () => {
    const { rerender } = render(<RecordStream {...streamProps()} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    setGeometry(scroller, 2000, 800);

    // 用户手动上翻离开底部 100px 热区（距底 500px > 100px）
    fireEvent.wheel(scroller);
    scroller.scrollTop = 700;
    fireEvent.scroll(scroller);

    // 单条流式增长撑高内容
    setGeometry(scroller, 2500, 800);
    const updatedLast = {
      ...twoInAGroup[1],
      payload: { ...twoInAGroup[1].payload, text: '流式输出继续增长' },
    };
    rerender(<RecordStream {...streamProps({ records: [twoInAGroup[0], updatedLast] })} />);
    // 视口必须留在 700，严禁强行滚底！
    expect(scroller.scrollTop).toBe(700);
  });

  it('平滑滚动途中经过距底 >100px 位置时不被误解除武装（防滚着滚着自己不跟了）', () => {
    const { rerender } = render(<RecordStream {...streamProps()} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    setGeometry(scroller, 2000, 800);
    scroller.scrollTop = 1200; // 贴底

    // 触发平滑滚动（例如追加新条目撑高到 2600）
    setGeometry(scroller, 2600, 800);
    const appended1 = record({ id: 'd', seq: 3, kind: 'agent.say', payload: { text: '第一条' } });
    rerender(<RecordStream {...streamProps({ records: [...twoInAGroup, appended1] })} />);

    // 平滑滚动动画在半路上（比如 scrollTop 此时由于逐帧动画停在 1300，距底 500px > 100px）
    // 此时没有用户手动输入（无 wheel、无按键）
    scroller.scrollTop = 1300;
    fireEvent.scroll(scroller);

    // 再次追加新条目撑高到 3000
    setGeometry(scroller, 3000, 800);
    const appended2 = record({ id: 'e', seq: 4, kind: 'agent.say', payload: { text: '第二条' } });
    rerender(<RecordStream {...streamProps({ records: [...twoInAGroup, appended1, appended2] })} />);
    // 状态机没有在中途被误解除，继续滚到底部 3000
    expect(scroller.scrollTop).toBe(3000);
  });

  it('鼠标按住原生滚动条滑块拖离底部 100px 热区后立即解除自动滚底', () => {
    const { rerender } = render(<RecordStream {...streamProps()} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    setGeometry(scroller, 2000, 800);
    scroller.scrollTop = 1200; // 贴底

    // 模拟鼠标按在右侧滚动条区域（clientX 在容器右边界 20px 内）
    vi.spyOn(scroller, 'getBoundingClientRect').mockReturnValue({
      right: 500,
      left: 0,
      top: 0,
      bottom: 800,
      width: 500,
      height: 800,
      x: 0,
      y: 0,
      toJSON: () => {},
    });
    fireEvent.mouseDown(scroller, { clientX: 490 });

    // 鼠标拖拽滚动条向上，scrollTop 变为 800（距底 400px > 100px）
    scroller.scrollTop = 800;
    fireEvent.scroll(scroller);

    // 新条目到来，内容增加到 2600px，视口绝对不动
    setGeometry(scroller, 2600, 800);
    const appended = record({ id: 'd', seq: 3, kind: 'agent.say', payload: { text: '新内容' } });
    rerender(<RecordStream {...streamProps({ records: [...twoInAGroup, appended] })} />);
    expect(scroller.scrollTop).toBe(800);
  });

  it('用户离开底部 100px 热区后，整流重拉/轮询刷新绝不抢滚', () => {
    const { rerender } = render(<RecordStream {...streamProps()} />);
    const scroller = screen.getByTestId('record-stream-scroll');
    setGeometry(scroller, 2000, 800);

    // 用户上翻离开底部 100px 热区
    fireEvent.wheel(scroller);
    scroller.scrollTop = 900;
    fireEvent.scroll(scroller);

    // 整流替换/全量刷新（first 和 last 均变化）
    setGeometry(scroller, 2400, 800);
    const refreshed = [
      record({ id: 'r1', seq: 10, kind: 'user.say', payload: { text: '重排1' } }),
      record({ id: 'r2', seq: 11, kind: 'agent.say', payload: { text: '重排2' } }),
    ];
    rerender(<RecordStream {...streamProps({ records: refreshed })} />);
    // 视口依然保持在 900，绝不强行沉底
    expect(scroller.scrollTop).toBe(900);
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

    it('每一档带真实条数——筛掉的东西必须在条数上看得见（Inspect 折叠组含 Hooks/Tools/System 合计条数）', () => {
      render(<RecordStream {...streamProps({ records: mixed })} />);
      expect(screen.getByTestId('lens-all').textContent).toContain('5');
      expect(screen.getByTestId('lens-talk').textContent).toContain('2');
      const inspectToggle = screen.getByTestId('lens-inspect-toggle');
      expect(inspectToggle.textContent).toContain('Inspect');
      expect(inspectToggle.textContent).toContain('3');
      fireEvent.click(inspectToggle);
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

    it('展开 Inspect 并挑一档就只剩那一档', () => {
      render(<RecordStream {...streamProps({ records: mixed })} />);
      fireEvent.click(screen.getByTestId('lens-inspect-toggle'));
      fireEvent.click(screen.getByTestId('lens-hook'));
      expect(screen.getByTestId('hook-inject')).toBeTruthy();
      expect(screen.queryByText('开工')).toBeNull();
      expect(screen.queryByText('好的')).toBeNull();
    });

    it('一条记录都没有时不摆镜头——没有可挑的', () => {
      render(<RecordStream {...streamProps({ records: [] })} />);
      expect(screen.queryByTestId('stream-lens')).toBeNull();
    });

    it('档位条右侧展示紧凑模型与当前 Context 读数，累计总量收入 title 悬停提示', () => {
      render(
        <RecordStream
          {...streamProps({
            records: mixed,
            usage: { model: 'gemini-4-argon-medium', context: 15_200, total: 28_400 },
          })}
        />
      );
      expect(screen.queryByTestId('stream-lens-usage')).toBeNull();
      const lensUsage = screen.getByTestId('lens-usage');
      expect(lensUsage.textContent).toBe('gemini-4-argon-medium · 上下文 15k');
      expect(lensUsage.getAttribute('title')).toContain('15,200');
      expect(lensUsage.getAttribute('title')).toContain('累计 28k');
    });

    it('档位条主行收敛为 进展 / Talk / All，Hooks/Tools/System 收进 Inspect 折叠组并支持展开收起', () => {
      render(<RecordStream {...streamProps({ records: mixed })} />);
      expect(screen.queryByTestId('lens-executor-label')).toBeNull();
      expect(screen.getByTestId('lens-watcher').textContent).toContain('进展');
      expect(screen.getByTestId('lens-talk').textContent).toContain('对话');
      expect(screen.getByTestId('lens-all').textContent).toContain('全部');
      expect(screen.queryByTestId('lens-hook')).toBeNull();

      fireEvent.click(screen.getByTestId('lens-inspect-toggle'));
      expect(screen.getByTestId('lens-inspect-group')).toBeTruthy();
      expect(screen.getByTestId('lens-hook')).toBeTruthy();
      expect(screen.getByTestId('lens-tool')).toBeTruthy();
      expect(screen.getByTestId('lens-system')).toBeTruthy();

      fireEvent.click(screen.getByTestId('lens-inspect-close'));
      expect(screen.queryByTestId('lens-inspect-group')).toBeNull();
      expect(screen.getByTestId('lens-inspect-toggle')).toBeTruthy();

      expect(normalizeStreamLensParam('progress')).toEqual({ lens: 'talk', progressOpen: true });
      expect(normalizeStreamLensParam('watcher')).toEqual({ lens: 'talk', progressOpen: true });
      expect(normalizeStreamLensParam('all')).toEqual({ lens: 'all', progressOpen: false });
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
      // Talk 计数只计真实可见的对话气泡（u1 与 a1 共 2 条），不把折叠进聚合行的 5 条 thinking 算进去
      expect(screen.getByTestId('lens-talk').textContent).toContain('2');
    });

    it('Talk 视图下当首屏满 200 条但筛入 Talk 不足 40 条气泡或视口未填满且 hasOlder=true 时，自动调用 onLoadOlder 补页，且内容容器贴底向上排列', () => {
      const onLoadOlder = vi.fn();
      const sparsePage = Array.from({ length: 200 }, (_, i) =>
        record({
          id: `sp-${i}`,
          seq: 158 + i,
          kind: i < 25 ? 'agent.say' : 'tool.call',
          payload: i < 25 ? { text: `回复 ${i}` } : { tool_name: 'Bash', args: {} },
        })
      );
      render(
        <RecordStream
          {...streamProps({
            records: sparsePage,
            hasOlder: true,
            onLoadOlder,
          })}
        />
      );
      expect(screen.getByTestId('lens-talk').textContent).toContain('25');
      expect(onLoadOlder).toHaveBeenCalledTimes(1);
      const contentBox = screen.getByTestId('record-stream-content');
      expect(contentBox.className).toContain('min-h-full');
      expect(contentBox.className).toContain('justify-end');
    });

    it('切入 Watcher 时滚回顶部，从 Watcher 切回 Talk / All 时滚动区与 Minimap 滑块立即沉底', () => {
      const origClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
      Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
        configurable: true,
        get(this: HTMLElement) {
          if (this.getAttribute?.('data-testid') === 'stream-minimap') return 400;
          if (this.getAttribute?.('data-testid') === 'record-stream-scroll') return 800;
          return 0;
        },
      });
      try {
        const onLoadOlder = vi.fn();
        render(
          <RecordStream
            {...streamProps({
              records: mixed,
              minimap: true,
              hasOlder: true,
              onLoadOlder,
            })}
          />
        );
        const scroller = screen.getByTestId('record-stream-scroll') as HTMLDivElement;
        Object.defineProperty(scroller, 'scrollHeight', { value: 2000, configurable: true });

        // 1. 切入 Watcher：scrollTop 置为 0，在 Watcher 内滚动不误触 onLoadOlder
        fireEvent.click(screen.getByTestId('lens-watcher'));
        expect(scroller.scrollTop).toBe(0);
        onLoadOlder.mockClear();
        fireEvent.scroll(scroller);
        expect(onLoadOlder).not.toHaveBeenCalled();

        // 2. 从 Watcher 切回对话（Talk）：scrollTop 立即沉底，Minimap 滑块位于轨道底部 (400 - 160 = 240)
        fireEvent.click(screen.getByTestId('lens-talk'));
        expect(scroller.scrollTop).toBe(2000);
        const thumbTalk = screen.getByTestId('stream-minimap-thumb');
        expect(parseFloat(thumbTalk.style.top)).toBeGreaterThan(0);
        expect(parseFloat(thumbTalk.style.top) + parseFloat(thumbTalk.style.height)).toBeCloseTo(400, 1);

        // 3. 再次进 Watcher 后切回全部（All）：scrollTop 与 Minimap 滑块同样立即沉底
        fireEvent.click(screen.getByTestId('lens-watcher'));
        expect(scroller.scrollTop).toBe(0);
        fireEvent.click(screen.getByTestId('lens-all'));
        expect(scroller.scrollTop).toBe(2000);
        const thumbAll = screen.getByTestId('stream-minimap-thumb');
        expect(parseFloat(thumbAll.style.top)).toBeGreaterThan(0);
        expect(parseFloat(thumbAll.style.top) + parseFloat(thumbAll.style.height)).toBeCloseTo(400, 1);
      } finally {
        if (origClientHeight) {
          Object.defineProperty(HTMLElement.prototype, 'clientHeight', origClientHeight);
        } else {
          delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientHeight;
        }
      }
    });

    it('Watcher 视图渲染三段式汇报 Table（态势锚点卡 + 事项总控表 + 里程碑表）并支持 Talk 折叠与内联决策卡交互', () => {
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
          tasks: [
            {
              id: 'T1',
              proposed_at: 1_753_800_000_000,
              title: '梳理 Watcher 信息结构',
              status: 'waiting',
              actor: '主会话 · CoreAgent',
              conclusion: '已完成 `RecordStream.tsx` 改造，待拍板方案',
            },
          ],
          runs: [
            {
              id: 'run-1',
              run_id: 1,
              task_id: 'T1',
              actor: '主会话 · CoreAgent',
              at: 1_753_800_005_000,
              cursor_from: 0,
              cursor_to: 4,
              phase_goal: '结构重塑与决策确认',
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
      expect(screen.getByTestId('watcher-anchor-card')).toBeTruthy();
      expect(screen.getByTestId('watcher-anchor-card').textContent).not.toContain('WATCHER ·');
      expect(screen.getByTestId('watcher-anchor-card').textContent).toContain('PROGRESS LEDGER');
      expect(screen.getByTestId('watcher-stat-pills').textContent).toContain('待拍板 1');
      expect(screen.getByTestId('watcher-goal-anchor').textContent).toContain('梳理信息结构');
      expect(screen.getByTestId('watcher-current-state').textContent).toContain(
        '已完成代码改造，等待选择信息结构'
      );
      expect(screen.getByTestId('watcher-decision-banner').textContent).toContain(
        'Observer 信息结构采用哪种组织方式？'
      );

      const tasksTable = screen.getByTestId('watcher-tasks-table');
      expect(tasksTable.textContent).toContain('T1');
      expect(tasksTable.textContent).toContain('梳理 Watcher 信息结构');
      expect(tasksTable.querySelector('code')?.textContent).toBe('RecordStream.tsx');

      const milestonesTable = screen.getByTestId('watcher-milestones-table');
      const runRow = screen.getByTestId('watcher-run-1');
      expect(runRow.textContent).toContain('#1');
      expect(runRow.textContent).toContain('主会话 · CoreAgent');
      expect(milestonesTable.textContent).toContain('结构重塑与决策确认');
      expect(milestonesTable.textContent).toContain('完成了 Watcher 与 Talk 改造');

      // Watcher 视图下不渲染跳到底部浮钮
      expect(screen.queryByTestId('jump-to-latest')).toBeNull();

      // Talk 默认折叠，但决策卡在 watcher-card-slot 中原样展示且可直接选择发送
      const toggle = screen.getByTestId('watcher-talk-toggle-1');
      expect(toggle.getAttribute('aria-expanded')).toBe('false');
      expect(screen.queryByTestId('watcher-talk-body-1')).toBeNull();
      expect(screen.getByTestId('watcher-card-slot')).toBeTruthy();
      expect(screen.getByTestId('decision-card')).toBeTruthy();

      fireEvent.click(screen.getAllByTestId('decision-option')[1]);
      expect(answer).not.toHaveBeenCalled();
      fireEvent.click(screen.getByTestId('decision-answer'));
      expect(answer).toHaveBeenCalledTimes(1);

      // 点击展开包裹的 Talk，展示内部对话
      fireEvent.click(toggle);
      expect(toggle.getAttribute('aria-expanded')).toBe('true');
      expect(screen.getByTestId('watcher-talk-body-1')).toBeTruthy();
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
      const toggle = screen.getByTestId('watcher-talk-toggle-1');
      expect(toggle.textContent).toContain('1条提问');
      expect(toggle.textContent).toContain('1条回复');

      // 游标 2 之后尚未总结的新对话排布在顶部锚点卡下方、总控表与里程碑表之前，不掉到页面最底部
      expect(screen.getByTestId('watcher-run-1')).toBeTruthy();
      expect(screen.queryByTestId('watcher-run-2')).toBeNull();
      const anchor = screen.getByTestId('watcher-anchor-card');
      const tail = screen.getByTestId('watcher-unsummarized-tail');
      const tasksTable = screen.getByTestId('watcher-tasks-table');
      const milestonesTable = screen.getByTestId('watcher-milestones-table');
      expect(anchor.compareDocumentPosition(tail) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(tail.compareDocumentPosition(tasksTable) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(tail.compareDocumentPosition(milestonesTable) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(tail.innerHTML).toContain('max-h-[360px]');
      expect(tail.textContent).toContain('浮动按钮上的L和数字是什么含义？');
      expect(tail.textContent).toContain('L是行号的缩写，代表起始行号到结束行号。');
    });

    it('Watcher 在无 tasks 字段时自动从 runs 合成总控事项，且 Talk 切片计数随中英语言切换', async () => {
      const recordsForI18n = [
        record({ id: 'u1', seq: 0, kind: 'user.say', payload: { text: '第一段目标。第二段目标？' } }),
        record({ id: 'tc1', seq: 1, kind: 'tool.call', payload: { tool_name: 'Read', args: {} } }),
        record({ id: 'a1', seq: 2, kind: 'agent.say', payload: { text: '已完成检查' } }),
      ];
      const observerView: SessionObserverView = {
        state: {
          bound: true,
          anchor: '第一段目标。第二段目标？',
          tail: { kind: 'now', text: '正在检查 `RecordStream.tsx` 排版。' },
          decision: '请选择排版方案',
          happened: [
            '人在写入前新增检查项：先核对本轮改动是否越出用户原话，再查本地成例。',
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
              phase_goal: '排版核对',
              tail: { kind: 'now', text: '正在检查 `RecordStream.tsx` 排版。' },
              happened_add: [
                '人在写入前新增检查项：先核对本轮改动是否越出用户原话，再查本地成例。',
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

      // 未给 tasks 时自动从 runs 合成 T1，且待拍板条幅存在
      expect(screen.getByTestId('watcher-tasks-table').textContent).toContain('T1');
      expect(screen.getByTestId('watcher-decision-banner').textContent).toContain('请选择排版方案');
      expect(screen.getByTestId('watcher-talk-toggle-1').textContent).toContain('1条提问 · 1次工具调用 · 1条回复');

      // 切换到英文状态：Talk 切片计数词条切换为英文
      await act(async () => {
        await i18n.changeLanguage('en');
      });
      rerender(<RecordStream {...streamProps({ records: recordsForI18n, observer: observerView })} />);
      expect(screen.getByTestId('watcher-talk-toggle-1').textContent).toContain('1 prompts · 1 tool calls · 1 replies');

      await act(async () => {
        await i18n.changeLanguage('zh');
      });
    });

    it('Watcher「② 阶段里程碑追加记录」按 #N → #1 倒序置顶渲染，新增里程碑自动排首行且 Talk 切片与原始批次号精确绑定零串行', () => {
      const recs = [
        record({ id: 'u1', seq: 0, kind: 'user.say', payload: { text: '第1轮提问：初始化环境' } }),
        record({ id: 'a1', seq: 1, kind: 'agent.say', payload: { text: '第1轮答复：环境已就绪' } }),
        record({ id: 'u2', seq: 2, kind: 'user.say', payload: { text: '第2轮提问：排查接口超时' } }),
        record({ id: 'a2', seq: 3, kind: 'agent.say', payload: { text: '第2轮答复：已定位连接池瓶颈' } }),
        record({ id: 'u3', seq: 4, kind: 'user.say', payload: { text: '第3轮提问：验证修复补丁' } }),
        record({ id: 'a3', seq: 5, kind: 'agent.say', payload: { text: '第3轮答复：回归测试全绿' } }),
        record({ id: 'u4', seq: 6, kind: 'user.say', payload: { text: '第4轮提问：收尾归档' } }),
        record({ id: 'a4', seq: 7, kind: 'agent.say', payload: { text: '第4轮答复：文档与产物已归档' } }),
      ];
      const baseRuns = [
        {
          id: 'run-1',
          run_id: 1,
          task_id: 'T1',
          actor: '主会话',
          at: 1_753_800_001_000,
          cursor_from: 0,
          cursor_to: 2,
          phase_goal: '初始化',
          tail: { kind: 'output' as const, text: '完成环境检查' },
          happened_add: ['完成环境检查'],
          decision: '',
          summary: '完成环境检查',
        },
        {
          id: 'run-2',
          run_id: 2,
          task_id: 'T2',
          actor: 'Worker-A',
          at: 1_753_800_002_000,
          cursor_from: 2,
          cursor_to: 4,
          phase_goal: '排查超时',
          tail: { kind: 'output' as const, text: '定位连接池瓶颈' },
          happened_add: ['定位连接池瓶颈'],
          decision: '',
          summary: '定位连接池瓶颈',
        },
        {
          id: 'run-3',
          run_id: 3,
          task_id: 'T3',
          actor: '主会话',
          at: 1_753_800_003_000,
          cursor_from: 4,
          cursor_to: 6,
          phase_goal: '验证修复',
          tail: { kind: 'output' as const, text: '回归测试全绿' },
          happened_add: ['回归测试全绿'],
          decision: '',
          summary: '回归测试全绿',
        },
      ];
      const makeObserver = (runs: typeof baseRuns): SessionObserverView => ({
        state: {
          bound: true,
          anchor: '全链路排查与修复',
          tail: runs[runs.length - 1].tail,
          decision: '',
          happened: runs.flatMap((r) => r.happened_add),
          updated_at: runs[runs.length - 1].at,
          model: 'deepseek-v4-flash',
          status: 'ok',
          status_detail: null,
          runs,
        },
        loading: false,
        error: null,
      });

      const { rerender } = render(
        <RecordStream {...streamProps({ records: recs.slice(0, 6), observer: makeObserver(baseRuns) })} />
      );
      fireEvent.click(screen.getByTestId('lens-watcher'));

      const table = screen.getByTestId('watcher-milestones-table');
      expect(table.textContent).toContain('已追加 3 轮 · 最新置顶');
      const rowIds = [...table.querySelectorAll('tbody tr.w-run-row')].map((el) =>
        el.getAttribute('data-testid')
      );
      expect(rowIds).toEqual(['watcher-run-3', 'watcher-run-2', 'watcher-run-1']);
      expect(screen.getByTestId('watcher-run-3').textContent).toContain('#3');
      expect(screen.getByTestId('watcher-run-1').textContent).toContain('#1');

      // 点击顶行 #3 展开，只展示第 3 轮对话，不与 #1 串行
      fireEvent.click(screen.getByTestId('watcher-talk-toggle-3'));
      const body3 = screen.getByTestId('watcher-talk-body-3');
      expect(body3.textContent).toContain('第3轮答复：回归测试全绿');
      expect(body3.textContent).not.toContain('第1轮答复');
      expect(screen.getByTestId('watcher-run-3').nextElementSibling?.contains(body3)).toBe(true);

      // 点击底行 #1 展开，只展示第 1 轮对话
      fireEvent.click(screen.getByTestId('watcher-talk-toggle-1'));
      const body1 = screen.getByTestId('watcher-talk-body-1');
      expect(body1.textContent).toContain('第1轮答复：环境已就绪');
      expect(body1.textContent).not.toContain('第3轮答复');
      expect(screen.getByTestId('watcher-run-1').nextElementSibling?.contains(body1)).toBe(true);

      // 追加第 4 轮到数组末尾：#4 自动置顶为首行，且已展开的 #3/#1 状态保持绑定原始切片零错位
      const runs4 = [
        ...baseRuns,
        {
          id: 'run-4',
          run_id: 4,
          task_id: 'T4',
          actor: '主会话',
          at: 1_753_800_004_000,
          cursor_from: 6,
          cursor_to: 8,
          phase_goal: '归档收尾',
          tail: { kind: 'output' as const, text: '文档与产物已归档' },
          happened_add: ['文档与产物已归档'],
          decision: '',
          summary: '文档与产物已归档',
        },
      ];
      rerender(
        <RecordStream {...streamProps({ records: recs, observer: makeObserver(runs4) })} />
      );
      expect(table.textContent).toContain('已追加 4 轮 · 最新置顶');
      const updatedRowIds = [...table.querySelectorAll('tbody tr.w-run-row')].map((el) =>
        el.getAttribute('data-testid')
      );
      expect(updatedRowIds).toEqual([
        'watcher-run-4',
        'watcher-run-3',
        'watcher-run-2',
        'watcher-run-1',
      ]);
      expect(screen.getByTestId('watcher-talk-body-3').textContent).toContain('第3轮答复：回归测试全绿');
      expect(screen.getByTestId('watcher-talk-body-1').textContent).toContain('第1轮答复：环境已就绪');
    });

    it('PROGRESS LEDGER 自动剥离系统脚手架噪音，长任务书默认紧凑折叠并支持展开全文/收起及切会话重置', () => {
      const longTaskPrompt = [
        '<image name=[Image #1] path="/Users/frago/.frago/webui_uploads/s1/shot.png"></image>',
        '<frago-employee id="frago-developer" title="frago Developer" kernel="claude">',
        '岗位：frago Developer',
        '</frago-employee>',
        '',
        '# 任务书：会话详情页 PROGRESS LEDGER 高度优化',
        '',
        '## 1. 背景与现象',
        '当 prompt 很长或给 worker 派发长任务书时，顶部 Goal Anchor 原样渲染整篇长文导致卡片高度暴涨，下方事项总控表被挤出首屏。',
        '',
        '## 2. 交付要求',
        '- 剥离系统注入脚手架路径与内部指令。',
        '- 限制默认展示高度，并提供平滑的展开全文与收起交互。',
        '',
        '[附带图片，请用读文件的工具逐一打开查看]:',
        '/Users/frago/.frago/webui_uploads/s1/shot.png',
      ].join('\n');

      const longRecords = [
        record({ id: 'u1', seq: 0, kind: 'user.say', payload: { text: longTaskPrompt } }),
        record({ id: 'a1', seq: 1, kind: 'agent.say', payload: { text: '已开始定位并改造' } }),
      ];

      const observerWithLongAnchor: SessionObserverView = {
        state: {
          bound: true,
          anchor: longTaskPrompt,
          tail: { kind: 'now', text: '正在编写前端紧凑折叠交互' },
          decision: '',
          happened: ['已完成链路定位'],
          updated_at: 1_753_800_005_000,
          model: 'deepseek-v4-flash',
          status: 'ok',
          status_detail: null,
          runs: [
            {
              id: 'run-1',
              run_id: 1,
              task_id: 'T1',
              actor: '主会话',
              at: 1_753_800_005_000,
              cursor_from: 0,
              cursor_to: 2,
              phase_goal: 'PROGRESS LEDGER 优化',
              tail: { kind: 'now', text: '正在编写前端紧凑折叠交互' },
              happened_add: ['已完成链路定位'],
              decision: '',
              summary: '正在编写前端紧凑折叠交互',
            },
          ],
        },
        loading: false,
        error: null,
      };

      const { rerender } = render(
        <RecordStream
          {...streamProps({ sessionId: 'ses-long-1', records: longRecords, observer: observerWithLongAnchor })}
        />
      );
      fireEvent.click(screen.getByTestId('lens-watcher'));

      const anchorBox = screen.getByTestId('watcher-goal-anchor');
      const anchorTextEl = screen.getByTestId('watcher-goal-anchor-text');
      const toggleBtn = screen.getByTestId('watcher-goal-anchor-toggle');

      // 1. 剥离了系统注入脚手架与附带图片路径
      expect(anchorBox.textContent).not.toContain('附带图片');
      expect(anchorBox.textContent).not.toContain('webui_uploads');
      expect(anchorBox.textContent).not.toContain('frago-employee');

      // 2. 默认处于紧凑折叠态，展示提炼标题与目标，且右侧短 Current State 不出现展开按钮
      expect(anchorTextEl.getAttribute('data-clamped')).toBe('true');
      expect(anchorTextEl.className).toContain('is-clamped');
      expect(anchorTextEl.textContent).toContain('任务书：会话详情页 PROGRESS LEDGER 高度优化');
      expect(toggleBtn.getAttribute('aria-expanded')).toBe('false');
      expect(toggleBtn.textContent).toContain('展开全文');
      expect(screen.queryByTestId('watcher-current-state-toggle')).toBeNull();

      // 3. 点击「展开全文」展示完整干净任务书原文
      fireEvent.click(toggleBtn);
      expect(toggleBtn.getAttribute('aria-expanded')).toBe('true');
      expect(toggleBtn.textContent).toContain('收起');
      expect(anchorTextEl.getAttribute('data-clamped')).toBe('false');
      expect(anchorTextEl.className).toContain('is-expanded');
      expect(anchorTextEl.textContent).toContain('限制默认展示高度，并提供平滑的展开全文与收起交互');
      expect(anchorTextEl.textContent).not.toContain('附带图片');

      // 4. 切换到新会话时自动复位折叠态
      rerender(
        <RecordStream
          {...streamProps({ sessionId: 'ses-long-2', records: longRecords, observer: observerWithLongAnchor })}
        />
      );
      expect(screen.getByTestId('watcher-goal-anchor-toggle').getAttribute('aria-expanded')).toBe('false');
      expect(screen.getByTestId('watcher-goal-anchor-text').getAttribute('data-clamped')).toBe('true');

      // 5. 再点击展开、然后点击收起还原
      fireEvent.click(screen.getByTestId('watcher-goal-anchor-toggle'));
      expect(screen.getByTestId('watcher-goal-anchor-toggle').getAttribute('aria-expanded')).toBe('true');
      fireEvent.click(screen.getByTestId('watcher-goal-anchor-toggle'));
      expect(screen.getByTestId('watcher-goal-anchor-toggle').getAttribute('aria-expanded')).toBe('false');
      expect(screen.getByTestId('watcher-goal-anchor-text').getAttribute('data-clamped')).toBe('true');
    });

    it('事项全为 done 且待拍板 0 时忽略过期 decision，且无真实交互决策卡时不渲染虚假「定位决策卡 ↓」按钮', () => {
      const recsNoCard = [
        record({ id: 'u1', seq: 0, kind: 'user.say', payload: { text: '优化输入区布局' } }),
        record({ id: 'a1', seq: 1, kind: 'agent.say', payload: { text: '已上线并在 8093 验证。' } }),
      ];
      const staleObserver: SessionObserverView = {
        state: {
          bound: true,
          anchor: '优化输入区布局',
          tail: { kind: 'output', text: 'Composer 改造已在 8093 上线，亮暗双主题实拍已归档。' },
          decision: '需等待前端视觉主审 ui-designer 返回细节',
          happened: ['Composer 改造上线'],
          updated_at: 1_753_800_005_000,
          model: 'minimax-m3.1-flash',
          status: 'ok',
          status_detail: null,
          tasks: [
            {
              id: 'T4',
              proposed_at: 1_753_800_000_000,
              title: '优化输入区非输入状态布局视觉',
              status: 'done',
              actor: '研发工作会话',
              conclusion: 'Composer 胶囊态已上线',
            },
          ],
          runs: [
            {
              id: 'run-1',
              run_id: 1,
              task_id: 'T4',
              actor: '研发工作会话',
              at: 1_753_800_005_000,
              cursor_from: 0,
              cursor_to: 2,
              phase_goal: '优化输入区',
              tail: { kind: 'output', text: 'Composer 改造已在 8093 上线' },
              happened_add: ['Composer 改造上线'],
              decision: '需等待前端视觉主审 ui-designer 返回细节',
              summary: 'Composer 改造已在 8093 上线',
            },
          ],
        },
        loading: false,
        error: null,
      };

      const { rerender } = render(
        <RecordStream {...streamProps({ sessionId: 'ses-stale-1', records: recsNoCard, observer: staleObserver })} />
      );
      fireEvent.click(screen.getByTestId('lens-watcher'));

      // 1. 待拍板 0 + 已办结 1：状态为 Completed，不显示 Waiting decision 与虚假横幅/定位按钮
      expect(screen.getByTestId('watcher-stat-pills').textContent).toContain('待拍板 0');
      expect(screen.getByTestId('watcher-stat-pills').textContent).toContain('已办结 1');
      expect(screen.getByTestId('watcher-current-state').textContent).toContain('Completed');
      expect(screen.getByTestId('watcher-current-state').textContent).not.toContain('Waiting decision');
      expect(screen.queryByTestId('watcher-decision-banner')).toBeNull();
      expect(screen.queryByText('定位决策卡 ↓')).toBeNull();

      // 2. 即使存在 waiting 事项与文本提问，但流里并无真实交互决策卡组件时，只显示提示横幅而不出现虚假「定位决策卡 ↓」
      const textOnlyWaitingObserver: SessionObserverView = {
        ...staleObserver,
        state: {
          ...staleObserver.state!,
          tasks: [
            {
              ...staleObserver.state!.tasks![0],
              status: 'waiting',
            },
          ],
          decision: '请问是否确认直接发布？',
        },
      };
      rerender(
        <RecordStream
          {...streamProps({ sessionId: 'ses-stale-1', records: recsNoCard, observer: textOnlyWaitingObserver })}
        />
      );
      expect(screen.getByTestId('watcher-decision-banner').textContent).toContain('请问是否确认直接发布？');
      expect(screen.queryByText('定位决策卡 ↓')).toBeNull();
    });

    it('长会话 Progress 视图下早期条目未加载时自动触发 onLoadOlder 补齐历史记录，且真实无对话条目禁用展开避免渲染空框', () => {
      // 模拟长会话首屏只加载了尾部 seq 325..326，而早期条目 #48 位于 [322, 325)、#47 位于 [320, 322)（全量历史中也无记录）
      const tailOnlyRecords = [
        record({ id: 'u-tail', seq: 325, kind: 'user.say', payload: { text: '启动 Batch 1 修复' } }),
        record({ id: 'a-tail', seq: 326, kind: 'agent.say', payload: { text: '正在检索同类 E2E 门禁先例' } }),
      ];
      const earlyAndTailRecords = [
        record({ id: 't-48', seq: 322, kind: 'agent.think', payload: { text: '思考批次拆分' } }),
        record({ id: 'a-48', seq: 323, kind: 'agent.say', payload: { text: '24 张纯 PIN Issue 已拆为 5 大批' } }),
        ...tailOnlyRecords,
      ];
      const longObserver: SessionObserverView = {
        state: {
          bound: true,
          anchor: '分析并分批修复 PIN Issue',
          tail: { kind: 'now', text: '正在检索同类 E2E 门禁先例' },
          decision: '',
          happened: ['24 张纯 PIN Issue 已拆为 5 大批'],
          updated_at: 1_753_800_005_000,
          model: 'gpt-6.4',
          status: 'ok',
          status_detail: null,
          runs: [
            {
              id: 'run-47',
              run_id: 47,
              task_id: 'T4',
              actor: '主会话',
              at: 1_753_800_001_000,
              cursor_from: 320,
              cursor_to: 322,
              phase_goal: '按问题性质分组并逐批修复 PIN Issue',
              tail: { kind: 'now', text: '准备生成确认卡' },
              happened_add: [],
              decision: '',
              summary: '准备生成确认卡',
            },
            {
              id: 'run-48',
              run_id: 48,
              task_id: 'T4',
              actor: '主会话',
              at: 1_753_800_002_000,
              cursor_from: 322,
              cursor_to: 325,
              phase_goal: '按问题性质分组并逐批修复 PIN Issue',
              tail: { kind: 'output', text: '24 张纯 PIN Issue 已拆为 5 大批' },
              happened_add: ['24 张纯 PIN Issue 已拆为 5 大批'],
              decision: '',
              summary: '24 张纯 PIN Issue 已拆为 5 大批',
            },
            {
              id: 'run-49',
              run_id: 49,
              task_id: 'T4',
              actor: '主会话',
              at: 1_753_800_003_000,
              cursor_from: 325,
              cursor_to: 327,
              phase_goal: '从 Batch 1 修复并验证 APEXP-4591',
              tail: { kind: 'now', text: '正在检索同类 E2E 门禁先例' },
              happened_add: ['首批修复顺序已拍板'],
              decision: '',
              summary: '正在检索同类 E2E 门禁先例',
            },
          ],
        },
        loading: false,
        error: null,
      };

      const onLoadOlder = vi.fn();
      const { rerender } = render(
        <RecordStream
          {...streamProps({
            sessionId: 'ses-long-progress',
            records: tailOnlyRecords,
            hasOlder: true,
            loadingOlder: false,
            onLoadOlder,
            observer: longObserver,
          })}
        />
      );

      // 切换到 Progress 视图：由于 earliestWatcherSeq(320) < records[0].seq(325) 且 hasOlder=true，自动触发 onLoadOlder
      fireEvent.click(screen.getByTestId('lens-watcher'));
      expect(onLoadOlder).toHaveBeenCalledTimes(1);

      // 历史尚未补齐前，#48 显示「正在加载早期记录…」而非误导性的「暂无对话记录」
      const toggle48Before = screen.getByTestId('watcher-talk-toggle-48') as HTMLButtonElement;
      expect(toggle48Before.textContent).toContain('正在加载早期记录');
      expect(toggle48Before.disabled).toBe(false);

      // 若用户在补齐完成前点击展开 #48，展开区显示 loading 指示器而非空黑框
      fireEvent.click(toggle48Before);
      expect(screen.getByTestId('watcher-talk-loading-48')).toBeTruthy();

      // 模拟历史记录补齐完成（hasOlder=false，earlyAndTailRecords 已加载）
      rerender(
        <RecordStream
          {...streamProps({
            sessionId: 'ses-long-progress',
            records: earlyAndTailRecords,
            hasOlder: false,
            loadingOlder: false,
            onLoadOlder,
            observer: longObserver,
          })}
        />
      );

      // #48 自动更新为「1次thinking · 1条回复」，且已展开区域渲染出真实的早期对话内容
      const toggle48After = screen.getByTestId('watcher-talk-toggle-48') as HTMLButtonElement;
      expect(toggle48After.textContent).toContain('1次thinking · 1条回复');
      expect(screen.queryByTestId('watcher-talk-loading-48')).toBeNull();
      expect(screen.getByTestId('watcher-talk-body-48').textContent).toContain(
        '24 张纯 PIN Issue 已拆为 5 大批'
      );

      // #47 在全量历史记录下确实无任何对话记录：按钮显示「暂无对话记录」且为 disabled，点击不会展开空框
      const toggle47 = screen.getByTestId('watcher-talk-toggle-47') as HTMLButtonElement;
      expect(toggle47.textContent).toContain('暂无对话记录');
      expect(toggle47.disabled).toBe(true);
      fireEvent.click(toggle47);
      expect(screen.queryByTestId('watcher-talk-body-47')).toBeNull();
    });

    it('Progress 视图切换会话时等待 records 与 observer 均落定后再一次成型渲染，且后台 loadingOlder 不在顶部插条也不触发 scrollTop 补偿', () => {
      const sessionARecords = [
        record({ id: 'a-u1', seq: 0, kind: 'user.say', payload: { text: '会话A目标' } }),
        record({ id: 'a-a1', seq: 1, kind: 'agent.say', payload: { text: '会话A回复' } }),
      ];
      const sessionAObserver: SessionObserverView = {
        state: {
          bound: true,
          anchor: '会话A目标',
          tail: { kind: 'output', text: '会话A完成' },
          decision: '',
          happened: ['会话A完成'],
          updated_at: 1_753_800_001_000,
          model: 'gpt-6.4',
          status: 'ok',
          status_detail: null,
          runs: [
            {
              id: 'run-a1',
              run_id: 1,
              task_id: 'T1',
              actor: '主会话',
              at: 1_753_800_001_000,
              cursor_from: 0,
              cursor_to: 2,
              phase_goal: '会话A阶段',
              tail: { kind: 'output', text: '会话A完成' },
              happened_add: ['会话A完成'],
              decision: '',
              summary: '会话A完成',
            },
          ],
        },
        loading: false,
        error: null,
      };
      const sessionBRecords = [
        record({ id: 'b-u2', seq: 2, kind: 'user.say', payload: { text: '会话B后续提问' } }),
        record({ id: 'b-a2', seq: 3, kind: 'agent.say', payload: { text: '会话B后续回复' } }),
      ];
      const sessionBAllRecords = [
        record({ id: 'b-u1', seq: 0, kind: 'user.say', payload: { text: '会话B首轮提问' } }),
        record({ id: 'b-a1', seq: 1, kind: 'agent.say', payload: { text: '会话B首轮回复' } }),
        ...sessionBRecords,
      ];
      const sessionBObserver: SessionObserverView = {
        state: {
          bound: true,
          anchor: '会话B总目标',
          tail: { kind: 'output', text: '会话B阶段进展' },
          decision: '',
          happened: ['会话B阶段进展'],
          updated_at: 1_753_800_002_000,
          model: 'gpt-6.4',
          status: 'ok',
          status_detail: null,
          runs: [
            {
              id: 'run-b1',
              run_id: 1,
              task_id: 'T1',
              actor: '主会话',
              at: 1_753_800_002_000,
              cursor_from: 0,
              cursor_to: 2,
              phase_goal: '会话B首轮',
              tail: { kind: 'output', text: '会话B首轮完成' },
              happened_add: ['会话B首轮完成'],
              decision: '',
              summary: '会话B首轮完成',
            },
            {
              id: 'run-b2',
              run_id: 2,
              task_id: 'T1',
              actor: '主会话',
              at: 1_753_800_003_000,
              cursor_from: 2,
              cursor_to: 4,
              phase_goal: '会话B次轮',
              tail: { kind: 'output', text: '会话B次轮完成' },
              happened_add: ['会话B次轮完成'],
              decision: '',
              summary: '会话B次轮完成',
            },
          ],
        },
        loading: false,
        error: null,
      };

      const { rerender } = render(
        <RecordStream
          {...streamProps({
            sessionId: 'ses-A',
            records: sessionARecords,
            observer: sessionAObserver,
          })}
        />
      );
      fireEvent.click(screen.getByTestId('lens-watcher'));
      expect(screen.getByTestId('watcher-anchor-card').textContent).toContain('会话A目标');

      // 模拟用户曾滚动浏览，scrollTop 非 0
      const scroller = screen.getByTestId('record-stream-scroll') as HTMLDivElement;
      Object.defineProperty(scroller, 'scrollHeight', { value: 2400, configurable: true });
      scroller.scrollTop = 320;

      // 1. 切到会话 B：records 已先到达，但 observer 仍在 loading，绝不抢跑渲染回退版 watcher-unsummarized-tail 或空表
      rerender(
        <RecordStream
          {...streamProps({
            sessionId: 'ses-B',
            records: sessionBRecords,
            loading: false,
            observer: { state: null, loading: true, error: null },
          })}
        />
      );
      expect(scroller.scrollTop).toBe(0);
      expect(screen.getByTestId('record-stream-loading')).toBeTruthy();
      expect(screen.queryByTestId('stream-lens')).toBeNull();
      expect(screen.queryByTestId('watcher-view')).toBeNull();
      expect(screen.queryByTestId('watcher-unsummarized-tail')).toBeNull();

      // 2. 换另一种时序：observer 先到达，但 records 仍在首取 loading，同样不抢跑渲染无镜头栏/无里程碑的半截 Progress
      rerender(
        <RecordStream
          {...streamProps({
            sessionId: 'ses-B',
            records: [],
            loading: true,
            observer: sessionBObserver,
          })}
        />
      );
      expect(screen.getByTestId('record-stream-loading')).toBeTruthy();
      expect(screen.queryByTestId('stream-lens')).toBeNull();
      expect(screen.queryByTestId('watcher-view')).toBeNull();

      // 3. records 与 observer 均落定（同时后台 loadingOlder=true 正在补齐早期记录）：
      //    同帧一次性出现 stream-lens 与完整 watcher-view，且顶部绝不出现「正在加载更早记录」挤压行
      rerender(
        <RecordStream
          {...streamProps({
            sessionId: 'ses-B',
            records: sessionBRecords,
            loading: false,
            loadingOlder: true,
            hasOlder: true,
            observer: sessionBObserver,
          })}
        />
      );
      expect(screen.queryByTestId('record-stream-loading')).toBeNull();
      expect(screen.getByTestId('stream-lens')).toBeTruthy();
      expect(screen.getByTestId('watcher-view')).toBeTruthy();
      expect(screen.getByTestId('watcher-anchor-card').textContent).toContain('会话B总目标');
      expect(screen.queryByText('正在加载更早记录…')).toBeNull();
      expect(scroller.scrollTop).toBe(0);

      // 4. 后台早期页前插合并后，Progress 视图 scrollTop 依然保持为 0（不触发正序流 prepend scrollTop 补偿）
      rerender(
        <RecordStream
          {...streamProps({
            sessionId: 'ses-B',
            records: sessionBAllRecords,
            loading: false,
            loadingOlder: false,
            hasOlder: false,
            observer: sessionBObserver,
          })}
        />
      );
      expect(scroller.scrollTop).toBe(0);
      expect(screen.getByTestId('watcher-talk-toggle-1').textContent).toContain('1条提问 · 1条回复');
    });

    it('事项总控表 · Tasks Overview 长列表默认折叠已完结 Tx、展示渐变预览提示，支持展开/收起且轮询刷新不重置状态', () => {
      const mkTask = (
        id: string,
        status: 'done' | 'doing' | 'waiting' | 'blocked',
        title: string
      ) => ({
        id,
        proposed_at: 1_753_800_000_000,
        title,
        status,
        actor: status === 'done' ? 'worker-old' : '主会话',
        conclusion: `${id} 进展结论`,
      });

      const baseRecords = [
        record({ id: 'u-task', seq: 0, kind: 'user.say', payload: { text: '推进多阶段任务' } }),
        record({ id: 'a-task', seq: 1, kind: 'agent.say', payload: { text: '正在执行中' } }),
      ];

      const makeObserver = (tasks: ReturnType<typeof mkTask>[], updatedAt = 1_753_800_010_000): SessionObserverView => ({
        state: {
          bound: true,
          anchor: '推进多阶段任务',
          tail: { kind: 'now', text: '正在执行 T6' },
          decision: '',
          happened: ['已完成 T1-T5'],
          updated_at: updatedAt,
          model: 'deepseek-v4-flash',
          status: 'ok',
          status_detail: null,
          tasks,
          runs: [
            {
              id: 'run-1',
              run_id: 1,
              task_id: tasks[tasks.length - 1]?.id || 'T1',
              actor: '主会话',
              at: updatedAt,
              cursor_from: 0,
              cursor_to: 2,
              phase_goal: '多阶段持续推进',
              tail: { kind: 'now', text: '正在执行 T6' },
              happened_add: ['已完成 T1-T5'],
              decision: '',
              summary: '正在执行 T6',
            },
          ],
        },
        loading: false,
        error: null,
      });

      const initialTasks = [
        mkTask('T1', 'done', '初始化仓库结构'),
        mkTask('T2', 'done', '梳理接口契约'),
        mkTask('T3', 'done', '完成数据层校验'),
        mkTask('T4', 'done', '接入路由和鉴权'),
        mkTask('T5', 'done', '补充后端单测'),
        mkTask('T6', 'doing', '实现前端折叠与渐变提示'),
        mkTask('T7', 'waiting', '待主人拍板最终视觉细节'),
      ];

      const { rerender } = render(
        <RecordStream
          {...streamProps({
            sessionId: 'ses-tasks-fold-1',
            records: baseRecords,
            observer: makeObserver(initialTasks),
          })}
        />
      );
      fireEvent.click(screen.getByTestId('lens-watcher'));

      // 1. 初始化默认折叠：T1–T5 隐藏，仅 T6、T7 主行可见，顶部出现渐变预览行 T5 与展开按钮
      expect(screen.queryByTestId('watcher-task-row-T1')).toBeNull();
      expect(screen.queryByTestId('watcher-task-row-T5')).toBeNull();
      expect(screen.getByTestId('watcher-task-row-T6')).toBeTruthy();
      expect(screen.getByTestId('watcher-task-row-T7')).toBeTruthy();

      const peekRow = screen.getByTestId('watcher-tasks-peek-row');
      expect(peekRow.textContent).toContain('T5');
      expect(peekRow.textContent).toContain('补充后端单测');

      const foldRow = screen.getByTestId('watcher-tasks-fold-row');
      expect(foldRow.textContent).toContain('已自动折叠 5 项已完结旧事项 (T1–T5)');
      const foldToggle = screen.getByTestId('watcher-tasks-fold-toggle');
      expect(foldToggle.getAttribute('aria-expanded')).toBe('false');

      // 2. 点击展开：完整显示 T1..T7，按钮变为「收起已完结」
      fireEvent.click(foldToggle);
      expect(screen.getByTestId('watcher-tasks-fold-toggle').getAttribute('aria-expanded')).toBe('true');
      expect(screen.queryByTestId('watcher-tasks-peek-row')).toBeNull();
      expect(screen.getByTestId('watcher-task-row-T1')).toBeTruthy();
      expect(screen.getByTestId('watcher-task-row-T5')).toBeTruthy();
      expect(screen.getByTestId('watcher-task-row-T6')).toBeTruthy();
      expect(screen.getByTestId('watcher-task-row-T7')).toBeTruthy();

      // 3. 模拟后台 Progress 每 15 秒轮询推送更新（updated_at 与任务进度变化）：用户手动展开态保持稳定不被重置
      const polledTasks = [
        ...initialTasks.slice(0, 5),
        mkTask('T6', 'done', '实现前端折叠与渐变提示'),
        mkTask('T7', 'doing', '补全验证与截图交付'),
      ];
      rerender(
        <RecordStream
          {...streamProps({
            sessionId: 'ses-tasks-fold-1',
            records: baseRecords,
            observer: makeObserver(polledTasks, 1_753_800_025_000),
          })}
        />
      );
      expect(screen.getByTestId('watcher-tasks-fold-toggle').getAttribute('aria-expanded')).toBe('true');
      expect(screen.getByTestId('watcher-task-row-T1')).toBeTruthy();
      expect(screen.getByTestId('watcher-task-row-T6')).toBeTruthy();
      expect(screen.getByTestId('watcher-task-row-T7')).toBeTruthy();

      // 4. 切换到另一场全完结的长列表会话：新会话默认自动折叠，且全完结兜底保留最近 2 条 (T4, T5) 可见
      const allDoneTasks = [
        mkTask('T1', 'done', '已完成阶段1'),
        mkTask('T2', 'done', '已完成阶段2'),
        mkTask('T3', 'done', '已完成阶段3'),
        mkTask('T4', 'done', '已完成阶段4'),
        mkTask('T5', 'done', '已完成阶段5'),
      ];
      rerender(
        <RecordStream
          {...streamProps({
            sessionId: 'ses-tasks-fold-all-done',
            records: baseRecords,
            observer: makeObserver(allDoneTasks, 1_753_800_030_000),
          })}
        />
      );
      expect(screen.getByTestId('watcher-tasks-fold-toggle').getAttribute('aria-expanded')).toBe('false');
      expect(screen.getByTestId('watcher-tasks-fold-row').textContent).toContain('已自动折叠 3 项已完结旧事项 (T1–T3)');
      expect(screen.getByTestId('watcher-tasks-peek-row').textContent).toContain('T3');
      expect(screen.queryByTestId('watcher-task-row-T1')).toBeNull();
      expect(screen.getByTestId('watcher-task-row-T4')).toBeTruthy();
      expect(screen.getByTestId('watcher-task-row-T5')).toBeTruthy();

      // 5. 切回第一场会话后仍保留之前的展开记忆，且支持再次点击收起
      rerender(
        <RecordStream
          {...streamProps({
            sessionId: 'ses-tasks-fold-1',
            records: baseRecords,
            observer: makeObserver(polledTasks, 1_753_800_025_000),
          })}
        />
      );
      expect(screen.getByTestId('watcher-tasks-fold-toggle').getAttribute('aria-expanded')).toBe('true');
      fireEvent.click(screen.getByTestId('watcher-tasks-fold-toggle'));
      expect(screen.getByTestId('watcher-tasks-fold-toggle').getAttribute('aria-expanded')).toBe('false');
      expect(screen.queryByTestId('watcher-task-row-T1')).toBeNull();
      expect(screen.getByTestId('watcher-task-row-T7')).toBeTruthy();
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

  it('底部汇总为单行静默总数，完整各家分布收进 title 悬停提示，只有已经发生的绝对数', () => {
    const { container } = render(
      <TestRail state={railState()} selectedId={null} onSelect={NOOP} />
    );
    const foot = screen.getByTestId('rail-foot');
    expect(foot.textContent).toContain('累计 2 场会话');
    expect(foot.getAttribute('title')).toContain('共 2 场');
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
    // 整行换底加整圈描边与微阴影（--sel-bg / --sel-border / --sel-shadow），状态由整行承担。
    expect(className).toContain('bg-[var(--sel-bg)]');
    expect(className).toContain('var(--sel-border)');
    expect(className).toContain('var(--sel-shadow)');
    expect(className).not.toContain('accent-primary');
    // 真正的禁令：任何单边色条都不许出现。
    expect(className).not.toMatch(/border-[lrtb]-\d/);
    expect(className).not.toMatch(/\bborder-[lrtb]\b/);
  });

  it('组容器下沉为暗托盘、组间距拉开到 14px，未选中分支卡与选中项样式层级分明', () => {
    const rows = [
      session({ session_id: 'solo-0', title: '独立会话 0' }),
      session({ session_id: 'parent-1', title: '主会话 1' }),
      session({
        session_id: 'branch-1',
        title: '分支会话 1',
        parent_session_id: 'parent-1',
        relation: { kind: 'branch', closed: false },
      }),
      session({ session_id: 'parent-2', title: '主会话 2' }),
      session({
        session_id: 'branch-2',
        title: '分支会话 2',
        parent_session_id: 'parent-2',
        relation: { kind: 'branch', closed: false },
      }),
    ];
    const { container } = render(
      <TestRail
        state={railState({ sessions: rows, visible: rows, todaySessions: rows })}
        selectedId="branch-1"
        onSelect={NOOP}
      />
    );
    const heads = container.querySelectorAll('[data-branch-pos="head"]');
    const tails = container.querySelectorAll('[data-branch-pos="tail"]');
    expect(heads).toHaveLength(2);
    expect(tails).toHaveLength(2);
    // 第一个组头跟在普通独立卡片后面，补 pt-3（12px + 上一行 2px = 14px）；第二个组头紧跟上一组尾（已有 h-3.5 = 14px），不再重复叠加
    expect(heads[0].className).toContain('pt-3');
    expect(heads[1].className).not.toContain('pt-3');
    // 组容器采用下沉暗托盘 --grp-bg 与淡描边 --grp-border，组内卡片间距为 pb-[5px]
    expect(heads[0].firstElementChild?.className).toContain('bg-[var(--grp-bg)]');
    expect(heads[0].firstElementChild?.className).toContain('border-[var(--grp-border)]');
    expect(heads[0].firstElementChild?.firstElementChild?.className).toContain('pb-[5px]');
    // 每个分支组尾部留 14px（h-3.5）组间距
    const gaps = screen.getAllByTestId('group-gap');
    expect(gaps).toHaveLength(2);
    for (const g of gaps) {
      expect(g.className).toContain('h-3.5');
    }
    const items = screen.getAllByTestId('session-item');
    // 组内主次：源头父卡浮起在暗槽之上（实色底 + 整圈细描边），派生分支子卡退到暗槽底
    const root1 = items.find((el) => el.textContent?.includes('主会话 1'))!;
    const root2 = items.find((el) => el.textContent?.includes('主会话 2'))!;
    for (const root of [root1, root2]) {
      expect(root.getAttribute('data-branch-root')).toBe('true');
      expect(root.className).toContain('bg-[var(--grp-card-bg)]');
      expect(root.className).toContain('var(--grp-card-border)');
    }
    // 选中的分支卡整卡换品牌绿底与整圈描边；未选中的分支卡落在暗槽底、不画凸起盒、左缩进 14px、标题降半档字重
    const selectedBranch = items.find((el) => el.textContent?.includes('分支会话 1'))!;
    const unselectedBranch = items.find((el) => el.textContent?.includes('分支会话 2'))!;
    expect(selectedBranch.getAttribute('data-branch-card')).toBe('true');
    expect(selectedBranch.className).toContain('bg-[var(--sel-bg)]');
    expect(selectedBranch.className).toContain('var(--sel-border)');
    expect(selectedBranch.className).toContain('var(--sel-shadow)');
    expect(unselectedBranch.getAttribute('data-branch-card')).toBe('true');
    expect(unselectedBranch.className).toContain('bg-[var(--branch-card-bg)]');
    expect(unselectedBranch.className).not.toContain('inset_0_0_0_1px_var(--branch-card-border)');
    expect(unselectedBranch.className).toContain('pl-[14px]');
    const unselectedTitle = unselectedBranch.querySelector('[data-testid=session-title]')!;
    expect(unselectedTitle.className).toContain('font-medium');
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

  it('顶栏扩为 All / Needs Decision / Callback Backlog / Running 四档筛选，告警档带 .warn-chip', () => {
    render(<TestRail state={railState()} selectedId={null} onSelect={NOOP} />);
    const ids = screen
      .getAllByTestId(/^list-filter-/)
      .map((el) => el.getAttribute('data-testid'));
    expect(ids).toEqual([
      'list-filter-all',
      'list-filter-decision',
      'list-filter-backlog',
      'list-filter-running',
    ]);
    expect(screen.getByTestId('list-filter-decision').className).toContain('warn-chip');
    expect(screen.getByTestId('list-filter-backlog').className).toContain('warn-chip');
    expect(screen.getByTestId('list-filter-running').className).not.toContain('warn-chip');
    expect(screen.queryByTestId(/^status-filter-/)).toBeNull();
  });

  it('员工入口创建的会话在卡片上方展示对应 Employee 颜色色带与员工名字，普通会话不展示', () => {
    const rows = [
      session({
        session_id: 'emp-session-1',
        title: '获取腾讯接口的所有标准板块并分析波动率',
        employee_id: 'stock',
        employee_title: 'Stock 投研与策略专员',
        employee_color: 'amber',
      }),
      session({
        session_id: 'normal-session-1',
        title: '普通会话',
        employee_id: null,
      }),
    ];
    render(
      <TestRail
        state={railState({ sessions: rows, visible: rows, todaySessions: rows })}
        selectedId={null}
        onSelect={NOOP}
      />
    );
    const items = screen.getAllByTestId('session-item');
    expect(items[0].getAttribute('data-employee')).toBe('stock');
    expect(items[0].getAttribute('data-emp-color')).toBe('amber');
    expect(items[1].getAttribute('data-employee')).toBeNull();
    expect(items[1].getAttribute('data-emp-color')).toBeNull();

    const bars = screen.getAllByTestId('session-employee');
    expect(bars).toHaveLength(1);
    expect(bars[0].getAttribute('data-employee-id')).toBe('stock');
    expect(bars[0].className).toContain('si-emp-bar');
    expect(bars[0].textContent).toBe('Stock 投研与策略专员');

    // 已带员工顶栏的卡片不重复渲染 Employee 来源胶囊；常态 Completed 生命周期也不画徽标；非常态 Running 才画生命周期徽标
    expect(items[0].querySelector('[data-testid="session-origin"]')).toBeNull();
    expect(items[0].querySelector('[data-testid="session-lifecycle"]')).toBeNull();
    expect(items[0].querySelector('[data-testid="session-badges"]')).toBeNull();
    expect(items[1].querySelector('[data-testid="session-origin"]')).toBeNull();
    expect(items[1].querySelector('[data-testid="session-badges"]')).toBeNull();
  });


  it('每一档带实时计数角标（All / Needs Decision / Callback Backlog / Running）', () => {
    const rows = [
      session({ session_id: 's-wait', title: '等待拍板' }),
      session({ session_id: 's-run', title: '运行中', status: 'running' }),
      session({ session_id: 's-cb', title: '回传积压' }),
    ];
    render(
      <TestRail
        state={railState({ sessions: rows, visible: rows, todaySessions: rows })}
        selectedId={null}
        onSelect={NOOP}
        decisionCardOf={(id) => (id === 's-wait' ? '选 A 还是 B？' : null)}
        callbackSessionIds={new Set(['s-cb'])}
      />
    );
    expect(screen.getByTestId('list-filter-all').textContent).toContain('3');
    expect(screen.getByTestId('list-filter-decision').textContent).toContain('1');
    expect(screen.getByTestId('list-filter-backlog').textContent).toContain('1');
    expect(screen.getByTestId('list-filter-running').textContent).toContain('1');
  });

  it('点 Needs Decision 切出待决策列表并同步 setFilter，点 Callback Backlog / Running 各自过滤', () => {
    const setFilter = vi.fn();
    const rows = [
      session({ session_id: 's-wait', title: '待拍板会话' }),
      session({ session_id: 's-run', title: '执行中会话', status: 'running' }),
      session({ session_id: 's-cb', title: '积压回传会话' }),
    ];
    render(
      <TestRail
        state={railState({ sessions: rows, visible: rows, todaySessions: rows, setFilter })}
        selectedId={null}
        onSelect={NOOP}
        decisionCardOf={(id) => (id === 's-wait' ? '请确认？' : null)}
        callbackSessionIds={new Set(['s-cb'])}
      />
    );
    fireEvent.click(screen.getByTestId('list-filter-decision'));
    expect(setFilter).toHaveBeenCalledWith('for-you');
    expect(screen.getAllByTestId('session-title').map((el) => el.textContent)).toEqual(['待拍板会话']);

    fireEvent.click(screen.getByTestId('list-filter-backlog'));
    expect(screen.getAllByTestId('session-title').map((el) => el.textContent)).toEqual(['积压回传会话']);

    fireEvent.click(screen.getByTestId('list-filter-running'));
    expect(screen.getAllByTestId('session-title').map((el) => el.textContent)).toEqual(['执行中会话']);
  });

  it('主会话派发了运行中子 Worker 时显示 Running 且计入「运行中」，绝不误报 Waiting decision / For you', () => {
    const parent = session({
      session_id: 's-parent',
      title: '主会话派发中',
      status: 'done',
      has_running_worker: true,
      need_decision: false,
    });
    const worker = session({
      session_id: 'core_w1',
      title: '子 Worker 执行中',
      origin: 'worker',
      parent_session_id: 's-parent',
      relation: { kind: 'dispatch', closed: false },
      status: 'running',
    });
    const cbParent = session({
      session_id: 's-cb-parent',
      title: '等待回调回传会话',
      status: 'done',
      callback_queued: true,
      need_decision: false,
    });
    const plainDone = session({
      session_id: 's-plain',
      title: '普通已完结会话',
      status: 'done',
      need_decision: false,
    });
    const rows = [parent, worker, cbParent, plainDone];

    render(
      <TestRail
        state={railState({ sessions: rows, visible: rows, todaySessions: rows })}
        selectedId={null}
        onSelect={NOOP}
      />
    );

    expect(screen.getByTestId('list-filter-decision').textContent).toContain('0');
    expect(screen.getByTestId('list-filter-backlog').textContent).toContain('1');
    expect(screen.getByTestId('list-filter-running').textContent).toContain('2');

    const items = screen.getAllByTestId('session-item');
    const parentItem = items.find((el) => el.textContent?.includes('主会话派发中'))!;
    expect(parentItem.querySelector('[data-testid="session-lifecycle"]')?.textContent).toContain('Running');
    expect(parentItem.querySelector('[data-testid="session-lifecycle"]')?.textContent).not.toContain(
      'Waiting decision'
    );
    expect(parentItem.getAttribute('data-for-you')).toBeNull();

    const cbItem = items.find((el) => el.textContent?.includes('等待回调回传会话'))!;
    expect(cbItem.querySelector('[data-testid="session-lifecycle"]')?.textContent).toContain('Callback queued');

    const plainItem = items.find((el) => el.textContent?.includes('普通已完结会话'))!;
    expect(plainItem.querySelector('[data-testid="session-lifecycle"]')).toBeNull();
  });

  it('标题上方遵循塔夫特常态静默：仅非默认来源与非常态生命周期才渲染 .si-badges，常态 Direct+Completed 完全静默，仍不暴露摘要预览行', () => {
    const one = session({
      session_id: SID,
      status: 'error',
      digest_done: '把镜头判断追加进了 verdict.jsonl',
      digest_stuck: 'API Error: 连接中断',
    });
    const pairSession = session({
      session_id: 'pair-1',
      title: 'Paired session · Alice',
      origin: 'pair' as WorkbenchSession['origin'],
      status: 'running',
    });
    const cronSession = session({
      session_id: 'cron-1',
      title: 'Schedule daily sync',
      origin: 'schedule' as WorkbenchSession['origin'],
      status: 'done',
    });
    const quietSession = session({
      session_id: 'quiet-1',
      title: 'Normal finished session',
      origin: 'human' as WorkbenchSession['origin'],
      status: 'done',
    });
    const rows = [one, pairSession, cronSession, quietSession];
    const { rerender } = render(
      <TestRail
        state={railState({ sessions: rows, visible: rows, todaySessions: rows })}
        selectedId={null}
        onSelect={NOOP}
      />
    );
    // schedule 来源会话收进独立可折叠「定时任务」分组
    const schedulesHeader = screen.getByTestId('schedules-header');
    expect(schedulesHeader.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByText('Schedule daily sync')).toBeNull();

    // 选中定时任务会话重新挂载时自动展开该分组（兼容 jsdom 中未 mock Virtuoso 的初始窗口渲染）
    rerender(
      <TestRail
        key="cron-expanded"
        state={railState({ sessions: rows, visible: rows, todaySessions: rows })}
        selectedId="cron-1"
        onSelect={NOOP}
      />
    );

    const items = screen.getAllByTestId('session-item');
    const oneItem = items.find((el) => el.textContent?.includes(one.title))!;
    const pairItem = items.find((el) => el.textContent?.includes('Paired session · Alice'))!;
    const cronItem = items.find((el) => el.textContent?.includes('Schedule daily sync'))!;
    const quietItem = items.find((el) => el.textContent?.includes('Normal finished session'))!;

    expect(oneItem.querySelector('[data-testid=session-preview]')).toBeNull();
    // human 默认来源静默，但 Error 属于非常态生命周期正常渲染
    expect(oneItem.querySelector('[data-testid=session-origin]')).toBeNull();
    expect(oneItem.querySelector('[data-testid=session-lifecycle]')?.textContent).toBe('Error');
    expect(oneItem.querySelector('[data-testid=session-lifecycle]')?.className).toContain('text-accent-error');
    // Pair + Running 双显
    expect(pairItem.querySelector('[data-testid=session-origin]')?.textContent).toBe('Pair');
    expect(pairItem.querySelector('[data-testid=session-lifecycle]')?.textContent).toBe('Running');
    // Cron 非常态来源渲染，但 Completed 静默
    expect(cronItem.querySelector('[data-testid=session-origin]')?.textContent).toBe('Cron');
    expect(cronItem.querySelector('[data-testid=session-lifecycle]')).toBeNull();
    // Normal Direct + Completed 整行 .si-badges 容器不渲染
    expect(quietItem.querySelector('[data-testid=session-badges]')).toBeNull();
    expect(oneItem.textContent).not.toContain('verdict.jsonl');

    expect(
      sessionOriginOf(session({ session_id: 'hook-1', origin: 'hook' as WorkbenchSession['origin'], title: 'pre-commit hook' }))
    ).toBe('hook');
    expect(sessionLifecycleOf(session({ session_id: 'cb-1' }), { callbackQueued: true })).toEqual({
      key: 'callback',
      label: 'Callback queued',
    });
  });

  it('不恢复旧版「等你决策」旧筛选命名', () => {
    const { container } = render(
      <TestRail state={railState()} selectedId={null} onSelect={NOOP} />
    );
    const text = container.textContent ?? '';
    expect(text).not.toContain('等你');
    expect(text).not.toContain('待决策');
    expect(screen.queryByTestId('status-filter-waiting')).toBeNull();
  });

  it('搜索那一行只是入口：点它打开全站的搜会话浮窗，清单不跟着筛', () => {
    act(() => {
      useUIStore.getState().setSessionSearchOpen(false);
    });
    render(<TestRail state={railState()} selectedId={null} onSelect={NOOP} />);
    expect(screen.queryByRole('textbox', { name: '搜会话' })).toBeNull();
    fireEvent.click(screen.getByTestId('session-search-trigger'));
    expect(useUIStore.getState().sessionSearchOpen).toBe(true);
    act(() => {
      useUIStore.getState().setSessionSearchOpen(false);
    });
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
    expect(card.textContent).toContain('发送中');
    expect(card.querySelector('p')).toBeNull();
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

describe('ReportPanel 右栏（纯 Stack 模式）', () => {
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

  it('没选会话时显示 Stack 标题与引导，不出现右栏 Observer', () => {
    const { container } = render(<ReportBody sessionId={null} view={view(null)} />);
    expect(screen.getByText('暂存')).toBeTruthy();
    expect(screen.getByText(/选一场会话/)).toBeTruthy();
    expect(container.querySelector('.obs-panel')).toBeNull();
    expect(screen.queryByTestId('observer-panel')).toBeNull();
    expect(screen.queryByTestId('observer-four-stage')).toBeNull();
    expect(screen.queryByTestId('observer-pending-jump')).toBeNull();
  });

  it('选中会话时右栏仅渲染纯 Stack 容器，不再重复渲染四段式 Observer', () => {
    const { container } = render(
      <ReportBody
        sessionId="s1"
        view={view({ decision: '待决问题' })}
        lower={<div data-testid="pure-stack">暂存列表内容</div>}
      />,
    );
    expect(screen.getByTestId('report-lower')).toBeTruthy();
    expect(screen.getByTestId('pure-stack')).toBeTruthy();
    expect(container.querySelector('.obs-panel')).toBeNull();
    expect(screen.queryByTestId('observer-panel')).toBeNull();
    expect(screen.queryByTestId('observer-four-stage')).toBeNull();
    expect(screen.queryByTestId('observer-pending-jump')).toBeNull();
  });

  it('jumpToPendingCard 可定位待拍板决策卡并触发 flash-focus', () => {
    const dcard = document.createElement('div');
    dcard.className = 'dcard is-pending';
    dcard.scrollIntoView = vi.fn();
    document.body.appendChild(dcard);
    try {
      expect(jumpToPendingCard()).toBe(true);
      expect(dcard.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'center' });
      expect(dcard.classList.contains('flash-focus')).toBe(true);
    } finally {
      dcard.remove();
    }
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

  it('挂着右侧缩略滚动条时滚动容器保留 pr-10 右侧安全间距，避免用户消息卡片外圆角与滚动条区域重叠', () => {
    render(
      <RecordStream
        {...props({
          minimap: true,
          records: [rec({ id: 'u-pad', seq: 1, kind: 'user.say', payload: { text: '检查右缘安全间距' } })],
        })}
      />
    );
    const scroller = screen.getByTestId('record-stream-scroll');
    expect(scroller.className).toContain('pr-10');
    expect(scroller.className).not.toContain('pr-6');
  });
});

