import { beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import i18n from '@/i18n';
import type { CliAgentsStatus } from '@/api';

const getCliAgentsStatus = vi.fn();
const setOpencodeServiceDisabled = vi.fn();

vi.mock('@/api', () => ({
  getCliAgentsStatus: () => getCliAgentsStatus(),
  setOpencodeServiceDisabled: (disabled: boolean) => setOpencodeServiceDisabled(disabled),
}));

import CliAgentSettings from '../CliAgentSettings';

function sampleStatus(ocDisabled: boolean): CliAgentsStatus {
  return {
    agents: [
      {
        agent_type: 'claude',
        display_name: 'Claude Code',
        family: 'claude-code',
        installed: true,
        path: '/usr/local/bin/claude',
        opencode_service: null,
      },
      {
        agent_type: 'opencode',
        display_name: 'opencode',
        family: 'opencode',
        installed: true,
        path: '/opt/homebrew/bin/opencode',
        opencode_service: {
          supported: true,
          disabled: ocDisabled,
          config_path: '~/.config/opencode/service.json',
        },
      },
      {
        agent_type: 'codex',
        display_name: 'Codex CLI',
        family: 'codex',
        installed: false,
        path: null,
        opencode_service: null,
      },
    ],
  };
}

beforeAll(async () => {
  await i18n.changeLanguage('en');
});

describe('CliAgentSettings', () => {
  it('lights up detected CLI agents and dims uninstalled ones', async () => {
    getCliAgentsStatus.mockResolvedValue(sampleStatus(false));
    render(<CliAgentSettings />);

    await screen.findByText('Claude Code');

    const claudeCard = screen.getByTestId('cli-agent-card-claude');
    const opencodeCard = screen.getByTestId('cli-agent-card-opencode');
    const codexCard = screen.getByTestId('cli-agent-card-codex');

    expect(claudeCard.getAttribute('data-installed')).toBe('true');
    expect(opencodeCard.getAttribute('data-installed')).toBe('true');
    expect(codexCard.getAttribute('data-installed')).toBe('false');
    expect(codexCard.className).toContain('is-off');
    expect(screen.getByText('/opt/homebrew/bin/opencode')).toBeTruthy();
  });

  it('toggles opencode service disabled true and false via API', async () => {
    getCliAgentsStatus.mockResolvedValue(sampleStatus(false));
    setOpencodeServiceDisabled.mockResolvedValue(sampleStatus(true));

    render(<CliAgentSettings />);

    const toggle = (await screen.findByLabelText(
      /Disable background daemon/i,
    )) as HTMLInputElement;
    expect(toggle.checked).toBe(false);

    fireEvent.click(toggle);

    await waitFor(() => {
      expect(setOpencodeServiceDisabled).toHaveBeenCalledWith(true);
      expect(toggle.checked).toBe(true);
    });
  });
});
