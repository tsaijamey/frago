import { describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { humanReplyText, repliesAfter, useDecisionCards } from '../useDecisionCards';
import type { RecordKind, WorkbenchRecord } from '../useWorkbenchRecords';

let n = 0;
function rec(kind: RecordKind, payload: Record<string, unknown> = {}, agent_path: string[] = []): WorkbenchRecord {
  n += 1;
  return {
    id: `r${n}`,
    session_id: 's',
    group_id: null,
    seq: n,
    ts: 1_000 * n,
    kind,
    agent_path,
    payload,
    raw_available: false,
  };
}

describe('谁算人的答复', () => {
  it('人直接说的、插话算；斜杠命令、子 agent、队友转来的不算', () => {
    expect(humanReplyText(rec('user.say', { text: '好' }))).toBe('好');
    expect(humanReplyText(rec('context.inject', { channel: 'queued_command', body: '插一句' }))).toBe('插一句');
    expect(humanReplyText(rec('user.say', { text: 'x', command: '/rename' }))).toBeNull();
    expect(humanReplyText(rec('user.say', { text: 'x' }, ['sub']))).toBeNull();
    expect(humanReplyText(rec('user.say', { text: '【frago team】帮我看一下' }))).toBeNull();
  });

  it('每条 agent 回复之后人的第一句话就是它的答复', () => {
    const a1 = rec('agent.say', { text: '卡 1' });
    const a2 = rec('agent.say', { text: '卡 2' });
    const u1 = rec('user.say', { text: '【answer】A · x —— y' });
    const a3 = rec('agent.say', { text: '卡 3' });
    const tool = rec('tool.call', {});
    const map = repliesAfter([a1, a2, u1, a3, tool]);
    expect(map.get(a1.id)).toBe(u1);
    expect(map.get(a2.id)).toBe(u1);
    expect(map.has(a3.id)).toBe(false);
  });
});

describe('useDecisionCards', () => {
  it('点了先本地锁住；发送失败按信封编号撤掉，卡片重新可点', () => {
    const card = rec('agent.say', { text: '卡' });
    const onSendStart = vi.fn(() => 'out-1');
    const onSendFailed = vi.fn();
    const { result } = renderHook(() =>
      useDecisionCards({ sessionId: 's', records: [card], blockedReason: null, onSendStart, onSendFailed })
    );
    expect(result.current.host.answerOf(card.id)).toBeNull();

    act(() => result.current.host.answer(card.id, '【answer】A · x —— y'));
    expect(result.current.answer?.text).toBe('【answer】A · x —— y');
    expect(result.current.host.answerOf(card.id)?.kind).toBe('pending');

    act(() => {
      result.current.onSendStart('【answer】A · x —— y', 0);
    });
    expect(onSendStart).toHaveBeenCalledTimes(1);
    act(() => result.current.onSendFailed('out-1'));
    expect(onSendFailed).toHaveBeenCalledWith('out-1');
    expect(result.current.host.answerOf(card.id)).toBeNull();
  });

  it('记录里见到答复：卡片发的是 card，自己打字的是 own-words', () => {
    const c1 = rec('agent.say', { text: '卡' });
    const u1 = rec('user.say', { text: '【answer】A · x —— y' });
    const c2 = rec('agent.say', { text: '卡' });
    const u2 = rec('user.say', { text: '先别动' });
    const { result } = renderHook(() =>
      useDecisionCards({ sessionId: 's', records: [c1, u1, c2, u2], blockedReason: null, onSendStart: () => undefined })
    );
    expect(result.current.host.answerOf(c1.id)).toEqual({ kind: 'card', text: '【answer】A · x —— y', at: u1.ts });
    expect(result.current.host.answerOf(c2.id)?.kind).toBe('own-words');
  });

  it('这场发不出去时 canAnswer 为假，原因照搬', () => {
    const { result } = renderHook(() =>
      useDecisionCards({ sessionId: null, records: [], blockedReason: 'k', onSendStart: () => undefined })
    );
    expect(result.current.host.canAnswer).toBe(false);
    expect(result.current.host.blockedReason).toBe('k');
  });
});
