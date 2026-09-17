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

import { beforeAll, describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import RecordCard, { KIND_GROUP, formatBytes, formatDuration } from '../RecordCard';
import { RECORD_KINDS, type RecordKind, type WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import i18n from '@/i18n';

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
  'usage.tick': {
    context_tokens: 179064,
    context_window: null,
    turn_tokens: 181841,
    total_tokens: 2193569,
    breakdown: { input: 2, output: 538, cache_creation: 1052, cache_read: 180249 },
    model: 'claude-opus-5',
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

describe('RecordCard 的十六种形态', () => {
  it('形态清单恰好十六种，且分组穷尽不重叠', () => {
    expect(RECORD_KINDS).toHaveLength(16);
    expect(new Set(RECORD_KINDS).size).toBe(16);
    expect(Object.keys(KIND_GROUP).sort()).toEqual([...RECORD_KINDS].sort());
    const counts = { text: 0, tool: 0, system: 0 };
    for (const kind of RECORD_KINDS) counts[KIND_GROUP[kind]] += 1;
    expect(counts).toEqual({ text: 4, tool: 6, system: 6 });
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

describe('旁路注入卡', () => {
  function hookRecord(payload: Record<string, unknown> = {}): WorkbenchRecord {
    return makeRecord('context.inject', {
      payload: {
        channel: 'hook',
        source: 'hook',
        hook_event: 'PreToolUse',
        hook_target: 'Bash',
        label: 'PreToolUse:Bash',
        blocks: ['第一条规则', '第二条规则'],
        body: '第一条规则\n\n第二条规则',
        ...payload,
      },
    });
  }

  it('自成一格，且默认就摊开——旁路塞进来的话不该藏在折叠里', () => {
    render(<RecordCard record={hookRecord()} sessionId={SID} />);
    expect(screen.getByTestId('hook-inject')).toBeTruthy();
    expect(screen.getByText('第一条规则')).toBeTruthy();
    expect(screen.getByText('第二条规则')).toBeTruthy();
  });

  it('说人话，不把 PreToolUse 这种机器名摆给人看', () => {
    render(<RecordCard record={hookRecord()} sessionId={SID} />);
    expect(screen.getByText(/动手之前塞进来的/)).toBeTruthy();
    expect(screen.getByText('Bash')).toBeTruthy();
  });

  it('段界保留：两个 hook 各说一句，跟一个 hook 说很长一句是两回事', () => {
    const { container } = render(<RecordCard record={hookRecord()} sessionId={SID} />);
    expect(screen.getByText('2 段')).toBeTruthy();
    expect(container.querySelector('[data-source="hook"]')).not.toBeNull();
  });

  it('hook 挂了要看得见', () => {
    render(
      <RecordCard
        record={hookRecord({ exit_code: 2, stderr: '起不来', blocks: [], body: '' })}
        sessionId={SID}
      />
    );
    expect(screen.getByText('退出码 2')).toBeTruthy();
    expect(screen.getByText('起不来')).toBeTruthy();
    expect(screen.getByText('这次 hook 一个字都没说')).toBeTruthy();
  });

  it('不是 hook 来的注入照旧走通用那张卡', () => {
    render(
      <RecordCard
        record={makeRecord('context.inject', {
          payload: { channel: 'engine', source: 'engine', label: '引擎注入', body: '正文' },
        })}
        sessionId={SID}
      />
    );
    expect(screen.queryByTestId('hook-inject')).toBeNull();
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
  it('十六种形态全渲染出来，文本里搜不到百分比与 X 比 Y 计数，也没有进度条', () => {
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

describe('思考卡', () => {
  it('正文没落盘的思考只占一行，不撑成一张空盒子', () => {
    render(
      <RecordCard
        record={makeRecord('agent.think', { payload: { text: '' } })}
        sessionId={SID}
      />
    );
    expect(screen.getByTestId('think-empty')).toBeTruthy();
    expect(screen.getByText('思考了一轮，正文没落盘')).toBeTruthy();
  });

  it('有正文的思考照旧可折叠', () => {
    render(<RecordCard record={makeRecord('agent.think')} sessionId={SID} />);
    expect(screen.queryByTestId('think-empty')).toBeNull();
  });
});

describe('顶着「你说」出现的那几种机器记事', () => {
  it('斜杠命令把命令摆成徽标，正文只留人打的那段参数', () => {
    const args = '在 webui 添加一个 todo 的添加按钮，用户只需要填描述，剩下的交给 agent';
    render(
      <RecordCard
        record={makeRecord('user.say', {
          payload: { text: args, command: '/goal', input_mode: 'slash-command', images: [] },
        })}
        sessionId={SID}
      />
    );
    expect(screen.getByTestId('user-command').textContent).toBe('/goal');
    expect(screen.getByText(args)).toBeTruthy();
    // 尖括号包装一个字都不许露给人看。
    expect(document.body.textContent).not.toContain('command-args');
  });

  it('参数是一个取值时跟命令连成一句，不拆成两行两种字号', () => {
    // 人打的是 `/model Opus`，一句话。拆开会读成"命令是 /model，然后我说了一句 Opus"。
    render(
      <RecordCard
        record={makeRecord('user.say', {
          payload: { text: 'Opus', command: '/model', input_mode: 'slash-command', images: [] },
        })}
        sessionId={SID}
      />
    );
    expect(screen.getByTestId('user-command').textContent).toBe('/model Opus');
  });

  it('参数是一整段任务书时才拆开，不把它挤进徽标', () => {
    const long = '按分析的结论，完成接口的实现并在本机完成 e2e 测试。';
    render(
      <RecordCard
        record={makeRecord('user.say', {
          payload: { text: long, command: '/goal', input_mode: 'slash-command', images: [] },
        })}
        sessionId={SID}
      />
    );
    expect(screen.getByTestId('user-command').textContent).toBe('/goal');
    expect(screen.getByText(long)).toBeTruthy();
  });

  it('参数带换行就一律拆开，再短也不连排', () => {
    render(
      <RecordCard
        record={makeRecord('user.say', {
          payload: { text: '完成：\n迁移', command: '/goal', input_mode: 'slash-command', images: [] },
        })}
        sessionId={SID}
      />
    );
    expect(screen.getByTestId('user-command').textContent).toBe('/goal');
  });

  it('叹号直跑的命令没有另外的正文，不摆一句「正文为空」', () => {
    render(
      <RecordCard
        record={makeRecord('user.say', {
          payload: { text: '', command: 'uv run frago server restart', input_mode: 'bash-command', images: [] },
        })}
        sessionId={SID}
      />
    );
    expect(screen.getByTestId('user-command').textContent).toBe('uv run frago server restart');
    expect(screen.queryByText('（正文为空）')).toBeNull();
  });

  it('打字是常态，不在卡上标输入方式', () => {
    render(
      <RecordCard
        record={makeRecord('user.say', {
          payload: { text: '把日历挪到底部', input_mode: 'typed', images: [] },
        })}
        sessionId={SID}
      />
    );
    expect(document.body.textContent).not.toContain('typed');
    expect(document.body.textContent).not.toContain('输入方式');
  });

  it('引擎追加在句尾的提醒折起来，不混进人写的那段话', async () => {
    const { container } = render(
      <RecordCard
        record={makeRecord('user.say', {
          payload: {
            text: '把扫描改成只读',
            reminders: ['执行 Python MUST 用 uv run。'],
            images: [],
          },
        })}
        sessionId={SID}
      />
    );
    expect(screen.getByTestId('user-reminders')).toBeTruthy();
    // 折着的时候提醒的正文不在页面上，人读到的就是自己写的那一句。
    expect(container.textContent).not.toContain('uv run');
  });

  it('后台任务通知读作那句摘要，不是一坨任务号', () => {
    render(
      <RecordCard
        record={makeRecord('context.inject', {
          payload: {
            channel: 'task-notification',
            source: 'task-notification',
            label: '后台任务失败',
            body: 'Background command "Render four previews" failed with exit code 143',
            task_status: 'failed',
            task_id: 'brafm2y85',
            output_file: '/tmp/tasks/brafm2y85.output',
          },
        })}
        sessionId={SID}
      />
    );
    expect(screen.getByText('后台任务')).toBeTruthy();
    expect(screen.getByText('失败')).toBeTruthy();
    expect(document.body.textContent).not.toContain('task-notification');
  });

  it('本机命令的输出走等宽块，默认折起来', () => {
    const { container } = render(
      <RecordCard
        record={makeRecord('context.inject', {
          payload: {
            channel: 'local-command-output',
            source: 'local-command',
            label: '命令输出',
            body: 'Goal set: 在 webui 添加按钮',
            stdout: 'Goal set: 在 webui 添加按钮',
            stderr: '',
          },
        })}
        sessionId={SID}
      />
    );
    expect(screen.getByText('命令输出')).toBeTruthy();
    expect(container.textContent).not.toContain('local-command-stdout');
    expect(container.textContent).not.toContain('Goal set');
  });
});

describe('用量刻度', () => {
  it('头一行只报上下文与累计，两个数都带千分位', () => {
    const { container } = render(
      <RecordCard record={makeRecord('usage.tick')} sessionId={SID} />
    );
    const text = container.textContent ?? '';
    expect(text).toContain('上下文 179,064');
    expect(text).toContain('累计 2,193,569');
    // 本轮那个数几乎总是贴着上下文走，两个并排摆会让人以为自己看重了：它收在折叠里。
    expect(text).not.toContain('181,841');
  });

  it('展开之后才是本轮与它的四项明细，零的那一项不摆', () => {
    const { container } = render(
      <RecordCard
        record={makeRecord('usage.tick', {
          payload: {
            context_tokens: 51004,
            context_window: null,
            turn_tokens: 51604,
            total_tokens: 51604,
            breakdown: { input: 4, output: 600, cache_creation: 0, cache_read: 51000 },
            model: 'claude-opus-5',
          },
        })}
        sessionId={SID}
      />
    );
    fireEvent.click(container.querySelector('button[aria-expanded]') as HTMLElement);
    // 一项一行：名目与数各占一格，数字右对齐。挤成一行要从左读到右才找得到某一项。
    const rows = [...container.querySelectorAll('dl > div')].map((row) => [
      row.querySelector('dt')?.textContent,
      row.querySelector('dd')?.textContent,
    ]);
    expect(rows).toEqual([
      ['本轮', '51,604'],
      ['入', '4'],
      ['出', '600'],
      ['缓存读', '51,000'],
    ]);
    expect(container.textContent ?? '').not.toContain('缓存写');
  });
});
