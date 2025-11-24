# Implementation Plan: Run命令系统

**Branch**: `005-run-command-system` | **Date**: 2025-11-21 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/005-run-command-system/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

添加 run 命令系统，包含两个核心组件：

1. **CLI `uv run frago run` 子命令组**：管理运行实例的生命周期（init、set-context、log、screenshot）
2. **/frago.run slash 命令**：在 Claude Code 中执行 AI 主持的浏览器自动化任务

Run 实例采用**主题型**设计（如 "find-job-on-upwork"），作为持久化的**信息中心**，支持：
- Recipe 创建前的探索和调研
- 跨多个 Recipe 调用的上下文积累
- 构建复杂 Workflow 时的信息组织
- 一次性但复杂的任务执行

所有数据通过结构化日志（execution.jsonl）记录，包含 `action_type`（操作类型）和 `execution_method`（执行方法）字段，清晰追踪 AI 的执行痕迹。

## Technical Context

**Language/Version**: Python 3.9+ (pyproject.toml 已要求 >=3.9)
**Primary Dependencies**:
- click (CLI 框架，已用于现有 frago CLI)
- 现有 Frago CDP 客户端模块
- 现有 Recipe 系统模块
- pathlib, json, datetime (标准库)

**Storage**: 文件系统
- Run 实例目录：`runs/<topic-slug>/`
- 日志：JSONL 格式（`logs/execution.jsonl`）
- 配置：`.frago/current_run`（存储当前 run 上下文）
- 脚本文件：`scripts/*.{py,js,sh}`
- 截图：PNG 格式

**Testing**: pytest（项目现有测试框架）
- 单元测试：CLI 命令逻辑、日志格式化、路径解析
- 集成测试：完整 run 生命周期、日志写入、目录创建
- 契约测试：log 命令的 JSONL 输出格式验证

**Target Platform**: Linux/macOS（CLI 工具，跨平台）

**Project Type**: Single project（扩展现有 Frago CLI）

**Performance Goals**:
- log 命令执行 <50ms
- init 命令目录创建 <100ms
- 支持单个 run 实例积累 10k+ 日志条目

**Constraints**:
- 必须与现有 `uv run frago` CLI 集成
- 兼容现有 Recipe 系统和 CDP 命令
- 日志文件必须是标准 JSONL 格式（便于 jq/grep 处理）
- 截图文件名必须可排序（用序号前缀）

**Scale/Scope**:
- 预期同时管理 10-50 个 run 实例
- 单个 run 实例：数百个日志条目、数十个截图
- /frago.run slash 命令需集成到 Claude Code

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**状态**: ✅ PASS（项目暂无正式 Constitution 文件）

当前项目通过 CLAUDE.md 管理开发规范，主要约束：
- Python 使用 `uv run` 执行
- 代码风格遵循项目现有惯例
- Recipe 系统支持多运行时（chrome-js, python, shell）

本功能设计符合项目架构：
- 扩展现有 CLI 框架（不引入新架构）
- 使用文件系统存储（与 Recipe 系统一致）
- JSONL 日志格式（标准化、可处理）
- 无需额外依赖或复杂抽象

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/frago/
├── cli/
│   ├── commands.py           # 现有 CDP 命令（navigate, click, etc.）
│   ├── recipe_commands.py    # 现有 Recipe 命令（list, run, etc.）
│   └── run_commands.py       # 🆕 Run 子命令组（init, set-context, log, screenshot）
├── run/                      # 🆕 Run 系统核心模块
│   ├── __init__.py
│   ├── manager.py           # Run 实例管理（创建、查找、列表）
│   ├── logger.py            # 日志记录（JSONL 格式化、验证）
│   ├── context.py           # 上下文管理（读写 .frago/current_run）
│   ├── discovery.py         # Run 实例自动发现
│   └── models.py            # 数据模型（RunInstance, LogEntry）
├── cdp/                      # 现有 CDP 模块
├── recipes/                  # 现有 Recipe 系统
└── tools/

.claude/
└── commands/
    ├── frago.recipe.md      # 现有
    ├── frago.test.md        # 现有
    └── frago.run.md         # 🆕 AI 主持的任务执行 slash 命令

runs/                         # 🆕 Run 实例工作目录（git ignore）
└── <topic-slug>/
    ├── logs/
    │   └── execution.jsonl
    ├── screenshots/
    ├── scripts/
    └── outputs/

.frago/                      # 🆕 Frago 配置目录
└── current_run              # 当前 run 上下文

tests/
├── unit/
│   └── test_run/            # 🆕 Run 系统单元测试
│       ├── test_manager.py
│       ├── test_logger.py
│       └── test_context.py
├── integration/
│   └── test_run_lifecycle.py  # 🆕 完整生命周期测试
└── contract/
    └── test_log_format.py    # 🆕 JSONL 格式验证
```

**Structure Decision**: Single project 结构，扩展现有 `src/frago/` 模块。新增 `run/` 子模块处理核心逻辑，CLI 命令集成到 `cli/run_commands.py`。Run 实例数据存储在项目根目录的 `runs/` 目录（与现有 `projects/`、`examples/` 目录并列）。

## Complexity Tracking

**无违规项**：本功能设计简单，无需复杂抽象。
