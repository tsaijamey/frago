/**
 * 交互决策卡（`frago app ask`）随 Stop 消息渐显的时序测试。
 *
 * 覆盖核心时序场景与返工边界：
 * 1. 卡片先到且 Stop 未到（回合仍在运行）→ 暂存隐藏不提前闪现（含先有过程 agent.say 与 All 镜头）；
 * 2. Stop 消息到达 → 卡片随 Stop 一同显现并带渐显类；
 * 3. 回合结束（进入 done/stop/interrupt 终态）但无尾文 → 卡片解除暂存正常渐显不卡死；
 * 4. 历史已完结会话 / Stop 已存在 / 前置历史回合 / 切会话 → 正常立即显示无回归、不误藏；
 * 5. 过程旁白 + 同回合多张卡片（及先败后成）+ 二次归一化 & Watcher 视图 → 不泄露旧卡或失败卡；
 * 6. tool.result 后出现普通 error 终态 → 立即释放不延迟（前置 error 不误释放）；
 * 7. 孤儿 activeTrail 残留 & 有界兜底定时器 → 非运行态立刻释放、断连漏事件经有界时长必释放；
 * 8. 无尾文兜底挂旧过程旁白不闪烁外层气泡 + 切镜头/动效播完不重播淡入动画。
 */

import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';

import RecordStream, {
  STAGED_DECISION_CARD_FALLBACK_MS,
  buildTalkSegments,
  extractSliceDecisionCards,
  talkView,
  withTurnDecisionCards,
} from '../RecordStream';
import type { SendTrail, WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

afterEach(() => {
  vi.useRealTimers();
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

const CARD_JSON_V2 = JSON.stringify({
  frago_ui_component: 'decision-card',
  component_type: 'single-choice',
  data: {
    type: 'single-choice',
    question: '已修订方案，确认执行第二版发布计划？',
    options: [
      { key: 'A', label: '执行第二版', effect: '按修订方案发布', recommended: true, reversible: true },
      { key: 'B', label: '继续修改', effect: '暂不发布', recommended: false, reversible: true },
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

  it('场景⑤（P1-1）：过程旁白 + 同回合多张 frago app ask（及先失败后成功）二次归一化不泄露旧卡', () => {
    const u1 = rec({ id: 'u5', kind: 'user.say', payload: { text: '帮我出方案确认卡' } });
    const preSay = rec({
      id: 'a-pre-5',
      kind: 'agent.say',
      payload: { text: '正在整理选项并生成卡片...' },
    });
    const tcFail = rec({
      id: 'tc5-fail',
      kind: 'tool.call',
      payload: {
        call_id: 'ask-5-fail',
        tool_name: 'Bash',
        args: { command: 'frago app ask --type single-choice' },
      },
    });
    const tFail = rec({
      id: 't5-fail',
      kind: 'tool.result',
      payload: {
        call_id: 'ask-5-fail',
        tool_name: 'Bash',
        status: 'error',
        body: 'error: missing --option',
      },
    });
    const tc1 = rec({
      id: 'tc5-1',
      kind: 'tool.call',
      payload: {
        call_id: 'ask-5-1',
        tool_name: 'Bash',
        args: { command: 'frago app ask --type single-choice' },
      },
    });
    const t1 = rec({
      id: 't5-1',
      kind: 'tool.result',
      payload: { call_id: 'ask-5-1', tool_name: 'Bash', status: 'ok', body: CARD_JSON },
    });
    const tc2 = rec({
      id: 'tc5-2',
      kind: 'tool.call',
      payload: {
        call_id: 'ask-5-2',
        tool_name: 'Bash',
        args: { command: 'frago app ask --type single-choice' },
      },
    });
    const t2 = rec({
      id: 't5-2',
      kind: 'tool.result',
      payload: { call_id: 'ask-5-2', tool_name: 'Bash', status: 'ok', body: CARD_JSON_V2 },
    });
    const runningRecords = [u1, preSay, tcFail, tFail, tc1, t1, tc2, t2];

    // 1. 运行中一次归一化：同回合失败卡与两张成功卡全部标记 staged + delegated，绝不挂到过程旁白上
    const normalized = withTurnDecisionCards(runningRecords, { deferUnfinishedTurn: true });
    expect(normalized[1].payload.ui_component).toBeUndefined();
    expect(normalized[3].payload.ui_component_staged).toBe(true);
    expect(normalized[3].payload.ui_component_delegated).toBe(true);
    expect(normalized[5].payload.ui_component_staged).toBe(true);
    expect(normalized[5].payload.ui_component_delegated).toBe(true);
    expect(normalized[7].payload.ui_component_staged).toBe(true);
    expect(normalized[7].payload.ui_component_delegated).toBe(true);

    // 2. 无参二次归一化（模拟 Watcher 面板或无 options 重扫）绝不复活旧卡或失败卡
    expect(extractSliceDecisionCards(normalized)).toHaveLength(0);
    expect(extractSliceDecisionCards(normalized, { deferUnfinishedTurn: true })).toHaveLength(0);
    expect(talkView(normalized).some((r) => r.id === 't5-1' || r.id === 't5-2' || r.id === 't5-fail')).toBe(
      false
    );
    expect(
      buildTalkSegments(normalized).some(
        (s) => s.kind === 'record' && (s.record.id === 't5-1' || s.record.id === 't5-2')
      )
    ).toBe(false);

    // 3. Stop 到达后：仅挂载最新第二版卡片，且无参二次归一化仍只返回最新一张，不复活旧卡
    const stopSay = rec({
      id: 'a-stop-5',
      kind: 'agent.say',
      payload: { text: '已按最新方案汇总，请确认。' },
    });
    const resolvedAfterStop = withTurnDecisionCards([...runningRecords, stopSay], {
      deferUnfinishedTurn: true,
    });
    const extractedAfterStop = extractSliceDecisionCards(resolvedAfterStop);
    expect(extractedAfterStop).toHaveLength(1);
    expect(extractedAfterStop[0].recordId).toBe('a-stop-5');
    expect(extractedAfterStop[0].block.question).toBe('已修订方案，确认执行第二版发布计划？');

    // 4. 渲染层全链路验证：运行中 Talk、All 与 Watcher（进展）视图均不泄露任何旧卡或误显待拍板横幅；Stop 到达后仅显示第二版卡
    const watcherObserver = {
      state: {
        bound: true,
        session_id: 'ses-multi-card',
        anchor: '整理方案并确认发布',
        phase_goal: '输出确认卡',
        tail: { kind: 'now' as const, text: '正在整理第二版选项' },
        decision: '',
        happened: ['已整理初稿'],
        tasks: [],
        runs: [
          {
            id: 'run-1',
            run_id: 1,
            task_id: 'T1',
            actor: '主会话',
            at: t2.ts,
            cursor_from: u1.seq,
            cursor_to: t2.seq + 1,
            tail: { kind: 'now' as const, text: '正在整理第二版选项' },
            happened_add: ['已整理初稿'],
            decision: '',
            summary: '整理发布方案',
          },
        ],
        updated_at: t2.ts,
        model: 'observer',
        status: 'ok' as const,
        status_detail: null,
      },
      loading: false,
      error: null,
    };
    const { rerender } = render(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-multi-card',
          records: runningRecords,
          sessionRunning: true,
          observer: watcherObserver,
        })}
      />
    );
    expect(screen.queryByTestId('decision-card')).toBeNull();
    fireEvent.click(screen.getByTestId('lens-all'));
    expect(screen.queryByTestId('decision-card')).toBeNull();
    fireEvent.click(screen.getByTestId('lens-watcher'));
    expect(screen.getByTestId('watcher-view')).toBeTruthy();
    expect(screen.queryByTestId('watcher-card-slot')).toBeNull();
    expect(screen.queryByTestId('watcher-decision-banner')).toBeNull();
    expect(screen.queryByTestId('decision-card')).toBeNull();

    // 切回 Talk 镜头并送入 Stop：仅显示第二版卡，旧卡不复活
    fireEvent.click(screen.getByTestId('lens-talk'));
    rerender(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-multi-card',
          records: [...runningRecords, stopSay],
          sessionRunning: true,
          observer: {
            ...watcherObserver,
            state: {
              ...watcherObserver.state,
              runs: [
                {
                  ...watcherObserver.state.runs[0],
                  cursor_to: stopSay.seq + 1,
                },
              ],
            },
          },
        })}
      />
    );
    const renderedCards = screen.getAllByTestId('decision-card');
    expect(renderedCards).toHaveLength(1);
    expect(screen.getByText('已修订方案，确认执行第二版发布计划？')).toBeTruthy();
    expect(screen.queryByText('确认是否立即发布本次改动？')).toBeNull();
  });

  it('场景⑥（P1-2a）：tool.result 之后出现普通 error 记录时立即释放卡片，前置 error 不误释放', () => {
    const u1 = rec({ id: 'u6', kind: 'user.say', payload: { text: '准备发布' } });
    const preErr = rec({
      id: 'err-pre-6',
      kind: 'error',
      payload: { code: 'rate_limit', message: '请求短暂限流，自动重试' },
    });
    const tc1 = rec({
      id: 'tc6',
      kind: 'tool.call',
      payload: {
        call_id: 'ask-6',
        tool_name: 'Bash',
        args: { command: 'frago app ask --type single-choice' },
      },
    });
    const t1 = rec({
      id: 't6',
      kind: 'tool.result',
      payload: { call_id: 'ask-6', tool_name: 'Bash', status: 'ok', body: CARD_JSON },
    });
    const postErr = rec({
      id: 'err-post-6',
      kind: 'error',
      payload: { code: 'upstream_timeout', message: '模型接口超时中断' },
    });

    // error 出现在 tool.result 之前：不误释放，卡片保持暂存隐藏
    const { rerender } = render(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-error-release',
          records: [u1, preErr, tc1, t1],
          sessionRunning: true,
        })}
      />
    );
    expect(screen.queryByTestId('decision-card')).toBeNull();

    // error 出现在 tool.result 之后（即使 sessionRunning 仍为 true）：立即解除暂存并渐显
    rerender(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-error-release',
          records: [u1, preErr, tc1, t1, postErr],
          sessionRunning: true,
        })}
      />
    );
    const card = screen.getByTestId('decision-card');
    expect(card).toBeTruthy();
    expect(card.className).toContain('is-reveal');
    expect(card.getAttribute('data-reveal')).toBe('true');
  });

  it('场景⑦（P1-2b）：孤儿 activeTrail 残留与有界兜底定时器释放，绝不永久卡死隐藏', () => {
    const u1 = rec({ id: 'u7', kind: 'user.say', payload: { text: '请给我选项' } });
    const tc1 = rec({
      id: 'tc7',
      kind: 'tool.call',
      payload: {
        call_id: 'ask-7',
        tool_name: 'Bash',
        args: { command: 'frago app ask --type single-choice' },
      },
    });
    const t1 = rec({
      id: 't7',
      kind: 'tool.result',
      payload: { call_id: 'ask-7', tool_name: 'Bash', status: 'ok', body: CARD_JSON },
    });
    const orphanTrail: SendTrail = {
      id: 'trail-orphan-7',
      text: '请给我选项',
      attachments: 0,
      recordId: u1.id,
      midTurn: false,
      steps: {
        on_its_way: u1.ts - 500,
        in_the_session: u1.ts,
        picked_up: tc1.ts,
      },
    };

    // 1. 存在未 settled 的孤儿 activeTrail，但外层 sessionRunning 明确为 false → 立即释放不卡死
    const { rerender, unmount } = render(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-orphan-trail',
          records: [u1, tc1, t1],
          trails: [orphanTrail],
          sessionRunning: true,
        })}
      />
    );
    expect(screen.queryByTestId('decision-card')).toBeNull();

    rerender(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-orphan-trail',
          records: [u1, tc1, t1],
          trails: [orphanTrail],
          sessionRunning: false,
        })}
      />
    );
    const releasedOnNonRunning = screen.getByTestId('decision-card');
    expect(releasedOnNonRunning).toBeTruthy();
    expect(releasedOnNonRunning.className).toContain('is-reveal');
    unmount();

    // 2. 即使 sessionRunning 仍为 true（如 WS 丢 SESSION_TURN_DONE 导致 inFlight 永存或后端 90s 活跃窗口滞后），
    //    经过 STAGED_DECISION_CARD_FALLBACK_MS 有界兜底时长后必然释放并渐显，绝不无限期卡死
    vi.useFakeTimers();
    render(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-bounded-fallback',
          records: [u1, tc1, t1],
          trails: [orphanTrail],
          sessionRunning: true,
        })}
      />
    );
    expect(screen.queryByTestId('decision-card')).toBeNull();

    act(() => {
      vi.advanceTimersByTime(STAGED_DECISION_CARD_FALLBACK_MS - 1);
    });
    expect(screen.queryByTestId('decision-card')).toBeNull();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    const fallbackCard = screen.getByTestId('decision-card');
    expect(fallbackCard).toBeTruthy();
    expect(fallbackCard.className).toContain('is-reveal');
    expect(fallbackCard.getAttribute('data-reveal')).toBe('true');
  });

  it('场景⑧（P2-1）：无尾文挂回旧过程旁白时不给外层气泡加 is-decision-reveal，且切镜头/播完后不重播淡入', () => {
    vi.useFakeTimers();
    const u1 = rec({ id: 'u8', kind: 'user.say', payload: { text: '请给我选项' } });
    const preSay = rec({
      id: 'a-pre-8',
      kind: 'agent.say',
      payload: { text: '先看一下当前环境状态。' },
    });
    const tc1 = rec({
      id: 'tc8',
      kind: 'tool.call',
      payload: {
        call_id: 'ask-8',
        tool_name: 'Bash',
        args: { command: 'frago app ask --type single-choice' },
      },
    });
    const t1 = rec({
      id: 't8',
      kind: 'tool.result',
      payload: { call_id: 'ask-8', tool_name: 'Bash', status: 'ok', body: CARD_JSON },
    });

    // 第 1 帧：运行中暂存，过程旁白已展示但无卡片
    const { container, rerender } = render(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-pre-fallback-no-flash',
          records: [u1, preSay, tc1, t1],
          sessionRunning: true,
        })}
      />
    );
    expect(screen.getByText('先看一下当前环境状态。')).toBeTruthy();
    expect(screen.queryByTestId('decision-card')).toBeNull();

    // 第 2 帧：无新尾文直接回合结束 → 卡片兜底挂回旧过程旁白，但外层 .wb-record 不加 is-decision-reveal，仅子卡片渐显
    rerender(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-pre-fallback-no-flash',
          records: [u1, preSay, tc1, t1],
          sessionRunning: false,
        })}
      />
    );
    const preEl = container.querySelector('[data-record-id="a-pre-8"]');
    expect(preEl).toBeTruthy();
    expect(preEl?.className).not.toContain('is-decision-reveal');
    expect(preEl?.getAttribute('data-decision-reveal')).toBeNull();

    const card = screen.getByTestId('decision-card');
    expect(card.className).toContain('is-reveal');
    expect(card.getAttribute('data-reveal')).toBe('true');

    // 第 3 帧：立刻切换镜头（Talk → All → Talk），已消费卡片不再携带 is-reveal，避免重挂载反复淡入
    fireEvent.click(screen.getByTestId('lens-all'));
    const allCard = screen.getByTestId('decision-card');
    expect(allCard.className).not.toContain('is-reveal');
    expect(allCard.getAttribute('data-reveal')).toBeNull();

    fireEvent.click(screen.getByTestId('lens-talk'));
    const talkCardAgain = screen.getByTestId('decision-card');
    expect(talkCardAgain.className).not.toContain('is-reveal');
    expect(talkCardAgain.getAttribute('data-reveal')).toBeNull();

    // 第 4 帧：新回合走正常 Stop 渐显后，等待动效消费定时器完成（400ms），不切镜头也会自动清除 is-reveal / is-decision-reveal
    const u2 = rec({ id: 'u8-2', kind: 'user.say', payload: { text: '第二轮' } });
    const t2 = rec({
      id: 't8-2',
      kind: 'tool.result',
      payload: { call_id: 'ask-8-2', tool_name: 'Bash', status: 'ok', body: CARD_JSON_V2 },
    });
    const stop2 = rec({
      id: 'a-stop-8-2',
      kind: 'agent.say',
      payload: { text: '第二轮收尾回复。' },
    });
    rerender(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-pre-fallback-no-flash',
          records: [u1, preSay, tc1, t1, u2, t2],
          sessionRunning: true,
        })}
      />
    );
    rerender(
      <RecordStream
        {...streamProps({
          sessionId: 'ses-pre-fallback-no-flash',
          records: [u1, preSay, tc1, t1, u2, t2, stop2],
          sessionRunning: true,
        })}
      />
    );
    const stop2El = container.querySelector('[data-record-id="a-stop-8-2"]');
    expect(stop2El?.className).toContain('is-decision-reveal');
    expect(stop2El?.querySelector('[data-testid="decision-card"]')?.className).toContain('is-reveal');

    act(() => {
      vi.advanceTimersByTime(500);
    });
    const settledStop2El = container.querySelector('[data-record-id="a-stop-8-2"]');
    expect(settledStop2El?.className).not.toContain('is-decision-reveal');
    expect(settledStop2El?.querySelector('[data-testid="decision-card"]')?.className).not.toContain(
      'is-reveal'
    );
  });
});
