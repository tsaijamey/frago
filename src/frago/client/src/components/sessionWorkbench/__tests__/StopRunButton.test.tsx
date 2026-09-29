/**
 * 「…」菜单里的 Close tmux session（流程在 `StopRunButton.tsx` 的 `useCloseTmux`）。
 *
 * 钉住的是几件按错了就出事的事：本页知道还在干活时先确认、一个请求都不出门；不在干活直接
 * 关；服务端说「还在干活」时界面不许当成关掉了，换成确认再问一次、人确认了才带 force；
 * tmux 里已经没了时照实说；这场不在 tmux 里时菜单里根本没有这一项。
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import SessionMenu from '../SessionMenu';
import i18n from '@/i18n';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const TMUX = `frago-agent-${SID}`;

const SESSION = {
  session_id: SID,
  family: 'claude-code',
  title: 'SG服务器端trade history配方陈旧',
  directory: '/Users/frago',
  in_tmux: true,
  tmux_name: TMUX,
} as unknown as WorkbenchSession;

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

function mockStop(...bodies: Record<string, unknown>[]) {
  const fetchMock = vi.fn();
  for (const body of bodies) {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ sid: SID, name: TMUX, via: null, error: null, ...body }),
    });
  }
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function forceOf(fetchMock: ReturnType<typeof vi.fn>, i: number) {
  return JSON.parse((fetchMock.mock.calls[i][1] as RequestInit).body as string).force;
}

async function clickClose() {
  fireEvent.click(screen.getByTestId('session-menu-button'));
  await act(async () => {
    fireEvent.click(screen.getByTestId('session-menu-close'));
  });
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe('Close tmux session（菜单项）', () => {
  it('不在 tmux 里：菜单里没有这一项，连同它那一段', () => {
    render(<SessionMenu session={SESSION} pinned={false} inTmux={false} />);
    fireEvent.click(screen.getByTestId('session-menu-button'));
    expect(screen.queryByTestId('session-menu-close')).toBeNull();
    const sections = screen.getAllByTestId('session-menu-section').map((el) => el.dataset.section);
    expect(sections).toEqual(['organize', 'delete']);
  });

  it('悬停说明写清关掉会怎样', () => {
    render(<SessionMenu session={SESSION} pinned={false} inTmux />);
    fireEvent.click(screen.getByTestId('session-menu-button'));
    expect(screen.getByTestId('session-menu-close').getAttribute('title')).toContain('会话记录还在');
  });

  it('本页知道还在干活：先确认，一个请求都不出门；确认了才带 force 去关', async () => {
    const fetchMock = mockStop({ alive: true, busy: true, stopped: true });
    const onStopped = vi.fn();
    render(<SessionMenu session={SESSION} pinned={false} inTmux busyTurn onStopped={onStopped} />);

    await clickClose();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByTestId('session-menu-confirm-close').textContent).toContain('还在干活');

    await act(async () => {
      fireEvent.click(screen.getByTestId('session-stop-run-confirm'));
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(forceOf(fetchMock, 0)).toBe(true);
    await waitFor(() => expect(onStopped).toHaveBeenCalled());
    expect(screen.queryByTestId('session-menu')).toBeNull();
  });

  it('不在干活直接关，关掉之后菜单收起并叫人重拉清单', async () => {
    const fetchMock = mockStop({ alive: true, busy: false, stopped: true });
    const onStopped = vi.fn();
    render(<SessionMenu session={SESSION} pinned={false} inTmux onStopped={onStopped} />);

    await clickClose();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain(`/api/workbench/sessions/${SID}/stop`);
    expect(forceOf(fetchMock, 0)).toBe(false);
    await waitFor(() => expect(onStopped).toHaveBeenCalled());
    expect(screen.queryByTestId('session-menu')).toBeNull();
  });

  it('服务端说还在干活时换成确认再问一次，NEVER 当成已经关掉', async () => {
    const fetchMock = mockStop(
      { alive: true, busy: true, stopped: false },
      { alive: true, busy: true, stopped: true }
    );
    const onStopped = vi.fn();
    render(<SessionMenu session={SESSION} pinned={false} inTmux onStopped={onStopped} />);

    await clickClose();

    await waitFor(() => expect(screen.getByTestId('session-menu-confirm-close')).toBeTruthy());
    expect(screen.getByTestId('session-menu-confirm-close').textContent).toContain('结束这一轮');
    expect(onStopped).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(screen.getByTestId('session-stop-run-confirm'));
    });
    expect(forceOf(fetchMock, 1)).toBe(true);
    await waitFor(() => expect(onStopped).toHaveBeenCalled());
  });

  it('tmux 里已经没了就照实说，并叫人重拉清单让这一项消失', async () => {
    mockStop({ alive: false, busy: false, stopped: false });
    const onStopped = vi.fn();
    render(<SessionMenu session={SESSION} pinned={false} inTmux onStopped={onStopped} />);

    await clickClose();

    await waitFor(() =>
      expect(screen.getByTestId('session-stop-run-result').textContent).toContain('已经没有')
    );
    expect(screen.queryByTestId('session-stop-run-confirm')).toBeNull();
    expect(onStopped).toHaveBeenCalled();
  });
});
