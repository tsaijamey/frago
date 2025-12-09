# Tasks: Frago GUI Tasks Redesign

**Input**: Design documents from `/specs/011-gui-tasks-redesign/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/gui-api.md ✓

**Tests**: 仅在 spec.md 中要求时包含测试任务（本功能不强制要求）

**Organization**: 任务按用户故事分组，每个故事可独立实现和测试

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事（US1, US2, US3, US4）
- 描述中包含精确的文件路径

## Path Conventions

- **Single project**: `src/frago/` at repository root
- **GUI Frontend**: `src/frago/gui/assets/`
- **Tests**: `tests/` at repository root

---

## Phase 1: Setup (共享基础设施)

**Purpose**: 确认项目结构和依赖准备就绪

- [X] T001 确认分支 `011-gui-tasks-redesign` 已创建并切换
- [X] T002 [P] 确认现有 GUI 依赖满足需求（pywebview>=6.1, watchdog）
- [X] T003 [P] 确认现有 session 模块可用（`src/frago/session/`）

---

## Phase 2: Foundational (阻塞性前置条件)

**Purpose**: 所有用户故事依赖的核心基础设施

**⚠️ CRITICAL**: 必须完成此阶段后才能开始任何用户故事

### 2.1 数据模型扩展

- [X] T004 [P] 添加 `TaskStatus` 枚举到 `src/frago/gui/models.py`
  - 定义: RUNNING (黄), COMPLETED (绿), ERROR (红), CANCELLED (红)
  - 实现: `color`, `icon`, `label` 属性方法
  - 参考: data-model.md 1.2 节

- [X] T005 [P] 添加 `TaskItem` 模型到 `src/frago/gui/models.py`
  - 字段: session_id, name, status, started_at, ended_at, duration_ms, step_count, tool_call_count, last_activity, project_path
  - 方法: `from_session(MonitoredSession)` 类方法
  - 参考: data-model.md 1.1 节

- [X] T006 [P] 添加 `TaskStep` 模型到 `src/frago/gui/models.py`
  - 字段: step_id, type, timestamp, content, tool_name, tool_status
  - 方法: `from_session_step(SessionStep)` 类方法
  - 参考: data-model.md 1.4 节

- [X] T007 添加 `TaskSummary` 和 `ToolUsageStat` 模型到 `src/frago/gui/models.py`
  - 字段: total_duration_ms, user_message_count, assistant_message_count, tool_call_count, tool_success_count, tool_error_count, most_used_tools
  - 方法: `from_session_summary(SessionSummary)` 类方法
  - 参考: data-model.md 1.5 节

- [X] T008 添加 `TaskDetail` 模型到 `src/frago/gui/models.py`（依赖 T005-T007）
  - 字段: 继承 TaskItem 字段 + user_message_count, assistant_message_count, steps, steps_total, steps_offset, has_more_steps, summary
  - 方法: `from_session_data(session, steps, summary, offset, limit)` 类方法
  - 参考: data-model.md 1.3 节

### 2.2 页面状态扩展

- [X] T009 扩展 `PageType` 枚举在 `src/frago/gui/models.py`
  - 新增: TIPS, TASKS, TASK_DETAIL
  - 修改默认值: TIPS（原 home）
  - 参考: data-model.md 2.1 节

- [X] T010 扩展 `AppState` 模型在 `src/frago/gui/models.py`（依赖 T009）
  - 修改: current_page 默认值改为 PageType.TIPS
  - 新增: current_task_id 字段
  - 参考: data-model.md 2.2 节

### 2.3 Storage 层扩展

- [X] T011 [P] 添加 `read_steps_paginated()` 函数到 `src/frago/session/storage.py`
  - 参数: session_id, agent_type, limit=50, offset=0
  - 返回: `{"steps": [...], "total": int, "offset": int, "limit": int, "has_more": bool}`
  - 参考: contracts/gui-api.md 6.2 节

- [X] T012 [P] 添加 `count_sessions()` 函数到 `src/frago/session/storage.py`
  - 参数: agent_type (可选), status (可选)
  - 返回: int (会话数量)
  - 参考: contracts/gui-api.md 6.2 节

**Checkpoint**: 基础设施就绪 - 可开始用户故事实现

---

## Phase 3: User Story 1 - 启动GUI并查看Tips页面 (Priority: P1) 🎯 MVP

**Goal**: 用户启动 GUI 后默认显示 Tips 页面（空状态占位）

**Independent Test**: 启动 `uv run frago gui --debug`，验证默认页面为 Tips

**Success Criteria**: SC-001 (GUI 启动到显示 Tips 页面 ≤3 秒)

### Implementation for User Story 1

- [X] T013 [US1] 添加 Tips 页面 HTML 结构到 `src/frago/gui/assets/index.html`
  - 创建 `<section id="page-tips" class="page active">`
  - 添加空状态提示（图标 + 标题 + 描述）
  - 参考: quickstart.md 2.1 节

- [X] T014 [US1] 添加 Tips 页面样式到 `src/frago/gui/assets/styles/main.css`
  - 空状态组件样式: `.empty-state`, `.empty-state__icon`, `.empty-state__title`, `.empty-state__description`
  - 参考: quickstart.md 2.3 节

- [X] T015 [US1] 修改默认页面加载逻辑在 `src/frago/gui/assets/scripts/app.js`
  - 修改 `initApp()` 或类似初始化函数
  - 设置默认激活页面为 `page-tips`
  - 参考: research.md 页面结构建议

- [X] T016 [US1] 更新导航菜单在 `src/frago/gui/assets/index.html`
  - 将"主页"改为"Tasks"
  - 添加"Tips"导航项（第一个位置）
  - 更新导航项的 active 状态逻辑

**Checkpoint**: Tips 页面可独立工作，启动后默认显示

---

## Phase 4: User Story 2 - 查看Tasks列表和状态 (Priority: P1)

**Goal**: Tasks 页面显示任务列表，红黄绿三色状态指示

**Independent Test**: 运行 `uv run frago agent "test"` 后，在 GUI Tasks 页面看到该任务及其状态

**Success Criteria**: SC-002 (Tasks 列表加载 ≤2 秒，50 个任务)

**Dependencies**: Phase 2 完成

### Implementation for User Story 2

- [X] T017 [US2] 添加 `get_tasks()` API 方法到 `src/frago/gui/api.py`
  - 参数: limit=50, offset=0
  - 返回: TaskListResponse 格式
  - 调用: `list_sessions()`, `count_sessions()`, `TaskItem.from_session()`
  - 参考: contracts/gui-api.md 1 节

- [X] T018 [US2] 添加 Tasks 页面 HTML 结构到 `src/frago/gui/assets/index.html`
  - 创建 `<section id="page-tasks" class="page">`
  - 添加页面头（标题 + 刷新按钮）
  - 添加任务列表容器 `#tasks-list`
  - 添加空状态容器 `#tasks-empty`
  - 参考: quickstart.md 2.1 节

- [X] T019 [P] [US2] 添加任务状态颜色样式到 `src/frago/gui/assets/styles/main.css`
  - `.task-status--running`: 黄色 (var(--accent-warning))
  - `.task-status--completed`: 绿色 (var(--accent-success))
  - `.task-status--error`, `.task-status--cancelled`: 红色 (var(--accent-error))
  - 参考: quickstart.md 2.3 节

- [X] T020 [P] [US2] 添加任务卡片样式到 `src/frago/gui/assets/styles/main.css`
  - `.task-card`, `.task-card:hover`
  - `.task-card__header`, `.task-card__name`, `.task-card__time`, `.task-card__stats`
  - 参考: quickstart.md 2.3 节

- [X] T021 [US2] 实现 `loadTasks()` 函数在 `src/frago/gui/assets/scripts/app.js`
  - 调用 `pywebview.api.get_tasks()`
  - 渲染任务卡片列表
  - 处理空状态显示
  - 参考: quickstart.md 2.2 节

- [X] T022 [US2] 实现 `refreshTasks()` 函数在 `src/frago/gui/assets/scripts/app.js`
  - 刷新按钮点击处理
  - 重新加载任务列表

- [X] T023 [US2] 实现辅助函数在 `src/frago/gui/assets/scripts/app.js`
  - `getStatusIcon(status)`: 返回状态图标
  - `getStatusLabel(status)`: 返回状态标签（中文）
  - `formatTime(isoString)`: 格式化时间显示
  - `formatDuration(ms)`: 格式化持续时间
  - `escapeHtml(str)`: HTML 转义

**Checkpoint**: Tasks 页面显示任务列表，状态颜色正确

---

## Phase 5: User Story 3 - 查看任务详情和Session内容 (Priority: P1)

**Goal**: 点击任务进入详情页，显示 Claude 原生会话内容

**Independent Test**: 点击 Tasks 列表中的任务，查看详情页显示步骤列表

**Success Criteria**: SC-003 (任务详情加载 ≤5 秒), SC-006 (大会话分页加载)

**Dependencies**: Phase 4 完成

### Implementation for User Story 3

- [X] T024 [US3] 添加 `get_task_detail()` API 方法到 `src/frago/gui/api.py`
  - 参数: session_id
  - 返回: TaskDetailResponse 格式
  - 调用: `read_metadata()`, `read_steps_paginated()`, `read_summary()`
  - 错误处理: 任务不存在时返回 `{"error": "Task not found", ...}`
  - 参考: contracts/gui-api.md 2 节

- [X] T025 [US3] 添加 `get_task_steps()` API 方法到 `src/frago/gui/api.py`
  - 参数: session_id, limit=50, offset=0
  - 返回: TaskStepsResponse 格式
  - 调用: `read_steps_paginated()`
  - 参考: contracts/gui-api.md 3 节

- [X] T026 [US3] 添加任务详情页 HTML 结构到 `src/frago/gui/assets/index.html`
  - 创建 `<section id="page-task-detail" class="page">`
  - 添加页面头（返回按钮 + 标题）
  - 添加详情内容容器 `#task-detail-content`
  - 参考: quickstart.md 2.1 节

- [X] T027 [P] [US3] 添加任务详情页样式到 `src/frago/gui/assets/styles/main.css`
  - `.task-detail__info`, `.task-detail__status`, `.task-detail__meta`, `.task-detail__stats`
  - 参考: quickstart.md 2.3 节

- [X] T028 [P] [US3] 添加步骤列表样式到 `src/frago/gui/assets/styles/main.css`
  - `.step`, `.step__header`, `.step__content`, `.step__number`, `.step__type`, `.step__time`
  - 步骤类型边框颜色: `.step--user_message`, `.step--assistant_message`, `.step--tool_call`, `.step--tool_result`
  - 参考: quickstart.md 2.3 节

- [X] T029 [US3] 实现 `openTaskDetail(sessionId)` 函数在 `src/frago/gui/assets/scripts/app.js`
  - 保存 Tasks 页面滚动位置
  - 设置 currentTaskId
  - 切换到详情页
  - 调用 `pywebview.api.get_task_detail()`
  - 调用 `renderTaskDetail(task)`
  - 参考: quickstart.md 2.2 节

- [X] T030 [US3] 实现 `renderTaskDetail(task)` 函数在 `src/frago/gui/assets/scripts/app.js`
  - 渲染任务基本信息
  - 渲染统计信息
  - 渲染步骤列表
  - 渲染"加载更多"按钮（如果 has_more_steps）
  - 参考: quickstart.md 2.2 节

- [X] T031 [US3] 实现 `renderSteps(steps)` 函数在 `src/frago/gui/assets/scripts/app.js`
  - 渲染步骤列表 HTML
  - 区分步骤类型样式
  - 参考: quickstart.md 2.2 节

- [X] T032 [US3] 实现 `loadMoreSteps()` 函数在 `src/frago/gui/assets/scripts/app.js`
  - 调用 `pywebview.api.get_task_steps()` 分页加载
  - 追加到现有步骤列表
  - 更新"加载更多"按钮状态

- [X] T033 [US3] 实现 `backToTasks()` 函数在 `src/frago/gui/assets/scripts/app.js`
  - 清除 currentTaskId
  - 切换回 Tasks 页面
  - 恢复滚动位置
  - 参考: quickstart.md 2.2 节

- [X] T034 [US3] 实现 `getStepTypeLabel(type)` 辅助函数在 `src/frago/gui/assets/scripts/app.js`
  - 返回步骤类型的中文标签

**Checkpoint**: 任务详情页功能完整，可查看会话内容和分页加载

---

## Phase 6: User Story 4 - 页面导航和布局 (Priority: P2)

**Goal**: 清晰的导航结构，页面切换流畅

**Independent Test**: 在 Tips/Tasks/任务详情/其他页面间切换，验证导航正确

**Success Criteria**: SC-007 (页面切换 ≤1 秒)

**Dependencies**: Phase 3, 4, 5 完成

### Implementation for User Story 4

- [X] T035 [US4] 扩展 `switchPage(pageType)` 函数在 `src/frago/gui/assets/scripts/app.js`
  - 支持新页面类型: tips, tasks, task_detail
  - 更新导航菜单 active 状态
  - 处理页面特定的进入/离开逻辑
  - 参考: data-model.md 5.2 节

- [X] T036 [US4] 更新导航菜单样式在 `src/frago/gui/assets/styles/main.css`
  - 确保导航项 active 状态清晰
  - Tips 和 Tasks 导航项样式一致

- [X] T037 [US4] 在页面切换时触发数据加载
  - 切换到 Tasks 页面时调用 `loadTasks()`
  - 切换到其他页面时清理状态

**Checkpoint**: 导航系统完整，页面切换流畅

---

## Phase 7: Real-time Updates (Enhancement)

**Goal**: 正在运行的任务实时更新步骤和状态

**Success Criteria**: SC-005 (任务状态变化 10 秒内更新), SC-008 (10 个并发任务)

**Dependencies**: Phase 5 完成

### Implementation for Real-time Updates

- [X] T038 [P] 添加轮询机制到 `src/frago/gui/assets/scripts/app.js`
  - 任务列表轮询：`startTasksPolling()`, `stopTasksPolling()`
  - 任务详情轮询：`startTaskDetailPolling()`, `stopTaskDetailPolling()`
  - 轮询间隔：3 秒
  - **Note**: 使用轮询替代 watchdog 订阅机制，更简单可靠

- [X] T039 实现 `hasTasksChanged()` 函数检测任务列表变化
  - 比较关键字段：session_id, status, step_count, duration_ms
  - 仅在变化时更新 DOM

- [X] T040 实现 `updateTaskDetailInPlace()` 函数就地更新任务详情
  - 更新状态标签
  - 更新统计数据
  - 更新元信息（持续时间等）
  - 保留滚动位置

- [X] T041 在页面切换时自动管理轮询
  - 切换到 tasks 页面启动列表轮询
  - 离开 tasks 页面停止列表轮询
  - 任务详情页面：运行中任务启动轮询，完成后停止

- [X] T042 添加过渡动画到 `src/frago/gui/assets/styles/main.css`
  - 任务卡片滑入动画 `taskCardSlideIn`
  - 步骤淡入动画 `stepFadeIn`
  - 进行中状态脉冲动画 `statusPulse`
  - 空状态淡入动画 `emptyStateFadeIn`

- [X] T043 在 `openTaskDetail()` 中自动启动运行中任务的轮询
  - 检查任务状态
  - 如果 running 则调用 `startTaskDetailPolling()`

- [X] T044 在 `backToTaskList()` 中停止详情轮询
  - 调用 `stopTaskDetailPolling()`

**Checkpoint**: 运行中任务实时更新步骤和状态

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: 完善细节和优化

- [X] T045 [P] 添加加载状态指示器到 Tasks 和详情页
  - 显示加载中动画
  - 加载完成后隐藏
  - 已在 HTML 和 CSS 中实现 `.loading` 类

- [X] T046 [P] 添加错误提示 Toast 组件
  - 复用现有 `showToast(message, type)` 函数
  - 支持 error, warning, success, info 类型
  - 已在 `refreshTasks()` 和 `loadMoreSteps()` 中使用

- [X] T047 优化空状态显示
  - Tasks 页面无任务时的友好提示（`#tasks-empty`）
  - 详情页加载失败时的错误提示
  - 空状态带有 `frago agent` 使用提示

- [X] T048 [P] 验证代码可正常导入和实例化
  - API 实例创建成功
  - 所有模型导入成功
  - 启动命令 `uv run frago gui --debug`

- [X] T049 代码清理和注释
  - 添加必要的代码注释
  - 更新 docstrings
  - 添加参数验证和错误处理

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1: Setup
     │
     ▼
Phase 2: Foundational (BLOCKS ALL USER STORIES)
     │
     ├──────────────────┬──────────────────┐
     ▼                  ▼                  ▼
Phase 3: US1       Phase 4: US2       (parallel if staffed)
(Tips 页面)        (Tasks 列表)
     │                  │
     │                  ▼
     │             Phase 5: US3
     │             (任务详情)
     │                  │
     └──────────────────┤
                        ▼
                   Phase 6: US4
                   (导航布局)
                        │
                        ▼
                   Phase 7: Real-time
                   (实时更新)
                        │
                        ▼
                   Phase 8: Polish
                   (完善优化)
```

### User Story Dependencies

| Story | Can Start After | Dependencies |
|-------|-----------------|--------------|
| US1 (Tips) | Phase 2 | 无其他故事依赖 |
| US2 (Tasks) | Phase 2 | T004-T012 (数据模型和 API) |
| US3 (Detail) | Phase 4 | US2 完成 + Tasks API |
| US4 (Navigation) | Phase 3,4,5 | 所有页面实现 |

### Within Each Phase

- 标记 [P] 的任务可并行执行
- 模型任务 → API 任务 → 前端任务
- HTML → CSS → JavaScript 顺序

### Parallel Opportunities

**Phase 2 内可并行：**
- T004, T005, T006, T007 (数据模型)
- T011, T012 (Storage 函数)

**Phase 4 内可并行：**
- T019, T020 (CSS 样式)

**Phase 5 内可并行：**
- T027, T028 (CSS 样式)

**Phase 7 内可并行：**
- T038 (属性添加) 与其他任务

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational (关键路径)
3. 完成 Phase 3: User Story 1 (Tips 页面)
4. **验证**: 启动 GUI 默认显示 Tips 页面
5. 可部署/演示 MVP

### Recommended Sequence

1. Setup + Foundational → 基础就绪
2. US1 (Tips) → 验证默认页面 ✓
3. US2 (Tasks) → 验证任务列表 ✓
4. US3 (Detail) → 验证任务详情 ✓
5. US4 (Navigation) → 验证页面切换 ✓
6. Real-time → 验证实时更新 ✓
7. Polish → 完成发布

### Estimated Task Count

| Phase | Task Count | Parallel |
|-------|------------|----------|
| Phase 1 (Setup) | 3 | 2 |
| Phase 2 (Foundational) | 9 | 5 |
| Phase 3 (US1) | 4 | 0 |
| Phase 4 (US2) | 7 | 2 |
| Phase 5 (US3) | 11 | 2 |
| Phase 6 (US4) | 3 | 0 |
| Phase 7 (Real-time) | 7 | 1 |
| Phase 8 (Polish) | 5 | 3 |
| **Total** | **49** | **15** |

---

## Notes

- [P] 任务 = 不同文件，无依赖，可并行
- [Story] 标签追踪任务所属用户故事
- 每个用户故事应可独立完成和测试
- 每个任务或逻辑组完成后提交
- 在任何检查点停止验证故事独立性
- 避免: 模糊任务，同文件冲突，破坏独立性的跨故事依赖
