/**
 * Unit tests for DecisionModelCard in Settings -> General (Models & Connections).
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import i18n from '@/i18n';
import type { DecisionModelSettings } from '@/api';

const getDecisionModelSettings = vi.fn();
const updateDecisionModelSettings = vi.fn();
const resetDecisionModelSettings = vi.fn();

vi.mock('@/api', () => ({
  getDecisionModelSettings: () => getDecisionModelSettings(),
  updateDecisionModelSettings: (payload: unknown) => updateDecisionModelSettings(payload),
  resetDecisionModelSettings: () => resetDecisionModelSettings(),
}));

import DecisionModelCard from '../DecisionModelCard';

function buildSettings(overrides: Partial<DecisionModelSettings> = {}): DecisionModelSettings {
  return {
    configured: false,
    enabled: false,
    wire: 'decisions',
    url: null,
    model: '',
    has_api_key: false,
    api_key_masked: '',
    temperature: null,
    ...overrides,
  };
}

beforeAll(async () => {
  await i18n.changeLanguage('en');
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe('DecisionModelCard', () => {
  it('renders unconfigured state with no preset selector and saves user-customized fields', async () => {
    getDecisionModelSettings.mockResolvedValue(buildSettings());

    render(<DecisionModelCard />);

    await screen.findByTestId('decision-model-status-unconfigured');
    fireEvent.click(screen.getByTestId('decision-model-configure-btn'));

    expect(screen.queryByTestId('decision-model-preset-select')).toBeNull();

    const urlInput = screen.getByTestId('decision-model-url-input') as HTMLInputElement;
    const modelInput = screen.getByTestId('decision-model-model-input') as HTMLInputElement;
    const apiKeyInput = screen.getByTestId('decision-model-apikey-input') as HTMLInputElement;

    expect(urlInput.value).toBe('');
    expect(modelInput.value).toBe('');

    fireEvent.change(urlInput, {
      target: { value: 'https://openrouter.ai/api/alpha/decisions' },
    });
    fireEvent.change(modelInput, { target: { value: 'clef' } });
    fireEvent.change(apiKeyInput, { target: { value: 'sk-or-test-key' } });

    updateDecisionModelSettings.mockResolvedValue(
      buildSettings({
        configured: true,
        enabled: true,
        wire: 'decisions',
        url: 'https://openrouter.ai/api/alpha/decisions',
        model: 'clef',
        has_api_key: true,
        api_key_masked: 'sk-o****-key',
        temperature: null,
      })
    );

    fireEvent.click(screen.getByTestId('decision-model-save-btn'));

    await waitFor(() => {
      expect(updateDecisionModelSettings).toHaveBeenCalledWith({
        enabled: true,
        wire: 'decisions',
        url: 'https://openrouter.ai/api/alpha/decisions',
        model: 'clef',
        api_key: 'sk-or-test-key',
        clear_api_key: false,
        temperature: null,
      });
    });

    await screen.findByTestId('decision-model-status-active');
    expect(screen.getByTestId('decision-model-summary-model').textContent).toBe('clef');
    expect(screen.getByTestId('decision-model-summary-url').textContent).toBe(
      'https://openrouter.ai/api/alpha/decisions'
    );
  });

  it('preserves user-entered inputs when switching wire mode between decisions and ollama', async () => {
    getDecisionModelSettings.mockResolvedValue(buildSettings());

    render(<DecisionModelCard />);

    await screen.findByTestId('decision-model-status-unconfigured');
    fireEvent.click(screen.getByTestId('decision-model-configure-btn'));

    const wireSelect = screen.getByTestId('decision-model-wire-select');
    const urlInput = screen.getByTestId('decision-model-url-input') as HTMLInputElement;
    const modelInput = screen.getByTestId('decision-model-model-input') as HTMLInputElement;

    fireEvent.change(wireSelect, { target: { value: 'ollama' } });
    fireEvent.change(urlInput, { target: { value: 'http://127.0.0.1:11434' } });
    fireEvent.change(modelInput, { target: { value: 'intern-decision:0.8b' } });

    expect(urlInput.value).toBe('http://127.0.0.1:11434');
    expect(modelInput.value).toBe('intern-decision:0.8b');
  });
});
