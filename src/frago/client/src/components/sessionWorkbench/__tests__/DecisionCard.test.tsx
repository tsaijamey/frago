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
  it('single-choice：点选项仅选中不立即发送，带可选输入框，点 Answer 按钮才发送', () => {
    const h = host();
    renderCard('single-choice', h);
    expect(screen.getByTestId('decision-input')).toBeTruthy();
    expect(answerBtn().disabled).toBe(true);
    fireEvent.click(options()[0]);
    expect(h.answer).not.toHaveBeenCalled();
    expect(options()[0].dataset.on).toBe('true');
    expect(answerBtn().disabled).toBe(false);
    fireEvent.click(answerBtn());
    expect(h.answer).toHaveBeenCalledWith(
      'r1',
      '【answer】A · 一起改，旧地址自动跳转 —— 路由改成 #/teams，打开 #/teaming 自动跳到新地址，旧书签照常能用'
    );
  });

  it('single-choice：选选项并补充输入框文字，点 Answer 一并发送', () => {
    const h = host();
    renderCard('single-choice', h);
    fireEvent.click(options()[0]);
    fireEvent.change(screen.getByTestId('decision-input'), { target: { value: '顺便把旧文档链接也查一遍' } });
    fireEvent.click(answerBtn());
    expect(h.answer).toHaveBeenCalledWith(
      'r1',
      '【answer】A · 一起改，旧地址自动跳转 —— 路由改成 #/teams，打开 #/teaming 自动跳到新地址，旧书签照常能用\n\n顺便把旧文档链接也查一遍'
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
  it('选中不可撤回项后点 Answer 先出确认条，Yes, do it 才发', () => {
    const h = host();
    renderCard('single-choice-irreversible', h);
    fireEvent.click(options()[0]);
    expect(h.answer).not.toHaveBeenCalled();
    expect(screen.queryByTestId('decision-confirm')).toBeNull();
    fireEvent.click(answerBtn());
    expect(h.answer).not.toHaveBeenCalled();
    expect(screen.getByTestId('decision-confirm').textContent).toContain("This can't be undone — do it?");
    expect(screen.getByTestId('decision-confirm').textContent).toContain('A · 发布 — 打 v1.4.111 tag');
    fireEvent.click(screen.getByTestId('decision-confirm-yes'));
    expect(h.answer).toHaveBeenCalledWith('r1', '【answer】A · 发布 —— 打 v1.4.111 tag 并上传 PyPI，发出去收不回');
  });

  it('可撤回的那项选中后点 Answer 直接发', () => {
    const h = host();
    renderCard('single-choice-irreversible', h);
    fireEvent.click(options()[1]);
    expect(h.answer).not.toHaveBeenCalled();
    fireEvent.click(answerBtn());
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
  // 2026-11-14：正在等人拍板的那一张走 `.ui-decision-spotlight`——全流对比度最高的一处。
  // 聚光是给"还要你动手"的：答过、只读、这场发不出去的那几张必须退回普通卡，
  // 否则一处亮着就不算信号了。
  describe('决策聚光：只有还在等你拍板的那一张亮着', () => {
    it('还能答的卡片带 ui-decision-spotlight', () => {
      renderCard('single-choice');
      const card = screen.getByTestId('decision-card');
      expect(card.dataset.state).toBe('open');
      expect(card.className).toContain('ui-decision-spotlight');
    });

    it('答过的卡片不带聚光，退回普通卡', () => {
      const b = blocks['single-choice'];
      const answered: DecisionAnswer = { kind: 'card', text: composeAnswer(b, [b.options[0]], ''), at: 1 };
      renderCard('single-choice', host({ answerOf: () => answered }));
      const card = screen.getByTestId('decision-card');
      expect(card.dataset.state).toBe('card');
      expect(card.className).not.toContain('ui-decision-spotlight');
    });

    it('这场发不出去（只读）的卡片不带聚光', () => {
      renderCard('single-choice', null);
      const card = screen.getByTestId('decision-card');
      expect(card.dataset.state).toBe('read-only');
      expect(card.className).not.toContain('ui-decision-spotlight');
    });
  });

  it('卡片未选未填时 Answer 按钮保持主色边框透明底；选中文本或输入后直接 fill 主色', () => {
    const { container } = renderCard('single-choice');
    // 未选未填：保持主色边框透明底，卡片无实心主色
    expect(container.querySelector('.bg-accent-primary')).toBeNull();
    expect(answerBtn().className).toContain('border-accent-primary');
    expect(answerBtn().className).toContain('text-accent-primary');
    expect(answerBtn().className).toContain('bg-transparent');
    expect(answerBtn().className).toContain('h-[32px]');

    // 选中选项后：按钮直接 fill 主色
    fireEvent.click(options()[0]);
    expect(answerBtn().className).toContain('bg-accent-primary');
    expect(answerBtn().className).toContain('text-[var(--text-on-accent)]');

    // 取消选中后填入输入框内容：同样直接 fill 主色
    fireEvent.click(options()[0]);
    expect(answerBtn().className).toContain('bg-transparent');
    fireEvent.change(screen.getByTestId('decision-input'), { target: { value: '自定义答复' } });
    expect(answerBtn().className).toContain('bg-accent-primary');
  });

  it('队友请求卡：From your teammate，原话与会改什么两框', () => {
    const { container } = renderCard('single-choice-teammate');
    expect(container.textContent).toContain('From your teammate');
    expect(container.textContent).toContain('Their request, as relayed');
    expect(container.textContent).toContain('What it would change here');
    expect(container.textContent).toContain('Pick one');
  });

  // 2026-11-13：KEY 方块原先是写死的 w-[18px]，11 号等宽字下只装得下两三个字符，
  // HOLD 就往外溢、IMPL_DYNAMIC 直接压住标题并越过选项行边框。
  describe('KEY 方块：短 KEY 保持方块，长 KEY 撑开截断不越界', () => {
    const keyBoxOf = (i: number) => options()[i].querySelector('span[title]') as HTMLElement;
    /** 写死的宽度是这次要根除的东西；`min-w-[18px]` 不算，逐 token 比对。 */
    const hasFixedWidth = (box: HTMLElement) =>
      box.className.split(/\s+/).some((c) => /^w-\[/.test(c));

    it('短 KEY：min-w-[18px] 顶住方块观感，不设死宽度', () => {
      renderCard('single-choice');
      const box = keyBoxOf(0);
      expect(box.className).toContain('min-w-[18px]');
      expect(box.className).toContain('max-w-[72px]');
      expect(box.className).toContain('overflow-hidden');
      expect(box.className).toContain('px-1');
      // 关键：不再有写死的宽度
      expect(hasFixedWidth(box)).toBe(false);
    });

    it('长 KEY：截断内层用 truncate，悬停给完整值', () => {
      renderCard('single-choice-long-key');
      const box = keyBoxOf(0);
      expect(box.getAttribute('title')).toBe('IMPL_DYNAMIC');
      expect(box.textContent).toBe('IMPL_DYNAMIC');
      expect(box.querySelector('.truncate')).toBeTruthy();
    });

    it('三种题型（单选/多选/选加写）的 KEY 方块共用同一套边界', () => {
      for (const id of ['single-choice-long-key', 'multi-choice-long-key', 'choice-and-text-long-key']) {
        const { unmount } = renderCard(id);
        const box = keyBoxOf(0);
        expect(box.className).toContain('min-w-[18px]');
        expect(box.className).toContain('max-w-[72px]');
        expect(hasFixedWidth(box)).toBe(false);
        unmount();
      }
    });

    it('多选：勾选框与 KEY 方块都在，两者之间留 gap-2 的间距', () => {
      renderCard('multi-choice-long-key');
      const row = options()[0];
      expect(row.querySelector('input[type="checkbox"]')).toBeTruthy();
      expect(row.className).toContain('gap-2');
      expect(keyBoxOf(0).getAttribute('title')).toBe('IMPL_DYNAMIC');
    });
  });
});
