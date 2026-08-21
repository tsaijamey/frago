/* 跟后端说话的唯一出口。
 *
 * 页面自己不知道后端在哪、数据目录在哪——这些由服务端每次请求现合成的
 * config.json 交代。所以启动顺序是死的：先拿 config，再拿别的。config 拿不到
 * 就不该硬猜一个地址继续跑，那样后面每个请求都会失败在跟真正原因无关的地方。
 *
 * 读盘一律走静态文件，不走 action：轮询每 800ms 一次，每次起一个配方子进程太重；
 * 而且访客模式下 apiBase 是 null，action 一个都调不通，静态文件却照样读得到。
 */

let CONFIG = null;

export function config() {
  return CONFIG;
}

/* 页面自己所在的目录，data/ 与 config.json 都挂在它下面。
   服务端给了 appBase 就用它，没给就从当前地址推——两种情况都要以 / 结尾，
   否则拼出来的 data/… 会把最后一段吃掉。 */
export function appBase() {
  const declared = CONFIG && CONFIG.appBase;
  const base = declared || window.location.pathname;
  return base.endsWith('/') ? base : base + '/';
}

async function getText(rel) {
  const sep = rel.includes('?') ? '&' : '?';
  const resp = await fetch(appBase() + rel + sep + 't=' + Date.now());
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText} — ${rel}`);
  return resp.text();
}

async function getJSON(rel) {
  return JSON.parse(await getText(rel));
}

export async function loadConfig() {
  const resp = await fetch('config.json?t=' + Date.now());
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText} — config.json`);
  CONFIG = await resp.json();
  return CONFIG;
}

// --- 磁盘真值 ---

/* 一次轮询看全局：active / projects_rev / panel_rev / scene_version 都在这一个小文件里。
   拆成四个文件各轮一遍的话，轮询次数翻倍，而且四份东西到达时机不同，
   页面会在半秒内闪过几种自相矛盾的状态。 */
export function fetchState() {
  return getJSON('data/state.json');
}

export function fetchProjects() {
  return getJSON('data/projects.json');
}

const projectFile = (slug, name) => `data/projects/${encodeURIComponent(slug)}/${name}`;

export function fetchScene(slug) {
  return getJSON(projectFile(slug, 'scene.json'));
}

export function fetchPanel(slug) {
  return getJSON(projectFile(slug, 'panel.json'));
}

/* 指挥记录是 JSONL，坏行跳过而不是整份放弃——
   一行写坏了就看不到全部历史，比看到少一行糟得多。 */
export async function fetchAgentLog(slug, limit = 12) {
  let raw;
  try {
    raw = await getText(projectFile(slug, 'agent_log.jsonl'));
  } catch {
    return [];      // 还没指挥过，文件不存在是正常的
  }
  const out = [];
  for (const line of raw.split('\n')) {
    const t = line.trim();
    if (!t) continue;
    try {
      out.push(JSON.parse(t));
    } catch {
      /* 跳过坏行 */
    }
  }
  return out.slice(-limit);
}

/* 回打后端跑一个 action。主人侧同步返回配方 stdout。 */
export async function run(params) {
  if (!CONFIG || !CONFIG.apiBase) {
    throw new Error('这是只读视图，跑不了动作');
  }
  const resp = await fetch(`${CONFIG.apiBase}/recipes/${CONFIG.recipeName}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ params }),
  });

  const raw = await resp.text();
  let data;
  try {
    data = JSON.parse(raw);
  } catch {
    throw new Error(`后端返回的不是 JSON：${raw.slice(0, 200)}`);
  }

  // frago server 把配方的 stdout 包一层：{ success, data: <配方返回>, ... }。
  // 外层 success 说的是「配方跑起来了没」，内层 success 说的是「这件事做成了没」，
  // 两层都要看——只看外层，配方返回的业务错误会被当成成功吞掉。
  if (data && data.success === false) {
    throw new Error(data.error || `配方没跑起来（HTTP ${resp.status}）`);
  }
  if (!resp.ok) {
    // 配方非零退出时，服务端只回 {"detail": "错误文本"}——结构化返回整个丢掉了。
    // 不认这个字段的话，人看到的就只剩一句「500 Internal Server Error」，
    // 而真正有用的那句话（缺了什么、可用的是什么）就在 detail 里。
    throw new Error(data.detail || data.error || `${resp.status} ${resp.statusText}`);
  }

  const payload = (data && (data.data || data.result)) || data;
  if (payload && payload.success === false) {
    const err = new Error(payload.error || '配方返回失败但没说原因');
    err.payload = payload;      // 指挥失败时页面要显示模型原话和被拒的理由
    throw err;
  }
  return payload;
}
