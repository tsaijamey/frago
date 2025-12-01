---
description: "执行AI主持的复杂浏览器自动化任务并管理run实例"
---

# /frago.run - Run命令系统

探索调研，为 Recipe 创建做准备。

## 参考文档

| 类型 | 文档 | 说明 |
|------|------|------|
| **规则** | [EXECUTION_PRINCIPLES.md](frago/rules/EXECUTION_PRINCIPLES.md) | 执行原则 |
| **规则** | [NAVIGATION_RULES.md](frago/rules/NAVIGATION_RULES.md) | 禁止幻觉导航 |
| **规则** | [SCREENSHOT_RULES.md](frago/rules/SCREENSHOT_RULES.md) | 截图规范 |
| **规则** | [TOOL_PRIORITY.md](frago/rules/TOOL_PRIORITY.md) | 工具优先级 |
| **规则** | [WORKSPACE_RULES.md](frago/rules/WORKSPACE_RULES.md) | 工作空间管理 |
| **指南** | [LOGGING_GUIDE.md](frago/guides/LOGGING_GUIDE.md) | 日志系统 |
| **示例** | [run_workflow.sh](frago/scripts/run_workflow.sh) | 工作流示例 |
| **示例** | [common_commands.sh](frago/scripts/common_commands.sh) | 通用命令 |

---

## 核心定位

| 项目 | 说明 |
|------|------|
| **目标** | 探索和调研，收集足够信息以创建 Recipe |
| **产出** | `execution.jsonl`（含 `_insights`）+ Recipe 草稿 |
| **区别** | `/frago.exec` 专注于任务完成，本命令专注于探索期 |

---

## 执行流程

### 0. 确保 Chrome 已启动

```bash
# 检查 CDP 连接状态
frago status

# 如未连接，启动 Chrome（选择合适的模式）
frago chrome              # 正常窗口
frago chrome --headless   # 无头模式
frago chrome --void       # 虚空模式（窗口移到屏幕外）
```

### 1. 明确调研目标

```markdown
## 调研目标
- **主题**：[简洁描述，如 "nano-banana-pro image api"]
- **关键问题**：
  1. [问题1]
  2. [问题2]
```

### 2. 发现现有项目

```bash
frago run list --format json
```

### 3. 生成项目 ID

**规则**：简洁、可读的英文短句（3-5 词）

| 用户任务 | 项目 ID |
|---------|---------|
| "调研nano banana pro的图片生成接口" | `nano-banana-pro-image-api-research` |
| "在Upwork上搜索Python职位" | `upwork-python-jobs-search` |

### 4. 初始化并设置上下文

```bash
frago run init "nano-banana-pro image api research"
frago run set-context nano-banana-pro-image-api-research
```

### 5. 执行调研

**CDP 命令自动记录日志**，Agent 负责：
- 手动记录 `_insights`（失败、关键发现）
- 手动记录 `analysis`、`recipe_execution` 等

### 6. 调研完成标志

最后一条日志包含 `ready_for_recipe: true` 和 `recipe_spec`。

### 7. 释放上下文

```bash
frago run release
```

---

## 核心规则（违反即失败）

| 规则 | 说明 | 详细文档 |
|------|------|---------|
| **禁止幻觉导航** | 严禁猜测 URL | [NAVIGATION_RULES.md](frago/rules/NAVIGATION_RULES.md) |
| **⛔ 禁止截图阅读** | 禁止用截图获取页面内容，必须用 `get-content` 或配方 | [SCREENSHOT_RULES.md](frago/rules/SCREENSHOT_RULES.md) |
| **工具优先级** | 先查配方 `recipe list`，再用 `get-content`，最后才用截图 | [TOOL_PRIORITY.md](frago/rules/TOOL_PRIORITY.md) |
| **工作空间隔离** | 所有产出在 `projects/<id>/` | [WORKSPACE_RULES.md](frago/rules/WORKSPACE_RULES.md) |
| **单一运行互斥** | 同时只允许一个活跃上下文 | [WORKSPACE_RULES.md](frago/rules/WORKSPACE_RULES.md) |

---

## _insights 强制记录

**每 5 条日志至少 1 条包含 `_insights`**。

| 触发条件 | insight_type | 要求 |
|---------|--------------|------|
| 操作失败/报错 | `pitfall` | **必须** |
| 重试后成功 | `lesson` | **必须** |
| 找到关键技巧 | `key_factor` | **必须** |

```bash
frago run log \
  --step "分析点击失败原因" \
  --status "warning" \
  --action-type "analysis" \
  --execution-method "analysis" \
  --data '{
    "_insights": [{"type": "pitfall", "summary": "动态class不可靠"}]
  }'
```

---

## 日志系统

详见 [LOGGING_GUIDE.md](frago/guides/LOGGING_GUIDE.md)

**自动日志**：`navigate`、`click`、`screenshot` 等 CDP 命令自动记录

**手动日志**：
- `action-type`：`recipe_execution`、`data_processing`、`analysis`、`user_interaction`、`other`
- `execution-method`：`command`、`recipe`、`file`、`manual`、`analysis`、`tool`

---

## 输出约束

### 允许的输出

| 输出物 | 用途 |
|--------|------|
| `execution.jsonl` | 探索过程记录 |
| `scripts/test_*.{py,js,sh}` | 验证脚本 |
| `screenshots/*.png` | 关键步骤截图 |
| Recipe 草稿（在日志中） | 调研结论 |
| 符合用户期望的结论文档 | 调研成果 |

### 禁止的输出

- ❌ 其他无关的总结文档

---

## 进度展示

**每 5 步输出摘要**：

```markdown
✅ 已完成 5 步：
1. 导航到搜索页（navigation/command）
2. 提取数据（extraction/command）💡 key_factor: 需等待加载
3. 筛选数据（data_processing/file）
4. 分析结构（analysis/analysis）
5. 生成报告（data_processing/file）

📊 Insights: 2个 key_factor, 1个 pitfall
```

