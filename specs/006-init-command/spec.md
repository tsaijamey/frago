# Feature Specification: Frago 环境初始化命令

**Feature Branch**: `006-init-command`
**Created**: 2025-11-25
**Status**: Draft
**Input**: User description: "当前项目还缺少 init 命令, 该命令应该用在用户通过 uv tool install frago 后,对其本地环境进行初始化"

## 澄清

### 会话 2025-11-25

- Q: 初始化检查顺序 → A: 并行检查所有依赖（Node.js 和 Claude Code），然后根据缺失的组件批量安装
- Q: 所有依赖已满足时的行为 → A: 显示当前配置状态，询问用户是否需要更新配置（API 端点、CCR 设置等）
- Q: Claude Code 官方登录与自定义端点的关系 → A: 互斥选择 - 用户要么使用官方 Claude Code 登录，要么配置自定义端点，两者不能同时存在
- Q: 安装失败后的恢复策略 → A: 任何安装步骤失败立即终止整个 init 流程，提示用户手动修复后重新运行
- Q: 用户主动退出（Ctrl+C）与安装失败的处理差异 → A: 区分对待 - 主动 Ctrl+C 保存进度可恢复，安装失败则完全终止并提示修复

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 并行依赖检查和智能安装 (Priority: P1)

新用户在通过 `uv tool install frago` 安装 Frago 后，需要立即能够使用该工具。系统应并行检测所有依赖（Node.js 和 Claude Code）的状态，根据检测结果智能决定需要安装的组件，避免不必要的操作。

**Why this priority**: 这是所有后续功能的基础。通过并行检查，用户可以快速了解当前环境状态，只安装缺失的组件，提供最优的初始化体验。

**Independent Test**: 在全新的系统上运行 `frago init`，系统能够：
1. 并行检查 Node.js 和 Claude Code 的安装状态
2. 显示检测结果摘要（哪些已安装，哪些缺失）
3. 询问用户是否安装缺失的组件
4. 根据依赖关系顺序安装（先 Node.js，后 Claude Code）
5. 验证所有安装成功

**Acceptance Scenarios**:

1. **Given** 用户系统上既没有 Node.js 也没有 Claude Code, **When** 用户运行 `frago init`, **Then** 系统并行检测后显示"需要安装：Node.js 20+, Claude Code"，询问是否继续
2. **Given** 用户系统上已有 Node.js 20+ 但没有 Claude Code, **When** 用户运行 `frago init`, **Then** 系统显示"Node.js ✓ (v20.x), 需要安装：Claude Code"，仅安装 Claude Code
3. **Given** 用户系统上已有 Claude Code 但 Node.js 版本低于 20, **When** 用户运行 `frago init`, **Then** 系统提示"Claude Code ✓, Node.js 需要升级 (当前 v18.x → 要求 v20+)"
4. **Given** 用户系统上已安装 Node.js 20+ 和 Claude Code, **When** 用户运行 `frago init`, **Then** 系统显示"所有依赖已满足 ✓"，跳转到配置更新流程
5. **Given** 任何安装步骤失败, **When** 安装过程出错, **Then** 系统立即终止流程，显示错误详情和手动修复建议，不保存部分进度

---

### User Story 2 - 认证方式选择（互斥配置） (Priority: P2)

用户在依赖安装完成后，需要选择如何认证 Claude API：使用官方 Claude Code 登录，或配置自定义 API 端点。两种方式互斥，用户必须选择其中一种。

**Why this priority**: 认证配置是使用 Frago 的前提。通过明确的互斥选择，避免配置冲突，简化用户决策流程。

**Independent Test**: 运行 `frago init`，在依赖检查完成后：
1. 系统显示两种认证方式选项
2. 用户选择官方登录或自定义端点
3. 根据选择引导完成相应配置
4. 配置保存到 `~/.frago/config.json`，标记选择的认证方式

**Acceptance Scenarios**:

1. **Given** 依赖安装完成, **When** 系统进入认证配置, **Then** 系统显示选项："(A) 使用官方 Claude Code 登录" 和 "(B) 配置自定义 API 端点"
2. **Given** 用户选择官方登录, **When** 系统处理选择, **Then** 系统提示运行 `claude-code login` 并等待用户完成，保存认证方式为 "official"
3. **Given** 用户选择自定义端点, **When** 系统处理选择, **Then** 系统进入端点配置流程，保存认证方式为 "custom"，且禁用官方登录选项
4. **Given** 已配置官方登录的用户重新运行 init, **When** 用户选择更新为自定义端点, **Then** 系统警告"将覆盖现有官方登录配置"，需确认后继续

---

### User Story 3 - 已有配置时的更新流程 (Priority: P2)

用户在所有依赖已满足且配置文件已存在时重新运行 `frago init`，系统应显示当前配置状态，并询问用户是否需要更新特定配置项（如更换 API 端点、启用/禁用 CCR 等）。

**Why this priority**: 支持配置更新是重要的运维需求。用户可能需要切换 API 端点、更新凭证或调整设置，而无需完全重新初始化。

**Independent Test**: 在已有完整配置的系统上运行 `frago init`：
1. 系统检测到所有依赖已满足
2. 系统读取并显示当前配置摘要
3. 询问用户是否需要更新配置
4. 根据用户选择进入对应的更新流程

**Acceptance Scenarios**:

1. **Given** 所有依赖已安装且配置文件存在, **When** 用户运行 `frago init`, **Then** 系统显示"环境已配置 ✓"和配置摘要（认证方式、端点类型、CCR 状态等）
2. **Given** 系统显示配置摘要, **When** 用户选择"无需更新", **Then** 系统显示"初始化完成"并退出
3. **Given** 用户选择"更新配置", **When** 系统进入更新模式, **Then** 系统显示可更新项列表（认证方式、API 端点、CCR 设置），允许用户选择更新项
4. **Given** 用户选择更新认证方式, **When** 系统处理更新, **Then** 系统警告现有配置将被覆盖，需确认后进入认证配置流程

---

### User Story 4 - 自定义 Claude API 端点配置 (Priority: P3)

高级用户可能希望使用第三方 Claude API 端点（如 Deepseek、Aliyun、M2 等），而不是官方端点。系统应提供简单的配置流程。

**Why this priority**: 这是为高级用户提供的灵活性功能。大多数用户使用官方 Claude 登录即可，但部分用户需要自定义端点以降低成本或满足特殊需求。

**Independent Test**: 运行 `frago init` 并选择"自定义端点"：
1. 系统显示支持的端点类型列表（Deepseek、Aliyun、M2、自定义）
2. 用户选择端点类型
3. 系统提示输入 API Key
4. 配置保存到 `~/.frago/config.json`

**Acceptance Scenarios**:

1. **Given** 用户选择配置自定义端点, **When** 系统显示端点选项, **Then** 系统列出预设选项（Deepseek、Aliyun、M2）和"自定义 URL"选项
2. **Given** 用户选择 Deepseek 端点, **When** 用户输入 API Key, **Then** 系统保存端点配置到 `~/.frago/config.json`，包含端点类型和 API Key
3. **Given** 用户选择自定义 URL, **When** 用户输入端点 URL 和 API Key, **Then** 系统验证 URL 格式，保存配置
4. **Given** 用户配置了自定义端点, **When** 配置完成, **Then** 系统显示配置摘要（隐藏部分 API Key），并提示如何验证连接

---

### User Story 5 - Claude Code Router 集成（可选） (Priority: P4)

部分用户希望使用 Claude Code Router 来管理多个 API 端点或实现负载均衡。系统应提供可选的 CCR 安装和配置流程。

**Why this priority**: 这是可选的高级功能，适用于需要复杂端点管理的用户。大多数用户不需要此功能，因此优先级较低。

**Independent Test**: 运行 `frago init` 并选择"使用 Claude Code Router"：
1. 系统询问是否安装 CCR
2. 用户同意后，系统安装 CCR
3. 系统提供 CCR 配置模板
4. 用户完成配置后，系统保存设置

**Acceptance Scenarios**:

1. **Given** 用户选择使用 Claude Code Router, **When** 系统检测到未安装 CCR, **Then** 系统询问是否安装，并在用户同意后执行安装命令
2. **Given** CCR 安装完成, **When** 系统准备配置, **Then** 系统在 `~/.frago/` 下创建 CCR 配置模板文件，并提示用户编辑
3. **Given** 用户完成 CCR 配置, **When** 用户确认配置, **Then** 系统更新 `~/.frago/config.json`，标记 CCR 已启用
4. **Given** 用户选择不使用 CCR, **When** 用户跳过此步骤, **Then** 系统继续后续流程，不安装 CCR

---

### User Story 6 - 配置持久化和摘要报告 (Priority: P5)

用户完成所有配置步骤后，系统应保存所有选择到配置文件，并显示完整的配置摘要，确保用户了解当前设置。

**Why this priority**: 这是收尾工作，确保用户的配置被正确保存。虽然重要，但依赖于前面所有步骤，因此优先级最低。

**Independent Test**: 完成 init 流程后：
1. 检查 `~/.frago/config.json` 文件存在
2. 文件包含所有用户选择（Node 版本、Claude Code 状态、端点配置等）
3. 系统显示配置摘要
4. 提供下一步操作建议

**Acceptance Scenarios**:

1. **Given** 用户完成所有 init 步骤, **When** 流程结束, **Then** 系统在 `~/.frago/` 目录下创建 `config.json` 文件
2. **Given** 配置文件创建完成, **When** 系统写入配置, **Then** 文件包含结构化的 JSON 数据：Node 版本、Claude Code 安装路径、登录状态、端点配置、CCR 状态等
3. **Given** 配置保存成功, **When** 系统显示摘要, **Then** 摘要包括：已安装的组件、配置的端点、下一步建议（如"运行 frago recipe list 查看可用配方"）
4. **Given** 配置文件已存在, **When** 用户重新运行 `frago init`, **Then** 系统检测到现有配置，询问是否重新配置或更新特定部分

---

### Edge Cases

- **网络连接失败**：用户在安装 nvm、Node.js 或 Claude Code 时网络中断，系统应立即终止流程，显示错误详情和手动安装建议，不保存部分进度
- **权限不足**：用户在安装 npm 全局包时缺少权限，系统应立即终止流程，显示权限错误并提示使用 sudo 或配置 npm 全局目录
- **配置文件冲突**：`~/.frago/config.json` 已存在但格式错误或损坏，系统应备份旧文件并创建新配置
- **用户主动中断（Ctrl+C）**：用户在 init 流程中按 Ctrl+C 退出，系统应保存当前已完成步骤的进度到临时状态文件，下次运行时询问"检测到未完成的初始化，是否继续？"
- **安装失败 vs 主动中断**：安装步骤失败时完全终止并清理，不保存进度；用户主动 Ctrl+C 则保存进度点，允许恢复
- **Node.js 版本管理工具冲突**：用户系统上同时存在 nvm、fnm、volta 等工具，系统应检测并提示用户选择或使用现有工具
- **Claude Code 多版本**：用户系统上安装了多个版本的 Claude Code，系统应检测并使用最新版本
- **代理环境**：用户在需要代理的网络环境下运行 init，系统应检测代理设置并在安装命令中正确使用
- **只读文件系统**：用户主目录不可写，系统应立即终止并提示错误，建议检查文件系统权限
- **认证方式切换**：用户从官方登录切换到自定义端点（或反向），系统应明确警告"此操作将覆盖现有认证配置"并要求确认

## Requirements *(mandatory)*

### Functional Requirements

#### 依赖检查和安装

- **FR-001**: 系统 MUST 在运行 `frago init` 时并行检查 Node.js 和 Claude Code 的安装状态和版本
- **FR-002**: 系统 MUST 在并行检查完成后，显示检测结果摘要（已安装的组件及版本，缺失的组件）
- **FR-003**: 系统 MUST 仅对缺失或版本不足的组件进行安装提示，跳过已满足要求的组件
- **FR-004**: 系统 MUST 在检测到 Node.js 未安装或版本低于 20 时，提示用户并提供安装 nvm 和 Node.js 的选项
- **FR-005**: 系统 MUST 在 Claude Code 未安装时，提供自动安装选项（通过 npm install）
- **FR-006**: 系统 MUST 在每个安装步骤后，验证安装成功（通过运行版本检查命令）
- **FR-007**: 系统 MUST 在所有依赖已满足时，显示"所有依赖已满足 ✓"并进入配置更新流程

#### 认证配置（互斥选择）

- **FR-008**: 系统 MUST 提供两种互斥的认证方式选项：官方 Claude Code 登录 或 自定义 API 端点
- **FR-009**: 系统 MUST 在用户选择官方登录后，禁用自定义端点配置选项
- **FR-010**: 系统 MUST 在用户选择自定义端点后，禁用官方登录选项
- **FR-011**: 系统 MUST 支持以下预设端点类型：Deepseek、Aliyun、M2 和自定义 URL
- **FR-012**: 系统 MUST 在用户切换认证方式时，明确警告"将覆盖现有认证配置"并要求确认

#### Claude Code Router（可选）

- **FR-013**: 用户 MUST 能够选择是否使用 Claude Code Router
- **FR-014**: 系统 MUST 在用户选择 CCR 时，检测安装状态并提供安装选项
- **FR-015**: 系统 MUST 在用户选择 CCR 时，提供配置模板文件

#### 配置持久化

- **FR-016**: 系统 MUST 在用户主目录下创建 `~/.frago/` 目录（如果不存在）
- **FR-017**: 系统 MUST 将所有用户配置保存到 `~/.frago/config.json` 文件，使用 JSON 格式
- **FR-018**: 配置文件 MUST 包含认证方式标识字段（"official" 或 "custom"）
- **FR-019**: 系统 MUST 在 init 流程结束时显示配置摘要
- **FR-020**: 系统 MUST 在配置摘要中隐藏敏感信息（如仅显示 API Key 的前 4 位和后 4 位）

#### 已有配置时的更新流程

- **FR-021**: 系统 MUST 在检测到所有依赖已满足且配置文件存在时，显示当前配置状态
- **FR-022**: 系统 MUST 询问用户是否需要更新配置，提供"无需更新"和"更新配置"选项
- **FR-023**: 系统 MUST 在用户选择更新配置时，显示可更新项列表（认证方式、API 端点、CCR 设置）

#### 错误处理和恢复

- **FR-024**: 系统 MUST 在任何安装步骤失败时，立即终止整个 init 流程
- **FR-025**: 系统 MUST 在安装失败时，显示清晰的错误信息和手动修复建议，不保存任何部分进度
- **FR-026**: 系统 MUST 在用户按 Ctrl+C 主动退出时，保存已完成步骤的进度到临时状态文件
- **FR-027**: 系统 MUST 在下次运行时检测未完成的 init 流程，询问"检测到未完成的初始化，是否继续？"
- **FR-028**: 系统 MUST 区分处理安装失败（完全终止）和主动中断（保存进度）两种场景

#### 用户交互

- **FR-029**: 系统 MUST 提供交互式命令行界面，支持用户通过键盘选择选项

### Key Entities

- **Config**: 用户配置对象，包含以下信息：
  - Node.js 版本和安装路径
  - npm 版本
  - Claude Code 安装状态和版本
  - **认证方式**（"official" 表示官方登录，"custom" 表示自定义端点）
  - API 端点配置（类型、URL、API Key）- 仅在认证方式为 "custom" 时存在
  - Claude Code 登录状态 - 仅在认证方式为 "official" 时存在
  - Claude Code Router 启用状态
  - 配置创建时间和最后更新时间
  - Init 流程完成状态

- **InstallationStep**: 安装步骤对象，跟踪每个安装阶段的状态：
  - 步骤名称（如 "check_dependencies"、"install_node"、"install_claude_code"）
  - 状态（pending、in_progress、completed、failed、skipped）
  - 开始时间和结束时间
  - 错误信息（如果失败）

- **TemporaryState**: 临时状态对象，用于保存用户主动中断时的进度：
  - 已完成的步骤列表
  - 当前中断点
  - 中断时间戳
  - 是否可恢复（true 表示 Ctrl+C 中断，false 表示安装失败）

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 用户能够在 5 分钟内完成完整的 init 流程（从运行命令到显示配置摘要）
- **SC-002**: 90% 的用户在首次运行 init 时无需手动干预即可完成环境配置
- **SC-003**: 系统能够正确检测并处理所有主流操作系统上的 Node.js 和 Claude Code 安装状态（Linux、macOS、Windows）
- **SC-004**: 用户配置在 init 完成后持久化保存，重启系统后配置仍然有效
- **SC-005**: 用户在遇到安装错误时，能够根据系统提示的建议解决 80% 的常见问题
- **SC-006**: 配置文件 `~/.frago/config.json` 具有清晰的 JSON 结构，用户可以手动编辑而不破坏功能
- **SC-007**: 用户在配置摘要中能够清楚了解所有已配置的组件和下一步操作

## Assumptions

- 用户已通过 `uv tool install frago` 成功安装 Frago CLI
- 用户的系统支持运行 shell 命令（bash、zsh 或 PowerShell）
- 用户具有基本的命令行使用经验
- 用户有权限在系统上安装 npm 全局包（或知道如何使用 sudo）
- 用户的网络连接可以访问 npm registry 和相关下载源
- nvm 安装脚本使用官方推荐的方式（curl | bash）
- Claude Code 可通过 npm 全局安装（`npm install -g @anthropic-ai/claude-code`）
- Claude Code Router（如果使用）可通过 npm 或其他包管理器安装
- 用户主目录（`~`）可写，可以创建 `.frago` 目录
- 默认 Node.js 版本为 LTS 20.x 或更高版本
- 用户在首次运行 init 时没有现有的 `~/.frago/config.json` 文件
- API Key 验证不在 init 阶段进行，用户需要在后续使用时验证有效性

## Out of Scope

- 自动配置系统级代理设置
- 自动修复系统权限问题（如 npm 全局安装权限）
- 提供 Claude API Key（用户需自行获取）
- 验证 API Key 的有效性（init 仅保存配置，不测试连接）
- 安装和配置其他开发工具（如 Git、Docker）
- 提供图形化配置界面（仅支持命令行）
- 自动备份现有的 Node.js 或 npm 配置
- 多用户环境下的配置共享
- 配置文件的加密存储（API Key 以明文保存在 JSON 中）
- Claude Code Router 的高级配置和优化（仅提供基础模板）
- 操作系统特定的环境变量自动配置（如自动添加到 PATH）
