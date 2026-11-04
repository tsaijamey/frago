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
  await i18n.changeLanguage('en');
});

beforeEach(() => {
  vi.clearAllMocks();
  useDataStore.setState({
    config: {
      theme: 'dark',
      language: 'en',
      agent_language: '',
      max_history_items: 100,
      shortcuts: { send: 'Ctrl+Enter', clear: 'Ctrl+L', settings: 'Ctrl+,' },
    },
    updateConfig: vi.fn().mockResolvedValue(undefined),
    setLanguage: vi.fn().mockResolvedValue(undefined),
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
    ],
  });
  getCliAgentsStatus.mockResolvedValue({ agents: [] });
  markInitComplete.mockResolvedValue({ status: 'ok', init_completed: true });
});

describe('InitWizardPage (#setup edge-case flow)', () => {
  it('renders both Appearance & language and Model connection cards and skips cleanly', async () => {
    const onComplete = vi.fn();
    render(<InitWizardPage onComplete={onComplete} />);

    expect(screen.getByTestId('setup-card-appearance')).toBeTruthy();
    expect(screen.getByTestId('setup-card-connection')).toBeTruthy();

    fireEvent.click(screen.getByTestId('setup-skip-bottom'));

    await waitFor(() => {
      expect(markInitComplete).toHaveBeenCalledTimes(1);
      expect(onComplete).toHaveBeenCalledTimes(1);
    });
  });

  it('creates profile, binds lightagent/observer/coreagent/worker, enables hook_review, and completes init', async () => {
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
