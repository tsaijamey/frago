# browser-backend-choice

使用浏览器的优先级只有三层，从上往下降级：

1. **`frago browser <cmd>`** —— extension 后端（默认，无需任何 flag）。标准路径，绝大多数场景直接跑，不需要做后端选择。
2. **`frago browser -b cdp <cmd>`** —— 默认后端做不到时的合法降级：需要真无头、需要与 agent 浏览器互不干扰的独立实例、需要 `--void` / `--app` / `--profile-dir` 这类启动形态（agent_os 的舞台浏览器与录制机位都走这条）。
3. **自起浏览器进程**（`chrome --headless`、`--remote-debugging-port`、自己连原生 CDP）—— 禁止，没有例外。

先默认，做不到再 `-b cdp`；两条都在 `frago browser` 之内，任何绕过 frago 直连浏览器的做法都不在选项里。

## 工作方式

```
frago browser start        # 拉起浏览器 + 扩展桥（自动完成全链路）
frago browser <cmd> ...    # navigate / get-content / click / detect 等全部命令
frago browser stop         # 对称拆除
```

控制通道是浏览器扩展 + native messaging，运行在真实浏览器环境里：

- **Edge 是 frago 的浏览器。** 自动挑选顺序固定，取第一个装了的：Edge Stable → Edge Beta → Edge Dev → Chromium → Chrome Beta → Chrome Dev → Chrome Canary → Brave → Vivaldi。Chrome Stable 被刻意排除——v137 起它静默忽略 `--load-extension`。`-b cdp` 那条路也是同一个优先级（Edge → Chromium → Chrome），两条路落在同一个浏览器上，agent 的登录态才只有一份。
- **直接使用所选浏览器自己的默认 profile**（如 Edge 的 `~/Library/Application Support/Microsoft Edge`），不做隔离拷贝。该浏览器是专给 agent 用的（用户日常浏览器是另一个品牌）；用户在这个浏览器里手动登录、保存的密码，agent 立即可见，反之亦然。
- 真实浏览器环境天然过 anti-bot 检测（Cloudflare / Datadome / Akamai），`detect --group <g>` 探针可用（见 `frago book browser-anti-bot`）。
- 同一时刻该 profile 只能有一个浏览器实例；start 撞锁会报错并提示先 stop。

## start 完成的全链路

`frago browser start` 一条命令：选浏览器 → 拉起 native messaging daemon → 写 manifest（`<profile>/NativeMessagingHosts/`）→ 带 `--load-extension` 启动浏览器 → 等待桥握手。无需任何手工准备。

桥未连时执行任何命令，CLI 返回 `{"ok": false, "code": ..., "hint": "run: frago browser start"}` 结构化错误（非零退出码），按 hint 先 start 即可。

## 默认后端下不要做的事

以下都是针对 **extension 后端的常规 browser 操作**：

- 不要为了"更保险"顺手加 `-b cdp`——默认后端够用时就用默认，降级要有具体理由（见下节）。
- 不要给 start 加 `--browser`：默认后端下它**不换浏览器**，只把 profile 目录换成该品牌的目录，启动的仍是自动挑中的那个浏览器。结果是拿 A 浏览器去开 B 浏览器的数据目录。让它自动挑。
- 不要用 `--headless` / `--void` / `--app` / `--port` / `--profile-dir` / `--reseed-profile`：这些是 CDP 后端的选项，默认后端下被静默丢弃，写了也不生效。要用它们就显式降到 `-b cdp`。
- 不要手动管理 profile 目录：profile 就是浏览器自己的，frago 不拷贝、不清理。

## 第二层：`-b cdp` 怎么用

什么时候降级——满足任一条即可：

- 要**真无头**（不弹窗口、不占屏幕）。extension 后端只给**前台**标签产帧，要连续拿画面就得让那个标签一直占着人的屏幕——agent_os 的舞台浏览器正是因为这一条从 extension 换回了 `-b cdp`。
- 要一个**独立实例**，不能占用/干扰 agent 那个常驻浏览器（如 agent_os 的录制机位）
- 要 `--void`（移出屏幕）/ `--app`（无边框窗口）/ `--profile-dir`（指定 profile）这类只有 CDP 后端提供的启动形态

```bash
frago browser -b cdp start --headless          # 独立无头实例，端口默认 9222
frago browser -b cdp start --void --keep-alive # 移出屏幕、保持运行
frago browser -b cdp navigate "file:///abs/path/page.html" --group <name>
frago browser -b cdp screenshot out.png --full-page
frago browser -b cdp stop                      # 对称拆除
```

`-b` 是 `browser` 组级 flag，位置在子命令之前，所有子命令通用。

CDP 后端的 profile 是独立的：`~/.frago/profiles/<浏览器>/9222/`，从系统浏览器 profile 初始化——首次启动要整棵拷贝，慢且占盘，这也是"能用默认就别降级"的实际代价。这份 profile 已经攒了一批站点的登录态，是 9222 值钱的地方。

group 的规则两个后端完全一致：一组最多 5 个标签、navigate 默认替换当前
标签、`--new` 才开新页、tab 命令只能碰本组的标签、30 分钟静默自动关组。
唯一差别是 CDP 碰不到浏览器的标签组界面，所以那边的 group 只是账本，标签
不会在标签栏上并成一条带名字的组。这不是没实现，是 CDP 协议里没有这个东西：
向浏览器要 `/json/protocol`，57 个域里 `tabGroup` 出现 0 次，标签组只有
`chrome.tabGroups` 这一个入口，而那是扩展 API。

**端口只有 9222 与 9223 两个，你自己用的永远是 9222。** 传别的数会被 CLI 直接拒；自创端口会在 `~/.frago/profiles/<浏览器>/<port>/` 留下垃圾 profile 目录、数据分叉。

- **9222** 默认值，不用传 `--port`。agent_os 的舞台浏览器（演员）也常驻在这一台上，就是为了复用那份登录态——所以你在 9222 上开的标签会出现在虚拟桌面的标签条里，舞台跑着的时候尽量别拿它开新标签。
- **9223** agent_os 的录制机位专用，只在录制期间存在，你没有理由自己去用它。它必须与演员分开：停录时机位会 `-b cdp stop` 收走自己，共用端口那一下会把演员连同登录态一起带走。

## 第三层：禁止

`chrome --headless`、`chrome --screenshot`、`chrome --remote-debugging-port=<x>`、自己拿 websocket 连原生 CDP——一律禁止。想无头、想独立实例、想指定 profile，第二层全都提供；绕过 frago 意味着没有 group 隔离、没有 tab 台账、没有反爬环境，且留下没人回收的进程与 profile。
