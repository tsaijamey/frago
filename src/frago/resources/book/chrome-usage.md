# chrome-usage

frago chrome 操作完整指南。所有浏览器操作通过 frago chrome 命令执行，不直接调用 CDP 或浏览器 API。

## Group（前提）

每条 tab 操作命令 MUST 带 `--group` 参数指定 group 上下文，否则报错 `NO_GROUP`。

  {{frago_launcher}} chrome navigate <url> --group <name>
  {{frago_launcher}} chrome get-content --group <name> [selector]
  {{frago_launcher}} chrome click --group <name> <selector>
  {{frago_launcher}} chrome exec-js --group <name> <js>
  {{frago_launcher}} chrome screenshot --group <name> <output_file>

recipe/run 环境中 `FRAGO_CURRENT_RUN` 环境变量作为 fallback，此时可省略 `--group`。

group 保证：同 group 内所有命令自动跟随同一 tab；不同 group 互不干扰；30 分钟不活跃自动清理。

管理类命令（start/stop/status/groups/list-tabs 等）不需要 `--group`。

## Group 查询

  {{frago_launcher}} chrome groups               # 列出所有 group
  {{frago_launcher}} chrome groups --json        # JSON 格式
  {{frago_launcher}} chrome group-info <name>    # group 详情
  {{frago_launcher}} chrome group-close <name>   # 关闭 group

## 导航

  {{frago_launcher}} chrome navigate <url> --group <name>

URL 来源必须可信：用户提供、页面提取、搜索结果、recipe 输出。禁止凭记忆构造 URL。

不确定 URL 时，洋葱剥皮：先导航到已知首页 → exec-js 提取链接 → 用真实链接导航。

搜索用 Google：`{{frago_launcher}} chrome navigate "https://google.com/search?q=..." --group <name>`

## 内容提取

  {{frago_launcher}} chrome get-content --group <name> [selector]       # 提取文字和链接
  {{frago_launcher}} chrome exec-js --group <name> <js> --return-value  # 提取结构化数据

截图不用于阅读内容，仅用于验证状态和调试。

## 交互

  {{frago_launcher}} chrome click --group <name> <selector>             # JS-first，自动 fallback 坐标点击
  {{frago_launcher}} chrome click --group <name> <selector> --precise   # 强制坐标级（canvas、拖拽起点）
  {{frago_launcher}} chrome scroll --group <name> down|up               # 按页滚动
  {{frago_launcher}} chrome scroll --group <name> down --pixels 500     # 按像素
  {{frago_launcher}} chrome scroll-to --group <name> <selector>         # 滚动到元素

## 选择器

稳定性排序：aria-label / data-testid > 语义 ID > 语义 class > 结构选择器。避免 CSS-in-JS 生成的 class（.css-*、._*）。Twitter 用 data-testid，YouTube 用 aria-label。

验证选择器：`{{frago_launcher}} chrome highlight --group <name> <selector>` 或 `exec-js "document.querySelector(...) !== null"`

## 视觉辅助

  {{frago_launcher}} chrome highlight --group <name> <selector>         # 红色边框
  {{frago_launcher}} chrome pointer --group <name> <selector>           # 指针标记
  {{frago_launcher}} chrome spotlight --group <name> <selector>         # 聚光灯
  {{frago_launcher}} chrome annotate --group <name> <selector> --text "说明"
  {{frago_launcher}} chrome clear-effects --group <name>                # 清除所有效果

## Tab 管理

  {{frago_launcher}} chrome list-tabs                    # 查看所有 tab
  {{frago_launcher}} chrome switch-tab <id>              # 切换 tab（自动更新 group 的跟随目标）
  {{frago_launcher}} chrome close-tab <id>               # 关闭 tab

## 禁止

- 禁止 window.open() / raw CDP Target.createTarget 开 tab
- 禁止 exec-js 手写 scrollBy / element.click() 替代专用命令
- 禁止截图当阅读工具
- 禁止凭记忆猜测 URL

## 进一步阅读

`chrome-usage` 只覆盖通用层。下列场景需要再拉对应 topic：

- 选 cdp 还是 extension 后端、profile 隔离机制 → `{{frago_launcher}} book chrome-backend-choice`
- 遇到 anti-bot / Cloudflare / captcha / 验证码 → `{{frago_launcher}} book chrome-anti-bot`
- 启动浏览器换 browser/端口/headless/void/app 模式 → `{{frago_launcher}} book chrome-startup`
