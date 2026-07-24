# chrome-backend-choice

frago chrome 只有一种标准用法：extension 后端（默认，无需任何 flag）。所有 chrome 子命令直接跑即可，不存在"什么场景选什么后端"的判断。

## 工作方式

```
{{frago_launcher}} chrome start        # 拉起浏览器 + 扩展桥（自动完成全链路）
{{frago_launcher}} chrome <cmd> ...    # navigate / get-content / click / detect 等全部命令
{{frago_launcher}} chrome stop         # 对称拆除
```

控制通道是浏览器扩展 + native messaging，运行在真实浏览器环境里：

- 自动挑选浏览器：优先 Edge，其次 Chromium / Chrome Beta+ / Brave / Vivaldi。Chrome Stable 被刻意排除——v137 起它静默忽略 `--load-extension`。
- **直接使用所选浏览器自己的默认 profile**（如 Edge 的 `~/Library/Application Support/Microsoft Edge`），不做隔离拷贝。该浏览器是专给 agent 用的（用户日常浏览器是另一个品牌）；用户在这个浏览器里手动登录、保存的密码，agent 立即可见，反之亦然。
- 真实浏览器环境天然过 anti-bot 检测（Cloudflare / Datadome / Akamai），`detect --group <g>` 探针可用（见 `{{frago_launcher}} book chrome-anti-bot`）。
- 同一时刻该 profile 只能有一个浏览器实例；start 撞锁会报错并提示先 stop。

## start 完成的全链路

`{{frago_launcher}} chrome start` 一条命令：选浏览器 → 拉起 native messaging daemon → 写 manifest（`<profile>/NativeMessagingHosts/`）→ 带 `--load-extension` 启动浏览器 → 等待桥握手。无需任何手工准备。

桥未连时执行任何命令，CLI 返回 `{"ok": false, "code": ..., "hint": "run: frago chrome start"}` 结构化错误（非零退出码），按 hint 先 start 即可。

## 不要做的事

以下都是针对 **extension 后端的常规 chrome 操作**（本篇的全部范围）：

- 不要给命令加 `-b`/`--backend` flag——默认后端就是唯一标准路径。
- 不要用 `--headless` / `--void` / `--port` / `--profile-dir` / `--reseed-profile`：这些是旧后端遗留选项，extension 模式下被忽略或已废弃。
- 不要手动管理 profile 目录：profile 就是浏览器自己的，frago 不拷贝、不清理。

## 唯一例外：agent_os 的录制机位

`--port` 的禁令**不适用于** agent_os 那套无头录制机位——它显式走 CDP 后端（`-b cdp`）、必须带 `--port 9222`，是与本篇并行的另一条路径，不是 extension 后端下的违规用法。

判别方法：做的是常规浏览网页、抓内容、点击交互 → 本篇规则，禁用 `--port`；做的是 agent_os 录制机位 → 走 CDP、只用 9222，见 `{{frago_launcher}} book` 中的 CDP 端口白名单条目。9222 之外的任何端口在两条路径下都禁止自创。
