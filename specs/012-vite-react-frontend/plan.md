# Implementation Plan: Vite React 前端重构与 Linux 依赖自动安装

**Branch**: `012-vite-react-frontend` | **Date**: 2025-12-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/012-vite-react-frontend/spec.md`

## Summary

将 Frago GUI 前端从原生 JavaScript 迁移到 Vite + React + TypeScript + TailwindCSS 现代化技术栈，提升开发体验和代码可维护性。同时实现 Linux 系统依赖自动检测和安装功能，降低用户的安装门槛。

## Technical Context

**Language/Version**: Python 3.9+（后端，已有）+ TypeScript 5.x（前端新增）
**Primary Dependencies**:
- 后端: pywebview>=6.1, click>=8.1.0, pydantic>=2.0（已有）
- 前端: React 18, Vite 5.x, TailwindCSS 3.x, Zustand（新增）
**Storage**: 文件系统（`~/.frago/`）
**Testing**: pytest（后端），Vite 内置测试支持（前端）
**Target Platform**: Linux (GTK/QT), macOS, Windows
**Project Type**: 嵌入式 Web 前端（pywebview 加载本地 HTML/JS）
**Performance Goals**: HMR < 3秒，主题切换 < 500ms
**Constraints**: 必须保持与现有 pywebview API 完整兼容，旧版代码保留但标记 deprecated
**Scale/Scope**: 5 个页面（Tips, Tasks, Recipes, Skills, Settings），17 个 API 方法

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

项目 constitution 为模板状态，未定义具体规则。按照默认最佳实践执行：
- ✅ 保持代码结构清晰
- ✅ 新功能有对应测试
- ✅ 文档与代码同步

## Project Structure

### Documentation (this feature)

```text
specs/012-vite-react-frontend/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
src/frago/gui/
├── frontend/                    # 新建：前端源码 (git tracked)
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── index.html               # Vite 入口
│   └── src/
│       ├── main.tsx             # React 入口
│       ├── App.tsx              # 根组件
│       ├── vite-env.d.ts        # Vite 类型
│       ├── api/
│       │   └── pywebview.ts     # pywebview API 封装
│       ├── stores/
│       │   └── appStore.ts      # Zustand 状态
│       ├── components/
│       │   ├── layout/
│       │   │   ├── Header.tsx
│       │   │   ├── NavTabs.tsx
│       │   │   └── StatusBar.tsx
│       │   ├── tips/
│       │   │   └── TipsPage.tsx
│       │   ├── tasks/
│       │   │   ├── TaskList.tsx
│       │   │   ├── TaskCard.tsx
│       │   │   ├── TaskDetail.tsx
│       │   │   └── StepList.tsx
│       │   ├── recipes/
│       │   │   ├── RecipeList.tsx
│       │   │   └── RecipeDetail.tsx
│       │   ├── skills/
│       │   │   └── SkillList.tsx
│       │   ├── settings/
│       │   │   └── SettingsPage.tsx
│       │   └── ui/
│       │       ├── Toast.tsx
│       │       ├── EmptyState.tsx
│       │       └── LoadingSpinner.tsx
│       ├── hooks/
│       │   ├── usePolling.ts
│       │   ├── useConfig.ts
│       │   └── useTasks.ts
│       └── styles/
│           └── globals.css      # Tailwind base + 自定义
│
├── assets/                      # Vite 构建输出 (git ignored)
│   ├── index.html               # vite build 输出
│   └── assets/                  # JS/CSS chunks
│
├── assets_legacy/               # 旧版前端 (deprecated, 保留作为参考)
│   ├── index.html               # 原 index.html (deprecated)
│   ├── scripts/
│   │   └── app.js               # 原 app.js (deprecated)
│   └── styles/
│       └── main.css             # 原 main.css (deprecated)
│
├── deps.py                      # 新建：Linux 依赖检测和自动安装
├── app.py                       # 修改：支持 dev/prod 模式切换 + 自动安装集成
├── api.py                       # 保持不变
├── models.py                    # 保持不变
└── ...
```

**Structure Decision**: 采用嵌入式 Web 前端结构。前端源码位于 `src/frago/gui/frontend/`，构建产物输出到 `src/frago/gui/assets/`，旧版代码移动到 `src/frago/gui/assets_legacy/` 并标记为 deprecated。

## Complexity Tracking

无违规需要说明。
