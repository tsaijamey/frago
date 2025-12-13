---
description: "执行一次性的复杂任务（使用完整的frago工具集）"
---

# /frago.do - 执行复杂任务

一次性任务执行，专注于任务完成。

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

- **目标**：完成用户指定的具体任务
- **产出**：任务成果 + 执行标准（`.metadata.json` 中的注意事项与执行要求）

## 信仰检查（执行前强制）

- 拒绝相信预训练知识中非「自然科学 / 基础底层技术 / 人类共识基础」的信息——必定过时不可靠
- 坚信只有亲自使用浏览器才能获得最新、最真、最可靠的具体信息
- WebSearch 工具失败时，立即转用浏览器访问 google.com 或 bing.com
- 只相信：自然科学 / 基础底层技术 / 人类共识基础 / 亲自收集到的信息

---

## 执行流程

### 0. 环境感知 - 立即获取可用资源

在开始任务前，先了解可用的工具和资源：

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
- 了解已有成果（避免重复工作）
- 评估任务可行性

### 1. 明确任务目标和输出格式

**首先理解任务需求**，判断是否需要浏览器：

| 场景 | 是否需要浏览器 | 工具选择 |
|------|---------------|---------|
| 网页数据抓取、UI 交互 | ✅ 需要 | CDP 命令、配方 |
| API 调用、文件处理 | ❌ 不需要 | CLI 工具、Python 脚本 |
| 混合场景 | ⚠️ 视情况 | 先尝试无浏览器方案 |

**如果需要浏览器**：

```bash
# 检查 CDP 连接状态
frago status

# 如未连接，启动 Chrome（选择合适的模式）
frago chrome start              # 正常窗口
frago chrome start --headless   # 无头模式
```

**提示**：先用 `frago recipe list | grep <关键词>` 查找现成配方，可能无需手动操作浏览器。

**必须先确认输出格式**。如用户未指定，使用 AskUserQuestion 询问：

| 输出格式 | 适用场景 |
|---------|---------|
| 📊 结构化数据（JSON/CSV） | 后续处理和分析 |
| 📝 文档报告（Markdown/HTML） | 阅读和分享 |
| 💾 仅执行日志 | 最小化输出 |

### 2. 生成项目 ID

**规则**：简洁、可读的英文短句（3-5 词）

| 用户任务 | 项目 ID |
|---------|---------|
| "在Upwork上申请5个Python职位" | `upwork-python-job-apply` |
| "批量下载YouTube视频字幕" | `youtube-batch-download-subtitles` |

### 3. 初始化工作空间

```bash
frago run init "upwork python job apply"
frago run set-context upwork-python-job-apply
```

### 4. 执行任务

**优先使用 Recipe**，加速重复操作：

```bash
# 发现现有 Recipe
frago recipe list --format json | grep "关键词"

# 执行 Recipe
frago recipe run <name> --params '{"key": "value"}' --output-file result.json
```

### 5. 保存结果

```bash
# 截图关键步骤
frago run screenshot "任务完成页面"

# 记录完成状态
frago run log \
  --step "任务完成：[简要描述]" \
  --status "success" \
  --action-type "analysis" \
  --execution-method "analysis" \
  --data '{"task_completed": true, "result_file": "outputs/result.json"}'
```

### 6. 释放上下文

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

## 日志系统

详见 [LOGGING_GUIDE.md](frago/guides/LOGGING_GUIDE.md)

**自动日志**：`navigate`、`click`、`screenshot` 等 CDP 命令自动记录

**手动日志**：
- `action-type`：`recipe_execution`、`data_processing`、`analysis`、`user_interaction`、`other`
- `execution-method`：`command`、`recipe`、`file`、`manual`、`analysis`、`tool`

---

## 输出约束

### 根据用户选择创建输出

| 格式 | 文件类型 | 说明 |
|------|---------|------|
| 结构化数据 | `*.json`、`*.csv` | Agent 可直接生成 |
| 文档报告 | `*.md`、`*.html` | Agent 可直接生成 |
| 多媒体 | `*.png`（截图） | 通过工具生成 |

### 禁止的行为

- ❌ 违背用户选择的输出格式
- ❌ 创建未经确认的文档
- ❌ 产出物放在工作空间外

---

## 任务完成标准

### ✅ 完成条件

1. 用户目标达成（可验证）
2. 结果已保存到 `outputs/`
3. 最后日志标记 `task_completed: true`

### 🛑 停止条件

- 用户目标达成
- 任务执行失败（原因已记录）
- 用户明确指示停止

---

## 进度展示

**每 5 步输出摘要**：

```markdown
✅ 已完成 5 步：
1. 导航到搜索页（navigation/command）
2. 搜索职位（interaction/command）
3. 提取职位列表（extraction/command）
4. 筛选合适职位（data_processing/analysis）
5. 申请第1个职位（user_interaction/recipe）

📊 当前进度：已申请 1/5 个职位
📁 输出文件：outputs/applied_jobs.json
```

---

## 任务完成摘要

```markdown
✅ 任务完成！

**Project**: upwork-python-job-apply
**执行时间**: 30分钟

**完成情况**：
- 成功申请 5 个 Python 职位

**输出文件**：
- outputs/applied_jobs.json
- screenshots/*.png

**详细日志**: projects/upwork-python-job-apply/logs/execution.jsonl
```

