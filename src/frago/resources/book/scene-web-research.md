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

  1. frago context data:<调研关键词>            # 找历史落盘产出
  2. frago session search "<一句话说清要找什么>"  # 按意思翻历史会话
  3. frago recipe list | grep research        # 检查已有调研 recipe
  4. frago browser navigate "https://google.com/search?q=关键词" --group <name>
  5. frago browser get-content --group <name> "#search"
  6. 逐层深入链接（禁止猜测 URL）
  7. 整理产出到 ~/.frago/data/<主体>/<YYYYMMDD>-<slug>/

## 关键约束
- must-browser-search — 搜索必须走 frago browser navigate google
- browser-usage — 读内容用 get-content 不截图读字；不猜 URL，从搜索结果逐层探索
- must-data-dir — 所有产出放 ~/.frago/data/<主体>/<YYYYMMDD>-<slug>/ 内

## 常见陷阱
- 用预训练知识编造 URL → 404
- 截图代替 get-content → 丢失结构信息
- 产出散落在 /tmp → 任务结束后丢失
- 调研结论不沉淀成 def 文档 → 下次同一主题从零开始
