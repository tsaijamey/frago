/**
 * 决定卡片的组件测试。守住的是「点了之后交出去的是什么」与「什么时候点不动」：
 *
 * 1. 4 型各自交出的原文与 spec「发出的原文」表逐字一致。
 * 2. 收不回的不经确认条发不出去。
 * 3. 草稿照原文时不附，改过才附；建议答案点了只填不发。
 * 4. 没有提供者、这场发不出去、已经答过——三种情况卡片都点不动。
 */

import { beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import i18n from '@/i18n';
import {
  DecisionCard,
  DecisionCardContext,
  type DecisionAnswer,
  type DecisionCardHost,
} from '../DecisionCard';
import { composeAnswer, loadYaml, parseDecisionBlock, type DecisionBlock } from '@/utils/decisionBlock';
import { DEMOS } from '@/utils/__tests__/decisionDemos';

let blocks: Record<string, DecisionBlock>;

beforeAll(async () => {
  await i18n.changeLanguage('en');
  const yaml = await loadYaml();
  blocks = {};
  for (const [k, src] of Object.entries(DEMOS)) {
    const r = parseDecisionBlock(src.trim(), yaml);
    if (r.ok) blocks[k] = r.block;
  }
});

function host(over: Partial<DecisionCardHost> = {}): DecisionCardHost & { answer: ReturnType<typeof vi.fn> } {
  return {
    canAnswer: true,
    blockedReason: null,
    answerOf: () => null,
    answer: vi.fn(),
    ...over,
  } as DecisionCardHost & { answer: ReturnType<typeof vi.fn> };
}

function renderCard(id: string, h: DecisionCardHost | null = host()) {
  const card = <DecisionCard block={blocks[id]} recordId="r1" />;
  return render(h ? <DecisionCardContext.Provider value={h}>{card}</DecisionCardContext.Provider> : card);
}

const options = () => screen.getAllByTestId('decision-option');
const answerBtn = () => screen.getByTestId('decision-answer') as HTMLButtonElement;

describe('4 型点选后交出的原文', () => {
  it('single-choice：点即答，带 label 与 effect', () => {
    const h = host();
    renderCard('single-choice', h);
    fireEvent.click(options()[0]);
    expect(h.answer).toHaveBeenCalledWith(
      'r1',
      '【answer】A · 一起改，旧地址自动跳转 —— 路由改成 #/teams，打开 #/teaming 自动跳到新地址，旧书签照常能用'
    );
  });

  it('multi-choice：未勾时按钮灰，勾两项后逐项列出', () => {
    const h = host();
    renderCard('multi-choice', h);
    expect(answerBtn().disabled).toBe(true);
    expect(answerBtn().textContent).toBe('Pick at least one');
    fireEvent.click(options()[0].querySelector('input')!);
    fireEvent.click(options()[2].querySelector('input')!);
    expect(answerBtn().textContent).toBe('Answer with 2 picked');
    fireEvent.click(answerBtn());
    const b = blocks['multi-choice'];
    expect(h.answer).toHaveBeenCalledWith('r1', composeAnswer(b, [b.options[0], b.options[2]], ''));
  });

  it('multi-choice：Select all 勾上全部', () => {
    renderCard('multi-choice');
    fireEvent.click(screen.getByTestId('decision-toggle-all'));
    expect(answerBtn().textContent).toBe('Answer with 3 picked');
    expect(screen.getByTestId('decision-toggle-all').textContent).toBe('Clear all');
  });

  it('text-answer：建议答案点了只填不发，按 Answer 才发文字', () => {
    const h = host();
    renderCard('text-answer-suggestions', h);
    fireEvent.click(screen.getAllByTestId('decision-suggestion')[1]);
    expect(h.answer).not.toHaveBeenCalled();
    expect((screen.getByTestId('decision-input') as HTMLInputElement).value).toBe('zenith-sit.example.com');
    fireEvent.click(answerBtn());
    expect(h.answer).toHaveBeenCalledWith('r1', '【answer】zenith-sit.example.com');
  });

  it('choice-and-text multi：勾选并写字，隔空行接在后面', () => {
    const h = host();
    renderCard('choice-and-text-multi', h);
    fireEvent.click(options()[1].querySelector('input')!);
    fireEvent.change(screen.getByTestId('decision-input'), { target: { value: '另外把截图换成新的' } });
    fireEvent.click(answerBtn());
    expect(h.answer).toHaveBeenCalledWith(
      'r1',
      '【answer】\n- B · 补 CHANGELOG —— 在 CHANGELOG.md 加 1.4.111 一节，列这次的 3 个修复\n\n另外把截图换成新的'
    );
  });
});

describe('收不回的先确认', () => {
  it('点下去先出确认条，Yes, do it 才发', () => {
    const h = host();
    renderCard('single-choice-irreversible', h);
    fireEvent.click(options()[0]);
    expect(h.answer).not.toHaveBeenCalled();
    expect(screen.getByTestId('decision-confirm').textContent).toContain("This can't be undone — do it?");
    expect(screen.getByTestId('decision-confirm').textContent).toContain('A · 发布 — 打 v1.4.111 tag');
    fireEvent.click(screen.getByTestId('decision-confirm-yes'));
    expect(h.answer).toHaveBeenCalledWith('r1', '【answer】A · 发布 —— 打 v1.4.111 tag 并上传 PyPI，发出去收不回');
  });

  it('可撤回的那项点了直接发', () => {
    const h = host();
    renderCard('single-choice-irreversible', h);
    fireEvent.click(options()[1]);
    expect(screen.queryByTestId('decision-confirm')).toBeNull();
    expect(h.answer).toHaveBeenCalledTimes(1);
  });

  it('整卡告警橙框，小字后跟 Can\'t be undone', () => {
    const { container } = renderCard('single-choice-irreversible');
    const card = screen.getByTestId('decision-card');
    expect(card.className).toContain('border-accent-warning');
    expect(container.textContent).toContain("Pick one · Can't be undone");
    expect(container.textContent).toContain('Recommended');
  });
});

describe('草稿：先只读，As is / Edit', () => {
  it('先以只读文字显示；照原文时不附文字', () => {
    const h = host();
    renderCard('choice-and-text-draft', h);
    expect(screen.getByTestId('decision-draft').textContent).toContain('触发：Stop');
    expect(screen.queryByTestId('decision-draft-input')).toBeNull();
    fireEvent.click(options()[0]);
    fireEvent.click(answerBtn());
    const plain = '【answer】A · 就这样 —— 照草稿原文写进 ~/.frago/hook/builtin-rules.json，下一轮生效';
    expect(h.answer).toHaveBeenLastCalledWith('r1', plain);
  });

  it('点了 Edit 但一字没改，也算没写', () => {
    const h = host();
    renderCard('choice-and-text-draft', h);
    fireEvent.click(screen.getByTestId('decision-draft-edit'));
    fireEvent.click(options()[0]);
    fireEvent.click(answerBtn());
    expect(h.answer).toHaveBeenLastCalledWith(
      'r1',
      '【answer】A · 就这样 —— 照草稿原文写进 ~/.frago/hook/builtin-rules.json，下一轮生效'
    );
  });

  it('Edit 改过才附，多行包进代码块', () => {
    const h = host();
    renderCard('choice-and-text-draft', h);
    fireEvent.click(screen.getByTestId('decision-draft-edit'));
    const box = screen.getByTestId('decision-draft-input') as HTMLTextAreaElement;
    expect(box.value).toBe(blocks['choice-and-text-draft'].draft);
    fireEvent.change(box, { target: { value: '触发：Stop\n条件：改过了' } });
    fireEvent.click(options()[1]);
    fireEvent.click(answerBtn());
    expect(h.answer).toHaveBeenCalledWith(
      'r1',
      '【answer】B · 改一下 —— 按你在框里改过的文字写进 builtin-rules.json\n\n```\n触发：Stop\n条件：改过了\n```'
    );
  });

  it('agent 写的选项与 As is / Edit 并存', () => {
    renderCard('choice-and-text-draft');
    expect(options()).toHaveLength(3);
    expect(screen.getByTestId('decision-draft-asis')).toBeTruthy();
  });
});

describe('什么时候点不动', () => {
  it('没有提供者（Teams 页右栏）：只读', () => {
    renderCard('single-choice', null);
    expect(screen.getByTestId('decision-card').dataset.state).toBe('read-only');
    expect(options().every((o) => (o as HTMLButtonElement).disabled)).toBe(true);
  });

  it('这场发不出去：可看不可点，写输入区同一句原因', () => {
    renderCard('single-choice', host({ canAnswer: false, blockedReason: 'workbench.composer.blockedNoSession' }));
    expect(options().every((o) => (o as HTMLButtonElement).disabled)).toBe(true);
    expect(screen.getByTestId('decision-blocked').textContent).toBe(
      i18n.t('workbench.composer.blockedNoSession')
    );
  });

  it('卡片答过：选中项高亮，其余变淡，底部写明作答时刻', () => {
    const at = new Date(2026, 8, 24, 13, 56, 53).getTime();
    const b = blocks['single-choice-irreversible'];
    const answered: DecisionAnswer = { kind: 'card', text: composeAnswer(b, [b.options[1]], ''), at };
    renderCard('single-choice-irreversible', host({ answerOf: () => answered }));
    const [a, bOpt] = options();
    expect(bOpt.dataset.on).toBe('true');
    expect(a.dataset.on).toBeUndefined();
    expect(a.className).toContain('opacity-45');
    expect((a as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId('decision-answered').textContent).toBe(
      'You answered at 13:56:53 — sent to the session as your message below'
    );
  });

  it('人自己打字回了：锁住、不高亮', () => {
    renderCard('single-choice', host({ answerOf: () => ({ kind: 'own-words', text: '先别动', at: 1 }) }));
    expect(options().some((o) => o.dataset.on)).toBe(false);
    expect(options().every((o) => (o as HTMLButtonElement).disabled)).toBe(true);
    expect(screen.getByTestId('decision-answered').textContent).toBe('You replied in your own words below');
  });

  it('答过的草稿卡：草稿变成只读的最终文字', () => {
    const b = blocks['choice-and-text-draft'];
    const text = composeAnswer(b, [b.options[1]], '改过的\n两行');
    renderCard('choice-and-text-draft', host({ answerOf: () => ({ kind: 'card', text, at: 1 }) }));
    expect(screen.queryByTestId('decision-draft-edit')).toBeNull();
    expect(screen.getByTestId('decision-card').textContent).toContain('改过的\n两行');
  });
});

describe('视觉规矩', () => {
  it('卡片上没有实心绿', () => {
    const { container } = renderCard('multi-choice');
    expect(container.querySelector('.bg-accent-primary')).toBeNull();
  });

  it('队友请求卡：From your teammate，原话与会改什么两框', () => {
    const { container } = renderCard('single-choice-teammate');
    expect(container.textContent).toContain('From your teammate');
    expect(container.textContent).toContain('Their request, as relayed');
    expect(container.textContent).toContain('What it would change here');
    expect(container.textContent).toContain('Pick one');
  });
});
