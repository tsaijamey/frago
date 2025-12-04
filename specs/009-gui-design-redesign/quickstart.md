# Quickstart: GUI 设计重构

快速了解如何实施 Frago GUI 界面设计重构。

---

## 目标文件

```
src/frago/gui/assets/styles/main.css
```

这是唯一需要修改的文件。

---

## 核心变更

### 1. 替换 CSS 变量定义

打开 `main.css`，找到 `:root` 块，将现有变量替换为新的配色方案：

```css
:root {
    /* === 背景色阶 - GitHub Dark 风格 === */
    --bg-primary: #0d1117;      /* 原: #1a1a2e */
    --bg-secondary: #161b22;    /* 原: #16213e */
    --bg-tertiary: #21262d;     /* 原: #0f3460 */
    --bg-card: #161b22;         /* 原: #1e2746 */

    /* === 文字色阶 === */
    --text-primary: #e6edf3;    /* 原: #eaeaea */
    --text-secondary: #8b949e;  /* 原: #a0a0a0 */
    --text-muted: #6e7681;      /* 原: #666 */

    /* === 强调色 - 柔和蓝 === */
    --accent-primary: #58a6ff;  /* 原: #00d9ff */
    --accent-secondary: #388bfd;/* 原: #0099cc */
    --accent-success: #3fb950;  /* 原: #00c853 */
    --accent-warning: #d29922;  /* 原: #ffc107 */
    --accent-error: #f85149;    /* 原: #ff5252 */

    /* === 边框 === */
    --border-color: #30363d;    /* 原: #2a3a5a */
    --shadow-color: rgba(0, 0, 0, 0.4);
}
```

### 2. 更新消息气泡样式

找到 `.message-*` 样式规则，更新为：

```css
.message-user {
    background: #1f6feb;        /* 使用 accent-muted */
    color: #ffffff;
    margin-left: auto;
}

.message-assistant {
    background: var(--bg-secondary);
    color: var(--text-primary);
}

.message-system {
    background: var(--bg-tertiary);
    color: var(--text-secondary);
    font-style: italic;
    max-width: 100%;
    text-align: center;
}

.message-error {
    background: rgba(248, 81, 73, 0.1);
    color: var(--accent-error);
    border: 1px solid var(--accent-error);
}
```

### 3. 更新浅色主题

找到 `[data-theme="light"]` 块，更新为：

```css
[data-theme="light"] {
    --bg-primary: #ffffff;
    --bg-secondary: #f6f8fa;
    --bg-tertiary: #f3f4f6;
    --bg-card: #ffffff;

    --text-primary: #1f2328;
    --text-secondary: #656d76;
    --text-muted: #8c959f;

    --accent-primary: #0969da;
    --accent-secondary: #0550ae;

    --border-color: #d0d7de;
    --shadow-color: rgba(0, 0, 0, 0.1);
}
```

---

## 验证步骤

1. 启动 GUI 应用：
   ```bash
   frago --gui
   ```

2. 检查以下页面：
   - [ ] 主页：配色和谐，输入区域突出
   - [ ] 配方列表：卡片边界清晰
   - [ ] Skills 网格：颜色对比适中
   - [ ] 设置页：表单元素可见

3. 切换主题（如果有）：
   - [ ] 深色主题正常
   - [ ] 浅色主题正常

4. 测试交互状态：
   - [ ] 按钮悬停效果
   - [ ] 输入框聚焦效果
   - [ ] 导航标签切换

---

## 常见问题

### Q: 修改后界面没有变化？

A: pywebview 可能缓存了旧样式。重启应用或清除缓存。

### Q: 某些颜色看起来不对？

A: 检查是否有硬编码的颜色值未替换为变量。搜索 `#1a1a2e`、`#00d9ff` 等旧值。

### Q: 浅色主题不生效？

A: 确认 `data-theme="light"` 属性正确设置在 `<html>` 或 `<body>` 标签上。

---

## 参考文档

- [research.md](./research.md) - 设计研究和决策依据
- [data-model.md](./data-model.md) - 完整设计系统定义
- [contracts/css-variables.md](./contracts/css-variables.md) - CSS 变量契约
