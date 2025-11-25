# Implementation Plan: Frago 环境初始化命令

**Branch**: `006-init-command` | **Date**: 2025-11-25 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/006-init-command/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

实现 `frago init` 命令，用于在用户通过 `uv tool install frago` 安装后，自动化配置本地开发环境。该命令将：

1. **并行检查依赖**：同时检测 Node.js 和 Claude Code 的安装状态
2. **智能安装**：仅安装缺失或版本不足的组件
3. **互斥认证配置**：用户选择官方 Claude Code 登录或自定义 API 端点
4. **可选 CCR 集成**：支持 Claude Code Router 配置
5. **配置持久化**：所有设置保存到 `~/.frago/config.json`
6. **错误恢复**：区分安装失败（终止）和主动中断（保存进度）

技术方法：
- 使用 Python Click 构建交互式 CLI
- 通过子进程调用外部命令（nvm、npm、claude-code）
- JSON 配置文件管理用户设置
- 临时状态文件支持 Ctrl+C 恢复

## Technical Context

**Language/Version**: Python 3.9+（符合 pyproject.toml 要求）
**Primary Dependencies**:
  - Click 8.1+ (CLI 框架)
  - Pydantic 2.0+ (配置验证)
  - psutil 7.1+ (进程检测)
  - PyYAML 6.0+ (配置文件)
  - subprocess (标准库 - 外部命令调用)
  - pathlib (标准库 - 路径操作)

**Storage**:
  - 用户配置：`~/.frago/config.json` (JSON)
  - 临时状态：`~/.frago/.init_state.json` (恢复用)
  - CCR 配置模板：`~/.frago/ccr.config.example` (文本)

**Testing**: pytest 7.4+ (包含 pytest-asyncio、pytest-cov)

**Target Platform**:
  - Linux (Ubuntu 24.04+, 其他主流发行版)
  - macOS (支持 zsh/bash)
  - Windows (通过 PowerShell - 需要研究)

**Project Type**: Single project (CLI 工具)

**Performance Goals**:
  - 依赖检查：< 2 秒（并行执行）
  - 完整 init 流程：< 5 分钟（包括所有安装）
  - 配置加载/保存：< 100ms

**Constraints**:
  - 必须支持无密码 sudo 和非 sudo 环境
  - 安装失败必须提供清晰的错误信息和修复建议
  - 配置文件必须向后兼容（支持部分配置）
  - 不能修改系统全局配置（PATH、环境变量等）

**Scale/Scope**:
  - 用户数量：预计数百到数千用户
  - 配置复杂度：6 种配置场景（已装/未装 x 官方/自定义/CCR）
  - 平台支持：3 个操作系统（Linux 优先）

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**注意**：当前项目 constitution.md 为模板状态，未定义具体原则。

基于 Frago 项目现有实践（从 CLAUDE.md 和 pyproject.toml 推断）：

| 检查项 | 状态 | 说明 |
|--------|------|------|
| **CLI-First 设计** | ✅ PASS | `frago init` 符合现有 CLI 命令模式（`frago navigate`, `frago recipe` 等） |
| **Python 版本一致性** | ✅ PASS | Python 3.9+ 符合 pyproject.toml 要求 |
| **依赖最小化** | ✅ PASS | 仅使用现有依赖（Click, Pydantic, psutil）+ 标准库 |
| **文件系统存储** | ✅ PASS | 使用 JSON 文件而非数据库，符合项目惯例 |
| **测试覆盖** | ⚠️ NEEDS VERIFICATION | 需要在 Phase 1 设计测试策略 |
| **跨平台兼容性** | ⚠️ NEEDS RESEARCH | Windows 支持需要研究（nvm-windows, npm 行为差异） |

**无违规项** - 不需要填写 Complexity Tracking 表格。

## Project Structure

### Documentation (this feature)

```text
specs/006-init-command/
├── spec.md              # 功能规格说明（已完成）
├── plan.md              # 本文件（当前阶段）
├── research.md          # Phase 0 output（待生成）
├── data-model.md        # Phase 1 output（待生成）
├── quickstart.md        # Phase 1 output（待生成）
├── contracts/           # Phase 1 output（待生成）
│   └── cli_commands.md  # CLI 命令接口契约
├── checklists/          # 已有检查清单
│   └── requirements.md  # 需求质量检查清单（已完成）
└── tasks.md             # Phase 2 output（/speckit.tasks 生成 - 本命令不创建）
```

### Source Code (repository root)

```text
src/frago/
├── cli/
│   ├── main.py              # CLI 入口（已有）
│   ├── commands.py          # CDP 命令（已有）
│   ├── recipe_commands.py   # Recipe 命令（已有）
│   └── init_command.py      # 新增：init 命令实现
├── init/                    # 新增：init 功能模块
│   ├── __init__.py
│   ├── checker.py           # 依赖检查逻辑
│   ├── installer.py         # 安装逻辑
│   ├── configurator.py      # 配置管理
│   ├── recovery.py          # 状态恢复逻辑
│   └── models.py            # Config, TempState 数据模型
├── tools/                   # 已有辅助工具
└── ...

tests/
├── unit/
│   └── init/                # 新增：init 单元测试
│       ├── test_checker.py
│       ├── test_installer.py
│       ├── test_configurator.py
│       └── test_recovery.py
├── integration/
│   └── test_init_command.py # 新增：init 集成测试
└── ...
```

**Structure Decision**: 采用 Option 1: Single project 结构，在现有 `src/frago/` 下新增 `init/` 模块。理由：
1. Frago 是单一 CLI 工具，不涉及前后端分离
2. 遵循现有模块组织方式（`cdp/`, `recipes/`, `cli/`）
3. 便于复用现有工具和配置系统

## Complexity Tracking

无违规项，此表格为空。

---

## Phase 0: 大纲与研究

### 研究任务清单

基于技术上下文中的 NEEDS RESEARCH/CLARIFICATION 项，需要研究以下主题：

#### 1. Windows 平台支持

**研究目标**: 确定 Windows 上 Node.js 环境检测和安装策略

**具体问题**:
- Windows 上 nvm 的替代方案（nvm-windows vs fnm vs volta）
- PowerShell 中检测 Node.js 版本的命令
- npm 全局安装路径在 Windows 上的差异
- subprocess 在 Windows 上调用外部命令的差异

**决策点**:
- 是否支持 Windows 自动安装，还是仅检测并提供手动安装指引
- 选择推荐的 Windows Node.js 版本管理工具

#### 2. 并行检查实现策略

**研究目标**: 确定 Python 中并行执行多个系统命令的最佳实践

**具体问题**:
- 使用 `subprocess.run` + `concurrent.futures.ThreadPoolExecutor`
- 使用 `asyncio` + `asyncio.create_subprocess_exec`
- 错误处理：一个检查失败是否中断其他检查

**决策点**: 选择并发模型（线程池 vs asyncio）

#### 3. 外部命令调用的错误处理

**研究目标**: 定义不同失败场景的错误处理策略

**具体问题**:
- 命令不存在 vs 命令执行失败的区分
- 网络错误（npm install 失败）的重试逻辑
- 权限错误的检测和提示
- 超时设置（长时间运行的安装命令）

**决策点**:
- 每类错误的标准化错误信息格式
- 是否需要错误码系统

#### 4. 交互式 CLI 实现

**研究目标**: 选择交互式 CLI 库和实现模式

**具体问题**:
- Click 原生支持 vs `click.prompt()` vs `inquirer` 库
- 多选菜单、确认提示的用户体验设计
- Ctrl+C 信号捕获和优雅处理

**决策点**:
- 使用 Click 内置功能还是引入额外的交互式库
- 交互式 UI 的一致性规范

#### 5. 配置文件版本兼容性

**研究目标**: 设计配置文件的版本演进策略

**具体问题**:
- 配置文件增加字段时的向后兼容
- 缺失字段的默认值处理
- 配置文件格式变更时的迁移策略

**决策点**:
- 是否在配置文件中包含 schema_version 字段
- 配置验证失败时是备份旧配置还是直接覆盖

#### 6. 临时状态文件的生命周期管理

**研究目标**: 确定 `.init_state.json` 的创建、清理和恢复逻辑

**具体问题**:
- 何时创建临时状态文件（首次运行还是安装开始时）
- 成功完成后是否删除临时状态文件
- 临时状态文件过期时间（7天？30天？）
- 多次 Ctrl+C 的状态累积问题

**决策点**:
- 临时状态文件的完整生命周期规则
- 是否需要 `frago init --reset` 命令清理状态

### 研究输出目标

生成 `research.md` 文件，包含每个研究任务的：
- **决策**: 选择的技术方案
- **理由**: 为什么选择该方案
- **考虑的替代方案**: 评估但未采用的方案及原因
- **实现指导**: 具体的代码模式或库使用建议

---

## Phase 1: 设计与契约

*前提条件: `research.md` 完成*

### 输出文件清单

1. **`data-model.md`**: 数据模型设计
   - Config 实体完整字段定义
   - TemporaryState 实体字段定义
   - InstallationStep 状态机设计
   - 配置文件 JSON Schema

2. **`contracts/cli_commands.md`**: CLI 命令接口契约
   - `frago init` 命令签名
   - 子命令选项（如 `--reset`, `--show-config`）
   - 退出码定义（0=成功, 1=安装失败, 2=用户取消等）
   - 输出格式规范（成功/错误消息模板）

3. **`quickstart.md`**: 开发快速入门
   - 本地开发环境设置
   - 如何运行 init 命令测试
   - 如何模拟不同环境状态（无 Node.js、无 Claude Code 等）
   - 测试配置文件位置和清理方法

### 设计任务

#### 数据模型设计要点

- **Config** 实体需要包含的字段（基于规格的 Key Entities）：
  - `node_version`: Optional[str]
  - `node_path`: Optional[str]
  - `npm_version`: Optional[str]
  - `claude_code_version`: Optional[str]
  - `claude_code_path`: Optional[str]
  - `auth_method`: Literal["official", "custom"]
  - `api_endpoint`: Optional[dict] - 仅 auth_method=custom 时有值
  - `ccr_enabled`: bool
  - `created_at`: datetime
  - `updated_at`: datetime
  - `init_completed`: bool

- **TemporaryState** 实体需要包含的字段：
  - `completed_steps`: List[str]
  - `current_step`: Optional[str]
  - `interrupted_at`: datetime
  - `recoverable`: bool

#### API 契约设计要点

- CLI 命令接口：
  ```bash
  frago init [OPTIONS]

  Options:
    --reset          清除临时状态，从头开始
    --show-config    显示当前配置并退出
    --skip-deps      跳过依赖检查（仅更新配置）
    --help           显示帮助信息
  ```

- 退出码：
  - 0: 成功完成
  - 1: 安装失败
  - 2: 用户主动取消
  - 3: 配置文件错误
  - 10: 环境检查失败（如主目录不可写）

---

## Phase 2: 任务生成

*由 `/speckit.tasks` 命令完成，不在本 plan.md 中生成。*

Phase 1 完成后，运行 `/speckit.tasks` 将基于 plan.md 和 data-model.md 生成可执行的任务列表。

---

## 附录：需要澄清的问题（已在 spec.md 中解决）

所有澄清问题已在 `spec.md` 的澄清章节中记录和解决：
1. ✅ 初始化检查顺序 → 并行检查
2. ✅ 所有依赖已满足时的行为 → 显示配置并询问是否更新
3. ✅ 认证方式关系 → 互斥选择
4. ✅ 安装失败策略 → 立即终止
5. ✅ 主动退出 vs 安装失败 → 区分处理

无遗留澄清问题。
