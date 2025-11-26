# Implementation Plan: frago init 命令与 Recipe 资源安装

**Branch**: `007-init-commands-setup` | **Date**: 2025-11-26 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/007-init-commands-setup/spec.md`

## Summary

扩展现有 `frago init` 命令，增加以下功能：
1. 将 Claude Code slash 命令（`.claude/commands/frago.*`）打包到 Python 包内，在 `frago init` 时安装到用户级 `~/.claude/commands/`
2. 创建用户级 recipe 目录 `~/.frago/recipes/`，并复制示例 recipe 供用户参考

## Technical Context

**Language/Version**: Python 3.9+（符合 pyproject.toml 要求）
**Primary Dependencies**: Click 8.1+, PyYAML 6.0+, pathlib (标准库)
**Storage**: 文件系统（用户目录 ~/.claude/ 和 ~/.frago/）
**Testing**: pytest（已配置）
**Target Platform**: Linux, macOS, Windows（跨平台支持）
**Project Type**: single（命令行工具）
**Performance Goals**: init 命令完成时间 < 5 秒
**Constraints**: 无网络依赖，所有资源随包分发
**Scale/Scope**: 安装约 5-10 个 slash 命令文件，10-20 个示例 recipe

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

项目无特定章程约束，采用以下合理规则：
- [x] 代码可测试：文件复制逻辑可独立测试
- [x] CLI 接口优先：通过 `frago init` 命令暴露功能
- [x] 简单性原则：仅使用标准库 + 现有依赖，不引入新依赖

## Project Structure

### Documentation (this feature)

```text
specs/007-init-commands-setup/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/frago/
├── cli/
│   └── init_command.py  # 扩展现有 init 命令
├── init/
│   ├── checker.py       # 现有：依赖检查
│   ├── installer.py     # 现有：依赖安装
│   ├── configurator.py  # 现有：配置管理
│   ├── models.py        # 现有：数据模型
│   ├── exceptions.py    # 现有：异常定义
│   └── resources.py     # 新增：资源安装模块
└── resources/           # 新增：随包分发的资源文件
    ├── commands/        # Claude Code slash 命令
    │   ├── frago.run.md
    │   ├── frago.recipe.md
    │   ├── frago.exec.md
    │   └── frago.test.md
    └── recipes/         # 示例 recipe
        ├── atomic/
        │   ├── chrome/
        │   └── system/
        └── workflows/

tests/
├── unit/
│   └── test_resources.py  # 新增：资源安装测试
└── integration/
    └── test_init_resources.py  # 新增：init 资源安装集成测试
```

**Structure Decision**: 在 `src/frago/` 下新增 `resources/` 目录存放随包分发的资源文件。新增 `init/resources.py` 模块处理资源安装逻辑。

## Complexity Tracking

> 无需填写，无章程违规

## Phase 0 Output

见 [research.md](./research.md)

## Phase 1 Output

见 [data-model.md](./data-model.md)、[contracts/](./contracts/)、[quickstart.md](./quickstart.md)
