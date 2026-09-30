/**
 * 与 frago-core 收尾检查共用的样本。
 *
 * 收尾检查（frago-core `src/card.rs`）照这里的判法推回写坏的区块，两边各留一份同名
 * `fixtures/decision-blocks.json`。改了这边的判法，样本和那边的代码要一起改，否则就会
 * 出现页面判写坏、收尾却放行（或反过来）的情况。
 */
import { beforeAll, describe, expect, it } from 'vitest';
import { loadYaml, parseDecisionBlock, type Yaml } from '../decisionBlock';
import samples from './fixtures/decision-blocks.json';

let yaml: Yaml;
beforeAll(async () => {
  yaml = await loadYaml();
});

describe('shared samples with the Stop-time card check', () => {
  it('covers every broken reason', () => {
    const codes = new Set(samples.map((s) => s.expect));
    for (const code of [
      'ok',
      'yaml',
      'notMapping',
      'type',
      'question',
      'optionsNotList',
      'needsOptions',
      'textAnswerNoOptions',
      'optionFields',
      'recommendedMany',
      'fromValue',
      'draftPlace',
      'suggestionsPlace',
      'multiPlace',
    ]) {
      expect(codes.has(code), code).toBe(true);
    }
  });

  it.each(samples)('$name → $expect', ({ raw, expect: want }) => {
    const r = parseDecisionBlock(raw, yaml);
    expect(r.ok ? 'ok' : r.reason.code).toBe(want);
  });
});
