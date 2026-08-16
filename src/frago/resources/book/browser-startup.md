# browser-startup

`frago browser start` 拉起 agent 专用浏览器 + 扩展桥。默认零参数即可，一条命令完成全链路。

## 标准启动

```bash
frago browser start     # 零参数，自动选浏览器，驱动其真实默认 profile
frago browser check     # 看哪些浏览器可用、支持哪个后端、是否正在运行
frago browser detect    # 只列系统已装的浏览器及路径（带 --group 时改为探测反爬，见 browser-anti-bot）
```

start 自动完成：选浏览器 → 拉起 native messaging daemon → 写 manifest → 加载 frago 扩展启动浏览器 → 等待桥握手。

**Edge 是 frago 的默认浏览器**，两个后端都一样。选浏览器的顺序固定：Edge Stable → Edge Beta → Edge Dev → Chromium → Chrome Beta → Chrome Dev → Chrome Canary → Brave → Vivaldi，取第一个装了的。Chrome Stable 排在最后且被扩展后端排除：v137 起它静默忽略 `--load-extension`，而且它通常是用户自己天天在用的那个浏览器，agent 不该默认闯进去。`-b cdp` 的顺序同理：Edge → Chromium → Chrome。

**不要传 `--browser`——这条只针对默认的 extension 后端。** 那边它换不了浏览器：启动的仍是自动挑中的那个，它只把 profile 目录改成你写的品牌的目录，等于拿 A 浏览器去开 B 浏览器的数据目录。而且它只认 `chrome` / `edge` / `chromium` 三个值，其余（brave、vivaldi 等）会被直接拒；其中 `chrome` 尤其危险——那是用户日常浏览器的数据目录。

**`-b cdp` 下 `--browser` 是真的换浏览器**，profile 目录跟着走（`--browser chrome --port 9222` → `~/.frago/profiles/chrome/9222/`，除非再用 `--profile-dir` 另指）。全仓库只有一处该用它：agent_os 拉演员与机位时显式钉 `--browser edge`——Edge 当前虽然就是默认值，但这个默认改过一次，再改一次舞台就会静默换到另一份几乎空白的 profile，而这种错只在撞上登录墙那一刻才发现。除此之外仍然让它自动挑。

## Profile

使用所选浏览器**自己的默认 profile**，不拷贝、不隔离。用户在该浏览器里手动登录、存的密码，agent 立即可见。该浏览器专给 agent 用，日常浏览器是另一个品牌，互不干扰。

同一 profile 同时只能有一个浏览器实例：start 撞锁会报错，先 `frago browser stop` 或手动关窗口。

## 启动后

```bash
frago browser status     # 健康检查（桥连接状态）
frago browser groups     # 看 group 状态
frago browser stop       # 关浏览器 + 停 daemon + 清 socket
```

## 反模式

- `frago browser start --browser <任意值>`：默认后端下换不了浏览器，只会让 profile 目录错位（见上）。`-b cdp` 下它有效，但除 agent_os 拉舞台之外没有该用它的场合
- `frago browser navigate --browser edge`：`--browser` 只有 start 有，别的命令会报 `No such option`
- 无理由加 `-b`/`--backend`：默认后端就是标准路径；有理由时（真无头、独立实例、`--void`/`--app`）才显式降到 `-b cdp`
- 在默认后端下写 `--headless` / `--void` / `--app` / `--port` / `--profile-dir` / `--reseed-profile`：这些是 CDP 后端的选项，会被静默丢弃，写了不生效——要用就 `frago browser -b cdp start --headless`
- 自己起浏览器进程（`chrome --headless`、`--remote-debugging-port`）：一律禁止，上面那条降级路线已经覆盖这些需求，见 `frago book browser-backend-choice`
