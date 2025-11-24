# Tasks: Run命令系统

**Input**: Design documents from `/specs/005-run-command-system/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**功能名称**: Run命令系统
**技术栈**: Python 3.9+, click, pypinyin, python-slugify, rapidfuzz
**测试策略**: pytest（单元测试、集成测试、契约测试）

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [X] T001 按实施计划创建 Run 系统目录结构（`src/frago/run/`, `tests/unit/test_run/`, `.frago/`, `runs/`）
- [X] T002 添加依赖到 pyproject.toml（pypinyin>=0.51.0, python-slugify>=8.0.0, rapidfuzz>=3.0.0）
- [X] T003 [P] 在 .gitignore 中添加 `runs/` 和 `.frago/current_run`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 创建数据模型在 src/frago/run/models.py（RunInstance, LogEntry, Screenshot, CurrentRunContext）
- [X] T005 [P] 创建自定义异常在 src/frago/run/exceptions.py（RunNotFoundError, InvalidRunIDError, ContextNotSetError, CorruptedLogError）
- [X] T006 [P] 实现主题slug生成逻辑在 src/frago/run/utils.py（使用 pypinyin + python-slugify）
- [X] T007 [P] 实现上下文管理器在 src/frago/run/context.py（读写 .frago/current_run，支持环境变量优先级）
- [X] T008 实现日志记录器在 src/frago/run/logger.py（JSONL格式化、schema验证、追加写入）
- [X] T009 实现 Run 实例管理器在 src/frago/run/manager.py（创建、查找、列表、归档）

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 2 - 主题型run实例管理与自动发现 (Priority: P1) 🎯 MVP

**Goal**: 实现主题型run实例的创建、发现和上下文管理，支持信息持续积累

**Independent Test**: 运行 `uv run frago run init "测试任务"` 两次，第二次应自动发现第一次创建的run

### Implementation for User Story 2

- [X] T010 [P] [US2] 实现 init 子命令在 src/frago/cli/run_commands.py（调用 manager.create_run）
- [X] T011 [P] [US2] 实现 set-context 子命令在 src/frago/cli/run_commands.py（调用 context.set_current_run）
- [X] T012 [P] [US2] 实现 list 子命令在 src/frago/cli/run_commands.py（支持 --format table/json, --status active/archived/all）
- [X] T013 [P] [US2] 实现 info 子命令在 src/frago/cli/run_commands.py（显示run详情、统计信息、最近日志）
- [X] T014 [P] [US2] 实现 archive 子命令在 src/frago/cli/run_commands.py（更新状态为archived，清空当前上下文）
- [X] T015 [US2] 实现 run 实例发现逻辑在 src/frago/run/discovery.py（扫描 runs/ 目录，使用 RapidFuzz 计算相似度）
- [X] T016 [US2] 在 src/frago/cli/commands.py 中注册 run 命令组（集成到主 CLI）

**Checkpoint**: 可以创建、列出、设置上下文、查看详情、归档 run 实例

---

## Phase 4: User Story 3 - CLI run子命令组 (Priority: P2)

**Goal**: 提供标准化的工具接口，确保日志和数据格式一致性

**Independent Test**: 执行 `uv run frago run log --step "测试" --status "success" --action-type "analysis" --execution-method "manual" --data '{}'`，验证日志正确写入

### Implementation for User Story 3

- [X] T017 [P] [US3] 实现 log 子命令在 src/frago/cli/run_commands.py（验证枚举值、调用 logger.write_log）
- [X] T018 [P] [US3] 实现截图自动编号机制在 src/frago/run/screenshot.py（扫描现有文件、原子性写入）
- [X] T019 [US3] 实现 screenshot 子命令在 src/frago/cli/run_commands.py（调用 CDP 截图、自动编号、记录日志）
- [X] T020 [US3] 添加 log 命令的参数验证（action_type 9种枚举、execution_method 6种枚举、status 3种枚举）
- [X] T021 [US3] 在 logger.py 中添加 schema_version 字段验证和数据迁移预留接口

**Checkpoint**: 所有 CLI 子命令可用，日志格式符合契约

---

## Phase 5: User Story 1 - AI主持的复杂任务执行与上下文积累 (Priority: P1)

**Goal**: 通过 /frago.run slash 命令支持 AI 主持的任务执行，作为信息中心

**Independent Test**: 在 Claude Code 中运行 `/frago.run "访问example.com并提取页面标题"`，验证任务执行和日志记录

### Implementation for User Story 1

- [X] T022 [US1] 创建 /frago.run slash 命令文档在 .claude/commands/frago.run.md（包含执行流程、工具使用指引、数据记录规范）
- [X] T023 [US1] 在 frago.run.md 中添加 run 实例发现流程（调用 list --format json，展示交互式菜单）
- [X] T024 [US1] 在 frago.run.md 中添加 Recipe 集成指引（如何发现和调用现有 Recipe）
- [X] T025 [US1] 在 frago.run.md 中添加代码文件处理约束（必须保存为 scripts/ 文件，禁止直接存储代码到日志）
- [X] T026 [US1] 在 frago.run.md 中添加进度展示要求（每5步输出摘要）和用户交互指引（使用 AskUserQuestion）
- [X] T027 [US1] 在 frago.run.md 中添加日志示例（6种 execution_method 的完整示例）

**Checkpoint**: /frago.run slash 命令可用，AI 可以执行复杂任务并正确记录日志

---

## Phase 6: User Story 4 - 清理过时的视频制作命令 (Priority: P3)

**Goal**: 删除旧的视频制作命令，将 Frago 定位转变为多运行时自动化基建

**Independent Test**: 尝试执行 `/frago.start`，确认命令不存在

### Implementation for User Story 4

- [X] T028 [P] [US4] 删除 .claude/commands/frago.start.md
- [X] T029 [P] [US4] 删除 .claude/commands/frago.storyboard.md
- [X] T030 [P] [US4] 删除 .claude/commands/frago.generate.md
- [X] T031 [P] [US4] 删除 .claude/commands/frago.evaluate.md
- [X] T032 [P] [US4] 删除 .claude/commands/frago.merge.md
- [X] T033 [US4] 更新 CLAUDE.md 移除视频制作 pipeline 描述（如果存在）

**Checkpoint**: 所有视频制作命令已删除，项目定位更新

---

## Phase 7: Testing (REQUIRED)

**Purpose**: Ensure all components meet quality standards

### Unit Tests

- [X] T034 [P] 单元测试 - manager.py 在 tests/unit/test_run/test_manager.py（create_run、find_run、list_runs、archive_run）
- [X] T035 [P] 单元测试 - logger.py 在 tests/unit/test_run/test_logger.py（write_log、schema验证、枚举值验证）
- [X] T036 [P] 单元测试 - context.py 在 tests/unit/test_run/test_context.py（set/get_current_run、环境变量优先级、失效处理）
- [X] T037 [P] 单元测试 - utils.py 在 tests/unit/test_run/test_utils.py（主题slug生成、中文处理、冲突检测）
- [X] T038 [P] 单元测试 - discovery.py 在 tests/unit/test_run/test_discovery.py（run实例扫描、相似度匹配）
- [X] T039 [P] 单元测试 - screenshot.py 在 tests/unit/test_run/test_screenshot.py（自动编号、原子性写入）

### Integration Tests

- [X] T040 集成测试 - 完整生命周期在 tests/integration/test_run_lifecycle.py（init → set-context → log → screenshot → archive）
- [X] T041 集成测试 - 多run实例在 tests/integration/test_multi_runs.py（创建多个run、切换上下文、互不干扰）
- [X] T042 集成测试 - 日志持久化在 tests/integration/test_log_persistence.py（跨会话日志累积、文件读写正确性）

### Contract Tests

- [X] T043 [P] 契约测试 - log 命令 JSONL 格式在 tests/contract/test_log_format.py（验证所有必需字段、枚举值、schema_version）
- [X] T044 [P] 契约测试 - CLI 命令退出码在 tests/contract/test_cli_exit_codes.py（验证所有命令的成功/失败退出码）
- [X] T045 [P] 契约测试 - JSON 输出格式在 tests/contract/test_json_output.py（使用 JSON Schema 验证 list/info/init 输出）

**Checkpoint**: 所有测试通过，代码质量达标

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [X] T046 [P] 添加类型注解到所有 run 模块（src/frago/run/*.py）
- [X] T047 [P] 添加 docstrings 到所有公共函数和类
- [X] T048 代码审查和重构（移除重复代码、优化性能）
- [X] T049 [P] 验证 quickstart.md 中的所有示例可执行
- [X] T050 [P] 更新项目 README.md 添加 Run 命令系统使用说明
- [X] T051 错误处理完善（统一错误消息格式、添加友好提示）
- [X] T052 性能测试（log 命令 <50ms、init 命令 <100ms、支持 10k+ 日志条目）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-6)**: All depend on Foundational phase completion
  - US2（P1）→ US3（P2）→ US1（P1）→ US4（P3）
  - US2 和 US3 可并行（不同文件）
  - US1 依赖 US2 和 US3（需要 CLI 命令和上下文管理）
- **Testing (Phase 7)**: Depends on all user stories being complete
- **Polish (Phase 8)**: Depends on testing completion

### User Story Dependencies

- **User Story 2 (P1)**: Can start after Foundational (Phase 2) - 基础run管理，无依赖
- **User Story 3 (P2)**: Can start after Foundational (Phase 2) - 日志和截图命令，无依赖
- **User Story 1 (P1)**: Depends on US2 + US3 - /frago.run 需要调用所有 CLI 命令
- **User Story 4 (P3)**: Independent - 删除旧命令，可随时执行

### Within Each User Story

- **US2**: T010-T014 可并行（不同子命令），T015 依赖 T009（manager），T016 集成所有子命令
- **US3**: T017-T018 可并行，T019 依赖 T018（截图机制），T020-T021 依赖 T017
- **US1**: T022-T027 串行（逐步完善文档内容）
- **US4**: T028-T032 可并行（删除不同文件），T033 最后执行

### Parallel Opportunities

- **Phase 1**: T002 和 T003 可并行
- **Phase 2**: T005、T006、T007 可并行（不同文件），T008-T009 依赖 T004（数据模型）
- **Phase 3 (US2)**: T010-T014 可并行（5个子命令）
- **Phase 4 (US3)**: T017-T018 可并行
- **Phase 6 (US4)**: T028-T032 可并行（删除5个文件）
- **Phase 7**: 所有单元测试（T034-T039）可并行，所有契约测试（T043-T045）可并行

---

## Parallel Example: Foundational Phase

```bash
# 并行创建基础模块（不同文件）:
Task: "创建自定义异常在 src/frago/run/exceptions.py"
Task: "实现主题slug生成逻辑在 src/frago/run/utils.py"
Task: "实现上下文管理器在 src/frago/run/context.py"

# 等待数据模型完成后，并行创建依赖模块:
Task: "实现日志记录器在 src/frago/run/logger.py"
Task: "实现 Run 实例管理器在 src/frago/run/manager.py"
```

---

## Parallel Example: User Story 2

```bash
# 并行实现所有子命令（不同功能，同一文件不同函数）:
Task: "[US2] 实现 init 子命令在 src/frago/cli/run_commands.py"
Task: "[US2] 实现 set-context 子命令在 src/frago/cli/run_commands.py"
Task: "[US2] 实现 list 子命令在 src/frago/cli/run_commands.py"
Task: "[US2] 实现 info 子命令在 src/frago/cli/run_commands.py"
Task: "[US2] 实现 archive 子命令在 src/frago/cli/run_commands.py"
```

---

## Implementation Strategy

### MVP First (User Story 2 + User Story 3)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 2（主题型run管理）
4. Complete Phase 4: User Story 3（CLI子命令组）
5. **STOP and VALIDATE**: 手动测试 init, set-context, log, screenshot 命令
6. 此时已有完整的 CLI 工具，可独立使用

### Full Feature (Add AI Integration)

1. Complete MVP (Phase 1-4)
2. Complete Phase 5: User Story 1（/frago.run slash命令）
3. **STOP and VALIDATE**: 在 Claude Code 中测试 /frago.run
4. Complete Phase 6: User Story 4（清理旧命令）
5. Complete Phase 7: Testing（确保质量）
6. Complete Phase 8: Polish（优化体验）

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 2（init, set-context, list, info, archive）
   - Developer B: User Story 3（log, screenshot）
   - Developer C: User Story 4（删除旧命令）
3. After US2 + US3 complete:
   - Developer A: User Story 1（/frago.run slash命令）
   - Developer B + C: Phase 7 Testing

---

## Notes

- [P] tasks = 不同文件或不同函数，无依赖，可并行
- [Story] label 映射任务到具体用户故事，便于追溯
- 每个用户故事应该独立完成和测试
- Phase 2（Foundational）是关键阻塞点，必须优先完成
- US1 依赖 US2+US3，因此虽然优先级同为 P1，但实施顺序在后
- 所有日志必须符合 data-model.md 中的 JSONL 格式规范
- 截图文件命名必须可排序（序号前缀 001、002...）
- 避免：模糊任务、同文件冲突、破坏独立性的跨故事依赖

---

## Success Metrics

完成本任务列表后，系统应满足以下标准：

- ✅ 用户可通过 CLI 创建、管理、查询 run 实例（SC-002）
- ✅ 所有日志为 JSONL 格式，100% 可程序解析（SC-003）
- ✅ 截图文件命名遵循规范（`<序号>_<描述slug>.png`）（SC-004）
- ✅ AI 在 /frago.run 中能识别并调用现有 Recipe（SC-007）
- ✅ 用户第二次执行相同主题任务时，系统自动发现现有run并提示复用（SC-009）
- ✅ 通过 set-context 机制，AI 执行的所有命令 100% 记录到同一个run实例（SC-010）
- ✅ log 命令执行 <50ms，init 命令 <100ms（性能目标）
- ✅ 支持单个 run 实例积累 10k+ 日志条目（性能目标）
- ✅ 所有测试通过（单元测试、集成测试、契约测试）

---

## Validation Checklist

在提交 PR 前，确认：

- [ ] 所有任务的复选框格式正确（`- [ ] [TaskID] [P?] [Story?] 描述及文件路径`）
- [ ] 所有文件路径为绝对路径或项目根目录相对路径
- [ ] 每个用户故事都有独立测试标准
- [ ] Foundational phase 完整且明确阻塞所有用户故事
- [ ] MVP 范围清晰（US2 + US3）
- [ ] 依赖关系图准确反映实施顺序
- [ ] 并行机会已标记 [P]
- [ ] 所有枚举值（action_type、execution_method、status）与 data-model.md 一致
