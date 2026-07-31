# browser-startup

`frago browser start` 拉起 agent 专用浏览器 + 扩展桥。默认零参数即可，一条命令完成全链路。

## 标准启动

```bash
{{frago_launcher}} browser start     # 零参数，自动选浏览器，驱动其真实默认 profile
{{frago_launcher}} browser check     # 看哪些浏览器可用、支持哪个后端、是否正在运行
{{frago_launcher}} browser detect    # 只列系统已装的浏览器及路径（带 --group 时改为探测反爬，见 browser-anti-bot）
```

start 自动完成：选浏览器 → 拉起 native messaging daemon → 写 manifest → 加载 frago 扩展启动浏览器 → 等待桥握手。

选浏览器的顺序固定：Edge Stable → Edge Beta → Edge Dev → Chromium → Chrome Beta → Chrome Dev → Chrome Canary → Brave → Vivaldi，取第一个装了的。Chrome Stable 被排除（v137 起静默忽略 `--load-extension`）。

**不要传 `--browser`。** 默认后端下它换不了浏览器：启动的仍是自动挑中的那个，它只把 profile 目录改成你写的品牌的目录，等于拿 A 浏览器去开 B 浏览器的数据目录。而且它只认 `chrome` / `edge` / `chromium` 三个值，其余（brave、vivaldi 等）会被直接拒；其中 `chrome` 尤其危险——那是用户日常浏览器的数据目录。

## Profile

使用所选浏览器**自己的默认 profile**，不拷贝、不隔离。用户在该浏览器里手动登录、存的密码，agent 立即可见。该浏览器专给 agent 用，日常浏览器是另一个品牌，互不干扰。

同一 profile 同时只能有一个浏览器实例：start 撞锁会报错，先 `{{frago_launcher}} browser stop` 或手动关窗口。

## 启动后

```bash
{{frago_launcher}} browser status     # 健康检查（桥连接状态）
{{frago_launcher}} browser groups     # 看 group 状态
{{frago_launcher}} browser stop       # 关浏览器 + 停 daemon + 清 socket
```

## 反模式

- `frago browser start --browser <任意值>`：默认后端下换不了浏览器，只会让 profile 目录错位（见上）
- `frago browser navigate --browser edge`：`--browser` 只有 start 有，别的命令会报 `No such option`
- 给命令加 `-b`/`--backend`：默认后端就是标准路径，不需要
- `--headless` / `--void` / `--app` / `--port` / `--profile-dir` / `--reseed-profile`：CDP 后端的选项，默认后端下被静默丢弃，写了不生效
