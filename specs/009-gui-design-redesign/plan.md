# Implementation Plan: Frago GUI 界面设计重构

**Branch**: `009-gui-design-redesign` | **Date**: 2025-12-04 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/009-gui-design-redesign/spec.md`

## Summary

将 Frago GUI 从当前的"开发者工具界面"提升为"专业级 AI 助手应用"。核心改动包括：
1. **配色方案重构** - 从高对比度青色主题迁移到 GitHub Dark 风格的柔和深色主题
2. **布局优化** - 以输入区域为视觉焦点，简化导航层级
3. **视觉层次建立** - 通过留白、色调和间距建立清晰的功能区分
4. **交互反馈增强** - 添加微动效和状态反馈

技术方案：直接修改现有 CSS 变量和样式规则，不改变 HTML 结构和 JavaScript 逻辑。

## Technical Context

**Language/Version**: Python 3.9+ (后端) + HTML5/CSS3/ES6 (前端)
**Primary Dependencies**: pywebview >= 6.1, Click >= 8.1.0 (现有依赖)
**Storage**: ~/.frago/gui_config.json (用户配置持久化)
**Testing**: 手动视觉测试 + 用户测试
**Target Platform**: Linux (PyGObject + WebKit2GTK)
**Project Type**: Single project - GUI 模块 (`src/frago/gui/`)
**Performance Goals**: 界面加载 < 2秒，动画流畅 60fps
**Constraints**: 固定窗口尺寸 600×1434px，深色主题优先
**Scale/Scope**: 5 个页面，约 15 个组件，1 个 CSS 文件 (~700 行)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**状态**: ✅ 通过

项目 constitution.md 为模板状态（未定义具体约束），因此本功能无需满足特定的章程要求。

**设计原则自检**:
- ✅ 遵循现有技术栈，不引入新依赖
- ✅ 修改限定在 CSS 层面，保持代码结构稳定
- ✅ 保持向后兼容，不破坏现有功能

## Project Structure

### Documentation (this feature)

```text
specs/009-gui-design-redesign/
├── plan.md              # 本文件
├── spec.md              # 功能规格说明
├── research.md          # 阶段 0: 配色和设计研究
├── data-model.md        # 阶段 1: 色彩系统定义
├── quickstart.md        # 阶段 1: 快速修改指南
├── contracts/           # 阶段 1: CSS 变量契约
└── tasks.md             # 阶段 2: 实施任务清单
```

### Source Code (repository root)

```text
src/frago/gui/
├── __init__.py              # 模块入口
├── app.py                   # 主应用类
├── api.py                   # JS-Python 桥接
├── models.py                # 数据模型
├── config.py                # 配置管理
├── state.py                 # 状态管理
├── history.py               # 历史记录
└── assets/                  # 前端资源 ← 本次重构重点
    ├── index.html           # HTML 模板 (结构不变)
    ├── scripts/
    │   └── app.js           # JavaScript (逻辑不变)
    └── styles/
        └── main.css         # 主样式表 ← 核心修改文件
```

**Structure Decision**: 单项目结构，本次重构仅涉及 `src/frago/gui/assets/styles/main.css` 文件的样式调整

## Complexity Tracking

> 本次设计重构无章程违规，无需复杂度追踪。

*N/A - 纯 CSS 样式修改，无架构变更*

---

## Phase 1 Design Review

### 设计后章程再评估

**状态**: ✅ 通过

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 技术栈一致性 | ✅ | 仅修改 CSS，不引入新技术 |
| 代码结构稳定性 | ✅ | HTML/JS 不变，仅调整样式变量 |
| 向后兼容性 | ✅ | 保留所有现有类名和结构 |
| 可维护性 | ✅ | 使用语义化 CSS 变量，便于后续调整 |

### 生成的工件清单

| 文件 | 用途 |
|------|------|
| `research.md` | 配色研究、竞品分析、设计决策 |
| `data-model.md` | 完整设计系统定义（色彩、间距、状态） |
| `contracts/css-variables.md` | CSS 变量契约和使用规范 |
| `quickstart.md` | 快速实施指南 |

### 下一步：阶段 2

运行 `/speckit.tasks` 命令生成 `tasks.md` 实施任务清单。
