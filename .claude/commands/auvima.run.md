---
description: "执行AI主持的复杂浏览器自动化任务并管理run实例"
---

# /auvima.run - Run命令系统

## 你的任务

作为任务执行者,你需要使用**Run命令系统**管理AI主持的复杂浏览器自动化任务。Run实例是**主题型的信息中心**,用于持久化存储任务执行历史和积累的知识。

## 核心概念

### Run实例的作用

- **探索和调研**: Recipe创建前的信息收集
- **跨Recipe上下文**: 多个Recipe调用的信息积累
- **Workflow构建**: 复杂流程的信息组织
- **一次性任务**: 复杂但不需要创建Recipe的任务

### 结构化日志格式

所有操作必须记录到 `execution.jsonl`,包含以下关键字段:

- `action_type`: 操作类型 (navigation/extraction/interaction/screenshot/recipe_execution/data_processing/analysis/user_interaction/other)
- `execution_method`: 执行方法 (command/recipe/file/manual/analysis/tool)
- `data`: 操作详情 (JSON对象)

## 执行流程

### 1. 发现现有run实例

首先检查是否存在相关的run实例:

```bash
uv run auvima run list --format json
```

分析JSON输出,提取run列表并计算与用户任务的相似度。

### 2. 交互式选择 (使用 AskUserQuestion)

如果发现相关run (相似度>60%),使用 **AskUserQuestion** 工具展示选项:

```markdown
问题: "发现现有run实例,选择继续哪个?"
选项:
- ⭐ find-job-on-upwork (相似度: 85%) - 主题: 在Upwork上搜索Python职位
- create-new-run - 为当前任务创建新的run实例
```

### 3. 固化工作环境

选择或创建run后,立即设置上下文:

```bash
# 继续现有run
uv run auvima run set-context <run_id>

# 或创建新run
uv run auvima run init "用户任务描述"
uv run auvima run set-context <返回的run_id>
```

**关键**: 上下文设置后,后续所有 `log` 和 `screenshot` 命令将自动关联到该run。

### 4. 执行任务并记录日志

每个关键步骤后,使用 `log` 命令记录:

```bash
uv run auvima run log \
  --step "步骤描述" \
  --status "success|error|warning" \
  --action-type "<9种类型之一>" \
  --execution-method "<6种方法之一>" \
  --data '{"key": "value"}'
```

**重要约束**:

- **禁止直接存储代码到日志**: 如果生成脚本文件(>100行),必须保存为 `scripts/*.{py,js,sh}`,然后在日志中记录文件路径
- **execution_method=file时,data必须包含file字段**: 记录脚本相对路径

### 5. 进度展示

**每5步输出一次进度摘要**,格式:

```markdown
✅ 已完成 5 步:
1. 导航到Upwork搜索页 (navigation/command)
2. 提取15个Python职位 (extraction/command)
3. 过滤薪资>$50的职位 (data_processing/file)
4. 分析技能要求 (analysis/analysis)
5. 生成报告 (data_processing/file)

📊 当前统计: 15条日志, 3个截图, 2个脚本文件
```

### 6. Recipe集成指引

**如何发现现有Recipe**:

```bash
uv run auvima recipe list --format json
```

**调用Recipe并记录**:

```bash
# 执行Recipe
uv run auvima recipe run <recipe_name> --params '{"url": "..."}' --output-file result.json

# 记录日志
uv run auvima run log \
  --step "执行Recipe: <recipe_name>" \
  --status "success" \
  --action-type "recipe_execution" \
  --execution-method "recipe" \
  --data '{"recipe_name": "<recipe_name>", "params": {...}, "output_file": "result.json"}'
```

### 7. 代码文件处理约束

**当需要执行代码时**:

1. **简单命令**: 直接使用 `uv run auvima <command>`,记录为 `execution_method: command`
2. **复杂脚本** (>30行): 保存为 `scripts/<name>.{py,js,sh}`,记录为 `execution_method: file`

示例:

```python
# 错误做法 (禁止)
data = {
    "code": "import json\nwith open(...) as f:\n..."  # ✗ 不要存储长代码
}

# 正确做法
# 1. 保存脚本
with open('runs/<run_id>/scripts/filter_jobs.py', 'w') as f:
    f.write(script_content)

# 2. 执行脚本
uv run python runs/<run_id>/scripts/filter_jobs.py

# 3. 记录日志
data = {
    "file": "scripts/filter_jobs.py",  # ✓ 记录文件路径
    "language": "python",
    "command": "uv run python scripts/filter_jobs.py",
    "exit_code": 0,
    "output": "处理了15条数据",
    "result_file": "outputs/filtered_jobs.json"
}
```

### 8. 用户交互处理

当需要用户输入或确认时:

```bash
# 使用 AskUserQuestion 工具获取用户输入
# 记录交互日志
uv run auvima run log \
  --step "询问用户选择职位" \
  --status "success" \
  --action-type "user_interaction" \
  --execution-method "tool" \
  --data '{"tool": "AskUserQuestion", "question": "...", "answer": "..."}'
```

## 6种 execution_method 完整示例

### 1. command - CLI命令执行

```bash
# 执行命令
uv run auvima navigate https://upwork.com/search

# 记录日志
uv run auvima run log \
  --step "导航到Upwork搜索页" \
  --status "success" \
  --action-type "navigation" \
  --execution-method "command" \
  --data '{"command": "uv run auvima navigate https://upwork.com/search", "exit_code": 0}'
```

### 2. recipe - Recipe调用

```bash
# 执行Recipe
uv run auvima recipe run upwork_extract_job_list --params '{"keyword": "Python"}'

# 记录日志
uv run auvima run log \
  --step "提取Python职位列表" \
  --status "success" \
  --action-type "recipe_execution" \
  --execution-method "recipe" \
  --data '{"recipe_name": "upwork_extract_job_list", "params": {"keyword": "Python"}, "output": {"jobs": [...], "total": 15}}'
```

### 3. file - 执行脚本文件

```bash
# 保存脚本
cat > runs/<run_id>/scripts/filter_jobs.py <<EOF
import json
jobs = json.load(open('outputs/raw_jobs.json'))
filtered = [j for j in jobs if j['rate'] > 50]
json.dump(filtered, open('outputs/filtered_jobs.json', 'w'))
print(f"筛选出 {len(filtered)} 个高薪职位")
EOF

# 执行脚本
cd runs/<run_id> && uv run python scripts/filter_jobs.py

# 记录日志
uv run auvima run log \
  --step "筛选薪资>$50的职位" \
  --status "success" \
  --action-type "data_processing" \
  --execution-method "file" \
  --data '{"file": "scripts/filter_jobs.py", "language": "python", "command": "uv run python scripts/filter_jobs.py", "exit_code": 0, "output": "筛选出 8 个高薪职位", "result_file": "outputs/filtered_jobs.json"}'
```

### 4. manual - 人工操作

```bash
# 提示用户手动操作,并等待确认
# 记录日志
uv run auvima run log \
  --step "等待用户登录Upwork" \
  --status "success" \
  --action-type "user_interaction" \
  --execution-method "manual" \
  --data '{"instruction": "请手动登录Upwork账号", "completed": true}'
```

### 5. analysis - AI推理/思考

```bash
# AI分析DOM结构,推断选择器
# 记录日志
uv run auvima run log \
  --step "分析页面DOM结构" \
  --status "success" \
  --action-type "analysis" \
  --execution-method "analysis" \
  --data '{"conclusion": "职位列表使用CSS选择器 .job-card", "confidence": "high", "reasoning": "观察到所有职位元素都包含 job-card 类名"}'
```

### 6. tool - AI工具调用

```bash
# 使用 AskUserQuestion 工具
# 记录日志
uv run auvima run log \
  --step "询问用户选择目标职位" \
  --status "success" \
  --action-type "user_interaction" \
  --execution-method "tool" \
  --data '{"tool": "AskUserQuestion", "question": "发现8个高薪职位,选择哪个?", "options": ["职位A", "职位B"], "answer": "职位A"}'
```

## 最佳实践

### ✅ 推荐做法

1. **任务开始前检查现有run**: 避免重复创建相似主题的run
2. **每5步输出摘要**: 让用户了解进度
3. **脚本文件化**: 超过30行的代码保存为文件,不直接存储到日志
4. **结构化data**: 使用清晰的JSON结构,便于后续分析
5. **截图关键步骤**: 使用 `uv run auvima run screenshot "描述"` 保存重要界面

### ❌ 禁止做法

1. **跳过上下文设置**: 必须先 `set-context` 再执行 `log`/`screenshot`
2. **日志中存储长代码**: 超过100行的代码必须保存为文件
3. **遗漏execution_method**: 每条日志必须明确执行方法
4. **模糊的step描述**: 步骤描述要具体 ("提取了15个职位" 而非 "提取数据")

## 任务完成后

生成执行摘要:

```markdown
✅ 任务完成!

**Run实例**: find-job-on-upwork
**执行时间**: 2025-11-21 10:00 - 10:45 (45分钟)

**完成步骤**:
1. 导航到Upwork搜索页
2. 提取15个Python职位
3. 筛选出8个薪资>$50的职位
4. 分析技能要求分布
5. 生成分析报告

**生成文件**:
- outputs/raw_jobs.json (15个职位)
- outputs/filtered_jobs.json (8个高薪职位)
- outputs/skills_analysis.json (技能统计)

**详细日志**: runs/find-job-on-upwork/logs/execution.jsonl (共20条记录)

**下次继续**: `uv run auvima run set-context find-job-on-upwork`
```

## 注意事项

- **上下文优先级**: 环境变量 `AUVIMA_CURRENT_RUN` > 配置文件 `.auvima/current_run`
- **日志格式版本**: 当前为 `schema_version: "1.0"`
- **并发安全**: 同一时间只在一个run实例中工作,避免上下文混乱
