# Contract: CSS Variables

**Version**: 1.0.0
**Date**: 2025-12-04

本文档定义 Frago GUI 样式表中的 CSS 变量契约。所有样式必须使用这些变量，禁止硬编码颜色值。

---

## 1. 变量命名规范

### 命名格式

```
--{category}-{modifier}
```

| Category | 说明 | 示例 |
|----------|------|------|
| `bg` | 背景色 | `--bg-base`, `--bg-raised` |
| `text` | 文字色 | `--text-primary`, `--text-muted` |
| `accent` | 强调色 | `--accent-primary`, `--accent-muted` |
| `color` | 功能色 | `--color-success`, `--color-error` |
| `border` | 边框色 | `--border-default`, `--border-muted` |
| `spacing` | 间距 | `--spacing-sm`, `--spacing-lg` |
| `transition` | 过渡 | `--transition-fast`, `--transition-slow` |
| `radius` | 圆角 | `--radius-md`, `--radius-lg` |
| `font-size` | 字号 | `--font-size-base`, `--font-size-lg` |

---

## 2. 完整变量清单

### 2.1 颜色变量

```css
:root {
    /* === 背景色阶 === */
    --bg-base: #0d1117;
    --bg-raised: #161b22;
    --bg-overlay: #21262d;
    --bg-subtle: #30363d;

    /* === 文字色阶 === */
    --text-primary: #e6edf3;
    --text-secondary: #8b949e;
    --text-muted: #6e7681;
    --text-link: #58a6ff;

    /* === 强调色 === */
    --accent-primary: #58a6ff;
    --accent-secondary: #388bfd;
    --accent-muted: #1f6feb;

    /* === 功能色 === */
    --color-success: #3fb950;
    --color-warning: #d29922;
    --color-error: #f85149;

    /* === 边框色 === */
    --border-default: #30363d;
    --border-muted: #21262d;

    /* === 阴影 === */
    --shadow-color: rgba(0, 0, 0, 0.4);
}
```

### 2.2 间距变量

```css
:root {
    --spacing-xs: 4px;
    --spacing-sm: 8px;
    --spacing-md: 16px;
    --spacing-lg: 24px;
    --spacing-xl: 32px;
    --spacing-2xl: 48px;
}
```

### 2.3 过渡变量

```css
:root {
    --transition-fast: 0.1s ease;
    --transition-normal: 0.2s ease;
    --transition-slow: 0.3s ease;

    --ease-out: cubic-bezier(0.33, 1, 0.68, 1);
    --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);
}
```

### 2.4 圆角变量

```css
:root {
    --radius-sm: 4px;
    --radius-md: 8px;
    --radius-lg: 12px;
}
```

### 2.5 字体变量

```css
:root {
    --font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                   'Helvetica Neue', Arial, sans-serif;
    --font-mono: 'SF Mono', Monaco, 'Cascadia Code', Consolas, monospace;

    --font-size-xs: 11px;
    --font-size-sm: 12px;
    --font-size-base: 14px;
    --font-size-md: 16px;
    --font-size-lg: 20px;
    --font-size-xl: 28px;

    --font-weight-normal: 400;
    --font-weight-medium: 500;
    --font-weight-semibold: 600;
}
```

### 2.6 布局变量

```css
:root {
    --header-height: 48px;
    --nav-height: 44px;
    --status-height: 32px;
}
```

---

## 3. 浅色主题覆盖

```css
[data-theme="light"] {
    /* === 背景色阶 === */
    --bg-base: #ffffff;
    --bg-raised: #f6f8fa;
    --bg-overlay: #ffffff;
    --bg-subtle: #f3f4f6;

    /* === 文字色阶 === */
    --text-primary: #1f2328;
    --text-secondary: #656d76;
    --text-muted: #8c959f;
    --text-link: #0969da;

    /* === 强调色 === */
    --accent-primary: #0969da;
    --accent-secondary: #0550ae;
    --accent-muted: #ddf4ff;

    /* === 边框色 === */
    --border-default: #d0d7de;
    --border-muted: #e6e8eb;

    /* === 阴影 === */
    --shadow-color: rgba(0, 0, 0, 0.1);
}
```

---

## 4. 使用规范

### 4.1 必须使用变量的场景

| 场景 | 变量 | 禁止 |
|------|------|------|
| 任何背景色 | `var(--bg-*)` | `#1a1a2e` |
| 任何文字色 | `var(--text-*)` | `#eaeaea` |
| 任何边框色 | `var(--border-*)` | `#2a3a5a` |
| 交互元素颜色 | `var(--accent-*)` | `#00d9ff` |
| 状态反馈色 | `var(--color-*)` | `#00c853` |

### 4.2 允许硬编码的场景

- `transparent` 关键字
- `inherit`, `currentColor` 关键字
- `rgba()` 中的透明度变化（基于变量色值）
- 一次性使用的装饰性颜色

### 4.3 变量组合示例

```css
/* ✅ 正确 */
.button {
    background: var(--accent-primary);
    color: var(--bg-base);
    border-radius: var(--radius-md);
    transition: background var(--transition-fast);
}

/* ❌ 错误 */
.button {
    background: #58a6ff;
    color: #0d1117;
    border-radius: 8px;
    transition: background 0.1s ease;
}
```

---

## 5. 变量变更流程

### 添加新变量

1. 在 `data-model.md` 中添加定义
2. 更新本契约文档
3. 在 `main.css` 的 `:root` 中添加变量
4. 同步更新浅色主题覆盖

### 修改现有变量

1. 评估影响范围（搜索变量使用位置）
2. 更新 `data-model.md` 中的定义
3. 修改 `main.css` 中的变量值
4. 进行视觉回归测试

### 删除变量

1. 确认变量未被使用
2. 从 `:root` 和 `[data-theme="light"]` 中移除
3. 更新本契约文档
4. 更新 `data-model.md`

---

## 6. 兼容性说明

### 浏览器支持

- WebKit/GTK (Linux) - pywebview 默认渲染引擎
- CSS Variables: 完全支持

### 回退策略

对于不支持 CSS 变量的环境，不提供回退。pywebview 使用的 WebKit 版本均支持 CSS 变量。
