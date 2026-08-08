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

同一个 group 里最多摊得下 5 页，多页流程就是靠这 5 个格子来回倒。

  1. frago run find <workflow 关键词>                        # 搜索历史类似任务
  2. frago recipe list | grep workflow                     # 检查已有 workflow recipe
  3. frago browser navigate <A 页面> --group <g>            # 第一页
  4. frago browser navigate <B 页面> --group <g> --new      # 需要同时留着 A 才加 --new
  5. frago browser list-tabs --group <g>                    # 本组标签，带 * 的是当前页
  6. frago browser switch-tab --group <g> <tab_id>          # 把后续命令切到某一页
  7. 每次切换后 get-content 确认页面状态
  8. frago browser group-close <g>                          # 收尾

只是顺序读几个页面、不需要同时留着，就别加 `--new`：不带它的 navigate 会
替换当前页，5 个格子一个都不占。

## 关键约束
- browser-usage — 打开新 URL 一律走 browser navigate；`--new` 是唯一的开页方式；不猜页面间跳转 URL；复杂页面用 highlight 定位
- browser-startup — 跨页面流程依赖同一个浏览器实例，别中途换后端

## 常见陷阱
- 不查 `list-tabs --group` → 不知道当前落在哪一页，命令打到别的页上
- 每页都加 `--new` → 5 个格子很快用光，第 6 次直接失败
- 撞上 GROUP_TAB_LIMIT 就换个 group 名绕过去 → 标签栏上堆出第二个组，且两组之间再也切不过去
- 页面加载未完成就操作 → 元素找不到
- 干完不 group-close → 页面挂在人的标签栏上，直到 30 分钟静默才被收走
