# interactive-recipe

分类: 效率（AVAILABLE）

## 解决什么问题
agent 要做人机协作的配方（用户审核、标注、选择），需要知道页面从哪来、状态怎么交给页面、页面用什么地址打开、由谁打开。

## 一件必须先记住的事

配方页面是**给人看的**，它开在 **frago WebUI 里**：左边菜单 recipes 下面 pin 一行子菜单，页面在右侧显示。agent 看不见也关不掉。

WebUI 已经开着，就直接切到这一页，不开新标签；没开着，才让系统默认浏览器打开 WebUI 指向这一页的地址（`http://localhost:8093/#/app/<配方名>`，非默认槽位是 `…/#/app/<配方名>/<槽位>`）。人在 WebUI 里点子菜单回到页面，点 × 摘掉。

打开它只用一条命令：

  frago recipe open <配方名>            # 站在配方外面，手里只有名字时
  frago recipe open <完整地址>          # 配方跑完自己调，publish 已经把地址给它了
  frago recipe open <配方名> --slot <槽位>   # 同一配方存了多份结果时挑一份

配方名会被展开成 `http://localhost:8093/app/<配方名>`。给的东西既不是已发布的配方名、也不是能打开的地址时，命令直接退非零，NEVER 交给浏览器——浏览器对着一个不成立的地址只会开白页，不会报错，那样错误会被当成成功。

NEVER 用 `frago browser navigate` 打开配方页面。那条命令驱动的是 agent 自己的受控浏览器，用途是抓网页、做自动化；配方页面走它既没有意义，也会让 agent 误以为页面在自己手里。两条路的分工如下：

| 命令 | 开在哪里 | 谁在看 | agent 能否控制 |
|------|---------------|--------|---------------|
| `frago recipe open <配方名\|地址>` | frago WebUI 右侧（没开着时由系统默认浏览器打开 WebUI） | 人 | 不能 |
| `frago browser navigate <url> --group <g>` | frago 驱动的受控浏览器 | agent | 能 |

批量跑一个带界面的配方前先想清楚：跑 50 次就是把人正在看的 WebUI 连切 50 次，每个槽位还在菜单里多 pin 一行，而 agent 收不回来。批量场景用配方的非界面模式（多数带界面的配方都留了只出数据的入参），或者一次只跑一局。

## 适用场景

| 场景 | 为什么需要交互 |
|------|---------------|
| 媒体标注 | 用户选择片段、标记时间戳 |
| 多步创作流程 | 用户在步骤间审核、调整 |
| 参考素材分配 | 用户指定图片用途 |
| 质量控制 | 用户审批或拒绝结果 |

不适合：全自动任务、无头环境、无需人看一眼的批处理。

## 页面住在哪

  http://localhost:8093/app/<配方名>

这个地址固定不变，人能读、能记、能收藏。同一个配方跑第二次、第十次，地址还是它，不会每次生出一个新的。

页面的 html / css / js 就放在配方自己的 `assets/` 目录里，服务端直接从那里发出去，**不复制**。改完前端刷新页面即可看到，磁盘上不会留下副本。

  ~/.frago/recipes/workflows/<配方名>/
  ├── recipe.md           # 元数据（type: workflow, runtime: python）
  ├── recipe.py           # 脚本：算出这一轮的状态，发布，打开页面
  └── assets/
      ├── index.html
      ├── app.js
      └── style.css

服务端在 `/app/<配方名>/` 下开出四条路径：

| 路径 | 发出什么 |
|------|---------|
| `/app/<配方名>/` | 配方 `assets/index.html` |
| `/app/<配方名>/config.json` | 每次请求现合成，磁盘上没有这个文件 |
| `/app/<配方名>/data/<相对路径>` | 从配方声明的数据目录按需读，不复制 |
| `/app/<配方名>/<其他文件>` | `assets/` 里的其余静态文件 |

前端一律用相对路径取这些东西（`fetch('config.json')`、`fetch('data/x.json')`），页面不需要知道自己挂在哪。

## 脚本这一侧要做的两件事

### 发布这一轮的状态

页面开出来要显示什么，由配方在每次运行结束时发布。状态是一个 JSON 对象，从标准输入进去，命令回一个页面地址：

  frago recipe publish <配方名> [--slot <槽位>]

  # 状态过大不好用管道时
  frago recipe publish <配方名> --state-file /path/to/state.json

Python 里的写法：

```python
import json
import subprocess

def publish_page(state: dict, slot: str = 'default') -> str:
    r = subprocess.run(
        ['frago', 'recipe', 'publish', '<配方名>', '--slot', slot],
        input=json.dumps(state, ensure_ascii=False),
        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f'发布页面状态失败: {r.stderr.strip()[:300]}')
    return r.stdout.strip()          # 页面地址
```

状态里放页面自己算不出来的东西：要显示的文件清单、页面可以调的子配方名。**NEVER 往里放路径**——基类的 `publish` 会当场拒绝，页面那一侧也没有这台机器的文件系统。服务端在发出 `config.json` 时会再补上四个字段：

| 字段 | 值 |
|------|-----|
| `apiBase` | `/api`（相对路径，换台设备访问也不会断） |
| `recipeName` | 配方名 |
| `appBase` | `/app/<配方名>/` |
| `slot` | 本次读的槽位名 |

运行期数据不要往 `assets/` 里塞，也不要复制到别处：写进平台交代的落点（`self.data_dir`）就行。`/app/<配方名>/data/<文件>` 直接从那里读，**配方不用说、也说不了那个目录在哪**——服务端按请求者自己算出来，主人、登录用户、未登录的人各算各的，读的和写的是同一个判断。

所以状态里只放文件的名字，不放它的位置：

```python
self.publish({
    'files': [f.name for f in media_files],   # 页面拼 data/<name> 去取
    'generatedAt': stamp,
})
```

数据分项目的配方（一次跑一件互不相干的活），项目就是落点里的一层目录，页面按 `data/projects/<项目名>/<文件>` 取。用的是配方自己的项目名，不是机器上的位置。

以前这里写的是「在状态里声明 `dataDir`」。那条路已经关了：配方交给页面的东西里出现路径，`publish` 直接报错——同一句 `dataDir` 在主人机器上指主人的目录，别人打开页面时会把主人的文件原样送出去，而且页面渲染得好好的、不报任何错。

### 把页面交给人

  frago recipe open <url>

```python
def open_browser(url: str) -> bool:
    r = subprocess.run(['frago', 'recipe', 'open', url],
                       capture_output=True, text=True, timeout=30)
    return r.returncode == 0
```

打不开不算致命：把地址原样吐出来，让人自己粘贴。标准输出这样写：

```json
{"success": true, "url": "http://localhost:8093/app/<配方名>", "browser_opened": true}
```

还有一条更省事的路：标准输出里带上 `open_url` 字段，runner 看到就替你开，同样开在 WebUI 里。脚本自己不必调 `recipe open`：

```json
{"success": true, "open_url": "http://localhost:8093/app/<配方名>", "url": "...", "slot": "..."}
```

两条路选一条，别同时用，否则一次运行会把页面打开两遍。

### 每一种结局都要落到人看得见的地方

人在页面**外面**按下运行（WebUI 的运行按钮、命令行、agent 调用），能看到的只有两样：这次运行的结局提示，和平台替它打开的页面。所以配方的每一条出口——成功、**被拒**——都要把人带到能继续往下做的地方。平台保证的和配方要做的分开如下：

| 谁 | 负责什么 |
|----|---------|
| 配方 | 说清结局：成功就给 `open_url`；被拒就用 `self.refuse(...)`，写原因、给出处理这件事的页面 |
| 平台 | 决定开不开：页面外发起的照开（开在 WebUI 里）；**从配方自己页面上发起的一律不开**；访客发起的一律不开 |
| WebUI | 结果里有拒绝，就把配方写的原因显示出来，不报「执行成功」 |

**被拒不是失败。** 还有一局没打完、账户没钱、今天的数据还没到——配方看过之后说不，运行本身是对的。用 `raise self.fail(...)` 会变成失败加非零退出码，登录访客只会看到一句「the run failed」。用基类的拒绝出口：

```python
if live is not None:
    return self.refuse(
        'open_session',                       # 原因代号，页面可以据此分支
        '你还有一局没打完，先结束它再开新局。',  # 给人看的话，WebUI 原样显示
        page=live['session_id'],              # 去哪儿处理：槽位名；True 是不带槽位的短地址
        session_id=live['session_id'],        # 其余字段照常带回
    )
```

它交回 `{"refused": 代号, "message": 原话, "url": 地址, "open_url": 地址, ...}`。这个形状就是约定，不用基类的配方照这个形状写也一样被认。参数里 `open=false` 时只给 `url`、不给 `open_url`。

页面地址用 `self.page_url(槽位)` 取，NEVER 自己拼 `http://localhost:8093/app/...`。

**反例（2026-09-15，kline_blind_trainer）**：在 WebUI 按运行开新局，配方因为还有一局没打完而拒绝，但拒绝结果里没带页面地址——平台无页可开，WebUI 又把它报成「已启动」。人按了两次，屏幕上什么都没发生。同一个配方的页面自己点「开新局」时，成功结果带着新一局的地址，平台照开，于是页面整页重载、WebUI 菜单里每开一局多一行。前一半靠 `refuse(..., page=...)` 修，后一半现在由平台统一挡掉，页面不用再传 `open=false`。

## 同时开好几份

多数配方只需要一份，槽位参数可以不管：再跑一次就换掉页面上显示的东西，跟刷新一个看板是同一回事。

真要同时开着好几份（一个视频项目一份、一局训练一份）才用槽位。槽位名跟在地址后面：

  http://localhost:8093/app/<配方名>?key=<槽位>

不带 `?key=` 时给的是默认那份。一个常见做法是同一份状态发布两次——一次进本局的槽位，一次进默认槽位——这样人手敲那个不带参数的短地址，看到的总是最近开的那一局。

槽位状态落在 `~/.frago/app-state/<配方名>/<槽位>.json`，写入是原子的，页面在半路刷新也读不到写了一半的文件。

## 借用别人的前端

一套前端确实要服务好几个配方时，在配方元数据里写一行：

```yaml
ui_from: <另一个配方名>
```

服务端就去那个配方的 `assets/` 取文件，本配方不必再放一份副本。

## 页面这一侧

### 加载配置

```javascript
const r = await fetch('config.json', { cache: 'no-store' });
const cfg = await r.json();
// cfg.apiBase / cfg.recipeName / cfg.appBase / cfg.slot 由服务端补齐
```

### 读写文件

```javascript
const resp = await fetch(`${cfg.apiBase}/file?path=${encodeURIComponent(filePath)}`);
const data = await resp.json();

// 二进制文件（图片等）直接当 src 用
img.src = `${cfg.apiBase}/file?path=${encodeURIComponent(imagePath)}`;
```

```javascript
await fetch(`${cfg.apiBase}/file?path=${encodeURIComponent(filePath)}`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ content: JSON.stringify(data, null, 2) })
});
```

配方自己的运行期数据走 `data/` 更直接，不用暴露绝对路径：

```javascript
const bars = await (await fetch('data/records.json')).json();
```

### 调用配方

```javascript
const resp = await fetch(`${cfg.apiBase}/recipes/${cfg.recipeName}/run`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ params: { action: 'step', session_id: cfg.sessionId } })
});
```

页面需要改服务端状态时，走这条路回到配方脚本里去改，别让前端直接写状态文件——脱敏、校验、结算这些事只有脚本那一侧做得对。

### 缓存

不必再往 script 标签后面追时间戳。服务端对 `/app/` 下每个响应都要求浏览器回来校验一次，改了前端刷新就是新的，没改则回 304。

### 自动保存与快捷键

```javascript
let autoSaveTimeout = null;
function autoSave() {
  if (autoSaveTimeout) clearTimeout(autoSaveTimeout);
  autoSaveTimeout = setTimeout(saveProject, 2000);
}
```

```javascript
document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  switch (e.key.toLowerCase()) {
    case 's': if (e.ctrlKey || e.metaKey) { e.preventDefault(); saveProject(); } break;
  }
});
```

## recipe.md 要求

必须带 interactive 标签：

  tags:
    - interactive
    - workflow

**还 MUST 写这一行**——本篇通篇让脚本 shell 出去调 `frago recipe publish` / `frago recipe open`，
配方跑在一个只看得见指定目录的视图里，不声明就拿不到 frago 命令自己的工作目录：

  uses_frago_cli: true

不写的后果：`frago recipe validate` 直接拒，隔离下那两条命令也跑不动。

inputs 里通常有工作目录之类的入参。outputs 里给 `url`，需要区分多份时再给 `slot`。

`content_id` 已经废弃——它描述的那个哈希目录不存在了，出参里还留着它就是在指向一个空地址。

## 前置条件

1. frago server 运行中：`frago server`（端口 8093）
2. 工作目录存在，脚本启动时自行校验

不需要 `frago browser start`。配方页面与那个受控浏览器没有关系，把它写进前置条件会让后来的 agent 以为页面归自己管。

## 创建检查清单

- recipe.md 含 interactive 标签
- recipe.md 写了 `uses_frago_cli: true`（脚本要调 `frago recipe publish` / `open`）
- 前端文件留在配方 `assets/` 里，不复制到任何地方
- 脚本用 `frago recipe publish` 发布状态，取回地址
- 运行期数据写进平台交代的落点，状态里只放文件名，前端走 `data/<文件名>` 读
- 脚本用 `frago recipe open` 打开页面，失败时照样把地址吐给人
- 每条「被拒」出口都用 `self.refuse(代号, 原话, page=...)`，给出人去处理的页面
- 页面用相对路径 `fetch('config.json')` 取配置，用 `cfg.apiBase` 拼接接口
- 页面实现自动保存，常用操作配快捷键
- 页面要调的子配方声明在 dependencies 里

## 样板

`~/.frago/recipes/workflows/kline_blind_trainer/recipe.py` 是一份实测跑通的完整例子：一局一个槽位、状态脱敏后发布、页面全部动作回打配方脚本、打不开浏览器就把地址交回给人。

## 不要做

- 不要用 `frago browser navigate` 打开配方页面
- 不要复制 `assets/`，不要往磁盘写 `config.json`
- 不要用哈希拼 `content_id`，不要再提 `viewer/content/<哈希>/`
- 不要把接口基地址写死成 `http://127.0.0.1:8093/api`
- 不要在前端给 script 标签追时间戳绕缓存
- 不要把「Chrome CDP 可用」写进带界面配方的前置条件
- 不要用 `raise self.fail` 表达「看过之后说不」，也不要返回一个不带页面地址的拒绝
- 不要自己拼页面地址，用 `self.page_url()`
