/**
 * 离线外壳那个 worker 挂不挂、挂在哪儿。
 *
 * 钉住的其实是「什么情况下**不**挂」：开发环境、浏览器不认这套、桌面端走 file://。挂错了
 * 不是少个功能——是人在开发时对着旧模块调半天，或者控制台里多一条没人看得懂的红字。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { registerShellWorker, SHELL_WORKER_URL, shellWorkerAvailable } from '../shellWorker';

/** 装一个认这套东西的浏览器，返回它的注册入口。 */
function browserWithServiceWorker(
  register: (url: string, options?: unknown) => Promise<unknown> = () => Promise.resolve()
): ReturnType<typeof vi.fn> {
  const spy = vi.fn(register);
  Object.defineProperty(globalThis.navigator, 'serviceWorker', {
    value: { register: spy },
    configurable: true,
  });
  return spy;
}

beforeEach(() => {
  vi.stubEnv('PROD', true);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(globalThis.navigator, 'serviceWorker');
});

describe('挂上去', () => {
  it('发出去的产物里而且页面是 http 来的，就挂在站点根路径上，且更新时绕开缓存', () => {
    const register = browserWithServiceWorker();

    registerShellWorker();

    expect(register).toHaveBeenCalledWith(SHELL_WORKER_URL, { updateViaCache: 'none' });
  });
});

describe('不挂', () => {
  it('开发环境——留一份存量外壳只会让人对着旧模块调半天', () => {
    vi.stubEnv('PROD', false);
    const register = browserWithServiceWorker();

    registerShellWorker();

    expect(register).not.toHaveBeenCalled();
  });

  it('这套浏览器不认——不挂，也不炸', () => {
    expect(shellWorkerAvailable()).toBe(false);

    expect(() => registerShellWorker()).not.toThrow();
  });

  it('桌面端走 file://——那里根本没有 worker 可挂', () => {
    vi.stubGlobal('location', { protocol: 'file:' });
    const register = browserWithServiceWorker();

    registerShellWorker();

    expect(register).not.toHaveBeenCalled();
  });
});

describe('注册没成', () => {
  it('浏览器把它拒了也只当没这回事，不往外抛', async () => {
    browserWithServiceWorker(() => Promise.reject(new Error('unsupported MIME type')));

    expect(() => registerShellWorker()).not.toThrow();

    // 把这条被拒的承诺走完：没人接的话，未处理的拒绝会在这一步把用例打红。
    await Promise.resolve();
    await Promise.resolve();
  });
});
