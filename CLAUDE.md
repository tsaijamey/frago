# Frago Development Guidelines

Auto-generated from all feature plans. Last updated: 2025-11-15

## Active Technologies
- Python 3.9+（已有pyproject.toml要求 >=3.9） (003-skill-automation)
- 文件系统存储 (003-skill-automation)
- Python 3.9+（pyproject.toml 已要求 >=3.9） (004-recipe-architecture-refactor)
- 文件系统（Recipe 脚本 .js/.py/.sh + 元数据 .md，无数据库） (004-recipe-architecture-refactor)
- Python 3.9+ (pyproject.toml 已要求 >=3.9) (005-run-command-system)
- Python 3.9+（符合 pyproject.toml 要求） (006-init-command)
- Python 3.9+（符合 pyproject.toml 要求） + Click 8.1+, PyYAML 6.0+, pathlib (标准库) (007-init-commands-setup)
- 文件系统（用户目录 ~/.claude/ 和 ~/.frago/） (007-init-commands-setup)

- Bash/Shell Script (POSIX兼容) + websocat工具，Chrome DevTools Protocol (001-standardize-cdp-scripts)

## Project Structure

```text
src/
tests/
```

## Commands

# Add commands for Bash/Shell Script (POSIX兼容)

## Code Style

Bash/Shell Script (POSIX兼容): Follow standard conventions

## Recent Changes
- 007-init-commands-setup: Added Python 3.9+（符合 pyproject.toml 要求） + Click 8.1+, PyYAML 6.0+, pathlib (标准库)
- 006-init-command: Added Python 3.9+（符合 pyproject.toml 要求）
- 005-run-command-system: Added Python 3.9+ (pyproject.toml 已要求 >=3.9)


<!-- MANUAL ADDITIONS START -->

## 前置约定

**frago 命令来自 PyPI 包 `frago-cli`，通过 `uv tool install frago-cli` 安装。**

- **PyPI 包名**: `frago-cli`
- **命令名称**: `frago`

所有示例使用 `frago <command>` 格式。如果提示 `command not found`：

```bash
uv tool install frago-cli
```

---

## 命令速查

| 命令 | 用途 |
|------|------|
| `/frago.dev.run` | 探索调研（Recipe 创建前） |
| `/frago.dev.exec` | 一次性任务执行 |
| `/frago.dev.recipe` | 配方创建/更新 |
| `/frago.dev.test` | 配方测试验证 |

---

## 核心规则（违反即失败）

### 1. 截图使用规范

> **禁止使用截图获取网页文字内容。必须使用 `get-content` 或配方提取。**

导航后必须执行的流程：
```
1. frago navigate <url>           ← 导航
2. frago recipe list | grep xxx   ← 检查是否有现成配方
3. frago get-content              ← 无配方时用此命令获取内容
4. （可选）frago screenshot       ← 仅用于验证状态，禁止用于阅读
```

截图的唯一合法用途：
- ✅ 验证状态：确认导航成功、元素已加载
- ✅ 调试定位：排查元素定位失败
- ✅ 视觉备份：记录元素位置

### 2. 禁止幻觉导航

**严禁猜测 URL 直接导航。** Claude 容易凭空构造看似合理但不存在的链接。

正确做法：剥洋葱式层层深入
```bash
# ✅ 第一步：导航到已知首页
frago navigate "https://example.com"

# ✅ 第二步：从页面获取真实链接
frago exec-js "Array.from(document.querySelectorAll('a')).map(a => ({text: a.textContent.trim(), href: a.href})).filter(a => a.text)" --return-value

# ✅ 第三步：使用从上一步获取的真实 URL
frago navigate "<从上一步获取的真实 URL>"
```

允许直接导航的 URL 来源：
- 用户明确提供
- 上下文中的链接
- 页面上获取的（通过 `exec-js` 提取的 `href`）
- 搜索结果返回
- 配方输出的

### 3. 工具优先级

```
1. 已有配方 (Recipe)        ← 最优先
2. frago 命令               ← 跨 agent 通用
3. 系统命令或第三方软件命令   ← 功能强大
4. Claude Code 内置工具      ← 最后兜底
```

| 需求 | ❌ 不要 | ✅ 应该 |
|------|--------|--------|
| 搜索信息 | `WebSearch` | `frago navigate "https://google.com/search?q=..."` |
| 查看网页 | `WebFetch` | `frago navigate <url>` + `get-content` |
| 提取数据 | 手写 JS | 先查 `frago recipe list` |
| 文件操作 | 手动创建 | 使用 Claude Code 的 Write/Edit 工具 |

### 4. 工作空间隔离

所有产出物必须放在 Project 工作空间内：
```
projects/<project_id>/
├── project.json             # 元数据
├── logs/execution.jsonl     # 执行日志
├── scripts/                 # 执行脚本
├── screenshots/             # 截图
├── outputs/                 # 任务产出物
└── temp/                    # 临时文件
```

禁止的行为：
- ❌ 在桌面、/tmp、下载目录等外部位置创建文件
- ❌ 使用 `cd` 命令切换目录（会导致 `frago` 命令失效）

正确做法：
- ✅ 始终在项目根目录执行所有命令，使用绝对路径或相对路径访问文件

### 5. 执行原则

1. **正确理解意图** - 如果意图不清晰，通过交互菜单让人类选择
2. **立即感知** - 先打印可用的 frago 配方/工具
3. **实在的工具** - 放弃预训练记忆，用工具"看"和"交互"获取真实信息
4. **过程存储** - 所有产生的文件/记录都放在工作空间里
5. **试错记录** - 尝试 → 记录成功/失败 → 反复失败则换思路
6. **及时求助** - 反复遇到困难时，向人类寻求帮助

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
frago navigate <url>           # 导航
frago click <selector>         # 点击
frago exec-js <expr> --return-value  # 执行 JS
frago get-content              # 获取内容
frago screenshot output.png    # 截图
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

## 选择器优先级

在生成 JavaScript 时，按此优先级排序选择器（5 最高，1 最低）：

| 优先级 | 类型 | 示例 | 稳定性 |
|--------|------|------|--------|
| **5** | ARIA 标签 | `[aria-label="按钮"]` | ✅ 很稳定 |
| **5** | data 属性 | `[data-testid="submit"]` | ✅ 很稳定 |
| **4** | 稳定 ID | `#main-button` | ✅ 稳定 |
| **3** | 语义化类名 | `.btn-primary` | ⚠️ 中等 |
| **3** | HTML5 语义标签 | `button`, `nav` | ⚠️ 中等 |
| **2** | 结构选择器 | `div > button` | ⚠️ 脆弱 |
| **1** | 生成的类名 | `.css-abc123` | ❌ 很脆弱 |

---

## 日志系统

### 自动日志（CDP 命令执行后自动记录）

| 命令 | action_type |
|------|-------------|
| `navigate` | navigation |
| `click`, `scroll`, `exec-js` | interaction |
| `screenshot` | screenshot |
| `get-title`, `get-content` | extraction |

### 手动日志（需要 Agent 判断时使用）

```bash
frago run log \
  --step "步骤描述" \
  --status "success|error|warning" \
  --action-type "<action_type>" \
  --execution-method "<method>" \
  --data '{"key": "value"}'
```

**execution-method 有效值**：
1. `command` - CLI 命令执行
2. `recipe` - Recipe 调用
3. `file` - 执行脚本文件
4. `manual` - 人工手动操作
5. `analysis` - AI 推理和思考
6. `tool` - AI 工具调用

---

## 目录结构

```
src/frago/
├── cdp/                  # CDP核心模块
├── cli/                  # 命令行接口
├── recipes/              # Recipe系统核心
└── tools/                # 辅助工具

examples/                 # 示例级 Recipe
├── atomic/chrome/        # Chrome CDP操作示例
├── atomic/system/        # 系统操作示例
└── workflows/            # Workflow示例

.claude/
├── commands/             # 自定义slash命令
│   └── frago/            # Frago 规则和指南
│       ├── COMMON.md     # 公共资源索引
│       ├── rules/        # 核心规则
│       ├── guides/       # 使用指南
│       └── scripts/      # 脚本示例
└── skills/               # 项目级skills

projects/                 # Run实例工作目录
```

<!-- MANUAL ADDITIONS END -->
