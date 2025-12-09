# Tasks: Vite React 前端重构与 Linux 依赖自动安装

**Input**: Design documents from `/specs/012-vite-react-frontend/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Tests**: 未在规格说明中明确要求测试，本任务列表不包含测试任务。

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

本项目采用嵌入式 Web 前端结构：
- **前端源码**: `src/frago/gui/frontend/`
- **构建输出**: `src/frago/gui/assets/`
- **旧版代码**: `src/frago/gui/assets_legacy/`
- **后端修改**: `src/frago/gui/`

---

## Phase 1: Setup (项目初始化)

**Purpose**: 前端项目初始化和基础配置

- [X] T001 移动旧版前端文件到 `src/frago/gui/assets_legacy/` 并添加 deprecated 标记
- [X] T002 创建 `src/frago/gui/frontend/` 目录结构
- [X] T003 初始化 Vite + React + TypeScript 项目在 `src/frago/gui/frontend/`
- [X] T004 [P] 配置 TailwindCSS 在 `src/frago/gui/frontend/tailwind.config.js`
- [X] T005 [P] 配置 PostCSS 在 `src/frago/gui/frontend/postcss.config.js`
- [X] T006 [P] 配置 Vite 构建输出到 `../assets/` 在 `src/frago/gui/frontend/vite.config.ts`
- [X] T007 更新 `.gitignore` 添加 `src/frago/gui/assets/` 和 `src/frago/gui/frontend/node_modules/`

---

## Phase 2: Foundational (基础设施)

**Purpose**: 所有用户故事依赖的核心基础设施

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T008 复制 TypeScript 类型定义 `specs/012-vite-react-frontend/contracts/pywebview-api.ts` 到 `src/frago/gui/frontend/src/types/pywebview.d.ts`
- [X] T009 创建 pywebview API 封装层在 `src/frago/gui/frontend/src/api/pywebview.ts`
- [X] T010 [P] 创建 Zustand 状态管理 store 在 `src/frago/gui/frontend/src/stores/appStore.ts`
- [X] T011 [P] 从现有 `main.css` 提取 CSS 变量到 `src/frago/gui/frontend/src/styles/globals.css`
- [X] T012 创建 React 入口文件 `src/frago/gui/frontend/src/main.tsx`
- [X] T013 创建根组件 `src/frago/gui/frontend/src/App.tsx`（带页面路由）
- [X] T014 创建 Vite 入口 HTML `src/frago/gui/frontend/index.html`（带默认 data-theme）

**Checkpoint**: Foundation ready - 前端项目可以启动开发服务器

---

## Phase 3: User Story 1 - 开发者体验改进 (Priority: P1) 🎯 MVP

**Goal**: 建立现代化前端开发环境，支持 HMR 和 TypeScript 类型检查

**Independent Test**: 启动 Vite 开发服务器，修改组件代码，观察 HMR 是否在 3 秒内更新界面

### Implementation for User Story 1

- [X] T015 [US1] 修改 `src/frago/gui/app.py` 添加开发模式检测（FRAGO_GUI_DEV 环境变量）
- [X] T016 [US1] 在 `src/frago/gui/app.py` 中实现开发模式加载 `http://localhost:5173`
- [X] T017 [US1] 在 `src/frago/gui/app.py` 中实现生产模式加载 `file://{assets}/index.html`
- [X] T018 [P] [US1] 创建 usePolling hook 在 `src/frago/gui/frontend/src/hooks/usePolling.ts`
- [X] T019 [P] [US1] 创建 useConfig hook 在 `src/frago/gui/frontend/src/hooks/useConfig.ts`
- [X] T020 [P] [US1] 创建 useTasks hook 在 `src/frago/gui/frontend/src/hooks/useTasks.ts`
- [X] T021 [US1] 验证 TypeScript 编译零错误（运行 `npm run type-check`）

**Checkpoint**: 开发者可以使用 HMR 进行前端开发，修改代码后界面自动更新

---

## Phase 4: User Story 2 - 功能完整性保持 (Priority: P1)

**Goal**: 实现所有现有页面功能，确保迁移后无功能退步

**Independent Test**: 启动生产版本 GUI，逐一验证 Tips、Tasks、Recipes、Skills、Settings 页面功能

### Layout Components (布局组件)

- [X] T022 [P] [US2] 创建 Header 组件在 `src/frago/gui/frontend/src/components/layout/Header.tsx`
- [X] T023 [P] [US2] 创建 NavTabs 组件在 `src/frago/gui/frontend/src/components/layout/NavTabs.tsx`
- [X] T024 [P] [US2] 创建 StatusBar 组件在 `src/frago/gui/frontend/src/components/layout/StatusBar.tsx`

### UI Components (通用 UI 组件)

- [X] T025 [P] [US2] 创建 Toast 组件在 `src/frago/gui/frontend/src/components/ui/Toast.tsx`
- [X] T026 [P] [US2] 创建 EmptyState 组件在 `src/frago/gui/frontend/src/components/ui/EmptyState.tsx`
- [X] T027 [P] [US2] 创建 LoadingSpinner 组件在 `src/frago/gui/frontend/src/components/ui/LoadingSpinner.tsx`

### Tips Page

- [X] T028 [US2] 创建 TipsPage 组件在 `src/frago/gui/frontend/src/components/tips/TipsPage.tsx`

### Tasks Page (任务页面)

- [X] T029 [P] [US2] 创建 TaskCard 组件在 `src/frago/gui/frontend/src/components/tasks/TaskCard.tsx`
- [X] T030 [US2] 创建 TaskList 组件在 `src/frago/gui/frontend/src/components/tasks/TaskList.tsx`（依赖 T029）
- [X] T031 [P] [US2] 创建 StepList 组件在 `src/frago/gui/frontend/src/components/tasks/StepList.tsx`
- [X] T032 [US2] 创建 TaskDetail 组件在 `src/frago/gui/frontend/src/components/tasks/TaskDetail.tsx`（依赖 T031）
- [X] T033 [US2] 实现任务列表轮询更新逻辑在 TaskList 组件中

### Recipes Page (配方页面)

- [X] T034 [US2] 创建 RecipeList 组件在 `src/frago/gui/frontend/src/components/recipes/RecipeList.tsx`
- [X] T035 [US2] 创建 RecipeDetail 组件在 `src/frago/gui/frontend/src/components/recipes/RecipeDetail.tsx`

### Skills Page

- [X] T036 [US2] 创建 SkillList 组件在 `src/frago/gui/frontend/src/components/skills/SkillList.tsx`

### Settings Page

- [X] T037 [US2] 创建 SettingsPage 组件在 `src/frago/gui/frontend/src/components/settings/SettingsPage.tsx`
- [X] T038 [US2] 实现主题切换功能（dark/light）在 SettingsPage 和 appStore 中

### Build & Integration

- [X] T039 [US2] 运行 `npm run build` 验证构建产物正确输出到 `../assets/`
- [ ] T040 [US2] 验证生产模式 GUI 启动并加载构建产物

**Checkpoint**: 所有 5 个页面功能完整可用，主题切换正常工作

---

## Phase 5: User Story 3 - Linux 首次运行自动安装 (Priority: P2)

**Goal**: Linux 用户首次运行时自动检测并安装缺失的 GUI 依赖

**Independent Test**: 在缺少 GUI 依赖的 Linux 环境中运行 `frago gui`，观察自动安装流程

### Implementation for User Story 3

- [X] T041 [US3] 创建依赖检测模块 `src/frago/gui/deps.py`
- [X] T042 [US3] 在 deps.py 中实现 `detect_distro()` 函数（解析 /etc/os-release）
- [X] T043 [US3] 在 deps.py 中实现 `check_webkit_available()` 函数
- [X] T044 [US3] 在 deps.py 中实现 `auto_install_deps()` 函数（使用 pkexec）
- [X] T045 [US3] 修改 `src/frago/gui/app.py` 中的 `start_gui()` 集成自动安装逻辑
- [X] T046 [US3] 实现安装成功后自动重启 GUI 的逻辑

**Checkpoint**: Ubuntu/Debian 用户首次运行时可以自动安装依赖

---

## Phase 6: User Story 4 - 多发行版兼容 (Priority: P3)

**Goal**: 支持更多 Linux 发行版的自动安装，并为不支持的发行版提供手动指南

**Independent Test**: 在 Fedora、Arch、openSUSE 等发行版中测试自动安装流程

### Implementation for User Story 4

- [X] T047 [P] [US4] 在 deps.py 中添加 Fedora/RHEL 支持（dnf 包管理器）
- [X] T048 [P] [US4] 在 deps.py 中添加 Arch/Manjaro 支持（pacman 包管理器）
- [X] T049 [P] [US4] 在 deps.py 中添加 openSUSE 支持（zypper 包管理器）
- [X] T050 [US4] 实现不支持发行版的回退逻辑（打印手动安装指南）
- [X] T051 [US4] 实现 pkexec 不可用时的回退逻辑（命令行提示）

**Checkpoint**: 所有主流 Linux 发行版都能正确检测并提供安装方案

---

## Phase 7: Polish & Cross-Cutting Concerns (完善)

**Purpose**: 边缘情况处理和代码质量优化

- [X] T052 处理开发模式下 Vite 服务器未运行的错误提示
- [X] T053 处理构建产物损坏或缺失的友好错误提示
- [X] T054 处理网络离线时包管理器失败的错误提示
- [ ] T055 [P] 代码清理：移除未使用的导入和变量
- [ ] T056 运行 quickstart.md 验证开发流程

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion - BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Phase 2 completion
- **User Story 2 (Phase 4)**: Depends on Phase 2 completion, can run parallel with US1
- **User Story 3 (Phase 5)**: Depends on Phase 2 completion, independent of US1/US2
- **User Story 4 (Phase 6)**: Depends on Phase 5 completion (extends US3)
- **Polish (Phase 7)**: Depends on all user stories being complete

### User Story Dependencies

```
Phase 1 (Setup)
    │
    ▼
Phase 2 (Foundational)
    │
    ├───────────────────────────┐
    ▼                           ▼
Phase 3 (US1)              Phase 4 (US2)
开发者体验                  功能完整性
    │                           │
    └───────────┬───────────────┘
                ▼
           Phase 5 (US3)
        Linux 自动安装
                │
                ▼
           Phase 6 (US4)
         多发行版兼容
                │
                ▼
           Phase 7 (Polish)
              完善
```

### Parallel Opportunities

**Phase 1 内并行**:
- T004, T005, T006 可并行

**Phase 2 内并行**:
- T010, T011 可并行

**Phase 3 内并行**:
- T018, T019, T020 可并行

**Phase 4 内并行**:
- T022, T023, T024 布局组件可并行
- T025, T026, T027 UI 组件可并行
- T029, T031 任务相关组件可并行

**Phase 6 内并行**:
- T047, T048, T049 各发行版支持可并行

---

## Parallel Example: Phase 4 (US2)

```bash
# Launch layout components in parallel:
Task: "创建 Header 组件在 src/frago/gui/frontend/src/components/layout/Header.tsx"
Task: "创建 NavTabs 组件在 src/frago/gui/frontend/src/components/layout/NavTabs.tsx"
Task: "创建 StatusBar 组件在 src/frago/gui/frontend/src/components/layout/StatusBar.tsx"

# Launch UI components in parallel:
Task: "创建 Toast 组件在 src/frago/gui/frontend/src/components/ui/Toast.tsx"
Task: "创建 EmptyState 组件在 src/frago/gui/frontend/src/components/ui/EmptyState.tsx"
Task: "创建 LoadingSpinner 组件在 src/frago/gui/frontend/src/components/ui/LoadingSpinner.tsx"
```

---

## Implementation Strategy

### MVP First (User Story 1 + 2)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: User Story 1 (开发者体验)
4. Complete Phase 4: User Story 2 (功能完整性)
5. **STOP and VALIDATE**: 测试开发模式和生产模式 GUI
6. Deploy/demo if ready

### Incremental Delivery

1. Setup + Foundational → 前端项目可启动
2. Add US1 → HMR 开发体验可用
3. Add US2 → 所有页面功能完整 (MVP!)
4. Add US3 → Linux 自动安装
5. Add US4 → 多发行版支持
6. Polish → 边缘情况处理

### Single Developer Strategy

按优先级顺序执行：
1. Phase 1 → Phase 2 → Phase 3 → Phase 4 (MVP)
2. Phase 5 → Phase 6 → Phase 7

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- 每个用户故事应该可以独立完成和测试
- 每个任务或逻辑组完成后提交
- 在任何检查点停止以独立验证故事
- 避免：模糊任务、同一文件冲突、破坏独立性的跨故事依赖
