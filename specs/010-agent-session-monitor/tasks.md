# Tasks: Agent 会话监控与数据展示优化

**Input**: Design documents from `/specs/010-agent-session-monitor/`
**Prerequisites**: plan.md, spec.md, data-model.md, contracts/cli-interface.md, research.md

**Organization**: 任务按用户故事组织，支持独立实现和测试。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事（US1、US2、US3）
- 描述中包含确切的文件路径

## Path Conventions

基于 plan.md 的项目结构：
- 源码: `src/frago/`
- 测试: `tests/`
- 新模块: `src/frago/session/`

---

## Phase 1: Setup (项目初始化)

**Purpose**: 创建模块结构和依赖配置

- [x] T001 创建 session 模块目录结构 `src/frago/session/__init__.py`
- [x] T002 [P] 在 `pyproject.toml` 中添加 watchdog 依赖
- [x] T003 [P] 创建测试目录结构 `tests/unit/session/` 和 `tests/integration/`

---

## Phase 2: Foundational (基础设施)

**Purpose**: 所有用户故事依赖的核心组件

**⚠️ CRITICAL**: 必须在任何用户故事开始前完成

- [x] T004 在 `src/frago/session/models.py` 中定义枚举类型（AgentType, SessionStatus, StepType, ToolCallStatus）
- [x] T005 [P] 在 `src/frago/session/models.py` 中实现 MonitoredSession 数据模型
- [x] T006 [P] 在 `src/frago/session/models.py` 中实现 SessionStep 数据模型
- [x] T007 [P] 在 `src/frago/session/models.py` 中实现 ToolCallRecord 数据模型
- [x] T008 [P] 在 `src/frago/session/models.py` 中实现 SessionSummary 数据模型
- [x] T009 在 `src/frago/session/parser.py` 中实现 JSONL 增量解析器（记录文件偏移量）
- [x] T010 在 `src/frago/session/parser.py` 中实现 Claude Code 记录类型解析（user, assistant, tool_use, tool_result, system）
- [x] T011 在 `src/frago/session/storage.py` 中实现会话目录创建（`~/.frago/sessions/{agent_type}/{session_id}/`）
- [x] T012 [P] 在 `src/frago/session/storage.py` 中实现 metadata.json 读写
- [x] T013 [P] 在 `src/frago/session/storage.py` 中实现 steps.jsonl 追加写入
- [x] T014 [P] 在 `src/frago/session/storage.py` 中实现 summary.json 生成

**Checkpoint**: 基础设施就绪，可以开始用户故事实现

---

## Phase 3: User Story 1 - 实时查看 Agent 执行状态 (Priority: P1) 🎯 MVP

**Goal**: 用户执行 `frago agent` 后，终端实时显示结构化的执行状态

**Independent Test**: 执行 `frago agent "测试任务"` 后，观察终端是否显示时间戳、步骤类型、工具调用等结构化信息

### Implementation for User Story 1

- [x] T015 [US1] 在 `src/frago/session/formatter.py` 中实现终端输出格式化器（时间戳 + emoji + 内容摘要）
- [x] T016 [US1] 在 `src/frago/session/formatter.py` 中实现 JSON 格式输出（`--json-status` 模式）
- [x] T017 [US1] 在 `src/frago/session/monitor.py` 中实现 SessionMonitor 类（使用 watchdog 监听目录变化）
- [x] T018 [US1] 在 `src/frago/session/monitor.py` 中实现会话关联逻辑（启动时间戳 + 项目路径匹配）
- [x] T019 [US1] 在 `src/frago/session/monitor.py` 中实现增量解析回调（新记录到达时触发）
- [x] T020 [US1] 在 `src/frago/session/monitor.py` 中实现并发会话隔离（每个 frago agent 进程独立监控）
- [x] T021 [US1] 修改 `src/frago/cli/agent_command.py` 添加 `--quiet`, `--json-status`, `--no-monitor` 参数
- [x] T022 [US1] 修改 `src/frago/cli/agent_command.py` 在执行前记录启动时间戳
- [x] T023 [US1] 修改 `src/frago/cli/agent_command.py` 启动后台监控线程
- [x] T024 [US1] 修改 `src/frago/cli/agent_command.py` 集成实时状态输出到终端

**Checkpoint**: 用户故事 1 完成，`frago agent` 命令可显示实时状态

---

## Phase 4: User Story 2 - 会话数据持久化存储 (Priority: P2)

**Goal**: Agent 执行过程中的数据自动保存到 `~/.frago/sessions/` 目录

**Independent Test**: 执行 `frago agent` 后，检查 `~/.frago/sessions/claude/{session_id}/` 目录是否生成 metadata.json 和 steps.jsonl

### Implementation for User Story 2

- [x] T025 [US2] 在 `src/frago/session/monitor.py` 中实现持久化集成（监控回调中调用 storage 模块）
- [x] T026 [US2] 在 `src/frago/session/monitor.py` 中实现会话结束检测（无新活动超时或 Claude 进程退出）
- [x] T027 [US2] 在 `src/frago/session/monitor.py` 中实现会话结束时生成 summary.json
- [x] T028 [US2] 在 `src/frago/session/storage.py` 中实现会话列表查询（按时间排序）
- [x] T029 [US2] 在 `src/frago/session/storage.py` 中实现会话数据读取（metadata + steps）
- [x] T030 [US2] 在 `src/frago/cli/session_commands.py` 中创建 session 命令组
- [x] T031 [US2] 在 `src/frago/cli/session_commands.py` 中实现 `frago session list` 命令
- [x] T032 [US2] 在 `src/frago/cli/session_commands.py` 中实现 `frago session show <session_id>` 命令
- [x] T033 [US2] 在 `src/frago/cli/session_commands.py` 中实现 `frago session watch [session_id]` 命令
- [x] T034 [US2] 在 `src/frago/cli/session_commands.py` 中实现 `frago session clean` 命令
- [x] T035 [US2] 在 `src/frago/cli/main.py` 中注册 session 命令组

**Checkpoint**: 用户故事 2 完成，会话数据可持久化并通过 CLI 查询

---

## Phase 5: User Story 3 - 支持多种 Agent 工具 (Priority: P3)

**Goal**: 目录结构和数据格式预留 agent_type 扩展性

**Independent Test**: 检查 `~/.frago/sessions/` 下的目录结构包含 `claude/` 子目录，metadata.json 包含 `agent_type` 字段

### Implementation for User Story 3

- [x] T036 [US3] 在 `src/frago/session/models.py` 中扩展 AgentType 枚举（添加 cursor, cline 预留值）
- [x] T037 [US3] 在 `src/frago/session/storage.py` 中验证 agent_type 路径隔离逻辑
- [x] T038 [US3] 在 `src/frago/cli/session_commands.py` 中为 `frago session list` 添加 `--agent-type` 筛选参数
- [x] T039 [US3] 在 `src/frago/session/monitor.py` 中抽象 AgentAdapter 接口（为未来 Cursor/Cline 适配器预留）

**Checkpoint**: 用户故事 3 完成，系统架构支持多 Agent 扩展

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 完善和横切关注点

- [x] T040 [P] 在 `src/frago/session/monitor.py` 中添加异常处理（目录不存在、权限问题、磁盘空间不足）
- [x] T041 [P] 在 `src/frago/session/parser.py` 中添加格式变更容错（未知字段忽略、关键字段缺失警告）
- [x] T042 [P] 添加环境变量支持（FRAGO_SESSION_DIR, FRAGO_CLAUDE_DIR, FRAGO_MONITOR_ENABLED）
- [ ] T043 运行 quickstart.md 验证所有功能正常

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，可立即开始
- **Foundational (Phase 2)**: 依赖 Setup 完成，阻塞所有用户故事
- **User Stories (Phase 3-5)**: 依赖 Foundational 完成
  - US1 和 US2 有轻度依赖（US2 使用 US1 的 monitor 模块）
  - US3 独立于其他故事
- **Polish (Phase 6)**: 依赖所有用户故事完成

### User Story Dependencies

```
Phase 1: Setup
    ↓
Phase 2: Foundational (models, parser, storage)
    ↓
    ├─→ Phase 3: US1 - 实时状态展示 (formatter, monitor, agent集成)
    │       ↓
    │   Phase 4: US2 - 持久化存储 (持久化集成, session命令组)
    │       ↓
    │   Phase 5: US3 - 多Agent支持 (扩展性设计)
    │
    └─→ [US3 可与 US1/US2 并行]
```

### Within Each User Story

- 模型/解析器 → 存储 → 监控器 → CLI 集成
- 完成当前故事后再进入下一优先级

### Parallel Opportunities

**Phase 1 内**:
- T002, T003 可并行

**Phase 2 内**:
- T005, T006, T007, T008 可并行（模型定义）
- T012, T013, T014 可并行（存储子功能）

**跨用户故事**:
- US3 (T036-T039) 可与 US1/US2 并行开发

---

## Parallel Example: Phase 2 (Foundational)

```bash
# 并行启动所有模型定义任务:
Task: "在 src/frago/session/models.py 中实现 MonitoredSession 数据模型"
Task: "在 src/frago/session/models.py 中实现 SessionStep 数据模型"
Task: "在 src/frago/session/models.py 中实现 ToolCallRecord 数据模型"
Task: "在 src/frago/session/models.py 中实现 SessionSummary 数据模型"

# 并行启动所有存储子功能任务:
Task: "在 src/frago/session/storage.py 中实现 metadata.json 读写"
Task: "在 src/frago/session/storage.py 中实现 steps.jsonl 追加写入"
Task: "在 src/frago/session/storage.py 中实现 summary.json 生成"
```

---

## Implementation Strategy

### MVP First (仅 User Story 1)

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational
3. 完成 Phase 3: User Story 1
4. **验证点**: 执行 `frago agent "测试"` 查看实时状态输出
5. 如满足核心需求，可暂停部署

### Incremental Delivery

1. Setup + Foundational → 基础设施就绪
2. 添加 US1 → 独立测试 → 可演示实时状态功能
3. 添加 US2 → 独立测试 → 可演示历史查询功能
4. 添加 US3 → 独立测试 → 架构扩展性验证
5. 每个故事增加价值且不破坏已有功能

### Suggested MVP Scope

**推荐 MVP**: Phase 1 + Phase 2 + Phase 3 (User Story 1)

这将交付：
- 实时状态展示（核心价值）
- 基础数据解析能力
- `--quiet`, `--no-monitor` 参数

**后续迭代**:
- Phase 4 (US2): 添加持久化和 `frago session` 命令
- Phase 5 (US3): 添加多 Agent 扩展支持

---

## Notes

- [P] 任务 = 不同文件，无依赖
- [Story] 标签映射任务到特定用户故事
- 每个用户故事应可独立完成和测试
- 每个任务或逻辑组后提交
- 在任何检查点停下来验证故事独立性
- 避免：模糊任务、同文件冲突、破坏独立性的跨故事依赖
