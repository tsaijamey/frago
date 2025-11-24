# Frago Development Guidelines

Auto-generated from all feature plans. Last updated: 2025-11-15

## Active Technologies
- Python 3.9+（已有pyproject.toml要求 >=3.9） (003-skill-automation)
- 文件系统存储 (003-skill-automation)
- Python 3.9+（pyproject.toml 已要求 >=3.9） (004-recipe-architecture-refactor)
- 文件系统（Recipe 脚本 .js/.py/.sh + 元数据 .md，无数据库） (004-recipe-architecture-refactor)
- Python 3.9+ (pyproject.toml 已要求 >=3.9) (005-run-command-system)

- Bash/Shell Script (POSIX兼容) + websocat工具，Chrome DevTools Protocol (001-standardize-cdp-scripts)

## Project Structure

```text
src/
tests/
```

## Commands

# Add commands for Bash/Shell Script (POSIX兼容)

## Code Style

Bash/Shell Script (POSIX兼容): Follow standard conventions

## Recent Changes
- 005-run-command-system: Added Python 3.9+ (pyproject.toml 已要求 >=3.9)
- 004-recipe-architecture-refactor: Added Python 3.9+（pyproject.toml 已要求 >=3.9）
- 004-recipe-architecture-refactor: Added Python 3.9+（pyproject.toml 已要求 >=3.9）


<!-- MANUAL ADDITIONS START -->

## 核心使用方式

### Chrome CDP操作（Python CLI）

**正确方式**: 使用 `uv run frago <command>`

```bash
# 导航网页
uv run frago navigate <url>

# 点击元素
uv run frago click <selector>

# 执行JavaScript
uv run frago exec-js <expression>

# 截图
uv run frago screenshot <output_file>

# 其他命令
uv run frago --help
```

**不要使用**: ~~`./scripts/share/cdp_*.sh`~~ （已废弃删除）

### Recipe 系统（AI-First 设计）

从004-recipe-architecture-refactor开始，Frago采用元数据驱动的Recipe架构，支持多运行时和Workflow编排。

#### 核心特性

- **三级优先级**: Project (.frago/recipes/) > User (~/.frago/recipes/) > Example (examples/)
- **多运行时支持**: chrome-js, python, shell
- **元数据驱动**: YAML frontmatter定义输入/输出/依赖
- **Workflow编排**: Python Recipe可调用多个atomic Recipe
- **AI-First**: JSON格式输出，供AI agent发现和使用

#### Recipe 管理命令

**列出所有 Recipe**:
```bash
uv run frago recipe list                    # 表格格式
uv run frago recipe list --format json      # JSON格式（AI使用）
uv run frago recipe list --source project   # 仅项目级
```

**查看 Recipe 详情**:
```bash
uv run frago recipe info <recipe_name>
uv run frago recipe info <name> --format json  # JSON格式
```

**执行 Recipe**:
```bash
uv run frago recipe run <recipe_name> \
  --params '{"url": "https://..."}' \
  --output-file result.json
```

**复制示例到用户级**:
```bash
uv run frago recipe copy upwork_extract_job_details_as_markdown
```

#### Recipe 结构

**目录组织**:
```
.frago/recipes/          # 项目级（优先级最高）
~/.frago/recipes/        # 用户级
examples/                 # 示例级
  ├── atomic/
  │   ├── chrome/         # Chrome CDP 操作
  │   └── system/         # 系统操作
  └── workflows/          # 编排多个 Recipe
```

**元数据格式** (YAML frontmatter):
```yaml
---
name: recipe_name
type: atomic | workflow
runtime: chrome-js | python | shell
description: "Recipe描述"
use_cases:
  - "用例1"
  - "用例2"
output_targets:
  - stdout
  - file
  - clipboard
inputs:
  param_name:
    type: string | number | boolean | array | object
    required: true
    description: "参数描述"
outputs:
  result_field: string
dependencies:
  - dependency_recipe_name
version: "1.0.0"
---
```

#### Claude Code集成

**使用 /frago.recipe 命令创建新Recipe**:
```
/frago.recipe create "批量提取Upwork职位"
```

**使用 /frago.test 命令测试Recipe**:
```
/frago.test youtube_extract_video_transcript
```

### 项目结构

```
src/frago/
├── cdp/                  # CDP核心模块
│   ├── commands/         # CDP命令实现
│   ├── client.py         # CDP客户端
│   └── session.py        # CDP会话管理
├── cli/                  # 命令行接口
│   ├── commands.py       # CDP命令CLI
│   └── recipe_commands.py  # Recipe命令CLI
├── recipes/              # Recipe系统核心（004重构）
│   ├── metadata.py       # 元数据解析和验证
│   ├── registry.py       # Recipe注册表
│   ├── runner.py         # Recipe执行器
│   ├── output_handler.py # 输出处理（stdout/file/clipboard）
│   └── exceptions.py     # Recipe异常
└── tools/                # 辅助工具

examples/                 # 示例级 Recipe
├── atomic/chrome/        # Chrome CDP操作示例
├── atomic/system/        # 系统操作示例
└── workflows/            # Workflow示例

.claude/                  # Claude Code配置
├── commands/             # 自定义slash命令
└── skills/               # 项目级skills

projects/                 # Run实例工作目录（持久化任务上下文）
```

<!-- MANUAL ADDITIONS END -->
