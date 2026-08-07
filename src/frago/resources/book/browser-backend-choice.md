# browser-backend-choice

使用浏览器的优先级只有三层，从上往下降级：

1. **`frago browser <cmd>`** —— extension 后端（默认，无需任何 flag）。标准路径，绝大多数场景直接跑，不需要做后端选择。
2. **`frago browser -b cdp <cmd>`** —— 默认后端做不到时的合法降级：需要真无头、需要与 agent 浏览器互不干扰的独立实例、需要 `--void` / `--app` / `--profile-dir` 这类启动形态（agent_os 的录制机位就走这条）。
3. **自起浏览器进程**（`chrome --headless`、`--remote-debugging-port`、自己连原生 CDP）—— 禁止，没有例外。

先默认，做不到再 `-b cdp`；两条都在 `frago browser` 之内，任何绕过 frago 直连浏览器的做法都不在选项里。

## 工作方式

```
frago browser start        # 拉起浏览器 + 扩展桥（自动完成全链路）
frago browser <cmd> ...    # navigate / get-content / click / detect 等全部命令
frago browser stop         # 对称拆除
```

控制通道是浏览器扩展 + native messaging，运行在真实浏览器环境里：

- 自动挑选浏览器，顺序固定：Edge Stable → Edge Beta → Edge Dev → Chromium → Chrome Beta → Chrome Dev → Chrome Canary → Brave → Vivaldi，取第一个装了的。Chrome Stable 被刻意排除——v137 起它静默忽略 `--load-extension`。
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

- 要**真无头**（不弹窗口、不占屏幕）
- 要一个**独立实例**，不能占用/干扰 agent 那个常驻浏览器（如 agent_os 的录制机位）
- 要 `--void`（移出屏幕）/ `--app`（无边框窗口）/ `--profile-dir`（指定 profile）这类只有 CDP 后端提供的启动形态

```bash
frago browser -b cdp start --headless          # 独立无头实例，端口固定 9222
frago browser -b cdp start --void --keep-alive # 移出屏幕、保持运行
frago browser -b cdp navigate "file:///abs/path/page.html" --group <name>
frago browser -b cdp screenshot out.png --full-page
frago browser -b cdp stop                      # 对称拆除
```

`-b` 是 `browser` 组级 flag，位置在子命令之前，所有子命令通用。

CDP 后端的 profile 是独立的：`~/.frago/profiles/<浏览器>/9222/`，从系统浏览器 profile 初始化——首次启动要整棵拷贝，慢且占盘，这也是"能用默认就别降级"的实际代价。

**端口只有 9222。** 9222 是唯一白名单值，传别的会被 CLI 直接拒（`frago book` 中的 CDP 端口白名单条目）；自创端口会在 `~/.frago/profiles/chrome/<port>/` 留下垃圾 profile 目录、数据分叉。

## 第三层：禁止

`chrome --headless`、`chrome --screenshot`、`chrome --remote-debugging-port=<x>`、自己拿 websocket 连原生 CDP——一律禁止。想无头、想独立实例、想指定 profile，第二层全都提供；绕过 frago 意味着没有 group 隔离、没有 tab 台账、没有反爬环境，且留下没人回收的进程与 profile。
