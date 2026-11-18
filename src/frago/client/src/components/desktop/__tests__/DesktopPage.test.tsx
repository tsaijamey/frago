import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import DesktopPage from '../DesktopPage';
import i18n from '@/i18n';
import { usePageStore } from '@/stores/pageStore';

vi.mock('@/hooks/useWebSocket', () => ({
  useWebSocket: () => ({ isConnected: true }),
}));

const mockUseAgentClients = vi.fn();

vi.mock('@/hooks/useAgentClients', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/useAgentClients')>();
  return {
    ...actual,
    useAgentClients: (...args: unknown[]) => mockUseAgentClients(...args),
  };
});

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>();
  return {
    ...actual,
    getActiveDesktopSession: vi.fn().mockResolvedValue({
      session_id: null,
      employee: 'desktop-operator',
      restored: false,
    }),
  };
});

const SAMPLE_AGENTS = [
  {
    agent_type: 'opencode',
    display_name: 'OpenCode',
    installed: true,
    path: '/usr/local/bin/opencode',
    family: 'opencode',
    selectable: true,
    reason: null,
    id_origin: 'claimed' as const,
  },
  {
    agent_type: 'claude',
    display_name: 'Claude Code',
    installed: true,
    path: '/usr/local/bin/claude',
    family: 'claude-code',
    selectable: true,
    reason: null,
    id_origin: 'caller' as const,
  },
  {
    agent_type: 'coreagent',
    display_name: 'CoreAgent',
    installed: true,
    path: '/Users/frago/.frago/bin/frago-core',
    family: 'coreagent',
    selectable: false,
    reason: 'agent.noConnection',
    id_origin: 'caller' as const,
  },
  {
    agent_type: 'codex',
    display_name: 'Codex CLI',
    installed: true,
    path: '/usr/local/bin/codex',
    family: 'codex',
    selectable: true,
    reason: null,
    id_origin: 'claimed' as const,
  },
  {
    agent_type: 'agy',
    display_name: 'Antigravity CLI',
    installed: false,
    path: null,
    family: 'agy',
    selectable: false,
    reason: 'agent.notInstalled',
    id_origin: 'claimed' as const,
  },
];

beforeAll(async () => {
  await i18n.changeLanguage('en');
});

beforeEach(() => {
  mockUseAgentClients.mockReturnValue({
    agents: SAMPLE_AGENTS,
    fallbackDefault: 'claude',
    loading: false,
    error: null,
  });
  usePageStore.setState({
    currentPage: 'desktop',
    desktopSessionId: null,
    desktopExplicitSessionId: null,
  });
});

describe('DesktopPage (P1-5)', () => {
  it('renders unified .ph header controls, priority-ordered Agent selector, and bidirectional toolbar postMessage sync', async () => {
    usePageStore.setState({
      currentPage: 'desktop',
      desktopSessionId: '12345678-abcd-ef01-2345-6789abcdef01',
    });

    const { container } = render(<DesktopPage />);
    const iframe = container.querySelector('iframe.dt-frame') as HTMLIFrameElement;
    expect(iframe).toBeTruthy();

    const posted: Record<string, unknown>[] = [];
    Object.defineProperty(iframe, 'contentWindow', {
      configurable: true,
      value: {
        postMessage: (msg: Record<string, unknown>) => {
          posted.push(msg);
        },
      },
    });

    const header = container.querySelector('header.ui-page-header.ph');
    expect(header).toBeTruthy();
    expect(screen.getByTestId('desktop-status-pill')).toBeTruthy();

    // Agent selector sorted by coreagent > claude > codex > agy > opencode; coreagent unavailable -> defaults to claude
    const agentSelect = screen.getByTestId('desktop-agent-select') as HTMLSelectElement;
    const optionValues = Array.from(agentSelect.options).map((o) => o.value);
    expect(optionValues).toEqual(['coreagent', 'claude', 'codex', 'agy', 'opencode']);
    expect(agentSelect.options[0].disabled).toBe(true);
    expect(agentSelect.options[3].disabled).toBe(true);
    await waitFor(() => expect(agentSelect.value).toBe('claude'));

    fireEvent.change(agentSelect, { target: { value: 'codex' } });
    expect(agentSelect.value).toBe('codex');
    expect(posted).toContainEqual({ type: 'frago:desktop-agent', agent: 'codex' });

    const resSelect = screen.getByLabelText('Resolution') as HTMLSelectElement;
    expect(resSelect.value).toBe('1920×1080');
    fireEvent.change(resSelect, { target: { value: '1440×900' } });
    expect(resSelect.value).toBe('1440×900');

    const fpsSelect = screen.getByLabelText('FPS') as HTMLSelectElement;
    expect(fpsSelect.value).toBe('30 fps');
    fireEvent.change(fpsSelect, { target: { value: '60 fps' } });
    expect(fpsSelect.value).toBe('60 fps');

    const narratorBtn = screen.getByTestId('desktop-narrator-toggle');
    expect(narratorBtn.textContent).toContain('Voice: Xiaoxiao');
    fireEvent.click(narratorBtn);
    expect(narratorBtn.textContent).toContain('Voice: Muted');

    const observeBtn = screen.getByRole('button', { name: 'Observe' });
    const takeoverBtn = screen.getByRole('button', { name: 'Takeover' });
    expect(observeBtn.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(takeoverBtn);
    expect(takeoverBtn.getAttribute('aria-pressed')).toBe('true');

    const unlockBtn = screen.getByTestId('desktop-audio-unlock');
    expect(unlockBtn.textContent).toContain('Unlock');
    fireEvent.click(unlockBtn);
    expect(unlockBtn.textContent).toContain('Audio Ready');
    expect(posted).toContainEqual({ type: 'frago:desktop-unlock-audio', unlocked: true });

    const toolbar = screen.getByTestId('desktop-compact-toolbar');
    expect(toolbar.className).toContain('dt-toolbar');
    const appSelect = screen.getByLabelText('Virtual App') as HTMLSelectElement;
    fireEvent.change(appSelect, { target: { value: 'browser' } });
    expect(appSelect.value).toBe('browser');
    expect(screen.getByRole('button', { name: 'Browser' }).getAttribute('aria-pressed')).toBe('true');
    expect(posted).toContainEqual({ type: 'frago:desktop-app', app: 'browser' });

    fireEvent.load(iframe);
    expect(screen.getByTestId('desktop-status-pill').textContent).toContain('Connected');

    // Reverse sync from stage iframe via frago:desktop-state
    act(() => {
      window.dispatchEvent(
        new MessageEvent('message', {
          data: {
            type: 'frago:desktop-state',
            mode: 'observe',
            narrator: true,
            soundUnlocked: true,
            app: 'term',
          },
        }),
      );
    });
    expect(observeBtn.getAttribute('aria-pressed')).toBe('true');
    expect(narratorBtn.textContent).toContain('Voice: Xiaoxiao');
    expect(unlockBtn.textContent).toContain('Audio Ready');
    expect(appSelect.value).toBe('term');
    expect(screen.getByRole('button', { name: 'Terminal' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('defaults to CoreAgent when CoreAgent is selectable', async () => {
    mockUseAgentClients.mockReturnValue({
      agents: SAMPLE_AGENTS.map((a) =>
        a.agent_type === 'coreagent' ? { ...a, selectable: true, reason: null } : a,
      ),
      fallbackDefault: 'claude',
      loading: false,
      error: null,
    });
    render(<DesktopPage />);
    const agentSelect = screen.getByTestId('desktop-agent-select') as HTMLSelectElement;
    await waitFor(() => expect(agentSelect.value).toBe('coreagent'));
  });

  it('does not inject random ?session= on normal load and syncs header sessionId via postMessage without reloading iframe', () => {
    const { container } = render(<DesktopPage />);
    const iframe = container.querySelector('iframe.dt-frame') as HTMLIFrameElement;
    expect(iframe).toBeTruthy();
    const initialSrc = iframe.getAttribute('src') || '';
    expect(initialSrc).not.toContain('session=');

    act(() => {
      window.dispatchEvent(
        new MessageEvent('message', {
          data: {
            type: 'frago:desktop-session',
            sessionId: 'core_f9983f7b163240a7b68b22d88f6e5004',
          },
        }),
      );
    });

    expect(usePageStore.getState().desktopSessionId).toBe('core_f9983f7b163240a7b68b22d88f6e5004');
    expect(usePageStore.getState().desktopExplicitSessionId).toBeNull();
    expect(iframe.getAttribute('src')).toBe(initialSrc);
    expect(container.querySelector('.ui-page-header-meta')?.textContent).toContain('core_f99');
  });

  it('passes ?session= to iframe only when desktopExplicitSessionId is set via switchPage', () => {
    usePageStore.getState().switchPage('desktop', 'core_recipe_explicit_123');
    const { container } = render(<DesktopPage />);
    const iframe = container.querySelector('iframe.dt-frame') as HTMLIFrameElement;
    expect(iframe.getAttribute('src')).toContain('session=core_recipe_explicit_123');
  });
});
