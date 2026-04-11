# chrome-usage

frago chrome 操作完整指南。所有浏览器操作通过 frago chrome 命令执行，不直接调用 CDP 或浏览器 API。

## Group（前提）

每条 chrome 命令必须有 group 上下文，否则报错 `NO_GROUP`。

  --group <name>              # 显式指定
  FRAGO_CURRENT_RUN 环境变量   # recipe/run 环境自动设置

group 保证：同 group 内 navigate 后 get-content/click/screenshot 自动跟随同一 tab；不同 group 互不干扰；30 分钟不活跃自动清理。

## 导航

  frago chrome navigate <url> --group <name>

URL 来源必须可信：用户提供、页面提取、搜索结果、recipe 输出。禁止凭记忆构造 URL。

不确定 URL 时，洋葱剥皮：先导航到已知首页 → exec-js 提取链接 → 用真实链接导航。

搜索用 Google：`frago chrome navigate "https://google.com/search?q=..."`

## 内容提取

  frago chrome get-content [selector]       # 提取文字和链接
  frago chrome exec-js <js> --return-value  # 提取结构化数据

截图不用于阅读内容，仅用于验证状态和调试。

## 交互

  frago chrome click <selector>             # JS-first，自动 fallback 坐标点击
  frago chrome click <selector> --precise   # 强制坐标级（canvas、拖拽起点）
  frago chrome scroll down|up               # 按页滚动
  frago chrome scroll down --pixels 500     # 按像素
  frago chrome scroll-to <selector>         # 滚动到元素

## 选择器

稳定性排序：aria-label / data-testid > 语义 ID > 语义 class > 结构选择器。避免 CSS-in-JS 生成的 class（.css-*、._*）。Twitter 用 data-testid，YouTube 用 aria-label。

验证选择器：`frago chrome highlight <selector>` 或 `exec-js "document.querySelector(...) !== null"`

## 视觉辅助

  frago chrome highlight <selector>         # 红色边框
  frago chrome pointer <selector>           # 指针标记
  frago chrome spotlight <selector>         # 聚光灯
  frago chrome annotate <selector> --text "说明"
  frago chrome clear-effects                # 清除所有效果

## Tab 管理

  frago chrome list-tabs                    # 查看所有 tab
  frago chrome switch-tab <id>              # 切换 tab（自动更新 group 的跟随目标）
  frago chrome close-tab <id>               # 关闭 tab

## 禁止

- 禁止 window.open() / raw CDP Target.createTarget 开 tab
- 禁止 exec-js 手写 scrollBy / element.click() 替代专用命令
- 禁止截图当阅读工具
- 禁止凭记忆猜测 URL
