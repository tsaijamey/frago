/**
 * 标题栏那个「结束运行」。
 *
 * 钉住的是四件按错了就出事的事：一按不出门（否则手滑就把会话打断了）、服务端说
 * 「还在干活」时界面不许当成关掉了、这一场没在跑时照实说而不是报「已结束」、
 * 以及**按钮上不留文字**——那一行还挤着标题、工作目录和删除按钮，带字就把标题挤没。
 * 少了字不等于少了说法：每一档的完整说法挂在无障碍名称上，所以这几条照旧按名字找它。
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import StopRunButton from '../StopRunButton';
import i18n from '@/i18n';

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

function mockStop(body: Record<string, unknown>) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ sid: SID, name: `frago-agent-${SID}`, via: null, error: null, ...body }),
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/** 按当前这一档的说法找那个按钮。 */
function button(name: string): HTMLElement {
  return screen.getByRole('button', { name });
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe('StopRunButton', () => {
  it('按钮上只有图标，一个字的正文都没有', () => {
    mockStop({ alive: true, busy: false, stopped: true });
    render(<StopRunButton sessionId={SID} />);

    expect(button('结束运行').textContent).toBe('');
  });

  it('第一下只问不出门', () => {
    const fetchMock = mockStop({ alive: true, busy: false, stopped: true });
    render(<StopRunButton sessionId={SID} />);

    fireEvent.click(button('结束运行'));

    expect(button('确认结束')).toBeTruthy();
    expect(button('确认结束').textContent).toBe('');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('再按一下才真去关，关掉之后叫人重拉清单', async () => {
    const fetchMock = mockStop({ alive: true, busy: false, stopped: true });
    const onStopped = vi.fn();
    render(<StopRunButton sessionId={SID} onStopped={onStopped} />);

    fireEvent.click(button('结束运行'));
    await act(async () => {
      fireEvent.click(button('确认结束'));
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain(`/api/workbench/sessions/${SID}/stop`);
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ force: false });
    await waitFor(() => expect(button('已结束')).toBeTruthy());
    expect(onStopped).toHaveBeenCalled();
  });

  it('服务端说还在干活时，界面换一句话再问一次，NEVER 当成已经关掉', async () => {
    const fetchMock = mockStop({ alive: true, busy: true, stopped: false });
    const onStopped = vi.fn();
    render(<StopRunButton sessionId={SID} onStopped={onStopped} />);

    fireEvent.click(button('结束运行'));
    await act(async () => {
      fireEvent.click(button('确认结束'));
    });

    await waitFor(() => expect(button('还在干活，仍要结束')).toBeTruthy());
    expect(onStopped).not.toHaveBeenCalled();

    // 人决定打断：这一按带上 force。
    await act(async () => {
      fireEvent.click(button('还在干活，仍要结束'));
    });
    expect(JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string)).toEqual({
      force: true,
    });
  });

  it('这一场没在跑就照实说', async () => {
    mockStop({ alive: false, busy: false, stopped: false });
    const onStopped = vi.fn();
    render(<StopRunButton sessionId={SID} onStopped={onStopped} />);

    fireEvent.click(button('结束运行'));
    await act(async () => {
      fireEvent.click(button('确认结束'));
    });

    await waitFor(() => expect(button('这一场没在跑')).toBeTruthy());
    expect(onStopped).not.toHaveBeenCalled();
  });
});
