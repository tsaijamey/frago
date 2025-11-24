# Implementation Plan: 技能自动化生成系统（简化架构）

**Branch**: `003-skill-automation` | **Date**: 2025-11-19 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/Users/chagee/Repos/Frago/specs/003-skill-automation/spec.md`

**Note**: 本计划基于2025-11-19的架构简化调整，删除了过度设计的探索引擎，采用Claude Code原生对话能力。

## Summary

通过 `/frago.recipe` 命令进入对话流程，用户逐步描述操作步骤，Claude Code（被prompt模板引导）使用frago的CDP原子命令实际执行每一步，记录操作历史和关键选择器，最后从对话历史中提取信息生成可复用的JavaScript配方脚本和配套知识文档。核心创新在于利用Claude Code本身作为智能探索引擎，无需构建复杂的状态管理系统。

## Technical Context

**Language/Version**: Python 3.9+（已有pyproject.toml要求 >=3.9）
**Primary Dependencies**:
- websocket-client（CDP通信，已有）
- click（CLI框架，已有）
- pydantic（数据验证，已有）
- 现有CDP命令模块（src/frago/cdp/commands/）

**Storage**: 文件系统存储
- 配方脚本：`src/frago/recipes/*.js`
- 知识文档：`src/frago/recipes/*.md`
- 无需数据库或复杂状态存储

**Testing**: pytest（已配置）
- 单元测试：配方生成逻辑、选择器策略、模板渲染
- 集成测试：完整的配方创建流程验证
- **无需Mock复杂的探索会话**：测试重点在代码生成质量

**Target Platform**: macOS开发环境 + Linux服务器（次要）
**Project Type**: 单项目（扩展现有Frago）

**Performance Goals**:
- 配方生成时间 <30秒（从对话完成到文件写入）
- 配方脚本执行成功率 >90%（相同页面条件）

**Constraints**:
- 配方脚本大小 50-200行（保持可读性）
- Prompt模板引导对话，无需独立探索引擎类
- 从Claude Code对话历史提取信息，无需ExplorationSession状态管理

**Scale/Scope**:
- 预期配方库规模：20-100个配方
- 扁平目录结构，通过描述性文件名组织

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**注**: 项目暂无正式章程文件（.specify/memory/constitution.md为空模板），以下检查基于软件开发通用原则。

### 简洁性原则
- ✅ **通过**: 删除了过度设计的RecipeExplorer类和ExplorationSession状态管理
- ✅ **通过**: 利用Claude Code原生对话能力，无需构建独立智能系统
- ✅ **通过**: 保留核心价值组件：Selector策略、模板系统、配方库管理

### 独立性与可测试性
- ✅ **通过**: 配方脚本设计为独立可执行单元
- ✅ **通过**: 代码生成器可独立测试（输入=对话历史，输出=JavaScript代码）
- ✅ **通过**: 选择器策略和模板系统已有完整单元测试覆盖

### 可维护性
- ✅ **通过**: Prompt模板清晰易维护
- ✅ **通过**: 标准化知识文档确保长期可读性
- ✅ **通过**: 从对话提取信息的逻辑简单直接

### 性能与规模
- ✅ **通过**: 文件系统存储适合20-100个配方
- ✅ **通过**: 无复杂状态管理开销
- ✅ **通过**: 性能目标合理可测量

### 用户体验
- ✅ **通过**: 自然对话界面，用户无需学习复杂命令
- ✅ **通过**: Prompt引导确保流程清晰
- ✅ **通过**: 实时CDP执行提供即时反馈

**结论**: ✅ 简化后的架构全部通过，可进入Phase 0研究阶段

## Project Structure

### Documentation (this feature)

```text
specs/003-skill-automation/
├── plan.md              # 本文件 (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   ├── recipe.schema.json
│   ├── selector.schema.json
│   └── knowledge_document.schema.json
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/frago/
├── recipes/                    # 【已创建】配方库（扁平目录）
│   ├── *.js                   # 可执行配方脚本
│   └── *.md                   # 配方知识文档
├── cli/                       # 【扩展】CLI命令
│   ├── main.py               # 主入口（已有）
│   ├── commands.py           # 现有CDP命令（已有）
│   └── recipe_commands.py    # 【新增】配方管理命令（简化版）
├── cdp/                       # 【复用】CDP核心模块（已有）
│   ├── client.py
│   ├── session.py
│   └── commands/
│       ├── dom.py            # 【复用】DOM查询
│       ├── runtime.py        # 【复用】JavaScript执行
│       ├── screenshot.py     # 【复用】截图
│       └── page.py           # 【复用】页面导航
└── recipes/                   # 【已创建】配方库（扁平目录）
    ├── *.js                   # Claude Code直接写入的可执行配方脚本
    └── *.md                   # Claude Code直接写入的配方知识文档
└── tools/                     # 【复用】辅助工具（已有）

tests/
├── unit/                      # 【已有】单元测试
│   └── recipe/               # 【已完成部分】
│       ├── test_models.py    # 【已完成，需调整】
│       ├── test_selector.py  # 【已完成】
│       ├── test_generator.py # 【需重写】
│       └── test_library.py   # 【新增】
└── integration/               # 【新增】集成测试
    └── recipe/
        └── test_recipe_creation.py  # 完整创建流程

.claude/commands/              # Claude Code命令配置
└── frago_recipe.md          # 【需创建】/frago.recipe prompt模板
```

**Structure Decision**:
- 采用**单项目结构**（Option 1），扩展现有Frago项目
- **完全删除 `src/frago/recipe/` Python模块**：不需要Python代码来生成代码
- 保留 `src/frago/recipes/` 扁平目录存储Claude Code生成的配方和文档
- 复用现有CDP模块，无需重复实现
- **核心组件**：`.claude/commands/frago_recipe.md` prompt模板教会Claude Code如何创建配方

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

**无违规项** - 简化后的架构消除了所有复杂性问题

## Post-Design Constitution Re-check

**阶段**: Phase 1设计完成后重新评估
**日期**: 待定（待research.md和data-model.md生成后）

### 待验证项
- ✅ 从对话历史提取信息的逻辑是否足够简单
- ✅ Prompt模板设计是否清晰易维护
- ✅ 简化后的数据模型是否满足需求

**下一步**: 进入Phase 0研究阶段，生成research.md
