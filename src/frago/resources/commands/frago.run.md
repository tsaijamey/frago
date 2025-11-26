---
description: "执行AI主持的复杂浏览器自动化任务并管理run实例"
---

# /frago.run - Run命令系统

## 你的任务

作为任务执行者,你需要使用**Run命令系统**管理AI主持的复杂浏览器自动化任务。Run实例是**主题型的信息中心**,用于持久化存储任务执行历史和积累的知识。

## 核心概念

### Run实例的作用（专注于Recipe创建前的探索调研）

- **探索和调研**: Recipe创建前的信息收集
- **跨Recipe上下文**: 多个Recipe调用的信息积累
- **Workflow构建**: 复杂流程的信息组织

**重要**：run 系统专注于"探索期"，目标是收集足够的信息以创建 Recipe。如果需要执行一次性的复杂任务，请使用 `/frago.exec` 命令。

### 结构化日志格式

所有操作必须记录到 `execution.jsonl`,包含以下关键字段:

- `action_type`: 操作类型 (navigation/extraction/interaction/screenshot/recipe_execution/data_processing/analysis/user_interaction/other)
- `execution_method`: 执行方法 (command/recipe/file/manual/analysis/tool)
- `data`: 操作详情 (JSON对象)

## 执行流程

### 1. 明确调研目标

在开始前，明确本次调研的关键问题：

```markdown
## 调研目标
- **主题**：[简洁描述，如 "nano-banana-pro image api"]
- **关键问题**：
  1. [问题1]
  2. [问题2]
  3. [问题3]
```

### 2. 发现现有run实例

检查是否存在相关的run实例:

```bash
uv run frago run list --format json
```

分析JSON输出,提取run列表并计算与用户任务的相似度。

### 3. 生成主题 ID (如需创建新 run)

**重要**：run_id 必须是简洁、可读的英文短句（3-5 个词）

根据用户任务描述，生成主题短句：

```python
# 示例 1
用户任务："调研nano banana pro的图片生成接口使用方法"
主题短句："nano-banana-pro image api research"

# 示例 2
用户任务："在Upwork上搜索Python职位"
主题短句："upwork python jobs search"

# 示例 3
用户任务："测试YouTube字幕提取功能"
主题短句："youtube transcript extraction test"
```

**生成规则**：
- 使用英文（避免中文转拼音）
- 保留专有名词原样（Nano Banana Pro → nano-banana-pro）
- 提取核心动作和对象（搜索职位 → jobs search）
- 3-5 个词，用空格或连字符分隔

### 4. 交互式选择 (使用 AskUserQuestion)

如果发现相关run (相似度>60%),使用 **AskUserQuestion** 工具展示选项:

```markdown
问题: "发现现有run实例,选择继续哪个?"
选项:
- ⭐ upwork-python-jobs (相似度: 85%) - 主题: 在Upwork上搜索Python职位
- create-new-run - 为当前任务创建新的run实例
```

### 5. 固化工作环境

选择或创建run后,立即设置上下文:

```bash
# 继续现有run
uv run frago run set-context <run_id>

# 或创建新run（使用生成的主题短句）
uv run frago run init "nano-banana-pro image api research"
uv run frago run set-context <返回的run_id>
```

**关键**: 上下文设置后,后续所有 `log` 和 `screenshot` 命令将自动关联到该run。

### 6. 执行调研并记录日志

每个关键步骤后,使用 `log` 命令记录:

```bash
uv run frago run log \
  --step "步骤描述" \
  --status "success|error|warning" \
  --action-type "<见下方9种有效值>" \
  --execution-method "<见下方6种有效值>" \
  --data '{"key": "value"}'
```

**9种有效 action-type 值**（必须严格使用以下值之一）：
1. `navigation` - 页面导航（打开URL、前进、后退）
2. `extraction` - 数据提取（抓取页面内容、解析DOM）
3. `interaction` - 页面交互（点击、输入、选择）
4. `screenshot` - 截图操作
5. `recipe_execution` - 执行Recipe
6. `data_processing` - 数据处理（筛选、转换、保存文件）
7. `analysis` - AI分析和推理
8. `user_interaction` - 用户交互（询问、确认）
9. `other` - 其他操作

**常见错误映射**：
- ❌ `web_search` → ✅ 使用 `data_processing` 或 `extraction`
- ❌ `browsing` → ✅ 使用 `navigation`
- ❌ `scraping` → ✅ 使用 `extraction`
- ❌ `click` → ✅ 使用 `interaction`
- ❌ `query` → ✅ 使用 `user_interaction` 或 `analysis`

**6种有效 execution-method 值**（必须严格使用以下值之一）：
1. `command` - CLI命令执行（如 `uv run frago navigate`）
2. `recipe` - Recipe调用
3. `file` - 执行脚本文件（.py/.js/.sh）
4. `manual` - 人工手动操作
5. `analysis` - AI推理和思考
6. `tool` - AI工具调用（如 AskUserQuestion）

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
uv run frago recipe list --format json
```

**调用Recipe并记录**:

```bash
# 执行Recipe
uv run frago recipe run <recipe_name> --params '{"url": "..."}' --output-file result.json

# 记录日志
uv run frago run log \
  --step "执行Recipe: <recipe_name>" \
  --status "success" \
  --action-type "recipe_execution" \
  --execution-method "recipe" \
  --data '{"recipe_name": "<recipe_name>", "params": {...}, "output_file": "result.json"}'
```

### 7. 代码文件处理约束

**当需要执行代码时**:

1. **简单命令**: 直接使用 `uv run frago <command>`,记录为 `execution_method: command`
2. **复杂脚本** (>30行): 保存为 `scripts/<name>.{py,js,sh}`,记录为 `execution_method: file`

示例:

```python
# 错误做法 (禁止)
data = {
    "code": "import json\nwith open(...) as f:\n..."  # ✗ 不要存储长代码
}

# 正确做法
# 1. 保存脚本
with open('projects/<run_id>/scripts/filter_jobs.py', 'w') as f:
    f.write(script_content)

# 2. 执行脚本
uv run python projects/<run_id>/scripts/filter_jobs.py

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
uv run frago run log \
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
uv run frago navigate https://upwork.com/search

# 记录日志
uv run frago run log \
  --step "导航到Upwork搜索页" \
  --status "success" \
  --action-type "navigation" \
  --execution-method "command" \
  --data '{"command": "uv run frago navigate https://upwork.com/search", "exit_code": 0}'
```

### 2. recipe - Recipe调用

```bash
# 执行Recipe
uv run frago recipe run upwork_extract_job_list --params '{"keyword": "Python"}'

# 记录日志
uv run frago run log \
  --step "提取Python职位列表" \
  --status "success" \
  --action-type "recipe_execution" \
  --execution-method "recipe" \
  --data '{"recipe_name": "upwork_extract_job_list", "params": {"keyword": "Python"}, "output": {"jobs": [...], "total": 15}}'
```

### 3. file - 执行脚本文件

```bash
# 保存脚本
cat > projects/<run_id>/scripts/filter_jobs.py <<EOF
import json
jobs = json.load(open('outputs/raw_jobs.json'))
filtered = [j for j in jobs if j['rate'] > 50]
json.dump(filtered, open('outputs/filtered_jobs.json', 'w'))
print(f"筛选出 {len(filtered)} 个高薪职位")
EOF

# 执行脚本 (注意: 在项目根目录执行,使用完整相对路径)
uv run python projects/<run_id>/scripts/filter_jobs.py

# 记录日志
uv run frago run log \
  --step "筛选薪资>$50的职位" \
  --status "success" \
  --action-type "data_processing" \
  --execution-method "file" \
  --data '{"file": "scripts/filter_jobs.py", "language": "python", "command": "uv run python projects/<run_id>/scripts/filter_jobs.py", "exit_code": 0, "output": "筛选出 8 个高薪职位", "result_file": "outputs/filtered_jobs.json"}'
```

### 4. manual - 人工操作

```bash
# 提示用户手动操作,并等待确认
# 记录日志
uv run frago run log \
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
uv run frago run log \
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
uv run frago run log \
  --step "询问用户选择目标职位" \
  --status "success" \
  --action-type "user_interaction" \
  --execution-method "tool" \
  --data '{"tool": "AskUserQuestion", "question": "发现8个高薪职位,选择哪个?", "options": ["职位A", "职位B"], "answer": "职位A"}'
```

## 调研成功标准（必须遵守）

### ✅ 信息充分性检查

调研完成需满足以下条件：

1. **关键问题有答案**：
   - 每个预定义的关键问题都有明确答案
   - 答案记录在日志的 `data` 字段

2. **验证测试通过**：
   - 如涉及API/工具，已有测试脚本验证可行性
   - 测试结果记录在日志

3. **最后一条日志标记**：
   ```json
   {
     "action_type": "analysis",
     "execution_method": "analysis",
     "step": "总结调研结论并生成 Recipe 草稿",
     "data": {
       "answers": {
         "问题1": "具体答案（包含数据、链接、验证结果）",
         "问题2": "具体答案"
       },
       "ready_for_recipe": true,  // 关键标记
       "recipe_spec": {           // 必需：Recipe 草稿
         "name": "recipe_name_snake_case",
         "type": "atomic",  // 或 "workflow"
         "runtime": "chrome-js",  // 或 "python", "shell"
         "description": "简短描述这个 Recipe 的作用",
         "inputs": {
           "param1": {
             "type": "string",
             "required": true,
             "description": "参数说明"
           }
         },
         "outputs": {
           "result_field": "返回值说明"
         },
         "key_steps": [
           "步骤1的描述",
           "步骤2的描述"
         ],
         "critical_selectors": {  // 如果是 chrome-js
           "element1": "CSS 选择器"
         },
         "verified_scripts": [  // 验证脚本列表
           "scripts/test_selectors.js"
         ]
       }
     }
   }
   ```

### 🛑 停止条件

满足以下任一条件立即停止：
- 所有关键问题有答案 + 最后一条日志标记 `ready_for_recipe: true`
- 用户明确指示停止
- 发现信息不足以创建 Recipe，需要重新定义调研目标

### ❌ 禁止的输出行为

1. **禁止创建 Markdown 文档**：
   - ❌ 总结文档（`RESEARCH_SUMMARY.md`）
   - ❌ 快速指南（`QUICKSTART_GUIDE.md`）
   - ❌ 分析报告（`*_ANALYSIS.md`）
   - **原因**：所有信息已在 `execution.jsonl` 的 `data` 字段

2. **禁止重复记录相似日志**：
   - ❌ 多次"创建文档"日志
   - ❌ 多次"总结"日志

### ✅ 允许的输出（服务于 Recipe 创建）

**核心原则**：所有输出物必须直接服务于 Recipe 的创建和验证。

#### 1. **必需输出**

- **`execution.jsonl`**（必需）
  - 作用：记录完整的探索过程，包括尝试、失败、成功的步骤
  - 用途：Recipe 创建时参考实际执行流程

#### 2. **验证脚本**（强烈推荐）

- **`scripts/test_*.{py,js,sh}`**
  - 作用：验证关键步骤的可行性（如选择器有效性、API 调用成功）
  - 用途：Recipe 的测试用例基础
  - 示例：
    - `scripts/test_login.py` - 验证登录流程
    - `scripts/test_selectors.js` - 测试 DOM 选择器
    - `scripts/extract_sample_data.py` - 验证数据提取逻辑

#### 3. **探索过程快照**（关键步骤截图）

- **`screenshots/*.png`**
  - 作用：记录关键界面状态和 DOM 结构
  - 用途：Recipe 文档中的步骤说明
  - 命名规范：`001_step-description.png`（按顺序编号）

#### 4. **Recipe 草稿**（调研完成时输出）

在最后一条日志的 `data` 字段中包含 Recipe 草稿：

```json
{
  "action_type": "analysis",
  "step": "总结调研结论并生成 Recipe 草稿",
  "data": {
    "ready_for_recipe": true,
    "recipe_spec": {
      "name": "recipe_name",
      "type": "atomic",
      "runtime": "chrome-js",
      "inputs": {
        "url": {"type": "string", "required": true},
        "keyword": {"type": "string", "required": false}
      },
      "outputs": {
        "result": "extracted_data"
      },
      "key_steps": [
        "1. 导航到目标页面",
        "2. 等待页面加载",
        "3. 提取数据",
        "4. 返回结果"
      ],
      "critical_selectors": {
        "job_list": ".job-card",
        "job_title": ".job-card h3",
        "job_rate": ".job-card .rate"
      },
      "verified_by": "scripts/test_selectors.js"
    }
  }
}
```

#### 5. **临时数据文件**（可选，用于验证）

- **`outputs/sample_*.json`**
  - 作用：保存探索过程中提取的样本数据
  - 用途：验证数据结构，设计 Recipe 的输出格式
  - 示例：`outputs/sample_jobs.json`（提取的职位样本）

**重要约束**：
- ❌ **禁止**创建独立的总结文档（如 `RESEARCH_SUMMARY.md`）
- ❌ **禁止**创建用户阅读型报告（不管是 `.md` 还是其他格式）
- ✅ **所有信息必须在 `execution.jsonl` 或 Recipe 草稿中体现**
- ✅ **所有输出物必须直接服务于 Recipe 创建**（验证脚本、测试数据、截图）

## 最佳实践

### ✅ 推荐做法

1. **调研开始前明确目标**: 列出 3-5 个关键问题
2. **每5步输出摘要**: 让用户了解进度
3. **脚本文件化**: 超过30行的代码保存为文件,不直接存储到日志
4. **结构化data**: 使用清晰的JSON结构,便于后续分析
5. **截图关键步骤**: 使用 `uv run frago run screenshot "描述"` 保存重要界面

### ❌ 禁止做法

1. **跳过上下文设置**: 必须先 `set-context` 再执行 `log`/`screenshot`
2. **日志中存储长代码**: 超过100行的代码必须保存为文件
3. **遗漏execution_method**: 每条日志必须明确执行方法
4. **模糊的step描述**: 步骤描述要具体 ("提取了15个职位" 而非 "提取数据")
5. **创建冗余文档**: 不要创建 Markdown 总结文档

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

**详细日志**: projects/find-job-on-upwork/logs/execution.jsonl (共20条记录)

**下次继续**: `uv run frago run set-context find-job-on-upwork`
```

## 注意事项

- **上下文优先级**: 环境变量 `FRAGO_CURRENT_RUN` > 配置文件 `.frago/current_run`
- **日志格式版本**: 当前为 `schema_version: "1.0"`
- **并发安全**: 同一时间只在一个run实例中工作,避免上下文混乱

## ⚠️ 重要: 工作目录管理

**禁止使用 `cd` 命令切换目录!** 这会导致 `uv run frago` 命令失效。

### ✅ 正确做法

**始终在项目根目录 (`/Users/chagee/Repos/Frago`) 执行所有命令**,使用绝对路径或相对路径访问文件:

```bash
# ✓ 正确: 使用绝对路径执行脚本
uv run python projects/<run_id>/scripts/filter_jobs.py

# ✓ 正确: 使用相对路径读取文件
cat projects/<run_id>/outputs/result.json

# ✓ 正确: 使用find查看文件结构
find projects/<run_id> -type f -name "*.md" | sort
```

### ❌ 错误做法

```bash
# ✗ 错误: 不要使用 cd
cd projects/<run_id> && uv run python scripts/filter_jobs.py

# ✗ 错误: 切换目录后 uv run frago 会失效
cd projects/<run_id>
uv run frago run log ...  # 这会报错!
```

### 文件路径约定

在 run 实例内部引用文件时,使用**相对于 run 根目录的路径**:

```bash
# 记录日志时, data.file 使用相对路径
uv run frago run log \
  --data '{"file": "scripts/filter_jobs.py", "result_file": "outputs/filtered_jobs.json"}'

# 但执行脚本时,使用完整相对路径或绝对路径
uv run python projects/<run_id>/scripts/filter_jobs.py
```
