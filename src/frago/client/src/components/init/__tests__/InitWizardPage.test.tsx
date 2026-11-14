import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import i18n from '@/i18n';
import { useDataStore } from '@/stores/dataStore';

const getEndpointPresets = vi.fn();
const getCliAgentsStatus = vi.fn();
const createProfile = vi.fn();
const getProfiles = vi.fn();
const bindRole = vi.fn();
const setHookReviewEnabled = vi.fn();
const markInitComplete = vi.fn();

vi.mock('@/api/client', () => ({
  getEndpointPresets: () => getEndpointPresets(),
  getCliAgentsStatus: () => getCliAgentsStatus(),
  createProfile: (payload: unknown) => createProfile(payload),
  getProfiles: () => getProfiles(),
  bindRole: (role: string, id: string) => bindRole(role, id),
  setHookReviewEnabled: (enabled: boolean) => setHookReviewEnabled(enabled),
  markInitComplete: () => markInitComplete(),
}));

import { InitWizardPage } from '../InitWizardPage';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

beforeEach(async () => {
  vi.clearAllMocks();
  await i18n.changeLanguage('zh');
  useDataStore.setState({
    config: {
      theme: 'dark',
      language: 'zh',
      agent_language: '',
      max_history_items: 100,
      shortcuts: { send: 'Ctrl+Enter', clear: 'Ctrl+L', settings: 'Ctrl+,' },
    },
    updateConfig: vi.fn().mockResolvedValue(undefined),
    setLanguage: vi.fn(),
  });
  getEndpointPresets.mockResolvedValue({
    presets: [
      {
        id: 'deepseek',
        display_name: 'DeepSeek (deepseek-chat)',
        base_url: 'https://api.deepseek.com/anthropic',
        default_model: 'deepseek-chat',
        sonnet_model: 'deepseek-reason',
        haiku_model: 'deepseek-chat',
        responses_url: 'https://api.deepseek.com',
        responses_models: ['deepseek-v4-flash'],
      },
      {
        id: 'aliyun',
        display_name: 'Aliyun Bailian (qwen3-max)',
        base_url: 'https://dashscope.aliyuncs.com/apps/anthropic',
        default_model: 'qwen3-max',
        sonnet_model: 'qwen3-max',
        haiku_model: 'qwen3-max',
        responses_url: null,
        responses_models: [],
      },
    ],
  });
  getCliAgentsStatus.mockResolvedValue({ agents: [] });
  markInitComplete.mockResolvedValue({ status: 'ok', init_completed: true });
});

describe('InitWizardPage (#setup 零先验中文向导与体验打磨)', () => {
  it('默认在中文环境下 100% 呈现纯正简体中文，无硬编码英文或开发者路径黑话，且支持稍后配置跳过', async () => {
    const onComplete = vi.fn();
    const { container } = render(<InitWizardPage onComplete={onComplete} />);

    expect(screen.getByText('欢迎使用 Frago · 首次快速设置')).toBeTruthy();
    expect(screen.getByTestId('setup-card-appearance')).toBeTruthy();
    expect(screen.getByTestId('setup-card-connection')).toBeTruthy();
    expect(screen.getByText('保存并进入工作台')).toBeTruthy();
    expect(screen.getByText('稍后配置')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByText('DeepSeek 官方（推荐 · 高性价比）')).toBeTruthy();
    });

    // 高级工程参数默认折叠，避免干扰零代码普通用户
    expect(screen.queryByTestId('setup-advanced-panel')).toBeNull();

    // 确认旧版残留硬编码英文与工程黑话已彻底消除
    const fullText = container.textContent || '';
    expect(fullText).not.toContain('Provider preset');
    expect(fullText).not.toContain('Save & enter workbench');
    expect(fullText).not.toContain('(0600)');
    expect(fullText).not.toContain('~/.frago/gui_config.json');
    expect(fullText).not.toContain('edge-case recovery flow');

    fireEvent.click(screen.getByTestId('setup-skip-bottom'));

    await waitFor(() => {
      expect(markInitComplete).toHaveBeenCalledTimes(1);
      expect(onComplete).toHaveBeenCalledTimes(1);
    });
  });

  it('在填入 API 密钥模式下若未填密钥误点保存，给出清晰中文防呆提示而不静默假装成功', async () => {
    const onComplete = vi.fn();
    render(<InitWizardPage onComplete={onComplete} />);

    fireEvent.click(screen.getByTestId('setup-save-submit'));

    expect(screen.getByTestId('setup-error-banner').textContent).toContain('请先粘贴你的 API 密钥');
    expect(markInitComplete).not.toHaveBeenCalled();
    expect(onComplete).not.toHaveBeenCalled();
  });

  it('选择自定义接口地址时自动展开高级连接参数，也可手动展开编辑备注名称', async () => {
    const onComplete = vi.fn();
    render(<InitWizardPage onComplete={onComplete} />);

    expect(screen.queryByTestId('setup-advanced-panel')).toBeNull();

    fireEvent.change(screen.getByTestId('setup-preset-select'), {
      target: { value: 'custom' },
    });

    expect(screen.getByTestId('setup-advanced-panel')).toBeTruthy();
    expect((screen.getByTestId('setup-profile-name') as HTMLInputElement).value).toBe('custom');
  });

  it('填入密钥后创建服务商配置，自动绑定 lightagent/observer/coreagent/worker 并完成初始化', async () => {
    const onComplete = vi.fn();
    createProfile.mockResolvedValue({ status: 'ok', message: 'Profile created' });
    getProfiles.mockResolvedValue({
      profiles: [{ id: 'prof-ds-1', name: 'deepseek' }],
      active_profile_id: null,
      active_targets: [],
      worker_profile_id: null,
    });
    bindRole.mockResolvedValue({ status: 'ok' });
    setHookReviewEnabled.mockResolvedValue({ enabled: true });

    render(<InitWizardPage onComplete={onComplete} />);

    fireEvent.change(screen.getByTestId('setup-api-key'), {
      target: { value: 'sk-test-123456789' },
    });

    fireEvent.click(screen.getByTestId('setup-save-submit'));

    await waitFor(() => {
      expect(createProfile).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'deepseek',
          endpoint_type: 'deepseek',
          api_key: 'sk-test-123456789',
        })
      );
      expect(bindRole).toHaveBeenCalledWith('lightagent', 'prof-ds-1');
      expect(bindRole).toHaveBeenCalledWith('observer', 'prof-ds-1');
      expect(bindRole).toHaveBeenCalledWith('coreagent', 'prof-ds-1');
      expect(bindRole).toHaveBeenCalledWith('worker', 'prof-ds-1');
      expect(setHookReviewEnabled).toHaveBeenCalledWith(true);
      expect(markInitComplete).toHaveBeenCalledTimes(1);
      expect(onComplete).toHaveBeenCalledTimes(1);
    });
  });
});
