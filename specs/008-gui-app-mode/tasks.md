# Tasks: Frago GUI 应用模式

**Input**: Design documents from `/specs/008-gui-app-mode/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/js-python-api.md

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

本项目采用 **Single project** 结构：
- 源码：`src/frago/gui/`
- 测试：`tests/unit/gui/`、`tests/integration/`
- 前端资源：`src/frago/gui/assets/`

---

## Phase 1: Setup (项目初始化)

**Purpose**: 配置 GUI 模块的基础结构和依赖

- [X] T001 在 `pyproject.toml` 中添加 pywebview 可选依赖 `gui = ["pywebview>=6.1"]`
- [X] T002 创建 `src/frago/gui/__init__.py` 初始化 GUI 模块
- [X] T003 [P] 创建 `src/frago/gui/assets/` 目录结构（styles/、scripts/）
- [X] T004 [P] 更新 `pyproject.toml` 的 `[tool.hatch.build.targets.wheel]` 包含 GUI assets 文件

---

## Phase 2: Foundational (基础设施)

**Purpose**: 核心基础设施，所有用户故事的前置条件

**⚠️ CRITICAL**: 用户故事工作需在此阶段完成后才能开始

- [X] T005 在 `src/frago/gui/models.py` 中实现数据模型（WindowConfig, AppState, UserConfig, TaskStatus 枚举等）
- [X] T006 [P] 在 `src/frago/gui/exceptions.py` 中实现 GUI 异常类（GuiApiError, TaskAlreadyRunningError 等）
- [X] T007 [P] 在 `src/frago/gui/config.py` 中实现配置持久化（load_config, save_config）到 `~/.frago/gui_config.json`
- [X] T008 [P] 在 `src/frago/gui/history.py` 中实现历史记录持久化（append_record, get_history）到 `~/.frago/gui_history.jsonl`
- [X] T009 在 `src/frago/gui/state.py` 中实现 AppStateManager 状态管理类（单例模式，线程安全）
- [X] T010 添加 headless 环境检测函数 `can_start_gui()` 到 `src/frago/gui/utils.py`

**Checkpoint**: 基础设施就绪 - 可以开始用户故事实现

---

## Phase 3: User Story 1 - 启动GUI应用模式 (Priority: P1) 🎯 MVP

**Goal**: 用户通过 `frago --gui` 命令启动无边框 GUI 窗口，显示 frago 欢迎界面

**Independent Test**: 执行 `frago --gui` 验证 GUI 窗口正确启动，窗口尺寸为 600×1434，无边框

### Implementation for User Story 1

- [X] T011 [US1] 在 `src/frago/gui/app.py` 中实现 `FragoGuiApp` 类，包含 `create_window()` 和 `start()` 方法
- [X] T012 [US1] 在 `src/frago/gui/app.py` 中配置 pywebview 窗口参数（width=600, height=1434, frameless=True, easy_drag=True）
- [X] T013 [P] [US1] 创建 `src/frago/gui/assets/index.html` 基础 HTML 结构（头部导航栏、内容区域、底部状态栏）
- [X] T014 [P] [US1] 创建 `src/frago/gui/assets/styles/main.css` 基础样式（深色主题、无边框窗口样式、布局网格）
- [X] T015 [P] [US1] 创建 `src/frago/gui/assets/scripts/app.js` 基础 JS（pywebviewready 事件监听、初始化函数）
- [X] T016 [US1] 在 `src/frago/cli/main.py` 中添加 `--gui` 全局选项，调用 `FragoGuiApp.start()`
- [X] T017 [US1] 在 `src/frago/gui/app.py` 中添加 headless 环境检测，无图形界面时输出友好错误信息
- [X] T018 [US1] 在 `src/frago/gui/assets/index.html` 中添加欢迎界面内容和 frago logo

**Checkpoint**: User Story 1 完成 - `frago --gui` 可启动无边框窗口显示欢迎界面

---

## Phase 4: User Story 2 - 使用App式界面访问frago功能 (Priority: P2)

**Goal**: 用户在 GUI 界面中通过页面切换导航访问配方列表、skills 列表、设置等功能

**Independent Test**: 在 GUI 中切换页面（主页、配方、Skills、历史、设置），验证页面内容正确显示

### Implementation for User Story 2

- [X] T019 [P] [US2] 在 `src/frago/gui/api.py` 中实现 `FragoGuiApi` 类骨架，继承 pywebview js_api 协议
- [X] T020 [P] [US2] 在 `src/frago/gui/api.py` 中实现 `get_recipes()` 方法，调用现有 `frago recipe list` 逻辑
- [X] T021 [P] [US2] 在 `src/frago/gui/api.py` 中实现 `get_skills()` 方法，读取 `~/.claude/skills/` 目录
- [X] T022 [US2] 在 `src/frago/gui/api.py` 中实现 `run_recipe(name, params)` 方法，调用现有配方执行逻辑
- [X] T023 [US2] 在 `src/frago/gui/app.py` 中将 `FragoGuiApi` 实例传入 `webview.create_window(js_api=api)`
- [X] T024 [P] [US2] 在 `src/frago/gui/assets/scripts/app.js` 中实现页面切换逻辑（HOME, RECIPES, SKILLS, HISTORY, SETTINGS）
- [X] T025 [P] [US2] 在 `src/frago/gui/assets/styles/main.css` 中实现页面切换动画（平滑过渡）
- [X] T026 [US2] 在 `src/frago/gui/assets/scripts/app.js` 中实现 `renderRecipeList()` 函数，调用 `pywebview.api.get_recipes()`
- [X] T027 [US2] 在 `src/frago/gui/assets/scripts/app.js` 中实现 `renderSkillList()` 函数，调用 `pywebview.api.get_skills()`
- [X] T028 [US2] 在 `src/frago/gui/assets/scripts/app.js` 中实现 `runRecipe()` 函数，支持点击配方直接运行
- [X] T029 [P] [US2] 在 `src/frago/gui/assets/index.html` 中添加配方列表页面结构（列表容器、配方卡片模板）
- [X] T030 [P] [US2] 在 `src/frago/gui/assets/index.html` 中添加 Skills 列表页面结构（图标网格布局）
- [X] T031 [P] [US2] 在 `src/frago/gui/assets/index.html` 中添加设置页面结构（主题切换、字体大小等）
- [X] T032 [US2] 在 `src/frago/gui/api.py` 中实现 `get_config()` 和 `update_config()` 方法

**Checkpoint**: User Story 2 完成 - 可通过页面切换访问配方、Skills、设置页面

---

## Phase 5: User Story 3 - 通过输入区域调用frago agent (Priority: P2)

**Goal**: 用户在输入区域输入问题，点击发送按钮调用 frago agent，实时显示 stream-json 响应

**Independent Test**: 输入问题点击发送，验证 frago agent 被调用且响应正确显示在结果区域

### Implementation for User Story 3

- [X] T033 [US3] 在 `src/frago/gui/api.py` 中实现 `run_agent(prompt)` 方法，调用 frago agent 子进程
- [X] T034 [US3] 在 `src/frago/gui/api.py` 中实现任务单例控制（使用 AppStateManager 的锁机制）
- [X] T035 [US3] 在 `src/frago/gui/api.py` 中实现 `get_task_status()` 方法返回当前任务状态
- [X] T036 [US3] 在 `src/frago/gui/api.py` 中实现 `cancel_agent()` 方法终止运行中的任务
- [X] T037 [US3] 在 `src/frago/gui/stream.py` 中实现 stream-json 解析器（按行解析 JSON，处理格式错误）
- [X] T038 [US3] 在 `src/frago/gui/api.py` 中实现 `push_stream_message()` 通过 `window.evaluate_js()` 推送消息到前端
- [X] T039 [P] [US3] 在 `src/frago/gui/assets/index.html` 中添加输入区域结构（多行文本框、发送按钮）
- [X] T040 [P] [US3] 在 `src/frago/gui/assets/index.html` 中添加结果展示区域结构（消息列表、滚动容器）
- [X] T041 [P] [US3] 在 `src/frago/gui/assets/index.html` 中添加进度条和状态指示器
- [X] T042 [US3] 在 `src/frago/gui/assets/scripts/app.js` 中实现 `sendMessage()` 函数调用 `pywebview.api.run_agent()`
- [X] T043 [US3] 在 `src/frago/gui/assets/scripts/app.js` 中实现 `window.handleStreamMessage()` 处理流式消息
- [X] T044 [US3] 在 `src/frago/gui/assets/scripts/app.js` 中实现 `window.updateProgress()` 更新进度条
- [X] T045 [US3] 在 `src/frago/gui/assets/scripts/app.js` 中实现快捷键 Ctrl+Enter 发送消息
- [X] T046 [P] [US3] 在 `src/frago/gui/assets/styles/main.css` 中实现消息样式（用户消息右对齐蓝色、系统消息左对齐灰色）

**Checkpoint**: User Story 3 完成 - 可通过输入区域与 frago agent 交互

---

## Phase 6: User Story 4 - 查看执行结果和日志 (Priority: P3)

**Goal**: 用户在 GUI 中查看命令执行结果和历史记录

**Independent Test**: 执行命令后验证结果显示，切换到历史页面验证历史记录正确显示

### Implementation for User Story 4

- [X] T047 [US4] 在 `src/frago/gui/api.py` 中实现 `get_history(limit, offset)` 方法调用 history.py
- [X] T048 [US4] 在 `src/frago/gui/api.py` 中实现 `clear_history()` 方法
- [X] T049 [US4] 在 `src/frago/gui/api.py` 的 `run_agent()` 和 `run_recipe()` 中添加历史记录写入
- [X] T050 [P] [US4] 在 `src/frago/gui/assets/index.html` 中添加历史记录页面结构（时间线布局、状态标签）
- [X] T051 [US4] 在 `src/frago/gui/assets/scripts/app.js` 中实现 `renderHistory()` 函数
- [X] T052 [US4] 在 `src/frago/gui/assets/scripts/app.js` 中实现历史记录详情展开/折叠
- [X] T053 [P] [US4] 在 `src/frago/gui/assets/styles/main.css` 中实现历史记录样式（成功绿色、失败红色、时间戳灰色）

**Checkpoint**: User Story 4 完成 - 可查看命令执行结果和历史记录

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 改进和横切关注点

- [X] T054 [P] 在 `src/frago/gui/api.py` 中实现 `get_system_status()` 返回 CPU/内存使用情况
- [X] T055 [P] 在 `src/frago/gui/api.py` 中实现 `check_connection()` 检查 Chrome 连接状态
- [X] T056 在 `src/frago/gui/api.py` 中实现 `minimize_window()` 和 `close_window()` 窗口控制
- [X] T057 在 `src/frago/gui/assets/scripts/app.js` 中实现 `window.showToast()` Toast 通知（3秒自动消失）
- [X] T058 [P] 在 `src/frago/gui/assets/styles/main.css` 中实现 Toast 通知样式（info/success/warning/error）
- [X] T059 在 `src/frago/gui/app.py` 中实现窗口关闭确认逻辑（检测运行中任务，智能倒计时）
- [X] T060 [P] 在 `src/frago/gui/assets/index.html` 中添加底部状态栏（CPU/内存、连接状态、窗口控制按钮）
- [X] T061 在 `src/frago/gui/assets/scripts/app.js` 中实现状态栏定时刷新（每 5 秒更新系统状态）
- [X] T062 在 `src/frago/gui/assets/scripts/app.js` 中实现设置页面保存功能
- [X] T063 [P] 验证 `quickstart.md` 中的安装和使用流程

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可立即开始
- **Foundational (Phase 2)**: 依赖 Setup 完成 - **阻塞所有用户故事**
- **User Stories (Phase 3-6)**: 全部依赖 Foundational 完成
  - US1 (P1) 可独立进行
  - US2 (P2) 可独立进行（与 US1 无强依赖）
  - US3 (P2) 可独立进行（与 US1/US2 无强依赖）
  - US4 (P3) 依赖 US3 的历史记录写入逻辑
- **Polish (Phase 7)**: 依赖所有用户故事完成

### User Story Dependencies

```
          ┌──────────────┐
          │   Setup (1)  │
          └──────┬───────┘
                 │
          ┌──────▼───────┐
          │Foundational(2)│
          └──────┬───────┘
                 │
    ┌────────────┼────────────┐
    │            │            │
┌───▼───┐   ┌────▼────┐  ┌────▼────┐
│ US1   │   │  US2    │  │  US3    │
│ (P1)  │   │  (P2)   │  │  (P2)   │
│  MVP  │   │         │  │         │
└───────┘   └─────────┘  └────┬────┘
                              │
                         ┌────▼────┐
                         │  US4    │
                         │  (P3)   │
                         └────┬────┘
                              │
                         ┌────▼────┐
                         │ Polish  │
                         │  (7)    │
                         └─────────┘
```

### Parallel Opportunities

- T003, T004 可并行（不同文件）
- T006, T007, T008 可并行（不同文件）
- T013, T014, T015 可并行（不同文件类型）
- T019, T020, T021 可并行（同文件不同方法，但建议顺序）
- T024, T025, T029, T030, T031 可并行（不同文件）
- T039, T040, T041, T046 可并行（不同文件类型）
- T050, T053 可并行（不同文件类型）

---

## Parallel Example: User Story 1

```bash
# 并行创建前端资源文件（T013, T014, T015）：
Task: "创建 src/frago/gui/assets/index.html 基础 HTML 结构"
Task: "创建 src/frago/gui/assets/styles/main.css 基础样式"
Task: "创建 src/frago/gui/assets/scripts/app.js 基础 JS"

# 完成后顺序执行：
Task: "在 src/frago/cli/main.py 中添加 --gui 全局选项"
Task: "添加 headless 环境检测"
Task: "添加欢迎界面内容"
```

---

## Implementation Strategy

### MVP First (仅 User Story 1)

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational（关键 - 阻塞所有故事）
3. 完成 Phase 3: User Story 1
4. **停止并验证**: 独立测试 User Story 1
5. 可部署/演示 MVP

### Incremental Delivery

1. Setup + Foundational → 基础设施就绪
2. 添加 User Story 1 → 独立测试 → 部署/演示（MVP!）
3. 添加 User Story 2 → 独立测试 → 部署/演示
4. 添加 User Story 3 → 独立测试 → 部署/演示
5. 添加 User Story 4 → 独立测试 → 部署/演示
6. 每个故事增加价值且不破坏已有功能

### 任务总结

| 阶段 | 任务数 | 说明 |
|------|--------|------|
| Setup | 4 | 项目初始化 |
| Foundational | 6 | 基础设施 |
| US1 (P1) | 8 | MVP - GUI 启动 |
| US2 (P2) | 14 | 页面导航 |
| US3 (P2) | 14 | Agent 交互 |
| US4 (P3) | 7 | 历史记录 |
| Polish | 10 | 完善优化 |
| **总计** | **63** | |

---

## Notes

- [P] 任务 = 不同文件，无依赖
- [Story] 标签将任务映射到特定用户故事以便追踪
- 每个用户故事应可独立完成和测试
- 每个任务或逻辑组完成后提交
- 可在任何检查点停止以独立验证故事
- 避免：模糊任务、同文件冲突、破坏独立性的跨故事依赖
