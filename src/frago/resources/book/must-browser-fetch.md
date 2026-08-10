# browser-fetch

分类: 替代（MUST）

## 是什么
获取网页内容必须通过 frago browser navigate 导航到目标页面，再用 get-content 提取内容。WebFetch 工具在 frago 环境中不可靠，且无法处理需要 JS 渲染的页面。

## 怎么用
  frago browser navigate "https://example.com/page" --group <name>
  frago browser get-content --group <name>              # 获取整页内容
  frago browser get-content --group <name> ".article"   # 获取指定区域

`--group <name>` 必带（recipe/run 环境里有 `FRAGO_CURRENT_RUN` 时可省）；缺了直接报错退出。
选择器是**位置参数**，不是 `--selector`——`get-content` 没有这个 flag。

## 什么时候用

适用范畴是**与搜索有关、与使用浏览器有关、与使用网页或网页数据有关的一切行为**，不限于「取一段远程网页正文」这一种形态。判定按行为落在哪个范畴，NEVER 按目的、按页面是本地还是远程、按是否只截一张图来给自己开口子。

落在范畴内的例子：
- 读任何网页内容、提取页面上的特定数据、与 SPA 交互
- 渲染任何 html（含 `file://` 本地文件）、截图、连拍测动效、验证前端改动
- 跑 JS、读 DOM、走 CDP 协议、抓接口返回

## 浏览器怎么起 —— 三层优先级

1. **`frago browser <cmd>`（默认 extension 后端）** —— 标准路径，覆盖绝大多数场景，包括 `file://` 本地渲染与截图。
2. **`frago browser -b cdp <cmd>`** —— 默认后端做不到时的合法降级路线：需要真无头、需要与 agent 浏览器互不干扰的独立实例、需要 `--void` / `--app` 这类启动形态。
3. **自起浏览器进程** —— 禁止，没有例外。

降级路线长这样（`-b` 是 `browser` 组级 flag，所有子命令通用）：

  frago browser -b cdp start --headless                              # 独立无头实例，端口默认 9222
  frago browser -b cdp navigate "file:///abs/path/page.html" --group <name>
  frago browser -b cdp screenshot out.png --full-page
  frago browser -b cdp stop

CDP 后端你用的端口永远是 9222（默认值，不用传 `--port`），profile 落在 `~/.frago/profiles/<浏览器>/9222/`（从系统 profile 初始化）。白名单里还有一个 9223，那是 agent_os 录制机位专用的，你没有理由碰它。选后端的判据见 `frago book browser-backend-choice`。

## 不要做
- 不要使用 WebFetch 工具
- 不要使用 curl 获取网页内容
- 不要假设页面是静态 HTML，始终通过浏览器渲染后获取
- 不要自己起浏览器进程（`chrome --headless`、`--screenshot`、`--remote-debugging-port` 等一律禁止）——需要无头或独立实例是**用 `-b cdp`** 的理由，不是自起进程的理由
