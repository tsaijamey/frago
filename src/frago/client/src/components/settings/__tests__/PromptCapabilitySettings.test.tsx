/**
 * Prompting 分区的两张卡。这里钉住 09-24 视觉打磨定下的几件事：
 *
 * 1. 分区顶上那段独立介绍不再渲染——它和分区标题下的短说明是同一件事说两遍；
 * 2. LightAgent 在跑时，徽章里是一颗圆点而不是打勾圆圈，模型名加重；
 * 3. 开关说明里带着存储位置 `hook_review.enabled`，以行内代码显示；
 * 4. 四种 LightAgent 状态的徽章文字各自正确。
 *
 * 走真的 i18n（英文），因为要验的正是文案里的 <b> 与 <c> 标签被渲染成元素。
 */

import { beforeAll, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import i18n from '@/i18n';
import type { HookReviewStatus, LightAgentStatus } from '@/api';

const getHookReviewStatus = vi.fn();

vi.mock('@/api', () => ({
  getHookReviewStatus: () => getHookReviewStatus(),
  setHookReviewEnabled: vi.fn(),
}));

import PromptCapabilitySettings from '../PromptCapabilitySettings';

function statusOf(status: LightAgentStatus): HookReviewStatus {
  return {
    enabled: status !== 'disabled',
    env_off: false,
    static_rules: { available: true, count: 42 },
    lightagent: {
      status,
      profile_name: 'DeepSeek',
      model: 'deepseek-v4-flash',
      detail: null,
    },
  };
}

async function renderWith(status: LightAgentStatus) {
  getHookReviewStatus.mockResolvedValue(statusOf(status));
  const view = render(<PromptCapabilitySettings onConfigureProfile={() => {}} />);
  await screen.findByText('LightAgent');
  return view;
}

beforeAll(async () => {
  await i18n.changeLanguage('en');
});

describe('PromptCapabilitySettings', () => {
  it('no longer renders the standalone intro paragraph', async () => {
    const { container } = await renderWith('enabled');
    expect(container.querySelector('.settings-cap-intro')).toBeNull();
    expect(screen.getByText(/42 rules matching/)).toBeTruthy();
  });

  it('shows a dot instead of a check icon on the Running badge, and sets the model in bold', async () => {
    const { container } = await renderWith('enabled');
    const badge = screen.getByText('Running').closest('.settings-cap-badge');
    expect(badge?.querySelector('.settings-cap-dot')).not.toBeNull();
    expect(badge?.querySelector('svg')).toBeNull();
    const bold = container.querySelector('.settings-cap-body b');
    expect(bold?.textContent).toBe('deepseek-v4-flash');
  });

  it('names the stored field as inline code in the switch description', async () => {
    const { container } = await renderWith('enabled');
    const codes = [...container.querySelectorAll('.settings-cap-switch-desc code')].map(
      (el) => el.textContent,
    );
    expect(codes).toContain('hook_review.enabled');
  });

  it.each([
    ['enabled', 'Running'],
    ['disabled', 'Turned off'],
    ['not_configured', 'Not configured'],
    ['no_key', 'No api key'],
  ] as const)('labels the %s badge as "%s"', async (status, label) => {
    const { container } = await renderWith(status);
    const badges = [...container.querySelectorAll('.settings-cap-badge')].map((el) => el.textContent);
    expect(badges).toContain(label);
    const hasDot = container.querySelector('.settings-cap-dot') !== null;
    expect(hasDot).toBe(status === 'enabled');
  });
});
