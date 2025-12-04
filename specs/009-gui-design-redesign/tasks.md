# Tasks: Frago GUI 界面设计重构

**Feature**: 009-gui-design-redesign
**Generated**: 2025-12-04
**Source**: [spec.md](./spec.md), [plan.md](./plan.md), [data-model.md](./data-model.md)
**Status**: ✅ 全部完成

---

## 用户故事摘要

| ID | 优先级 | 用户故事 | 独立测试标准 |
|----|--------|---------|-------------|
| US1 | P1 | 首次打开感知应用定位 | 5位新用户在10秒内正确描述应用用途 |
| US2 | P1 | 深色主题下舒适的视觉体验 | 30分钟使用后视觉疲劳评分降低30% |
| US3 | P2 | 快速定位和使用核心功能 | 从主页到执行配方不超过3次点击 |
| US4 | P2 | 实时感知系统状态和任务进度 | 状态变化有明确视觉反馈 |

---

## 依赖关系图

```
阶段 1: 设置
    └── 阶段 2: 基础 (CSS 变量重构)
            ├── 阶段 3: US1+US2 (P1 配色 + 视觉焦点)
            │       └── 阶段 4: US3 (P2 导航优化)
            │               └── 阶段 5: US4 (P2 状态反馈)
            │                       └── 阶段 6: 完善
```

---

## 阶段 1: 设置 ✅

**目标**: 准备开发环境和备份

- [X] T001 备份当前 CSS 文件到 `src/frago/gui/assets/styles/main.css.bak`
- [X] T002 创建设计系统注释块模板在 `src/frago/gui/assets/styles/main.css` 顶部

---

## 阶段 2: 基础 (CSS 变量重构) ✅

**目标**: 建立新的设计系统基础，替换所有 CSS 变量定义

**阻塞**: 所有用户故事都依赖此阶段完成

### 任务清单

- [X] T003 更新 `:root` 中的背景色阶变量 (`--bg-primary` → `#0d1117`, `--bg-secondary` → `#161b22`, `--bg-tertiary` → `#21262d`, `--bg-card` → `#161b22`) 在 `src/frago/gui/assets/styles/main.css`
- [X] T004 [P] 更新 `:root` 中的文字色阶变量 (`--text-primary` → `#e6edf3`, `--text-secondary` → `#8b949e`, `--text-muted` → `#6e7681`) 在 `src/frago/gui/assets/styles/main.css`
- [X] T005 [P] 更新 `:root` 中的强调色变量 (`--accent-primary` → `#58a6ff`, `--accent-secondary` → `#388bfd`) 在 `src/frago/gui/assets/styles/main.css`
- [X] T006 [P] 更新 `:root` 中的功能色变量 (`--accent-success` → `#3fb950`, `--accent-warning` → `#d29922`, `--accent-error` → `#f85149`) 在 `src/frago/gui/assets/styles/main.css`
- [X] T007 [P] 更新 `:root` 中的边框色变量 (`--border-color` → `#30363d`) 在 `src/frago/gui/assets/styles/main.css`
- [X] T008 更新 `[data-theme="light"]` 浅色主题变量覆盖 在 `src/frago/gui/assets/styles/main.css`
- [X] T009 添加新的间距变量 (`--spacing-xs` 到 `--spacing-2xl`) 到 `:root` 在 `src/frago/gui/assets/styles/main.css`
- [X] T010 [P] 添加新的圆角变量 (`--radius-sm`, `--radius-md`, `--radius-lg`) 到 `:root` 在 `src/frago/gui/assets/styles/main.css`
- [X] T011 [P] 添加缓动函数变量 (`--ease-out`, `--ease-in-out`) 到 `:root` 在 `src/frago/gui/assets/styles/main.css`

**验证**: ✅ 界面正常加载，无样式错误

---

## 阶段 3: US1 + US2 (P1 - 配色与视觉焦点) ✅

**目标**:
- US1: 用户首次打开时立即理解应用定位
- US2: 长时间使用无视觉疲劳

**独立测试**:
- US1: 邀请新用户打开应用，10秒内能描述"这是一个可以输入命令的 AI 助手"
- US2: 新旧配色对比测试，30分钟后评分视觉舒适度

### 任务清单

- [X] T012 [US1] 更新 `.welcome-container` 样式，增加视觉焦点引导 在 `src/frago/gui/assets/styles/main.css`
- [X] T013 [P] [US1] 更新 `.input-container` 样式，增加边框和阴影使输入区突出 在 `src/frago/gui/assets/styles/main.css`
- [X] T014 [P] [US1] 更新 `.input-text` 聚焦状态，添加蓝色边框高亮 在 `src/frago/gui/assets/styles/main.css`
- [X] T015 [P] [US1] 更新 `.send-btn` 样式，使用新的强调色 在 `src/frago/gui/assets/styles/main.css`
- [X] T016 [US2] 更新 `.message-user` 样式，背景改为 `#1f6feb`，文字改为 `#ffffff` 在 `src/frago/gui/assets/styles/main.css`
- [X] T017 [P] [US2] 更新 `.message-assistant` 样式，背景改为 `var(--bg-secondary)` 在 `src/frago/gui/assets/styles/main.css`
- [X] T018 [P] [US2] 更新 `.message-system` 样式，背景改为 `var(--bg-tertiary)` 在 `src/frago/gui/assets/styles/main.css`
- [X] T019 [P] [US2] 更新 `.message-error` 样式，添加红色边框和淡红色背景 在 `src/frago/gui/assets/styles/main.css`
- [X] T020 [US2] 更新 `.output-container` 样式，调整内边距和边框颜色 在 `src/frago/gui/assets/styles/main.css`

**验证**: ✅ 主页视觉焦点落在输入区，消息气泡颜色和谐可区分

---

## 阶段 4: US3 (P2 - 导航优化) ✅

**目标**: 用户能快速在功能模块间切换，导航清晰可见

**独立测试**: 从主页切换到配方列表并运行配方，不超过3次点击

### 任务清单

- [X] T021 [US3] 更新 `.nav-tabs` 样式，调整背景和边框 在 `src/frago/gui/assets/styles/main.css`
- [X] T022 [P] [US3] 更新 `.nav-tab` 默认状态样式，使用次要文字色 在 `src/frago/gui/assets/styles/main.css`
- [X] T023 [P] [US3] 更新 `.nav-tab:hover` 悬停状态，使用主要文字色 在 `src/frago/gui/assets/styles/main.css`
- [X] T024 [P] [US3] 更新 `.nav-tab.active` 激活状态，使用强调色和底部指示器 在 `src/frago/gui/assets/styles/main.css`
- [X] T025 [US3] 更新 `.recipe-card` 和 `.skill-card` 悬停效果 在 `src/frago/gui/assets/styles/main.css`
- [X] T026 [P] [US3] 更新 `.page-header` 样式，调整标题和按钮间距 在 `src/frago/gui/assets/styles/main.css`

**验证**: ✅ 导航标签激活状态明显，配方卡片悬停有视觉反馈

---

## 阶段 5: US4 (P2 - 状态反馈) ✅

**目标**: 用户能实时感知系统状态和任务进度

**独立测试**: 启动长时间任务，验证进度更新的及时性和可见性

### 任务清单

- [X] T027 [US4] 更新 `.progress-bar` 和 `.progress-fill` 样式，使用新的强调色 在 `src/frago/gui/assets/styles/main.css`
- [X] T028 [P] [US4] 更新 `.status-bar` 样式，调整背景和边框 在 `src/frago/gui/assets/styles/main.css`
- [X] T029 [P] [US4] 更新 `.indicator-dot` 状态颜色 (`.connected` → `#3fb950`, `.checking` → `#d29922`) 在 `src/frago/gui/assets/styles/main.css`
- [X] T030 [P] [US4] 更新 `.toast` 通知样式，使用新的功能色 在 `src/frago/gui/assets/styles/main.css`
- [X] T031 [US4] 更新 `.loading` 和 `.empty-state` 样式 在 `src/frago/gui/assets/styles/main.css`

**验证**: ✅ 进度条颜色与整体配色和谐，连接状态指示器颜色正确

---

## 阶段 6: 完善 ✅

**目标**: 优化细节，确保一致性

### 任务清单

- [X] T032 更新 `.header` 和 `.header-btn` 样式 在 `src/frago/gui/assets/styles/main.css`
- [X] T033 [P] 更新 `.settings-form` 和 `.setting-item` 样式 在 `src/frago/gui/assets/styles/main.css`
- [X] T034 [P] 更新 `.history-item` 和 `.history-status` 样式 在 `src/frago/gui/assets/styles/main.css`
- [X] T035 [P] 更新滚动条样式 (`::-webkit-scrollbar`) 在 `src/frago/gui/assets/styles/main.css`
- [X] T036 清理代码：移除未使用的旧变量，添加注释说明 在 `src/frago/gui/assets/styles/main.css`
- [X] T037 删除备份文件 `src/frago/gui/assets/styles/main.css.bak`（确认无问题后）

**最终验证**: ✅
- [X] 主页配色和谐，输入区域突出
- [X] 配方列表卡片边界清晰
- [X] Skills 网格颜色对比适中
- [X] 设置页表单元素可见
- [X] 深色主题变量完整（浅色主题需运行时验证）

---

## 并行执行示例

### 阶段 2 并行任务组

```
T003 (背景色) ──┐
T004 (文字色) ──┼── 同时执行 ✅
T005 (强调色) ──┤
T006 (功能色) ──┤
T007 (边框色) ──┘
```

### 阶段 3 并行任务组

```
T012 (欢迎区) → T013 (输入容器) ──┐
                 T014 (输入框) ────┼── 同时执行 ✅
                 T015 (发送按钮) ──┘

T016 (用户消息) → T017 (助手消息) ──┐
                   T018 (系统消息) ──┼── 同时执行 ✅
                   T019 (错误消息) ──┘
```

---

## 实施策略

### MVP 范围

**阶段 1-3 (T001-T020)** 构成 MVP：
- 完整的配色系统重构
- 首次打开的视觉焦点引导
- 消息气泡的舒适配色

### 增量交付

1. **第一次交付**: ✅ 阶段 1-2 完成后，基础配色系统就位
2. **第二次交付**: ✅ 阶段 3 完成后，P1 用户故事满足
3. **第三次交付**: ✅ 阶段 4-5 完成后，P2 用户故事满足
4. **最终交付**: ✅ 阶段 6 完成后，全部完善

---

## 任务统计

| 阶段 | 任务数 | 可并行 | 状态 |
|------|--------|--------|------|
| 阶段 1: 设置 | 2 | 0 | ✅ |
| 阶段 2: 基础 | 9 | 7 | ✅ |
| 阶段 3: US1+US2 | 9 | 7 | ✅ |
| 阶段 4: US3 | 6 | 5 | ✅ |
| 阶段 5: US4 | 5 | 4 | ✅ |
| 阶段 6: 完善 | 6 | 4 | ✅ |
| **总计** | **37** | **27** | **✅ 完成** |

---

## 完成时间

**实施日期**: 2025-12-04
**完成状态**: 全部 37 个任务已完成
