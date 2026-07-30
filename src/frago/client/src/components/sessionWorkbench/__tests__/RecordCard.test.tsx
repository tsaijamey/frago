/**
 * RecordCard 的组件测试。
 *
 * 四件事必须守住：
 *
 * 1. 十五种形态各能渲染，一种都不许崩——崩一种，那一类记录在界面上就等于没发生过。
 * 2. 报错卡不含任何取原文入口。服务端拦一道（恒 403），界面拦一道，两道都要有。
 * 3. 全域禁令：渲染结果里搜不到百分比、搜不到 X 比 Y 计数、没有进度条元素。
 * 4. 分组编号一个字都不露给人看。
 */

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import RecordCard, { KIND_GROUP, formatBytes, formatDuration } from '../RecordCard';
import { RECORD_KINDS, type RecordKind, type WorkbenchRecord } from '@/hooks/useWorkbenchRecords';

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';

/** 每种形态一份贴近真实数据的载荷。字段名与两家翻译层的产出逐字对齐。 */
const PAYLOADS: Record<RecordKind, Record<string, unknown>> = {
  'user.say': {
    text: '把会话工作台做成 React 页面',
    images: [{ media_type: 'image/png', bytes: 2048 }],
    input_mode: 'keyboard',
    is_tool_result: false,
  },
  'agent.say': { text: '已经把三栏挂进导航了。', model: 'claude-opus-5' },
  'agent.think': { text: '先确认接口返回的形状，再决定卡片怎么分组。', model: 'claude-opus-5' },
  'context.inject': {
    channel: 'engine',
    label: '引擎注入',
    body: '当前工作目录已切换。',
    exit_code: 0,
    unrecognized: false,
  },
  'tool.call': {
    call_id: 'toolu_abc',
    tool_name: 'Bash',
    tool_family: 'shell',
    args: { command: 'pnpm build', description: '跑一次构建' },
    args_unparsed: null,
  },
  'tool.result': {
    call_id: 'toolu_abc',
    tool_name: 'Bash',
    status: 'ok',
    body: 'built in two seconds',
    body_kind: 'text',
    truncation: 'none',
    truncation_ref: null,
    duration_ms: 2190,
  },
  'subagent.dispatch': {
    call_id: 'toolu_sub',
    agent_ref: 'agent-x',
    agent_type: 'Explore',
    description: '找出会话页的组件划分',
    prompt: '读一遍 claudeSessions 目录',
    status: 'completed',
    stats: { total_tokens: 8421, total_tool_use_count: 7, total_duration_ms: 41000 },
    content: '组件按列表与详情两栏切分。',
    trace_available: true,
  },
  'media.attach': {
    media_type: 'file',
    ref: '/Users/frago/Repos/frago/README.md',
    display_name: 'README.md',
    bytes: 5120,
    attachment_type: 'file',
  },
  'todo.snapshot': {
    source: 'agent-write',
    item_count: 3,
    items: [
      { content: '挂进导航', status: 'completed' },
      { content: '接中栏真数据', status: 'in_progress' },
      { content: '补组件测试', status: 'pending' },
    ],
  },
  'permission.outcome': {
    call_id: 'toolu_abc',
    tool_name: 'Bash',
    decision: 'denied',
    reason: '这条命令不在放行清单里',
    mode: 'default',
  },
  error: {
    scope: 'api',
    code: 'APIError:529',
    message: '上游暂时不可用',
  },
  interrupt: {
    target: 'msg_abc',
    phase: 'tool',
    text: '你在工具跑到一半时按了停止',
    source: 'message-error',
  },
  'context.compact': {
    trigger: 'auto',
    tokens_before: 152000,
    tokens_after: 24000,
    summary_text: '此前讨论了统一记录类型的十五种形态。',
    bridge_from: null,
  },
  'session.state': { field: 'model', from: 'claude-sonnet-5', to: 'claude-opus-5' },
  'call.envelope': {
    channel: 'step-marker',
    label: 'finish',
    phase: 'finish',
    snapshot: 'snap_abc',
    step_start_count: 2,
    step_finish_count: 2,
    paired: true,
    finish_reason: 'stop',
    tokens: { input: 1200, output: 340 },
    cost: 0.02,
    duration_ms: 8300,
    message_count: 6,
  },
};

function makeRecord(kind: RecordKind, overrides: Partial<WorkbenchRecord> = {}): WorkbenchRecord {
  return {
    id: `rec-${kind}`,
    session_id: SID,
    group_id: kind === 'user.say' ? null : 'msg_0193abcdef0123456789abcdef012345',
    seq: 0,
    ts: 1_753_800_000_000,
    kind,
    agent_path: [],
    payload: PAYLOADS[kind],
    raw_available: kind !== 'error',
    ...overrides,
  };
}

describe('RecordCard 的十五种形态', () => {
  it('形态清单恰好十五种，且分组穷尽不重叠', () => {
    expect(RECORD_KINDS).toHaveLength(15);
    expect(new Set(RECORD_KINDS).size).toBe(15);
    expect(Object.keys(KIND_GROUP).sort()).toEqual([...RECORD_KINDS].sort());
    const counts = { text: 0, tool: 0, system: 0 };
    for (const kind of RECORD_KINDS) counts[KIND_GROUP[kind]] += 1;
    expect(counts).toEqual({ text: 4, tool: 6, system: 5 });
  });

  it.each(RECORD_KINDS)('%s 能渲染，且标出自己的形态', (kind) => {
    const { container } = render(<RecordCard record={makeRecord(kind)} sessionId={SID} />);
    const node = container.querySelector(`[data-kind="${kind}"]`);
    expect(node).not.toBeNull();
    expect(node?.getAttribute('data-group')).toBe(KIND_GROUP[kind]);
  });

  it('载荷为空时照样渲染，不崩', () => {
    for (const kind of RECORD_KINDS) {
      const { container } = render(
        <RecordCard record={makeRecord(kind, { payload: {} })} sessionId={SID} />
      );
      expect(container.querySelector(`[data-kind="${kind}"]`)).not.toBeNull();
    }
  });
});

describe('报错卡', () => {
  it('只显示范围、代码、消息三项', () => {
    render(<RecordCard record={makeRecord('error')} sessionId={SID} />);
    expect(screen.getByText('范围')).toBeTruthy();
    expect(screen.getByText('代码')).toBeTruthy();
    expect(screen.getByText('消息')).toBeTruthy();
    expect(screen.getByText('APIError:529')).toBeTruthy();
  });

  it('不给任何取原文入口——按钮一个都没有', () => {
    const { container } = render(<RecordCard record={makeRecord('error')} sessionId={SID} />);
    expect(container.querySelectorAll('button')).toHaveLength(0);
    expect(screen.queryByText('取原文')).toBeNull();
    expect(screen.queryByText(/查看原文/)).toBeNull();
  });

  it('内容完整的工具结果也不挂取原文入口——没被截断就没有别处可取', () => {
    render(<RecordCard record={makeRecord('tool.result')} sessionId={SID} />);
    expect(screen.queryByText('取原文')).toBeNull();
  });

  it('被截断的工具结果才挂取原文入口', () => {
    render(
      <RecordCard
        record={makeRecord('tool.result', {
          payload: { ...PAYLOADS['tool.result'], truncation: 'clipped' },
        })}
        sessionId={SID}
      />
    );
    expect(screen.getByText('取原文')).toBeTruthy();
    expect(screen.getByText('中段内容已永久丢失')).toBeTruthy();
  });
});

describe('全域禁令', () => {
  it('十五种形态全渲染出来，文本里搜不到百分比与 X 比 Y 计数，也没有进度条', () => {
    const { container } = render(
      <>
        {RECORD_KINDS.map((kind) => (
          <RecordCard key={kind} record={makeRecord(kind)} sessionId={SID} />
        ))}
      </>
    );
    const text = container.textContent ?? '';
    expect(text.match(/\d+\s*%/g)).toBeNull();
    expect(text.match(/\d+\s*\/\s*\d+/g)).toBeNull();
    expect(container.querySelectorAll('progress, [role="progressbar"]')).toHaveLength(0);
    expect(text).not.toMatch(/预计|还需|剩余/);
  });

  it('分组编号一个字都不露', () => {
    const { container } = render(
      <>
        {RECORD_KINDS.map((kind) => (
          <RecordCard key={kind} record={makeRecord(kind)} sessionId={SID} />
        ))}
      </>
    );
    expect(container.textContent ?? '').not.toContain('msg_0193abcdef0123456789abcdef012345');
  });
});

describe('已发生的绝对数怎么写', () => {
  it('时长按已经过去的量写，没有分母', () => {
    expect(formatDuration(340)).toBe('340 毫秒');
    expect(formatDuration(2190)).toBe('2.2 秒');
    expect(formatDuration(125_000)).toBe('2 分 5 秒');
    expect(formatDuration(null)).toBe('');
  });

  it('体积按绝对量写', () => {
    expect(formatBytes(512)).toBe('512 字节');
    expect(formatBytes(5120)).toBe('5.0 KB');
    expect(formatBytes(null)).toBe('');
  });
});
