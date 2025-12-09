# Implementation Plan: Frago GUI Tasks Redesign

**Branch**: `011-gui-tasks-redesign` | **Date**: 2025-12-08 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/011-gui-tasks-redesign/spec.md`

## Summary

重新设计 Frago GUI 应用程序，将默认启动页面改为 Tips 页面，将原"主页"更名为"Tasks"页面。Tasks 页面将显示所有已运行任务的列表，使用红（错误/停止）、黄（进行中）、绿（完成）三色状态指示器。点击任务列表项可进入任务详情页面，加载对应的 Claude 原生会话内容。

技术方案：基于现有 pywebview GUI 架构，扩展 session 监控模块的数据访问 API，新增 Tips 和 TaskDetail 页面组件，重构导航系统。

## Technical Context

**Language/Version**: Python 3.9+ (后端) + HTML5/CSS3/ES6 (前端)
**Primary Dependencies**: pywebview>=6.1, click>=8.1.0, pydantic>=2.0, watchdog (会话监控)
**Storage**: 文件系统
  - 会话数据: `~/.frago/sessions/{agent_type}/{session_id}/`
  - GUI 配置: `~/.frago/gui_config.json`
  - GUI 历史: `~/.frago/gui_history.jsonl`
**Testing**: pytest + 手动 GUI 测试
**Target Platform**: macOS (WebKit), Linux (GTK+WebKit2), Windows (Edge WebView2)
**Project Type**: 单项目 (CLI + GUI 混合)
**Performance Goals**:
  - GUI 启动到显示 Tips 页面 ≤3 秒 (SC-001)
  - Tasks 列表加载 ≤2 秒 (50 个任务) (SC-002)
  - 任务详情加载 ≤5 秒 (SC-003)
  - 页面切换 ≤1 秒 (SC-007)
**Constraints**:
  - 内存使用 <200MB（处理大量会话数据时）
  - 支持 10 个并发任务的实时监控 (SC-008)
  - 会话内容超过 1MB 时需要分页加载 (SC-006)
**Scale/Scope**:
  - 支持显示最多 100+ 任务列表
  - 单个会话可能包含数千条消息

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

当前项目 constitution.md 为模板状态，未定义具体约束。根据现有代码模式，遵循以下实践原则：

| 原则 | 当前实践 | 本功能合规性 |
|------|---------|-------------|
| 模块化架构 | GUI 模块独立于 CLI、Session 模块 | ✅ 本功能在现有 GUI 模块内扩展 |
| 文件系统存储 | 使用 JSON/JSONL 存储数据 | ✅ 使用现有 session 存储机制 |
| pywebview 集成 | Python 后端 + Web 前端 | ✅ 沿用现有架构模式 |
| 增量更新 | watchdog 文件监听 | ✅ 复用现有会话监控机制 |

**结论**: 无章程违规，可进入阶段 0。

## Project Structure

### Documentation (this feature)

```text
specs/011-gui-tasks-redesign/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/frago/
├── gui/
│   ├── app.py           # pywebview 主应用 (需修改: 默认页面切换)
│   ├── api.py           # Python-JS API 桥接 (需扩展: Tasks/Session API)
│   ├── models.py        # 数据模型 (需扩展: TaskItem, TaskDetail)
│   ├── state.py         # 状态管理 (可能需扩展)
│   ├── config.py        # 配置持久化
│   ├── history.py       # 历史记录
│   └── assets/
│       ├── index.html   # 页面结构 (需修改: 新增 Tips/Tasks/TaskDetail 页面)
│       ├── scripts/
│       │   └── app.js   # 前端逻辑 (需扩展: 新页面交互)
│       └── styles/
│           └── main.css # 样式 (需扩展: 状态颜色、新布局)
├── session/
│   ├── models.py        # 会话数据模型 (已有: MonitoredSession, SessionStep)
│   ├── monitor.py       # 会话监控器 (已有: SessionMonitor)
│   ├── storage.py       # 会话存储 (已有: list_sessions, read_steps)
│   ├── parser.py        # 会话解析器
│   └── formatter.py     # 输出格式化
└── cli/
    └── gui_command.py   # GUI CLI 命令

tests/
├── unit/
│   └── gui/
│       ├── test_api.py       # API 单元测试
│       └── test_models.py    # 模型单元测试
└── integration/
    └── gui/
        └── test_tasks_flow.py  # Tasks 页面集成测试
```

**Structure Decision**: 采用单项目结构，本功能在现有 `src/frago/gui/` 模块内扩展。GUI 前端（HTML/CSS/JS）与后端（Python API）保持现有分层。

## Complexity Tracking

> **无章程违规需要跟踪**

本功能为现有 GUI 系统的增量扩展，不引入新的架构复杂度：
- 复用现有 pywebview 架构
- 复用现有 session 存储模块
- 不引入新的外部依赖
- 不引入新的数据存储机制

---

## Post-Design Constitution Re-check

*阶段 1 设计完成后的章程重新评估*

| 原则 | 设计决策 | 合规性 |
|------|---------|--------|
| 模块化架构 | 新增 `TaskItem`, `TaskDetail`, `TaskStep` 模型在 `gui/models.py`；扩展 API 在 `gui/api.py`；分页函数在 `session/storage.py` | ✅ 保持模块独立性 |
| 文件系统存储 | 复用 `~/.frago/sessions/` 存储，无新增存储位置 | ✅ 符合现有模式 |
| pywebview 集成 | 新增 5 个 API 方法通过 `js_api` 暴露；使用 `evaluate_js()` 推送更新 | ✅ 符合现有 API 模式 |
| 增量更新 | 任务状态推送复用 `handleStreamMessage` 模式；会话步骤支持分页 | ✅ 复用现有机制 |
| 性能约束 | 分页 API 确保大会话加载性能；虚拟滚动作为 P2 优化 | ✅ 满足 SC-002/SC-003/SC-006 |

**设计后结论**:
- 所有设计决策符合现有架构原则
- 无新增外部依赖
- 数据模型与现有 `session` 模块保持一致性映射
- API 契约明确，可独立测试

---

## Generated Artifacts

| 文件 | 状态 | 说明 |
|------|------|------|
| `specs/011-gui-tasks-redesign/plan.md` | ✅ 完成 | 本文件 |
| `specs/011-gui-tasks-redesign/research.md` | ✅ 完成 | 技术研究报告 |
| `specs/011-gui-tasks-redesign/data-model.md` | ✅ 完成 | 数据模型定义 |
| `specs/011-gui-tasks-redesign/contracts/gui-api.md` | ✅ 完成 | GUI API 契约 |
| `specs/011-gui-tasks-redesign/quickstart.md` | ✅ 完成 | 快速开始指南 |
| `CLAUDE.md` | ✅ 更新 | 代理上下文已同步 |
