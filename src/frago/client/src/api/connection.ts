/**
 * 「本机后台服务还在不在」——页面侧的唯一判据。
 *
 * 服务停掉、重启、升级的那十几秒里，页面上每个请求都会失败。此前每处调用点各写各的：
 * 左栏塞一行「会话清单取不到」，中间那片空着，别处再飘一条提示，人看到七八处零碎报错，
 * 读不出「是服务没了，等它回来就行」这一件事。
 *
 * 判定收在这一个文件里：给浏览器的 fetch 包一层，凡是打给本机 `/api` 的请求没能从服务
 * 手上拿到答复，就算服务不在；连续失败满 SHOW_DELAY_MS 才点亮遮罩——网络抖一下不该闪
 * 一层东西出来。遮罩亮着的时候由这里每隔 PROBE_INTERVAL_MS 探一次，探到明确答复就撤，
 * 顺带喊一声让页面立刻把数据补回来。
 *
 * 为什么拦在 fetch 上而不是改写各处调用点：全库一百多处请求，一半走集中封装、一半裸写
 * 在 hook 里，逐个改是改得完的，但下一个新写的接口照样漏。断连这件事的性质是「所有请求
 * 一起坏」，它就该被拦在所有请求都经过的那一处。
 */

import { create } from 'zustand';
import { getWebSocketClient } from './websocket';

/** 连续失败多久才点亮遮罩。低于这个数的抖动人根本来不及反应，遮罩一闪反而像出了事。 */
export const SHOW_DELAY_MS = 800;

/** 遮罩亮着时隔多久探一次服务。 */
export const PROBE_INTERVAL_MS = 1_500;

/**
 * 探服务用哪条接口。
 *
 * 挑 `/api/info`：它只报本机服务自己的三件事（地址、端口、起于何时），不读盘、不数进程、
 * 不查浏览器，服务刚起来就答得上。`/api/status` 那条要顺带清点任务与标签页，拿它当探针
 * 等于每 1.5 秒催服务干一趟活。
 */
export const PROBE_PATH = '/api/info';

/**
 * 服务回来时在 window 上喊一声。
 *
 * 听着的是 `useAutoRefresh`：遮罩撤掉的那一刻各个内容页还没重取过，左栏那行旧报错要等
 * 下一次轮询（最多 15 秒）才消失。听见这一声就立刻补一趟。
 */
export const RECONNECTED_EVENT = 'frago:reconnected';

/**
 * 这几个状态码算「服务不在」。
 *
 * 502/503/504 是网关答的，说明请求根本没走到本机服务手上。其余状态码一律算服务在——
 * 后端某个接口自己报 500 是那个接口的事，不该把整页盖住。
 */
const UNAVAILABLE_STATUS = new Set([502, 503, 504]);

interface ConnectionSlice {
  /** 服务答得上话。页面所有请求都以它为准，遮罩也是。 */
  reachable: boolean;
  /** 一次请求没能从服务手上拿到答复。 */
  reportFailure: () => void;
  /** 一次请求拿到了答复——只用来撤销「遮罩要亮」这个倒计时，撤不了已经亮起来的遮罩。 */
  reportSuccess: () => void;
}

let showTimer: ReturnType<typeof setTimeout> | null = null;
let probeTimer: ReturnType<typeof setInterval> | null = null;
/** 已经在等遮罩亮，或遮罩已经亮着。两种情况都不必再排一个计时器。 */
let countingDown = false;

function clearShowTimer(): void {
  if (showTimer) {
    clearTimeout(showTimer);
    showTimer = null;
  }
}

function stopProbe(): void {
  if (probeTimer) {
    clearInterval(probeTimer);
    probeTimer = null;
  }
}

export const useConnectionStore = create<ConnectionSlice>((set, get) => ({
  reachable: true,

  reportFailure: () => {
    if (countingDown || !get().reachable) return;
    countingDown = true;
    showTimer = setTimeout(() => {
      showTimer = null;
      countingDown = false;
      set({ reachable: false });
      startProbe();
    }, SHOW_DELAY_MS);
  },

  reportSuccess: () => {
    clearShowTimer();
    countingDown = false;
  },
}));

/**
 * 服务回来了。
 *
 * 只有探针探到明确答复才走这里。**别让随便一条应答来撤遮罩**：开发模式下后端没起时
 * vite 的开发代理会拿一段纯文本 500 顶上，页面自己的轮询每十几秒就撞上一条，那样遮罩会
 * 亮一下又被抹掉，看着像好了，其实什么都没通。
 */
function markReachable(): void {
  if (useConnectionStore.getState().reachable) return;
  useConnectionStore.setState({ reachable: true });
  stopProbe();
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(RECONNECTED_EVENT));
  }
}

/**
 * 探一次服务。
 *
 * 要一个**明确的答复**才算服务回来：答得成 200、且返回体是 JSON。这一条比正常请求严，
 * 因为它是撤遮罩的判据——撤错了人对着一个连不上的页面继续点，比多等一轮更糟。也正因如此
 * 它挡得住开发模式下的假象：后端没起时 vite 的开发代理会拿一段纯文本 500 顶上来，那不是
 * 我们服务的答复。
 *
 * 探不到就是失败，不只是在遮罩亮着的时候用来确认，也是 WebSocket 断线那条快路的落点
 * （见 `handleSocketDisconnect`）。
 */
async function probe(): Promise<void> {
  if (!callNative) return;
  try {
    const res = await callNative(PROBE_PATH, { cache: 'no-store' });
    if (res.ok) {
      await res.json();
      markReachable();
      return;
    }
  } catch {
    // 没答上来，按失败走。
  }
  useConnectionStore.getState().reportFailure();
}

/**
 * WebSocket 断开时走这里：立刻探一次，探不到就按失败走。
 *
 * 断开本身不直接点亮遮罩——浏览器把睡觉的标签页的连接掐掉是常事，那时 HTTP 还好好的，
 * 直接亮会闪。探针答得上话就什么都不做。
 */
export function handleSocketDisconnect(): void {
  void probe();
}

function startProbe(): void {
  stopProbe();
  probeTimer = setInterval(() => void probe(), PROBE_INTERVAL_MS);
  // 立刻探一次：断连多半是服务在重启，几秒就回来了，不必干等满一轮。
  void probe();
}

/** 回环地址的几个写法。开发模式下接口走 127.0.0.1，页面在 localhost，两者算同一台机器。 */
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '0.0.0.0']);

/**
 * 这条请求是不是打给本机服务的。
 *
 * 两道都要过：路径在 `/api` 下，且去处是同一台机器——同一个主机名，或者两边都是回环
 * （开发模式下接口配成 127.0.0.1:8093，页面在 localhost:5173，那是同一份服务）。
 * 外网的请求一律不管：那边不通不该让整页变模糊。
 */
export function isBackendRequest(input: RequestInfo | URL): boolean {
  const raw =
    typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
  try {
    const page = new URL(globalThis.location?.href ?? 'http://localhost/');
    const target = new URL(raw, page);
    if (target.pathname !== '/api' && !target.pathname.startsWith('/api/')) return false;
    if (target.hostname === page.hostname) return true;
    return LOOPBACK_HOSTS.has(target.hostname) && LOOPBACK_HOSTS.has(page.hostname);
  } catch {
    return false;
  }
}

/** 人自己取消的请求（切页、改搜索词）不是断连。 */
function isAbort(err: unknown): boolean {
  return (err as { name?: string } | null)?.name === 'AbortError';
}

/** 装之前那个 fetch，原样留着以便卸载时换回去。 */
let originalFetch: typeof fetch | null = null;
/** 装上去的那一层包装，卸载时靠它认出「现在这个还是我装的吗」。 */
let installedWrapper: typeof fetch | null = null;
/** 原生函数绑好 this 的版本，供内部调用。 */
let callNative: typeof fetch | null = null;
let unsubscribeSocket: (() => void) | null = null;

/**
 * 给浏览器的 fetch 包一层，并订阅 WebSocket 断线。装一次就够，重复调用返回同一个卸载函数。
 *
 * 卸载会把一切还原干净：原生 fetch 换回去、计时器停掉、状态复位。测试里靠它保证各条用例
 * 互不串味。
 */
export function installConnectionMonitor(): () => void {
  if (originalFetch) return uninstallConnectionMonitor;

  if (!globalThis.fetch) return () => {};
  originalFetch = globalThis.fetch;
  const native = originalFetch.bind(globalThis);
  callNative = native;

  installedWrapper = (async (input: RequestInfo | URL, init?: RequestInit) => {
    if (!isBackendRequest(input)) return native(input, init);
    try {
      const res = await native(input, init);
      if (UNAVAILABLE_STATUS.has(res.status)) {
        useConnectionStore.getState().reportFailure();
      } else {
        useConnectionStore.getState().reportSuccess();
      }
      return res;
    } catch (err) {
      if (!isAbort(err)) useConnectionStore.getState().reportFailure();
      throw err;
    }
  }) as typeof fetch;
  globalThis.fetch = installedWrapper;

  unsubscribeSocket = watchSocket();

  return uninstallConnectionMonitor;
}

export function uninstallConnectionMonitor(): void {
  // 只认自己装上去的那一层：装完又有人把 fetch 换掉（测试里立桩就是这样），换回去等于
  // 把别人的东西抹了。
  if (originalFetch && globalThis.fetch === installedWrapper) {
    globalThis.fetch = originalFetch;
  }
  originalFetch = null;
  installedWrapper = null;
  callNative = null;
  unsubscribeSocket?.();
  unsubscribeSocket = null;
  clearShowTimer();
  stopProbe();
  countingDown = false;
  useConnectionStore.setState({ reachable: true });
}

/**
 * 盯着 WebSocket 断线。
 *
 * 它断得比 HTTP 轮询早——服务一没，连接当场就断，而下一趟轮询可能还在十几秒之后。断开
 * 走 `handleSocketDisconnect`。
 */
function watchSocket(): (() => void) | null {
  try {
    return getWebSocketClient().onDisconnect(handleSocketDisconnect);
  } catch {
    return null;
  }
}
