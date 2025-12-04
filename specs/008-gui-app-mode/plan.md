# Implementation Plan: Frago GUI 应用模式

**Branch**: `008-gui-app-mode` | **Date**: 2025-12-04 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/008-gui-app-mode/spec.md`

## Summary

为 frago 添加 GUI 应用模式，通过 `frago --gui` 命令启动一个无边框的桌面窗口。该窗口使用 pywebview 渲染 HTML 页面，提供 App 式 UI 界面，包含输入区域、配方列表、skills 列表等功能模块，支持调用 `frago agent` 并实时显示 stream-json 响应。

## Technical Context

**Language/Version**: Python 3.9+（符合现有 pyproject.toml 要求）
**Primary Dependencies**: pywebview>=6.1, click>=8.1.0（现有依赖）
**Storage**: 文件系统（`~/.frago/` 用户配置、`~/.claude/` 会话上下文）
**Testing**: pytest（现有测试框架）
**Target Platform**: Linux、macOS、Windows 桌面环境（需图形界面支持）
**Project Type**: single（扩展现有 CLI 项目）
**Performance Goals**: GUI 启动时间 <5s，用户操作延迟 <500ms
**Constraints**: 离线时提供有限功能，同时只运行一个 frago 任务
**Scale/Scope**: 单用户桌面应用，4个主要页面（主页、配方、Skills、历史）

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

> **注意**: 项目 constitution.md 为模板状态，无具体约束条件。以下为基于 frago 项目惯例的自检：

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 符合现有技术栈 | ✅ | Python + Click CLI，pywebview 为新增轻量依赖 |
| 遵循项目结构 | ✅ | 新增 `src/frago/gui/` 模块，符合现有 src 布局 |
| 测试要求 | ✅ | 使用 pytest，可为 GUI 模块添加单元测试 |
| 跨平台支持 | ✅ | pywebview 支持 Linux/macOS/Windows |
| 不破坏现有功能 | ✅ | `--gui` 为新增可选参数，不影响现有 CLI 行为 |

## Project Structure

### Documentation (this feature)

```text
specs/008-gui-app-mode/
├── plan.md              # 本文件
├── research.md          # 阶段 0：框架研究
├── data-model.md        # 阶段 1：数据模型
├── quickstart.md        # 阶段 1：快速入门
├── contracts/           # 阶段 1：API 契约
│   └── js-python-api.md # JS ↔ Python 通信接口
└── tasks.md             # 阶段 2：任务列表（/speckit.tasks 生成）
```

### Source Code (repository root)

```text
src/frago/
├── cli/
│   └── main.py              # 修改：添加 --gui 全局选项
├── gui/                     # 新增：GUI 模块
│   ├── __init__.py
│   ├── app.py               # GUI 应用入口和窗口管理
│   ├── api.py               # Python ↔ JS 桥接 API
│   ├── state.py             # 应用状态管理
│   └── assets/              # 前端资源
│       ├── index.html       # 主 HTML 页面
│       ├── styles/
│       │   └── main.css     # 样式文件
│       └── scripts/
│           └── app.js       # 前端 JS 逻辑
└── ...

tests/
├── unit/
│   └── gui/                 # GUI 模块单元测试
│       ├── test_app.py
│       ├── test_api.py
│       └── test_state.py
└── integration/
    └── test_gui_cli.py      # CLI --gui 集成测试
```

**Structure Decision**: 采用单项目结构（Option 1），在现有 `src/frago/` 下新增 `gui/` 模块。前端资源（HTML/CSS/JS）作为 assets 子目录打包，随 PyPI 包分发。

## Complexity Tracking

> 无章程违规，此部分留空。

---

## Phase 0: Research ✅

已生成 [`research.md`](./research.md)，包含：
- ✅ pywebview 6.1 技术验证
- ✅ JS ↔ Python 双向通信机制（js_api + evaluate_js）
- ✅ 前端技术栈选择：原生 HTML/CSS/JS
- ✅ 跨平台兼容性分析（Linux GTK/QT、macOS Cocoa、Windows WinForms）

## Phase 1: Design ✅

已生成：
- ✅ [`data-model.md`](./data-model.md) - 7个核心实体定义
- ✅ [`contracts/js-python-api.md`](./contracts/js-python-api.md) - 完整 API 契约
- ✅ [`quickstart.md`](./quickstart.md) - 快速入门指南

## Constitution Re-check (设计后)

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 新增依赖合理性 | ✅ | pywebview 为轻量依赖（~1MB），BSD 许可证兼容 |
| 数据模型简洁性 | ✅ | 7个实体，职责清晰，无过度设计 |
| API 设计合理性 | ✅ | 遵循 pywebview 最佳实践，Promise-based |
| 资源打包策略 | ✅ | HTML/CSS/JS 作为 assets 打包，符合现有模式 |
| 测试覆盖计划 | ✅ | 单元测试（api、state）+ 集成测试（cli） |

## Phase 2: Tasks (下一步)

运行 `/speckit.tasks` 生成任务列表。
