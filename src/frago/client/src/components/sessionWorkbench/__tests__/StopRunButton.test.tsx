/**
 * 标题栏那个「关闭 tmux 会话」。
 *
 * 钉住的是几件按错了就出事的事：点按钮只开弹窗不出门（否则手滑就把会话打断了）、
 * 弹窗里摆出要关的 tmux 会话名、服务端说「还在干活」时界面不许当成关掉了、
 * tmux 里已经没了时照实说，以及**按钮上不留文字**——那一行还挤着标题、工作目录和
 * 删除按钮，带字就把标题挤没。
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import StopRunButton from '../StopRunButton';
import i18n from '@/i18n';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const TMUX = `frago-agent-${SID}`;

const SESSION = {
  session_id: SID,
  title: 'SG服务器端trade history配方陈旧',
  directory: '/Users/frago',
  in_tmux: true,
  tmux_name: TMUX,
} as unknown as WorkbenchSession;

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

function mockStop(body: Record<string, unknown>) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ sid: SID, name: TMUX, via: null, error: null, ...body }),
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

async function openAndConfirm() {
  fireEvent.click(screen.getByTestId('session-stop-run'));
  await act(async () => {
    fireEvent.click(screen.getByTestId('session-stop-run-confirm'));
  });
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe('StopRunButton', () => {
  it('按钮上只有图标，名字挂在无障碍名称上', () => {
    mockStop({ alive: true, busy: false, stopped: true });
    render(<StopRunButton session={SESSION} />);

    const btn = screen.getByRole('button', { name: '关闭 tmux 会话' });
    expect(btn.textContent).toBe('');
  });

  it('点按钮只开弹窗不出门，弹窗里摆出 tmux 会话名和后果', () => {
    const fetchMock = mockStop({ alive: true, busy: false, stopped: true });
    render(<StopRunButton session={SESSION} />);

    fireEvent.click(screen.getByTestId('session-stop-run'));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText(`tmux: ${TMUX}`)).toBeTruthy();
    expect(screen.getByText(/会话记录不动/)).toBeTruthy();
  });

  it('确认才真去关，关掉之后弹窗收起并叫人重拉清单', async () => {
    const fetchMock = mockStop({ alive: true, busy: false, stopped: true });
    const onStopped = vi.fn();
    render(<StopRunButton session={SESSION} onStopped={onStopped} />);

    await openAndConfirm();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain(`/api/workbench/sessions/${SID}/stop`);
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ force: false });
    await waitFor(() => expect(onStopped).toHaveBeenCalled());
    expect(screen.queryByTestId('session-stop-run-confirm')).toBeNull();
  });

  it('服务端说还在干活时，弹窗换成「仍要关闭」再问一次，NEVER 当成已经关掉', async () => {
    const fetchMock = mockStop({ alive: true, busy: true, stopped: false });
    const onStopped = vi.fn();
    render(<StopRunButton session={SESSION} onStopped={onStopped} />);

    await openAndConfirm();

    await waitFor(() =>
      expect(screen.getByTestId('session-stop-run-confirm').textContent).toBe('仍要关闭')
    );
    expect(screen.getByTestId('session-stop-run-interrupt').textContent).toContain('打断');
    expect(onStopped).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(screen.getByTestId('session-stop-run-confirm'));
    });
    expect(JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string)).toEqual({
      force: true,
    });
  });

  it('tmux 里已经没了就照实说，并叫人重拉清单让按钮消失', async () => {
    mockStop({ alive: false, busy: false, stopped: false });
    const onStopped = vi.fn();
    render(<StopRunButton session={SESSION} onStopped={onStopped} />);

    await openAndConfirm();

    await waitFor(() =>
      expect(screen.getByTestId('session-stop-run-result').textContent).toContain('已经没有')
    );
    expect(screen.queryByTestId('session-stop-run-confirm')).toBeNull();
    expect(onStopped).toHaveBeenCalled();
  });
});
