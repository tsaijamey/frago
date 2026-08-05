[English](browser-support.md)

# 浏览器支持

frago 通过两个后端驱动基于 Chromium 的浏览器：

- **extension（默认）** — 浏览器扩展 + native messaging 桥，驱动浏览器**自己的真实 profile**。无需任何 flag，是所有页面操作的标准路径。
- **cdp** — 旧版 Chrome DevTools Protocol 路径，需显式 `-b cdp` 选择。留给需要独立 CDP 实例（固定 9222 端口）的无头 / 录屏工作流（如 `agent_os` 录制机位）。

本文档默认讲 extension 后端。完整命令参考与反爬指南见内置 book：`frago book browser-usage`、`frago book browser-backend-choice`、`frago book browser-anti-bot`。

## 支持的浏览器

| 浏览器 | 支持状态 | 说明 |
|--------|----------|------|
| **Edge** | ✅ 默认 | 装有即优先选择（Stable > Beta > Dev） |
| **Chromium** | ✅ | 开源基础版 |
| **Chrome** | ✅（非 Stable） | Beta/Dev/Canary；Stable 被排除（v137+ 静默忽略 `--load-extension`） |
| **Brave / Vivaldi** | ✅ | 同样可自动探测 |
| **Firefox** | ❌ 不支持 | Firefox 141 (2025) 已移除 CDP |
| **Safari** | ❌ 不支持 | 无 CDP 支持 |

选择器按固定顺序取第一个已安装：Edge Stable → Edge Beta → Edge Dev → Chromium → Chrome Beta → Chrome Dev → Chrome Canary → Brave → Vivaldi。**不要传 `--browser`**：默认后端下它不换浏览器，只换 profile 目录指向。

## 浏览器探测

```bash
# 列出已装浏览器及 frago 会选谁
frago browser detect

# 各浏览器能力 + 运行状态
frago browser check
```

## 浏览器生命周期

```bash
# 启动：选浏览器 → 拉起扩展桥 → 打开其真实 profile
frago browser start

# 健康检查
frago browser status

# 关闭浏览器 + daemon + socket
frago browser stop
```

`start` 一条命令完成全链路：选浏览器 → 拉起 native messaging daemon → 写 manifest → 带扩展启动浏览器 → 等待桥握手。无需任何手工准备。

浏览器运行在**自己的默认 profile** 上（agent 可见其中登录态、密码、cookie，反之亦然）。同一 profile 同时只能有一个实例——start 撞锁会报错并提示先 stop。

### CDP 后端的启动选项

`--headless`、`--void`、`--app/--app-url`、`--width`、`--height`、`--port`、`--profile-dir`、`--no-kill`、`--keep-alive`、`--reseed-profile` 都是 **CDP 后端选项**。默认 extension 后端下会被静默丢弃。要用它们必须显式选 CDP：

```bash
frago browser -b cdp start --headless          # 无头 CDP 实例（9222 端口）
frago browser -b cdp start --void --keep-alive # 移出屏幕、保持运行
```

CDP 端口固定为 **9222**——唯一白名单端口。传其它值会被拒绝；禁止自创端口（见 `frago book` 中 CDP 端口白名单条目）。

## 页面操作

所有页面操作都走默认后端；`--group <name>` 把操作限定到某个 tab 组（缺省读 `FRAGO_CURRENT_RUN`）。

### 导航

```bash
# 导航到 URL 并等页面加载
frago browser navigate https://example.com

# 等选择器出现再返回
frago browser navigate https://example.com --wait-for '.content-loaded'

# 等 N 秒（支持小数）
frago browser wait 2
```

### 元素交互

```bash
# 点击元素
frago browser click "#submit-button"
frago browser click "button[type=submit]" --wait-timeout 15

# 执行 JavaScript（加 --return-value 取回返回值）
frago browser exec-js "document.title"
frago browser exec-js "return document.querySelectorAll('a').length" --return-value
```

### 页面内容

```bash
# 获取页面标题
frago browser get-title

# 获取页面或元素的文本内容（选择器缺省 body）
frago browser get-content
frago browser get-content "#main-content"
```

### 截图

```bash
# 页面截图（默认当前视口）
frago browser screenshot output.png

# 整页截图
frago browser screenshot page.png --full-page --quality 90
```

### 滚动

```bash
# 按像素滚动（正向下、负向上）或别名
frago browser scroll 500
frago browser scroll down
frago browser scroll page-down

# 滚动到元素（或按文本）
frago browser scroll-to "#footer"
frago browser scroll-to --text "Load more"
```

### 缩放

```bash
# 设置缩放（1.0 = 100%）
frago browser zoom 1.5
```

## Tab 管理

```bash
# 列出所有标签
frago browser list-tabs

# 按 id 切换标签（支持部分匹配）
frago browser switch-tab ABC123

# 关闭标签
frago browser close-tab ABC123

# Tab 组
frago browser groups
frago browser group-info <group_name>
frago browser group-close <group_name>
frago browser group-cleanup
```

## 视觉辅助

调试与演示用的视觉标记；两个后端都可用，`clear-effects` 能清掉任一后端留下的效果。

```bash
frago browser highlight "#target-element" --color "#FF6B6B"
frago browser pointer "#target-element"
frago browser spotlight "#focus-element" --life-time 5
frago browser annotate "#element" "This is important" --position top
frago browser underline "#text-element"
frago browser clear-effects
```

## Profile 管理

- **extension 后端** — 用浏览器自己的默认 profile。frago 不拷贝、不隔离、不清理。
- **cdp 后端** — 每个浏览器每个端口一个独立 profile：`~/.frago/profiles/<浏览器>/<端口>/`（如 `~/.frago/profiles/edge/9222`），从系统浏览器 profile 初始化。路径里端口始终显式。

```bash
# CDP 实例用自定义 profile（端口仍是 9222）
frago browser -b cdp start --profile-dir /path/to/custom/profile
```

## 反爬

extension 后端是真实浏览器环境，天然过 Cloudflare / Datadome / Akamai 检测。探测某个 group 当前页是否反爬挑战：

```bash
frago browser detect --group research
```

交互式 / 不可见 / 被拦截三档处置见 `frago book browser-anti-bot`。

## 平台注意事项

### Linux

- Wayland 会话下 void 模式自动走 XWayland。
- root 用户自动禁用 sandbox（`--no-sandbox`）。

### Windows

- 浏览器探测含注册表查询，可发现非常规安装路径。
- Windows 10/11 预装 Edge。

### macOS

- 浏览器在 `/Applications/` 中探测。
- Edge 可能需要手动安装。

## 故障排查

### 找不到浏览器

```bash
# 查看可用浏览器与 frago 会选谁
frago browser detect
frago browser check

# 确认浏览器可执行文件在 PATH 中
which microsoft-edge
which google-chrome
```

### 桥未连接

```bash
# 先看状态——未连就 start 再重试
frago browser status
frago browser start

# 桥错误是结构化 JSON，带 hint：{"ok": false, "code": ..., "hint": "run: frago browser start"}
```

### CDP 连接失败

```bash
# CDP 端口固定 9222 —— 看谁占着
lsof -i :9222   # Linux/macOS
netstat -an | findstr 9222   # Windows

# 停掉现有 CDP 实例再重启
frago browser -b cdp stop
frago browser -b cdp start
```

### 权限被拒（Linux）

root 运行需禁用 sandbox——frago 会自动处理，也可显式设置：

```bash
export FRAGO_NO_SANDBOX=1
frago browser -b cdp start
```
