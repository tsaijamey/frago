# chrome-backend-choice

frago chrome 有两套后端，行为差异显著。选错会绕路或失败。

## 后端选择

```
{{frago_launcher}} chrome -b cdp <cmd>        # 默认；FRAGO_CHROME_BACKEND env 也可设
{{frago_launcher}} chrome -b extension <cmd>  # 通过浏览器扩展 + native messaging
```

`-b/--backend` 是 `chrome` 顶层的 flag，位置必须在子命令**之前**（`chrome -b extension detect`），写在子命令后面会报 `No such option`。

## backend 与 browser 是两个正交维度

- `start --browser edge` 只决定启动**哪个 Chromium 系浏览器**（Chrome / Edge / Chromium），控制通道仍是默认的 CDP，profile 用 `~/.frago/profiles/` 隔离，不碰用户日常浏览器。
- `-b extension` 换的是控制通道：扩展 + native messaging。它同样由 frago 完整管理浏览器生命周期，但用的是独立的 extension-profile 和自动挑选的浏览器（见下节），不是用户日常浏览器本体。
- 换浏览器 ≠ 换后端；反爬要过检靠的是 extension 后端，不是换成 Edge。

| 维度 | CDP | Extension |
|------|-----|-----------|
| 命令覆盖 | 全部 26 条 | 全部对齐（navigate/exec-js/get-content/click/screenshot/tab/group/visual/wait 均可用）|
| 浏览器生命周期 | start/stop 完整管理 | start/stop 同样完整管理（自动选浏览器 + 拉起 daemon + 装 manifest + 加载扩展）|
| anti-bot 探针 | ❌（`detect --group` 会报错）| ✅ `detect --group <g>` 独有 |
| 通过 CF / Akamai | 易被检测 | 真实浏览器环境，过检率高 |
| 启动选项（headless/void/profile-dir/port） | ✅ | ❌（自动管理 profile，CDP-only 选项被忽略；仅 `--reseed-profile` 是 extension 专属）|
| 可用浏览器 | Chrome / Edge / Chromium | Edge / Chromium / Chrome Beta+ / Brave / Vivaldi（Chrome Stable ≥v137 静默忽略 --load-extension，被排除）|
| 性能 / 调试 | 直连 DevTools，最快 | 多一层 RPC，略慢 |

**默认选 CDP**。下列场景切 extension：
1. 网站有 anti-bot 检测（Cloudflare / Datadome / PerimeterX / Akamai）
2. 需要 `frago chrome detect --group <g>` 探针返回 challenge 状态
3. 受限环境（localhost:9222 不可用，比如某些公司网络）
4. 走真人 profile（用户日常用的浏览器扩展、登录态）做"代为操作"

## Profile 隔离机制（CDP 后端）

CDP 启动浏览器时用 `--user-data-dir=~/.frago/profiles/<browser>/<port>/`，**跟系统浏览器 profile 完全隔离**：

- **首次**启动从系统 profile（`Default/` + `Local State`）拷贝一次：登录态、cookies、书签带过来
- 之后两边各走各的——frago 里改不影响系统浏览器，反之亦然
- 不同 `--port` 启动会派生独立 profile（`~/.frago/profiles/<browser>/<port>/`），多实例并存

含义：
- agent 第一次开 frago Chrome 看到的是用户当时的快照，不必担心污染日常浏览器
- 反过来：日常浏览器后续登的新账号、装的新扩展，frago 这边看不到——必要时 `rm -rf ~/.frago/profiles/<browser>/<port>` 让它下次启动重新从系统拷

`--profile-dir <path>` 可指定独立 profile 目录（多账号场景）。

## Extension 后端的生命周期

`{{frago_launcher}} chrome -b extension start` 一条命令完成全链路，无需任何手工准备：

- 自动挑选可用浏览器：优先 Edge，其次 Chromium / Chrome Beta+ / Brave / Vivaldi。Chrome Stable 被刻意排除——v137 起它静默忽略 `--load-extension`，装了也连不上。
- 以独立 profile（`~/.frago/chrome/extension-profile`）启动，不碰用户日常浏览器数据。首次启动会从系统 profile 继承登录态、cookies、书签（与 CDP 相同的隔离拷贝机制，只拷一次，之后各走各的）；`start --reseed-profile` 可删除该 profile 并重新从系统拷一份。
- 自动 `--load-extension` 加载 frago 扩展 bundle、拉起 native messaging daemon、写 per-profile manifest，等待握手完成后返回。
- `stop` 对称拆除：关浏览器 + 停 daemon + 清 socket（`~/.frago/chrome/extension.sock`）。
- 桥未连时执行任何命令，CLI 返回 `{"ok": false, "code": ..., "hint": "run: frago chrome -b extension start"}` 结构化错误（非零退出码），按 hint 先 start 即可。

## 决策流

```
任务 → 是否反爬场景？
        ├─ 是 → -b extension（先 detect 探一下）
        └─ 否 → -b cdp（默认即可）
              → 需要换 browser/port/headless？→ 见 chrome-startup
```
