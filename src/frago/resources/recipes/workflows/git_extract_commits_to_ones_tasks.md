---
name: git_extract_commits_to_ones_tasks
type: workflow
runtime: python
description: "从 Git 日志提取 commit 信息，生成 ONES 任务 Markdown 文档"
use_cases:
  - "自动化团队周报：批量提取本周的 commit 并生成任务列表"
  - "项目交付文档：将开发过程转换为结构化任务记录"
  - "代码审查准备：快速生成待审查的功能列表"
  - "工时统计：基于代码量自动估算工时"
tags:
  - git
  - ones
  - task-generation
  - documentation
  - workflow
output_targets:
  - stdout
  - file
inputs:
  project_path:
    type: string
    required: true
    description: "Git 项目的绝对路径"
  commit_range:
    type: string
    required: false
    description: "Git commit 范围，如 'HEAD~10..HEAD' 或 'v1.0..v2.0'，默认 'HEAD~10..HEAD'"
  output_file:
    type: string
    required: false
    description: "输出 Markdown 文件路径，不指定则输出到 stdout"
  author_mapping_file:
    type: string
    required: false
    description: "作者邮箱 → ONES 用户名映射文件（JSON/YAML）"
  project_name:
    type: string
    required: false
    description: "ONES 项目名称（如 '[Scrum] D版 算法AI应用'）"
outputs:
  success:
    type: boolean
    description: "执行是否成功"
  commits_count:
    type: integer
    description: "提取的 commit 数量"
  output_file:
    type: string
    description: "生成的 Markdown 文件路径"
  markdown_content:
    type: string
    description: "Markdown 内容（仅在未指定 output_file 时通过 stdout 输出）"
dependencies: []
version: "1.0.0"
---

# git_extract_commits_to_ones_tasks

## 功能描述

从 Git 仓库提取 commit 历史，解析 Conventional Commits 格式的 commit message，自动生成 ONES 项目管理系统的任务 Markdown 文档。

**核心功能**：
1. **Git 信息提取**：使用 `git log` 和 `git show` 提取 commit 元数据、message、文件变更统计
2. **Conventional Commits 解析**：自动识别 `type(scope): description` 格式，提取 type、scope、body、footer
3. **智能映射**：
   - Git commit type → ONES Issue type（feat→Task, fix→Bug）
   - Git scope → 所属模块
   - Git author email → ONES 负责人（通过映射表）
   - 代码行数 → 预估工时（简单估算规则）
4. **Markdown 生成**：生成结构化的任务文档，可直接复制到 ONES 或用于团队汇报

**适用场景**：
- 团队周报：快速生成本周开发任务列表
- 项目交付：将开发过程转换为结构化任务记录
- 代码审查：生成待审查的功能和修复列表
- 工时统计：基于代码量自动估算工时

## 使用方法

### 基础用法（输出到终端）

```bash
# 提取当前项目最近 10 个 commit
uv run frago recipe run git_extract_commits_to_ones_tasks \
  --params '{"project_path": "/home/yammi/repos/Frago"}'

# 提取指定范围的 commit
uv run frago recipe run git_extract_commits_to_ones_tasks \
  --params '{
    "project_path": "/home/yammi/repos/Frago",
    "commit_range": "HEAD~20..HEAD"
  }'
```

### 输出到文件

```bash
# 生成 Markdown 文件
uv run frago recipe run git_extract_commits_to_ones_tasks \
  --params '{
    "project_path": "/home/yammi/repos/ChimeOS",
    "commit_range": "HEAD~15..HEAD",
    "output_file": "tasks_2025-11-24.md"
  }'
```

### 使用作者映射表

**创建映射文件** `author_mapping.json`:
```json
{
  "author_mapping": {
    "yammi@yammi.cafe": "蔡佳鸣",
    "john@example.com": "张三",
    "alice@example.com": "李四"
  }
}
```

**执行配方**：
```bash
uv run frago recipe run git_extract_commits_to_ones_tasks \
  --params '{
    "project_path": "/home/yammi/repos/Frago",
    "output_file": "tasks.md",
    "author_mapping_file": "author_mapping.json",
    "project_name": "[Scrum] Frago 自动化框架"
  }'
```

### 使用 Git 标签范围

```bash
# 提取两个版本之间的 commit
uv run frago recipe run git_extract_commits_to_ones_tasks \
  --params '{
    "project_path": "/home/yammi/repos/Frago",
    "commit_range": "v1.0.0..v2.0.0",
    "output_file": "release_tasks_v2.0.0.md"
  }'
```

## 前置条件

1. **Git 仓库**：目标路径必须是有效的 Git 仓库（包含 `.git` 目录）
2. **Python 环境**：Python 3.9+（Frago 项目已满足）
3. **可选依赖**：
   - 如果使用 YAML 格式的作者映射文件，需要安装 `pyyaml`
   - 如果使用 JSON 格式，无需额外依赖

## 参数说明

### `project_path`（必需）
- **类型**: string
- **说明**: Git 项目的**绝对路径**
- **示例**: `"/home/yammi/repos/Frago"`

### `commit_range`（可选）
- **类型**: string
- **默认值**: `"HEAD~10..HEAD"`
- **说明**: Git commit 范围，支持：
  - 相对范围：`HEAD~10..HEAD`（最近 10 个 commit）
  - 标签范围：`v1.0.0..v2.0.0`（两个版本之间）
  - 分支范围：`main..feature/new-auth`
  - 时间范围：`--since="2 weeks ago"`（需要修改脚本支持）

### `output_file`（可选）
- **类型**: string
- **默认值**: `null`（输出到 stdout）
- **说明**: 输出 Markdown 文件的路径（相对或绝对路径）
- **示例**: `"tasks_2025-11-24.md"` 或 `"/tmp/tasks.md"`

### `author_mapping_file`（可选）
- **类型**: string
- **默认值**: `null`（使用 Git author name）
- **说明**: 作者邮箱 → ONES 用户名映射文件，支持 JSON 和 YAML 格式
- **格式**:
  ```json
  {
    "author_mapping": {
      "email@example.com": "ONES用户名"
    }
  }
  ```

### `project_name`（可选）
- **类型**: string
- **默认值**: `null`（不显示项目名）
- **说明**: ONES 项目名称，会显示在每个任务的 `Project` 字段
- **示例**: `"[Scrum] D版 算法AI应用"`

## 预期输出

### 成功时（输出到文件）

**stdout（JSON 格式）**:
```json
{
  "success": true,
  "commits_count": 5,
  "output_file": "/home/yammi/repos/Frago/tasks_2025-11-24.md",
  "message": "已生成 5 个任务到 tasks_2025-11-24.md"
}
```

**生成的 Markdown 文件** (`tasks_2025-11-24.md`):
```markdown
# ONES 任务列表

> 生成时间: 2025-11-24 10:50:00
> 共 5 个任务

---

## 任务 1: 添加用户登录功能

### 基本信息

- **Title**: 添加用户登录功能
- **Project**: [Scrum] Frago 自动化框架
- **Issue type**: Task
- **任务类型**: 新功能开发
- **负责人**: 蔡佳鸣
- **所属模块**: auth
- **预估工时**: 4.0 小时
- **当前步骤**: 已完成

### 描述

实现基于 JWT 的用户认证系统，支持用户名/密码登录和 Token 自动刷新。

#### 技术细节

**修改文件**:
- `src/auth/login.py`
- `src/auth/utils.py`
- `tests/test_login.py`
- `frontend/pages/Login.tsx`

**变更统计**:
- 新增: 230 行
- 删除: 15 行
- 修改文件数: 4

**Commit 信息**:
- Hash: `a1b2c3d`
- Author: 蔡佳鸣 <yammi@yammi.cafe>
- Date: 2025-11-24 10:00:00 +0800

### 关联信息

- **关联问题**: #123, #456

---

## 任务 2: 修复登录页面样式错误

...
```

### 失败时（错误输出到 stderr）

```json
{
  "success": false,
  "error": {
    "type": "Exception",
    "message": "Git 命令执行失败: fatal: not a git repository"
  }
}
```

## Conventional Commits 解析规则

脚本会自动解析符合 [Conventional Commits](https://www.conventionalcommits.org/) 规范的 commit message：

### 标准格式

```
<type>(<scope>): <description>

<body>

<footer>
```

**示例**:
```
feat(auth): 添加用户登录功能

实现基于 JWT 的用户认证系统，支持：
- 用户名/密码登录
- Token 自动刷新
- 记住我功能

Closes #123
Related to #456
```

### 提取的字段

| 字段 | 来源 | 用途 |
|------|------|------|
| `type` | commit message 第一行 | 映射到 ONES Issue type 和任务类型 |
| `scope` | commit message 第一行 | 映射到所属模块 |
| `description` | commit message 第一行 | 任务标题 |
| `body` | commit message 正文 | 任务描述 |
| `footer` | commit message 末尾 | 提取关联问题和依赖关系 |

### 支持的 commit type

| Type | ONES Issue Type | 任务类型 |
|------|----------------|----------|
| `feat` | Task | 新功能开发 |
| `fix` | Bug | 问题修复 |
| `refactor` | Task | 代码重构 |
| `docs` | Task | 文档更新 |
| `test` | Task | 测试 |
| `chore` | Task | 杂务 |
| `style` | Task | 代码格式 |
| `perf` | Task | 性能优化 |
| `ci` | Task | CI/CD |
| `build` | Task | 构建 |

### 关联问题提取

脚本会从 footer 中提取以下关键字：

- **关联问题**：`Closes #123`, `Fixes #456`, `Resolves #789`, `Ref #101`, `Related to #102`
- **依赖关系**：`Depends on #200`, `Blocked by #201`

## 工时估算规则

基于代码变更行数的简单估算：

| 总行数（增+删） | 预估工时 |
|----------------|---------|
| < 50 行 | 0.5 小时 |
| 50-200 行 | 2.0 小时 |
| 200-500 行 | 4.0 小时 |
| > 500 行 | 8.0 小时 |

**注意**：这是粗略估算，实际工时应根据任务复杂度调整。

## 模块推断规则

脚本会按以下优先级推断任务所属模块：

1. **优先使用 scope**：如果 commit message 包含 scope（如 `feat(auth): ...`），直接使用 `auth` 作为模块
2. **文件路径推断**：如果没有 scope，取第一个修改文件的顶层目录：
   - `src/auth/login.py` → `src`
   - `frontend/pages/Login.tsx` → `frontend`
3. **默认值**：如果无法推断，使用 `"未知"` 或 `"根目录"`

**建议**：在 commit message 中使用 scope 以获得更准确的模块分类。

## 作者映射表格式

### JSON 格式

```json
{
  "author_mapping": {
    "yammi@yammi.cafe": "蔡佳鸣",
    "john@example.com": "张三",
    "alice@example.com": "李四"
  }
}
```

### YAML 格式

```yaml
author_mapping:
  yammi@yammi.cafe: "蔡佳鸣"
  john@example.com: "张三"
  alice@example.com: "李四"
```

**注意**：
- YAML 格式需要安装 `pyyaml`：`pip install pyyaml`
- 如果未提供映射表，脚本会直接使用 Git author name

## 实际使用示例

### 场景 1：团队周报

**需求**：生成本周的开发任务列表，用于周会汇报。

```bash
# 提取本周的 commit（假设本周有 15 个 commit）
uv run frago recipe run git_extract_commits_to_ones_tasks \
  --params '{
    "project_path": "/home/yammi/repos/ChimeOS",
    "commit_range": "HEAD~15..HEAD",
    "output_file": "weekly_report_2025-11-24.md",
    "author_mapping_file": "team_mapping.json",
    "project_name": "[Scrum] ChimeOS 语音助手"
  }'
```

**输出**：生成 `weekly_report_2025-11-24.md`，包含 15 个任务的详细信息。

### 场景 2：版本发布文档

**需求**：生成 v1.0 到 v2.0 之间的所有功能和修复。

```bash
uv run frago recipe run git_extract_commits_to_ones_tasks \
  --params '{
    "project_path": "/home/yammi/repos/Frago",
    "commit_range": "v1.0.0..v2.0.0",
    "output_file": "release_notes_v2.0.0.md",
    "project_name": "[Release] Frago v2.0.0"
  }'
```

### 场景 3：代码审查准备

**需求**：提取最近 5 个 commit 用于代码审查。

```bash
uv run frago recipe run git_extract_commits_to_ones_tasks \
  --params '{
    "project_path": "/home/yammi/repos/frago",
    "commit_range": "HEAD~5..HEAD",
    "output_file": "code_review_tasks.md"
  }'
```

### 场景 4：快速查看（不保存文件）

**需求**：快速查看最近的任务，不保存文件。

```bash
# 输出到终端，可以使用 less 查看
uv run frago recipe run git_extract_commits_to_ones_tasks \
  --params '{
    "project_path": "/home/yammi/repos/Frago",
    "commit_range": "HEAD~3..HEAD"
  }' | less
```

## 注意事项

1. **Conventional Commits 格式**：
   - 脚本会尽力解析不规范的 commit message，但建议使用标准格式
   - 不符合格式的 commit，type 会被设为 `unknown`，整行作为 description

2. **Git 仓库状态**：
   - 脚本只读取 Git 历史，不会修改仓库
   - 确保目标路径是有效的 Git 仓库

3. **工时估算精度**：
   - 当前使用简单的行数估算规则，实际工时可能有较大偏差
   - 建议根据团队实际情况调整估算规则（修改脚本中的 `estimate_hours_from_stats` 函数）

4. **中文编码**：
   - 脚本使用 UTF-8 编码，确保 commit message 和输出文件都是 UTF-8

5. **性能**：
   - 提取大量 commit（如 100+）时可能较慢，因为每个 commit 需要执行 `git show`
   - 建议按需提取（如最近 20 个 commit）

6. **Merge Commits**：
   - 脚本默认跳过 merge commits（`--no-merges`）
   - 如果需要包含 merge commits，需要修改脚本

## 扩展建议

### 1. 自定义工时估算规则

修改 `estimate_hours_from_stats` 函数，增加更复杂的估算逻辑：

```python
def estimate_hours_from_stats(lines_added: int, lines_deleted: int, commit_type: str, files: List[str]) -> float:
    """增强的工时估算"""
    total_lines = lines_added + lines_deleted

    # 基础工时
    if total_lines < 50:
        base_hours = 0.5
    elif total_lines < 200:
        base_hours = 2.0
    elif total_lines < 500:
        base_hours = 4.0
    else:
        base_hours = 8.0

    # 根据文件类型调整
    if any('test' in f for f in files):
        base_hours *= 0.8  # 测试文件系数

    if any('frontend' in f or '.tsx' in f or '.vue' in f for f in files):
        base_hours *= 1.2  # 前端复杂度系数

    # 根据 commit type 调整
    if commit_type == 'fix':
        base_hours *= 1.5  # Bug 修复通常更复杂

    return round(base_hours, 1)
```

### 2. 增加模块映射配置

类似作者映射，支持从配置文件读取模块映射：

```json
{
  "module_mapping": {
    "src/auth/": "认证模块",
    "src/api/": "API 模块",
    "frontend/": "前端",
    "tests/": "测试"
  }
}
```

### 3. 集成 ONES API

将生成的任务数据直接通过 ONES API 创建任务，而非生成 Markdown：

```python
import requests

def create_ones_task(task_data):
    """通过 ONES API 创建任务"""
    api_url = "https://ones.example.com/api/v1/tasks"
    headers = {"Authorization": "Bearer YOUR_TOKEN"}
    response = requests.post(api_url, json=task_data, headers=headers)
    return response.json()
```

### 4. 支持时间范围

修改脚本支持时间范围参数：

```bash
uv run frago recipe run git_extract_commits_to_ones_tasks \
  --params '{
    "project_path": "/home/yammi/repos/Frago",
    "since": "2025-11-01",
    "until": "2025-11-24"
  }'
```

## 故障排查

### 错误：不是 Git 仓库

```json
{
  "success": false,
  "error": "不是 Git 仓库: /path/to/project"
}
```

**解决方案**：确保 `project_path` 包含 `.git` 目录。

### 错误：未找到任何 commit

```json
{
  "success": false,
  "error": "未找到任何 commit"
}
```

**可能原因**：
- `commit_range` 范围内没有 commit
- 所有 commit 都是 merge commits（被 `--no-merges` 过滤）

**解决方案**：调整 `commit_range` 或检查 Git 历史。

### 错误：Git 命令执行失败

```json
{
  "success": false,
  "error": "Git 命令执行失败: fatal: ambiguous argument 'v1.0.0..v2.0.0'"
}
```

**可能原因**：指定的标签不存在。

**解决方案**：使用 `git tag` 检查可用的标签。

## 更新历史

| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-24 | v1.0.0 | 初始版本，支持从 Git 提取 commit 并生成 ONES 任务 Markdown |
