# Frago 公共资源索引

本目录包含所有 `/frago.dev.*` 命令共享的规则、指南和脚本示例。

## 前置约定

**本文档假设 frago 已通过 `uv tool install frago-cli` 安装为全局命令。**

所有示例使用 `frago <command>` 格式。如果提示 `command not found`：

```bash
uv tool install frago-cli
```

---

## 命令速查

| 命令 | 用途 | 文档 |
|------|------|------|
| `/frago.run` | 探索调研（Recipe 创建前） | [frago.dev.run.md](../frago.dev.run.md) |
| `/frago.do` | 一次性任务执行 | [frago.dev.do.md](../frago.dev.do.md) |
| `/frago.recipe` | 配方创建/更新 | [frago.dev.recipe.md](../frago.dev.recipe.md) |
| `/frago.test` | 配方测试验证 | [frago.dev.test.md](../frago.dev.test.md) |
| `frago view` | 内容查看器（演示/文档） | 见下方"内容查看"章节 |

---

## 规则文档 (rules/)

核心规则，**违反即失败**。

| 文档 | 适用命令 | 说明 |
|------|---------|------|
| [EXECUTION_PRINCIPLES.md](rules/EXECUTION_PRINCIPLES.md) | run, do | 执行原则（意图理解、工具驱动、试错记录） |
| [SCREENSHOT_RULES.md](rules/SCREENSHOT_RULES.md) | 全部 | 截图使用规范（少用截图，多用 get-content） |
| [NAVIGATION_RULES.md](rules/NAVIGATION_RULES.md) | run, do | 禁止幻觉导航（严禁猜测 URL） |
| [TOOL_PRIORITY.md](rules/TOOL_PRIORITY.md) | run, do | 工具优先级（Recipe > frago > 系统命令） |
| [WORKSPACE_RULES.md](rules/WORKSPACE_RULES.md) | run, do | 工作空间管理（隔离、互斥、禁止 cd） |

---

## 指南文档 (guides/)

详细使用指南和最佳实践。

| 文档 | 适用命令 | 说明 |
|------|---------|------|
| [LOGGING_GUIDE.md](guides/LOGGING_GUIDE.md) | run, do | 日志系统（自动/手动、6种 execution_method） |
| [SELECTOR_PRIORITY.md](guides/SELECTOR_PRIORITY.md) | recipe | 选择器优先级（ARIA > ID > class） |

---

## 脚本示例 (scripts/)

可执行的工作流示例。

| 脚本 | 适用命令 | 说明 |
|------|---------|------|
| [common_commands.sh](scripts/common_commands.sh) | 全部 | 通用命令速查 |
| [run_workflow.sh](scripts/run_workflow.sh) | run | 调研工作流示例 |
| [do_workflow.sh](scripts/do_workflow.sh) | do | 任务执行工作流示例 |
| [recipe_workflow.sh](scripts/recipe_workflow.sh) | recipe | 配方创建工作流示例 |

---

## 快速入门

### 1. 发现资源

```bash
frago recipe list              # 列出配方
frago recipe info <name>       # 配方详情
frago --help                   # 所有命令
```

### 2. 浏览器操作

```bash
frago chrome start             # 启动 Chrome
frago chrome navigate <url>    # 导航
frago chrome click <selector>  # 点击
frago chrome exec-js <expr> --return-value  # 执行 JS
frago chrome get-content       # 获取内容
frago chrome screenshot output.png  # 截图
```

### 3. 项目管理

```bash
frago run init "task desc"     # 创建项目
frago run set-context <id>     # 设置上下文
frago run release              # 释放上下文
```

### 4. 执行配方

```bash
frago recipe run <name>
frago recipe run <name> --params '{}' --output-file result.json
```

### 5. 内容查看

```bash
frago view slides.md             # 自动检测模式
frago view slides.md --present   # 强制演示模式（reveal.js）
frago view README.md --doc       # 强制文档模式
frago view report.pdf            # 查看 PDF
frago view config.json           # 格式化 JSON
```

---

## 内容查看 (frago view)

基于 pywebview 的通用内容查看器，内嵌 reveal.js / PDF.js / highlight.js，**完全离线可用**。

### 两种模式

| 模式 | 触发条件 | 引擎 | 用途 |
|------|---------|------|------|
| **演示模式** | 文件含 `---` 分隔符，或 `--present` | reveal.js | 幻灯片展示 |
| **文档模式** | 默认，或 `--doc` | HTML + highlight.js | 可滚动文档 |

### 支持格式

| 格式 | 演示模式 | 文档模式 |
|------|---------|---------|
| `.md` | reveal.js 幻灯片（`---` 分页） | Markdown 渲染 |
| `.html` | 直接展示 | 直接渲染 |
| `.pdf` | ❌ | PDF.js 渲染 |
| `.json` | ❌ | 格式化 + 语法高亮 |
| `.py/.js/.ts/...` | ❌ | 语法高亮 |

---

### 演示文档规范（重要）

#### 文件结构

```markdown
# 演示标题

第一页内容（标题页）

---

## 第二页标题

正文内容，支持所有 Markdown 语法：

- 列表项 1
- 列表项 2

---

## 代码展示

​```python
def hello():
    print("语法高亮")
​```

---

## 垂直幻灯片组

这是主幻灯片

--

### 子幻灯片 1

按 ↓ 键导航到这里

--

### 子幻灯片 2

继续向下

---

# 结束页

感谢观看！
```

#### 分隔符规则

| 分隔符 | 作用 | 导航键 |
|--------|------|--------|
| `---` | 水平分隔（新的一页） | ← → |
| `--` | 垂直分隔（子页面） | ↑ ↓ |

**注意**：分隔符前后必须有空行！

```markdown
内容...

---

下一页...
```

#### 支持的 Markdown 语法

| 语法 | 示例 |
|------|------|
| 标题 | `# H1` `## H2` `### H3` |
| 列表 | `- item` `1. item` |
| 代码块 | ` ```python ` |
| 行内代码 | `` `code` `` |
| 粗体/斜体 | `**bold**` `*italic*` |
| 链接 | `[text](url)` |
| 图片 | `![alt](path)` |
| 表格 | 标准 Markdown 表格 |
| 引用 | `> quote` |

#### 键盘快捷键（演示时）

| 按键 | 功能 |
|------|------|
| `→` `Space` `N` | 下一页 |
| `←` `P` | 上一页 |
| `↑` `↓` | 垂直导航 |
| `F` | 全屏 |
| `S` | 演讲者备注 |
| `O` | 幻灯片概览 |
| `B` | 黑屏暂停 |
| `Esc` | 退出全屏/概览 |
| `/` | 搜索 |

---

### 可用主题

**深色**：`black`(默认), `night`, `moon`, `dracula`, `blood`, `league`

**浅色**：`white`, `beige`, `serif`, `simple`, `sky`, `solarized`

```bash
frago view slides.md --theme dracula
frago view slides.md --theme white --fullscreen
```

---

### 命令选项

```bash
frago view <file>                    # 自动检测模式
frago view <file> --present          # 强制演示模式
frago view <file> --doc              # 强制文档模式
frago view <file> --theme <name>     # 指定主题
frago view <file> --fullscreen       # 全屏启动
frago view <file> -w 1920 -h 1080    # 指定窗口尺寸
frago view --stdin                   # 从标准输入读取
frago view -c "# Hello"              # 直接传入内容
```

| 选项 | 短选项 | 说明 |
|------|--------|------|
| `--present` | `-p` | 强制演示模式 |
| `--doc` | `-d` | 强制文档模式 |
| `--theme` | `-t` | 主题名称 |
| `--fullscreen` | `-f` | 全屏启动 |
| `--width` | `-w` | 窗口宽度（默认 1280） |
| `--height` | `-h` | 窗口高度（默认 800） |
| `--title` | | 窗口标题 |
| `--stdin` | | 从标准输入读取 |
| `--content` | `-c` | 直接传入内容字符串 |

---

### 自动模式检测逻辑

1. `.pdf` 文件 → 文档模式
2. `.md` 文件含 `\n---\n` 或 `\n--\n` → 演示模式
3. `.html` 文件含 `class="reveal"` → 演示模式
4. 其他 → 文档模式

---

### 完整演示模板

```markdown
# 项目名称

副标题或简介

作者 / 日期

---

## 目录

1. 背景介绍
2. 核心功能
3. 技术实现
4. 演示
5. 总结

---

## 1. 背景介绍

### 问题描述

- 痛点 1
- 痛点 2

### 解决方案

我们的方案是...

---

## 2. 核心功能

### 功能 A

详细说明...

--

### 功能 B

详细说明...

--

### 功能 C

详细说明...

---

## 3. 技术实现

​```python
# 核心代码示例
class MyClass:
    def __init__(self):
        pass
​```

---

## 4. 演示

> 这里可以放截图或说明

---

## 5. 总结

- 要点 1
- 要点 2
- 要点 3

---

# Q&A

感谢观看！

联系方式 / 链接
```

---

## 目录结构

```
.claude/commands/
├── frago.dev.run.md       # 探索调研命令
├── frago.dev.do.md        # 任务执行命令
├── frago.dev.recipe.md    # 配方创建命令
├── frago.dev.test.md      # 配方测试命令
└── frago/
    ├── COMMON.md          # 本索引文档
    ├── rules/             # 核心规则
    │   ├── EXECUTION_PRINCIPLES.md
    │   ├── SCREENSHOT_RULES.md
    │   ├── NAVIGATION_RULES.md
    │   ├── TOOL_PRIORITY.md
    │   └── WORKSPACE_RULES.md
    ├── guides/            # 使用指南
    │   ├── LOGGING_GUIDE.md
    │   └── SELECTOR_PRIORITY.md
    └── scripts/           # 脚本示例
        ├── common_commands.sh
        ├── run_workflow.sh
        ├── do_workflow.sh
        └── recipe_workflow.sh
```
