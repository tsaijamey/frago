import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

vi.mock('@/stores/appStore', () => ({
  useAppStore: (selector: (s: { showToast: () => void }) => unknown) =>
    selector({ showToast: () => {} }),
}));

const getMainConfig = vi.fn();
const getProfiles = vi.fn();
const getConnections = vi.fn();
const bindHarness = vi.fn();
const bindRole = vi.fn();
const deleteProfile = vi.fn();
const getHookReviewStatus = vi.fn();
const setHookReviewEnabled = vi.fn();
const getDecisionModelSettings = vi.fn();
const updateDecisionModelSettings = vi.fn();
const resetDecisionModelSettings = vi.fn();
const openConfigInVSCode = vi.fn();

vi.mock('@/api', () => ({
  getMainConfig: () => getMainConfig(),
  getProfiles: () => getProfiles(),
  getConnections: () => getConnections(),
  bindHarness: (agentType: string, role: 'main' | 'worker', profileId: string) =>
    bindHarness(agentType, role, profileId),
  bindRole: (role: string, profileId: string) => bindRole(role, profileId),
  deleteProfile: (id: string) => deleteProfile(id),
  getHookReviewStatus: () => getHookReviewStatus(),
  setHookReviewEnabled: (enabled: boolean) => setHookReviewEnabled(enabled),
  getDecisionModelSettings: () => getDecisionModelSettings(),
  updateDecisionModelSettings: (payload: unknown) => updateDecisionModelSettings(payload),
  resetDecisionModelSettings: () => resetDecisionModelSettings(),
  openConfigInVSCode: (agentType?: string) => openConfigInVSCode(agentType),
  getEndpointPresets: vi.fn().mockResolvedValue({ presets: [] }),
  getActivationTargets: vi.fn().mockResolvedValue({ targets: [], default_targets: ['claude'] }),
  createProfile: vi.fn().mockResolvedValue({ status: 'ok' }),
  updateProfile: vi.fn().mockResolvedValue({ status: 'ok' }),
  activateProfile: vi.fn().mockResolvedValue({ status: 'ok' }),
  deactivateProfile: vi.fn().mockResolvedValue({ status: 'ok' }),
  saveCurrentAsProfile: vi.fn().mockResolvedValue({ status: 'ok' }),
}));

import GeneralSettings from '../GeneralSettings';

const SAMPLE_PROFILES = [
  {
    id: 'deepseek',
    name: 'DeepSeek',
    kind: 'endpoint',
    endpoint_type: 'deepseek',
    api_key_masked: 'sk-c****3998',
    url: 'https://api.deepseek.com/anthropic',
    default_model: 'deepseek-chat',
    sonnet_model: 'deepseek-chat',
    haiku_model: 'deepseek-flash',
    context_window: 1000000,
    channels: [
      { protocol: 'anthropic', url: 'https://api.deepseek.com/anthropic', models: ['deepseek-chat'], source: 'profile' },
      { protocol: 'responses', url: 'https://api.deepseek.com', models: ['deepseek-v4-flash'], source: 'preset' },
    ],
    is_active: true,
    created_at: '2026-09-01T00:00:00',
    updated_at: '2026-09-01T00:00:00',
  },
  {
    id: 'openrouter',
    name: 'OpenRouter',
    kind: 'endpoint',
    endpoint_type: 'custom',
    api_key_masked: 'sk-o****9048',
    url: 'https://openrouter.ai/api',
    default_model: 'anthropic/claude-sonnet-4.5',
    sonnet_model: 'anthropic/claude-sonnet-4.5',
    haiku_model: 'deepseek/deepseek-v4.1-flash',
    context_window: 200000,
    channels: [
      { protocol: 'anthropic', url: 'https://openrouter.ai/api', models: ['anthropic/claude-sonnet-4.5'], source: 'profile' },
    ],
    is_active: false,
    created_at: '2026-09-01T00:00:00',
    updated_at: '2026-09-01T00:00:00',
  },
];

const SAMPLE_HARNESSES = [
  {
    agent_type: 'claude',
    display_name: 'Claude Code',
    protocol: 'anthropic',
    protocol_label: 'Anthropic',
    config_path: '~/.claude/settings.json',
    installed: true,
    main_profile_id: 'deepseek',
    worker_profile_id: 'follow',
  },
  {
    agent_type: 'codex',
    display_name: 'Codex CLI',
    protocol: 'responses',
    protocol_label: 'OpenAI Responses',
    config_path: '~/.codex/config.toml',
    installed: true,
    main_profile_id: 'official',
    worker_profile_id: 'deepseek',
  },
  {
    agent_type: 'opencode',
    display_name: 'opencode',
    protocol: 'anthropic',
    protocol_label: 'Anthropic',
    config_path: '~/.config/opencode/opencode.json',
    installed: true,
    main_profile_id: 'openrouter',
    worker_profile_id: 'follow',
  },
  {
    agent_type: 'agy',
    display_name: 'Antigravity CLI',
    protocol: 'gemini',
    protocol_label: 'Gemini / 厂商 CLI',
    config_path: '~/.gemini/antigravity-cli/settings.json',
    installed: true,
    main_profile_id: 'official',
    worker_profile_id: 'follow',
  },
];

describe('GeneralSettings · 顶部三段切换与多 Harness 独立绑定', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getMainConfig.mockResolvedValue({
      working_directory: '~/.frago',
      auth_method: 'custom',
      resources_installed: true,
      init_completed: true,
    });
    getProfiles.mockResolvedValue({
      profiles: SAMPLE_PROFILES,
      active_profile_id: 'deepseek',
      active_targets: ['claude', 'opencode'],
      worker_profile_id: null,
    });
    getConnections.mockResolvedValue({
      connections: SAMPLE_PROFILES,
      bindings: [
        { role: 'lightagent', profile_id: 'deepseek', connection: SAMPLE_PROFILES[0], targets: [] },
        { role: 'observer', profile_id: null, connection: null, targets: [] },
        { role: 'coreagent', profile_id: 'deepseek', connection: SAMPLE_PROFILES[0], targets: [] },
      ],
      vendor_cores: [],
      harnesses: SAMPLE_HARNESSES,
    });
    getHookReviewStatus.mockResolvedValue({
      enabled: true,
      env_off: false,
      static_rules: { available: true, count: 12 },
      lightagent: { status: 'enabled', profile_name: 'DeepSeek', model: 'deepseek-flash', detail: null },
    });
    getDecisionModelSettings.mockResolvedValue({
      configured: true,
      enabled: true,
      wire: 'decisions',
      url: 'https://api.deepseek.com/v1/decisions',
      model: 'deepseek-chat',
      has_api_key: true,
      api_key_masked: 'sk-****',
      temperature: null,
    });
    bindHarness.mockResolvedValue({ status: 'ok' });
    bindRole.mockResolvedValue({ status: 'ok' });
    openConfigInVSCode.mockResolvedValue({ status: 'ok' });
  });

  it('默认展示 Harness 工具矩阵与 4 工具 Danger Zone，并可独立切换绑定', async () => {
    render(<GeneralSettings />);

    await screen.findByTestId('zone-harnesses');
    expect(screen.getByTestId('harness-row-claude')).toBeTruthy();
    expect(screen.getByTestId('harness-row-codex')).toBeTruthy();
    expect(screen.getByTestId('harness-row-opencode')).toBeTruthy();
    expect(screen.getByTestId('harness-row-agy')).toBeTruthy();

    // Codex 日常会话下拉中，不带 Responses 通道的 OpenRouter 应被禁用
    const codexMainSelect = screen.getByLabelText('Codex CLI 日常会话配置') as HTMLSelectElement;
    const orOption = Array.from(codexMainSelect.querySelectorAll('option')).find(
      (o) => o.value === 'openrouter',
    );
    expect(orOption?.disabled).toBe(true);

    // 切换 Codex 日常会话到 deepseek
    fireEvent.change(codexMainSelect, { target: { value: 'deepseek' } });
    await waitFor(() => expect(bindHarness).toHaveBeenCalledWith('codex', 'main', 'deepseek'));

    // Danger Zone 选择 opencode 并用 VSCode 打开
    const dangerSelect = screen.getByLabelText('选择要打开的 Harness 原生配置文件');
    fireEvent.change(dangerSelect, { target: { value: 'opencode' } });
    fireEvent.click(screen.getByTestId('open-in-vscode-btn'));
    await waitFor(() => expect(openConfigInVSCode).toHaveBeenCalledWith('opencode'));
  });

  it('切换到「内置与旁路 AI」与「AI 服务商」子视图，正确汇总反向引用气泡', async () => {
    render(<GeneralSettings />);
    await screen.findByTestId('zone-harnesses');

    // 切到「内置与旁路 AI」
    fireEvent.click(screen.getByTestId('general-tab-sidecar'));
    expect(await screen.findByTestId('zone-sidecar-ai')).toBeTruthy();
    expect(screen.getByTestId('sidecar-lightagent')).toBeTruthy();
    expect(screen.getByTestId('sidecar-observer')).toBeTruthy();
    expect(screen.getByTestId('sidecar-coreagent')).toBeTruthy();
    expect(screen.getByTestId('sidecar-decision')).toBeTruthy();

    // 展开决策模型内联配置
    fireEvent.click(screen.getByTestId('decision-model-toggle-btn'));
    expect(screen.getByTestId('decision-model-wire-select')).toBeTruthy();

    // 切到「AI 服务商」
    fireEvent.click(screen.getByTestId('general-tab-profiles'));
    expect(await screen.findByTestId('zone-profiles')).toBeTruthy();
    expect(screen.getByTestId('profile-row-deepseek')).toBeTruthy();
    expect(screen.getByText('Claude Code 日常')).toBeTruthy();
    expect(screen.getByText('Codex CLI Worker')).toBeTruthy();
  });
});
