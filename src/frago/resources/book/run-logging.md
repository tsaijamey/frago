# run-logging

分类: 效率（AVAILABLE）

## 解决什么问题
agent 不清楚哪些日志自动记录、哪些需手动补充，不写 _insights 导致后续 Recipe 生成缺乏关键经验。

## 自动日志 vs 手动日志

### 自动记录（CDP 命令执行后自动写入）

| 命令 | action_type | 自动记录内容 |
|------|-------------|-------------|
| navigate | navigation | URL、加载状态、DOM 特征 |
| click | interaction | selector、DOM 变化 |
| scroll | interaction | 滚动距离 |
| exec-js | interaction | 执行结果 |
| screenshot | screenshot | 文件路径 |
| get-title | extraction | 页面标题 |
| get-content | extraction | selector、内容 |
| highlight/pointer/spotlight/annotate | interaction | 视觉效果参数 |

自动日志只记录客观执行结果，不含 _insights。

### 需要手动记录的场景

1. 添加 _insights（失败反思、关键发现）
2. AI 分析（action_type: analysis）
3. 用户交互（action_type: user_interaction）
4. Recipe 执行（action_type: recipe_execution）
5. 数据处理（action_type: data_processing）
6. 脚本文件执行（execution_method: file）

## 手动日志命令格式

  frago run log \
    --step "步骤描述" \
    --status "success|error|warning" \
    --action-type "<见下方>" \
    --execution-method "<见下方>" \
    --data '{"key": "value"}'

### action-type 值

CDP 自动：navigation, extraction, interaction, screenshot
手动专用：recipe_execution, data_processing, analysis, user_interaction, other

### execution-method 值（6 种）

1. command — CLI 命令执行
2. recipe — Recipe 调用
3. file — 脚本文件执行（data 必须含 file 字段）
4. manual — 人工操作
5. analysis — AI 推理
6. tool — AI 工具调用

## _insights 强制记录

每 5 条日志至少 1 条含 _insights。这是 Recipe 生成的核心信息源。

| 触发条件 | insight_type | 是否必须 |
|---------|-------------|---------|
| 操作失败/报错 | pitfall | 必须 |
| 重试后成功 | lesson | 必须 |
| 发现意外行为 | pitfall/workaround | 必须 |
| 找到关键技巧 | key_factor | 必须 |
| 首次成功 | - | 可选 |

示例：

  frago run log \
    --step "分析点击失败原因" \
    --status "warning" \
    --action-type "analysis" \
    --execution-method "analysis" \
    --data '{
      "command": "frago chrome click .job-card",
      "error": "Element not found",
      "_insights": [
        {"type": "pitfall", "summary": "动态 class 不可靠，需要 data-testid"}
      ]
    }'

## 脚本文件处理

- 简单命令：直接用 frago <command>，记为 execution_method: command
- 复杂脚本（>30 行）：保存为 scripts/<name>.{py,js,sh}，记为 execution_method: file

file 类型的 data 必须包含 file 字段，代码不要内联到日志。

## 研究完成标准

1. 关键问题都有答案
2. 涉及 API/工具的有测试脚本验证
3. 最后一条日志包含 Recipe draft（ready_for_recipe: true）

## 进度展示

每 5 步输出进度摘要：

  ✅ 完成 5 步:
  1. 导航到搜索页面 (navigation/command)
  2. 提取 15 条记录 (extraction/command) 💡 key_factor: 需等待加载
  3. 过滤高价值记录 (data_processing/file)
  4. 分析需求匹配 (analysis/analysis)
  5. 生成报告 (data_processing/file)

  📊 当前统计: 15 logs, 3 screenshots, 2 scripts | Insights: 2 key_factors, 1 pitfall
