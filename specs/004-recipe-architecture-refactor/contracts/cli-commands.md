# CLI Command Contracts: Recipe 系统

**Feature**: Recipe 系统架构重构
**Date**: 2025-11-20

## 概述

本文档定义 Frago Recipe 系统的所有 CLI 命令契约，包括命令格式、参数、输出格式和错误处理。

---

## 命令组: `frago recipe`

所有 Recipe 管理命令的父命令组。

### 通用选项

所有子命令继承的全局选项：

| 选项 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `--debug` | Flag | `false` | 启用调试模式，输出详细日志 |
| `--quiet` | Flag | `false` | 静默模式，仅输出关键信息 |
| `--help` | Flag | - | 显示帮助信息 |

---

## 命令 1: `frago init`

**描述**: 初始化用户级 Recipe 目录结构。

### 用法
```bash
uv run frago init [OPTIONS]
```

### 选项

| 选项 | 类型 | 必需 | 默认值 | 描述 |
|------|------|------|--------|------|
| `--force` | Flag | ❌ | `false` | 强制重新创建目录（覆盖已存在的） |

### 行为

1. 检查 `~/.frago/recipes/` 是否存在
2. 如未存在或 `--force`，创建以下目录：
   ```
   ~/.frago/
   └── recipes/
       ├── atomic/
       │   ├── chrome/
       │   └── system/
       └── workflows/
   ```
3. 输出成功消息

### 输出格式

**成功**:
```text
✓ Recipe 目录已初始化: /home/user/.frago/recipes
  - atomic/chrome/
  - atomic/system/
  - workflows/
```

**已存在（非 force）**:
```text
ℹ Recipe 目录已存在: /home/user/.frago/recipes
  使用 --force 选项强制重新创建
```

### 退出码

| 退出码 | 描述 |
|--------|------|
| `0` | 成功 |
| `1` | 权限不足或 I/O 错误 |

---

## 命令 2: `frago recipe list`

**描述**: 列出所有可用的 Recipe，标注来源。

### 用法
```bash
uv run frago recipe list [OPTIONS]
```

### 选项

| 选项 | 类型 | 必需 | 默认值 | 描述 |
|------|------|------|--------|------|
| `--source` | Choice | ❌ | `all` | 过滤来源：`project` / `user` / `example` / `all` |
| `--type` | Choice | ❌ | `all` | 过滤类型：`atomic` / `workflow` / `all` |
| `--format` | Choice | ❌ | `table` | 输出格式：`table` / `json` / `names` |

### 输出格式

**表格格式（`--format table`，默认）**:
```text
SOURCE   TYPE      NAME                                     RUNTIME    VERSION
──────────────────────────────────────────────────────────────────────────────
Project  workflow  custom_upwork_workflow                   python     1.0.0
User     atomic    upwork_extract_job_details_as_markdown   chrome-js  1.0.0
User     atomic    youtube_extract_video_transcript         chrome-js  1.2.0
Example  atomic    x_extract_tweet_with_comments            chrome-js  1.0.0
Example  atomic    test_inspect_tab                         chrome-js  1.0.0
```

**JSON 格式（`--format json`）**:
```json
[
  {
    "source": "Project",
    "type": "workflow",
    "name": "custom_upwork_workflow",
    "runtime": "python",
    "version": "1.0.0",
    "path": "/path/to/.frago/recipes/workflows/custom_upwork_workflow.py"
  },
  {
    "source": "User",
    "type": "atomic",
    "name": "upwork_extract_job_details_as_markdown",
    "runtime": "chrome-js",
    "version": "1.0.0",
    "path": "/home/user/.frago/recipes/atomic/chrome/upwork_extract_job_details_as_markdown.js"
  }
]
```

**仅名称格式（`--format names`）**:
```text
custom_upwork_workflow
upwork_extract_job_details_as_markdown
youtube_extract_video_transcript
x_extract_tweet_with_comments
test_inspect_tab
```

### 退出码

| 退出码 | 描述 |
|--------|------|
| `0` | 成功 |
| `1` | 扫描失败或 I/O 错误 |

---

## 命令 3: `frago recipe info`

**描述**: 显示指定 Recipe 的详细信息。

### 用法
```bash
uv run frago recipe info <NAME> [OPTIONS]
```

### 参数

| 参数 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `NAME` | String | ✅ | Recipe 名称 |

### 选项

| 选项 | 类型 | 必需 | 默认值 | 描述 |
|------|------|------|--------|------|
| `--format` | Choice | ❌ | `text` | 输出格式：`text` / `json` / `yaml` |

### 输出格式

**文本格式（`--format text`，默认）**:
```text
Recipe: upwork_extract_job_details_as_markdown
══════════════════════════════════════════════

基本信息
────────
名称:     upwork_extract_job_details_as_markdown
类型:     atomic
运行时:   chrome-js
版本:     1.0.0
来源:     User
路径:     /home/user/.frago/recipes/atomic/chrome/upwork_extract_job_details_as_markdown.js

输入参数
────────
• url (string, 必需): Upwork 职位详情页 URL

输出字段
────────
• title: string - 职位标题
• description: string - 职位描述
• skills: array - 技能列表

依赖
────
无

描述
────
从 Upwork 职位详情页提取完整信息并格式化为 Markdown
```

**JSON 格式（`--format json`）**:
```json
{
  "name": "upwork_extract_job_details_as_markdown",
  "type": "atomic",
  "runtime": "chrome-js",
  "version": "1.0.0",
  "source": "User",
  "script_path": "/home/user/.frago/recipes/atomic/chrome/upwork_extract_job_details_as_markdown.js",
  "metadata_path": "/home/user/.frago/recipes/atomic/chrome/upwork_extract_job_details_as_markdown.md",
  "inputs": {
    "url": {
      "type": "string",
      "required": true,
      "description": "Upwork 职位详情页 URL"
    }
  },
  "outputs": {
    "title": "string",
    "description": "string",
    "skills": "array"
  },
  "dependencies": [],
  "description": "从 Upwork 职位详情页提取完整信息并格式化为 Markdown"
}
```

### 错误情况

**Recipe 未找到**:
```text
错误: Recipe 'unknown_recipe' 未找到

已搜索路径:
  - /path/to/project/.frago/recipes
  - /home/user/.frago/recipes
  - /path/to/frago/examples

提示: 使用 'uv run frago recipe list' 查看所有可用 Recipe
```

### 退出码

| 退出码 | 描述 |
|--------|------|
| `0` | 成功 |
| `1` | Recipe 未找到 |
| `2` | 元数据解析失败 |

---

## 命令 4: `frago recipe run`

**描述**: 执行指定的 Recipe。

### 用法
```bash
uv run frago recipe run <NAME> [OPTIONS]
```

### 参数

| 参数 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `NAME` | String | ✅ | Recipe 名称 |

### 选项

| 选项 | 类型 | 必需 | 默认值 | 描述 |
|------|------|------|--------|------|
| `--params` | String | ❌ | `'{}'` | JSON 格式参数字符串 |
| `--params-file` | Path | ❌ | - | 从文件读取参数（JSON 格式） |
| `--output` | Path | ❌ | - | 将结果写入文件（不指定则输出到 stdout） |
| `--timeout` | Integer | ❌ | `300` | 执行超时时间（秒） |

### 输出格式

**成功执行**:
```json
{
  "success": true,
  "data": {
    "title": "Senior Python Developer",
    "description": "We are looking for...",
    "skills": ["Python", "Django", "PostgreSQL"]
  },
  "execution_time": 2.35,
  "recipe_name": "upwork_extract_job_details_as_markdown",
  "runtime": "chrome-js"
}
```

**执行失败**:
```json
{
  "success": false,
  "error": {
    "type": "RecipeExecutionError",
    "message": "Recipe execution failed with exit code 1",
    "recipe_name": "upwork_extract_job_details_as_markdown",
    "runtime": "chrome-js",
    "exit_code": 1,
    "stdout": "Navigated to https://www.upwork.com/...",
    "stderr": "Error: Element not found: .job-title"
  },
  "execution_time": 1.02,
  "recipe_name": "upwork_extract_job_details_as_markdown",
  "runtime": "chrome-js"
}
```

### 错误情况

**缺少必需参数**:
```text
错误: 缺少必需参数 'url'

Recipe 'upwork_extract_job_details_as_markdown' 需要以下参数:
  • url (string, 必需): Upwork 职位详情页 URL

示例:
  uv run frago recipe run upwork_extract_job_details_as_markdown \
    --params '{"url": "https://www.upwork.com/jobs/..."}'
```

**参数格式错误**:
```text
错误: 参数格式无效

提供的参数不是合法的 JSON:
  --params '{url: "https://..."}'
             ↑
  期望字符串使用双引号

正确格式:
  --params '{"url": "https://..."}'
```

**Recipe 执行超时**:
```text
错误: Recipe 执行超时

Recipe 'upwork_extract_job_details_as_markdown' 执行超过 300 秒

可能原因:
  - 网页加载缓慢
  - Recipe 逻辑中存在无限循环
  - 等待元素出现超时

建议:
  - 使用 --timeout 选项增加超时时间
  - 检查 Recipe 脚本逻辑
```

### 退出码

| 退出码 | 描述 |
|--------|------|
| `0` | 成功执行 |
| `1` | Recipe 未找到 |
| `2` | 参数验证失败 |
| `3` | Recipe 执行失败 |
| `4` | 超时 |

---

## 命令 5: `frago recipe copy`

**描述**: 将示例 Recipe 复制到用户目录供修改。

### 用法
```bash
uv run frago recipe copy <NAME> [OPTIONS]
```

### 参数

| 参数 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `NAME` | String | ✅ | 要复制的 Recipe 名称 |

### 选项

| 选项 | 类型 | 必需 | 默认值 | 描述 |
|------|------|------|--------|------|
| `--dest` | Choice | ❌ | 自动检测 | 目标位置：`user` / `project` |
| `--force` | Flag | ❌ | `false` | 覆盖已存在的文件 |

### 行为

1. 在示例目录查找指定 Recipe
2. 确定目标位置：
   - 如在项目目录（存在 `.frago/`），默认复制到项目级
   - 否则复制到用户级 `~/.frago/recipes/`
3. 复制脚本文件和元数据文件到对应子目录（`atomic/chrome/` 或 `workflows/`）
4. 输出成功消息

### 输出格式

**成功**:
```text
✓ Recipe 'upwork_extract_job_details_as_markdown' 已复制到用户目录

文件位置:
  脚本:   /home/user/.frago/recipes/atomic/chrome/upwork_extract_job_details_as_markdown.js
  元数据: /home/user/.frago/recipes/atomic/chrome/upwork_extract_job_details_as_markdown.md

现在可以修改这些文件以自定义 Recipe
```

**已存在（非 force）**:
```text
错误: Recipe 已存在于目标位置

文件:
  /home/user/.frago/recipes/atomic/chrome/upwork_extract_job_details_as_markdown.js
  /home/user/.frago/recipes/atomic/chrome/upwork_extract_job_details_as_markdown.md

使用 --force 选项覆盖现有文件
```

### 错误情况

**示例 Recipe 未找到**:
```text
错误: Recipe 'unknown_recipe' 在示例中未找到

可用的示例 Recipe:
  - upwork_extract_job_details_as_markdown
  - youtube_extract_video_transcript
  - x_extract_tweet_with_comments
  - test_inspect_tab

提示: 使用 'uv run frago recipe list --source example' 查看所有示例
```

### 退出码

| 退出码 | 描述 |
|--------|------|
| `0` | 成功 |
| `1` | Recipe 未找到 |
| `2` | 目标文件已存在（未使用 --force） |
| `3` | I/O 错误 |

---

## 命令 6: `frago recipe validate`（可选，未来增强）

**描述**: 验证 Recipe 元数据和脚本的有效性。

### 用法
```bash
uv run frago recipe validate <NAME_OR_PATH> [OPTIONS]
```

### 参数

| 参数 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `NAME_OR_PATH` | String | ✅ | Recipe 名称或脚本文件路径 |

### 选项

| 选项 | 类型 | 必需 | 默认值 | 描述 |
|------|------|------|--------|------|
| `--strict` | Flag | ❌ | `false` | 严格模式，检查所有可选字段 |

### 输出格式

**验证通过**:
```text
✓ Recipe 'upwork_extract_job_details_as_markdown' 验证通过

检查项:
  ✓ 元数据文件存在
  ✓ 脚本文件存在
  ✓ 必需字段完整
  ✓ 运行时类型有效
  ✓ 版本号格式正确
  ✓ 依赖 Recipe 存在
  ✓ 脚本文件可执行 (Shell only)
```

**验证失败**:
```text
✗ Recipe 'upwork_extract_job_details_as_markdown' 验证失败

错误:
  ✗ 缺少必需字段: 'runtime'
  ✗ 版本号格式无效: 'v1.0' (期望: '1.0' 或 '1.0.0')
  ⚠ 警告: 输出字段 'skills' 未在输出中定义类型

请修复以上错误后重新验证
```

### 退出码

| 退出码 | 描述 |
|--------|------|
| `0` | 验证通过 |
| `1` | 验证失败 |

---

## 错误处理规范

### 错误格式（stderr）

所有错误输出到 stderr，格式统一：

```text
错误: <简短错误描述>

<详细错误信息和上下文>

<建议或示例>
```

### 调试模式（--debug）

启用 `--debug` 时，输出额外信息：

```text
[DEBUG] RecipeRegistry: 扫描路径 /home/user/.frago/recipes
[DEBUG] RecipeRegistry: 找到 3 个 Recipe
[DEBUG] RecipeRunner: 选择执行器 ChromeJSExecutor
[DEBUG] ChromeJSExecutor: 执行命令: uv run frago exec-js ...
[DEBUG] ChromeJSExecutor: 退出码: 0
[DEBUG] RecipeRunner: 解析输出 JSON (2341 bytes)
```

---

## JSON Schema（Recipe 元数据）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Recipe Metadata",
  "type": "object",
  "required": ["name", "type", "runtime", "version"],
  "properties": {
    "name": {
      "type": "string",
      "pattern": "^[a-zA-Z0-9_-]+$",
      "minLength": 1,
      "description": "Recipe 唯一标识符"
    },
    "type": {
      "type": "string",
      "enum": ["atomic", "workflow"],
      "description": "Recipe 类型"
    },
    "runtime": {
      "type": "string",
      "enum": ["chrome-js", "python", "shell"],
      "description": "运行时类型"
    },
    "inputs": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "properties": {
          "type": {
            "type": "string",
            "enum": ["string", "number", "boolean", "array", "object"]
          },
          "required": { "type": "boolean" },
          "default": {},
          "description": { "type": "string" }
        },
        "required": ["type", "required"]
      },
      "description": "输入参数定义"
    },
    "outputs": {
      "type": "object",
      "additionalProperties": { "type": "string" },
      "description": "输出字段定义"
    },
    "version": {
      "type": "string",
      "pattern": "^\\d+\\.\\d+(\\.\\d+)?$",
      "description": "语义化版本号"
    },
    "dependencies": {
      "type": "array",
      "items": { "type": "string" },
      "description": "依赖的 Recipe 列表"
    },
    "description": {
      "type": "string",
      "maxLength": 200,
      "description": "简短描述"
    }
  }
}
```

---

## 总结

所有 CLI 命令遵循统一规范：
- **输入**: 参数 + 选项（统一命名风格）
- **输出**: JSON / 表格 / 文本（支持多格式）
- **错误**: stderr 输出，清晰的错误消息 + 建议
- **退出码**: 明确的语义（0=成功，1-4=不同错误类型）

CLI 契约确保用户友好、可脚本化、易于调试。
