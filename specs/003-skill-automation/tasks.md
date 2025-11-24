# Tasks: 技能自动化生成系统（简化架构）

**Input**: Design documents from `/specs/003-skill-automation/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**关键架构变更**: 本任务列表基于2025-11-19的架构简化，删除了RecipeExplorer、ExplorationSession等过度设计组件，采用对话历史驱动的配方生成方式。

**Tests**: 已有单元测试覆盖（51个测试通过），Phase 3将添加集成测试。

**Organization**: 任务按用户故事组织，确保每个故事可独立实现和测试。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 任务所属的用户故事（US1, US2, US3）
- 包含确切的文件路径

## Path Conventions

单项目结构（扩展现有Frago项目）：
- Source: `src/frago/`
- Tests: `tests/`
- Recipes: `src/frago/recipes/`
- Commands: `.claude/commands/`

---

## ~~Phase 1-2: 基础设施~~（已删除）

**状态**: ❌ 原Phase 1-2的Python代码和51个测试已全部删除

**原因**: 架构简化 - Claude Code不需要Python代码来生成代码

**已删除的任务**:
- ~~T001-T009~~（创建Python模块、数据模型、选择器策略、模板系统）

**保留的成果**:
- ✅ `src/frago/recipes/` 目录（空目录，等待Claude Code写入配方）
- ✅ 选择器优先级规则（已整合到`.claude/commands/frago_recipe.md`）

---

## Phase 1: User Story 1 - 通过对话创建配方脚本 (Priority: P1) 🎯 MVP

**Goal**: 用户通过 `/frago.recipe` 命令进入对话流程，逐步描述操作步骤，Claude Code执行CDP命令，最后使用Write工具直接生成可执行的JavaScript配方脚本和配套知识文档。

**Independent Test**:
1. 执行 `/frago.recipe "提取YouTube视频字幕"`
2. 在对话中描述步骤（点击作者声明 → 点击内容转文字 → 提取文本）
3. Claude Code实际执行 `uv run frago click` 等命令
4. 验证Claude Code使用Write工具生成的 `youtube_extract_transcript.js` 和 `.md` 文件存在
5. 执行 `uv run frago exec-js recipes/youtube_extract_transcript.js` 验证脚本可运行

### Implementation for User Story 1

- [x] T001 [US1] 创建 `/frago.recipe` prompt模板在 `.claude/commands/frago_recipe.md`（完整版，包含选择器优先级规则表格、JavaScript模板示例、6章节文档格式）
- [x] ~~T002-T007~~（已删除的Python代码生成任务）

**Checkpoint**: ✅ Prompt模板已完成 - Claude Code已能通过对话创建配方

---

## ~~Phase 2: User Story 2~~（已合并到US1）

**状态**: ✅ 知识文档生成已整合到prompt模板中

**说明**: Prompt模板明确指示Claude Code在生成配方脚本(.js)的同时，使用Write工具创建配套的知识文档(.md)，包含6个标准章节。

**无需独立任务** - Claude Code在一次对话中完成脚本和文档的生成。

---

## Phase 2: User Story 3 - 配方迭代更新 (Priority: P2)

**Goal**: 当配方脚本因目标网站改版失效时，用户可通过 `/frago.recipe update <配方名> "原因"` 重新探索页面，Claude Code覆盖原文件并更新历史记录。

**Independent Test**:
1. 执行 `/frago.recipe update youtube_extract_transcript "字幕按钮选择器失效"`
2. Claude Code使用Read工具读取现有.js和.md文件
3. 在对话中描述新的操作步骤
4. 验证Claude Code覆盖原.js文件（文件名不变）
5. 验证.md文档的"更新历史"章节追加了新记录
6. 验证新脚本可成功执行

### Implementation for User Story 3

- [x] T002 [US3] 扩展prompt模板支持更新模式在 `.claude/commands/frago_recipe.md`（包含Read现有文件、版本号+1、追加历史记录的指令）

**Checkpoint**: ✅ 更新模式已整合到prompt模板中 - Claude Code可更新现有配方

---

## Phase 3: 配方库管理功能 (Priority: P3)

**Goal**: 提供配方列表查看功能，方便用户管理和使用已生成的配方库。

**Independent Test**:
1. 执行 `/frago.recipe list` 验证显示所有配方列表
2. 验证列表按平台分组，包含配方名称、描述、版本号
3. 验证空配方库时的友好提示

### Implementation

- [x] T003 [P3] 扩展prompt模板支持列出模式在 `.claude/commands/frago_recipe.md`（包含扫描目录、解析头部注释、按平台分组显示的指令）

**Checkpoint**: ✅ 列出模式已整合到prompt模板中 - Claude Code可列出所有配方

---

## Phase 4: 验证和完善 (质量保证)

**Purpose**: 端到端验证配方系统，优化prompt模板

### 实施任务

- [ ] T004 [P] 手动测试：创建YouTube字幕提取配方（验证完整对话流程）
- [ ] T005 [P] 手动测试：创建GitHub仓库信息提取配方（验证不同平台适配性）
- [ ] T006 手动测试：更新现有配方（验证版本管理和历史记录）
- [ ] T007 手动测试：列出配方库（验证扫描和显示逻辑）
- [ ] T008 [P] 优化prompt模板的引导语言（提高对话体验）
- [ ] T009 [P] 完善prompt中的错误处理指令（应对CDP命令失败）
- [ ] T010 [P] 更新CLAUDE.md项目文档，添加Recipes系统使用说明
- [ ] T011 验证生成的配方脚本执行成功率 >90%（在相同页面条件下）

**Checkpoint**: 系统经过验证，生产就绪

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (US1 - 创建配方)**: ✅ 已完成 - Prompt模板已创建
- **Phase 2 (US3 - 更新配方)**: ✅ 已完成 - 更新模式已整合到prompt
- **Phase 3 (配方库管理)**: ✅ 已完成 - 列出模式已整合到prompt
- **Phase 4 (验证和完善)**: 进行中 - 依赖Phase 1-3完成

### User Story Dependencies

- **User Story 1 (P1)**: 在Foundational之后可开始 - 无其他故事依赖
- **User Story 2 (P2)**: 在Foundational之后可开始 - 与US1集成但可并行开发（知识文档生成是US1的自然扩展）
- **User Story 3 (P3)**: 依赖US1和US2 - 需要现有配方和文档才能更新

### Within Each User Story

- **US1**: Prompt模板 [P] → 对话解析器 [P] → 代码生成器 → 知识文档生成器 → CLI集成 → 验证逻辑
- **US2**: 章节填充 [P] 和 脆弱选择器警告 [P] → 更新历史 → 测试
- **US3**: 配方加载器 [P] 和 Prompt扩展 [P] → 版本增量 → 历史追加 → CLI命令 → 集成测试

### Parallel Opportunities

- **Phase 1-2**: ✅ 已完成 - T003与T004、T005-T009均可并行
- **Phase 3 (US1)**: T010 (prompt) 和 T011 (parser) 可并行启动
- **Phase 4 (US2)**: T017 (章节填充) 和 T018 (脆弱选择器) 可并行
- **Phase 5 (US3)**: T021 (加载器) 和 T022 (prompt) 可并行
- **Phase 6**: T027 (扫描) 和 T028 (格式化) 可并行
- **Phase 7**: T031和T032集成测试可并行执行
- **Phase 8**: T036, T037, T039, T040, T042均可并行处理

---

## Parallel Example: User Story 1

```bash
# 并行启动US1的独立任务：
Task: "创建 /frago.recipe prompt模板在 .claude/commands/frago_recipe.md"
Task: "实现对话历史解析器在 src/frago/recipe/conversation_parser.py"

# 等待上述完成后，继续：
Task: "实现配方代码生成器在 src/frago/recipe/generator.py"
```

---

## Implementation Strategy

### MVP First (仅User Story 1)

1. ✅ 完成 Phase 1: Setup
2. ✅ 完成 Phase 2: Foundational (关键阻塞点)
3. 🎯 完成 Phase 3: User Story 1（T010-T016）
4. **STOP and VALIDATE**: 独立测试US1（通过对话创建配方并执行）
5. 演示/部署MVP

### Incremental Delivery

1. ✅ Setup + Foundational → 基础就绪（51个测试通过）
2. 🎯 添加 User Story 1 → 独立测试 → 部署/演示（MVP！）
3. 添加 User Story 2 → 独立测试 → 部署/演示
4. 添加 User Story 3 → 独立测试 → 部署/演示
5. 每个故事添加价值而不破坏已有功能

### Parallel Team Strategy

多开发者场景：

1. 团队一起完成 Setup + Foundational ✅
2. Foundational完成后：
   - Developer A: User Story 1 (T010-T016)
   - Developer B: User Story 2 (T017-T020，等US1的generator.py初版完成后）
   - Developer C: 配方库管理 (T027-T030)
3. 故事独立完成并集成

---

## 架构简化总结（重要参考）

### ❌ 完全删除的Python代码生成组件

本任务列表**不包含**以下组件的实现：

- ~~RecipeExplorer类~~ → Claude Code本身就是探索引擎
- ~~ExplorationSession/Step模型~~ → 对话历史即为状态
- ~~Selector模型和策略（selector.py）~~ → 规则整合在prompt中
- ~~Recipe/KnowledgeDocument模型（models.py）~~ → Claude Code不需要Python数据模型
- ~~模板系统（templates.py）~~ → Prompt中提供JavaScript模板示例
- ~~对话解析器（conversation_parser.py）~~ → Claude Code读自己的对话历史
- ~~代码生成器（generator.py）~~ → Claude Code用Write工具直接写文件
- ~~配方库管理（library.py）~~ → Claude Code用Glob/Read工具扫描目录
- ~~所有单元测试（51个测试）~~ → 测试的代码已删除

### ✅ 唯一保留的组件

- **Prompt模板**（`.claude/commands/frago_recipe.md`）→ 完整的指令集，包含：
  - 选择器优先级规则表格
  - JavaScript配方脚本模板示例
  - Markdown知识文档6章节格式
  - 创建/更新/列出三种模式的流程指令
- **配方库目录**（`src/frago/recipes/`）→ 存放Claude Code生成的.js和.md文件

---

## Notes

- **[P]** 标记任务可在不同文件中并行执行，无相互依赖
- **[Story]** 标签将任务映射到具体用户故事，确保可追溯性
- 每个用户故事应独立完成和测试
- Phase 1-2已完成（51个测试通过）
- 当前重点：Phase 3（T010-T016）实现MVP
- 在每个checkpoint停下来独立验证故事功能
- 避免：模糊任务、同文件冲突、破坏故事独立性的跨故事依赖
- 所有路径必须使用绝对路径：`/Users/chagee/Repos/Frago/...`

---

## 总结（最终简化版本）

**总任务数**: 11（T001-T011）
**已完成**: 3个（T001-T003，Prompt模板三种模式）
**待完成**: 8个（T004-T011，验证和完善）

**Phase分布**:
- Phase 1（US1 - 创建配方）: ✅ 1个任务（T001，Prompt模板创建模式）
- Phase 2（US3 - 更新配方）: ✅ 1个任务（T002，Prompt模板更新模式）
- Phase 3（配方库管理）: ✅ 1个任务（T003，Prompt模板列出模式）
- Phase 4（验证和完善）: 8个任务（T004-T011）

**并行机会**:
- Phase 4: T004 ‖ T005（手动测试可并行）
- Phase 4: T008 ‖ T009 ‖ T010（文档优化可并行）

**MVP范围**: ✅ 已完成 - Phase 1-3的Prompt模板已创建，系统可用

**测试标准**:
- US1: 通过对话创建配方脚本，Claude Code执行CDP命令，生成.js和.md文件
- US3: 更新现有配方，Claude Code读取原文件，覆盖并追加历史记录
- 列出: Claude Code扫描recipes/目录，解析头部注释，按平台分组显示

**关键里程碑**:
1. ✅ Phase 1-3完成 → Prompt模板已完成，核心功能可用
2. 🎯 Phase 4进行中 → 手动验证和优化
3. Phase 4完成 → 生产就绪
