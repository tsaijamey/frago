# Implementation Plan: Recipe 系统架构重构（AI-First）

**Branch**: `004-recipe-architecture-refactor` | **Date**: 2025-11-20 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/004-recipe-architecture-refactor/spec.md`

**Note**: 本计划基于 AI-first 设计理念重新生成，核心使用者是 Claude Code AI Agent。

## Summary

重构 Frago 的 Recipe 系统架构，核心目标是**让 AI Agent（Claude Code）能够自主创建、发现、选择和执行 Recipe**。实现代码与资源分离、支持多语言 Recipe（JavaScript、Python、Shell）、通过元数据驱动的方式让 AI 理解每个 Recipe 的能力和输出形态。Recipe 系统设计为"AI 可调度的工具集"，而非传统的"人类操作的 CLI 工具"。

技术方法：
1. **元数据增强**：Recipe 元数据包含 `description`, `use_cases`, `tags`, `output_targets` 等 AI 可理解的字段
2. **混合接口**：AI 通过 Bash 工具调用 CLI 命令，人类也可手动执行（次要场景）
3. **AI 生成 Workflow**：扩展 `/frago.recipe` 命令，支持 AI 根据自然语言描述自动生成编排 Recipe
4. **输出形态声明**：Recipe 明确声明支持的输出去向（stdout/file/clipboard），AI 可根据任务需求选择

## Technical Context

**Language/Version**: Python 3.9+（pyproject.toml 已要求 >=3.9）

**Primary Dependencies**:
  - `click`（CLI 框架，已在使用）
  - `pyyaml`（解析 YAML frontmatter，需新增）
  - `pathlib`（路径处理，标准库）
  - `pyperclip`（可选，用于剪贴板操作支持）

**Storage**: 文件系统（Recipe 脚本 .js/.py/.sh + 元数据 .md，无数据库）

**Testing**: pytest（现有测试框架）

**Target Platform**: Linux（主要），macOS（次要支持），Windows（未全面测试）

**Project Type**: 单一 Python 包项目（CLI 工具 + 库）

**Performance Goals**:
  - Recipe 注册表扫描 50+ recipes < 1 秒
  - Recipe 执行延迟 < 200ms（不含 Recipe 本身耗时）
  - `recipe list --format json` 响应时间 < 500ms（AI 查询场景）

**Constraints**:
  - 必须向后兼容现有 `uv run frago exec-js` 命令
  - Recipe 输出 JSON 大小限制 10MB（避免内存问题）
  - 元数据文件必须是合法的 Markdown + YAML frontmatter（便于人类阅读和 AI 解析）
  - **AI-first 约束**：所有 CLI 输出必须是结构化的 JSON（`--format json`）或清晰的表格，便于 AI 解析

**Scale/Scope**:
  - 支持至少 50 个 Recipe 并发管理
  - 三级查找路径（项目/用户/示例）
  - 现有 5 个 Recipe 需迁移到新架构
  - **AI 使用场景**：每个用户会话可能涉及 10-20 次 Recipe 查询/执行

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**当前状态**: ⚠️ 项目尚未定义正式章程（`.specify/memory/constitution.md` 为模板状态）

**基于 CLAUDE.md 和 AI-first 原则的隐式检查**:

- ✅ **CLI 优先**: 所有功能通过 `uv run frago` CLI 暴露（AI 通过 Bash 工具调用）
- ✅ **语言统一**: Python 作为主实现语言
- ✅ **文件系统存储**: Recipe 作为文件管理，符合现有模式
- ✅ **AI 可理解性**: 元数据驱动，结构化输出（JSON），语义描述字段
- ⚠️ **测试覆盖**: 需在实施阶段补充测试用例（特别是 AI 使用场景的集成测试）

**建议**: 在 Phase 1 后重新评估是否需要正式定义项目章程

## Project Structure

### Documentation (this feature)

```text
specs/004-recipe-architecture-refactor/
├── plan.md              # 本文件（AI-first 重构计划）
├── research.md          # Phase 0：技术决策研究（AI 集成重点）
├── data-model.md        # Phase 1：数据模型（包含 AI 元数据字段）
├── quickstart.md        # Phase 1：快速开始（AI 使用场景为主）
├── contracts/           # Phase 1：CLI 命令契约（强调 JSON 输出）
│   └── cli-commands.md
└── tasks.md             # Phase 2：任务列表（由 /speckit.tasks 生成）
```

### Source Code (repository root)

```text
# Python 包代码（打包到 wheel）
src/frago/
├── cdp/                      # 现有 CDP 核心模块（不变）
│   └── commands/
├── cli/                      # 现有 CLI 接口（扩展）
│   ├── main.py              # 主 CLI 入口（扩展新命令组）
│   ├── commands.py          # 现有命令（保持）
│   └── recipe_commands.py   # 🆕 Recipe 相关命令（list, info, run, copy）
├── recipes/                  # 🆕 Recipe 引擎代码（重构重点）
│   ├── __init__.py          # 导出 RecipeRunner, RecipeRegistry
│   ├── runner.py            # RecipeRunner 核心执行器
│   ├── registry.py          # RecipeRegistry 注册表（支持 JSON 输出）
│   ├── metadata.py          # RecipeMetadata 元数据解析（扩展 AI 字段）
│   ├── output_handler.py    # 🆕 OutputHandler 输出去向处理（stdout/file/clipboard）
│   └── exceptions.py        # Recipe 专用异常类
└── tools/                    # 现有工具模块（不变）

# 官方示例 Recipe（不打包，或作为 data files）
examples/
├── atomic/                   # 原子 Recipe
│   ├── chrome/              # Chrome CDP 操作（现有 recipes 迁移至此）
│   │   ├── upwork_extract_job_details_as_markdown.js
│   │   ├── upwork_extract_job_details_as_markdown.md  # 🔄 元数据更新（添加 AI 字段）
│   │   ├── youtube_extract_video_transcript.js
│   │   ├── youtube_extract_video_transcript.md
│   │   ├── x_extract_tweet_with_comments.js
│   │   ├── x_extract_tweet_with_comments.md
│   │   └── test_inspect_tab.js/md
│   └── system/              # 🆕 系统操作示例
│       ├── clipboard_read.py
│       ├── clipboard_read.md
│       ├── file_copy.sh
│       └── file_copy.md
└── workflows/               # 🆕 编排 Recipe 示例（AI 生成）
    ├── upwork_batch_extract.py
    └── upwork_batch_extract.md

# 测试
tests/
├── unit/
│   ├── test_recipe_runner.py       # 🆕 RecipeRunner 单元测试
│   ├── test_recipe_registry.py     # 🆕 RecipeRegistry 单元测试
│   ├── test_metadata_parser.py     # 🆕 元数据解析测试（含 AI 字段）
│   └── test_output_handler.py      # 🆕 输出处理器测试
├── integration/
│   ├── test_recipe_execution.py    # 🆕 Recipe 执行集成测试
│   ├── test_ai_workflow.py         # 🆕 AI 使用场景集成测试（模拟 AI 调用）
│   └── test_cli_recipe_commands.py # 🆕 CLI 命令集成测试（JSON 输出验证）
└── fixtures/
    └── recipes/                     # 🆕 测试用 Recipe 样本
        ├── test_simple.js
        ├── test_simple.md
        ├── test_python.py
        └── test_python.md

# Claude Code 命令配置（AI 集成关键）
.claude/commands/
├── frago-recipe.md         # 🔄 更新 /frago.recipe 命令（支持生成 Workflow）
└── ...                      # 其他命令

# 用户级 Recipe 目录（运行时创建，不在仓库）
~/.frago/
└── recipes/
    ├── atomic/
    │   ├── chrome/
    │   └── system/
    └── workflows/

# 项目级 Recipe 目录（可选，不在仓库，用户项目中创建）
.frago/
└── recipes/
    └── workflows/
```

**Structure Decision**: 采用单一 Python 包项目结构。核心变更：
1. `src/frago/recipes/` 从存放 Recipe 脚本改为存放引擎代码
2. 新增 `output_handler.py` 模块处理多种输出去向
3. `metadata.py` 扩展支持 AI 可理解字段（`description`, `use_cases`, `tags`, `output_targets`）
4. 测试新增 `test_ai_workflow.py` 模拟 AI Agent 使用场景
5. CLI 命令强制支持 `--format json` 选项（AI 友好）

## Complexity Tracking

**无需填写** - 当前架构重构符合单一 Python 包项目模式，AI-first 设计增加了元数据字段和输出处理逻辑，但未引入不必要的复杂性。
