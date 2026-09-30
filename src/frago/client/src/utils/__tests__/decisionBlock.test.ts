import { beforeAll, describe, expect, it } from 'vitest';
import {
  composeAnswer,
  loadYaml,
  parseCardAnswer,
  parseDecisionBlock,
  pickedFromAnswer,
  splitTrailingBlock,
  trailingDecision,
  writtenFromAnswer,
  type DecisionBlock,
  type ParseResult,
  type Yaml,
} from '../decisionBlock';
import { DEMOS, wrap } from './decisionDemos';

const FENCE = '```';

let yaml: Yaml;
beforeAll(async () => {
  yaml = await loadYaml();
});

const parse = (src: string): ParseResult => parseDecisionBlock(src.trim(), yaml);
const ok = (src: string): DecisionBlock => {
  const r = parse(src);
  if (!r.ok) throw new Error(`expected ok, got ${r.reason.code}`);
  return r.block;
};
const reasonOf = (src: string) => {
  const r = parse(src);
  if (r.ok) throw new Error('expected broken');
  return r.reason;
};

describe('splitTrailingBlock', () => {
  it('切出末尾区块，正文与区块分开', () => {
    const s = splitTrailingBlock(wrap('测试全过。', 'type: single-choice'));
    expect(s).toEqual({ body: '测试全过。', raw: 'type: single-choice' });
  });

  it('区块后面还有正文就不认', () => {
    const t = wrap('前文', 'type: single-choice') + '\n\n还有一句';
    expect(splitTrailingBlock(t)).toBeNull();
  });

  it('两个区块只认最末尾那个，前一个留在正文里', () => {
    const first = `${FENCE}answer-needed-by-human\ntype: text-answer\n${FENCE}`;
    const t = wrap(`开头\n\n${first}\n\n中间`, 'type: multi-choice');
    const s = splitTrailingBlock(t)!;
    expect(s.raw).toBe('type: multi-choice');
    expect(s.body).toContain(first);
    expect(s.body.endsWith('中间')).toBe(true);
  });

  it('没有区块、或只是别的代码块，返回 null', () => {
    expect(splitTrailingBlock('普通回复')).toBeNull();
    expect(splitTrailingBlock(`${FENCE}yaml\ntype: single-choice\n${FENCE}`)).toBeNull();
  });

  it('整条回复只有区块、末尾带空白也认', () => {
    const s = splitTrailingBlock(`${FENCE}answer-needed-by-human\ntype: x\n${FENCE}\n\n  `);
    expect(s).toEqual({ body: '', raw: 'type: x' });
  });
});

describe('原型 10 张演示卡', () => {
  it('8 张通过、2 张写坏', () => {
    const passed = Object.entries(DEMOS)
      .filter(([, y]) => trailingDecision(wrap('正文', y), yaml)?.result.ok)
      .map(([k]) => k);
    expect(passed).toEqual([
      'single-choice',
      'single-choice-irreversible',
      'single-choice-teammate',
      'single-choice-done-or-cant',
      'multi-choice',
      'text-answer-suggestions',
      'choice-and-text-draft',
      'choice-and-text-multi',
    ]);
  });

  it('旧类型名：原因写明不在 4 型里', () => {
    expect(reasonOf(DEMOS.broken)).toEqual({
      code: 'type',
      params: {
        type: 'approve-irreversible',
        types: 'single-choice, multi-choice, text-answer, choice-and-text',
      },
    });
  });

  it('坏缩进：原因取 js-yaml 的报错与行号', () => {
    expect(reasonOf(DEMOS['broken-yaml'])).toEqual({
      code: 'yaml',
      params: { detail: 'bad indentation of a sequence entry (line 9)' },
    });
  });

  it('字段按原样读出，标记落到位', () => {
    const irr = ok(DEMOS['single-choice-irreversible']);
    expect(irr.options[0]).toEqual({
      key: 'A',
      label: '发布',
      effect: '打 v1.4.111 tag 并上传 PyPI，发出去收不回',
      reversible: false,
      recommended: true,
    });
    expect(irr.options[1].reversible).toBe(true);

    const tm = ok(DEMOS['single-choice-teammate']);
    expect(tm.fromTeammate).toBe(true);
    expect(tm.request).toContain('Stop 收尾提醒');
    expect(tm.changes).toContain('builtin-rules.json');

    const draft = ok(DEMOS['choice-and-text-draft']);
    expect(draft.draft?.split('\n')).toHaveLength(3);
    expect(draft.draft?.endsWith('\n')).toBe(false);

    expect(ok(DEMOS['choice-and-text-multi']).multi).toBe(true);
    expect(ok(DEMOS['text-answer-suggestions']).suggestions).toEqual([
      'zenith.example.com',
      'zenith-sit.example.com',
    ]);
  });

  it('以 JSON 规则集解析：日期、版本号原样是字符串', () => {
    const b = ok(`
type: single-choice
question: 2026-09-24 发不发？
why: 2026-09-24
options:
  - key: A
    label: 1.10
    effect: 2026-09-24`);
    expect(b.why).toBe('2026-09-24');
    expect(b.options[0].effect).toBe('2026-09-24');
    expect(b.options[0].label).toBe('1.1');
  });
});

describe('校验清单', () => {
  const cases: [string, string, string][] = [
    ['不是键值块', '- a\n- b', 'notMapping'],
    ['question 缺', 'type: single-choice\noptions:\n  - {key: A, label: a, effect: e}', 'question'],
    ['options 不是列表', 'type: single-choice\nquestion: q\noptions: A', 'optionsNotList'],
    ['该有 options 却没有', 'type: multi-choice\nquestion: q', 'needsOptions'],
    ['text-answer 带 options', 'type: text-answer\nquestion: q\noptions:\n  - {key: A, label: a, effect: e}', 'textAnswerNoOptions'],
    ['选项缺 effect', 'type: single-choice\nquestion: q\noptions:\n  - {key: A, label: a}', 'optionFields'],
    [
      '推荐多于一个',
      'type: single-choice\nquestion: q\noptions:\n  - {key: A, label: a, effect: e, recommended: true}\n  - {key: B, label: b, effect: e, recommended: true}',
      'recommendedMany',
    ],
    ['from 不是 teammate', 'type: text-answer\nquestion: q\nfrom: boss', 'fromValue'],
    ['draft 用在单选上', 'type: single-choice\nquestion: q\ndraft: x\noptions:\n  - {key: A, label: a, effect: e}', 'draftPlace'],
    ['suggestions 不是列表', 'type: text-answer\nquestion: q\nsuggestions: a', 'suggestionsPlace'],
    ['suggestions 不在 text-answer 上', 'type: choice-and-text\nquestion: q\nsuggestions: [a]\noptions:\n  - {key: A, label: a, effect: e}', 'suggestionsPlace'],
    ['multi 不在 choice-and-text 上', 'type: multi-choice\nquestion: q\nmulti: true\noptions:\n  - {key: A, label: a, effect: e}', 'multiPlace'],
  ];
  it.each(cases)('%s', (_name, src, code) => {
    expect(reasonOf(src).code).toBe(code);
  });

  it('key 重复不检查，照画', () => {
    const b = ok('type: single-choice\nquestion: q\noptions:\n  - {key: A, label: a, effect: e}\n  - {key: A, label: b, effect: f}');
    expect(b.options.map((o) => o.key)).toEqual(['A', 'A']);
  });

  it('规格外的旧字段不画、也不判写坏', () => {
    const b = ok('type: text-answer\nquestion: q\nsteps: [1, 2]\nfree_text: true');
    expect(b.type).toBe('text-answer');
  });

  it('没有 from: teammate 时 request / changes 不带出来', () => {
    const b = ok('type: text-answer\nquestion: q\nrequest: r\nchanges: c');
    expect(b.request).toBeNull();
    expect(b.changes).toBeNull();
  });
});

describe('composeAnswer', () => {
  it('single-choice 带 label 与 effect 原文', () => {
    const b = ok(DEMOS['single-choice-irreversible']);
    expect(composeAnswer(b, [b.options[0]], '')).toBe(
      '【answer】A · 发布 —— 打 v1.4.111 tag 并上传 PyPI，发出去收不回'
    );
  });

  it('multi-choice 逐项列出', () => {
    const b = ok(DEMOS['multi-choice']);
    expect(composeAnswer(b, [b.options[0], b.options[2]], '')).toBe(
      '【answer】\n- A · 轮换 57b060f7 里推上去的两个 Lenovo API key —— frago todo add 一条，优先级 high\n' +
        '- C · 补完 todo 清理的遗留 —— frago todo add 一条，附 29 条未写、4 条存疑、2 条重复的清单'
    );
  });

  it('text-answer 只有文字', () => {
    const b = ok(DEMOS['text-answer-suggestions']);
    expect(composeAnswer(b, [], 'zenith.example.com')).toBe('【answer】zenith.example.com');
  });

  it('choice-and-text：选项与文字隔一个空行，多行文字包进代码块', () => {
    const multi = ok(DEMOS['choice-and-text-multi']);
    expect(composeAnswer(multi, [multi.options[1]], '另外把截图换成新的')).toBe(
      '【answer】\n- B · 补 CHANGELOG —— 在 CHANGELOG.md 加 1.4.111 一节，列这次的 3 个修复\n\n另外把截图换成新的'
    );
    const draft = ok(DEMOS['choice-and-text-draft']);
    expect(composeAnswer(draft, [draft.options[1]], '第一行\n第二行')).toBe(
      '【answer】B · 改一下 —— 按你在框里改过的文字写进 builtin-rules.json\n\n```\n第一行\n第二行\n```'
    );
    expect(composeAnswer(draft, [], '只写不选')).toBe('【answer】只写不选');
  });
});

describe('从答复认回', () => {
  it('单选、多选都认回选中项，写的字去掉围栏', () => {
    const draft = ok(DEMOS['choice-and-text-draft']);
    const a = composeAnswer(draft, [draft.options[1]], '第一行\n第二行');
    expect(pickedFromAnswer(a, draft)).toEqual([1]);
    expect(writtenFromAnswer(a, draft)).toBe('第一行\n第二行');

    const multi = ok(DEMOS['multi-choice']);
    const m = composeAnswer(multi, [multi.options[0], multi.options[2]], '');
    expect(pickedFromAnswer(m, multi)).toEqual([0, 2]);
    expect(writtenFromAnswer(m, multi)).toBe('');
  });

  it('不是卡片发的，或者认不出，就当没选', () => {
    const b = ok(DEMOS['single-choice']);
    expect(pickedFromAnswer('A', b)).toEqual([]);
    expect(pickedFromAnswer('【answer】A · 别的', b)).toEqual([]);
  });
});

describe('parseCardAnswer：不看卡片，只凭原文拆回来排版', () => {
  const strip = (o: { key: string; label: string; effect: string }) => ({
    key: o.key,
    label: o.label,
    effect: o.effect,
  });

  it('单选、多选、选加写、只写，都能从 composeAnswer 的原文拆回', () => {
    const single = ok(DEMOS['single-choice-irreversible']);
    expect(parseCardAnswer(composeAnswer(single, [single.options[0]], ''))).toEqual({
      picked: [strip(single.options[0])],
      written: '',
    });

    const multi = ok(DEMOS['multi-choice']);
    expect(
      parseCardAnswer(composeAnswer(multi, [multi.options[0], multi.options[2]], ''))
    ).toEqual({ picked: [strip(multi.options[0]), strip(multi.options[2])], written: '' });

    const cat = ok(DEMOS['choice-and-text-multi']);
    expect(parseCardAnswer(composeAnswer(cat, [cat.options[1]], '另外把截图换成新的'))).toEqual({
      picked: [strip(cat.options[1])],
      written: '另外把截图换成新的',
    });

    const draft = ok(DEMOS['choice-and-text-draft']);
    expect(parseCardAnswer(composeAnswer(draft, [draft.options[1]], '第一行\n第二行'))).toEqual({
      picked: [strip(draft.options[1])],
      written: '第一行\n第二行',
    });
    expect(parseCardAnswer('【answer】只写不选')).toEqual({ picked: [], written: '只写不选' });
  });

  it('不是卡片发的，或者什么都没有，返回 null', () => {
    expect(parseCardAnswer('A · 发布 —— 打 tag')).toBeNull();
    expect(parseCardAnswer('【answer】')).toBeNull();
    expect(parseCardAnswer('【answer】\n- 不像选项的一行')).toBeNull();
  });
});
