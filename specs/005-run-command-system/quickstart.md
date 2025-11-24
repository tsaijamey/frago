# Quickstart: Run命令系统

**Feature**: 005-run-command-system
**Created**: 2025-11-21
**Audience**: 开发者和高级用户

---

## 概述

Run 命令系统为 Frago 提供持久化的任务执行管理能力，包括：
- **CLI 子命令组**（`uv run frago run`）：管理 run 实例生命周期
- **/frago.run slash 命令**：在 Claude Code 中执行 AI 主持的任务

---

## 5分钟快速开始

### 1. 创建第一个 run 实例

```bash
$ uv run frago run init "测试run系统"
{
  "run_id": "ce-shi-run-xi-tong",
  "created_at": "2025-11-21T10:30:00Z",
  "path": "/home/user/project/runs/ce-shi-run-xi-tong"
}
```

### 2. 设置为当前工作run

```bash
$ uv run frago run set-context ce-shi-run-xi-tong
{
  "run_id": "ce-shi-run-xi-tong",
  "theme_description": "测试run系统",
  "set_at": "2025-11-21T10:31:00Z"
}
```

### 3. 记录第一条日志

```bash
$ uv run frago run log \
  --step "测试日志记录" \
  --status "success" \
  --action-type "analysis" \
  --execution-method "manual" \
  --data '{"note": "系统正常工作"}'

{
  "logged_at": "2025-11-21T10:32:00Z",
  "run_id": "ce-shi-run-xi-tong",
  "log_file": "runs/ce-shi-run-xi-tong/logs/execution.jsonl"
}
```

### 4. 查看run详情

```bash
$ uv run frago run info ce-shi-run-xi-tong

Run ID: ce-shi-run-xi-tong
Status: active
Theme: 测试run系统
Created: 2025-11-21 10:30:00
Last Accessed: 2025-11-21 10:32:00

Statistics:
- Log Entries: 1
- Screenshots: 0
- Scripts: 0
- Disk Usage: 0.2 KB

Recent Logs (last 5):
  [2025-11-21 10:32] ✓ 测试日志记录 (analysis/manual)
```

---

## 完整工作流示例

### 场景：在 Upwork 上搜索 Python 职位

#### 步骤 1：初始化 run

```bash
$ uv run frago run init "在Upwork上搜索Python职位"
{
  "run_id": "zai-upwork-shang-sou-suo-python-zhi-wei",
  "created_at": "2025-11-21T10:00:00Z",
  "path": "..."
}

$ uv run frago run set-context zai-upwork-shang-sou-suo-python-zhi-wei
```

#### 步骤 2：执行任务并记录日志

```bash
# 导航到搜索页
$ uv run frago navigate https://upwork.com/search
$ uv run frago run log \
  --step "导航到Upwork搜索页" \
  --status "success" \
  --action-type "navigation" \
  --execution-method "command" \
  --data '{"command": "uv run frago navigate https://upwork.com/search", "exit_code": 0}'

# 截图
$ uv run frago run screenshot "搜索页面"
{
  "file_path": "runs/.../screenshots/001_search-page.png",
  "sequence_number": 1
}

# 提取职位（使用Recipe）
$ uv run frago recipe run upwork_extract_job_list --params '{"keyword": "Python"}'
$ uv run frago run log \
  --step "提取Python职位列表" \
  --status "success" \
  --action-type "recipe_execution" \
  --execution-method "recipe" \
  --data '{"recipe_name": "upwork_extract_job_list", "params": {"keyword": "Python"}, "output": {"jobs": [...], "total": 15}}'

# 数据处理（使用脚本）
$ cat > runs/.../scripts/filter_jobs.py <<EOF
import json
jobs = json.load(open('outputs/raw_jobs.json'))
filtered = [j for j in jobs if j['rate'] > 50]
json.dump(filtered, open('outputs/filtered_jobs.json', 'w'))
print(f"筛选出 {len(filtered)} 个高薪职位")
EOF

$ uv run python runs/.../scripts/filter_jobs.py
$ uv run frago run log \
  --step "筛选薪资>$50的职位" \
  --status "success" \
  --action-type "data_processing" \
  --execution-method "file" \
  --data '{"file": "scripts/filter_jobs.py", "language": "python", "output": "筛选出 8 个高薪职位", "result_file": "outputs/filtered_jobs.json"}'
```

#### 步骤 3：查看执行历史

```bash
$ uv run frago run info zai-upwork-shang-sou-suo-python-zhi-wei

Run ID: zai-upwork-shang-sou-suo-python-zhi-wei
Status: active
Theme: 在Upwork上搜索Python职位
Created: 2025-11-21 10:00:00
Last Accessed: 2025-11-21 10:15:00

Statistics:
- Log Entries: 4
- Screenshots: 1
- Scripts: 1
- Disk Usage: 12.5 KB

Recent Logs (last 5):
  [10:15] ✓ 筛选薪资>$50的职位 (data_processing/file)
  [10:12] ✓ 提取Python职位列表 (recipe_execution/recipe)
  [10:08] ✓ 搜索页面 (screenshot/command)
  [10:05] ✓ 导航到Upwork搜索页 (navigation/command)
```

#### 步骤 4：继续任务（第二天）

```bash
# 列出现有 run
$ uv run frago run list --format table
RUN_ID                                  STATUS   CREATED_AT           LAST_ACCESSED
zai-upwork-shang-sou-suo-python-zhi-wei  active   2025-11-21 10:00     2025-11-21 10:15

# 恢复上下文
$ uv run frago run set-context zai-upwork-shang-sou-suo-python-zhi-wei

# 继续工作...
$ uv run frago run log \
  --step "应用第一个职位" \
  --status "success" \
  --action-type "interaction" \
  --execution-method "manual" \
  --data '{"job_title": "Python Backend Developer", "action": "submitted application"}'
```

---

## 在 Claude Code 中使用 /frago.run

### 场景 1：创建新 run

```
Human: /frago.run 在Upwork上搜索Python职位

Claude: 我发现 runs/ 目录中已有以下 run 实例：
1. zai-upwork-shang-sou-suo-python-zhi-wei (最后访问: 2025-11-21 10:15)
   主题: 在Upwork上搜索Python职位

是否继续现有 run？
[ ] 继续现有 run
[x] 创建新 run

好的，我创建了一个新 run 实例...
(AI 执行任务，自动调用 CDP 命令和 Recipe，记录所有操作到日志)

任务完成！执行摘要：
- 导航到 Upwork 搜索页
- 提取到 15 个 Python 职位
- 筛选出 8 个薪资 >$50 的职位
- 生成结果文件: outputs/filtered_jobs.json

详细日志: runs/.../logs/execution.jsonl
```

### 场景 2：继续现有 run

```
Human: /frago.run 继续分析这些职位的技能要求

Claude: 检测到当前 run: zai-upwork-shang-sou-suo-python-zhi-wei

我将继续在这个 run 实例中工作。让我先查看之前积累的信息...

(AI 读取 execution.jsonl，恢复上下文)

我看到之前已经提取了 8 个高薪职位。现在我将分析它们的技能要求...
(AI 继续执行，新的操作追加到同一个日志文件)

分析完成！技能统计：
- Python: 8/8 (100%)
- Django/Flask: 6/8 (75%)
- PostgreSQL: 5/8 (62.5%)
- ...

详细日志: runs/.../logs/execution.jsonl (新增 3 条记录)
```

---

## 常见任务

### 列出所有 run 实例（JSON格式）

```bash
$ uv run frago run list --format json | jq '.runs[].run_id'
"zai-upwork-shang-sou-suo-python-zhi-wei"
"fen-xi-github-langchain-xiang-mu"
```

### 归档已完成的 run

```bash
$ uv run frago run archive zai-upwork-shang-sou-suo-python-zhi-wei
{
  "run_id": "zai-upwork-shang-sou-suo-python-zhi-wei",
  "archived_at": "2025-11-21T15:00:00Z",
  "previous_status": "active"
}

# 归档后不会显示在默认列表中
$ uv run frago run list --status active
(无结果)

# 查看归档的 run
$ uv run frago run list --status archived
RUN_ID                                  STATUS    CREATED_AT           LAST_ACCESSED
zai-upwork-shang-sou-suo-python-zhi-wei  archived  2025-11-21 10:00     2025-11-21 15:00
```

### 分析日志文件（使用 jq）

```bash
# 查看所有成功的操作
$ cat runs/zai-upwork-shang-sou-suo-python-zhi-wei/logs/execution.jsonl \
  | jq 'select(.status == "success") | .step'

# 统计 action_type 分布
$ cat runs/.../logs/execution.jsonl \
  | jq -r '.action_type' | sort | uniq -c
  1 navigation
  1 recipe_execution
  1 data_processing
  1 screenshot

# 提取所有错误
$ cat runs/.../logs/execution.jsonl \
  | jq 'select(.status == "error")'
```

### 手动导出数据

```bash
# 从日志中提取所有职位数据
$ cat runs/.../logs/execution.jsonl \
  | jq 'select(.action_type == "extraction") | .data.output.jobs' \
  > runs/.../outputs/all_jobs.json

# 转换为 CSV
$ jq -r '.[] | [.title, .rate, .description] | @csv' \
  runs/.../outputs/all_jobs.json \
  > runs/.../outputs/jobs.csv
```

---

## 环境变量

### FRAGO_CURRENT_RUN

临时覆盖当前 run 上下文（优先级高于配置文件）：

```bash
$ export FRAGO_CURRENT_RUN=ce-shi-run-xi-tong
$ uv run frago run log --step "测试" --status "success" ...
# 日志会记录到 ce-shi-run-xi-tong 而不是配置文件中的 run
```

---

## 故障排查

### 错误：Current run context not set

```bash
$ uv run frago run log ...
Error: Current run context not set. Run 'uv run frago run set-context <run_id>' first.
```

**解决方法**：
```bash
$ uv run frago run set-context <run_id>
```

### 错误：Run 'xxx' not found

```bash
$ uv run frago run set-context invalid-id
Error: Run 'invalid-id' not found
```

**解决方法**：
```bash
# 查看可用的 run
$ uv run frago run list

# 使用正确的 run_id
$ uv run frago run set-context <正确的run_id>
```

### 日志文件损坏

```bash
$ uv run frago run info my-run
Warning: Found 2 corrupted log entries, skipped
```

**处理方式**：
- 系统会自动跳过损坏的行
- 建议检查 `logs/execution.jsonl` 文件，手动修复或删除损坏行

---

## 下一步

- **查看完整契约**：[contracts/cli-commands.md](./contracts/cli-commands.md)
- **理解数据模型**：[data-model.md](./data-model.md)
- **阅读研究文档**：[research.md](./research.md)
- **执行实施任务**：运行 `/speckit.tasks` 生成任务列表
