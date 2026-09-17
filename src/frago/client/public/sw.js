/**
 * 断连也打得开的一层壳。
 *
 * 这个页面平时由 8093 上的 frago 服务自己发。服务停了再按 F5，浏览器连的是那个端口，一行
 * 页面代码都还没轮到执行就被拒了，屏幕上只剩「无法访问此网站」——页面里那张重连遮罩进都
 * 进不来。这个 worker 把首屏那几份文件在本地留一份：导航先问服务，服务答不上就发存量，
 * 于是服务不在的时候页面照样起得来，起得来就归页面自己的遮罩管（api/connection.ts）。
 *
 * 三条规矩：
 *
 * 1. 接口一律不碰。打给 `/api` 的请求原样直连——服务不在就得让它真的失败，遮罩认的正是
 *    这个。替服务答一个存下来的旧数据比连接被拒还坏：人会拿过期内容当现在的用。
 * 2. 导航先问服务。问得到就用新的、顺手存下，问不到才发存量。所以只要服务在，看到的一定
 *    是当前这一版，不会出现「服务已经好了、页面还是旧的」。
 * 3. 静态文件按内容寻址。文件名里带哈希，同名即同内容，命中直接发，不必再问一趟。
 *
 * 换策略时把 CACHE_NAME 的版本号改掉：activate 会把别的版本一并清掉。
 */

const CACHE_NAME = 'frago-shell-v1';

/** 外壳就是首页那一份 HTML。站内各条路由发的是同一份，存一份够用。 */
const SHELL_URL = '/';

/** 内容寻址的静态文件都在这条路径下（构建时出来的 assets/[name]-[hash].[ext]）。 */
const ASSET_PREFIX = '/assets/';

/** 从 HTML 里挑出它要用的静态文件。挑不到就什么都不做，绝不据此删东西。 */
const ASSET_REF = /\/assets\/[A-Za-z0-9._-]+/g;

self.addEventListener('install', (event) => {
  // 不等旧页面关掉：这个 worker 只管导航和静态文件，中途换人不打扰正在跑的那一页。
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      await dropOtherCaches();
      // 第一次装上时页面早就加载完了，它那几份文件没经过我，得自己去取一遍。少了这一步，
      // 头一次打开之后马上断连，按 F5 还是打不开。
      await precacheShell();
      await self.clients.claim();
    })()
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  let url;
  try {
    url = new URL(request.url);
  } catch (_) {
    return;
  }
  if (url.origin !== self.location.origin) return;
  // 接口直连，连碰都不碰。
  if (url.pathname === '/api' || url.pathname.startsWith('/api/')) return;

  if (request.mode === 'navigate') {
    event.respondWith(serveShell(request));
    return;
  }
  if (url.pathname.startsWith(ASSET_PREFIX)) {
    event.respondWith(serveAsset(request));
  }
});

/** 服务答得上就用新的并存下，答不上就发存的那份。 */
async function serveShell(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    // `cache: 'no-cache'` 是问**浏览器自己那层缓存**要一次重新验证。少了它，这一句
    // fetch 可能压根没出门：浏览器手里存着上一版 HTML、又还在它自己估的新鲜期内，就
    // 直接把旧的塞回来。于是第 2 条规矩（"只要服务在，看到的一定是当前这一版"）在界面
    // 刚重建过的那一刻正好失效——而那正是它唯一要紧的时刻。
    const fresh = await fetch(request, { cache: 'no-cache' });
    if (fresh && fresh.ok) await storeShell(cache, fresh);
    return fresh;
  } catch (err) {
    const stored = await cache.match(SHELL_URL);
    if (stored) return stored;
    throw err;
  }
}

/** 名字里带哈希，命中即同内容。 */
async function serveAsset(request) {
  const cache = await caches.open(CACHE_NAME);
  const stored = await cache.match(request);
  if (stored) return stored;
  const fresh = await fetch(request);
  if (fresh && fresh.ok) await cache.put(request, fresh.clone());
  return fresh;
}

async function precacheShell() {
  try {
    const fresh = await fetch(SHELL_URL, { cache: 'no-cache' });
    if (!fresh || !fresh.ok) return;
    await storeShell(await caches.open(CACHE_NAME), fresh);
  } catch (_) {
    // 装的时候服务就不在。下一次导航会自己补上。
  }
}

/** 存下这份 HTML，并按它把静态文件对齐。 */
async function storeShell(cache, response) {
  const html = await response.clone().text();
  await cache.put(
    SHELL_URL,
    new Response(html, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers,
    })
  );
  await syncAssets(cache, html);
}

/**
 * 按刚拿到的这份 HTML 把静态文件对齐。
 *
 * 每重建一次界面，文件名里的哈希就换一批：跟着这份 HTML 要的新文件得先躺进缓存，否则断连
 * 那会儿首屏有、它要的 JS 没有，照样白屏；上一版留下的不再被任何一份 HTML 引用，留着没人
 * 问，清掉免得一年下来堆出几百兆。
 */
async function syncAssets(cache, html) {
  const wanted = new Set(html.match(ASSET_REF) || []);
  // 一份都没认出来（产物形状变了）就原地不动：宁可留着旧的，也不能把正在用的删了。
  if (wanted.size === 0) return;

  await Promise.all(
    [...wanted].map(async (path) => {
      try {
        if (await cache.match(path)) return;
        const fresh = await fetch(path, { cache: 'no-cache' });
        if (fresh && fresh.ok) await cache.put(path, fresh);
      } catch (_) {
        // 缺一份不耽误别的，下一次导航再补。
      }
    })
  );

  const stored = await cache.keys();
  await Promise.all(
    stored.map((request) => {
      const path = new URL(request.url).pathname;
      if (!path.startsWith(ASSET_PREFIX) || wanted.has(path)) return null;
      return cache.delete(request);
    })
  );
}

async function dropOtherCaches() {
  const names = await caches.keys();
  await Promise.all(
    names.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name))
  );
}
