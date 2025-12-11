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
