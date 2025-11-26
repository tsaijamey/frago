# Tasks: frago init 命令与 Recipe 资源安装

**Input**: Design documents from `/specs/007-init-commands-setup/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: 可选，仅在需要时包含测试任务。

**Organization**: 任务按用户故事组织，支持独立实现和测试。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事（US1, US2, US3）
- 描述中包含确切文件路径

## Path Conventions

- **Single project**: `src/frago/`, `tests/` 在仓库根目录
- 资源目录: `src/frago/resources/`

---

## Phase 1: Setup (项目初始化)

**Purpose**: 创建资源目录结构，配置包打包

- [x] T001 创建 `src/frago/resources/` 目录并添加 `__init__.py`
- [x] T002 创建 `src/frago/resources/commands/` 目录
- [x] T003 [P] 创建 `src/frago/resources/recipes/atomic/chrome/` 目录结构
- [x] T004 [P] 创建 `src/frago/resources/recipes/atomic/system/` 目录结构
- [x] T005 [P] 创建 `src/frago/resources/recipes/workflows/` 目录结构
- [x] T006 更新 `pyproject.toml` 添加资源文件 include 配置

---

## Phase 2: Foundational (基础模块)

**Purpose**: 实现核心资源访问和数据模型

**⚠️ CRITICAL**: 用户故事实现前必须完成此阶段

- [x] T007 在 `src/frago/init/models.py` 中添加 `ResourceType`, `InstallResult`, `ResourceStatus` 数据类
- [x] T008 创建 `src/frago/init/resources.py` 实现 `get_package_resources_path()` 函数
- [x] T009 [P] 在 `src/frago/init/resources.py` 中实现 `get_target_path()` 函数
- [x] T010 复制 `.claude/commands/frago.*.md` 到 `src/frago/resources/commands/`
- [x] T011 [P] 选择并复制示例 recipe 到 `src/frago/resources/recipes/`（至少 3 个 atomic + 2 个 workflow）

**Checkpoint**: 资源目录和基础模块就绪，可开始用户故事实现

---

## Phase 3: User Story 1 - 首次安装后运行 init 获得完整工具链 (Priority: P1) 🎯 MVP

**Goal**: 用户执行 `frago init` 后，slash 命令和示例 recipe 自动安装到用户目录

**Independent Test**: 在全新环境执行 `pip install frago && frago init`，验证 `~/.claude/commands/frago.*.md` 和 `~/.frago/recipes/` 存在

### Implementation for User Story 1

- [x] T012 [US1] 在 `src/frago/init/resources.py` 中实现 `install_commands()` 函数（始终覆盖）
- [x] T013 [US1] 在 `src/frago/init/resources.py` 中实现 `install_recipes()` 函数（仅首次安装）
- [x] T014 [US1] 在 `src/frago/init/resources.py` 中实现 `install_all_resources()` 主入口函数
- [x] T015 [US1] 在 `src/frago/cli/init_command.py` 中集成资源安装到 init 流程（在依赖检查后、配置前调用）
- [x] T016 [US1] 实现安装摘要输出，显示已安装文件列表
- [x] T017 [US1] 处理权限错误，提供明确的错误提示和解决建议

**Checkpoint**: 首次安装功能完成，可独立测试

---

## Phase 4: User Story 2 - 更新已安装的命令和 recipe (Priority: P2)

**Goal**: 用户升级后运行 `frago init` 更新系统资源，保留用户自定义内容

**Independent Test**: 先运行旧版本 init，创建自定义 recipe，升级后再运行 init，验证自定义内容未被覆盖

### Implementation for User Story 2

- [x] T018 [US2] 在 `src/frago/cli/init_command.py` 中添加 `--skip-resources` 选项
- [x] T019 [US2] 在 `src/frago/cli/init_command.py` 中添加 `--update-resources` 选项（强制更新所有资源）
- [x] T020 [US2] 修改 `install_recipes()` 支持 `--update-resources` 模式下的覆盖行为
- [x] T021 [US2] 实现备份逻辑：覆盖用户修改过的文件前创建 `.bak` 备份
- [x] T022 [US2] 更新安装摘要输出，显示更新、跳过和备份的文件统计

**Checkpoint**: 升级更新功能完成，可独立测试

---

## Phase 5: User Story 3 - 查看已安装资源状态 (Priority: P3)

**Goal**: 用户执行 `frago init --status` 查看当前资源安装状态

**Independent Test**: 执行 `frago init --status`，验证输出信息与文件系统状态一致

### Implementation for User Story 3

- [x] T023 [US3] 在 `src/frago/init/resources.py` 中实现 `get_resources_status()` 函数
- [x] T024 [US3] 实现 `count_installed_commands()` 统计已安装命令数量
- [x] T025 [US3] 实现 `count_installed_recipes()` 统计已安装 recipe 数量
- [x] T026 [US3] 修改 `src/frago/cli/init_command.py` 的 `--show-config` 选项逻辑，增加资源状态显示
- [x] T027 [US3] 格式化状态输出，包含目录位置、文件数量、版本信息

**Checkpoint**: 状态查看功能完成，可独立测试

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 完善和横切关注点

- [x] T028 [P] 在 `src/frago/init/models.py` 中扩展 `Config` 模型，添加 `resources_installed`, `resources_version`, `last_resource_update` 字段
- [x] T029 [P] 更新 `save_config()` 和 `load_config()` 支持新字段（Pydantic 自动处理）
- [x] T030 边缘情况处理：目标目录不存在时自动创建（mkdir parents=True）
- [x] T031 边缘情况处理：源资源目录为空或损坏时的错误处理
- [x] T032 运行 `quickstart.md` 验证：按快速开始指南验证完整流程

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，可立即开始
- **Foundational (Phase 2)**: 依赖 Setup 完成，阻塞所有用户故事
- **User Stories (Phase 3-5)**: 依赖 Foundational 完成，可并行或按优先级顺序执行
- **Polish (Phase 6)**: 依赖所有目标用户故事完成

### User Story Dependencies

- **User Story 1 (P1)**: 在 Foundational 后可开始，无其他故事依赖
- **User Story 2 (P2)**: 在 Foundational 后可开始，复用 US1 的安装函数
- **User Story 3 (P3)**: 在 Foundational 后可开始，独立于 US1/US2

### Within Each User Story

- 核心函数实现 → CLI 集成 → 输出格式化 → 错误处理

### Parallel Opportunities

- T003, T004, T005: 可并行创建不同子目录
- T009: 可与 T008 并行
- T010, T011: 可并行复制资源
- T028, T029: 可并行实现

---

## Parallel Example: Phase 2 Foundational

```bash
# 并行创建目录结构
Task: "创建 src/frago/resources/recipes/atomic/chrome/ 目录结构"
Task: "创建 src/frago/resources/recipes/atomic/system/ 目录结构"
Task: "创建 src/frago/resources/recipes/workflows/ 目录结构"

# 并行复制资源
Task: "复制 .claude/commands/frago.*.md 到 src/frago/resources/commands/"
Task: "选择并复制示例 recipe 到 src/frago/resources/recipes/"
```

---

## Implementation Strategy

### MVP First (仅 User Story 1)

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational
3. 完成 Phase 3: User Story 1
4. **STOP and VALIDATE**: 测试 `frago init` 首次安装功能
5. 可发布/演示

### Incremental Delivery

1. Setup + Foundational → 基础就绪
2. 添加 User Story 1 → 测试 → 发布 (MVP!)
3. 添加 User Story 2 → 测试 → 发布（支持升级）
4. 添加 User Story 3 → 测试 → 发布（支持状态查看）

---

## Notes

- [P] 任务 = 不同文件，无依赖
- [Story] 标签将任务映射到用户故事
- 每个用户故事可独立完成和测试
- 每个任务或逻辑组完成后提交
- 在任何检查点停止以独立验证故事
