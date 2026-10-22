/**
 * useSessionQueue 单元测试：验证 [end, end-5] 轮交互卡检测、stop 轮次识别与自动注入。
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import {
  detectStopTurnId,
  hasInteractiveCardInTailTurns,
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
  groupId: string | null = null
): WorkbenchRecord {
  return {
    id: `rec-${seq}`,
    session_id: SID,
    group_id: groupId,
    seq,
    ts: 1_700_000_000_000 + seq * 1000,
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

function hookTurn(turnIdx: number, baseSeq: number): WorkbenchRecord[] {
  return [
    makeRecord(baseSeq, 'context.inject', { source: 'hook', body: `hook ${turnIdx}` }),
    makeRecord(baseSeq + 1, 'agent.say', { text: `补充说明 ${turnIdx}` }, `gh-${turnIdx}`),
  ];
}

beforeAll(async () => {
  await loadYaml();
});

describe('hasInteractiveCardInTailTurns ([end, end-5] 轮交互卡检测)', () => {
  it('近 6 轮无交互卡时返回 false，并识别出末尾 stop 轮次', () => {
    const records: WorkbenchRecord[] = [];
    for (let i = 0; i < 6; i += 1) {
      records.push(...normalTurn(i, i * 10));
    }
    expect(hasInteractiveCardInTailTurns(records)).toBe(false);
    expect(detectStopTurnId(records)).toBe('rec-51');
  });

  it('交互卡在 end 到 end-5 任一轮（含被 1~5 轮 hook 补充回复遮挡）时返回 true', () => {
    for (let hookCount = 0; hookCount <= 5; hookCount += 1) {
      const records: WorkbenchRecord[] = [
        makeRecord(1, 'user.say', { text: '开始部署' }),
        makeRecord(2, 'agent.say', { text: FENCE_CARD }, 'g-card'),
      ];
      for (let h = 0; h < hookCount; h += 1) {
        records.push(...hookTurn(h + 1, 10 + h * 10));
      }
      expect(segmentMainTurns(records)).toHaveLength(1 + hookCount);
      expect(hasInteractiveCardInTailTurns(records)).toBe(true);
    }
  });

  it('frago ask 的 tool.result 交互卡被 5 轮 hook 遮挡在 end-5 时仍返回 true', () => {
    const records: WorkbenchRecord[] = [
      makeRecord(1, 'user.say', { text: '怎么回滚？' }),
      makeRecord(2, 'tool.call', { tool: 'ask' }, 'g-ask'),
      makeRecord(3, 'tool.result', { status: 'ok', body: ASK_JSON }, 'g-ask'),
      makeRecord(4, 'agent.say', { text: '请点选上方卡片' }, 'g-ask'),
    ];
    for (let h = 0; h < 5; h += 1) {
      records.push(...hookTurn(h + 1, 10 + h * 10));
    }
    expect(segmentMainTurns(records)).toHaveLength(6);
    expect(hasInteractiveCardInTailTurns(records)).toBe(true);
  });

  it('交互卡在 end-6（后方已有 6 轮无卡会话）时不再阻断', () => {
    const records: WorkbenchRecord[] = [
      makeRecord(1, 'user.say', { text: '开始部署' }),
      makeRecord(2, 'agent.say', { text: FENCE_CARD }, 'g-card'),
    ];
    for (let h = 0; h < 6; h += 1) {
      records.push(...hookTurn(h + 1, 10 + h * 10));
    }
    expect(segmentMainTurns(records)).toHaveLength(7);
    expect(hasInteractiveCardInTailTurns(records)).toBe(false);
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
