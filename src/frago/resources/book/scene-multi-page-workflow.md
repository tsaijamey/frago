# scene-multi-page-workflow

场景类型: 跨页面操作

## 问题特征
任务需要在多个网页或标签页之间切换操作。每个页面可能有不同的状态和交互模式。

## 典型触发
- 从 A 网站收集信息填到 B 网站
- 多标签页对比内容
- 登录后跳转的多步流程
- 监控多个页面状态

## 推荐路径

  1. {{frago_launcher}} run find <workflow 关键词>           # 搜索历史类似任务
  2. {{frago_launcher}} recipe list | grep workflow        # 检查已有 workflow recipe
  2. {{frago_launcher}} chrome navigate <第一个页面>
  3. {{frago_launcher}} chrome list-tabs                    # 查看当前标签页
  4. {{frago_launcher}} chrome navigate <第二个页面>        # 自动在新标签打开或复用
  5. {{frago_launcher}} chrome switch-tab <tab_id>          # 在标签页间切换
  6. 每次切换后 get-content 确认页面状态

## 关键约束
- must-tab-creation — 打开新 URL 用 {{frago_launcher}} chrome navigate
- must-navigation — 不猜测页面间的跳转 URL
- chrome-click — 点击可能触发新标签页打开
- visual-effects — 在复杂页面中高亮定位目标元素

## 常见陷阱
- 不查 list-tabs → 不知道当前有哪些标签页
- 在错误的标签页执行操作 → 操作目标错误
- 页面加载未完成就操作 → 元素找不到
- 不记录每步状态 → 出错后无法回溯
