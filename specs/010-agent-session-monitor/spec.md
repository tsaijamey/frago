# Feature Specification: Agent 会话监控与数据展示优化

**Feature Branch**: `010-agent-session-monitor`
**Created**: 2025-12-05
**Status**: Draft
**Input**: User description: "对 frago agent 执行过程中的数据展示进行优化，通过监听 ~/.claude/ 会话数据文件变化，解析内容并保存到 ~/.frago/ 目录"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 实时查看 Agent 执行状态 (Priority: P1)

用户执行 `frago agent "完成某个任务"` 后，能够在终端实时看到 Agent 的执行进度、当前步骤、工具调用情况等结构化信息，而不是依赖 Agent 自身的原始输出。

**Why this priority**: 这是核心功能，直接解决用户无法清晰了解 Agent 执行状态的痛点。

**Independent Test**: 执行任意 `frago agent` 命令后，观察终端输出是否呈现结构化的状态信息。

**Acceptance Scenarios**:

1. **Given** 用户执行 `frago agent "搜索某个信息"`, **When** Agent 开始执行, **Then** 终端显示当前执行步骤、已用时间等状态信息
2. **Given** Agent 调用了某个工具（如浏览器导航）, **When** 工具执行完成, **Then** 终端更新显示工具名称、执行结果摘要
3. **Given** Agent 执行过程中, **When** 用户查看终端, **Then** 能看到与当前会话关联的准确状态，不会与其他并发会话混淆

---

### User Story 2 - 会话数据持久化存储 (Priority: P2)

Agent 执行过程中产生的关键数据（步骤、工具调用、结果等）被自动解析并保存到 `~/.frago/sessions/` 目录，供后续查询和分析。

**Why this priority**: 持久化是实时展示的基础，也为后续的历史查询、统计分析提供数据支撑。

**Independent Test**: 执行完 `frago agent` 命令后，检查 `~/.frago/sessions/` 目录是否生成了对应的会话数据文件。

**Acceptance Scenarios**:

1. **Given** 用户执行 `frago agent` 命令, **When** Agent 执行过程中, **Then** 会话数据被持续写入 `~/.frago/sessions/{session_id}/` 目录
2. **Given** 会话数据文件存在, **When** 用户查看文件内容, **Then** 数据结构清晰，包含时间戳、步骤、工具调用等字段
3. **Given** 多个 Agent 会话同时执行, **When** 各会话产生数据, **Then** 每个会话的数据被正确隔离存储在各自的目录中

---

### User Story 3 - 支持多种 Agent 工具 (Priority: P3)

系统设计预留扩展性，目录结构和数据格式能够支持未来接入其他 Agent 工具（如 Cursor、Cline 等），而不仅限于 Claude Code。

**Why this priority**: 前瞻性设计，避免后期重构，但当前主要聚焦 Claude Code 的实现。

**Independent Test**: 检查目录结构和配置文件是否包含 agent 类型标识字段。

**Acceptance Scenarios**:

1. **Given** 系统存储会话数据, **When** 查看目录结构, **Then** 路径中包含 agent 类型标识（如 `~/.frago/sessions/claude/{session_id}/`）
2. **Given** 会话数据文件, **When** 检查数据格式, **Then** 包含 `agent_type` 字段标识数据来源

---

### Edge Cases

- 当 `~/.claude/` 目录不存在或无权限访问时，系统应给出明确提示而非静默失败
- 当多个终端同时执行 `frago agent` 命令时，每个会话的监控数据应正确隔离
- 当 Claude Code 的会话文件格式发生变化时，解析器应优雅降级并记录警告
- 当磁盘空间不足时，应及时提醒用户并停止写入

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 能够识别当前 `frago agent` 进程对应的 Claude Code 会话 ID
- **FR-002**: 系统 MUST 监听 `~/.claude/projects/{project_path}/` 目录下对应会话文件的变化
- **FR-003**: 系统 MUST 解析会话 JSONL 文件，提取以下字段：
  - 消息内容（user/assistant）
  - 工具调用（tool name, parameters, result）
  - 时间戳
  - 执行状态
- **FR-004**: 系统 MUST 将解析后的数据写入 `~/.frago/sessions/{agent_type}/{session_id}/` 目录
- **FR-005**: 系统 MUST 在 `frago agent` 命令输出中展示结构化的执行状态信息
- **FR-006**: 系统 MUST 确保多个并发会话的数据隔离，通过会话 ID 关联正确的数据源
- **FR-007**: 系统 MUST 在会话文件格式无法解析时记录警告日志并继续运行

### Key Entities

- **Session**: 表示一次 Agent 执行会话，包含唯一 ID、开始时间、agent 类型、关联的项目路径
- **Step**: 表示会话中的一个执行步骤，包含序号、类型（message/tool_call）、内容、时间戳
- **ToolCall**: 表示一次工具调用，包含工具名称、参数、执行结果、耗时

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 用户执行 `frago agent` 后，能在 2 秒内看到首条状态信息输出
- **SC-002**: 会话数据文件在 Agent 执行结束后 5 秒内完成写入
- **SC-003**: 在 5 个并发 Agent 会话同时执行的场景下，100% 的会话数据被正确隔离存储
- **SC-004**: 90% 的用户能通过状态输出清晰了解 Agent 当前正在执行的操作

## Assumptions

- Claude Code 的会话数据存储在 `~/.claude/projects/{project_path}/{session_id}.jsonl` 格式的文件中
- 会话文件采用 JSONL 格式，每行一个 JSON 对象
- `frago agent` 命令在执行时能够获取或生成唯一的会话标识
- 用户对 `~/.claude/` 和 `~/.frago/` 目录具有读写权限
