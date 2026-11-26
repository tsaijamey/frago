import { describe, expect, it } from 'vitest';
import {
  STACK_CLUSTER_H,
  STACK_LABEL_H,
  STACK_MAX_OFFSET,
  cleanQuoteText,
  computeFinalAgentSayIds,
  isResponseAt,
  layoutStackLabels,
  stackLabelText,
  stackStatusOf,
  type StackRailItem,
} from '../stackRailLayout';
import type { WorkbenchMark } from '@/types/api';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';

function mk(id: string, over: Partial<WorkbenchMark> = {}): WorkbenchMark {
  return {
    id,
    kind: 'stack',
    record_id: 'r1',
    text: `原文-${id}`,
    occurrence: 0,
    note: '',
    used: false,
    created_at: 1,
    used_at: null,
    ...over,
  };
}

function item(id: string, rawY: number, status: 'pending' | 'draft' = 'pending'): StackRailItem {
  return { mark: mk(id), status, rawY };
}

function rec(id: string, kind: WorkbenchRecord['kind'], payload: Record<string, unknown> = {}): WorkbenchRecord {
  return {
    id,
    session_id: 's1',
    group_id: null,
    seq: 1,
    ts: 1,
    kind,
    agent_path: [],
    payload,
    raw_available: false,
  };
}

describe('stackRailLayout helpers', () => {
  it('cleanQuoteText、stackLabelText 与 stackStatusOf 按契约返回', () => {
    expect(cleanQuoteText('  第一行\n\t 第二行  ')).toBe('第一行 第二行');
    expect(stackLabelText(mk('1', { note: '  优先看这里 ', text: '原文' }))).toBe('优先看这里');
    expect(stackLabelText(mk('2', { note: '   ', text: '原文\n换行' }))).toBe('原文 换行');

    const draftSet = new Set(['m-draft']);
    expect(stackStatusOf(mk('m-used', { used: true }), draftSet)).toBe('used');
    expect(stackStatusOf(mk('m-draft'), draftSet)).toBe('draft');
    expect(stackStatusOf(mk('m-pending'), draftSet)).toBe('pending');
  });

  it('单条与 2-3 条近邻标签可散开且最大偏移不超过 36px，互相不重叠', () => {
    expect(layoutStackLabels([], 500)).toEqual([]);
    expect(layoutStackLabels([item('a', 100)], 0)).toEqual([]);

    const single = layoutStackLabels([item('s', 2)], 500, 28);
    expect(single).toHaveLength(1);
    expect(single[0].kind).toBe('single');
    expect(single[0].dispY).toBe(28);

    const spread3 = layoutStackLabels(
      [item('a', 195), item('b', 200), item('c', 205)],
      500,
      4
    );
    expect(spread3.every((e) => e.kind === 'single')).toBe(true);
    for (let i = 0; i < spread3.length; i += 1) {
      const ent = spread3[i];
      if (ent.kind === 'single') {
        expect(Math.abs(ent.dispY + STACK_LABEL_H / 2 - ent.item.rawY)).toBeLessThanOrEqual(
          STACK_MAX_OFFSET
        );
      }
      if (i > 0) {
        expect(ent.dispY).toBeGreaterThanOrEqual(spread3[i - 1].dispY + spread3[i - 1].h + 2);
      }
    }
  });

  it('4 条及以上近邻或底部溢出时合并成 cluster 胶囊，prefItem 优先选 pending', () => {
    const four = layoutStackLabels(
      [
        item('d1', 100, 'draft'),
        item('p1', 108, 'pending'),
        item('d2', 114, 'draft'),
        item('d3', 120, 'draft'),
      ],
      500,
      4
    );
    expect(four).toHaveLength(1);
    expect(four[0].kind).toBe('cluster');
    if (four[0].kind === 'cluster') {
      expect(four[0].items).toHaveLength(4);
      expect(four[0].prefItem.mark.id).toBe('p1');
      expect(four[0].allDraft).toBe(false);
      expect(four[0].h).toBe(STACK_CLUSTER_H);
    }

    // 底部空间不足时触发跨组反向合并成 cluster
    const bottomCrowded = layoutStackLabels(
      [item('b1', 460), item('b2', 488)],
      500,
      4
    );
    expect(bottomCrowded).toHaveLength(1);
    expect(bottomCrowded[0].kind).toBe('cluster');
  });
});

describe('computeFinalAgentSayIds 过程旁白过滤', () => {
  it('过滤紧邻下一次 tool.call 之前的 agent.say，仅保留轮次最终回复', () => {
    const records: WorkbenchRecord[] = [
      rec('u1', 'user.say'),
      rec('a-nar-1', 'agent.say'),
      rec('th-1', 'agent.think'),
      rec('tc-1', 'tool.call'),
      rec('tr-1', 'tool.result'),
      rec('a-nar-2', 'agent.say'),
      rec('tc-2', 'tool.call'),
      rec('tr-2', 'tool.result'),
      rec('a-final-1', 'agent.say'),
      rec('u2', 'user.say'),
      rec('a-nar-3', 'agent.say'),
      rec('tc-3', 'tool.call'),
      rec('tr-3', 'tool.result'),
      rec('a-final-2', 'agent.say'),
      rec('qc-1', 'context.inject', { channel: 'queued_command' }),
      rec('a-final-3', 'agent.say'),
    ];

    expect(isResponseAt(records, 0)).toBe(false);
    expect(isResponseAt(records, 1)).toBe(false);
    expect(isResponseAt(records, 5)).toBe(false);
    expect(isResponseAt(records, 8)).toBe(true);
    expect(isResponseAt(records, 10)).toBe(false);
    expect(isResponseAt(records, 13)).toBe(true);
    expect(isResponseAt(records, 15)).toBe(true);

    expect([...computeFinalAgentSayIds(records)]).toEqual(['a-final-1', 'a-final-2', 'a-final-3']);
  });
});
