# scene-data-extraction

场景类型: 数据提取

## 问题特征
从网页批量提取结构化数据——列表、表格、评论、价格等，整理成可用的数据集。

## 典型触发
- 提取搜索结果列表
- 收集商品/职位/文章信息
- 抓取评论或用户反馈
- 导出表格数据

## 推荐路径

  1. frago run find <提取关键词>                # 搜索历史类似任务
  2. frago recipe list | grep extract         # 检查已有提取 recipe
  2. frago chrome navigate <目标页面>
  3. frago chrome get-content                  # 初步了解页面结构
  4. frago chrome exec-js "探索 DOM 结构" --return-value
  5. 确定选择器（按 selector-priority 排序）
  6. frago chrome highlight "选择器"           # 高亮验证
  7. frago chrome exec-js "批量提取" --return-value
  8. 如需翻页：frago chrome scroll / click 下一页
  9. 结果存入 workspace/outputs/

## 关键约束
- must-content-extraction — 用 get-content + exec-js 提取，不截图读字
- selector-priority — 选稳定选择器，写 fallback
- chrome-scroll — 懒加载页面需要滚动触发内容加载
- better-structured-data — 提取结果用 frago def 存档（开发中）

## 常见陷阱
- 页面懒加载 → 只拿到首屏数据，需要 scroll + 等待
- 动态渲染 → get-content 时内容尚未加载，需要 wait
- 分页逻辑 → 不同网站分页机制不同（URL 参数 / 点击 / 无限滚动）
- 反爬 → 操作频率过高触发验证码，需要适当间隔
