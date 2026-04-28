# run-logging

分类: 效率（AVAILABLE）

## 解决什么问题
agent 不清楚哪些日志自动记录、哪些需手动补充，导致 execution.jsonl 缺关键步骤、Recipe 生成时无据可凭。

本章讲操作日志（execution.jsonl）。领域级知识沉淀（事实/决策/伏笔/状态/教训）走 `{{frago_launcher}} run insights`，详见 `{{frago_launcher}} book domain-insights`。

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

自动日志只记录客观执行结果。

### 需要手动记录的场景

1. AI 分析（action_type: analysis）
2. 用户交互（action_type: user_interaction）
3. Recipe 执行（action_type: recipe_execution）
4. 数据处理（action_type: data_processing）
5. 脚本文件执行（execution_method: file）

## 手动日志命令格式

  {{frago_launcher}} run log \
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

## 脚本文件处理

- 简单命令：直接用 {{frago_launcher}} <command>，记为 execution_method: command
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
  2. 提取 15 条记录 (extraction/command)
  3. 过滤高价值记录 (data_processing/file)
  4. 分析需求匹配 (analysis/analysis)
  5. 生成报告 (data_processing/file)

  📊 当前统计: 15 logs, 3 screenshots, 2 scripts
