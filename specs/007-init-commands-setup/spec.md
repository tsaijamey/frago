# Feature Specification: frago init 命令与 Recipe 资源安装

**Feature Branch**: `007-init-commands-setup`
**Created**: 2025-11-26
**Status**: Draft
**Input**: User description: "frago工具是依赖 claude code 的 slash 命令的.但我们目前并没有把这部分命令放在包内,也就是说, 用户安装 frago 后实际上没法得到 .claude/commands 下的frago.*相关指令. 且我们似乎也没有实现在 frago init 时,为用户创建系统级的recipe仓库目录和提供example内容."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 首次安装后运行 init 获得完整工具链 (Priority: P1)

用户通过 pip/uv 安装 frago 包后，运行 `frago init` 命令。系统自动为用户安装 Claude Code 集成所需的 slash 命令（如 `/frago.run`、`/frago.recipe` 等），并创建用户级 recipe 目录结构，复制示例 recipe 供用户参考和使用。

**Why this priority**: 这是 frago 工具链完整可用的基础。没有 slash 命令，用户无法在 Claude Code 中使用 frago 的 AI 集成功能；没有用户级 recipe 目录，用户无法自定义和持久化自己的 recipe。

**Independent Test**: 可通过在全新环境中执行 `pip install frago && frago init` 验证，检查 `~/.claude/commands/` 下是否存在 frago.* 命令文件，以及 `~/.frago/recipes/` 目录结构是否正确创建。

**Acceptance Scenarios**:

1. **Given** 用户已安装 frago 包但从未运行过 init, **When** 用户执行 `frago init`, **Then** 系统在 `~/.claude/commands/` 下创建所有 frago 相关 slash 命令文件
2. **Given** 用户已安装 frago 包但从未运行过 init, **When** 用户执行 `frago init`, **Then** 系统创建 `~/.frago/recipes/` 目录结构并复制示例 recipe
3. **Given** 用户已安装 frago 包但从未运行过 init, **When** 用户执行 `frago init`, **Then** 系统显示安装成功信息，列出已安装的资源

---

### User Story 2 - 更新已安装的命令和 recipe (Priority: P2)

用户升级 frago 版本后，运行 `frago init` 更新 Claude Code slash 命令和示例 recipe。系统检测已存在的资源，仅更新需要更新的文件，保留用户自定义的内容。

**Why this priority**: 用户需要在版本升级后获取新功能，同时不丢失自己的自定义配置。

**Independent Test**: 可通过先运行旧版本 init，创建用户自定义 recipe，然后升级并再次运行 init，验证自定义内容未被覆盖而系统资源已更新。

**Acceptance Scenarios**:

1. **Given** 用户已运行过 init 且存在旧版本 slash 命令, **When** 用户升级后执行 `frago init`, **Then** 系统更新所有 frago 相关 slash 命令为新版本
2. **Given** 用户已创建自定义 recipe 在 `~/.frago/recipes/`, **When** 用户执行 `frago init`, **Then** 系统不覆盖用户自定义的 recipe 文件
3. **Given** 系统示例 recipe 有更新, **When** 用户执行 `frago init --update-examples`, **Then** 系统更新示例 recipe 同时备份用户修改过的同名文件

---

### User Story 3 - 查看已安装资源状态 (Priority: P3)

用户想了解当前系统中 frago 资源的安装状态，包括 slash 命令版本、recipe 数量等信息。

**Why this priority**: 帮助用户了解当前环境状态，便于故障排查和版本确认。

**Independent Test**: 可通过执行 `frago init --status` 查看输出信息，验证显示的信息与实际文件系统状态一致。

**Acceptance Scenarios**:

1. **Given** 用户已完成 init, **When** 用户执行 `frago init --status`, **Then** 系统显示已安装的 slash 命令列表及版本
2. **Given** 用户已完成 init, **When** 用户执行 `frago init --status`, **Then** 系统显示用户级 recipe 目录位置和 recipe 数量

---

### Edge Cases

- 用户没有 `~/.claude/` 目录写入权限时如何处理？
- 用户的 `~/.claude/commands/` 下已存在同名但非 frago 创建的命令文件时如何处理？
- 网络断开或资源文件损坏时如何处理？
- 用户中断 init 过程后再次运行时如何恢复？

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: frago 包必须将 slash 命令模板文件打包在分发包内，随 pip 安装一起分发
- **FR-002**: `frago init` 命令必须将 slash 命令文件复制到 `~/.claude/commands/` 目录
- **FR-003**: `frago init` 命令必须创建 `~/.frago/recipes/` 用户级 recipe 目录结构
- **FR-004**: `frago init` 命令必须将示例 recipe 复制到用户级目录供参考
- **FR-005**: 系统必须在复制文件前检测目标位置是否已存在同名文件
- **FR-006**: 系统必须在覆盖用户可能修改过的文件前给出警告或创建备份
- **FR-007**: 系统必须在 init 完成后显示安装摘要信息
- **FR-008**: `frago init --status` 必须显示当前资源安装状态
- **FR-009**: 系统必须在缺少写入权限时给出明确的错误提示和解决建议

### Key Entities

- **Slash Command**: Claude Code 集成命令，存储在 `~/.claude/commands/`，以 `.md` 为扩展名
- **User Recipe**: 用户级 recipe 文件，存储在 `~/.frago/recipes/`，包含 atomic 和 workflows 子目录
- **Example Recipe**: 随包分发的示例 recipe，供用户学习和参考

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 用户执行 `frago init` 后可在 Claude Code 中直接使用 `/frago.run`、`/frago.recipe` 等命令
- **SC-002**: 用户执行 `frago init` 后 `~/.frago/recipes/` 目录存在且包含至少 3 个示例 recipe
- **SC-003**: 全新安装用户从 `pip install frago` 到可以使用所有功能的时间不超过 2 分钟
- **SC-004**: 升级后运行 init 不会导致用户自定义 recipe 丢失
- **SC-005**: init 命令在权限不足时提供可操作的错误信息，用户可根据提示自行解决问题

## Assumptions

- 用户已安装 Claude Code 并且 `~/.claude/` 目录结构存在或可创建
- 用户对 `~/.claude/commands/` 和 `~/.frago/` 目录有写入权限
- slash 命令文件格式遵循 Claude Code 的 markdown 格式规范
- 示例 recipe 使用 004 架构重构后的元数据格式
