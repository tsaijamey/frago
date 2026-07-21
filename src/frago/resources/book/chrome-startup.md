# chrome-startup

`frago chrome start` 拉起 agent 专用浏览器 + 扩展桥。默认零参数即可，一条命令完成全链路。

## 标准启动

```bash
{{frago_launcher}} chrome start                    # 自动选浏览器（优先 Edge），驱动其真实默认 profile
{{frago_launcher}} chrome start --browser chromium # 指定浏览器品牌（edge / chromium / brave / vivaldi ...）
{{frago_launcher}} chrome detect                   # 列出系统已装的浏览器
```

start 自动完成：选浏览器 → 拉起 native messaging daemon → 写 manifest → 加载 frago 扩展启动浏览器 → 等待桥握手。Chrome Stable 不可选（v137 起静默忽略 `--load-extension`）。

`--browser` 是 **start** 的 flag，不是 navigate / get-content 等命令的 flag。

## Profile

使用所选浏览器**自己的默认 profile**，不拷贝、不隔离。用户在该浏览器里手动登录、存的密码，agent 立即可见。该浏览器专给 agent 用，日常浏览器是另一个品牌，互不干扰。

同一 profile 同时只能有一个浏览器实例：start 撞锁会报错，先 `{{frago_launcher}} chrome stop` 或手动关窗口。

## 启动后

```bash
{{frago_launcher}} chrome status     # 健康检查（桥连接状态）
{{frago_launcher}} chrome groups     # 看 group 状态
{{frago_launcher}} chrome stop       # 关浏览器 + 停 daemon + 清 socket
```

## 反模式

- `frago chrome navigate --browser edge`：`--browser` 不是 navigate 的 flag，会报 `No such option`
- 给命令加 `-b`/`--backend`：默认后端就是标准路径，不需要
- `--headless` / `--void` / `--port` / `--profile-dir` / `--reseed-profile`：旧后端遗留选项，被忽略或已废弃
