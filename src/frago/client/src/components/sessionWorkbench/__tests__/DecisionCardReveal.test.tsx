/**
 * 交互决策卡（`frago app ask`）随 Stop 消息渐显的时序测试。
 *
 * 覆盖 4 个核心时序场景与边界：
 * 1. 卡片先到且 Stop 未到（回合仍在运行）→ 暂存隐藏不提前闪现（含先有过程 agent.say 与 All 镜头）；
 * 2. Stop 消息到达 → 卡片随 Stop 一同显现并带渐显类；
 * 3. 回合结束（进入 done/stop/interrupt 终态）但无尾文 → 卡片解除暂存正常渐显不卡死；
 * 4. 历史已完结会话 / Stop 已存在 / 前置历史回合 / 切会话 → 正常立即显示无回归、不误藏。
 */

import { beforeAll, describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import RecordStream, {
  buildTalkSegments,
  extractSliceDecisionCards,
  talkView,
  withTurnDecisionCards,
} from '../RecordStream';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const CARD_JSON = JSON.stringify({
  frago_ui_component: 'decision-card',
  component_type: 'single-choice',
  data: {
    type: 'single-choice',
    question: '确认是否立即发布本次改动？',
    options: [
      { key: 'A', label: '立即发布', effect: '构建并发布到生产环境', recommended: true, reversible: true },
      { key: 'B', label: '暂缓发布', effect: '仅保留代码待后续人工确认', recommended: false, reversible: true },
    ],
  },
});

const INLINE_STOP_TEXT = [
  '以下是直接写在收尾消息里的确认项：',
  '',
  '```answer-needed-by-human',
  'type: single-choice',
  'question: 确认内联卡片行为正常？',
  'options:',
  '  - key: A',
  '    label: 确认',
  '    effect: 继续后续步骤',
  '    recommended: true',
  '    reversible: true',
  '  - key: B',
  '    label: 取消',
  '    effect: 保持当前状态',
  '    recommended: false',
  '    reversible: true',
  '```',
].join('\n');

let seqCounter = 0;

function rec(
  over: Partial<WorkbenchRecord> & Pick<WorkbenchRecord, 'kind'>,
  sid = 'ses-reveal'
): WorkbenchRecord {
  seqCounter += 1;
  return {
    id: `rec-${seqCounter}`,
    session_id: sid,
    group_id: null,
    seq: seqCounter,
    ts: 1_753_800_000_000 + seqCounter * 1_000,
    agent_path: [],
    payload: {},
    raw_available: false,
    ...over,
  };
}

function streamProps(over: Partial<Parameters<typeof RecordStream>[0]> = {}) {
  return {
    sessionId: 'ses-reveal',
    records: [] as WorkbenchRecord[],
    loading: false,
    loadingOlder: false,
    hasOlder: false,
    error: null,
    onLoadOlder: () => {},
    ...over,
  };
}

describe('交互决策卡时序：暂存隐藏与随 Stop 消息渐显', () => {
  it('场景①：卡片 tool.result 先到且 Stop 未到（本轮运行中）时暂存隐藏，不提前闪现（含过程旁白与 All 镜头）', () => {
    const u1 = rec({ id: 'u1', kind: 'user.say', payload: { text: '准备发布' } });
    const preSay = rec({
      id: 'a-pre',
      kind: 'agent.say',
      payload: { text: '正在生成确认卡片...' },
    });
    const tc1 = rec({
      id: 'tc1',
      kind: 'tool.call',
      payload: {
        call_id: 'ask-1',
        tool_name: 'Bash',
        tool_family: 'shell',
        args: { command: 'frago app ask --type single-choice' },
      },
    });
    const t1 = rec({
      id: 't1',
      kind: 'tool.result',
      payload: { call_id: 'ask-1', tool_name: 'Bash', status: 'ok', body: CARD_JSON },
    });
    const records = [u1, preSay, tc1, t1];

    // 纯数据层：末尾运行回合的卡片应被标记为 staged + delegated，且绝不提前挂到早于它的过程 agent.say 上
    const normalized = withTurnDecisionCards(records, { deferUnfinishedTurn: true });
    expect(normalized[1].payload.ui_component).toBeUndefined();
    expect(normalized[3].payload.ui_component_delegated).toBe(true);
    expect(normalized[3].payload.ui_component_staged).toBe(true);
    expect(talkView(normalized).some((r) => r.id === 't1')).toBe(false);
    expect(
      buildTalkSegments(normalized).some((s) => s.kind === 'record' && s.record.id === 't1')
    ).toBe(false);
    expect(extractSliceDecisionCards(normalized)).toHaveLength(0);

    // 渲染层（Talk 镜头 + All 镜头）：不提前渲染决策卡，不占高
    render(<RecordStream {...streamProps({ records, sessionRunning: true })} />);
    expect(screen.getByText('正在生成确认卡片...')).toBeTruthy();
    expect(screen.queryByTestId('decision-card')).toBeNull();

    fireEvent.click(screen.getByTestId('lens-all'));
    expect(screen.queryByTestId('decision-card')).toBeNull();
  });

  it('场景②：Stop 消息到达后，卡片随 Stop 一同显现并带柔和渐显类（含先有过程旁白场景）', () => {
    const u1 = rec({ id: 'u2', kind: 'user.say', payload: { text: '准备发布' } });
    const preSay = rec({
      id: 'a-pre-2',
      kind: 'agent.say',
      payload: { text: '先检查变更并弹出确认卡。' },
    });
    const tc1 = rec({
      id: 'tc2',
      kind: 'tool.call',
      payload: {
        call_id: 'ask-2',
        tool_name: 'Bash',
        args: { command: 'frago app ask --type single-choice' },
      },
    });
    const t1 = rec({
      id: 't2',
      kind: 'tool.result',
      payload: { call_id: 'ask-2', tool_name: 'Bash', status: 'ok', body: CARD_JSON },
    });
    const stopSay = rec({
      id: 'a-stop-2',
      kind: 'agent.say',
      payload: { text: '所有前置检查已通过，请在下方卡片确认是否发布。' },
    });

    // 第 1 帧：tool.result 先到、Stop 未到 → 隐藏
    const { container, rerender } = render(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-stop-reveal',
          records: [u1, preSay, tc1, t1],
          sessionRunning: true,
        })}
      />
    );
    expect(screen.queryByTestId('decision-card')).toBeNull();

    // 第 2 帧：Stop 消息到达（即使后端 sessionRunning 尚未切回 false）→ 卡片随 Stop 一起显现并带渐显类
    rerender(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-stop-reveal',
          records: [u1, preSay, tc1, t1, stopSay],
          sessionRunning: true,
        })}
      />
    );

    expect(screen.getByText('所有前置检查已通过，请在下方卡片确认是否发布。')).toBeTruthy();
    const cards = screen.getAllByTestId('decision-card');
    expect(cards).toHaveLength(1);
    expect(cards[0].className).toContain('is-reveal');
    expect(cards[0].getAttribute('data-reveal')).toBe('true');

    // Stop 消息外壳带同步渐显类，过程旁白不带卡片也不带渐显类
    const stopEl = container.querySelector('[data-record-id="a-stop-2"]');
    const preEl = container.querySelector('[data-record-id="a-pre-2"]');
    expect(stopEl?.className).toContain('is-decision-reveal');
    expect(stopEl?.getAttribute('data-decision-reveal')).toBe('true');
    expect(stopEl?.querySelector('[data-testid="decision-card"]')).toBeTruthy();
    expect(preEl?.querySelector('[data-testid="decision-card"]')).toBeNull();
    expect(preEl?.className).not.toContain('is-decision-reveal');
  });

  it('场景③：回合结束（done/stop 或 interrupt）但无附加尾文时，卡片解除暂存并渐显不永久隐藏', () => {
    const u1 = rec({ id: 'u3', kind: 'user.say', payload: { text: '请给我选项' } });
    const tc1 = rec({
      id: 'tc3',
      kind: 'tool.call',
      payload: {
        call_id: 'ask-3',
        tool_name: 'Bash',
        args: { command: 'frago app ask --type single-choice' },
      },
    });
    const t1 = rec({
      id: 't3',
      kind: 'tool.result',
      payload: { call_id: 'ask-3', tool_name: 'Bash', status: 'ok', body: CARD_JSON },
    });

    // 运行中：先隐藏
    const { rerender } = render(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-no-tail',
          records: [u1, tc1, t1],
          sessionRunning: true,
        })}
      />
    );
    expect(screen.queryByTestId('decision-card')).toBeNull();

    // 回合进入 done/stop 终态（sessionRunning=false），且无 agent.say 尾文 → 兜底显现并带渐显类
    rerender(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-no-tail',
          records: [u1, tc1, t1],
          sessionRunning: false,
        })}
      />
    );
    const card = screen.getByTestId('decision-card');
    expect(card).toBeTruthy();
    expect(card.className).toContain('is-reveal');
    expect(card.getAttribute('data-reveal')).toBe('true');

    // 另一路兜底：sessionRunning 尚未刷新为 false，但流里出现了 interrupt 记录 → 同样立即解除暂存
    const intr = rec({ id: 'intr-3', kind: 'interrupt', payload: { reason: 'user' } });
    const afterInterrupt = withTurnDecisionCards([u1, tc1, t1, intr], {
      deferUnfinishedTurn: true,
    });
    expect(afterInterrupt[2].payload.ui_component_staged).toBeUndefined();
    expect(afterInterrupt[2].payload.ui_component_delegated).toBeUndefined();
  });

  it('场景④：历史已完结会话 / Stop 已存在 / 前置历史回合 / 切会话均零回归，立即显示且不误藏', async () => {
    const u1 = rec({ id: 'u4', kind: 'user.say', payload: { text: '历史问题' } });
    const tc1 = rec({
      id: 'tc4',
      kind: 'tool.call',
      payload: {
        call_id: 'ask-4',
        tool_name: 'Bash',
        args: { command: 'frago app ask --type single-choice' },
      },
    });
    const t1 = rec({
      id: 't4',
      kind: 'tool.result',
      payload: { call_id: 'ask-4', tool_name: 'Bash', status: 'ok', body: CARD_JSON },
    });
    const a1 = rec({
      id: 'a4',
      kind: 'agent.say',
      payload: { text: '历史收尾回复，请确认。' },
    });

    // 1. 历史已完结会话首次加载（Stop 已存在）→ 立即正常显示，不触发暂存渐显类
    const { container, rerender } = render(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-history-1',
          records: [u1, tc1, t1, a1],
          sessionRunning: false,
        })}
      />
    );
    const histCard = screen.getByTestId('decision-card');
    expect(histCard).toBeTruthy();
    expect(histCard.className).not.toContain('is-reveal');
    expect(histCard.getAttribute('data-reveal')).toBeNull();
    expect(
      container.querySelector('[data-record-id="a4"]')?.className
    ).not.toContain('is-decision-reveal');

    // 2. 历史已完结且无尾文的会话 → 不误藏，立即显示
    rerender(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-history-2',
          records: [u1, tc1, t1],
          sessionRunning: false,
        })}
      />
    );
    const noTailHistCard = screen.getByTestId('decision-card');
    expect(noTailHistCard).toBeTruthy();
    expect(noTailHistCard.className).not.toContain('is-reveal');

    // 3. 第 1 轮历史卡片无尾文 + 第 2 轮正在运行中 → 第 1 轮历史卡片绝不被误藏，仅第 2 轮未到 Stop 的卡片暂存
    const u2 = rec({ id: 'u4-2', kind: 'user.say', payload: { text: '继续下一步' } });
    const t2 = rec({
      id: 't4-2',
      kind: 'tool.result',
      payload: { call_id: 'ask-4-2', tool_name: 'Bash', status: 'ok', body: CARD_JSON },
    });
    rerender(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-history-3',
          records: [u1, tc1, t1, u2, t2],
          sessionRunning: true,
        })}
      />
    );
    // 只有第 1 轮的历史卡可见，第 2 轮刚到的 t2 暂存隐藏
    expect(screen.getAllByTestId('decision-card')).toHaveLength(1);
    expect(screen.getByTestId('decision-card').className).not.toContain('is-reveal');

    // 4. 切换到另一会话时清空暂存记忆（即使另一会话恰好复用相同记录 ID 也不误触渐显）
    rerender(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-history-4',
          records: [u2, t2, a1],
          sessionRunning: false,
        })}
      />
    );
    const switchedCard = screen.getByTestId('decision-card');
    expect(switchedCard.className).not.toContain('is-reveal');

    // 5. 卡片本就内联位于 Stop 消息中（answer-needed-by-human 代码块）→ 立即正常显示，不误藏也不加渐显类
    const inlineSay = rec({ id: 'a-inline', kind: 'agent.say', payload: { text: INLINE_STOP_TEXT } });
    rerender(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-history-5',
          records: [u1, inlineSay],
          sessionRunning: true,
        })}
      />
    );
    const inlineCard = await screen.findByTestId('decision-card');
    expect(inlineCard).toBeTruthy();
    expect(inlineCard.className).not.toContain('is-reveal');
  });
});
