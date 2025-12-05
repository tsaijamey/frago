# Implementation Plan: Agent 会话监控与数据展示优化

**Branch**: `010-agent-session-monitor` | **Date**: 2025-12-05 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/010-agent-session-monitor/spec.md`

## Summary

为 `frago agent` 命令添加实时会话监控能力。通过监听 `~/.claude/projects/` 目录下的 JSONL 会话文件变化，增量解析消息和工具调用数据，在终端展示结构化的执行状态，并将解析后的数据持久化到 `~/.frago/sessions/` 目录。

核心挑战是在多个并发会话场景下正确关联 `frago agent` 进程与其对应的 Claude Code 会话文件，采用「启动时间戳 + 项目路径 + 文件监听」的三重匹配策略解决。

## Technical Context

**Language/Version**: Python 3.9+（符合现有 pyproject.toml 要求）
**Primary Dependencies**: click>=8.1.0（现有）, pydantic（现有）, watchdog（新增，用于文件监听）
**Storage**: 文件系统（`~/.frago/sessions/{agent_type}/{session_id}/`）
**Testing**: pytest（现有）
**Target Platform**: Linux、macOS（跨平台）
**Project Type**: 单一项目（扩展现有 Frago CLI）
**Performance Goals**: 首条状态输出延迟 < 2秒，会话数据写入延迟 < 5秒
**Constraints**: 内存占用 < 50MB，支持 5 个并发会话监控
**Scale/Scope**: 面向个人开发者的本地工具

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

项目章程为模板状态，无强制约束。本特性设计遵循以下原则：

- ✅ 扩展现有模块而非创建新独立项目
- ✅ 复用现有数据模型（LogEntry、InsightEntry 等）
- ✅ 遵循 CLI 接口约定（click 命令、--json 参数）
- ✅ 使用 JSONL 格式与现有日志系统保持一致

## Project Structure

### Documentation (this feature)

```text
specs/010-agent-session-monitor/
├── spec.md              # 功能规格说明
├── plan.md              # 本文件
├── research.md          # 研究报告
├── data-model.md        # 数据模型设计
├── quickstart.md        # 快速开始指南
├── contracts/           # 接口契约
│   └── cli-interface.md # CLI 命令接口
└── checklists/
    └── requirements.md  # 需求检查清单
```

### Source Code (repository root)

```text
src/frago/
├── cli/
│   ├── agent_command.py       # [修改] 集成会话监控
│   └── session_commands.py    # [新增] session 子命令组
│
├── session/                   # [新增] 会话监控模块
│   ├── __init__.py
│   ├── monitor.py             # 会话监控器核心逻辑
│   ├── parser.py              # JSONL 解析器
│   ├── models.py              # 数据模型
│   ├── storage.py             # 数据持久化
│   └── formatter.py           # 输出格式化

tests/
├── unit/
│   └── session/
│       ├── test_parser.py
│       ├── test_monitor.py
│       └── test_storage.py
└── integration/
    └── test_session_monitor.py
```

**Structure Decision**: 在现有 `src/frago/` 下新增 `session/` 模块，与 `run/`、`gui/` 等模块并列。CLI 命令集成到 `cli/session_commands.py`，并在 `agent_command.py` 中调用监控功能。

## Implementation Phases

### Phase 1: 核心解析能力

1. 实现 JSONL 解析器（`parser.py`）
   - 增量读取文件（记录偏移量）
   - 解析用户消息、助手消息、工具调用
   - 提取关键字段（sessionId, timestamp, tool_use 等）

2. 实现数据模型（`models.py`）
   - MonitoredSession
   - SessionStep
   - ToolCallRecord
   - SessionSummary

3. 实现存储模块（`storage.py`）
   - 创建目录结构
   - 写入 metadata.json、steps.jsonl
   - 生成 summary.json

### Phase 2: 文件监听与会话关联

1. 实现会话监控器（`monitor.py`）
   - 使用 watchdog 监听目录变化
   - 基于时间窗口匹配新会话
   - 管理多个并发会话

2. 集成到 agent 命令
   - 在启动时记录时间戳
   - 启动后台监控线程
   - 实时输出状态信息

### Phase 3: CLI 命令扩展

1. 新增 session 命令组
   - `frago session list`
   - `frago session show`
   - `frago session watch`
   - `frago session clean`

2. 增强 agent 命令
   - 添加 `--quiet`、`--json-status`、`--no-monitor` 参数
   - 集成实时状态输出

### Phase 4: 测试与文档

1. 单元测试
   - 解析器测试（各种记录类型）
   - 存储模块测试
   - 监控器测试（模拟文件变化）

2. 集成测试
   - 端到端会话监控测试
   - 并发会话隔离测试

## Complexity Tracking

无需记录，本特性不引入复杂性违规。
