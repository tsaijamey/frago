[English](browser-support.md)

# 浏览器支持

frago 通过两个后端驱动基于 Chromium 的浏览器：

- **extension（默认）** — 浏览器扩展 + native messaging 桥，驱动浏览器**自己的真实 profile**。无需任何 flag，是所有页面操作的标准路径。
- **cdp** — Chrome DevTools Protocol 路径，需显式 `-b cdp` 选择。默认后端做不到时的降级路线：真无头、需要与常驻浏览器互不干扰的独立实例、`--void` / `--app` / `--profile-dir` 这类启动形态。CDP 端口是白名单制：**9222**（默认）与 **9223**（agent_os 录制机位）。

优先级固定为 **默认 extension > `-b cdp` > 自起浏览器进程（禁止）**。`chrome --headless`、`--remote-debugging-port`、自己连原生 CDP 一律不在选项里——无头与独立实例的需求由 `-b cdp` 覆盖。

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

选择器按固定顺序取第一个已安装：Edge Stable → Edge Beta → Edge Dev → Chromium → Chrome Beta → Chrome Dev → Chrome Canary → Brave → Vivaldi。

**`--browser` 在不同后端下含义不同。** extension 后端下它不换浏览器——只改 profile 目录指向；`-b cdp` 下它是真的换浏览器，profile 路径跟着走（`--browser chrome` → `~/.frago/profiles/chrome/9222/`）。frago 自己只有在 agent_os 舞台拉起演员与机位时才显式钉 `--browser edge`；其余场合都让选择器自动挑。

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

CDP 端口白名单只有 **9222**（默认）与 **9223**（agent_os 录制机位），传别的值会被拒绝，禁止自创端口。**9222 是公用的**：虚拟桌面舞台在跑时，它的演员就住在这台实例上，为的是复用播种来的登录 profile——而 `-b cdp start` 默认会顶掉端口上已有的实例（除非加 `--no-kill`）。起之前先 `frago desktop status` 看舞台在不在跑（见 `frago book browser-backend-choice`）。

## Tab 组

**一个 group 就是浏览器标签栏上一个真的标签组**——带颜色、能折叠、组名
写在上面。agent 开的每个页面都进它自己的组，两个 agent 同时干活也碰不到
彼此的页面，人扫一眼标签栏就知道这几页是谁开的。

每条页面命令都带 `--group <name>`（缺省读 `FRAGO_CURRENT_RUN`）。整个模型
就四条规矩：

1. **一组最多 5 个标签。** 开第 6 个会失败，并把挡路的那 5 个列出来，让
   调用方自己决定关掉哪个。不会静默踢掉最旧的——agent 以为页面还在、下一
   条命令却落在别的页上，这种错没有任何地方会提醒它。
2. **navigate 默认替换，不新开。** 替换的是这个 group 的**当前标签**（最后
   一次 navigate 或 switch-tab 指到的那个），不是浏览器里正显示的那个。人
   正在读的页面不会被换掉。
3. **`--new` 是唯一的开页方式。**
4. **用完 `group-close`。** 整整 30 分钟没有任何动静（命令、切换激活、页面
   内滚动都算），整组自动关掉——那是兜底，不是流程。

```bash
frago browser groups                    # 所有 group：用了几个标签、还有多久过期
frago browser group-info <name>         # 标签清单、当前标签、闲置时长
frago browser group-close <name>        # 用完了就关
frago browser group-cleanup             # 清掉标签已不存在的僵尸 group
```

## 页面操作

### 导航

```bash
# 替换 group 的当前标签
frago browser navigate https://example.com --group research

# 在同一个 group 里新开一个标签（最多 5 个）
frago browser navigate https://example.com/b --group research --new

# 等选择器出现再返回
frago browser navigate https://example.com --group research --wait-for '.content-loaded'

# 等 N 秒（支持小数）
frago browser wait --group research 2
```

### 元素交互

```bash
# 点击元素
frago browser click --group research "#submit-button"
frago browser click --group research "button[type=submit]" --wait-timeout 15

# 执行 JavaScript（加 --return-value 取回返回值）
frago browser exec-js --group research "document.title"
frago browser exec-js --group research "document.querySelectorAll('a').length" --return-value
```

### 页面内容

```bash
# 获取页面标题
frago browser get-title --group research

# 获取页面或元素的文本内容（选择器缺省 body）
frago browser get-content --group research
frago browser get-content --group research "#main-content"
```

### 截图

```bash
# 页面截图（默认当前视口）
frago browser screenshot --group research output.png

# 整页截图
frago browser screenshot --group research page.png --full-page --quality 90
```

### 滚动

```bash
# 按像素滚动（正向下、负向上）或别名
frago browser scroll --group research 500
frago browser scroll --group research down
frago browser scroll --group research page-down

# 滚动到元素（或按文本）
frago browser scroll-to --group research "#footer"
frago browser scroll-to --group research --text "Load more"
```

### 缩放

```bash
# 设置缩放（1.0 = 100%）
frago browser zoom --group research 1.5
```

## Tab 管理

tab 命令一律在 group **之内**生效：一个 group 只看得见、也只动得了自己的标签。

```bash
# 本组的标签清单，带 * 的那个是命令落点
frago browser list-tabs --group research

# 让后续命令改落在某一页（id 支持前缀匹配）。
# 它只改命令落点，不动浏览器的可见状态。
frago browser switch-tab --group research ABC123

# ……顺便把它切到人眼前
frago browser switch-tab --group research ABC123 --activate

# 关掉本组的一页——组满了就靠它腾位置
frago browser close-tab --group research ABC123
```

CDP 后端的规则完全一样，只有一处做不到：CDP 碰不到浏览器的标签组界面，
所以那边的 group 只是账本，标签不会在标签栏上并成一条。

## 视觉辅助

调试与演示用的视觉标记；两个后端都可用，`clear-effects` 能清掉任一后端留下的效果。

```bash
frago browser highlight --group research "#target-element" --color "#FF6B6B"
frago browser pointer --group research "#target-element"
frago browser spotlight --group research "#focus-element" --life-time 5
frago browser annotate --group research "#element" "This is important" --position top
frago browser underline --group research "#text-element"
frago browser clear-effects --group research
```

## Profile 管理

- **extension 后端** — 用浏览器自己的默认 profile。frago 不拷贝、不隔离、不清理。
- **cdp 后端** — 每个浏览器每个端口一个独立 profile：`~/.frago/profiles/<浏览器>/<端口>/`（如 `~/.frago/profiles/edge/9222`），从系统浏览器 profile 初始化。路径里端口始终显式。

```bash
# CDP 实例用自定义 profile（端口仍是 9222）
frago browser -b cdp start --profile-dir /path/to/custom/profile
```

## 虚拟桌面舞台

`frago desktop` 驱动一块可脚本操控的假桌面（一个真实 tmux 会话、一个真实
浏览器标签页、一张本地图片），供 `agent_os` 配方录制回放。舞台在跑时，
两个 CDP 端口都归它：

- **9222** — 舞台**演员**：一台无头 Edge，profile 从你真实的 Edge 登录态
  播种而来。它和独立 `frago browser -b cdp start` 会瞄准的是同一台实例，
  所以舞台在跑时不要起、也不要停 CDP 实例。
- **9223** — **机位**：`camera up`（或 `rec start` 自动架机位）时创建，
  `rec stop` / `camera down` 时整台收走。

动手前先 `frago desktop status`。完整用法见 `frago book desktop-usage`。

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
# 端口是白名单制：9222（默认）与 9223（agent_os 机位）
lsof -i :9222 -i :9223   # Linux/macOS
netstat -an | findstr 9222   # Windows

# 舞台在跑时，演员占着 9222——别碰它
frago desktop status

# 否则停掉现有 CDP 实例再重启
frago browser -b cdp stop
frago browser -b cdp start
```

### 权限被拒（Linux）

root 运行需禁用 sandbox——frago 会自动处理，也可显式设置：

```bash
export FRAGO_NO_SANDBOX=1
frago browser -b cdp start
```
