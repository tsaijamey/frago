# scene-web-research

场景类型: 信息调研

## 问题特征
需要从互联网获取信息，整理成结构化产出（报告、数据集、决策依据）。

## 典型触发
- 用户要求搜索某个主题
- 需要查找文档、API 参考
- 竞品调研、市场分析
- 验证某个说法或数据

## 推荐路径

  1. frago run find <调研关键词>                # 搜索历史类似任务
  2. frago run init "调研主题描述"
  3. frago recipe list | grep research        # 检查已有调研 recipe
  4. frago chrome navigate "https://google.com/search?q=关键词"
  5. frago chrome get-content --selector "#search"
  6. 逐层深入链接（禁止猜测 URL）
  7. frago run log --step "发现" --data '{"_insights": [...]}'
  8. 整理产出到 workspace/outputs/

## 关键约束
- must-browser-search — 搜索必须走 frago chrome navigate google
- must-content-extraction — 读内容用 get-content，不要截图读字
- must-navigation — 不要猜 URL，从搜索结果逐层探索
- must-workspace — 所有产出放 workspace 内
- run-logging — 每 5 条日志至少 1 条含 _insights

## 常见陷阱
- 用预训练知识编造 URL → 404
- 截图代替 get-content → 丢失结构信息
- 产出散落在 /tmp → 任务结束后丢失
- 不记 _insights → 下次无法生成 Recipe
