# 日志系统指南

适用于：`/frago.run`、`/frago.do`

## 一、自动日志与手动日志

### 自动日志（CDP 命令执行后自动记录）

以下 CDP 命令在有活跃 run context 时会**自动写入日志**：

| 命令 | action_type | 自动记录内容 |
|------|-------------|-------------|
| `navigate` | navigation | URL、加载状态、DOM 特征 |
| `click` | interaction | 选择器、DOM 特征变化 |
| `scroll` | interaction | 滚动距离 |
| `exec-js` | interaction | 执行结果 |
| `zoom` | interaction | 缩放比例 |
| `screenshot` | screenshot | 文件路径 |
| `get-title` | extraction | 页面标题 |
| `get-content` | extraction | 选择器、内容 |
| `highlight/pointer/spotlight/annotate` | interaction | 视觉效果参数 |

**重要**：自动日志只记录**客观执行结果**，不包含 `_insights`。

### 手动日志（需要 Agent 判断时使用）

以下情况**必须手动**调用 `frago run log`：

1. **添加 `_insights`**（失败反思、关键发现）
2. **记录 AI 分析**（`action_type: analysis`）
3. **记录用户交互**（`action_type: user_interaction`）
4. **记录 Recipe 执行**（`action_type: recipe_execution`）
5. **记录数据处理**（`action_type: data_processing`）
6. **记录文件脚本执行**（`execution_method: file`）

---

## 二、日志命令格式

```bash
frago run log \
  --step "步骤描述" \
  --status "success|error|warning" \
  --action-type "<见下方值>" \
  --execution-method "<见下方值>" \
  --data '{"key": "value"}'
```

### action-type 有效值

**CDP 命令自动记录**：
- `navigation` - 页面导航
- `extraction` - 数据提取
- `interaction` - 页面交互
- `screenshot` - 截图

**手动日志专用**：
1. `recipe_execution` - 执行 Recipe
2. `data_processing` - 数据处理（筛选、转换、保存文件）
3. `analysis` - AI 分析和推理
4. `user_interaction` - 用户交互（询问、确认）
5. `other` - 其他操作

### execution-method 有效值（6种）

1. `command` - CLI 命令执行（如 `frago chrome navigate`）
2. `recipe` - Recipe 调用
3. `file` - 执行脚本文件（.py/.js/.sh）
4. `manual` - 人工手动操作
5. `analysis` - AI 推理和思考
6. `tool` - AI 工具调用（如 AskUserQuestion）

---

## 三、6种 execution_method 完整示例

### 1. command - CLI 命令执行

```bash
# 执行命令
frago chrome navigate https://upwork.com/search

# 记录日志
frago run log \
  --step "导航到Upwork搜索页" \
  --status "success" \
  --action-type "navigation" \
  --execution-method "command" \
  --data '{"command": "frago chrome navigate https://upwork.com/search", "exit_code": 0}'
```

### 2. recipe - Recipe 调用

```bash
# 执行 Recipe
frago recipe run upwork_extract_job_list --params '{"keyword": "Python"}'

# 记录日志
frago run log \
  --step "提取Python职位列表" \
  --status "success" \
  --action-type "recipe_execution" \
  --execution-method "recipe" \
  --data '{"recipe_name": "upwork_extract_job_list", "params": {"keyword": "Python"}, "output": {"jobs": [], "total": 15}}'
```

### 3. file - 执行脚本文件

```bash
# 保存脚本
cat > projects/<project_id>/scripts/filter_jobs.py <<EOF
import json
jobs = json.load(open('outputs/raw_jobs.json'))
filtered = [j for j in jobs if j['rate'] > 50]
json.dump(filtered, open('outputs/filtered_jobs.json', 'w'))
print(f"筛选出 {len(filtered)} 个高薪职位")
EOF

# 执行脚本（注意：在项目根目录执行，使用完整相对路径）
uv run python projects/<project_id>/scripts/filter_jobs.py

# 记录日志
frago run log \
  --step "筛选薪资>$50的职位" \
  --status "success" \
  --action-type "data_processing" \
  --execution-method "file" \
  --data '{
    "file": "scripts/filter_jobs.py",
    "language": "python",
    "command": "uv run python projects/<project_id>/scripts/filter_jobs.py",
    "exit_code": 0,
    "output": "筛选出 8 个高薪职位",
    "result_file": "outputs/filtered_jobs.json"
  }'
```

**重要约束**：
- `execution_method=file` 时，`data` **必须包含 `file` 字段**
- 超过 30 行的代码必须保存为文件，不直接存储到日志

### 4. manual - 人工操作

```bash
# 提示用户手动操作，并等待确认
# 记录日志
frago run log \
  --step "等待用户登录Upwork" \
  --status "success" \
  --action-type "user_interaction" \
  --execution-method "manual" \
  --data '{"instruction": "请手动登录Upwork账号", "completed": true}'
```

### 5. analysis - AI 推理/思考

```bash
# AI 分析 DOM 结构，推断选择器
# 记录日志
frago run log \
  --step "分析页面DOM结构" \
  --status "success" \
  --action-type "analysis" \
  --execution-method "analysis" \
  --data '{
    "conclusion": "职位列表使用CSS选择器 .job-card",
    "confidence": "high",
    "reasoning": "观察到所有职位元素都包含 job-card 类名"
  }'
```

### 6. tool - AI 工具调用

```bash
# 使用 AskUserQuestion 工具
# 记录日志
frago run log \
  --step "询问用户选择目标职位" \
  --status "success" \
  --action-type "user_interaction" \
  --execution-method "tool" \
  --data '{
    "tool": "AskUserQuestion",
    "question": "发现8个高薪职位，选择哪个？",
    "options": ["职位A", "职位B"],
    "answer": "职位A"
  }'
```

---

## 四、_insights 强制记录（/frago.run 专用）

**每 5 条日志至少 1 条包含 `_insights`。** 这是 Recipe 生成的核心信息来源。

**重要**：CDP 命令的自动日志只记录客观执行结果，**`_insights` 必须由 Agent 手动添加**。

| 触发条件 | insight_type | 要求 |
|---------|--------------|------|
| 操作失败/报错 | `pitfall` | **必须** |
| 重试后成功 | `lesson` | **必须** |
| 发现意外行为 | `pitfall`/`workaround` | **必须** |
| 找到关键技巧 | `key_factor` | **必须** |
| 首次就成功 | - | 可选 |

### 典型流程

```bash
# 1. 执行 CDP 命令 → 自动记录基础日志
frago chrome click '.job-card'  # 失败，自动记录错误日志

# 2. Agent 反思后手动添加 insight
frago run log \
  --step "分析点击失败原因" \
  --status "warning" \
  --action-type "analysis" \
  --execution-method "analysis" \
  --data '{
    "command": "frago chrome click .job-card",
    "error": "Element not found",
    "_insights": [
      {"type": "pitfall", "summary": "动态class不可靠，需用data-testid"}
    ]
  }'
```

---

## 五、调研成功标准（/frago.run 专用）

调研完成需满足以下条件：

1. **关键问题有答案**：每个预定义的关键问题都有明确答案
2. **验证测试通过**：如涉及 API/工具，已有测试脚本验证可行性
3. **最后一条日志包含 Recipe 草稿**：

```json
{
  "action_type": "analysis",
  "execution_method": "analysis",
  "step": "总结调研结论并生成 Recipe 草稿",
  "data": {
    "ready_for_recipe": true,
    "recipe_spec": {
      "name": "recipe_name_snake_case",
      "type": "atomic",
      "runtime": "chrome-js",
      "description": "简短描述",
      "inputs": {},
      "outputs": {},
      "key_steps": [],
      "critical_selectors": {},
      "pitfalls_to_avoid": ["从 _insights 汇总"],
      "key_factors": ["从 _insights 汇总"]
    }
  }
}
```

---

## 六、代码文件处理约束

**当需要执行代码时**：

1. **简单命令**：直接使用 `frago <command>`，记录为 `execution_method: command`
2. **复杂脚本**（>30行）：保存为 `scripts/<name>.{py,js,sh}`，记录为 `execution_method: file`

```python
# ❌ 错误做法（禁止）
data = {
    "code": "import json\nwith open(...) as f:\n..."  # 不要存储长代码
}

# ✅ 正确做法
# 1. 保存脚本
with open('projects/<project_id>/scripts/filter_jobs.py', 'w') as f:
    f.write(script_content)

# 2. 执行脚本
uv run python projects/<project_id>/scripts/filter_jobs.py

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

---

## 七、进度展示

**每 5 步输出一次进度摘要**：

```markdown
✅ 已完成 5 步：
1. 导航到Upwork搜索页（navigation/command）
2. 提取15个Python职位（extraction/command）💡 key_factor: 需等待加载完成
3. 过滤薪资>$50的职位（data_processing/file）
4. 分析技能要求（analysis/analysis）
5. 生成报告（data_processing/file）

📊 当前统计：15条日志，3个截图，2个脚本文件 | Insights: 2个 key_factor，1个 pitfall
```
