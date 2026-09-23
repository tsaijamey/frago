/**
 * 「这一家为什么挑不了」那一句，跟着界面语言走。
 *
 * 钉住的是一条界线：服务端只说是哪一种情况，说成什么话由界面决定。从前服务端发的是
 * 现成的中文句子，英文界面上那一行就冒出一句中文——而且两侧都修不了，前端拿到的是
 * 一整句话看不出它在说什么，后端不知道此刻的人在读哪种语言。
 *
 * 这几条断言一旦红，多半是有人又在服务端那边把成品文案发了下来。
 */

import { beforeEach, describe, expect, it } from 'vitest';
import i18n from '@/i18n';
import { agentReasonText } from '../useAgentClients';

beforeEach(async () => {
  await i18n.changeLanguage('en');
});

describe('挑不了的理由', () => {
  it('英文界面说英文', async () => {
    expect(agentReasonText('agent.notReadable')).toMatch(/session records/);
    expect(agentReasonText('agent.notInstalled')).toMatch(/Not found on this machine/);
  });

  it('中文界面说中文', async () => {
    await i18n.changeLanguage('zh');
    expect(agentReasonText('agent.notReadable')).toMatch(/读不进工作台/);
    expect(agentReasonText('agent.notInstalled')).toMatch(/本机没找到这个命令/);
  });

  it('英文界面里一个汉字都不该有', () => {
    const codes = [
      'agent.notInstalled',
      'agent.notReadable',
      'agent.unknownInstall',
      'agent.noKernel',
      'agent.noConnection',
    ];
    for (const code of codes) {
      const said = agentReasonText(code) ?? '';
      expect(said, `${code} 在英文界面下混进了汉字：${said}`).not.toMatch(/[一-鿿]/);
    }
  });

  it('没有理由就是没有，不编一句出来', () => {
    expect(agentReasonText(null)).toBeNull();
    expect(agentReasonText(undefined)).toBeNull();
    expect(agentReasonText('')).toBeNull();
  });

  it('不认得的代号原样显示——看得出是哪一种情况，好过一片空白', () => {
    expect(agentReasonText('agent.somethingNewNobodyTranslatedYet')).toBe(
      'agent.somethingNewNobodyTranslatedYet',
    );
  });
});
