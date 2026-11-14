/**
 * useSessionQueue 单元测试：验证 [end, end-5] 轮交互卡检测、stop 轮次识别与自动注入。
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import {
  detectStopTurnId,
  hasInteractiveCardInTailTurns,
  recordHasInteractiveCard,
  segmentMainTurns,
  useSessionQueue,
} from '@/hooks/useSessionQueue';
import { loadYaml } from '@/utils/decisionBlock';

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';

const FENCE_CARD = `请确认方案：

\`\`\`answer-needed-by-human
question: 是否执行迁移？
options:
  - key: A
    label: 立即迁移
    will: 执行数据库迁移脚本
  - key: B
    label: 暂不迁移
    will: 保持现状
\`\`\``;

const ASK_JSON = JSON.stringify({
  frago_ui_component: 'decision-card',
  kind: 'single-choice',
  question: '选择回滚策略？',
  options: [
    { key: 'A', label: '全量回滚', will: '回滚全部节点' },
    { key: 'B', label: '灰度回滚', will: '仅回滚金丝雀节点' },
  ],
});

function makeRecord(
  seq: number,
  kind: WorkbenchRecord['kind'],
  payload: Record<string, unknown>,
  groupId: string | null = null,
  ts?: number
): WorkbenchRecord {
  return {
    id: `rec-${seq}`,
    session_id: SID,
    group_id: groupId,
    seq,
    // 默认步长 1 秒：正常工具流的间隔，绝不触发静默切分。要构造长静默跨段的用例显式传 ts。
    ts: ts ?? 1_700_000_000_000 + seq * 1000,
    kind,
    agent_path: [],
    payload,
    raw_available: true,
  };
}

function normalTurn(turnIdx: number, baseSeq: number): WorkbenchRecord[] {
  return [
    makeRecord(baseSeq, 'user.say', { text: `提问 ${turnIdx}` }),
    makeRecord(baseSeq + 1, 'agent.say', { text: `回复 ${turnIdx}` }, `g-${turnIdx}`),
  ];
}

beforeAll(async () => {
  await loadYaml();
});

describe('hasInteractiveCardInTailTurns (仅看最后一轮实际内容会话的交互卡检测)', () => {
  it('最后一轮无交互卡时返回 false，并识别出末尾 stop 轮次', () => {
    const records: WorkbenchRecord[] = [];
    for (let i = 0; i < 6; i += 1) {
      records.push(...normalTurn(i, i * 10));
    }
    expect(hasInteractiveCardInTailTurns(records)).toBe(false);
    expect(detectStopTurnId(records)).toBe('rec-51');
  });

  it('交互卡在最后一轮（end）时返回 true', () => {
    const records: WorkbenchRecord[] = [
      makeRecord(1, 'user.say', { text: '开始部署' }),
      makeRecord(2, 'agent.say', { text: FENCE_CARD }, 'g-card'),
    ];
    expect(segmentMainTurns(records)).toHaveLength(1);
    expect(hasInteractiveCardInTailTurns(records)).toBe(true);
  });

  it('frago ask 的 tool.result 交互卡位于最后一轮时返回 true', () => {
    const records: WorkbenchRecord[] = [
      makeRecord(1, 'user.say', { text: '怎么回滚？' }),
      makeRecord(2, 'tool.call', { tool: 'ask' }, 'g-ask'),
      makeRecord(3, 'tool.result', { status: 'ok', body: ASK_JSON }, 'g-ask'),
      makeRecord(4, 'agent.say', { text: '请点选上方卡片' }, 'g-ask'),
    ];
    expect(segmentMainTurns(records)).toHaveLength(1);
    expect(hasInteractiveCardInTailTurns(records)).toBe(true);
  });

  it('交互卡在上一轮（end-1），最后一轮已是新的实际 assistant response 文本时不再阻断', () => {
    const records: WorkbenchRecord[] = [
      makeRecord(1, 'user.say', { text: '开始部署' }),
      makeRecord(2, 'agent.say', { text: FENCE_CARD }, 'g-card'),
      ...normalTurn(1, 10),
    ];
    expect(segmentMainTurns(records)).toHaveLength(2);
    expect(hasInteractiveCardInTailTurns(records)).toBe(false);
  });

  it('末尾为空白 agent.say 时不构成实际内容轮次，仍保持上一轮交互卡阻断且不产生 stopTurnId', () => {
    const records: WorkbenchRecord[] = [
      makeRecord(1, 'user.say', { text: '开始部署' }),
      makeRecord(2, 'agent.say', { text: FENCE_CARD }, 'g-card'),
      makeRecord(3, 'user.say', { text: '追问' }),
      makeRecord(4, 'agent.say', { text: '   ' }, 'g-empty'),
    ];
    expect(segmentMainTurns(records)).toHaveLength(1);
    expect(hasInteractiveCardInTailTurns(records)).toBe(true);
    expect(detectStopTurnId(records)).toBeNull();
  });

  it('交互卡已被人类通过【answer】回复后不再阻断', () => {
    const records: WorkbenchRecord[] = [
      makeRecord(1, 'user.say', { text: '开始部署' }),
      makeRecord(2, 'agent.say', { text: FENCE_CARD }, 'g-card'),
      makeRecord(3, 'user.say', { text: '【answer】A · 立即迁移 —— 执行数据库迁移脚本' }),
      makeRecord(4, 'agent.say', { text: '已执行迁移。' }, 'g-done'),
    ];
    expect(hasInteractiveCardInTailTurns(records)).toBe(false);
  });
});

describe('命令回显里的卡片 JSON 不算待答卡片', () => {
  const CLI_ECHO_BODY = [
    'Created At: 2026-11-13T12:19:27+08:00',
    'Command exited with code 0.',
    '',
    'Command output:',
    'frago 82135 ... python -m frago.session.async_dispatch --job-file ...',
    '=== CLI VALID TEST ===',
    ASK_JSON,
  ].join('\n');

  it('复合 shell 命令回显卡片 JSON 时不阻断注入', () => {
    const records: WorkbenchRecord[] = [
      makeRecord(1, 'user.say', { text: '核验修复结果' }),
      makeRecord(
        2,
        'tool.call',
        {
          tool_name: 'run_command',
          call_id: 'c1',
          args: {
            CommandLine:
              'ls -la /tmp && echo "=== CLI VALID TEST ===" && frago app ask single-choice -q "测试"',
          },
        },
        'g-run'
      ),
      makeRecord(3, 'tool.result', { status: 'ok', call_id: 'c1', body: CLI_ECHO_BODY }, 'g-run'),
      makeRecord(4, 'agent.say', { text: '核验完成，测试全过。' }, 'g-run'),
    ];
    expect(recordHasInteractiveCard(records[2], records)).toBe(false);
    expect(hasInteractiveCardInTailTurns(records)).toBe(false);
  });

  it('独立 frago app ask 调用产出的卡片仍阻断', () => {
    const records: WorkbenchRecord[] = [
      makeRecord(1, 'user.say', { text: '怎么收尾？' }),
      makeRecord(
        2,
        'tool.call',
        {
          tool_name: 'run_command',
          call_id: 'c2',
          args: {
            CommandLine:
              'frago app ask single-choice -q "接下来如何收尾？" -o "A|提交|推送"',
          },
        },
        'g-ask2'
      ),
      makeRecord(3, 'tool.result', { status: 'ok', call_id: 'c2', body: ASK_JSON }, 'g-ask2'),
      makeRecord(4, 'agent.say', { text: '请点选上方卡片' }, 'g-ask2'),
    ];
    expect(recordHasInteractiveCard(records[2], records)).toBe(true);
    expect(hasInteractiveCardInTailTurns(records)).toBe(true);
  });

  it('带 --help 的 ask 调用不算挂卡', () => {
    const records: WorkbenchRecord[] = [
      makeRecord(1, 'user.say', { text: '看看用法' }),
      makeRecord(
        2,
        'tool.call',
        { tool_name: 'run_command', call_id: 'c3', args: { CommandLine: 'frago app ask --help' } },
        'g-help'
      ),
      makeRecord(3, 'tool.result', { status: 'ok', call_id: 'c3', body: ASK_JSON }, 'g-help'),
      makeRecord(4, 'agent.say', { text: '用法如上。' }, 'g-help'),
    ];
    expect(recordHasInteractiveCard(records[2], records)).toBe(false);
  });

  it('agent.say 代码围栏里的示例 JSON 不算待答卡片', () => {
    const records: WorkbenchRecord[] = [
      makeRecord(1, 'user.say', { text: '给我看看卡片 JSON 长什么样' }),
      makeRecord(
        2,
        'agent.say',
        { text: `示例长这样：\n\n\`\`\`json\n${ASK_JSON}\n\`\`\`\n` },
        'g-doc'
      ),
    ];
    expect(recordHasInteractiveCard(records[1], records)).toBe(false);
    expect(hasInteractiveCardInTailTurns(records)).toBe(false);
  });

  it('非围栏的组件 JSON 仍按真卡片处理', () => {
    const records: WorkbenchRecord[] = [
      makeRecord(1, 'user.say', { text: '选一个环境' }),
      makeRecord(2, 'agent.say', { text: ASK_JSON }, 'g-live'),
    ];
    expect(recordHasInteractiveCard(records[1], records)).toBe(true);
    expect(hasInteractiveCardInTailTurns(records)).toBe(true);
  });
});

describe('长单轮按静默时长与定时唤醒边界切分', () => {
  const BASE_MS = 1_700_000_000_000;

  it('早先段有卡片、跨过长静默后产生新实质回复（中间无人发言）时不再被旧卡卡死', () => {
    const records: WorkbenchRecord[] = [
      makeRecord(1, 'user.say', { text: '开始部署' }),
      makeRecord(2, 'agent.say', { text: FENCE_CARD }, 'g-old'),
      makeRecord(
        3,
        'agent.say',
        { text: '定时自查：Worker 仍在跑，继续等待。' },
        'g-new',
        BASE_MS + 10 * 60 * 1000
      ),
    ];
    expect(segmentMainTurns(records)).toHaveLength(2);
    expect(hasInteractiveCardInTailTurns(records)).toBe(false);
  });

  it('默认 1 秒步长的正常工具流不被静默阈值误切', () => {
    const records: WorkbenchRecord[] = [
      makeRecord(1, 'user.say', { text: '跑一下测试' }),
      makeRecord(2, 'tool.call', { tool_name: 'run_command' }, 'g-flow'),
      makeRecord(3, 'tool.result', { status: 'ok', body: '全部通过' }, 'g-flow'),
      makeRecord(4, 'agent.say', { text: '测试全过。' }, 'g-flow'),
    ];
    expect(segmentMainTurns(records)).toHaveLength(1);
  });

  it('卡片之后紧跟空回复不构成新轮，闸门继续拦', () => {
    const records: WorkbenchRecord[] = [
      makeRecord(1, 'user.say', { text: '开始部署' }),
      makeRecord(2, 'agent.say', { text: FENCE_CARD }, 'g-card'),
      makeRecord(3, 'agent.say', { text: '   ' }, 'g-empty', BASE_MS + 10 * 60 * 1000),
    ];
    expect(hasInteractiveCardInTailTurns(records)).toBe(true);
  });

  it('无人发言时，定时唤醒开启新一轮自查，早先轮里的卡不再锁死队列', () => {
    // 复刻事故现场的形状：同一次派发里所有记录 group_id 相同、每轮自查都有 agent.say 回复，
    // 只按 group 或只看「有没有说过话」都切不开，能切开它的只有定时唤醒这条边界。
    const records: WorkbenchRecord[] = [
      makeRecord(1, 'user.say', { text: '派发 Worker 后自查' }),
      makeRecord(
        2,
        'tool.call',
        { tool_name: 'schedule_wakeup', tool_family: 'schedule' },
        'g-same'
      ),
      makeRecord(3, 'tool.call', { tool: 'ask' }, 'g-same'),
      makeRecord(4, 'tool.result', { status: 'ok', body: ASK_JSON }, 'g-same'),
      makeRecord(5, 'agent.say', { text: '已挂好定时器，等下次自查。' }, 'g-same'),
      makeRecord(
        6,
        'tool.call',
        { tool_name: 'schedule_wakeup', tool_family: 'schedule' },
        'g-same'
      ),
      makeRecord(7, 'tool.result', { status: 'ok', body: 'Worker 仍在跑' }, 'g-same'),
      makeRecord(8, 'agent.say', { text: 'Worker 仍在跑，继续等。' }, 'g-same'),
    ];
    expect(segmentMainTurns(records)).toHaveLength(2);
    expect(hasInteractiveCardInTailTurns(records)).toBe(false);
  });

  it('真实 frago ask 卡片与同轮收尾回复仍照常拦', () => {
    const records: WorkbenchRecord[] = [
      makeRecord(1, 'user.say', { text: '怎么回滚？' }),
      makeRecord(2, 'tool.call', { tool: 'ask' }, 'g-ask'),
      makeRecord(3, 'tool.result', { status: 'ok', body: ASK_JSON }, 'g-ask'),
      makeRecord(4, 'agent.say', { text: '请点选上方卡片' }, 'g-ask'),
    ];
    expect(hasInteractiveCardInTailTurns(records)).toBe(true);
  });
});

describe('useSessionQueue 自动注入联动', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('当会话从 running 变为 stop 且 [end, end-5] 无交互卡时，自动调用 drain 注入最早一条并删除', async () => {
    const queueItems = [
      { id: 'q-1', text: '最早的一条消息', skills: [], attachments: 0, created_at: 1000 },
      { id: 'q-2', text: '第二条消息', skills: [], attachments: 0, created_at: 2000 },
    ];
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/queue') && (!init || !init.method || init.method === 'GET')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ sid: SID, items: queueItems }),
        } as unknown as Response;
      }
      if (url.endsWith('/queue/drain') && init?.method === 'POST') {
        const popped = queueItems.shift() ?? null;
        return {
          ok: true,
          status: 200,
          json: async () => ({
            sid: SID,
            injected: Boolean(popped),
            reason: 'ok',
            item: popped,
            items: [...queueItems],
          }),
        } as unknown as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as unknown as Response;
    });
    vi.stubGlobal('fetch', fetchMock);

    const onInjected = vi.fn();
    const records = normalTurn(1, 10);

    // 1. running=true 时不触发 drain
    const { result, rerender } = renderHook(
      ({ running, recs }) =>
        useSessionQueue(SID, {
          records: recs,
          recordsSessionId: SID,
          running,
          onInjected,
        }),
      { initialProps: { running: true, recs: records } }
    );

    await waitFor(() => expect(result.current.items).toHaveLength(2));
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    expect(onInjected).not.toHaveBeenCalled();

    // 2. running=false（会话 stop）且 [end, end-5] 无交互卡：自动注入最早一条 q-1，队列只剩 q-2
    rerender({ running: false, recs: records });
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    await waitFor(() => expect(onInjected).toHaveBeenCalledTimes(1));
    expect(onInjected.mock.calls[0][0].id).toBe('q-1');
    expect(result.current.items.map((it) => it.id)).toEqual(['q-2']);
  });
});
