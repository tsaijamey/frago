# Implementation Plan: 技能自动化生成系统

**Branch**: `003-skill-automation` | **Date**: 2025-11-18 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/home/yammi/repos/AuViMa/specs/003-skill-automation/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

实现一个通过自然语言指令生成可复用浏览器操作配方的系统。用户通过 `/auvima.recipe` 命令提供操作描述，Claude Code与Chrome CDP交互进行实际探索，理解操作流程后生成JavaScript配方脚本和配套知识文档。配方脚本保存在 `src/auvima/recipes/` 扁平目录中，文件名遵循"平台前缀_功能描述"格式（如 `youtube_extract_subtitles.js`），每个脚本配有包含6个标准章节的Markdown文档。系统支持配方迭代更新，版本历史记录在知识文档的"更新历史"章节。探索过程采用交互式引导，当无法定位元素时暂停并实时询问用户，确保生成的配方准确可用。

## Technical Context

**Language/Version**: Python 3.9+（已有pyproject.toml要求 >=3.9）
**Primary Dependencies**:
- websocket-client（CDP通信）
- click（CLI框架）
- pydantic（数据验证）
- 现有CDP命令模块（src/auvima/cdp/commands/）
- **新增需求**:
  - NEEDS CLARIFICATION - JavaScript解析和生成库（如果需要语法分析）
  - NEEDS CLARIFICATION - DOM选择器优化策略（选择哪些属性作为稳定选择器）

**Storage**: 文件系统存储
- 配方脚本：`src/auvima/recipes/*.js`
- 知识文档：`src/auvima/recipes/*.md`
- 无数据库，使用文件系统作为配方库

**Testing**: pytest（已配置）
- 单元测试：配方生成逻辑、文档模板渲染
- 集成测试：CDP探索流程、配方执行验证
- **需要新增**: 配方库测试（列出、搜索、验证配方完整性）

**Target Platform**: Linux服务器（主要）+ 跨平台CLI
**Project Type**: 单项目（现有AuViMa单体结构）

**Performance Goals**:
- 探索过程响应时间 <5秒/步（CDP操作）
- 配方生成时间 <30秒（从探索完成到文件写入）
- 配方执行时间因场景而异（无统一目标）

**Constraints**:
- 配方脚本大小 50-200行（保持可读性）
- 交互式澄清最多3次询问（避免用户疲劳）
- 配方必须独立可执行（无外部依赖配方）
- 生成的JavaScript必须能在CDP Runtime环境执行（浏览器上下文）

**Scale/Scope**:
- 预期配方库规模：20-100个配方
- 单个配方适用场景：单一网站/平台的特定操作
- 知识文档标准化：6章节固定结构
- 配方命名空间：扁平目录，通过描述性文件名区分

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**注**: 项目暂无正式章程文件（.specify/memory/constitution.md为空模板），以下检查基于软件开发通用原则。

### 简洁性原则
- ✅ **通过**: 使用现有CDP基础设施，无新增外部服务或数据库
- ✅ **通过**: 扁平目录结构，避免过度工程化
- ⚠️ **需要论证**: 是否需要引入JavaScript解析库（待研究阶段确认）

### 独立性与可测试性
- ✅ **通过**: 配方脚本设计为独立可执行单元
- ✅ **通过**: 使用现有pytest框架，无需新测试工具
- ✅ **通过**: 配方生成逻辑可独立单元测试

### 可维护性
- ✅ **通过**: 标准化知识文档（6章节结构）确保长期可维护
- ✅ **通过**: 版本历史机制（更新历史章节）便于追踪变更
- ✅ **通过**: 描述性文件命名便于人类和AI理解

### 性能与规模
- ✅ **通过**: 文件系统存储适合20-100个配方规模
- ✅ **通过**: 无复杂查询需求，扁平目录足够
- ✅ **通过**: 性能约束合理（<5秒/步探索，<30秒生成）

### 用户体验
- ✅ **通过**: 交互式引导降低用户学习成本
- ✅ **通过**: 最多3次澄清询问避免疲劳
- ✅ **通过**: 配方执行失败时提供清晰错误信息

**结论**: ✅ 通过关卡，可进入Phase 0研究阶段

## Project Structure

### Documentation (this feature)

```text
specs/003-skill-automation/
├── plan.md              # 本文件 (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   ├── recipe_script.schema.json      # 配方脚本结构规范
│   ├── knowledge_doc.schema.json      # 知识文档结构规范
│   └── exploration_session.schema.json # 探索会话数据格式
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/auvima/
├── recipes/                    # 【新增】配方库（扁平目录）
│   ├── *.js                   # 可执行配方脚本
│   └── *.md                   # 配方知识文档
├── cli/                       # 【扩展】CLI命令
│   ├── main.py               # 主入口（已有）
│   ├── commands.py           # 现有CDP命令（已有）
│   └── recipe_commands.py    # 【新增】配方管理命令
├── cdp/                       # 【复用】CDP核心模块（已有）
│   ├── client.py
│   ├── session.py
│   └── commands/
│       ├── dom.py            # 【复用】DOM查询
│       ├── runtime.py        # 【复用】JavaScript执行
│       ├── screenshot.py     # 【复用】截图
│       └── page.py           # 【复用】页面导航
├── recipe/                    # 【新增】配方系统核心模块
│   ├── __init__.py
│   ├── explorer.py           # 交互式探索引擎
│   ├── generator.py          # 配方脚本生成器
│   ├── knowledge.py          # 知识文档生成器
│   ├── library.py            # 配方库管理
│   ├── templates.py          # JavaScript和Markdown模板
│   └── selector.py           # DOM选择器优化策略
└── tools/                     # 【复用】辅助工具（已有）

tests/
├── unit/                      # 【扩展】单元测试
│   ├── recipe/               # 【新增】配方系统测试
│   │   ├── test_explorer.py
│   │   ├── test_generator.py
│   │   ├── test_knowledge.py
│   │   └── test_library.py
│   └── cdp/                  # 现有CDP测试（已有）
└── integration/               # 【新增】集成测试
    └── recipe/
        ├── test_recipe_creation.py      # 完整创建流程
        ├── test_recipe_update.py        # 更新流程
        └── test_recipe_execution.py     # 配方执行验证

.claude/commands/              # Claude Code命令
└── auvima_recipe.md          # 【已有】/auvima.recipe命令配置
```

**Structure Decision**:
- 采用**单项目结构**（Option 1），扩展现有AuViMa项目
- 新增 `src/auvima/recipe/` 模块包含配方系统核心逻辑
- 新增 `src/auvima/recipes/` 扁平目录存储生成的配方和文档
- 复用现有CDP模块，无需重复实现浏览器交互
- 在现有CLI结构中新增 `recipe_commands.py` 实现配方管理命令
- 测试结构遵循现有pytest配置，新增recipe相关测试目录

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

**无违规项需要论证** - Constitution Check全部通过

---

## Post-Design Constitution Re-check

**阶段**: Phase 1设计完成后重新评估
**日期**: 2025-11-18

### 设计后验证

✅ **简洁性原则** - 保持通过
- 设计使用模板字符串生成JavaScript，无需引入AST库（research.md §1）
- 数据模型简洁，6个核心实体，关系清晰（data-model.md）
- 无新增外部服务依赖

✅ **独立性与可测试性** - 保持通过
- 每个模块职责明确：explorer/generator/knowledge/library/selector
- Pydantic模型提供数据验证（data-model.md §验证规范）
- JSON Schema契约支持自动化测试（contracts/）

✅ **可维护性** - 保持通过
- 标准化6章节知识文档模板（research.md §5）
- 多层选择器降级策略确保长期稳定性（research.md §2）
- 版本历史机制便于追踪变更

✅ **性能与规模** - 保持通过
- 文件系统存储 + 可选元数据索引（data-model.md §数据存储策略）
- 性能目标合理且可测量（<5秒/步，<30秒生成）

✅ **用户体验** - 保持通过
- 三阶段交互流程（需求理解 → 元素定位 → 结果验证）
- 最多3次交互限制在数据模型中强制执行（ExplorationSession.interaction_count <= 3）

### 新发现的考虑点

**配方库索引文件**（`.index.json`）:
- **决策**: 设计为可选特性
- **理由**: 在配方库规模 <20 时，扫描文件系统足够快；规模达到50+时再启用索引
- **符合章程**: 渐进式优化，避免过早优化

**探索会话序列化**:
- **决策**: 存储为临时JSON文件（`/tmp/explorations/`）
- **理由**: 仅用于调试和回放，非核心功能数据
- **符合章程**: 简单文件存储，无需数据库

**结论**: ✅ 设计后章程检查全部通过，无新增违规项
