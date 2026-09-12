/**
 * 把离线外壳那个 worker 挂上（脚本见 public/sw.js，构建时原样落到产物根目录）。
 *
 * 只在发出去的产物里挂。开发时页面是 vite 现编现发的，留一份外壳存量只会让人对着旧模块
 * 调半天；桌面端走 file://，那里根本没有 worker 可挂。挂不上也不算错——页面照常跑，只是
 * 少了「断连后按 F5 还能进得来」这一条。
 */

/**
 * worker 脚本在产物根目录，作用域因此是整个站点。
 *
 * 要接管的正是「打开首页」这条导航，脚本搁进 /assets 下就只能管到那一层，够不着。
 */
export const SHELL_WORKER_URL = '/sw.js';

/**
 * 这套东西在这台机器上能不能用。
 *
 * 浏览器得认 serviceWorker；页面得是 http(s) 来的——file:// 下注册必被拒，明文 http 的
 * 局域网地址不是安全上下文，同样挂不上。
 */
export function shellWorkerAvailable(): boolean {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return false;
  const protocol = globalThis.location?.protocol;
  return protocol === 'http:' || protocol === 'https:';
}

export function registerShellWorker(): void {
  if (!import.meta.env.PROD) return;
  if (!shellWorkerAvailable()) return;

  // 更新时绕开 HTTP 缓存再问一遍：留着存量外壳的东西，绝不能让 worker 自己也被留成旧的。
  void navigator.serviceWorker.register(SHELL_WORKER_URL, { updateViaCache: 'none' }).catch(() => {
    // 挂不上就当没这回事。多半是这一版没带上这个文件，页面一切照旧。
  });
}
