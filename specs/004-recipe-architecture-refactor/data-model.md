# Data Model: Recipe 系统架构重构

**Feature**: Recipe 系统架构重构
**Branch**: 004-recipe-architecture-refactor
**Date**: 2025-11-20

## 模型概述

Recipe 系统的数据模型基于文件系统，无需数据库。核心实体包括 Recipe 元数据、注册表、执行器和执行结果。

---

## 核心实体

### 1. RecipeMetadata（Recipe 元数据）

**描述**: 代表单个 Recipe 的元数据信息，从 `.md` 文件的 YAML frontmatter 解析。

**字段**:

| 字段名 | 类型 | 必需 | 描述 | 验证规则 |
|--------|------|------|------|---------|
| `name` | `str` | ✅ | Recipe 唯一标识符 | 长度 >= 1，仅包含字母、数字、下划线、连字符 |
| `type` | `str` | ✅ | Recipe 类型 | 枚举值：`atomic`（原子）或 `workflow`（编排） |
| `runtime` | `str` | ✅ | 运行时类型 | 枚举值：`chrome-js`, `python`, `shell` |
| `inputs` | `dict` | ❌ | 输入参数定义 | 键为参数名，值为 `{type, required, default}` |
| `outputs` | `dict` | ❌ | 输出字段定义 | 键为字段名，值为类型描述字符串 |
| `version` | `str` | ✅ | 版本号 | 语义化版本格式：`MAJOR.MINOR[.PATCH]` |
| `dependencies` | `list[str]` | ❌ | 依赖的 Recipe 名称列表 | 每个元素为有效的 Recipe 名称 |
| `description` | `str` | ✅ | 简短功能描述（AI 可理解） | 最大长度 200 字符 |
| `use_cases` | `list[str]` | ✅ | 适用场景列表（AI 可理解） | 至少包含 1 个场景描述 |
| `tags` | `list[str]` | ❌ | 语义标签（AI 可发现） | 用于分类和搜索 |
| `output_targets` | `list[str]` | ✅ | 支持的输出去向（AI 可规划） | 枚举值：`stdout`, `file`, `clipboard` |

**示例**（YAML frontmatter，AI-first 设计）:
```yaml
---
name: upwork_extract_job_details
type: atomic
runtime: chrome-js
description: "从 Upwork 职位详情页提取完整信息并格式化为 Markdown"
use_cases:
  - "分析市场上的职位需求"
  - "批量收集职位信息"
  - "为投标准备数据"
tags:
  - web-scraping
  - upwork
  - job-market
output_targets:
  - stdout
  - file
inputs:
  url:
    type: string
    required: true
    description: "Upwork 职位详情页 URL"
outputs:
  title: string
  description: string
  skills: array
version: 1.0.0
dependencies: []
---
```

**关系**:
- 一个 Recipe 对应一个 `.js`/`.py`/`.sh` 脚本文件
- 一个 Recipe 对应一个 `.md` 元数据文件
- Workflow Recipe 可以依赖多个 Atomic Recipe（通过 `dependencies` 字段）

**AI 可理解字段说明**:
- `description`: 简短功能描述，让 AI 能快速理解 Recipe 能做什么
- `use_cases`: 具体的使用场景列表，帮助 AI 判断是否适合当前任务
- `tags`: 语义标签，支持 AI 的分类和搜索
- `output_targets`: 声明 Recipe 支持的输出去向，AI 可根据任务需求选择
  - `stdout`: 输出到标准输出（适合快速查看、传递给下一步）
  - `file`: 输出到文件（适合批量任务、持久化存储）
  - `clipboard`: 输出到剪贴板（适合立即使用、手动粘贴）

---

### 2. Recipe（Recipe 实体）

**描述**: 代表一个完整的 Recipe，包含元数据和脚本文件路径。

**字段**:

| 字段名 | 类型 | 描述 |
|--------|------|------|
| `metadata` | `RecipeMetadata` | Recipe 元数据对象 |
| `script_path` | `Path` | Recipe 脚本文件的绝对路径 |
| `metadata_path` | `Path` | Recipe 元数据文件的绝对路径 |
| `source` | `str` | Recipe 来源标签（`Project`, `User`, `Example`） |

**验证规则**:
- `script_path` 必须存在且可读
- `metadata_path` 必须存在且可读
- `metadata.name` 必须与文件名（去扩展名）一致

**状态转换**: 无（Recipe 是静态实体，无状态变化）

---

### 3. RecipeRegistry（Recipe 注册表）

**描述**: 管理所有可用 Recipe 的索引，支持三级查找路径。

**字段**:

| 字段名 | 类型 | 描述 |
|--------|------|------|
| `search_paths` | `list[Path]` | Recipe 查找路径列表（按优先级排序） |
| `recipes` | `dict[str, Recipe]` | Recipe 名称到 Recipe 对象的映射 |

**行为**:
- `scan()`: 扫描所有 `search_paths`，解析元数据并构建索引
- `find(name: str) -> Recipe`: 查找指定名称的 Recipe（按优先级）
- `list_all() -> list[Recipe]`: 列出所有 Recipe（包含来源标签）
- `get_by_source(source: str) -> list[Recipe]`: 按来源过滤 Recipe

**查找路径优先级**:
1. 项目级: `.frago/recipes/` （当前工作目录）
2. 用户级: `~/.frago/recipes/` （用户家目录）
3. 示例级: `examples/` （仓库根目录或安装位置）

**子目录结构**:
每个查找路径下包含：
- `atomic/chrome/`: Chrome CDP 相关 Recipe
- `atomic/system/`: 系统操作相关 Recipe
- `workflows/`: 编排 Recipe

---

### 4. RecipeExecutor（Recipe 执行器）

**描述**: 抽象基类，定义执行 Recipe 的接口。具体实现包括 `ChromeJSExecutor`, `PythonExecutor`, `ShellExecutor`。

**接口**:

| 方法 | 参数 | 返回值 | 描述 |
|------|------|--------|------|
| `execute(script: Path, params: dict)` | `script`: 脚本路径<br>`params`: JSON 参数 | `dict`: JSON 结果 | 执行 Recipe 并返回结果 |

**实现子类**:

#### ChromeJSExecutor
- 调用命令: `uv run frago exec-js <script> <params_json>`
- 超时: 继承自 `exec-js` 命令的超时设置
- 错误处理: 捕获 CDP 连接失败、JavaScript 运行时错误

#### PythonExecutor
- 调用命令: `python3 <script> <params_json>`
- 环境变量: 继承当前 Python 环境
- 错误处理: 捕获 ModuleNotFoundError、语法错误、运行时异常

#### ShellExecutor
- 调用命令: `<script> <params_json>`
- 权限检查: 确保脚本有执行权限（`chmod +x`）
- 错误处理: 捕获命令不存在、权限拒绝、非零退出码

---

### 5. OutputHandler（输出处理器）

**描述**: 统一处理 Recipe 输出到不同目标（stdout/file/clipboard）的模块，为 AI 提供一致的输出接口。

**字段**:

| 字段名 | 类型 | 描述 |
|--------|------|------|
| 无状态类 | - | 所有方法为静态方法 |

**方法**:

| 方法 | 参数 | 返回值 | 描述 |
|------|------|--------|------|
| `handle(data, target, options)` | `data`: dict<br>`target`: str (`stdout`/`file`/`clipboard`)<br>`options`: dict | `None` | 根据目标类型处理输出 |

**实现逻辑**:

#### stdout
- 将 `data` 序列化为 JSON（带格式化）
- 输出到 stdout
- 不需要 `options` 参数

#### file
- 将 `data` 序列化为 JSON
- 写入到 `options['path']` 指定的文件
- 自动创建父目录（如需要）
- 验证文件路径合法性

#### clipboard
- 将 `data` 序列化为 JSON
- 使用 `pyperclip.copy()` 复制到剪贴板
- 依赖：需要安装 `pyperclip` 包

**CLI 集成**:
```bash
# stdout（默认）
uv run frago recipe run <name> --params '{...}'

# file
uv run frago recipe run <name> --params '{...}' --output-file result.json

# clipboard
uv run frago recipe run <name> --params '{...}' --output-clipboard
```

**AI 使用场景**:
- AI 根据任务需求选择输出方式：
  - 快速查看结果 → stdout
  - 批量任务保存 → file
  - 立即使用数据 → clipboard
- AI 通过 Recipe 元数据的 `output_targets` 字段判断支持哪些输出方式

---

### 6. RecipeExecutionResult（Recipe 执行结果）

**描述**: 封装 Recipe 执行的结果或错误信息。

**字段**:

| 字段名 | 类型 | 描述 |
|--------|------|------|
| `success` | `bool` | 执行是否成功 |
| `data` | `dict | None` | 成功时的返回数据（JSON 对象） |
| `error` | `RecipeError | None` | 失败时的错误对象 |
| `execution_time` | `float` | 执行耗时（秒） |
| `recipe_name` | `str` | Recipe 名称 |
| `runtime` | `str` | 使用的运行时 |

**成功响应示例**:
```json
{
  "success": true,
  "data": {
    "title": "Senior Python Developer",
    "description": "...",
    "skills": ["Python", "Django", "PostgreSQL"]
  },
  "execution_time": 2.35,
  "recipe_name": "upwork_extract_job_details",
  "runtime": "chrome-js"
}
```

**失败响应示例**（AI 可理解的结构化错误）:
```json
{
  "success": false,
  "error": {
    "type": "RecipeExecutionError",
    "message": "Recipe 'upwork_extract_job_details' 执行失败",
    "recipe_name": "upwork_extract_job_details",
    "runtime": "chrome-js",
    "exit_code": 1,
    "stdout": "Navigated to https://...",
    "stderr": "Error: Element not found: .job-title"
  },
  "execution_time": 1.02,
  "recipe_name": "upwork_extract_job_details",
  "runtime": "chrome-js"
}
```

**AI 错误处理能力**:
- AI 可以通过 `error.type` 判断错误类别（执行错误 vs 参数错误 vs 依赖缺失）
- AI 可以通过 `error.stderr` 分析具体失败原因（如选择器错误、网络问题）
- AI 可以根据错误类型采取策略（重试、调整参数、报告用户）

---

## 实体关系图

```text
RecipeRegistry
├── search_paths: [Path, Path, Path]
└── recipes: dict[str, Recipe]
        │
        ├─> Recipe (来源: Project)
        │   ├── metadata: RecipeMetadata
        │   │   ├── name: "custom_workflow"
        │   │   ├── type: "workflow"
        │   │   ├── runtime: "python"
        │   │   └── dependencies: ["upwork_extract_job"]
        │   ├── script_path: /path/to/.frago/recipes/workflows/custom_workflow.py
        │   ├── metadata_path: /path/to/.frago/recipes/workflows/custom_workflow.md
        │   └── source: "Project"
        │
        ├─> Recipe (来源: User)
        │   ├── metadata: RecipeMetadata
        │   │   ├── name: "upwork_extract_job"
        │   │   ├── type: "atomic"
        │   │   └── runtime: "chrome-js"
        │   ├── script_path: ~/.frago/recipes/atomic/chrome/upwork_extract_job.js
        │   └── source: "User"
        │
        └─> Recipe (来源: Example)
            ├── metadata: RecipeMetadata
            │   └── name: "youtube_extract_transcript"
            └── source: "Example"

RecipeRunner
├── registry: RecipeRegistry
└── executors: dict[str, RecipeExecutor]
        ├── "chrome-js": ChromeJSExecutor
        ├── "python": PythonExecutor
        └── "shell": ShellExecutor

OutputHandler（静态类）
└── handle(data, target, options) → 输出到 stdout/file/clipboard

执行流程（AI-first 视角）:
AI Agent → Bash tool: uv run frago recipe list --format json
         → RecipeRegistry.list_all() → JSON 元数据数组
         → AI 分析 description, use_cases, output_targets

AI Agent → Bash tool: uv run frago recipe run <name> --params '{...}' [--output-file/--output-clipboard]
         → RecipeRunner.run(name, params, output_target)
         → RecipeRegistry.find(name) → Recipe
         → RecipeExecutor.execute(script, params) → RecipeExecutionResult
         → OutputHandler.handle(result.data, target, options) → 输出到指定目标
```

---

## 文件系统布局

### Recipe 文件命名规范

**脚本文件**: `<recipe_name>.<ext>`
- `<ext>`: `.js`（chrome-js）, `.py`（python）, `.sh`（shell）

**元数据文件**: `<recipe_name>.md`
- 必须与脚本文件同名（仅扩展名不同）

**示例**:
```text
~/.frago/recipes/atomic/chrome/
├── upwork_extract_job_details_as_markdown.js
├── upwork_extract_job_details_as_markdown.md
├── youtube_extract_video_transcript.js
└── youtube_extract_video_transcript.md
```

### 元数据文件格式（AI-first 设计）

```markdown
---
name: recipe_name
type: atomic | workflow
runtime: chrome-js | python | shell
description: "简短功能描述，AI 可理解"  # 必需，<200 字符
use_cases:  # 必需，至少 1 个
  - "使用场景 1"
  - "使用场景 2"
tags:  # 可选，语义标签
  - tag1
  - tag2
output_targets:  # 必需，支持的输出去向
  - stdout
  - file
  # - clipboard
inputs:
  param1:
    type: string | number | boolean | array | object
    required: true | false
    default: "default value"  # 可选
    description: "参数说明"   # 可选
outputs:
  field1: string
  field2: array
version: "1.0.0"
dependencies: [recipe1, recipe2]  # 可选
---

# Recipe 完整文档

## 功能描述
...

## 使用方法
...

## 示例
...
```

**AI 元数据字段优先级**:
1. **P0（核心）**: `description`, `use_cases`, `output_targets` - AI 发现和选择 Recipe 的关键
2. **P1（增强）**: `tags` - 支持语义搜索和分类
3. **P2（传统）**: `inputs`, `outputs`, `dependencies` - 验证和执行必需

---

## 验证规则汇总

### 元数据验证（AI-first 优先）
1. **必需字段（P0）**: `name`, `type`, `runtime`, `version`, `description`, `use_cases`, `output_targets` 必须存在
2. **枚举值**:
   - `type` ∈ {atomic, workflow}
   - `runtime` ∈ {chrome-js, python, shell}
   - `output_targets` 元素 ∈ {stdout, file, clipboard}
3. **版本格式**: `version` 匹配正则 `^\d+\.\d+(\.\d+)?$`
4. **依赖检查**: `dependencies` 中的每个 Recipe 必须在注册表中存在
5. **AI 字段验证**:
   - `description` 长度 <= 200 字符
   - `use_cases` 至少包含 1 个元素
   - `output_targets` 至少包含 1 个有效值

### 文件验证
1. **文件存在性**: 脚本文件和元数据文件必须同时存在
2. **文件权限**: 脚本文件必须可读，Shell 脚本必须可执行
3. **名称一致性**: 元数据中的 `name` 必须与文件名（去扩展名）一致

### 输入参数验证
1. **必需参数**: `inputs` 中标记为 `required: true` 的参数必须提供
2. **类型检查**: 简单类型检查（string, number, boolean, array, object）
3. **默认值**: 未提供的参数使用 `default` 值（如定义）

### 输出结果验证
1. **JSON 格式**: Recipe 输出必须是合法的 JSON
2. **大小限制**: 输出 JSON 序列化后不超过 10MB
3. **结构验证**: 包含 `outputs` 定义的字段（可选，不强制）

---

## 状态转换

Recipe 本身无状态转换（静态实体），但 Recipe 执行有生命周期：

```text
[待执行] → [参数验证] → [脚本调用] → [结果解析] → [完成/失败]
   ↓            ↓             ↓            ↓
   ✓     验证成功/失败   执行成功/失败   解析成功/失败
```

**状态定义**:
- **待执行**: RecipeRunner.run() 被调用
- **参数验证**: 检查必需参数、类型
- **脚本调用**: subprocess.run() 执行脚本
- **结果解析**: 解析 stdout 为 JSON
- **完成**: 返回 RecipeExecutionResult(success=True)
- **失败**: 返回 RecipeExecutionResult(success=False, error=...)

---

## 扩展点

### 新增运行时支持
1. 继承 `RecipeExecutor` 抽象类
2. 实现 `execute(script, params)` 方法
3. 在 `RecipeRunner.executors` 字典中注册
4. 在元数据 `runtime` 枚举中添加新值

### 新增查找路径
1. 在 `RecipeRegistry.search_paths` 列表中添加路径
2. 更新 `source` 标签逻辑

### 新增验证规则
1. 在 `validate_metadata()` 函数中添加校验逻辑
2. 或升级到 Pydantic 模型（自动验证）

---

## 总结

Recipe 系统采用**文件系统驱动的 AI-first 元数据模型**，核心实体清晰分离：
- **RecipeMetadata**: 元数据定义（YAML，包含 AI 可理解字段）
- **Recipe**: 完整 Recipe 实体（元数据 + 脚本路径）
- **RecipeRegistry**: 全局索引和查找（支持 JSON 输出）
- **RecipeExecutor**: 语言无关的执行抽象
- **OutputHandler**: 统一的输出目标处理（stdout/file/clipboard）
- **RecipeExecutionResult**: 统一的结果封装（结构化错误）

**AI-first 设计核心**:
1. **元数据驱动**: AI 通过 `description`, `use_cases`, `tags` 理解 Recipe 能力
2. **输出形态声明**: AI 通过 `output_targets` 知道如何处理结果
3. **结构化输出**: 所有 CLI 命令支持 `--format json`，便于 AI 解析
4. **错误可理解**: 结构化错误让 AI 能分析失败原因并采取策略

所有验证规则明确，支持渐进式扩展（新增运行时、查找路径、输出目标）。
