---
description: "执行AI主持的复杂浏览器自动化任务并管理run实例"
---

# /frago.run - Run命令系统

探索调研，为 Recipe 创建做准备。

## 参考文档（执行前必须全量加载）

立即并行执行以下 Read 命令：

```
Read ~/.claude/commands/frago/rules/EXECUTION_PRINCIPLES.md
Read ~/.claude/commands/frago/rules/NAVIGATION_RULES.md
Read ~/.claude/commands/frago/rules/SCREENSHOT_RULES.md
Read ~/.claude/commands/frago/rules/TOOL_PRIORITY.md
Read ~/.claude/commands/frago/rules/WORKSPACE_RULES.md
Read ~/.claude/commands/frago/guides/LOGGING_GUIDE.md
Read ~/.claude/commands/frago/guides/SELECTOR_PRIORITY.md
Read ~/.claude/commands/frago/guides/RECIPE_FIELDS.md
```

---

## 核心定位

- **目标**：探索和调研，收集足够信息以创建 Recipe
- **产出**：Recipe 草稿 + 执行标准（`.metadata.json` 中的注意事项与执行要求）

## 信仰检查（执行前强制）

- 拒绝相信预训练知识中非「自然科学 / 基础底层技术 / 人类共识基础」的信息——必定过时不可靠
- 坚信只有亲自使用浏览器才能获得最新、最真、最可靠的具体信息
- WebSearch 工具失败时，立即转用浏览器访问 google.com 或 bing.com
- 只相信：自然科学 / 基础底层技术 / 人类共识基础 / 亲自收集到的信息

---

## 执行流程

### 0. 环境感知 - 立即获取可用资源

在开始调研前，立刻运行命令了解可用的工具和资源：

```bash
# 1. 查看 frago 命令帮助
frago --help

# 2. 筛选相关配方（支持多关键词）
frago recipe list | grep -E "keyword1|keyword2|keyword3"

# 3. 检查已有项目（避免重复创建）
frago run list | grep -E "keyword1|keyword2"
```

**目的**：
- 发现可复用的配方（避免重新探索）
- 了解已有调研成果（避免重复工作）
- 评估任务可行性

### 1. 明确调研目标

**首先理解任务需求**，判断是否需要浏览器：

| 场景 | 是否需要浏览器 | 工具选择 |
|------|---------------|---------|
| 网页数据抓取、UI 交互 | ✅ 需要 | CDP 命令、配方 |
| API 调用、文件处理 | ❌ 不需要 | CLI 工具、Python 脚本 |
| 混合场景 | ⚠️ 视情况 | 先尝试无浏览器方案 |

**调研目标模板**：
```markdown
## 调研目标
- **主题**：[简洁描述，如 "nano-banana-pro image api"]
- **数据源**：[API / 网页 / 文件 / 混合]
- **关键问题**：
  1. [问题1]
  2. [问题2]
```

### 2. 启动浏览器（仅在需要时）

**如果任务涉及网页操作**，再启动浏览器：

```bash
# 检查 CDP 连接状态
frago status

# 如未连接，启动 Chrome（选择合适的模式）
frago chrome start              # 正常窗口
frago chrome start --headless   # 无头模式
```

**提示**：先用 `frago recipe list | grep <关键词>` 查找现成配方，可能无需手动操作浏览器。

### 3. 检查现有项目（已在步骤 0 完成）

如果步骤 0 中发现相关项目，可以复用或参考：

```bash
# 查看项目详情
frago run info <project_id>

# 查看项目日志
cat projects/<project_id>/logs/execution.jsonl | jq
```

### 4. 生成项目 ID

**规则**：简洁、可读的英文短句（3-5 词）

| 用户任务 | 项目 ID |
|---------|---------|
| "调研nano banana pro的图片生成接口" | `nano-banana-pro-image-api-research` |
| "在Upwork上搜索Python职位" | `upwork-python-jobs-search` |

### 5. 初始化并设置上下文

```bash
frago run init "nano-banana-pro image api research"
frago run set-context nano-banana-pro-image-api-research
```

### 6. 执行调研

**CDP 命令自动记录日志**，Agent 负责：
- 手动记录 `_insights`（失败、关键发现）
- 手动记录 `analysis`、`recipe_execution` 等

### 7. 调研完成标志

最后一条日志包含 `ready_for_recipe: true` 和 `recipe_spec`。

### 8. 释放上下文

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

### 必须的输出

| 输出物 | 位置 | 说明 |
|--------|------|------|
| **调研报告** | `outputs/report.*` | **必须生成**，格式见下方说明 |
| `execution.jsonl` | `logs/` | 探索过程记录（自动生成） |

### 报告格式选择

| 格式 | 文件 | 适用场景 |
|------|------|---------|
| 可预览文档 | `report.md` | 详细阅读、`frago view` 预览 |
| 演示文稿 | `report.html`（reveal.js） | 汇报演示、`frago view` 幻灯片 |
| 结构化数据 | `report.json` | 后续程序处理、数据提取 |

**选择建议**：
- 需要详细阅读 → Markdown 文档
- 需要演示汇报 → reveal.js 演示文稿
- 需要程序处理 → JSON
- 不确定时 → 询问用户

### 可选的输出

| 输出物 | 位置 | 用途 |
|--------|------|------|
| `scripts/test_*.{py,js,sh}` | `scripts/` | 验证脚本 |
| `screenshots/*.png` | `screenshots/` | 关键步骤截图 |
| `outputs/*.json` | `outputs/` | 结构化数据 |
| Recipe 草稿 | 在日志 `_insights` 中 | 调研结论 |

### 禁止的输出

- ❌ 工作空间外的文件
- ❌ 无关的总结文档

### 可预览内容要求（Markdown 或演示文稿输出时适用）

若选择可预览格式，**必须先加载指南**：
```
Read ~/.claude/skills/frago-previewable-content/SKILL.md
```

按 skill 指南生成：
- **Markdown 文档**：参考 Part 1，确保 Mermaid 图表语法、代码块标记正确
- **reveal.js 演示文稿**：参考 Part 2，使用 `<section>` 结构和 fragment 动画

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

