# chrome-startup

`frago chrome start` 启动浏览器。默认参数适合大多数场景；下面的 flags 是真实存在的、容易遗漏的。

## 浏览器选择

```bash
{{frago_launcher}} chrome start                    # auto-detect: Chrome > Edge > Chromium
{{frago_launcher}} chrome start --browser edge     # 指定 Edge
{{frago_launcher}} chrome start -b chromium        # 指定 Chromium（短形式）
{{frago_launcher}} chrome detect                   # 列出系统已装的浏览器
```

注意 `--browser` 是 **start** 的 flag，不是 navigate / get-content 等命令的 flag。需要换浏览器时**重启**——一个 frago 实例同时只跑一个浏览器后端。

## 启动模式（互斥四选一）

```bash
{{frago_launcher}} chrome start                              # default：可见窗口
{{frago_launcher}} chrome start --headless                   # 无 UI（CI / 服务器适用）
{{frago_launcher}} chrome start --void                       # 窗口移出屏幕外（保留 GPU/动画但不打扰桌面）
{{frago_launcher}} chrome start --app --app-url <url>        # 无边框 app 模式（嵌入式场景）
```

`--void` 是 frago 特色：相比 headless 行为更接近真实浏览器（不少反爬只检查 headless），相比可见窗口又不抢用户桌面。

## 端口与多实例

```bash
{{frago_launcher}} chrome start --port 9333    # 默认 9222；换端口 = 独立 profile（自动后缀）
```

要并行跑两个浏览器实例（如 Chrome + Edge）必须不同 `--port`。profile 目录自动派生为 `~/.frago/<browser>_profile_<port>`。

## Profile 控制

```bash
{{frago_launcher}} chrome start --profile-dir <path>    # 自定义 profile 目录（多账号场景）
```

不指定时默认 `~/.frago/<browser>_profile`，首次启动从系统 profile 拷贝（详见 `frago book chrome-backend-choice` 的 Profile 隔离段）。

## 进程管理

```bash
{{frago_launcher}} chrome start --no-kill        # 不杀已运行的浏览器进程，复用现有窗口
{{frago_launcher}} chrome start --keep-alive     # 启动后阻塞前台，Ctrl+C 关闭（调试用）
```

默认 frago start 会 kill 同 profile 的旧实例后重启。`--no-kill` 适合"已经手动开了浏览器，让 frago 接上"的场景。

## 窗口尺寸（CDP 后端）

```bash
{{frago_launcher}} chrome start --width 1920 --height 1080
{{frago_launcher}} chrome start --app --window-x 100 --window-y 100   # app 模式定位
```

## 一次启动成功后

```bash
{{frago_launcher}} chrome status     # 健康检查（CDP 连接 + 浏览器版本）
{{frago_launcher}} chrome groups     # 看 group 状态
```

## 反模式

- `frago chrome navigate --browser edge`：`--browser` 不是 navigate 的 flag，会报 `No such option`
- 同时启动两个浏览器但忘记换 `--port`：第二个会失败或挤掉第一个
- 反爬场景用 `--headless`：headless 浏览器指纹明显，更易被识别——见 `frago book chrome-anti-bot`
