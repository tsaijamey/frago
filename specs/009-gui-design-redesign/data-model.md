# Data Model: Frago GUI 设计系统

**Date**: 2025-12-04
**Status**: Draft

本文档定义 Frago GUI 的完整设计系统，包括色彩、间距、组件状态等核心实体。

---

## 1. 色彩系统 (Color System)

### 1.1 语义化颜色 Token

```yaml
ColorToken:
  description: 设计系统中的颜色抽象层
  attributes:
    name: string          # Token 名称，如 "bg-base"
    value: string         # CSS 颜色值，如 "#0d1117"
    category: enum        # background | text | accent | functional | border
    description: string   # 用途说明
```

### 1.2 背景色阶 (Background Scale)

| Token | Value | 用途 | 白色叠加 |
|-------|-------|------|---------|
| `--bg-base` | `#0d1117` | 窗口底色 | 0% |
| `--bg-raised` | `#161b22` | 卡片/面板 | +5% |
| `--bg-overlay` | `#21262d` | 模态框/下拉菜单 | +9% |
| `--bg-subtle` | `#30363d` | 悬停状态/分隔 | +14% |

### 1.3 文字色阶 (Text Scale)

| Token | Value | 用途 | 对比度 (vs bg-base) |
|-------|-------|------|-------------------|
| `--text-primary` | `#e6edf3` | 标题/正文 | 15.2:1 |
| `--text-secondary` | `#8b949e` | 次要信息 | 6.8:1 |
| `--text-muted` | `#6e7681` | 辅助文字/占位符 | 4.6:1 |
| `--text-link` | `#58a6ff` | 可点击链接 | 7.9:1 |

### 1.4 强调色 (Accent Colors)

| Token | Value | 用途 |
|-------|-------|------|
| `--accent-primary` | `#58a6ff` | 主要交互元素、激活状态 |
| `--accent-secondary` | `#388bfd` | 悬停状态 |
| `--accent-muted` | `#1f6feb` | 用户消息背景、淡色强调 |

### 1.5 功能色 (Functional Colors)

| Token | Value | 用途 |
|-------|-------|------|
| `--color-success` | `#3fb950` | 成功状态、连接正常 |
| `--color-warning` | `#d29922` | 警告状态、检查中 |
| `--color-error` | `#f85149` | 错误状态、连接断开 |

### 1.6 边框色 (Border Colors)

| Token | Value | 用途 |
|-------|-------|------|
| `--border-default` | `#30363d` | 卡片边框、分隔线 |
| `--border-muted` | `#21262d` | 微妙边框、内部分隔 |

---

## 2. 间距系统 (Spacing System)

### 2.1 间距 Token

```yaml
SpacingToken:
  description: 基于 8px 网格的间距抽象
  base_unit: 8px
  attributes:
    name: string    # Token 名称
    value: string   # CSS 值
    multiplier: number  # 基础单位倍数
```

### 2.2 间距定义

| Token | Value | 倍数 | 典型用途 |
|-------|-------|------|---------|
| `--spacing-xs` | `4px` | 0.5x | 图标与文字间距 |
| `--spacing-sm` | `8px` | 1x | 相关元素间距 |
| `--spacing-md` | `16px` | 2x | 组件内边距 |
| `--spacing-lg` | `24px` | 3x | 区块间距 |
| `--spacing-xl` | `32px` | 4x | 页面边距 |
| `--spacing-2xl` | `48px` | 6x | 大区域分隔 |

---

## 3. 组件状态系统 (Component States)

### 3.1 状态定义

```yaml
ComponentState:
  description: 交互组件的视觉状态
  states:
    - default     # 静默状态
    - hover       # 鼠标悬停
    - active      # 按下/激活
    - focus       # 键盘聚焦
    - disabled    # 禁用状态
    - loading     # 加载中
```

### 3.2 按钮状态 (Button States)

#### 主要按钮 (Primary Button)

| 状态 | 背景色 | 文字色 | 边框 |
|------|--------|--------|------|
| default | `#238636` | `#ffffff` | none |
| hover | `#2ea043` | `#ffffff` | none |
| active | `#238636` | `#ffffff` | none |
| focus | `#238636` | `#ffffff` | `2px solid #58a6ff` |
| disabled | `#21262d` | `#8b949e` | none |

#### 次要按钮 (Secondary Button)

| 状态 | 背景色 | 文字色 | 边框 |
|------|--------|--------|------|
| default | `#21262d` | `#e6edf3` | `1px solid #30363d` |
| hover | `#30363d` | `#e6edf3` | `1px solid #8b949e` |
| active | `#21262d` | `#e6edf3` | `1px solid #30363d` |
| disabled | `#161b22` | `#6e7681` | `1px solid #21262d` |

### 3.3 输入框状态 (Input States)

| 状态 | 背景色 | 边框色 | 文字色 |
|------|--------|--------|--------|
| default | `#0d1117` | `#30363d` | `#e6edf3` |
| hover | `#0d1117` | `#8b949e` | `#e6edf3` |
| focus | `#0d1117` | `#58a6ff` | `#e6edf3` |
| error | `rgba(248,81,73,0.1)` | `#f85149` | `#e6edf3` |
| disabled | `#161b22` | `#21262d` | `#6e7681` |

### 3.4 导航标签状态 (Nav Tab States)

| 状态 | 文字色 | 底部指示器 |
|------|--------|-----------|
| default | `#8b949e` | none |
| hover | `#e6edf3` | none |
| active | `#58a6ff` | `2px solid #58a6ff` |

---

## 4. 消息类型 (Message Types)

### 4.1 消息实体

```yaml
Message:
  description: 对话流中的消息单元
  attributes:
    type: enum      # user | assistant | system | error
    content: string
    timestamp: datetime

MessageStyle:
  description: 消息类型对应的视觉样式
  attributes:
    type: MessageType
    alignment: enum       # left | right | center
    background: ColorToken
    text_color: ColorToken
    border: string | null
    border_radius: string
```

### 4.2 消息样式定义

| 类型 | 对齐 | 背景色 | 文字色 | 边框 | 圆角 |
|------|------|--------|--------|------|------|
| user | right | `#1f6feb` | `#ffffff` | none | `12px` |
| assistant | left | `#161b22` | `#e6edf3` | none | `12px` |
| system | center | `#21262d` | `#8b949e` | none | `8px` |
| error | left | `rgba(248,81,73,0.1)` | `#f85149` | `1px solid #f85149` | `8px` |

---

## 5. 动画参数 (Animation Tokens)

### 5.1 过渡时间

| Token | Value | 用途 |
|-------|-------|------|
| `--transition-fast` | `0.1s` | 微交互（悬停、聚焦） |
| `--transition-normal` | `0.2s` | 状态变化（展开、切换） |
| `--transition-slow` | `0.3s` | 页面切换、模态框 |

### 5.2 缓动函数

| Token | Value | 用途 |
|-------|-------|------|
| `--ease-out` | `cubic-bezier(0.33, 1, 0.68, 1)` | 进入动画 |
| `--ease-in-out` | `cubic-bezier(0.65, 0, 0.35, 1)` | 双向过渡 |

---

## 6. 布局参数 (Layout Tokens)

### 6.1 固定尺寸

| Token | Value | 用途 |
|-------|-------|------|
| `--header-height` | `48px` | 顶部工具栏 |
| `--nav-height` | `44px` | 导航标签栏 |
| `--status-height` | `32px` | 底部状态栏 |
| `--window-width` | `600px` | 窗口宽度 |
| `--window-height` | `1434px` | 窗口高度 |

### 6.2 圆角半径

| Token | Value | 用途 |
|-------|-------|------|
| `--radius-sm` | `4px` | 小组件（标签、徽章） |
| `--radius-md` | `8px` | 按钮、输入框、卡片 |
| `--radius-lg` | `12px` | 消息气泡、模态框 |

---

## 7. 阴影系统 (Shadow Tokens)

> 深色主题中阴影效果较弱，使用边框代替

| Token | Value | 用途 |
|-------|-------|------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.3)` | 轻微抬升 |
| `--shadow-md` | `0 4px 12px rgba(0,0,0,0.4)` | 下拉菜单 |
| `--shadow-lg` | `0 8px 24px rgba(0,0,0,0.5)` | 模态框 |

---

## 8. 字体系统 (Typography)

### 8.1 字体栈

```css
--font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
               'Helvetica Neue', Arial, sans-serif;
--font-mono: 'SF Mono', Monaco, 'Cascadia Code', Consolas, monospace;
```

### 8.2 字号

| Token | Value | 用途 |
|-------|-------|------|
| `--font-size-xs` | `11px` | 辅助信息、时间戳 |
| `--font-size-sm` | `12px` | 状态栏、标签 |
| `--font-size-base` | `14px` | 正文 |
| `--font-size-md` | `16px` | 副标题 |
| `--font-size-lg` | `20px` | 页面标题 |
| `--font-size-xl` | `28px` | 欢迎标题 |

### 8.3 字重

| Token | Value | 用途 |
|-------|-------|------|
| `--font-weight-normal` | `400` | 正文 |
| `--font-weight-medium` | `500` | 按钮、导航 |
| `--font-weight-semibold` | `600` | 标题 |

---

## 9. 状态关系图

```
┌─────────────────────────────────────────────────────────────┐
│                      Color System                            │
├─────────────────────────────────────────────────────────────┤
│  Background    Text         Accent        Functional        │
│  ┌─────────┐   ┌─────────┐  ┌─────────┐   ┌─────────┐      │
│  │ base    │   │ primary │  │ primary │   │ success │      │
│  │ raised  │   │ secondary│ │ secondary│  │ warning │      │
│  │ overlay │   │ muted   │  │ muted   │   │ error   │      │
│  │ subtle  │   │ link    │  └─────────┘   └─────────┘      │
│  └─────────┘   └─────────┘                                  │
├─────────────────────────────────────────────────────────────┤
│                    Component States                          │
│  default → hover → active                                   │
│     ↓                                                       │
│  disabled    focus    loading                               │
├─────────────────────────────────────────────────────────────┤
│                    Message Types                             │
│  user (right, accent) ← → assistant (left, raised)         │
│              ↓                                              │
│       system (center, overlay)                              │
│              ↓                                              │
│       error (left, error-bg)                                │
└─────────────────────────────────────────────────────────────┘
```
