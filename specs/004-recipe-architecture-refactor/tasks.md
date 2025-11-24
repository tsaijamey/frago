# Tasks: Recipe 系统架构重构（AI-First）

**Input**: 设计文档来自 `/specs/004-recipe-architecture-refactor/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-commands.md, quickstart.md

**Tests**: 本任务列表不包含单独的测试任务。测试将作为实现任务的一部分，通过集成测试验证 AI 使用场景。

**Organization**: 任务按用户故事组织，以实现独立实现和测试。每个阶段对应一个用户故事，可独立交付价值。

## Format: `[ID] [P?] [Story] 描述及文件路径`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 任务所属的用户故事（US0, US1, US2...）
- 包含确切的文件路径

## Path Conventions

- **Python 包代码**: `src/frago/` （打包到 wheel）
- **示例 Recipe**: `examples/` （不打包，或作为 data files）
- **测试**: `tests/`
- **文档**: `specs/004-recipe-architecture-refactor/`

---

## Phase 1: Setup（项目初始化）

**Purpose**: 创建项目结构并安装必要依赖

- [X] T001 添加 `pyyaml` 依赖到 `pyproject.toml` 的 `dependencies` 列表
- [X] T002 [P] 创建 Recipe 引擎目录结构：`src/frago/recipes/` 及 `__init__.py`, `runner.py`, `registry.py`, `metadata.py`, `output_handler.py`, `exceptions.py`
- [X] T003 [P] 创建示例 Recipe 目录结构：`examples/atomic/chrome/`, `examples/atomic/system/`, `examples/workflows/`
- [X] T004 [P] 创建测试目录结构：`tests/unit/`, `tests/integration/`, `tests/fixtures/recipes/`
- [X] T005 更新 `pyproject.toml` 的 `[tool.setuptools]` 配置，排除 `examples/` 目录不打包到 wheel

---

## Phase 2: Foundational（基础架构 - 阻塞性前置条件）

**Purpose**: 核心基础设施，必须在任何用户故事之前完成

**⚠️ CRITICAL**: 所有用户故事工作必须等此阶段完成

- [X] T006 [P] 在 `src/frago/recipes/exceptions.py` 中实现 Recipe 专用异常类：`RecipeNotFoundError`, `RecipeExecutionError`, `RecipeValidationError`, `MetadataParseError`
- [X] T007 [P] 在 `src/frago/recipes/metadata.py` 中实现 `RecipeMetadata` 数据类，包含所有必需字段（name, type, runtime, version, inputs, outputs）和 AI 字段（description, use_cases, tags, output_targets）
- [X] T008 在 `src/frago/recipes/metadata.py` 中实现 `parse_metadata_file(path: Path) -> RecipeMetadata` 函数，解析 Markdown 文件的 YAML frontmatter
- [X] T009 在 `src/frago/recipes/metadata.py` 中实现 `validate_metadata(metadata: RecipeMetadata) -> None` 函数，验证必需字段、枚举值、AI 字段完整性
- [X] T010 [P] 在 `src/frago/recipes/registry.py` 中实现 `RecipeRegistry` 类，包含 `search_paths`, `recipes` 属性和 `scan()`, `find(name)`, `list_all()` 方法
- [X] T011 在 `src/frago/recipes/registry.py` 中实现三级查找路径逻辑：项目级（`.frago/recipes/`）> 用户级（`~/.frago/recipes/`）> 示例级（`examples/`）
- [X] T012 [P] 在 `src/frago/recipes/output_handler.py` 中实现 `OutputHandler` 静态类，包含 `handle(data, target, options)` 方法，支持 stdout, file, clipboard 三种输出目标
- [X] T013 [P] 在 `src/frago/recipes/runner.py` 中实现 `RecipeRunner` 类框架，包含 `registry` 属性和 `run(name, params, output_target)` 方法签名

**Checkpoint**: 基础架构就绪 - 用户故事实现现在可以并行开始

---

## Phase 3: User Story 0 - AI Agent 自动创建和使用 Recipe (Priority: P0 - 核心愿景) 🎯 AI-First MVP

**Goal**: 让 Claude Code AI Agent 能够通过元数据发现 Recipe、理解其能力、选择输出方式，并通过 Bash 工具成功调用

**Independent Test**: AI 接收任务"提取 YouTube 视频字幕并保存为文件"，自动完成：1) 通过 `recipe list --format json` 发现 `youtube_extract_video_transcript` Recipe；2) 分析其 `output_targets` 支持 `file`；3) 执行 `recipe run` 并指定 `--output-file` 选项；4) 成功输出到文件

### Implementation for User Story 0

- [X] T014 [P] [US0] 在 `src/frago/cli/recipe_commands.py` 中实现 `recipe list` 命令，支持 `--format json` 选项，输出包含 AI 元数据字段（description, use_cases, tags, output_targets）的 JSON 数组
- [X] T015 [P] [US0] 在 `src/frago/cli/recipe_commands.py` 中实现 `recipe info <name>` 命令，显示 Recipe 的所有元数据，包括 AI 可理解字段
- [X] T016 [US0] 在 `src/frago/cli/recipe_commands.py` 中实现 `recipe run <name>` 命令，支持 `--params`, `--params-file`, `--output-file`, `--output-clipboard` 选项
- [X] T017 [US0] 在 `src/frago/cli/main.py` 中注册 `recipe` 命令组，关联到 `recipe_commands.py` 的命令函数
- [X] T018 [P] [US0] 迁移现有 Recipe 到示例目录：将 `src/frago/recipes/upwork_extract_job_details_as_markdown.js` 移动到 `examples/atomic/chrome/`
- [X] T019 [P] [US0] 为迁移的 Recipe 创建元数据文件：`examples/atomic/chrome/upwork_extract_job_details_as_markdown.md`，包含 AI 字段（description, use_cases, tags, output_targets）
- [X] T020 [US0] 创建集成测试 `tests/integration/recipe/test_ai_workflow.py`，模拟 AI 调用 `recipe list --format json` → 解析 JSON → 选择 Recipe → 调用 `recipe run` 的完整流程
- [X] T021 [US0] 更新 `.claude/commands/frago-recipe.md` 文档，说明 `/frago.recipe` 命令如何支持 AI 生成 Workflow Recipe（包含 RecipeRunner 导入和调用示例）

**Checkpoint**: AI Agent 可通过 JSON 元数据发现和调用 Recipe，输出到不同目标

---

## Phase 4: User Story 1 - 创建跨语言 Recipe (Priority: P1)

**Goal**: 支持 JavaScript、Python、Shell 三种语言的 Recipe，统一调用和管理

**Independent Test**: 创建三种语言的简单 Recipe（JS 提取网页标题、Python 读取剪贴板、Shell 复制文件），通过统一命令成功执行所有三个 Recipe

### Implementation for User Story 1

- [X] T022 [P] [US1] 在 `src/frago/recipes/runner.py` 中实现 `_run_chrome_js(script_path, params)` 方法，调用 `uv run frago exec-js`，返回 JSON 结果
- [X] T023 [P] [US1] 在 `src/frago/recipes/runner.py` 中实现 `_run_python(script_path, params)` 方法，调用 `python3 <script> <params_json>`，返回 JSON 结果
- [X] T024 [P] [US1] 在 `src/frago/recipes/runner.py` 中实现 `_run_shell(script_path, params)` 方法，调用 `<script> <params_json>`，检查执行权限，返回 JSON 结果
- [X] T025 [US1] 在 `src/frago/recipes/runner.py` 的 `run()` 方法中实现运行时选择逻辑：根据 `metadata.runtime` 调用对应的执行器（chrome-js/python/shell）
- [X] T026 [US1] 在 `src/frago/recipes/runner.py` 中实现错误处理：捕获执行失败、JSON 解析错误、超时等，返回统一格式的 `RecipeExecutionError`
- [X] T027 [P] [US1] 创建示例 Python Recipe：`examples/atomic/system/clipboard_read.py` 和 `clipboard_read.md`，读取剪贴板内容并输出 JSON
- [X] T028 [P] [US1] 创建示例 Shell Recipe：`examples/atomic/system/file_copy.sh` 和 `file_copy.md`，复制文件并输出操作结果 JSON
- [X] T029 [US1] 创建集成测试 `tests/integration/recipe/test_recipe_execution.py`，测试三种运行时的 Recipe 执行、参数传递、JSON 输出、错误处理

**Checkpoint**: 三种语言的 Recipe 都能通过统一接口成功执行，错误信息格式一致

---

## Phase 5: User Story 2 - 代码与资源分离 (Priority: P1)

**Goal**: 将 Frago Python 包代码与用户 Recipe 资源完全分离，用户可在 `~/.frago/recipes/` 管理自定义 Recipe

**Independent Test**: 安装 Frago 后，用户在 `~/.frago/recipes/` 创建自定义 Recipe，卸载并重新安装 Frago，自定义 Recipe 依然可用

### Implementation for User Story 2

- [X] T030 [P] [US2] 在 `src/frago/cli/commands.py` 中实现 `init` 命令，创建用户级目录结构：`~/.frago/recipes/atomic/chrome/`, `atomic/system/`, `workflows/`
- [X] T031 [P] [US2] 在 `src/frago/cli/recipe_commands.py` 中实现 `recipe copy <name>` 命令，将示例 Recipe 复制到用户级目录（脚本 + 元数据文件）
- [X] T032 [US2] 在 `src/frago/recipes/registry.py` 的 `scan()` 方法中实现来源标注逻辑：标记 Recipe 为 `Project` / `User` / `Example` 来源
- [X] T033 [US2] 在 `src/frago/cli/recipe_commands.py` 的 `list` 命令中显示来源标签（表格格式的 SOURCE 列，JSON 格式的 source 字段）
- [X] T034 [US2] 迁移所有现有 Recipe 到 `examples/atomic/chrome/`：`youtube_extract_video_transcript.js/md`, `x_extract_tweet_with_comments.js/md`, `test_inspect_tab.js/md`
- [X] T035 [US2] 为所有迁移的 Recipe 更新元数据文件，添加 AI 字段（description, use_cases, tags, output_targets）
- [X] T036 [US2] 创建单元测试 `tests/unit/recipe/test_recipe_registry.py`，测试三级查找路径、优先级、来源标注、同名 Recipe 处理

**Checkpoint**: 用户级 Recipe 与包代码完全分离，升级不影响自定义 Recipe

---

## Phase 6: User Story 3 - 编排多个 Recipe 的工作流 (Priority: P2)

**Goal**: 支持创建 Workflow Recipe，在其中调用多个原子 Recipe，实现复杂自动化流程

**Independent Test**: 创建一个 Workflow Recipe（`workflows/upwork_batch_extract.py`），在其中循环调用 `upwork_extract_job_details_as_markdown` Recipe 提取 10 个职位，成功生成汇总结果

### Implementation for User Story 3

- [X] T037 [P] [US3] 在 `src/frago/recipes/__init__.py` 中导出 `RecipeRunner` 类，供 Workflow Recipe 代码导入使用
- [X] T038 [P] [US3] 在 `src/frago/recipes/runner.py` 中实现 `run()` 方法返回值规范化：返回 `{"success": bool, "data": dict, "error": dict | None}` 格式
- [X] T039 [US3] 创建示例 Workflow Recipe：`examples/workflows/upwork_batch_extract.py`，循环调用 `upwork_extract_job_details_as_markdown`，处理多个 URL
- [X] T040 [P] [US3] 为 Workflow 创建元数据文件：`examples/workflows/upwork_batch_extract.md`，声明 `type: workflow`, `runtime: python`, `dependencies: [upwork_extract_job_details_as_markdown]`
- [X] T041 [US3] 在 `src/frago/recipes/registry.py` 的 `scan()` 方法中实现依赖检查：验证 Workflow 的 `dependencies` 中列出的 Recipe 是否存在
- [X] T042 [US3] 在 `src/frago/recipes/runner.py` 中实现异常传播：Workflow 调用原子 Recipe 失败时，抛出 `RecipeExecutionError` 供 Workflow 捕获
- [X] T043 [US3] 创建集成测试 `tests/integration/recipe/test_workflow_execution.py`，测试 Workflow 调用多个原子 Recipe、循环处理、错误处理、结果汇总

**Checkpoint**: Workflow Recipe 可成功调用多个原子 Recipe，支持循环、条件、错误处理

---

## Phase 7: User Story 4 - Recipe 元数据管理 (Priority: P2)

**Goal**: 每个 Recipe 都有清晰的元数据（输入参数、输出格式、运行时类型、版本号），系统能自动校验和提示

**Independent Test**: 创建一个带有完整元数据的 Recipe（`.md` 文件包含 YAML frontmatter），执行 `uv run frago recipe info <name>` 显示所有元数据信息

### Implementation for User Story 4

- [X] T044 [P] [US4] 在 `src/frago/recipes/metadata.py` 中实现参数验证逻辑：检查必需参数（`inputs.*.required: true`）是否提供
- [X] T045 [P] [US4] 在 `src/frago/recipes/metadata.py` 中实现类型检查逻辑：简单验证参数类型（string, number, boolean, array, object）
- [X] T046 [US4] 在 `src/frago/recipes/runner.py` 的 `run()` 方法中调用参数验证：执行前验证 `params` 符合 `metadata.inputs` 定义
- [X] T047 [US4] 在 `src/frago/cli/recipe_commands.py` 的 `info` 命令中实现完整元数据展示：名称、类型、运行时、版本、输入参数、输出字段、依赖、AI 字段（description, use_cases, tags, output_targets）
- [X] T048 [US4] 在 `src/frago/cli/recipe_commands.py` 中实现参数缺失时的友好错误提示：明确指出缺少哪个必需参数
- [X] T049 [P] [US4] 创建单元测试 `tests/unit/recipe/test_metadata_parser.py`，测试 YAML frontmatter 解析、必需字段验证、AI 字段验证、依赖检查
- [X] T050 [US4] 更新所有示例 Recipe 的元数据文件，确保包含完整的 `inputs`, `outputs` 定义和 AI 字段

**Checkpoint**: 所有 Recipe 元数据完整，执行前自动验证参数，错误提示清晰

---

## Phase 8: User Story 5 - 项目级 Recipe 支持 (Priority: P3)

**Goal**: 支持在项目目录下创建项目专属 Recipe（位于 `.frago/recipes/`），与全局 Recipe 隔离

**Independent Test**: 在项目目录创建 `.frago/recipes/workflows/project_workflow.py`，执行 `uv run frago recipe run project_workflow`，系统优先使用项目级 Recipe

### Implementation for User Story 5

- [X] T051 [P] [US5] 在 `src/frago/recipes/registry.py` 中实现项目级路径检测：检查当前工作目录的 `.frago/recipes/` 是否存在
- [X] T052 [US5] 在 `src/frago/recipes/registry.py` 的 `scan()` 方法中实现优先级逻辑：项目级 > 用户级 > 示例级，同名 Recipe 优先使用项目级
- [X] T053 [US5] 在 `src/frago/cli/recipe_commands.py` 的 `list` 和 `info` 命令中添加优先级提示：当存在同名 Recipe 时，显示使用哪个来源
- [X] T054 [P] [US5] 创建项目级示例 Recipe 文档：`examples/workflows/project_specific_task.py` 和 `.md`，演示项目级 Recipe 使用
- [X] T055 [US5] 创建集成测试 `tests/integration/recipe/test_project_recipes.py`，测试项目级 Recipe 优先级、切换目录后行为、同名 Recipe 处理

**Checkpoint**: 项目级 Recipe 正常工作，优先级正确，不影响其他级别 Recipe

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: 完善和横切关注点，提升整体质量

- [X] T056 [P] 在 `src/frago/recipes/output_handler.py` 中添加 clipboard 支持的依赖检查：如果 `pyperclip` 未安装，提示友好错误信息
- [X] T057 [P] 在 `src/frago/recipes/runner.py` 中添加超时机制：Recipe 执行超过合理时间（如 5 分钟）自动终止
- [X] T058 [P] 在 `src/frago/recipes/runner.py` 中添加输出大小检查：Recipe 输出 JSON 超过 10MB 时拒绝解析并报错
- [X] T059 更新 `README.md`，添加 Recipe 系统快速开始章节，链接到 `docs/recipes.md`（已复制 quickstart 内容到 docs/）
- [X] T060 [P] 创建单元测试 `tests/unit/recipe/test_output_handler.py`，测试三种输出目标（stdout, file, clipboard）、文件路径创建、错误处理（14个测试）
- [X] T061 [P] 创建单元测试 `tests/unit/recipe/test_runner.py`，测试运行时选择、参数传递、JSON 解析、错误处理、超时机制（10个测试）
- [X] T062 验证 `docs/recipes.md` 文档正确性，修复命令行参数错误（--output → --output-file）
- [X] T063 在 `CLAUDE.md` 中更新 Recipe 系统使用说明，强调 AI-first 设计和元数据驱动的发现机制
- [X] T064 [P] 为所有 CLI 命令添加 `--help` 文档字符串，确保帮助信息完整清晰（已完成）
- [X] T065 代码审查和重构：运行全部82个Recipe测试通过，Recipe模块覆盖率75-100%

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可立即开始
- **Foundational (Phase 2)**: 依赖 Setup 完成 - **阻塞所有用户故事**
- **User Stories (Phase 3-8)**: 全部依赖 Foundational 阶段完成
  - 用户故事可并行进行（如有多人协作）
  - 或按优先级顺序（P0 → P1 → P2 → P3）
- **Polish (Phase 9)**: 依赖所有期望的用户故事完成

### User Story Dependencies

- **User Story 0 (P0)**: 可在 Foundational (Phase 2) 后开始 - 无其他故事依赖
- **User Story 1 (P1)**: 可在 Foundational (Phase 2) 后开始 - 无其他故事依赖
- **User Story 2 (P1)**: 可在 Foundational (Phase 2) 后开始 - 无其他故事依赖
- **User Story 3 (P2)**: 依赖 US1（需要原子 Recipe 执行能力）- 应在 US1 后开始
- **User Story 4 (P2)**: 可在 Foundational (Phase 2) 后开始 - 无其他故事依赖
- **User Story 5 (P3)**: 可在 Foundational (Phase 2) 后开始 - 无其他故事依赖

### Within Each User Story

- CLI 命令实现在引擎代码之后
- 集成测试在实现任务之后
- 元数据文件与脚本文件同时创建
- 核心实现完成后再进行集成

### Parallel Opportunities

- Setup 阶段：T002, T003, T004 可并行（创建不同目录）
- Foundational 阶段：T006, T007, T010, T012 可并行（不同文件）
- US0 阶段：T014, T015, T018, T019 可并行（不同文件）
- US1 阶段：T022, T023, T024, T027, T028 可并行（不同文件）
- US2 阶段：T030, T031 可并行（不同文件）
- US3 阶段：T037, T038, T040 可并行（不同文件）
- US4 阶段：T044, T045, T049 可并行（不同文件）
- US5 阶段：T051, T054 可并行（不同文件）
- Polish 阶段：T056, T057, T058, T060, T061, T064 可并行（不同文件）
- Foundational 完成后，US0, US1, US2, US4, US5 可由不同团队成员并行开发

---

## Parallel Example: User Story 0 (AI-First MVP)

```bash
# 可同时启动的任务（不同文件，无依赖）:
Task T014: "在 src/frago/cli/recipe_commands.py 中实现 recipe list 命令"
Task T015: "在 src/frago/cli/recipe_commands.py 中实现 recipe info 命令"
Task T018: "迁移现有 Recipe 到 examples/atomic/chrome/"
Task T019: "创建元数据文件 examples/atomic/chrome/upwork_extract_job_details_as_markdown.md"

# 必须顺序执行的任务:
T016 (recipe run 命令) 依赖 T014, T015 完成（共享同一文件）
T017 (注册命令组) 依赖 T016 完成
T020 (集成测试) 依赖 T017 完成（需要完整的 CLI 功能）
```

---

## Implementation Strategy

### AI-First MVP (User Story 0 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (**CRITICAL** - 阻塞所有故事)
3. Complete Phase 3: User Story 0 (AI Agent 自动创建和使用 Recipe)
4. **STOP and VALIDATE**:
   - 测试 AI 通过 `recipe list --format json` 发现 Recipe
   - 测试 AI 分析元数据字段（description, use_cases, output_targets）
   - 测试 AI 调用 `recipe run` 并选择输出方式（--output-file）
5. Deploy/demo if ready

### Incremental Delivery

1. Complete Setup + Foundational → 基础就绪
2. Add User Story 0 → 独立测试 → Deploy/Demo (**AI-First MVP!**)
3. Add User Story 1 → 独立测试 → Deploy/Demo (多语言 Recipe 支持)
4. Add User Story 2 → 独立测试 → Deploy/Demo (代码与资源分离)
5. Add User Story 3 → 独立测试 → Deploy/Demo (Workflow 编排能力)
6. Add User Story 4 → 独立测试 → Deploy/Demo (元数据管理完善)
7. Add User Story 5 → 独立测试 → Deploy/Demo (项目级 Recipe)
8. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 0 (AI-First MVP - 最高优先级)
   - Developer B: User Story 1 (多语言支持)
   - Developer C: User Story 2 (代码与资源分离)
   - Developer D: User Story 4 (元数据管理)
3. After US1 completes:
   - Developer B: User Story 3 (Workflow 编排 - 依赖 US1)
4. Stories complete and integrate independently

---

## Notes

- **[P] 任务** = 不同文件，无依赖，可并行执行
- **[Story] 标签** 映射任务到特定用户故事，便于追踪
- **AI-First 设计**: 所有元数据、CLI 输出、错误格式都为 AI 可理解设计
- **每个用户故事应独立完成和测试**: 避免交叉依赖破坏独立性
- 每个任务或逻辑组完成后提交代码
- 在任何检查点停止以独立验证故事
- **避免**: 模糊任务、同文件冲突、破坏独立性的跨故事依赖
- **测试策略**: 集成测试验证 AI 使用场景，单元测试验证核心组件

---

## Task Count Summary

- **Total Tasks**: 65
- **Phase 1 (Setup)**: 5 tasks
- **Phase 2 (Foundational)**: 8 tasks
- **Phase 3 (US0 - AI-First MVP)**: 8 tasks
- **Phase 4 (US1 - 多语言支持)**: 8 tasks
- **Phase 5 (US2 - 代码与资源分离)**: 7 tasks
- **Phase 6 (US3 - Workflow 编排)**: 7 tasks
- **Phase 7 (US4 - 元数据管理)**: 7 tasks
- **Phase 8 (US5 - 项目级 Recipe)**: 5 tasks
- **Phase 9 (Polish)**: 10 tasks

**Parallel Opportunities**: 32 tasks marked [P] can run in parallel (49% of total)

**Independent Test Standards**:
- US0: AI 通过 JSON 元数据发现、分析、调用 Recipe，输出到指定目标
- US1: 三种语言 Recipe（JS/Python/Shell）通过统一接口成功执行
- US2: 用户级 Recipe 在包升级后保持可用
- US3: Workflow 成功调用多个原子 Recipe 并汇总结果
- US4: 元数据驱动的参数验证和友好错误提示
- US5: 项目级 Recipe 优先级正确，不影响其他级别

**Suggested MVP Scope**: Phase 1 + Phase 2 + Phase 3 (User Story 0 - AI-First MVP)
