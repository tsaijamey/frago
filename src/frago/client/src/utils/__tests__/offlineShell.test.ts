/**
 * 离线外壳：存什么、什么时候发存量。
 *
 * 把 public/sw.js 当脚本读进来，在几个替身（替身 worker 全局、替身缓存、替身网络）里跑
 * 一遍，再照浏览器的来意去问它。不装真的 worker 环境是因为这里要验的是**取舍**——哪条
 * 请求碰、哪条不碰，什么时候发新的、什么时候发旧的——而不是浏览器的调度。
 *
 * 逐条钉住：
 *
 * 1. 接口一条都不接管。服务不在就得让请求真的失败，重连遮罩认的正是这个；替服务答一个
 *    存下来的旧数据比连不上还坏，人会拿过期内容当现在的用。
 * 2. 导航先问服务。服务答得上就绝不给旧界面，顺手把首屏和它要的文件存下。
 * 3. 服务不在时发存量，页面因此照样起得来。
 * 4. 头一次装上时页面已经加载完了，得自己去取一遍首屏，否则第一次打开之后马上断连，
 *    按 F5 还是打不开。
 * 5. 重建一次界面，文件名里的哈希换一批：新的补进来，旧的清掉，别一年堆出几百兆。
 * 6. HTML 的样子认不出来时就别动存量——宁可留着旧的，也不能把正在用的删了。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import workerSource from '../../../public/sw.js?raw';

const ORIGIN = 'http://127.0.0.1:8093';

/** 替真 Response。worker 只用到这五个面：状态、成不成、头、复制一份、读正文。 */
class FakeResponse {
  constructor(
    private readonly body: string,
    private readonly init: { status?: number; statusText?: string } = {}
  ) {}

  static ok(body: string): FakeResponse {
    return new FakeResponse(body);
  }

  get status(): number {
    return this.init.status ?? 200;
  }

  get ok(): boolean {
    return this.status >= 200 && this.status < 300;
  }

  get statusText(): string {
    return this.init.statusText ?? '';
  }

  get headers(): Record<string, string> {
    return {};
  }

  clone(): FakeResponse {
    return new FakeResponse(this.body, this.init);
  }

  async text(): Promise<string> {
    return this.body;
  }
}

function absolute(key: string | { url: string }): string {
  return new URL(typeof key === 'string' ? key : key.url, ORIGIN).href;
}

class FakeCache {
  readonly entries = new Map<string, FakeResponse>();

  async put(key: string | { url: string }, response: FakeResponse): Promise<void> {
    this.entries.set(absolute(key), response);
  }

  async match(key: string | { url: string }): Promise<FakeResponse | undefined> {
    return this.entries.get(absolute(key));
  }

  async delete(key: string | { url: string }): Promise<boolean> {
    return this.entries.delete(absolute(key));
  }

  /** worker 拿它来找旧文件，形状按真的来：一串带 url 的请求。 */
  async keys(): Promise<{ url: string }[]> {
    return [...this.entries.keys()].map((url) => ({ url }));
  }
}

class FakeCaches {
  private readonly byName = new Map<string, FakeCache>();

  async open(name: string): Promise<FakeCache> {
    if (!this.byName.has(name)) this.byName.set(name, new FakeCache());
    return this.byName.get(name)!;
  }

  async keys(): Promise<string[]> {
    return [...this.byName.keys()];
  }

  async delete(name: string): Promise<boolean> {
    return this.byName.delete(name);
  }

  /** 用例问「存下了什么」用的，不是 worker 的面。 */
  current(): FakeCache {
    const name = [...this.byName.keys()][0];
    return this.byName.get(name)!;
  }
}

interface FakeRequest {
  url: string;
  method: string;
  mode: string;
}

interface FakeEvent {
  request?: FakeRequest;
  respondWith?: (value: Promise<unknown>) => void;
  waitUntil?: (value: Promise<unknown>) => void;
}

type Handler = (event: FakeEvent) => void;

let listeners: Map<string, Handler>;
let fetcher: ReturnType<typeof vi.fn>;
let caches: FakeCaches;

beforeEach(() => {
  listeners = new Map();
  caches = new FakeCaches();
  // 默认谁都答不上来，跟服务停着一样。要它答哪条路径，用 serveRoutes 说。
  fetcher = vi.fn(() => Promise.reject(new TypeError('Failed to fetch')));

  const fakeSelf = {
    location: { origin: ORIGIN },
    addEventListener: (type: string, handler: Handler) => {
      listeners.set(type, handler);
    },
    skipWaiting: () => Promise.resolve(),
    clients: { claim: () => Promise.resolve() },
  };

  new Function('self', 'caches', 'fetch', 'Response', workerSource)(
    fakeSelf,
    caches,
    fetcher,
    FakeResponse
  );
});

/** 这一趟网络哪些路径答得上、答什么；没列出来的都算连不上。 */
function serveRoutes(routes: Record<string, string | FakeResponse>): void {
  fetcher.mockImplementation((input: unknown) => {
    const raw = typeof input === 'string' ? input : (input as { url: string }).url;
    const route = routes[new URL(raw, ORIGIN).pathname];
    if (route === undefined) return Promise.reject(new TypeError('Failed to fetch'));
    return Promise.resolve(typeof route === 'string' ? FakeResponse.ok(route) : route);
  });
}

function shell(asset: string): string {
  return `<!DOCTYPE html><html><body><div id="root"></div><script src="./assets/${asset}"></script></body></html>`;
}

/** 照浏览器的来意问它一次：它交回的答复；没接管就是 undefined（浏览器自己去连）。 */
async function ask(init: { url: string; mode?: string; method?: string }): Promise<FakeResponse | undefined> {
  let answered: Promise<FakeResponse> | undefined;
  const handler = listeners.get('fetch');
  if (!handler) throw new Error('worker 没挂上 fetch 监听');

  handler({
    request: {
      url: new URL(init.url, ORIGIN).href,
      method: init.method ?? 'GET',
      mode: init.mode ?? 'no-cors',
    },
    respondWith: (value) => {
      answered = value as Promise<FakeResponse>;
    },
  });

  return answered ? await answered : undefined;
}

/** 问它一次并要求它接管了，返回正文。 */
async function served(init: { url: string; mode?: string }): Promise<string> {
  const response = await ask(init);
  if (!response) throw new Error('worker 没接管这条请求');
  return response.text();
}

/** 装上并接管（install + activate 都走完）。 */
async function activate(): Promise<void> {
  const pending: Promise<unknown>[] = [];
  listeners.get('install')?.({ waitUntil: (value) => pending.push(value) });
  listeners.get('activate')?.({ waitUntil: (value) => pending.push(value) });
  await Promise.all(pending);
}

async function cached(path: string): Promise<string | undefined> {
  const response = await caches.current().match(path);
  return response ? response.text() : undefined;
}

describe('导航', () => {
  it('服务答得上：发新的，并把首屏连同它要的静态文件一起存下', async () => {
    serveRoutes({ '/': shell('index-A.js'), '/assets/index-A.js': 'A 这一版的包' });

    expect(await served({ url: '/', mode: 'navigate' })).toBe(shell('index-A.js'));

    expect(await cached('/')).toBe(shell('index-A.js'));
    expect(await cached('/assets/index-A.js')).toBe('A 这一版的包');
  });

  it('服务不在：发存下来的那份，页面因此还起得来', async () => {
    serveRoutes({ '/': shell('index-A.js'), '/assets/index-A.js': 'A 这一版的包' });
    await ask({ url: '/', mode: 'navigate' });

    serveRoutes({}); // 服务停了

    expect(await served({ url: '/', mode: 'navigate' })).toBe(shell('index-A.js'));
  });

  it('服务答的是它自己的错（界面还没建出来那种），原样发回去，不拿存量顶替', async () => {
    serveRoutes({ '/': shell('index-A.js') });
    await ask({ url: '/', mode: 'navigate' });

    serveRoutes({ '/': new FakeResponse('<h1>界面还没建出来</h1>', { status: 503 }) });

    expect(await served({ url: '/', mode: 'navigate' })).toBe('<h1>界面还没建出来</h1>');
    expect(await cached('/')).toBe(shell('index-A.js'));
  });

  it('服务不在而且一份存量都没有时，把失败交回浏览器', async () => {
    serveRoutes({});

    await expect(ask({ url: '/', mode: 'navigate' })).rejects.toThrow();
  });
});

describe('接口', () => {
  it('一条都不碰——服务不在就得让它真的失败，遮罩认的正是这个', async () => {
    serveRoutes({ '/api/info': '{"host":"127.0.0.1"}' });

    expect(await ask({ url: '/api/info' })).toBeUndefined();
    expect(await ask({ url: '/api/workbench/sessions' })).toBeUndefined();
    expect(await ask({ url: '/api/status' })).toBeUndefined();

    expect(fetcher).not.toHaveBeenCalled();
  });
});

describe('静态文件', () => {
  it('没存过就过一趟网络，顺手存下', async () => {
    serveRoutes({ '/assets/index-A.js': 'A 这一版的包' });

    expect(await served({ url: '/assets/index-A.js' })).toBe('A 这一版的包');
    expect(await cached('/assets/index-A.js')).toBe('A 这一版的包');
  });

  it('存过就直接发，不再问一趟', async () => {
    serveRoutes({ '/assets/index-A.js': 'A 这一版的包' });
    await ask({ url: '/assets/index-A.js' });
    const callsSoFar = fetcher.mock.calls.length;

    expect(await served({ url: '/assets/index-A.js' })).toBe('A 这一版的包');
    expect(fetcher.mock.calls.length).toBe(callsSoFar);
  });

  it('别处的请求一概不管', async () => {
    expect(await ask({ url: 'https://example.com/assets/index-A.js' })).toBeUndefined();
  });
});

describe('头一次装上', () => {
  it('页面已经加载完了，它那几份文件得自己去取一遍，否则第一次打开之后马上断连，F5 还是打不开', async () => {
    serveRoutes({ '/': shell('index-A.js'), '/assets/index-A.js': 'A 这一版的包' });

    await activate();

    expect(await cached('/')).toBe(shell('index-A.js'));
    expect(await cached('/assets/index-A.js')).toBe('A 这一版的包');
  });

  it('换版本时把上一版留下的整个清掉', async () => {
    await caches.open('frago-shell-旧版');
    serveRoutes({ '/': shell('index-A.js'), '/assets/index-A.js': 'A 这一版的包' });

    await activate();

    const names = await caches.keys();
    expect(names).not.toContain('frago-shell-旧版');
    expect(names).toHaveLength(1);
  });
});

describe('重建之后', () => {
  it('文件名里的哈希换了一批：新的补进来，旧的清掉', async () => {
    serveRoutes({ '/': shell('index-A.js'), '/assets/index-A.js': 'A 这一版的包' });
    await ask({ url: '/', mode: 'navigate' });

    serveRoutes({ '/': shell('index-B.js'), '/assets/index-B.js': 'B 这一版的包' });
    await ask({ url: '/', mode: 'navigate' });

    expect(await cached('/assets/index-B.js')).toBe('B 这一版的包');
    expect(await cached('/assets/index-A.js')).toBeUndefined();
  });

  it('HTML 的样子认不出来（一份静态文件都挑不到）就不动存量', async () => {
    serveRoutes({ '/': shell('index-A.js'), '/assets/index-A.js': 'A 这一版的包' });
    await ask({ url: '/', mode: 'navigate' });

    serveRoutes({ '/': '<!DOCTYPE html><html><body>换了副样子</body></html>' });
    await ask({ url: '/', mode: 'navigate' });

    expect(await cached('/assets/index-A.js')).toBe('A 这一版的包');
  });
});
