# browser-startup

`frago browser start` 拉起 agent 专用浏览器 + 扩展桥。默认零参数即可，一条命令完成全链路。

## 标准启动

```bash
frago browser start     # 零参数，自动选浏览器，驱动其真实默认 profile
frago browser check     # 看哪些浏览器可用、支持哪个后端、是否正在运行
frago browser detect    # 只列系统已装的浏览器及路径（带 --group 时改为探测反爬，见 browser-anti-bot）
frago browser install   # 取 frago 自带的 Chrome for Testing；已经有就什么都不做，--force 重取最新一版
```

start 自动完成：没有 CfT 就先取一份 → 选浏览器 → 拉起 native messaging daemon → 写 manifest → 加载 frago 扩展启动浏览器 → 等待桥握手。

**Chrome for Testing 是 frago 的默认浏览器**，它由 frago 自己下载、放在 `~/.frago/tools/chrome-for-testing/`，所有机器上都是这个位置。它排第一是因为它永远不是用户日常在用的那个浏览器，也不带厂商的登录与自动更新服务。选浏览器的顺序固定：Chrome for Testing → Edge Stable → Edge Beta → Edge Dev → Chromium → Chrome Beta → Chrome Dev → Chrome Canary → Brave → Vivaldi，取第一个可用的；CfT 之后的都是用户自己装的浏览器，只在 frago 没有自己那份 CfT 时才轮到。Chrome Stable 排在最后且被扩展后端排除：v137 起它静默忽略 `--load-extension`，而且它通常是用户自己天天在用的那个浏览器，agent 不该默认闯进去。`-b cdp` 的顺序同理：Edge → Chromium → Chrome。

**本机没有 CfT 时 frago 自己去取，不用人装。** `frago browser start` 和 agent_os 舞台发现 `~/.frago/tools/chrome-for-testing/` 下没有本平台那份，会先说明要用 CfT、取哪一版、多大、放哪儿，再下载、解压、跑一次 `--version` 验过，最后整目录挪进去（2026-09-15 实测 mac-arm64：191 MB，26 秒）。提前取或升级用 `frago browser install`。几处不会装成「文件在、起不来」的保证：

- 只认 Google 版本清单里有的平台：linux64、linux-arm64、mac-arm64、mac-x64、win32、win64。别的平台（如 Windows ARM）直接报没有官方 CfT。
- macOS 用 `ditto` 解压、Linux 用 `unzip`（没有就按 zip 里记的权限和符号链接还原），不用会丢这两样的 Python zipfile。
- 下载走本机代理探测（同浏览器那套，`FRAGO_BROWSER_PROXY` 可指定），失败报的是网络与所用代理。
- 两个进程同时发现缺 CfT，只有一个在下，另一个等它装好直接用。
- Linux 缺系统库时报出缺哪个库和补装命令——要 sudo，frago 不替人做。

取不到时两处表现不同：`start` 只提醒一句，退回上面那串用户自己装的浏览器；舞台直接起不来，决不去占人的 Edge / Chrome（原因见 `frago book desktop-usage`）。

**不要传 `--browser`——这条只针对默认的 extension 后端。** 那边它换不了浏览器：启动的仍是自动挑中的那个，它只把 profile 目录改成你写的品牌的目录，等于拿 A 浏览器去开 B 浏览器的数据目录。而且它只认 `chrome` / `edge` / `chromium` 三个值，其余（brave、vivaldi 等）会被直接拒；其中 `chrome` 尤其危险——那是用户日常浏览器的数据目录。

**`-b cdp` 下 `--browser` 是真的换浏览器**，profile 目录跟着走（`--browser chrome --port 9222` → `~/.frago/profiles/chrome/9222/`，除非再用 `--profile-dir` 另指）。全仓库只有一处该用它：agent_os 拉演员与机位时显式传 `--browser cft`——不交给默认值，因为这个默认改过不止一次，再改一次舞台就会静默换到另一份 profile，而这种错只在撞上登录墙那一刻才发现。舞台首选 CfT 的原因见 `frago book desktop-usage`。除此之外仍然让它自动挑。

## Profile

除 Chrome for Testing 外，使用所选浏览器**自己的默认 profile**，不拷贝、不隔离。CfT 是例外：它不是装出来的，没有厂商认定的 profile 位置，所以 profile 也归 frago，落在 `~/.frago/profiles/cft/extension/`。用户在该浏览器里手动登录、存的密码，agent 立即可见。该浏览器专给 agent 用，日常浏览器是另一个品牌，互不干扰。

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
