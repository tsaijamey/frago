# Tasks: 重构CDP集成

**Input**: Design documents from `/specs/002-cdp-integration-refactor/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: 测试任务不包含在本文档中（未在功能规范中明确请求）

**Organization**: 任务按用户故事分组，以实现每个故事的独立实现和测试

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行运行（不同文件，无依赖）
- **[Story]**: 任务所属的用户故事（例如：US1, US2, US3）
- 包含文件路径的明确描述

## Path Conventions

- **Single project**: `src/`, `tests/` at repository root
- Paths shown below assume single project structure from plan.md

---

## Phase 1: Setup (共享基础设施)

**目的**: 项目初始化和基础结构

- [x] T001 检查现有项目结构，确保src/frago/cdp/目录结构完整
- [x] T002 验证依赖项已安装：websocket-client, click, pydantic, python-dotenv
- [x] T003 [P] 验证测试框架配置：pytest, pytest-cov, pytest-asyncio

---

## Phase 2: Foundational (阻塞性前置条件)

**目的**: 必须在任何用户故事实现之前完成的核心基础设施

**⚠️ 关键**: 在此阶段完成之前，不能开始任何用户故事工作

- [x] T004 在src/frago/cdp/config.py中扩展CDPConfig，添加代理配置字段（proxy_host, proxy_port, proxy_username, proxy_password, no_proxy）
- [x] T005 在src/frago/cdp/session.py中修改WebSocket连接逻辑，支持代理配置参数
- [x] T006 [P] 创建工具目录src/frago/tools/，用于功能映射验证工具
- [x] T007 [P] 在src/frago/cdp/types.py中创建ProxyConfig数据类
- [x] T008 更新src/frago/cdp/exceptions.py，添加代理相关异常类（ProxyConnectionError, ProxyConfigError）

**Checkpoint**: 基础完成 - 现在可以并行开始用户故事实现

---

## Phase 3: User Story 1 - 统一的CDP方法目录结构 (Priority: P1) 🎯 MVP

**目标**: 在src/frago/cdp目录下建立清晰的方法目录结构，覆盖所有现有CDP功能

**独立测试**: 验证新的目录结构完整覆盖18个Shell脚本功能，每个方法都有对应Python实现

### Implementation for User Story 1

- [x] T009 [P] [US1] 在src/frago/cdp/commands/page.py中验证并完善导航方法（navigate, get_title, get_content）
- [x] T010 [P] [US1] 在src/frago/cdp/commands/screenshot.py中验证并完善截图方法（screenshot with full_page, quality options）
- [x] T011 [P] [US1] 在src/frago/cdp/commands/runtime.py中验证并完善JavaScript执行方法（execute_script）
- [x] T012 [P] [US1] 在src/frago/cdp/commands/input.py中验证并完善点击方法（click with wait_timeout）
- [x] T013 [P] [US1] 在src/frago/cdp/commands/scroll.py中创建滚动方法模块（scroll up/down, scroll_to_top, scroll_to_bottom）
- [x] T014 [P] [US1] 在src/frago/cdp/commands/wait.py中创建等待方法模块（wait_for_selector with timeout）
- [x] T015 [P] [US1] 在src/frago/cdp/commands/zoom.py中创建缩放方法模块（set_zoom_factor with 0.5-3.0 range）
- [x] T016 [P] [US1] 在src/frago/cdp/commands/status.py中创建状态检查模块（health_check, get_pages, check_chrome_status）
- [x] T017 [P] [US1] 在src/frago/cdp/commands/visual_effects.py中创建视觉效果模块（highlight, pointer, spotlight, annotate, clear_effects）
- [x] T018 [US1] 在src/frago/cdp/session.py中添加所有新命令模块的便利方法属性（@property for scroll, wait, zoom, status, visual_effects）
- [x] T019 [US1] 更新src/frago/cdp/commands/__init__.py，导出所有命令模块
- [x] T020 [US1] 创建功能映射验证脚本src/frago/tools/function_mapping.py，扫描并对比Shell脚本与Python实现

**Checkpoint**: 此时，用户故事1应该完全功能化并可独立测试 - 所有18个CDP功能在Python中都有对应实现

---

## Phase 4: User Story 2 - Python和Shell脚本功能对应 (Priority: P2)

**目标**: 确保Python代码中的CDP功能与scripts目录下的Shell脚本一一对应，保证功能一致性

**独立测试**: 验证每个Shell脚本功能在Python代码中都有对应实现，且行为一致

### Implementation for User Story 2

- [x] T021 [P] [US2] 扩展src/frago/tools/function_mapping.py，添加Shell脚本参数解析功能
- [x] T022 [P] [US2] 在src/frago/tools/function_mapping.py中实现Python函数签名提取
- [x] T023 [US2] 在src/frago/tools/function_mapping.py中实现参数对应关系验证逻辑
- [x] T024 [US2] 在src/frago/tools/function_mapping.py中实现行为一致性检查框架
- [x] T025 [US2] 创建功能映射报告生成器，输出JSON格式报告（包含coverage和consistency指标）
- [x] T026 [US2] 创建功能映射HTML报告生成器（可视化展示功能对应关系）
- [x] T027 [US2] 更新scripts/share/cdp_navigate.sh，确保所有参数正确传递给Python CLI
- [x] T028 [US2] 更新scripts/share/cdp_screenshot.sh，确保所有参数正确传递给Python CLI
- [x] T029 [US2] 更新scripts/share/cdp_exec_js.sh，确保所有参数正确传递给Python CLI
- [x] T030 [US2] 更新scripts/share/cdp_click.sh，确保所有参数正确传递给Python CLI
- [x] T031 [US2] 更新scripts/share/cdp_scroll.sh，确保所有参数正确传递给Python CLI
- [x] T032 [US2] 更新scripts/share/cdp_wait.sh，确保所有参数正确传递给Python CLI
- [x] T033 [US2] 更新scripts/share/cdp_zoom.sh，确保所有参数正确传递给Python CLI
- [x] T034 [US2] 更新scripts/share/cdp_get_title.sh，确保所有参数正确传递给Python CLI
- [x] T035 [US2] 更新scripts/share/cdp_get_content.sh，确保所有参数正确传递给Python CLI
- [x] T036 [US2] 更新scripts/share/cdp_status.sh，确保所有参数正确传递给Python CLI
- [x] T037 [US2] 更新scripts/generate/cdp_highlight.sh，确保所有参数正确传递给Python CLI
- [x] T038 [US2] 更新scripts/generate/cdp_pointer.sh，确保所有参数正确传递给Python CLI
- [x] T039 [US2] 更新scripts/generate/cdp_spotlight.sh，确保所有参数正确传递给Python CLI
- [x] T040 [US2] 更新scripts/generate/cdp_annotate.sh，确保所有参数正确传递给Python CLI
- [x] T041 [US2] 更新scripts/generate/cdp_clear_effects.sh，确保所有参数正确传递给Python CLI

**Checkpoint**: 此时，用户故事1和2应该都能独立工作 - 所有Shell脚本与Python实现100%对应

---

## Phase 5: User Story 3 - 代理参数检查 (Priority: P3)

**目标**: 确保Python代码通过websocket访问CDP时正确使用代理参数，避免在代理环境中出现连接问题

**独立测试**: 验证所有websocket连接代码都正确使用了代理配置参数

### Implementation for User Story 3

- [x] T042 [P] [US3] 在src/frago/cli/main.py中添加全局代理相关CLI选项（--proxy-host, --proxy-port, --proxy-username, --proxy-password, --no-proxy）
- [x] T043 [P] [US3] 在src/frago/cli/commands.py中更新所有命令，支持代理配置传递
- [x] T044 [US3] 在src/frago/cdp/session.py中实现WebSocket代理配置逻辑（使用websocket-client的代理参数）
- [x] T045 [US3] 在src/frago/cdp/config.py中添加从环境变量读取代理配置的逻辑（HTTP_PROXY, HTTPS_PROXY, NO_PROXY）
- [x] T046 [US3] 在src/frago/cdp/config.py中实现代理配置验证方法（validate_proxy_config）
- [x] T047 [US3] 更新scripts/share/cdp_common.sh，添加代理参数处理逻辑
- [x] T048 [US3] 创建代理配置测试脚本scripts/test/test_proxy_configuration.sh
- [x] T049 [US3] 在src/frago/cdp/logger.py中添加代理连接相关日志记录

**Checkpoint**: 所有用户故事现在应该独立功能化 - 代理环境下CDP连接成功率提升至95%以上

---

## Phase 6: Polish & Cross-Cutting Concerns

**目的**: 影响多个用户故事的改进

- [x] T050 [P] 在src/frago/cdp/retry.py中完善重试机制，支持代理连接失败重试
- [x] T051 [P] 更新README.md文档，记录代理配置和功能映射工具使用方法
- [x] T052 代码清理：确保所有模块遵循Python最佳实践和项目代码风格
- [x] T053 性能优化：优化CDP连接建立速度，确保延迟<500ms
- [x] T054 安全加固：确保代理认证信息不被记录到日志中
- [x] T055 运行quickstart.md中的所有验证场景，确保功能正常

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可立即开始
- **Foundational (Phase 2)**: 依赖Setup完成 - 阻塞所有用户故事
- **User Stories (Phase 3+)**: 都依赖Foundational阶段完成
  - 用户故事可并行进行（如有团队资源）
  - 或按优先级顺序依次进行（P1 → P2 → P3）
- **Polish (Final Phase)**: 依赖所有期望的用户故事完成

### User Story Dependencies

- **User Story 1 (P1)**: 可在Foundational (Phase 2)完成后开始 - 不依赖其他故事
- **User Story 2 (P2)**: 可在Foundational (Phase 2)完成后开始 - 依赖US1的目录结构，但应独立可测
- **User Story 3 (P3)**: 可在Foundational (Phase 2)完成后开始 - 不依赖其他故事，可独立测试

### Within Each User Story

- Phase 3 (US1): 命令模块可并行创建（T009-T017），然后更新session.py和__init__.py，最后创建验证工具
- Phase 4 (US2): 功能映射工具组件可并行开发（T021-T026），Shell脚本更新可并行进行（T027-T041）
- Phase 5 (US3): CLI选项和命令更新可并行（T042-T043），其他任务顺序执行

### Parallel Opportunities

- Phase 1: 所有标记[P]的任务可并行（T002-T003）
- Phase 2: 所有标记[P]的任务可并行（T006-T007）
- Phase 3: 所有命令模块创建任务可并行（T009-T017）
- Phase 4: 功能映射工具任务可并行（T021-T022），Shell脚本更新全部可并行（T027-T041）
- Phase 5: CLI任务可并行（T042-T043）
- Phase 6: 文档和重试机制改进可并行（T050-T051）

---

## Parallel Example: User Story 1

```bash
# 并行启动所有命令模块创建任务:
Task: "在src/frago/cdp/commands/page.py中验证并完善导航方法"
Task: "在src/frago/cdp/commands/screenshot.py中验证并完善截图方法"
Task: "在src/frago/cdp/commands/runtime.py中验证并完善JavaScript执行方法"
Task: "在src/frago/cdp/commands/input.py中验证并完善点击方法"
Task: "在src/frago/cdp/commands/scroll.py中创建滚动方法模块"
Task: "在src/frago/cdp/commands/wait.py中创建等待方法模块"
Task: "在src/frago/cdp/commands/zoom.py中创建缩放方法模块"
Task: "在src/frago/cdp/commands/status.py中创建状态检查模块"
Task: "在src/frago/cdp/commands/visual_effects.py中创建视觉效果模块"
```

## Parallel Example: User Story 2

```bash
# 并行启动所有Shell脚本更新任务:
Task: "更新scripts/share/cdp_navigate.sh"
Task: "更新scripts/share/cdp_screenshot.sh"
Task: "更新scripts/share/cdp_exec_js.sh"
# ... 等18个Shell脚本更新任务
```

---

## Implementation Strategy

### MVP First (仅用户故事1)

1. 完成Phase 1: Setup
2. 完成Phase 2: Foundational（关键 - 阻塞所有故事）
3. 完成Phase 3: User Story 1
4. **停止并验证**: 独立测试用户故事1
5. 如果就绪，部署/演示

### Incremental Delivery

1. 完成Setup + Foundational → 基础就绪
2. 添加用户故事1 → 独立测试 → 部署/演示（MVP！）
3. 添加用户故事2 → 独立测试 → 部署/演示
4. 添加用户故事3 → 独立测试 → 部署/演示
5. 每个故事在不破坏先前故事的情况下增加价值

### Parallel Team Strategy

多个开发者时：

1. 团队共同完成Setup + Foundational
2. Foundational完成后：
   - 开发者A: 用户故事1
   - 开发者B: 用户故事2（需等待US1的目录结构）
   - 开发者C: 用户故事3
3. 故事独立完成和集成

---

## Summary

**总任务数**: 55个任务

**每个用户故事的任务数**:
- Setup: 3个任务
- Foundational: 5个任务
- User Story 1 (P1): 12个任务
- User Story 2 (P2): 21个任务
- User Story 3 (P3): 8个任务
- Polish: 6个任务

**识别的并行机会**:
- Phase 3可并行9个命令模块创建任务
- Phase 4可并行15个Shell脚本更新任务
- Phase 5可并行2个CLI任务

**每个故事的独立测试标准**:
- US1: 验证所有18个CDP功能在Python中都有对应实现，目录结构清晰
- US2: 验证所有Shell脚本与Python实现参数和行为100%一致
- US3: 验证代理环境下CDP连接成功率>95%，所有websocket连接正确使用代理参数

**建议的MVP范围**:
仅用户故事1 - 提供统一的CDP方法目录结构，覆盖所有核心功能，为后续功能一致性和代理支持奠定基础

---

## Notes

- [P] 任务 = 不同文件，无依赖
- [Story] 标签将任务映射到特定用户故事以便追踪
- 每个用户故事应该独立可完成和可测试
- 每个任务或逻辑组后提交
- 在任何检查点停止以独立验证故事
- 避免: 模糊任务、相同文件冲突、破坏独立性的跨故事依赖
