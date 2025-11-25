# Tasks: Frago 环境初始化命令

**Input**: Design documents from `/home/yammi/repos/Frago/specs/006-init-command/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: 测试任务包含在内，遵循项目pytest规范

**Organization**: 任务按用户故事组织，以实现独立实现和测试

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行运行（不同文件，无依赖）
- **[Story]**: 任务所属的用户故事（如 US1, US2, US3）
- 描述中包含准确的文件路径

## Path Conventions

- **Single project**: `src/frago/`, `tests/` at repository root
- 遵循现有 Frago 项目结构

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 项目初始化和基础结构搭建

- [x] T001 在 `src/frago/init/` 创建模块目录结构
- [x] T002 [P] 创建 `src/frago/init/__init__.py` 导出模块
- [x] T003 [P] 创建 `tests/unit/init/` 单元测试目录
- [x] T004 [P] 创建 `tests/integration/` 集成测试目录（如不存在）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 核心基础设施，所有用户故事开始前必须完成

**⚠️ CRITICAL**: 在此阶段完成前，不能开始任何用户故事工作

- [x] T005 [P] 在 `src/frago/init/models.py` 实现 Config 数据模型（Pydantic）
- [x] T006 [P] 在 `src/frago/init/models.py` 实现 APIEndpoint 嵌套模型
- [x] T007 [P] 在 `src/frago/init/models.py` 实现 TemporaryState 数据模型
- [x] T008 [P] 在 `src/frago/init/models.py` 实现 InstallationStep 状态机
- [x] T009 [P] 在 `src/frago/init/models.py` 实现 DependencyCheckResult 模型
- [x] T010 [P] 在 `src/frago/init/exceptions.py` 创建自定义异常类（CommandError, InitErrorCode）
- [x] T011 [P] 在 `tests/unit/init/test_models.py` 编写所有模型的单元测试
- [x] T012 [P] 在 `tests/unit/init/test_exceptions.py` 编写异常类的单元测试

**Checkpoint**: 基础架构就绪 - 用户故事实现可以并行开始

---

## Phase 3: User Story 1 - 并行依赖检查和智能安装 (Priority: P1) 🎯 MVP

**Goal**: 实现 frago init 的核心功能 - 并行检查 Node.js 和 Claude Code 的安装状态，智能决定需要安装的组件

**Independent Test**: 在全新系统上运行 `uv run frago init`，系统能够：
1. 并行检查 Node.js 和 Claude Code 的安装状态
2. 显示检测结果摘要（哪些已安装，哪些缺失）
3. 询问用户是否安装缺失的组件
4. 根据依赖关系顺序安装（先 Node.js，后 Claude Code）
5. 验证所有安装成功

### Tests for User Story 1

> **NOTE: 编写这些测试，确保它们在实现前失败（TDD）**

- [x] T013 [P] [US1] 在 `tests/unit/init/test_checker.py` 编写 check_node_installed 测试
- [x] T014 [P] [US1] 在 `tests/unit/init/test_checker.py` 编写 check_claude_code_installed 测试
- [x] T015 [P] [US1] 在 `tests/unit/init/test_checker.py` 编写 parallel_dependency_check 测试
- [x] T016 [P] [US1] 在 `tests/unit/init/test_installer.py` 编写 install_node 测试（模拟 subprocess）
- [x] T017 [P] [US1] 在 `tests/unit/init/test_installer.py` 编写 install_claude_code 测试
- [x] T018 [P] [US1] 在 `tests/integration/test_init_command.py` 编写全新安装集成测试

### Implementation for User Story 1

- [x] T019 [P] [US1] 在 `src/frago/init/checker.py` 实现 check_node() 函数（检测 Node.js 版本）
- [x] T020 [P] [US1] 在 `src/frago/init/checker.py` 实现 check_claude_code() 函数
- [x] T021 [US1] 在 `src/frago/init/checker.py` 实现 parallel_dependency_check() 使用 ThreadPoolExecutor
- [x] T022 [P] [US1] 在 `src/frago/init/installer.py` 实现 run_external_command() 包装器（错误处理）
- [x] T023 [P] [US1] 在 `src/frago/init/installer.py` 实现 install_node() 函数（通过 nvm）
- [x] T024 [P] [US1] 在 `src/frago/init/installer.py` 实现 install_claude_code() 函数（npm install）
- [x] T025 [US1] 在 `src/frago/cli/init_command.py` 创建 Click 命令框架（@click.command）
- [x] T026 [US1] 在 `src/frago/cli/init_command.py` 实现依赖检查流程（调用 checker）
- [x] T027 [US1] 在 `src/frago/cli/init_command.py` 实现安装流程（调用 installer）
- [x] T028 [US1] 在 `src/frago/cli/init_command.py` 添加安装失败时的错误处理（立即终止）
- [x] T029 [US1] 在 `src/frago/cli/main.py` 注册 init 命令到 CLI 组

**Checkpoint**: User Story 1 完成 - 可以独立测试并部署为 MVP

---

## Phase 4: User Story 2 - 认证方式选择（互斥配置） (Priority: P2)

**Goal**: 实现互斥的认证配置 - 用户选择官方 Claude Code 登录或自定义 API 端点

**Independent Test**: 运行 `uv run frago init`（依赖已满足），系统能够：
1. 显示两种认证方式选项
2. 用户选择官方登录或自定义端点
3. 根据选择引导完成相应配置
4. 配置保存到 `~/.frago/config.json`，标记选择的认证方式

### Tests for User Story 2

- [x] T030 [P] [US2] 在 `tests/unit/init/test_configurator.py` 编写 prompt_auth_method 测试
- [x] T031 [P] [US2] 在 `tests/unit/init/test_configurator.py` 编写 configure_official_auth 测试
- [x] T032 [P] [US2] 在 `tests/unit/init/test_configurator.py` 编写 configure_custom_endpoint 测试
- [x] T033 [P] [US2] 在 `tests/unit/init/test_configurator.py` 编写认证互斥性验证测试
- [x] T034 [P] [US2] 在 `tests/integration/test_init_command.py` 编写官方登录流程集成测试
- [x] T035 [P] [US2] 在 `tests/integration/test_init_command.py` 编写自定义端点流程集成测试

### Implementation for User Story 2

- [x] T036 [P] [US2] 在 `src/frago/init/configurator.py` 实现 prompt_auth_method() 使用 Click.choice
- [x] T037 [P] [US2] 在 `src/frago/init/configurator.py` 实现 configure_official_auth() 函数
- [x] T038 [P] [US2] 在 `src/frago/init/configurator.py` 实现 configure_custom_endpoint() 函数
- [x] T039 [P] [US2] 在 `src/frago/init/configurator.py` 实现 load_config() 和 save_config() 函数
- [x] T040 [US2] 在 `src/frago/cli/init_command.py` 集成认证配置流程（调用 configurator）
- [x] T041 [US2] 在 `src/frago/cli/init_command.py` 实现认证方式切换时的警告提示

**Checkpoint**: User Stories 1 AND 2 都可以独立工作

---

## Phase 5: User Story 3 - 已有配置时的更新流程 (Priority: P2)

**Goal**: 实现配置更新流程 - 当依赖已满足且配置已存在时，允许用户更新特定配置项

**Independent Test**: 在已有完整配置的系统上运行 `uv run frago init`：
1. 系统检测到所有依赖已满足
2. 系统读取并显示当前配置摘要
3. 询问用户是否需要更新配置
4. 根据用户选择进入对应的更新流程

### Tests for User Story 3

- [x] T042 [P] [US3] 在 `tests/unit/init/test_configurator.py` 编写 display_config_summary 测试
- [x] T043 [P] [US3] 在 `tests/unit/init/test_configurator.py` 编写 prompt_config_update 测试
- [x] T044 [P] [US3] 在 `tests/integration/test_init_command.py` 编写配置更新流程集成测试
- [x] T045 [P] [US3] 在 `tests/integration/test_init_command.py` 编写无需更新退出测试

### Implementation for User Story 3

- [x] T046 [P] [US3] 在 `src/frago/init/configurator.py` 实现 display_config_summary() 函数
- [x] T047 [P] [US3] 在 `src/frago/init/configurator.py` 实现 prompt_config_update() 函数
- [x] T048 [P] [US3] 在 `src/frago/init/configurator.py` 实现 select_config_items_to_update() 函数
- [x] T049 [US3] 在 `src/frago/cli/init_command.py` 实现配置检测逻辑（所有依赖已满足且配置存在）
- [x] T050 [US3] 在 `src/frago/cli/init_command.py` 实现配置更新分支逻辑

**Checkpoint**: User Stories 1, 2 AND 3 都可以独立工作

---

## Phase 6: User Story 4 - 自定义 Claude API 端点配置 (Priority: P3)

**Goal**: 实现自定义 API 端点配置 - 支持 Deepseek、Aliyun、M2 和自定义 URL

**Independent Test**: 运行 `uv run frago init` 并选择"自定义端点"：
1. 系统显示支持的端点类型列表（Deepseek、Aliyun、M2、自定义）
2. 用户选择端点类型
3. 系统提示输入 API Key
4. 配置保存到 `~/.frago/config.json`

### Tests for User Story 4

- [x] T051 [P] [US4] 在 `tests/unit/init/test_configurator.py` 编写 prompt_endpoint_type 测试
- [x] T052 [P] [US4] 在 `tests/unit/init/test_configurator.py` 编写 prompt_api_key 测试（隐藏输入）
- [x] T053 [P] [US4] 在 `tests/unit/init/test_configurator.py` 编写 validate_endpoint_url 测试
- [x] T054 [P] [US4] 在 `tests/integration/test_init_command.py` 编写 Deepseek 端点配置测试
- [x] T055 [P] [US4] 在 `tests/integration/test_init_command.py` 编写自定义 URL 端点配置测试

### Implementation for User Story 4

- [x] T056 [P] [US4] 在 `src/frago/init/configurator.py` 实现 prompt_endpoint_type() 函数
- [x] T057 [P] [US4] 在 `src/frago/init/configurator.py` 实现 prompt_api_key() 函数（使用 hide_input=True）
- [x] T058 [P] [US4] 在 `src/frago/init/configurator.py` 实现 prompt_custom_endpoint_url() 函数
- [x] T059 [P] [US4] 在 `src/frago/init/configurator.py` 实现 validate_endpoint_url() 函数
- [x] T060 [P] [US4] 在 `src/frago/init/configurator.py` 实现预设端点 URL 映射（Deepseek/Aliyun/M2）
- [x] T061 [US4] 在 `src/frago/cli/init_command.py` 集成自定义端点配置逻辑到认证流程

**Checkpoint**: User Stories 1-4 都可以独立工作

---

## Phase 7: User Story 5 - Claude Code Router 集成（可选） (Priority: P4)

**Goal**: 实现可选的 Claude Code Router 安装和配置

**Independent Test**: 运行 `uv run frago init` 并选择"使用 Claude Code Router"：
1. 系统询问是否安装 CCR
2. 用户同意后，系统安装 CCR
3. 系统提供 CCR 配置模板
4. 用户完成配置后，系统保存设置

### Tests for User Story 5

- [ ] T062 [P] [US5] 在 `tests/unit/init/test_installer.py` 编写 check_ccr_installed 测试
- [ ] T063 [P] [US5] 在 `tests/unit/init/test_installer.py` 编写 install_ccr 测试
- [ ] T064 [P] [US5] 在 `tests/unit/init/test_configurator.py` 编写 create_ccr_config_template 测试
- [ ] T065 [P] [US5] 在 `tests/integration/test_init_command.py` 编写 CCR 集成测试

### Implementation for User Story 5

- [ ] T066 [P] [US5] 在 `src/frago/init/checker.py` 实现 check_ccr() 函数
- [ ] T067 [P] [US5] 在 `src/frago/init/installer.py` 实现 install_ccr() 函数
- [ ] T068 [P] [US5] 在 `src/frago/init/configurator.py` 实现 create_ccr_config_template() 函数
- [ ] T069 [P] [US5] 在 `src/frago/init/configurator.py` 实现 prompt_ccr_enable() 函数
- [ ] T070 [US5] 在 `src/frago/cli/init_command.py` 集成 CCR 配置流程（可选步骤）

**Checkpoint**: User Stories 1-5 都可以独立工作

---

## Phase 8: User Story 6 - 配置持久化和摘要报告 (Priority: P5)

**Goal**: 实现配置持久化和最终摘要显示

**Independent Test**: 完成 init 流程后：
1. 检查 `~/.frago/config.json` 文件存在
2. 文件包含所有用户选择（Node 版本、Claude Code 状态、端点配置等）
3. 系统显示配置摘要
4. 提供下一步操作建议

### Tests for User Story 6

- [x] T071 [P] [US6] 在 `tests/unit/init/test_configurator.py` 编写 save_config 持久化测试
- [x] T072 [P] [US6] 在 `tests/unit/init/test_configurator.py` 编写 format_final_summary 测试
- [x] T073 [P] [US6] 在 `tests/integration/test_init_command.py` 编写完整流程配置保存测试

### Implementation for User Story 6

- [x] T074 [P] [US6] 在 `src/frago/init/configurator.py` 完善 save_config() 函数（原子写入）
- [x] T075 [P] [US6] 在 `src/frago/init/configurator.py` 实现 format_final_summary() 函数
- [x] T076 [P] [US6] 在 `src/frago/init/configurator.py` 实现 suggest_next_steps() 函数
- [x] T077 [US6] 在 `src/frago/cli/init_command.py` 在流程结束时调用配置保存和摘要显示

**Checkpoint**: 所有用户故事完成并可独立测试

---

## Phase 9: Ctrl+C 恢复和错误处理（横切关注点）

**Purpose**: 实现 Ctrl+C 优雅中断、状态恢复和错误处理

- [x] T078 [P] 在 `src/frago/init/recovery.py` 实现 GracefulInterruptHandler 类
- [x] T079 [P] 在 `src/frago/init/recovery.py` 实现 load_temp_state() 函数
- [x] T080 [P] 在 `src/frago/init/recovery.py` 实现 save_temp_state() 函数
- [x] T081 [P] 在 `src/frago/init/recovery.py` 实现 delete_temp_state() 函数
- [x] T082 [P] 在 `src/frago/init/recovery.py` 实现 prompt_resume() 函数
- [x] T083 [P] 在 `tests/unit/init/test_recovery.py` 编写恢复逻辑测试
- [x] T084 [P] 在 `tests/unit/init/test_recovery.py` 编写状态过期测试
- [x] T085 [P] 在 `tests/integration/test_init_command.py` 编写 Ctrl+C 中断恢复集成测试
- [x] T086 在 `src/frago/cli/init_command.py` 集成 GracefulInterruptHandler（信号处理）
- [x] T087 在 `src/frago/cli/init_command.py` 实现启动时的状态恢复检测
- [x] T088 在 `src/frago/cli/init_command.py` 在每个步骤完成后更新临时状态

---

## Phase 10: CLI 选项和辅助功能

**Purpose**: 实现 --reset, --show-config, --skip-deps, --non-interactive 选项

- [x] T089 [P] 在 `src/frago/cli/init_command.py` 添加 --reset 选项（Click.option）
- [x] T090 [P] 在 `src/frago/cli/init_command.py` 添加 --show-config 选项
- [x] T091 [P] 在 `src/frago/cli/init_command.py` 添加 --skip-deps 选项
- [x] T092 [P] 在 `src/frago/cli/init_command.py` 添加 --non-interactive 选项
- [x] T093 [P] 在 `src/frago/init/configurator.py` 实现 --show-config 显示逻辑
- [x] T094 [P] 在 `tests/unit/init/test_init_command.py` 编写所有选项的测试
- [x] T095 [P] 在 `tests/integration/test_init_command.py` 编写 --reset 集成测试
- [x] T096 [P] 在 `tests/integration/test_init_command.py` 编写 --non-interactive 集成测试

---

## Phase 11: 错误消息和用户体验优化

**Purpose**: 实现标准化错误消息、彩色输出和进度提示

- [x] T097 [P] 在 `src/frago/init/formatter.py` 创建错误消息格式化模块
- [x] T098 [P] 在 `src/frago/init/formatter.py` 实现 format_error_message() 函数
- [x] T099 [P] 在 `src/frago/init/formatter.py` 实现 format_success_message() 函数
- [x] T100 [P] 在 `src/frago/init/formatter.py` 实现 format_dependency_status() 函数
- [x] T101 [P] 在 `src/frago/cli/init_command.py` 集成格式化的错误和成功消息
- [x] T102 [P] 在 `tests/unit/init/test_formatter.py` 编写格式化函数测试

---

## Phase 12: Polish & Cross-Cutting Concerns

**Purpose**: 完善和横切关注点

- [x] T103 [P] 在 `src/frago/init/__init__.py` 添加完整的模块文档字符串
- [x] T104 [P] 在所有 `src/frago/init/*.py` 文件添加类型注解（mypy 检查）
- [x] T105 [P] 运行 `black` 和 `ruff` 格式化所有新增代码
- [x] T106 [P] 在 `tests/integration/test_init_command.py` 添加边缘情况测试（网络错误、权限错误等）
- [x] T107 [P] 更新 `CLAUDE.md` 添加 init 命令使用说明
- [x] T108 验证 `specs/006-init-command/quickstart.md` 中的所有示例可运行
- [x] T109 运行完整测试套件确保 >= 80% 覆盖率：`uv run pytest --cov=frago.init --cov-report=term`
- [x] T110 在真实环境测试所有用户故事场景（全新系统、部分已装、已有配置）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可立即开始
- **Foundational (Phase 2)**: 依赖 Setup 完成 - **阻塞所有用户故事**
- **User Stories (Phase 3-8)**: 全部依赖 Foundational 完成
  - User stories 可并行进行（如果团队规模允许）
  - 或按优先级顺序（P1 → P2 → P3 → P4 → P5）
- **横切关注点 (Phase 9-11)**: 依赖核心用户故事（至少 US1）
- **Polish (Phase 12)**: 依赖所有期望的用户故事完成

### User Story Dependencies

- **User Story 1 (P1)**: Foundational 完成后即可开始 - 无其他故事依赖
- **User Story 2 (P2)**: 需要 US1 的 configurator 基础，但可独立测试
- **User Story 3 (P2)**: 需要 US2 的配置逻辑，但可独立测试
- **User Story 4 (P3)**: 扩展 US2 的认证配置，可独立测试
- **User Story 5 (P4)**: 独立功能，可独立测试
- **User Story 6 (P5)**: 整合所有故事的配置保存，可独立测试

### Within Each User Story

- Tests（如包含）必须先编写并失败
- Models 在 services 之前
- Services 在 CLI 集成之前
- 核心实现在集成之前
- 故事完成后再进入下一个优先级

### Parallel Opportunities

- Setup 阶段所有 [P] 任务可并行
- Foundational 阶段所有 [P] 任务可并行（在 Phase 2 内）
- Foundational 完成后，所有用户故事可并行开始（如果团队规模允许）
- 每个用户故事内的所有 tests 标记 [P] 可并行
- 每个用户故事内的 models 标记 [P] 可并行
- 不同用户故事可由不同团队成员并行工作

---

## Parallel Example: User Story 1

```bash
# 并行启动 User Story 1 的所有测试：
Task: "在 tests/unit/init/test_checker.py 编写 check_node_installed 测试"
Task: "在 tests/unit/init/test_checker.py 编写 check_claude_code_installed 测试"
Task: "在 tests/unit/init/test_checker.py 编写 parallel_dependency_check 测试"
Task: "在 tests/unit/init/test_installer.py 编写 install_node 测试（模拟 subprocess）"
Task: "在 tests/unit/init/test_installer.py 编写 install_claude_code 测试"
Task: "在 tests/integration/test_init_command.py 编写全新安装集成测试"

# 并行启动 User Story 1 的所有模型实现：
Task: "在 src/frago/init/checker.py 实现 check_node() 函数"
Task: "在 src/frago/init/checker.py 实现 check_claude_code() 函数"
Task: "在 src/frago/init/installer.py 实现 run_external_command() 包装器"
Task: "在 src/frago/init/installer.py 实现 install_node() 函数"
Task: "在 src/frago/init/installer.py 实现 install_claude_code() 函数"
```

---

## Parallel Example: User Story 2

```bash
# 并行启动 User Story 2 的所有测试：
Task: "在 tests/unit/init/test_configurator.py 编写 prompt_auth_method 测试"
Task: "在 tests/unit/init/test_configurator.py 编写 configure_official_auth 测试"
Task: "在 tests/unit/init/test_configurator.py 编写 configure_custom_endpoint 测试"
Task: "在 tests/unit/init/test_configurator.py 编写认证互斥性验证测试"
Task: "在 tests/integration/test_init_command.py 编写官方登录流程集成测试"
Task: "在 tests/integration/test_init_command.py 编写自定义端点流程集成测试"

# 并行启动 User Story 2 的所有配置实现：
Task: "在 src/frago/init/configurator.py 实现 prompt_auth_method() 使用 Click.choice"
Task: "在 src/frago/init/configurator.py 实现 configure_official_auth() 函数"
Task: "在 src/frago/init/configurator.py 实现 configure_custom_endpoint() 函数"
Task: "在 src/frago/init/configurator.py 实现 load_config() 和 save_config() 函数"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational（**关键** - 阻塞所有故事）
3. 完成 Phase 3: User Story 1
4. **停止并验证**: 独立测试 User Story 1
5. 如果就绪则部署/演示

### Incremental Delivery

1. 完成 Setup + Foundational → 基础就绪
2. 添加 User Story 1 → 独立测试 → 部署/演示（MVP!）
3. 添加 User Story 2 → 独立测试 → 部署/演示
4. 添加 User Story 3 → 独立测试 → 部署/演示
5. 每个故事增加价值而不破坏之前的故事

### Parallel Team Strategy

多开发者协作：

1. 团队共同完成 Setup + Foundational
2. Foundational 完成后：
   - 开发者 A: User Story 1
   - 开发者 B: User Story 2
   - 开发者 C: User Story 3
3. 故事独立完成和集成

---

## Summary

- **总任务数**: 110 个任务
- **User Story 1 (P1)**: 17 个任务（6 测试 + 11 实现）🎯 MVP
- **User Story 2 (P2)**: 12 个任务（6 测试 + 6 实现）
- **User Story 3 (P2)**: 9 个任务（4 测试 + 5 实现）
- **User Story 4 (P3)**: 11 个任务（5 测试 + 6 实现）
- **User Story 5 (P4)**: 9 个任务（4 测试 + 5 实现）
- **User Story 6 (P5)**: 7 个任务（3 测试 + 4 实现）
- **横切关注点**: 33 个任务（恢复、选项、格式化、完善）

**并行机会**: 约 70% 的任务标记为 [P]，可并行执行

**MVP 范围**: Phase 1 + Phase 2 + Phase 3 (User Story 1) = 34 个任务

**建议实施顺序**:
1. MVP（US1）→ 验证核心流程
2. 认证配置（US2）→ 完整可用
3. 配置更新（US3）→ 运维友好
4. 高级功能（US4-6）→ 按需添加

---

## Notes

- [P] 任务 = 不同文件，无依赖
- [Story] 标签将任务映射到特定用户故事以便追踪
- 每个用户故事应可独立完成和测试
- 实现前验证测试失败
- 每个任务或逻辑组后提交
- 在任何检查点停止以独立验证故事
- 避免：模糊任务、相同文件冲突、破坏独立性的跨故事依赖
