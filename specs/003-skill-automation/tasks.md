# Implementation Tasks: 技能自动化生成系统

**Feature**: 003-skill-automation
**Branch**: `003-skill-automation`
**Generated**: 2025-11-18
**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

---

## 任务概览

| 阶段 | 描述 | 任务数 | 用户故事 |
|------|------|--------|----------|
| Phase 1 | 项目设置 | 3 | Setup |
| Phase 2 | 基础设施 | 6 | Foundation |
| Phase 3 | US1 - 创建配方脚本 | 8 | P1 |
| Phase 4 | US2 - 知识文档生成 | 4 | P2 |
| Phase 5 | US3 - 配方迭代更新 | 5 | P3 |
| Phase 6 | 完善与优化 | 3 | Polish |

**总任务数**: 29

---

## 实施策略

### MVP范围（最小可行产品）

**仅User Story 1（Phase 3）** - 配方脚本创建核心功能

**MVP交付物**:
- 用户可通过 `/auvima.recipe create` 命令生成配方脚本
- 配方脚本能够在CDP环境中成功执行
- 基本的选择器策略和错误处理

**非MVP**:
- 知识文档生成（US2）- 可手动创建文档
- 配方更新功能（US3）- 可重新创建替代更新
- 配方库索引和高级搜索

### 增量交付

1. **Phase 1-2**: 搭建基础设施（1周）
2. **Phase 3**: 实现US1核心功能（2-3周）→ **MVP里程碑**
3. **Phase 4**: 添加知识文档（1周）
4. **Phase 5**: 实现迭代更新（1-2周）
5. **Phase 6**: 性能优化和边缘案例处理（1周）

**总预估**: 6-8周（根据实际测试反馈调整）

---

## 依赖关系

```
Phase 1 (Setup)
    ↓
Phase 2 (Foundation: 数据模型 + 选择器策略)
    ↓
    ├─→ Phase 3 (US1: 探索引擎 → 配方生成器 → CLI集成)
    │       ↓
    ├─→ Phase 4 (US2: 知识文档生成) [依赖US1]
    │       ↓
    └─→ Phase 5 (US3: 配方更新) [依赖US1 + US2]
            ↓
        Phase 6 (Polish)
```

### 并行执行机会

**Phase 2 (基础设施)**:
- T004 [P] 数据模型 ‖ T005 [P] 选择器策略 ‖ T006 [P] 模板系统

**Phase 3 (US1)**:
- T010 [P] Explorer测试 ‖ T012 [P] Generator测试（前提：T007-T009完成）
- T013 [P] Explorer实现 ‖ T014 [P] Generator实现（测试先行）

**Phase 4 (US2)**:
- T019 [P] Knowledge测试 ‖ T021 [P] 文档模板（独立模块）

---

## Phase 1: 项目设置

**目标**: 创建项目结构和配置

### 任务清单

- [x] T001 创建 `src/auvima/recipe/` 模块目录结构
- [x] T002 创建 `src/auvima/recipes/` 配方库目录
- [x] T003 创建测试目录结构 `tests/unit/recipe/` 和 `tests/integration/recipe/`

---

## Phase 2: 基础设施

**目标**: 实现共享数据模型和选择器策略

### 任务清单

- [x] T004 [P] 在 `src/auvima/recipe/models.py` 中实现核心数据模型（Recipe, Selector, ExplorationSession, ExplorationStep, KnowledgeDocument, UpdateRecord）使用Pydantic
- [x] T005 [P] 在 `src/auvima/recipe/selector.py` 中实现选择器优化策略（SelectorPriority枚举、稳定性评估、降级逻辑生成）
- [x] T006 [P] 在 `src/auvima/recipe/templates.py` 中创建JavaScript和Markdown模板基础类
- [x] T007 在 `src/auvima/recipe/__init__.py` 中导出公共接口
- [ ] T008 在 `tests/unit/recipe/test_models.py` 中编写数据模型验证测试（验证规则、状态转换）
- [ ] T009 在 `tests/unit/recipe/test_selector.py` 中编写选择器策略测试（优先级排序、降级生成）

---

## Phase 3: User Story 1 - 通过自然语言创建配方脚本 (P1)

**目标**: 实现核心配方创建功能

**独立测试标准**:
- 用户运行 `/auvima.recipe create "在YouTube视频页面提取字幕"`
- 系统生成 `src/auvima/recipes/youtube_extract_subtitles.js`
- 执行 `uv run auvima exec-js recipes/youtube_extract_subtitles.js` 成功返回字幕内容

### 任务清单

#### 3.1 探索引擎（ExplorationSession → ExplorationStep）

- [ ] T010 [P] [US1] 在 `tests/unit/recipe/test_explorer.py` 中编写探索引擎测试（会话创建、步骤记录、用户交互、元素定位）
- [ ] T011 [US1] 在 `tests/integration/recipe/test_explorer_cdp.py` 中编写CDP集成测试（使用mock CDP会话测试页面导航、元素查询、截图）
- [ ] T012 [P] [US1] 在 `src/auvima/recipe/explorer.py` 中实现 `RecipeExplorer` 类（会话管理、CDP交互、用户提问逻辑、元素定位与选择器提取）
- [ ] T013 [US1] 在 `explorer.py` 中实现交互式引导功能（使用AskUserQuestion工具、最多3次交互限制、候选元素展示）

#### 3.2 配方生成器（ExplorationSession → Recipe Script）

- [ ] T014 [P] [US1] 在 `tests/unit/recipe/test_generator.py` 中编写配方生成器测试（JavaScript代码生成、模板渲染、选择器降级逻辑、错误处理代码）
- [ ] T015 [US1] 在 `src/auvima/recipe/generator.py` 中实现 `RecipeGenerator` 类（从ExplorationSession生成JavaScript脚本、使用模板系统、注入选择器降级逻辑、添加错误处理）
- [ ] T016 [US1] 在 `templates.py` 中实现JavaScript配方脚本模板（等待元素、点击操作、内容提取、JSON返回格式）

#### 3.3 配方库管理（Recipe → Library）

- [ ] T017 [P] [US1] 在 `tests/unit/recipe/test_library.py` 中编写配方库管理测试（配方保存、命名冲突检测、配方列表、配方搜索）
- [ ] T018 [US1] 在 `src/auvima/recipe/library.py` 中实现 `RecipeLibrary` 类（配方保存、文件命名验证、配方列表、可选元数据索引）

#### 3.4 CLI集成

- [ ] T019 [US1] 在 `tests/integration/recipe/test_recipe_creation.py` 中编写端到端测试（完整的create流程：CLI输入 → 探索 → 生成 → 保存 → 执行验证）
- [ ] T020 [US1] 在 `src/auvima/cli/recipe_commands.py` 中实现 `recipe create` CLI命令（解析用户描述、创建Explorer实例、调用生成器、保存配方）
- [ ] T021 [US1] 在 `src/auvima/cli/main.py` 中注册recipe子命令组

---

## Phase 4: User Story 2 - 生成知识文档 (P2)

**目标**: 为每个配方自动生成标准化知识文档

**独立测试标准**:
- 配方脚本生成后自动创建配套.md文档
- 文档包含标准6章节：功能描述、使用方法、前置条件、预期输出、注意事项、更新历史
- 文档内容完整可读，技术细节从探索会话自动提取

### 任务清单

- [ ] T022 [P] [US2] 在 `tests/unit/recipe/test_knowledge.py` 中编写知识文档生成器测试（6章节模板渲染、从ExplorationSession提取信息、脆弱选择器标注、更新历史格式）
- [ ] T023 [US2] 在 `src/auvima/recipe/knowledge.py` 中实现 `KnowledgeGenerator` 类（生成6章节Markdown、自动填充内容、格式化代码块）
- [ ] T024 [P] [US2] 在 `templates.py` 中实现Markdown知识文档模板（6章节标准结构、前置条件checklist格式、输出JSON示例格式）
- [ ] T025 [US2] 在 `generator.py` 中集成知识文档生成（配方脚本保存后自动生成.md文档）
- [ ] T026 [US2] 在 `test_recipe_creation.py` 中添加知识文档验证测试（验证6章节存在、内容非空、格式正确）

---

## Phase 5: User Story 3 - 配方迭代更新 (P3)

**目标**: 支持配方脚本的版本迭代和更新

**独立测试标准**:
- 用户运行 `/auvima.recipe update youtube_extract_subtitles "字幕按钮选择器失效"`
- 系统重新探索页面，更新选择器
- 覆盖原.js文件，在.md的"更新历史"章节添加记录
- 更新后的配方脚本成功执行

### 任务清单

- [ ] T027 [P] [US3] 在 `tests/unit/recipe/test_library.py` 中添加配方更新测试（加载现有配方、版本号递增、更新历史追加）
- [ ] T028 [US3] 在 `library.py` 中实现 `load_recipe()` 方法（从.js和.md文件重建Recipe对象）
- [ ] T029 [US3] 在 `knowledge.py` 中实现更新历史追加功能（在"更新历史"章节添加UpdateRecord）
- [ ] T030 [US3] 在 `recipe_commands.py` 中实现 `recipe update` CLI命令（加载现有配方、重新探索、覆盖文件、更新文档）
- [ ] T031 [US3] 在 `tests/integration/recipe/test_recipe_update.py` 中编写端到端更新测试（完整的update流程：CLI输入 → 加载配方 → 重新探索 → 覆盖文件 → 验证更新历史）

---

## Phase 6: 完善与优化

**目标**: 边缘案例处理、性能优化、用户体验改进

### 任务清单

- [ ] T032 [P] 在 `recipe_commands.py` 中实现 `recipe list` CLI命令（列出所有配方、显示元数据、可选过滤）
- [ ] T033 在 `library.py` 中实现可选元数据索引功能（生成.index.json、增量更新、损坏重建）
- [ ] T034 在 `tests/integration/recipe/test_recipe_execution.py` 中编写配方执行验证测试（测试生成的配方在真实CDP环境中执行、验证错误处理、性能测量）
- [ ] T035 在 `explorer.py` 中添加边缘案例处理（动态加载检测、多页面流程、登录状态检查、探索超时）
- [ ] T036 在 `generator.py` 中优化生成的JavaScript代码（添加等待逻辑、改进错误消息、代码行数控制50-200行）
- [ ] T037 在 `spec.md` 文档中标注的Edge Cases章节中实现处理逻辑（网站结构频繁变化、动态加载内容、探索过程中断、多页面流程、权限和登录状态、脚本命名冲突、执行环境差异）

---

## 验证清单

### 每个用户故事的验证标准

#### User Story 1 (P1) - 配方创建

- [ ] 用户可通过自然语言描述创建配方
- [ ] 生成的JavaScript脚本在CDP环境中成功执行
- [ ] 探索过程中澄清问题不超过3个
- [ ] 配方脚本包含选择器降级逻辑和错误处理
- [ ] 配方文件名遵循命名规范（平台_操作_对象.js）
- [ ] 生成时间 <30秒（从探索完成到文件写入）

#### User Story 2 (P2) - 知识文档

- [ ] 每个配方脚本自动生成配套.md文档
- [ ] 文档包含标准6章节且内容完整
- [ ] 脆弱选择器在"注意事项"章节标注
- [ ] 文档可读性良好，代码块格式正确
- [ ] 前置条件以checklist格式呈现

#### User Story 3 (P3) - 配方更新

- [ ] 用户可更新失效的配方脚本
- [ ] 更新覆盖原文件且文件名保持不变
- [ ] 更新历史在.md中正确追加
- [ ] 版本号自动递增
- [ ] 更新后的配方脚本成功执行

### 跨故事验证

- [ ] 所有单元测试通过（pytest tests/unit/recipe/ -v）
- [ ] 所有集成测试通过（pytest tests/integration/recipe/ -v）
- [ ] 测试覆盖率 >80%（pytest --cov=auvima.recipe）
- [ ] 配方库规模达到5个示例配方（YouTube、GitHub、Twitter等）
- [ ] 性能符合约束（探索<5秒/步、生成<30秒、脚本50-200行）
- [ ] 符合Success Criteria SC-001至SC-008（见spec.md）

---

## 并行执行示例

### Phase 2并行任务

```bash
# 窗口1: 实现数据模型
# T004 [P] 数据模型
code src/auvima/recipe/models.py

# 窗口2: 实现选择器策略
# T005 [P] 选择器策略
code src/auvima/recipe/selector.py

# 窗口3: 实现模板系统
# T006 [P] 模板系统
code src/auvima/recipe/templates.py
```

### Phase 3并行任务（测试先行）

```bash
# 窗口1: 探索引擎测试
# T010 [P] [US1] Explorer测试
code tests/unit/recipe/test_explorer.py

# 窗口2: 生成器测试
# T014 [P] [US1] Generator测试
code tests/unit/recipe/test_generator.py

# 窗口3: 配方库测试
# T017 [P] [US1] Library测试
code tests/unit/recipe/test_library.py

# 测试编写完成后，并行实现
# 窗口1: T012 [P] [US1] Explorer实现
# 窗口2: T015 [US1] Generator实现
# 窗口3: T018 [US1] Library实现
```

---

## 注意事项

1. **测试驱动开发（TDD）**: 虽然spec未明确要求测试，但考虑到系统复杂性（CDP交互、文件生成、模板渲染），建议遵循TDD流程。每个模块先编写测试再实现。

2. **CDP Mock策略**: 集成测试中使用mock CDP会话，避免依赖真实浏览器。可使用 `unittest.mock` 或创建 `MockCDPSession` 类。

3. **任务ID连续性**: 任务ID T001-T037按执行顺序排列，实际实施时可能根据发现的新需求插入任务，保持顺序即可。

4. **并行标记[P]**: 仅在任务间无依赖且操作不同文件时标记。例如T004、T005、T006操作不同文件，可并行；T012和T013操作同一文件，需顺序执行。

5. **用户故事标签[US1/US2/US3]**: 帮助追踪每个任务属于哪个用户故事，便于验证故事完整性。设置和基础阶段无故事标签。

6. **MVP优先**: 如时间紧张，先完成Phase 1-3（US1），交付MVP。US2和US3可在后续迭代中添加。

7. **Edge Cases**: Phase 6的T037涵盖spec.md中列出的7种边缘案例，实施时应逐一验证处理逻辑。

---

## 文件路径速查

| 模块 | 文件路径 | 职责 |
|------|---------|------|
| 数据模型 | `src/auvima/recipe/models.py` | Pydantic模型定义 |
| 选择器策略 | `src/auvima/recipe/selector.py` | DOM选择器优先级和降级 |
| 模板系统 | `src/auvima/recipe/templates.py` | JavaScript和Markdown模板 |
| 探索引擎 | `src/auvima/recipe/explorer.py` | 交互式探索和CDP交互 |
| 配方生成器 | `src/auvima/recipe/generator.py` | JavaScript代码生成 |
| 知识文档 | `src/auvima/recipe/knowledge.py` | Markdown文档生成 |
| 配方库 | `src/auvima/recipe/library.py` | 配方管理和索引 |
| CLI命令 | `src/auvima/cli/recipe_commands.py` | `/auvima.recipe` 命令实现 |
| CLI注册 | `src/auvima/cli/main.py` | 注册recipe子命令 |
| 单元测试 | `tests/unit/recipe/test_*.py` | 各模块单元测试 |
| 集成测试 | `tests/integration/recipe/test_*.py` | 端到端流程测试 |
| 配方库目录 | `src/auvima/recipes/` | 存储生成的.js和.md文件 |

---

## 参考文档

- **功能规格**: [spec.md](./spec.md) - 用户故事、验收标准、边缘案例
- **实施计划**: [plan.md](./plan.md) - 技术栈、项目结构、性能约束
- **数据模型**: [data-model.md](./data-model.md) - 实体定义、验证规则、关系图
- **技术研究**: [research.md](./research.md) - JavaScript生成策略、选择器优化、交互模式
- **快速开始**: [quickstart.md](./quickstart.md) - 使用示例、测试场景
- **JSON Schema**: [contracts/](./contracts/) - 数据结构契约

---

**生成日期**: 2025-11-18
**总任务数**: 37
**预估工期**: 6-8周
**MVP范围**: Phase 1-3（User Story 1）

**下一步**: 执行 `/speckit.implement` 开始实施，或手动按任务ID顺序逐个完成。
