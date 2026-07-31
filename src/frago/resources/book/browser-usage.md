# browser-usage

frago browser 操作完整指南。所有浏览器操作通过 frago browser 命令执行，不直接调用 CDP 或浏览器 API。

唯一例外是把配方页面交给人看：那种页面用 `{{frago_launcher}} recipe open <url>` 开在用户的系统默认浏览器里，与本文讲的受控浏览器无关，agent 也控制不了它（见 `{{frago_launcher}} book interactive-recipe`）。除此之外，凡是 agent 自己要读、要点、要抓的页面，都走下面的命令。

## Group（前提）

每条 tab 操作命令 MUST 带 `--group` 参数指定 group 上下文，否则报错 `NO_GROUP`。

  {{frago_launcher}} browser navigate <url> --group <name>
  {{frago_launcher}} browser get-content --group <name> [selector]
  {{frago_launcher}} browser click --group <name> <selector>
  {{frago_launcher}} browser exec-js --group <name> <js>
  {{frago_launcher}} browser screenshot --group <name> <output_file>

recipe/run 环境中 `FRAGO_CURRENT_RUN` 环境变量作为 fallback，此时可省略 `--group`。

group 保证：同 group 内所有命令自动跟随同一 tab；不同 group 互不干扰；30 分钟不活跃自动清理。

下面这些命令不需要 `--group`（管理类，或自己就是全局操作）：

  start  stop  status  check  detect  wait  reset
  list-tabs  switch-tab  close-tab
  groups  group-info  group-close  group-cleanup

除此之外的每一条都必须有 group，缺了会报 `--group/-g required`。
`detect` 和 `wait` 两条可带可不带：`detect` 带上就从「列已装浏览器」变成「探测当前页反爬」，`wait` 带上才等在该 group 的页面上。

## Group 查询

  {{frago_launcher}} browser groups               # 列出所有 group
  {{frago_launcher}} browser groups --json        # JSON 格式
  {{frago_launcher}} browser group-info <name>    # group 详情
  {{frago_launcher}} browser group-close <name>   # 关闭 group
  {{frago_launcher}} browser group-cleanup        # 清掉 tab 已不存在的僵尸 group
  {{frago_launcher}} browser reset                # 关掉除落地页外的所有 tab（有 FRAGO_CURRENT_RUN 时只清本 group）

## 导航

  {{frago_launcher}} browser navigate <url> --group <name>

URL 来源必须可信：用户提供、页面提取、搜索结果、recipe 输出。禁止凭记忆构造 URL。

不确定 URL 时，洋葱剥皮：先导航到已知首页 → exec-js 提取链接 → 用真实链接导航。

搜索用 Google：`{{frago_launcher}} browser navigate "https://google.com/search?q=..." --group <name>`

## 内容提取

  {{frago_launcher}} browser get-content --group <name> [selector]       # 提取文字和链接
  {{frago_launcher}} browser get-title --group <name>                    # 只要标题
  {{frago_launcher}} browser exec-js --group <name> <js> --return-value  # 提取结构化数据

选择器是位置参数，`get-content` 没有 `--selector` 这个 flag。

抓回来的内容如果是 "Just a moment…" / "verify you are human" / 403 / 内容明显缺失，那是撞上反爬了，不是页面没加载好。**不要重试 navigate 或 click**，先 `{{frago_launcher}} browser detect --group <name>` 判档，处理办法见 `{{frago_launcher}} book browser-anti-bot`。

截图不用于阅读内容，仅用于验证状态和调试。

## 页面状态

  {{frago_launcher}} browser wait --group <name> 2        # 等待秒数，支持小数
  {{frago_launcher}} browser zoom --group <name> 0.8      # 缩放，1 为原始大小
  {{frago_launcher}} browser check                        # 各浏览器是否可用、走哪个后端、是否在跑

## 交互

  {{frago_launcher}} browser click --group <name> <selector>             # JS-first，自动 fallback 坐标点击
  {{frago_launcher}} browser click --group <name> <selector> --precise   # 强制坐标级（canvas、拖拽起点）
  {{frago_launcher}} browser scroll --group <name> down|up               # 按页滚动
  {{frago_launcher}} browser scroll --group <name> down --pixels 500     # 按像素
  {{frago_launcher}} browser scroll-to --group <name> <selector>         # 滚动到元素

## 选择器

稳定性排序：aria-label / data-testid > 语义 ID > 语义 class > 结构选择器。避免 CSS-in-JS 生成的 class（.css-*、._*）。Twitter 用 data-testid，YouTube 用 aria-label。

验证选择器：`{{frago_launcher}} browser highlight --group <name> <selector>` 或 `exec-js "document.querySelector(...) !== null"`

## 视觉辅助

  {{frago_launcher}} browser highlight --group <name> <selector>         # 红色边框
  {{frago_launcher}} browser pointer --group <name> <selector>           # 指针标记
  {{frago_launcher}} browser spotlight --group <name> <selector>         # 聚光灯
  {{frago_launcher}} browser annotate --group <name> <selector> --text "说明"
  {{frago_launcher}} browser underline --group <name> <selector>         # 文字逐行下划线动画
  {{frago_launcher}} browser clear-effects --group <name>                # 清除所有效果

## Tab 管理

  {{frago_launcher}} browser list-tabs                    # 查看所有 tab
  {{frago_launcher}} browser switch-tab <id>              # 切换 tab（自动更新 group 的跟随目标）
  {{frago_launcher}} browser close-tab <id>               # 关闭 tab

## 禁止

- 禁止 window.open() / raw CDP Target.createTarget 开 tab
- 禁止 exec-js 手写 scrollBy / element.click() 替代专用命令
- 禁止截图当阅读工具
- 禁止凭记忆猜测 URL

## 进一步阅读

`browser-usage` 只覆盖通用层。下列场景需要再拉对应 topic：

- 后端工作方式、profile 机制 → `{{frago_launcher}} book browser-backend-choice`
- 遇到 anti-bot / Cloudflare / captcha / 验证码 → `{{frago_launcher}} book browser-anti-bot`
- 启动浏览器、start 撞锁、以及为什么不要碰 `--browser` / `--port` / `--headless` → `{{frago_launcher}} book browser-startup`
