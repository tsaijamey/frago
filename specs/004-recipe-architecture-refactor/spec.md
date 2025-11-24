# Feature Specification: Recipe 系统架构重构

**Feature Branch**: `004-recipe-architecture-refactor`
**Created**: 2025-11-20
**Status**: Draft
**Input**: User description: "重构Recipe系统架构：分离代码与资源，建立语言无关的编排能力"

## 澄清

### 会话 2025-11-20

- Q: Recipe 系统的主要使用者是谁？ → A: 混合模式 - 既支持 AI Agent（Claude Code）作为主要使用者通过 Bash 工具调用，也支持人类用户手动执行 CLI 命令
- Q: AI Agent 调用 Recipe 的主要接口方式？ → A: Bash 工具直接调用（`uv run frago recipe ...`），但要求 Recipe 元数据（YAML）中明确声明输出形态，让 AI 能预期产出
- Q: Workflow Recipe 的创建方式？ → A: AI 通过 `/frago.recipe` 命令自动生成 Workflow，用户仅需描述意图，AI 生成包含循环、条件、错误处理的完整脚本
- Q: Recipe 的输出形态如何声明？ → A: 在元数据中声明支持的输出形态（`output_targets: [stdout, file, clipboard]`），CLI 命令提供对应选项（`--output-file`, `--output-clipboard`）
- Q: AI 如何发现和选择合适的 Recipe？ → A: Recipe 元数据包含语义描述字段（`description`, `use_cases`, `tags`），AI 通过 `recipe list` 查看并理解每个 Recipe 的能力后自主选择

## User Scenarios & Testing *(mandatory)*

### User Story 0 - AI Agent 自动创建和使用 Recipe（Priority: P0 - 核心愿景）

作为 **Claude Code AI Agent**，我希望能够：
1. 根据用户意图自动生成原子 Recipe 或编排 Workflow（通过 `/frago.recipe` 命令）
2. 通过 `recipe list` 发现现有 Recipe 的功能和输出形态
3. 使用 Bash 工具调用 Recipe（`uv run frago recipe run`），并明确预期输出去向（stdout/file/clipboard）
4. 规划任务执行路径时，组合使用多个 Recipe 完成复杂任务

**Why this priority**: 这是 Frago 的核心差异化价值 - AI 驱动的自动化，而非人类手动操作工具。Recipe 系统必须设计为"AI 可理解、可调度的工具集"。

**Independent Test**: AI 接收任务"批量提取 10 个 Upwork 职位信息并保存为 Markdown 文件"，自动完成：1) 通过 `recipe list` 发现 `upwork_extract_job` Recipe；2) 判断需要编排 Workflow；3) 通过 `/frago.recipe` 生成批量处理 Workflow；4) 执行 Workflow 并输出到文件。

**Acceptance Scenarios**:

1. **Given** AI 收到任务"提取 YouTube 视频字幕"，**When** AI 执行 `uv run frago recipe list --format json`，**Then** 返回包含 `youtube_extract_video_transcript` Recipe 的 JSON，明确标注 `description`, `use_cases`, `output_targets`
2. **Given** AI 发现 `youtube_extract_video_transcript` Recipe 支持 `output_targets: [stdout, file]`，**When** AI 需要将结果保存为文件，**Then** 执行 `uv run frago recipe run youtube_extract_video_transcript --params '{...}' --output-file transcript.txt`
3. **Given** AI 需要批量处理多个视频，**When** AI 调用 `/frago.recipe create workflow "批量提取 YouTube 字幕"`，**Then** AI 自动生成包含循环、错误处理的 Workflow Recipe 并保存到用户目录
4. **Given** AI 生成的 Workflow 执行失败，**When** 系统返回结构化错误（JSON 格式），**Then** AI 能理解错误原因并调整执行策略或报告给用户

---

### User Story 1 - 创建跨语言 Recipe（Priority: P1）

作为 Frago 用户（人类或 AI），我希望能用不同的编程语言（JavaScript、Python、Shell）创建 Recipe，系统能统一调用和管理这些 Recipe，无需关心底层实现语言。

**Why this priority**: 这是整个架构重构的核心价值。支持多语言 Recipe 是未来扩展能力的基础（Chrome CDP、AT-SPI、系统操作等）。

**Independent Test**: 创建三种语言的简单 Recipe（JS 提取网页标题、Python 读取剪贴板、Shell 复制文件），通过统一命令成功执行所有三个 Recipe。

**Acceptance Scenarios**:

1. **Given** 用户编写了一个 JavaScript Recipe（`chrome/get_title.js`）并配置了元数据文件（`.md`），**When** 用户执行 `uv run frago recipe run get_title`，**Then** Recipe 成功执行并返回 JSON 格式的网页标题
2. **Given** 用户编写了一个 Python Recipe（`system/clipboard_read.py`），**When** 用户执行 `uv run frago recipe run clipboard_read`，**Then** Recipe 成功执行并返回 JSON 格式的剪贴板内容
3. **Given** 用户编写了一个 Shell Recipe（`system/file_copy.sh`），**When** 用户执行 `uv run frago recipe run file_copy --params '{"src": "/tmp/a", "dst": "/tmp/b"}'`，**Then** Recipe 成功执行并返回操作结果
4. **Given** Recipe 执行失败（如文件不存在），**When** 系统捕获错误，**Then** 返回统一格式的错误信息（包含错误类型、消息、Recipe 名称）

---

### User Story 2 - 代码与资源分离（Priority: P1）

作为 Frago 开发者，我希望将 Frago Python 包代码与用户的 Recipe 资源完全分离，使得用户可以在自己的目录管理 Recipe，而不影响包的升级和分发。

**Why this priority**: 代码与资源混在一起会导致打包困难、用户无法持久化自定义 Recipe、升级覆盖用户数据等严重问题。这是架构清晰性的基础。

**Independent Test**: 安装 Frago 后，用户在 `~/.frago/recipes/` 创建自定义 Recipe，卸载并重新安装 Frago，自定义 Recipe 依然可用。

**Acceptance Scenarios**:

1. **Given** Frago 已安装，**When** 用户首次运行 `uv run frago init`，**Then** 系统在 `~/.frago/recipes/` 创建目录结构（`atomic/chrome/`, `atomic/system/`, `workflows/`）
2. **Given** 用户在 `~/.frago/recipes/atomic/chrome/` 创建了 Recipe，**When** 执行 `uv run frago recipe list`，**Then** 列表显示该 Recipe 并标注为 `[User]` 来源
3. **Given** Frago 包含官方示例 Recipe（位于 `examples/atomic/chrome/`），**When** 用户执行 `uv run frago recipe list`，**Then** 同时显示用户 Recipe 和示例 Recipe，清晰区分来源（`[User]` / `[Example]`）
4. **Given** 用户想复用官方示例，**When** 执行 `uv run frago recipe copy upwork_extract_job`，**Then** 示例 Recipe 被复制到 `~/.frago/recipes/atomic/chrome/` 供用户修改

---

### User Story 3 - 编排多个 Recipe 的工作流（Priority: P2）

作为 Frago 用户，我希望能创建一个编排 Recipe（Workflow），在其中调用多个原子 Recipe，实现复杂的自动化流程（如批量提取多个网页、混合操作浏览器和系统应用）。

**Why this priority**: 单个 Recipe 只能完成单一任务，真实场景需要循环、条件判断、多 Recipe 组合。Workflow 提供了这种编排能力。

**Independent Test**: 创建一个 Workflow Recipe（`workflows/upwork_batch_extract.py`），在其中循环调用 `upwork_extract_job` Recipe 提取 10 个职位，成功生成汇总结果。

**Acceptance Scenarios**:

1. **Given** 用户创建了一个 Workflow Recipe（Python 文件），**When** 在代码中调用 `runner.run('upwork_extract_job', {'url': '...'})`，**Then** 原子 Recipe 被成功调用并返回结果
2. **Given** Workflow 中需要循环处理 10 个 URL，**When** 使用 Python 的 `for` 循环调用原子 Recipe，**Then** 所有调用按顺序执行，返回结果数组
3. **Given** Workflow 需要混合调用不同语言的 Recipe（JS 提取数据 + Python 操作本地应用），**When** 依次调用两个 Recipe，**Then** 数据能在 Recipe 间传递（通过 JSON 输入输出）
4. **Given** Workflow 执行过程中某个原子 Recipe 失败，**When** 系统抛出异常，**Then** Workflow 可以捕获异常并记录错误日志（或继续处理其他项目）

---

### User Story 4 - Recipe 元数据管理（Priority: P2）

作为 Frago 用户，我希望每个 Recipe 都有清晰的元数据（输入参数、输出格式、运行时类型、版本号），系统能自动校验和提示，避免错误调用。

**Why this priority**: 元数据驱动的设计让 Recipe 自描述，降低使用门槛，提升可维护性。

**Independent Test**: 创建一个带有完整元数据的 Recipe（`.md` 文件包含 YAML frontmatter），执行 `uv run frago recipe info <name>` 显示所有元数据信息。

**Acceptance Scenarios**:

1. **Given** Recipe 的 `.md` 文件定义了 `inputs: {url: {type: string, required: true}}`，**When** 用户执行时未提供 `url` 参数，**Then** 系统报错提示缺少必需参数
2. **Given** Recipe 元数据定义了 `runtime: chrome-js`，**When** 用户执行 Recipe，**Then** 系统自动选择正确的执行器（`_run_chrome_js`）
3. **Given** 用户想查看某个 Recipe 的详细信息，**When** 执行 `uv run frago recipe info upwork_extract_job`，**Then** 显示名称、类型、运行时、输入输出定义、版本号、文档说明
4. **Given** 多个 Recipe 有依赖关系（Workflow 依赖原子 Recipe），**When** 查看 Workflow 元数据，**Then** 显示依赖的 Recipe 列表（从元数据中提取）

---

### User Story 5 - 项目级 Recipe 支持（Priority: P3）

作为在特定项目中使用 Frago 的用户，我希望能在项目目录下创建项目专属的 Recipe（位于 `.frago/recipes/`），与全局 Recipe 隔离，避免污染用户级配置。

**Why this priority**: 不同项目有不同的自动化需求，项目级 Recipe 提供了隔离性和可移植性（可随项目代码一起版本控制）。

**Independent Test**: 在项目目录创建 `.frago/recipes/workflows/project_workflow.py`，执行 `uv run frago recipe run project_workflow`，系统优先使用项目级 Recipe。

**Acceptance Scenarios**:

1. **Given** 用户在项目根目录创建 `.frago/recipes/workflows/custom.py`，**When** 在项目目录执行 `uv run frago recipe run custom`，**Then** 系统优先使用项目级 Recipe
2. **Given** 项目级和用户级存在同名 Recipe，**When** 执行 Recipe，**Then** 系统按优先级选择（项目级 > 用户级 > 示例级），并在日志中提示使用的来源
3. **Given** 用户切换到项目外的目录，**When** 执行项目级 Recipe，**Then** 系统提示 Recipe 未找到（因为已离开项目目录）
4. **Given** 用户将项目提交到 Git，**When** 其他人克隆项目，**Then** 项目级 Recipe 一起被克隆，可直接使用

---

### Edge Cases

- Recipe 元数据文件（`.md`）与脚本文件（`.js`/`.py`/`.sh`）不匹配（名称不一致）时，系统如何处理？
- 用户创建的 Recipe 没有对应的元数据文件，系统是否允许执行？
- Workflow Recipe 调用了不存在的原子 Recipe，错误信息如何提示？
- 同一个 Recipe 同时在三个位置存在（项目级、用户级、示例级），系统如何决定优先级并提示用户？
- Recipe 执行超时或卡死，系统是否有超时机制？
- Recipe 输出的 JSON 格式不合法（如语法错误），系统如何处理？
- 用户修改了示例 Recipe（位于 `examples/`），升级 Frago 后修改是否会丢失？
- Recipe 运行时类型（`runtime` 字段）拼写错误或不支持，系统如何报错？

## Requirements *(mandatory)*

### Functional Requirements

#### 核心架构（P1）

- **FR-001**: 系统必须支持三种 Recipe 运行时：`chrome-js`（通过 `uv run frago exec-js` 执行）、`python`（通过 Python 解释器执行）、`shell`（通过 Shell 执行）
- **FR-002**: 所有 Recipe 必须遵循统一的输入输出协议：通过 JSON 格式传递参数（CLI 参数或 stdin），输出 JSON 格式结果到 stdout
- **FR-003**: 每个 Recipe 必须有对应的元数据文件（`.md`），包含 YAML frontmatter 定义，**必需字段**：`name`, `type`, `runtime`, `inputs`, `outputs`, `version`，**AI 可理解字段**：`description`, `use_cases`, `tags`, `output_targets`
- **FR-004**: 系统必须提供 `RecipeRunner` 类，能根据元数据自动选择执行器（`_run_chrome_js`, `_run_python`, `_run_shell`）并调用 Recipe
- **FR-005**: 系统必须支持三级 Recipe 查找路径：项目级（`.frago/recipes/`）> 用户级（`~/.frago/recipes/`）> 示例级（`examples/`）
- **FR-006**: 系统必须在用户首次运行 `uv run frago init` 时创建用户级 Recipe 目录结构（`~/.frago/recipes/atomic/chrome/`, `atomic/system/`, `workflows/`）
- **FR-007**: 系统必须提供 `uv run frago recipe list` 命令，支持 `--format json` 输出结构化数据，包含每个 Recipe 的 `name`, `type`, `description`, `use_cases`, `tags`, `output_targets` 字段，便于 AI 解析和选择
- **FR-008**: 系统必须提供 `uv run frago recipe info <name>` 命令，显示指定 Recipe 的完整元数据（包括 AI 可理解的语义字段）
- **FR-009**: 系统必须提供 `uv run frago recipe run <name>` 命令，支持以下输出选项：`--output-file <path>`（保存到文件）、`--output-clipboard`（复制到剪贴板）、默认输出到 stdout
- **FR-010**: 系统必须提供 `uv run frago recipe copy <name>` 命令，将示例 Recipe 复制到用户级目录供修改

#### AI 集成（P0 - 核心）

- **FR-016**: Recipe 元数据必须包含 `description` 字段（简短功能描述，<200 字符），帮助 AI 理解 Recipe 的用途
- **FR-017**: Recipe 元数据必须包含 `use_cases` 字段（数组，列举适用场景，如 `["提取网页数据", "批量处理"]`），帮助 AI 判断是否适用于当前任务
- **FR-018**: Recipe 元数据必须包含 `output_targets` 字段（数组，枚举值：`stdout`, `file`, `clipboard`），明确声明支持的输出去向
- **FR-019**: Recipe 元数据可选包含 `tags` 字段（数组，如 `["web-scraping", "upwork", "job-market"]`），用于语义分类和搜索
- **FR-020**: `/frago.recipe` 命令必须支持生成 Workflow Recipe，接受自然语言描述（如 `/frago.recipe create workflow "批量提取 10 个 Upwork 职位"`），AI 自动生成包含循环、错误处理的 Python 脚本

#### 其他功能

- **FR-011**: 系统必须支持 Workflow Recipe（Python 文件），能通过 `RecipeRunner.run()` 方法调用其他原子 Recipe
- **FR-012**: Recipe 执行失败时，系统必须返回统一格式的错误信息（JSON 格式，包含 `success: false`, `error: {type, message, recipe_name, stdout, stderr}`）
- **FR-013**: 系统必须将现有的 `src/frago/recipes/` 目录内容迁移到 `examples/atomic/chrome/`，并在 `src/frago/recipes/` 创建引擎代码（`runner.py`, `registry.py`）
- **FR-014**: Python 包打包配置（`pyproject.toml`）必须排除 `examples/` 目录，确保用户 Recipe 不被打包进 wheel 文件
- **FR-015**: Recipe 元数据必须支持依赖声明（`dependencies: [recipe1, recipe2]`），系统在执行前检查依赖是否存在

### Key Entities

- **Recipe**: 代表一个可执行的自动化脚本，包含脚本文件（`.js`/`.py`/`.sh`）和元数据文件（`.md`）
  - 属性：名称、类型（atomic/workflow）、运行时（chrome-js/python/shell）、输入参数定义、输出格式定义、版本号、依赖 Recipe 列表
  - 分类：原子 Recipe（单一任务，无依赖）、编排 Recipe（调用多个原子 Recipe，包含业务逻辑）

- **RecipeMetadata**: Recipe 的元数据，从 `.md` 文件的 YAML frontmatter 解析
  - 属性：name（Recipe 名称）、type（atomic/workflow）、runtime（执行器类型）、inputs（参数定义）、outputs（返回值定义）、version（版本号）、dependencies（依赖 Recipe 列表）

- **RecipeRegistry**: Recipe 注册表，负责扫描三个位置的 Recipe 并构建索引
  - 属性：search_paths（查找路径列表）、recipes（Recipe 名称到元数据的映射）
  - 行为：扫描目录、解析元数据、处理同名 Recipe 优先级

- **RecipeRunner**: Recipe 执行器，负责调用不同语言的 Recipe
  - 属性：registry（Recipe 注册表）
  - 行为：根据 runtime 选择执行器、传递 JSON 参数、解析 JSON 输出、处理错误

## Success Criteria *(mandatory)*

### Measurable Outcomes

#### AI 可用性（核心）

- **SC-001**: AI Agent 能通过 `recipe list --format json` 在 1 秒内获取所有 Recipe 的结构化元数据（包括 `description`, `use_cases`, `output_targets`），并基于语义理解选择合适的 Recipe
- **SC-002**: AI Agent 通过 `/frago.recipe` 命令生成的 Workflow Recipe 能 100% 成功执行（包含正确的循环、错误处理、Recipe 调用）
- **SC-003**: AI Agent 能根据 Recipe 元数据中的 `output_targets` 字段，正确选择输出方式（`--output-file` / `--output-clipboard` / stdout），成功率 > 95%
- **SC-004**: Recipe 执行失败时，返回的 JSON 错误信息能让 AI 理解失败原因并采取正确的应对策略（重试、调整参数、报告用户），成功率 > 90%

#### 系统性能

- **SC-005**: 系统支持至少 50 个 Recipe 的注册和快速查找（`recipe list` 命令响应时间 < 1 秒）
- **SC-006**: Workflow Recipe 可以成功调用 10 个以上的原子 Recipe，总执行时间线性增长（执行器调度开销 < 200ms）
- **SC-007**: 用户在不同项目间切换时，系统能正确识别和使用项目级 Recipe（100% 准确率）

#### 兼容性与稳定性

- **SC-008**: Frago 升级后，用户的自定义 Recipe（位于 `~/.frago/recipes/`）100% 保持可用（无数据丢失）
- **SC-009**: 代码与资源完全分离后，Frago Python 包体积减少（示例 Recipe 不打包），安装速度提升 20%
- **SC-010**: 官方示例 Recipe 覆盖三种语言（至少各 2 个示例）和三种输出形态（stdout, file, clipboard），元数据完整性 100%

## Assumptions

### 环境假设

- 用户已安装 Python 3.9+ 和 `uv` 包管理工具
- 用户环境中可用 Node.js（如需执行 JavaScript Recipe）
- 用户有权限创建 `~/.frago/` 目录（家目录写权限）
- Recipe 脚本文件具有可执行权限（Shell 和 Python Recipe）
- 项目级 Recipe 位于项目根目录下的 `.frago/recipes/`（通过当前工作目录判断）

### AI Agent 假设

- **主要使用者是 Claude Code AI Agent**，通过 Bash 工具调用 `uv run frago` 命令
- AI Agent 能理解 JSON 格式的元数据和输出，并基于语义描述（`description`, `use_cases`）选择合适的 Recipe
- AI Agent 通过 `/frago.recipe` 命令生成的 Recipe 代码是可执行的（AI 理解 Python/JavaScript/Shell 语法）
- AI Agent 能根据任务需求自主决定输出去向（文件、剪贴板、stdout）
- 人类用户也可以手动执行 CLI 命令，但这是次要使用场景

### 数据与协议假设

- Recipe 元数据的 YAML frontmatter 遵循标准语法（由 Python `yaml` 库解析）
- Recipe 输出的 JSON 不超过合理大小（如 10MB），避免内存问题
- 不同语言的 Recipe 间通过 JSON 传递数据，不支持复杂对象（如函数、类实例）
- Recipe 的 `output_targets` 字段真实反映其能力（如声明支持 `clipboard` 则脚本内部实现了剪贴板操作）

## Dependencies

- Python 库：`pyyaml`（解析 YAML frontmatter）、`click`（CLI 命令）、`pathlib`（路径处理）
- 现有 Frago 模块：`frago.cdp`（Chrome CDP 操作）、`frago.cli`（CLI 框架）
- 外部工具：Node.js（执行 JavaScript Recipe，可选）、Bash/Zsh（执行 Shell Recipe）
- 已有的 Recipe 脚本（位于 `src/frago/recipes/`），需迁移到 `examples/atomic/chrome/`

## Out of Scope

- Recipe 的可视化编辑器（当前版本仅支持文本编辑）
- Recipe 的版本控制和回滚机制（由用户通过 Git 管理）
- Recipe 的权限控制和沙箱隔离（假设用户信任自己的 Recipe）
- Recipe 的远程仓库和分享平台（未来可扩展）
- Recipe 执行的实时日志流（当前仅返回最终结果和错误）
- Recipe 的性能监控和统计（如执行时间、成功率等）
- Recipe 的依赖自动安装（如 Python 库、npm 包，需用户手动安装）
- 跨平台兼容性测试（当前主要支持 Linux，macOS 和 Windows 未全面测试）
