/**
 * 递话之后页面摆哪一档。
 *
 * 盯的是 CoreAgent 那种形态：那一场正忙，这句话只在助手两次模型调用的空档被读到，
 * **递进去不等于被接住**。服务端为此当场回 ``status: "queued"``（那条路不等整轮），
 * 页面收到就得当场把信封换成「排队中」——一路显示「已发送」会让人以为话已经进去了。
 */
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useSendToSession } from '../useSendToSession';

const SID = 'core_18dbe0cfd02cb8a00000865f0000';

function stubSend(status: string) {
  return vi.fn(
    async () =>
      ({
        ok: true,
        json: async () => ({ sid: SID, status, text: '' }),
      }) as Response
  );
}

describe('递话之后的排队口', () => {
  it('服务端说排队，就当场把信封编号交回去让页面标成排队中', async () => {
    vi.stubGlobal('fetch', stubSend('queued'));
    const marked: (string | undefined)[] = [];
    const { result } = renderHook(() =>
      useSendToSession(SID, { onSendStart: () => 'out-1', onQueued: (id) => marked.push(id) })
    );

    act(() => result.current.setText('接着干'));
    await act(async () => {
      await result.current.send();
    });

    expect(marked).toEqual(['out-1']);
  });

  it('照常等整轮的那一条不喊排队：它回来时那句话早进了会话', async () => {
    vi.stubGlobal('fetch', stubSend('activating'));
    const marked: unknown[] = [];
    const { result } = renderHook(() =>
      useSendToSession(SID, { onSendStart: () => 'out-2', onQueued: (id) => marked.push(id) })
    );

    act(() => result.current.setText('接着干'));
    await act(async () => {
      await result.current.send();
    });

    expect(marked).toEqual([]);
  });

  it('没发出去的那一单不喊排队——它压根没进去', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status: 409, json: async () => ({ detail: '这一场还在跑' }) }) as Response)
    );
    const marked: unknown[] = [];
    const { result } = renderHook(() =>
      useSendToSession(SID, { onSendStart: () => 'out-3', onQueued: (id) => marked.push(id) })
    );

    act(() => result.current.setText('接着干'));
    await act(async () => {
      await result.current.send();
    });

    expect(marked).toEqual([]);
    expect(result.current.error).toContain('还在跑');
  });
});
