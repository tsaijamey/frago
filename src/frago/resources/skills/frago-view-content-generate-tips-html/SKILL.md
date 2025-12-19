---
name: frago-view-content-generate-tips-html
description: HTML/reveal.js 内容生成指南。当需要创建可通过 `frago view` 预览的 HTML 演示文稿时使用此 skill。涵盖 reveal.js 高级设计、CSS 技巧、多页协作流程。
---

# HTML/reveal.js 内容生成指南

创建具有专业设计感的 HTML 演示文稿，通过 `frago view` 预览。

## 快速开始

### 基础结构

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>演示标题</title>
</head>
<body>
    <div class="reveal">
        <div class="slides">
            <section>第 1 页</section>
            <section>第 2 页</section>
        </div>
    </div>
</body>
</html>
```

**说明**：`frago view` 自动注入 reveal.js 库，无需手动引入。

### 触发条件

HTML 文件中包含 `class="reveal"` 或 `class="slides"` 时自动进入演示模式。

### 预览命令

```bash
frago view slides.html              # 默认主题
frago view slides.html --theme dracula  # 指定主题
frago view slides.html --fullscreen     # 全屏模式
```

---

## 可用主题

| 主题 | 风格 | 适用场景 |
|------|------|---------|
| `black` | 深色背景（默认） | 技术演示 |
| `white` | 浅色背景 | 正式汇报 |
| `dracula` | Dracula 配色 | 开发者演示 |
| `moon` | 深蓝 | 夜间模式 |
| `night` | 深蓝渐变 | 科技风格 |
| `serif` | 衬线字体 | 学术演示 |
| `solarized` | Solarized 配色 | 柔和风格 |
| `blood` | 深红 | 强调风格 |
| `beige` | 米色 | 温暖风格 |
| `sky` | 蓝色 | 清新风格 |
| `league` | 灰色渐变 | 商务风格 |
| `simple` | 简约白 | 极简风格 |

---

## 幻灯片组织

### 水平导航

每个 `<section>` 是一页：

```html
<section>第 1 页</section>
<section>第 2 页</section>
<section>第 3 页</section>
```

### 垂直导航（嵌套）

嵌套 `<section>` 创建章节内的子页面：

```html
<section>
    <section>主题 A - 概述</section>
    <section>主题 A - 详情 1</section>
    <section>主题 A - 详情 2</section>
</section>
<section>
    <section>主题 B - 概述</section>
</section>
```

---

## 常用元素

### 标题和文本

```html
<section>
    <h1>大标题</h1>
    <h2>副标题</h2>
    <p>正文段落</p>
</section>
```

### 列表

```html
<section>
    <h2>要点</h2>
    <ul>
        <li>要点 1</li>
        <li>要点 2</li>
        <li>要点 3</li>
    </ul>
</section>
```

### 代码块

```html
<section>
    <h2>代码示例</h2>
    <pre><code class="language-python">
def hello():
    print("Hello, World!")
    </code></pre>
</section>
```

### 图片

```html
<section>
    <h2>架构图</h2>
    <img src="./images/architecture.png" alt="架构图">
</section>
```

---

## Fragment 动画

`class="fragment"` 让元素逐步显示：

```html
<p class="fragment">第一步显示</p>
<p class="fragment">第二步显示</p>
<p class="fragment fade-up">上滑淡入</p>
<p class="fragment highlight-red">高亮红色</p>
```

**动画类型**：

| 类型 | 效果 |
|------|------|
| `fade-in` | 淡入 |
| `fade-out` | 淡出 |
| `fade-up` | 上滑淡入 |
| `fade-down` | 下滑淡入 |
| `fade-left` | 左滑淡入 |
| `fade-right` | 右滑淡入 |
| `highlight-red` | 高亮红色 |
| `highlight-green` | 高亮绿色 |
| `highlight-blue` | 高亮蓝色 |
| `grow` | 放大 |
| `shrink` | 缩小 |

---

## 键盘快捷键

| 快捷键 | 功能 |
|--------|------|
| `→` / `Space` | 下一页 |
| `←` | 上一页 |
| `↑` / `↓` | 垂直导航 |
| `F` | 全屏 |
| `Esc` | 退出全屏 / 总览 |
| `O` | 幻灯片总览 |
| `S` | 演讲者笔记 |

---

## 多页 PPT 协作流程

### Phase 1: 规划

与用户确认：
1. 演示主题和目标受众
2. 章节大纲
3. 每页的类型和核心信息

### Phase 2: 骨架生成

创建基础结构和输出目录：

```
outputs/presentation/
├── slides.html       # 主文件
└── images/           # 配图目录
```

### Phase 3: 逐页设计

循环工作流：
1. 用户提供当前页核心内容
2. Agent 生成 HTML + CSS
3. 用户预览：`frago view slides.html`
4. 用户反馈调整
5. 满意后进入下一页

### Phase 4: 整体优化

1. 检查页间过渡
2. 统一视觉风格
3. 添加 fragment 动画
4. 最终预览确认

---

## 模板库

| 模板 | 用途 | 路径 |
|------|------|------|
| 基础骨架 | 快速开始 | [templates/basic-structure.html](templates/basic-structure.html) |
| 封面页 | 开场 | [templates/cover-slide.html](templates/cover-slide.html) |
| 内容页 | 正文 | [templates/content-slide.html](templates/content-slide.html) |
| 对比页 | 比较 | [templates/comparison-slide.html](templates/comparison-slide.html) |
| 时间线 | 历程 | [templates/timeline-slide.html](templates/timeline-slide.html) |
| 结尾页 | 收尾 | [templates/closing-slide.html](templates/closing-slide.html) |

---

## 设计禁忌

| 禁忌 | 原因 | 替代方案 |
|------|------|---------|
| 过多文字 | 幻灯片不是文档 | 提炼关键词 |
| 外部 CDN | 离线不可用 | 本地资源 |
| iframe 嵌入 | 安全限制 | 截图 |
| 复杂 JavaScript | pywebview 限制 | CSS 实现 |

---

## 参考

- [REFERENCE.md](REFERENCE.md) - CSS 高级技巧 + pywebview 限制
- [reveal.js 官方文档](https://revealjs.com/)
