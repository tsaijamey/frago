/**
 * 「本机后台服务还在不在」这套判定。
 *
 * 钉住的是它什么时候说话、什么时候闭嘴——说得太早，网络抖一下整页就模糊一次；说得太
 * 晚，人就对着一个哑掉的页面继续点。两边都是实打实的损失，所以逐条摆在下面：
 *
 * 1. 一次失败不当场亮，满 SHOW_DELAY_MS 才亮；
 * 2. 失败之后又有应答就不亮；
 * 3. 后端接口自己报 500 不算断连，502 才算；
 * 4. 人自己取消的请求、页面外的请求，都不算；
 * 5. 亮着的时候探到明确答复就撤，撤的时候在窗口上喊一声（内容页靠这一声立刻补数据）；
 * 6. 探到的是开发代理顶出来的纯文本、或静态服务器顶出来的 HTML，都不算服务回来。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  handleSocketDisconnect,
  installConnectionMonitor,
  isBackendRequest,
  PROBE_INTERVAL_MS,
  PROBE_PATH,
  RECONNECTED_EVENT,
  SHOW_DELAY_MS,
  uninstallConnectionMonitor,
  useConnectionStore,
} from '../connection';

interface Reply {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
}

function answer(status = 200): Reply {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => ({ host: '127.0.0.1', port: 8093, started_at: '2026-09-12T00:00:00' }),
  };
}

/** 服务没起时浏览器抛出来的那个错。 */
function networkFailure(): Promise<never> {
  return Promise.reject(new TypeError('Failed to fetch'));
}

function aborted(): Promise<never> {
  return Promise.reject(Object.assign(new Error('aborted'), { name: 'AbortError' }));
}

let reply: () => Promise<Reply>;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers();
  useConnectionStore.setState({ reachable: true });
  reply = networkFailure;
  fetchMock = vi.fn(() => reply());
  // 先立桩再装监听：装的时候会把当下这个 fetch 收进去当原生实现，装完换上去的是包装层。
  vi.stubGlobal('fetch', fetchMock);
  installConnectionMonitor();
});

afterEach(() => {
  uninstallConnectionMonitor();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  useConnectionStore.setState({ reachable: true });
});

/** 让它断连：一次失败的请求，再把 800 毫秒的等待走完。 */
async function goDown(): Promise<void> {
  await expect(fetch('/api/workbench/sessions')).rejects.toThrow();
  await vi.advanceTimersByTimeAsync(SHOW_DELAY_MS);
  expect(useConnectionStore.getState().reachable).toBe(false);
}

describe('服务在不在', () => {
  it('一次失败不当场亮遮罩，满 800 毫秒才亮', async () => {
    await expect(fetch('/api/workbench/sessions')).rejects.toThrow();
    expect(useConnectionStore.getState().reachable).toBe(true);

    await vi.advanceTimersByTimeAsync(SHOW_DELAY_MS);

    expect(useConnectionStore.getState().reachable).toBe(false);
  });

  it('失败之后又有应答，就当没断过', async () => {
    await expect(fetch('/api/a')).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(SHOW_DELAY_MS - 100);

    reply = () => Promise.resolve(answer());
    await fetch('/api/b');
    await vi.advanceTimersByTimeAsync(PROBE_INTERVAL_MS * 3);

    expect(useConnectionStore.getState().reachable).toBe(true);
  });

  it('后端接口自己报 500 不算断连——那是那个接口的事，不该盖住整页', async () => {
    reply = () => Promise.resolve(answer(500));
    await fetch('/api/a');
    await vi.advanceTimersByTimeAsync(SHOW_DELAY_MS);

    expect(useConnectionStore.getState().reachable).toBe(true);
  });

  it('网关答的 502 算断连', async () => {
    reply = () => Promise.resolve(answer(502));
    await fetch('/api/a');
    await vi.advanceTimersByTimeAsync(SHOW_DELAY_MS);

    expect(useConnectionStore.getState().reachable).toBe(false);
  });

  it('人自己取消的请求不算断连', async () => {
    reply = aborted;
    await expect(fetch('/api/workbench/search?q=x')).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(SHOW_DELAY_MS);

    expect(useConnectionStore.getState().reachable).toBe(true);
  });

  it('不是打给本机服务的请求失败，不把整页变模糊', async () => {
    await expect(fetch('https://example.com/whatever')).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(SHOW_DELAY_MS);

    expect(useConnectionStore.getState().reachable).toBe(true);
  });
});

describe('遮罩亮着的时候', () => {
  it('探到明确答复就撤，并在窗口上喊一声让页面补数据', async () => {
    await goDown();
    const heard = vi.fn();
    window.addEventListener(RECONNECTED_EVENT, heard);

    reply = () => Promise.resolve(answer());
    await vi.advanceTimersByTimeAsync(PROBE_INTERVAL_MS);

    expect(useConnectionStore.getState().reachable).toBe(true);
    expect(heard).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(PROBE_PATH, { cache: 'no-store' });
  });

  it('页面自己的一条应答撤不了它——开发模式下代理顶的 500 会看着像好了', async () => {
    await goDown();

    reply = () => Promise.resolve(answer(500));
    await fetch('/api/workbench/sessions');

    expect(useConnectionStore.getState().reachable).toBe(false);
  });

  it('探到开发代理顶出来的那段纯文本 500，就当服务还没回来', async () => {
    await goDown();

    reply = () =>
      Promise.resolve({
        ok: false,
        status: 500,
        json: async () => {
          throw new SyntaxError('Unexpected token E in JSON');
        },
      });
    await vi.advanceTimersByTimeAsync(PROBE_INTERVAL_MS * 2);

    expect(useConnectionStore.getState().reachable).toBe(false);
  });

  it('探针答 200 但返回体不是 JSON（被静态服务器顶了首屏），也不算回来', async () => {
    await goDown();

    reply = () =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: async () => {
          throw new SyntaxError('Unexpected token < in JSON');
        },
      });
    await vi.advanceTimersByTimeAsync(PROBE_INTERVAL_MS * 2);

    expect(useConnectionStore.getState().reachable).toBe(false);
  });

  it('撤了之后就不再探了', async () => {
    await goDown();

    reply = () => Promise.resolve(answer());
    await vi.advanceTimersByTimeAsync(PROBE_INTERVAL_MS);
    const callsWhenRecovered = fetchMock.mock.calls.length;

    await vi.advanceTimersByTimeAsync(PROBE_INTERVAL_MS * 5);

    expect(fetchMock.mock.calls.length).toBe(callsWhenRecovered);
  });
});

describe('WebSocket 断开这条快路', () => {
  it('探不到答复就按失败走，满 800 毫秒点亮', async () => {
    handleSocketDisconnect();
    await vi.advanceTimersByTimeAsync(SHOW_DELAY_MS);

    expect(useConnectionStore.getState().reachable).toBe(false);
    expect(fetchMock).toHaveBeenCalledWith(PROBE_PATH, { cache: 'no-store' });
  });

  it('探到答复就什么都不做——标签页睡觉被掐掉是常事，不该闪一层遮罩', async () => {
    reply = () => Promise.resolve(answer());
    handleSocketDisconnect();
    await vi.advanceTimersByTimeAsync(SHOW_DELAY_MS * 3);

    expect(useConnectionStore.getState().reachable).toBe(true);
  });

  it('开发代理顶出来的 500 也算探不到', async () => {
    reply = () =>
      Promise.resolve({
        ok: false,
        status: 500,
        json: async () => {
          throw new SyntaxError('Unexpected token E in JSON');
        },
      });
    handleSocketDisconnect();
    await vi.advanceTimersByTimeAsync(SHOW_DELAY_MS);

    expect(useConnectionStore.getState().reachable).toBe(false);
  });
});

describe('认不认这条请求', () => {
  it('本机服务那几条路都认', () => {
    expect(isBackendRequest('/api/info')).toBe(true);
    expect(isBackendRequest('/api/workbench/sessions')).toBe(true);
  });

  it('开发模式下接口配在另一个端口，也算本机这一份', () => {
    expect(isBackendRequest('http://127.0.0.1:8093/api/info')).toBe(true);
  });

  it('别的不认', () => {
    expect(isBackendRequest('/ws')).toBe(false);
    expect(isBackendRequest('/assets/index.js')).toBe(false);
    expect(isBackendRequest('https://example.com/api/info')).toBe(false);
    expect(isBackendRequest('https://example.com/other')).toBe(false);
  });
});

describe('卸载', () => {
  it('把原生 fetch 换回去，并把状态复位', async () => {
    await goDown();

    uninstallConnectionMonitor();

    expect(globalThis.fetch).toBe(fetchMock);
    expect(useConnectionStore.getState().reachable).toBe(true);
  });
});
