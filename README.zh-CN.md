# frago - Multi-Runtime Automation Infrastructure

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey)](https://github.com/tsaijamey/Frago)
[![Chrome](https://img.shields.io/badge/requires-Chrome-green)](https://www.google.com/chrome/)
[![Claude Code](https://img.shields.io/badge/powered%20by-Claude%20Code-purple)](https://claude.ai/code)

[English](README.md)

为 AI agent 设计的多运行时自动化基建，提供持久化上下文管理和可复用的 Recipe 系统。

**文档**: [关键概念](docs/concepts.zh-CN.md) · [安装指南](docs/installation.zh-CN.md) · [使用指南](docs/user-guide.zh-CN.md) · [Recipe 系统](docs/recipes.zh-CN.md) · [技术架构](docs/architecture.zh-CN.md) · [使用场景](docs/use-cases.zh-CN.md) · [开发指南](docs/development.zh-CN.md)

---

## 为什么需要 frago

AI 面对 prompt 解决问题时，只能"谈"而不能"做"，只"谈一次"而不会"从头开始做到尾"，例如 2023 年的 ChatGPT 等产品。于是有人设计出了 Agent，Agent 通过接口规范调用工具。

但现实是，事无穷而工具有尽。

你让 AI 提取 YouTube 字幕，它花 5 分钟探索成功了。第二天同样的需求，它又从零开始探索——完全不记得昨天做过。

即便 Claude Code 这样的 Agent，在面对每个人不同的个性化任务要求时，仍显笨拙：每一次都要探索，每一次都要花费大量 token，由 Agent 裹挟 LLM 从起点走到终点。慢且不稳定：10 次里，可能 5 次是正确的路线，而剩下 5 次则充满"奇怪"而"艰难"的试错。

Agent 缺少上下文是事实。但 Agent 缺少什么样的上下文呢？

人们试图用 RAG 这类碎片化的信息拆分方式，让 Agent 通过检索来"找到方法"，这是“理论上正确、但事实上偏离“的巨坑方法。关键问题在于：每个人自己的事务需求是"局部"的，是有边界的，并不需要一个厚重的 RAG 系统来支撑，RAG 把个体解决问题的基本方法复杂化了。

Anthropic 与 Google 的研究均指向了：直接查找文档。这同样是本项目作者在 2024 年时就提出的观点。但这种理念建立在 Agent 具备足够的能力基础上。Claude Code 正是这类 Agent。

Claude Code 设计了一种文档架构：commands 和 skills，来实践这类哲学。frago 锦上添花，在这个基础上，深入贯彻作者的设计哲学：每一个方法论知识，都需要与具体可执行的工具结合起来。

在 frago 的框架下，skills 是方法论的集合，recipe（"配方"）是可执行工具的集合。

作者的期望：通过 frago 提供的 Claude Code slash commands（/frago.run 等核心指令），建立一种 Agent 规范——使其在面对陌生问题时，能探索并将结果标准化为结构化信息；通过自发感知，主动建立 skills 和 recipe 的关联。

最终，你的 Agent 能充分理解你对某一类工作、事务需求的表述，借助已有的 skills 找到并合理运用相关的 recipes，继而实现"仅需花费少量 token 即可驱动事情自动执行"的结果。

frago 不是 Agent 本身，而是 Agent 的"骨骼"。

Agent 已经足够聪明，但还不够机灵。frago 让它记住如何做事。

---

## 如何使用

frago 结合 Claude Code，通过四个 slash command 构建完整的"探索 → 固化 → 执行"闭环。

```
/frago.run     探索研究，积累经验
     ↓
/frago.recipe  将经验固化为可复用的配方
/frago.test    验证配方（趁上下文还在）
     ↓
/frago.exec    通过 skill 指导，快速执行
```

### 第一步：探索研究

在 Claude Code 中输入：

```
/frago.run 研究如何提取 YouTube 视频字幕
```

Agent 会：
- 创建一个 project 存储此次 run 实例
- 使用 frago 提供的基础工具（navigate、click、exec-js 等）进行探索
- 自动记录 `execution.jsonl` 和关键收获
- 所有截图、脚本、输出文件持久化保存

```
projects/youtube-transcript-research/
├── logs/execution.jsonl    # 结构化执行日志
├── screenshots/            # 截图归档
├── scripts/                # 验证过的脚本
└── outputs/                # 输出文件
```

### 第二步：固化配方

探索完成后，输入：

```
/frago.recipe
```

Agent 会：
- 分析探索过程中积累的经验
- 自动生成完成此任务必要的 recipes
- 创建对应的 skill（*即将支持*）
- 将 skill 和 recipe 关联起来

生成的 recipe 示例：

```yaml
---
name: youtube_extract_video_transcript
type: atomic
runtime: chrome-js
description: "提取 YouTube 视频的完整转录文本"
use_cases:
  - "批量提取视频字幕内容用于文本分析"
  - "为视频创建索引或摘要"
---
```

### 第三步：验证配方

趁会话上下文还在，立即测试：

```
/frago.test youtube_extract_video_transcript
```

验证失败？当场调整，不用重新探索。这就是为什么 recipe 和 test 要并行——上下文丢失后再调试成本更高。

### 第四步：快速执行

下次遇到同类需求，输入：

```
/frago.exec video-production 制作一个关于 AI 的短视频
```

Agent 会：
- 加载指定的 skill（video-production）
- 根据 skill 中的方法论指导，调用相关的 recipes
- 快速完成任务，不再重复探索

**这就是"骨骼"的价值**：第一次花 5 分钟探索，之后只需几秒钟执行。

---

## 技术基础

上述流程依赖 frago 提供的底层能力：

| 能力 | 说明 |
|-----|------|
| **原生 CDP** | 直连 Chrome DevTools Protocol，~2MB 轻量级，无 Node.js 依赖 |
| **Run 系统** | 持久化任务上下文，JSONL 结构化日志 |
| **Recipe 系统** | 元数据驱动，三级优先级（Project > User > Example） |
| **Session 系统** | Agent 会话监控，实时执行跟踪，多 Agent 适配 |
| **多运行时** | Chrome JS、Python、Shell 三种运行时支持 |

```
架构对比：
Playwright:  Python → Node.js 中继 → CDP → Chrome  (~100MB)
frago:       Python → CDP → Chrome                  (~2MB)
```

---

## 快速开始

### 安装

```bash
# 基础安装（核心功能）
pip install frago-cli
# 或使用 uv（推荐）
uv tool install frago-cli

# 初始化环境（检查依赖、配置认证、安装资源）
frago init
```

### `frago init` 做了什么

init 命令一步完成环境配置：

- **检查依赖**：Node.js ≥18.0.0、Claude Code CLI
- **自动安装缺失依赖**：Node.js 通过 nvm、Claude Code 通过 npm
- **配置认证**：默认（Claude Code 内置）或自定义 API 端点（DeepSeek、阿里云、Kimi、MiniMax）
- **安装资源**：Slash 命令到 `~/.claude/commands/`、示例 Recipe 到 `~/.frago/recipes/`

```bash
# 查看当前配置和资源
frago init --show-config

# 重置并重新初始化
frago init --reset
```

详见 [安装指南](docs/installation.zh-CN.md)

### 基础使用

安装完成后，进入 Claude Code，使用 slash commands：

```bash
# 探索研究
/frago.run 在 Upwork 上搜索 Python 职位并分析技能要求

# 固化配方
/frago.recipe

# 验证配方
/frago.test upwork_search_jobs

# 快速执行（下次）
/frago.exec job-hunting 搜索远程 Python 职位
```

详细流程见上方「如何使用」章节。

### 命令行工具（人类直接使用）

frago 也提供命令行工具，供调试或脚本集成：

```bash
# 浏览器操作
frago chrome navigate https://example.com
frago chrome click 'button[type="submit"]'
frago chrome screenshot output.png

# Recipe 管理
frago recipe list
frago recipe info <recipe_name>
frago recipe run <recipe_name> --params '{...}'

# Run 实例管理
frago run list
frago run info <run_id>
```

---

## frago 不是 Playwright/Selenium

Playwright 和 Selenium 是**测试工具**——启动浏览器、跑测试、关闭浏览器。每次都是全新的开始。

frago 是**AI 的骨骼**——连接已有的浏览器，探索、学习、记住。经验可以积累。

| 你需要... | 选择 |
|----------|------|
| 质量保障、回归测试、CI/CD 集成 | Playwright/Selenium |
| 数据采集、工作流自动化、AI 辅助任务 | frago |
| 一次性脚本，跑完就扔 | Playwright/Selenium |
| 积累经验，下次更快 | frago |

技术上的差异（轻量级、直连 CDP、无 Node.js 依赖）是结果，不是目的。

**核心区别是设计哲学**：测试工具假设你知道要做什么；frago 假设你在探索，并帮你记住探索的结果。

## frago vs Dify/Coze/n8n

Dify、Coze、n8n 是**工作流编排工具**。

传统用法：你手动拖节点、连线、配参数。n8n 推出了 [AI Workflow Builder](https://docs.n8n.io/advanced-ai/ai-workflow-builder/)，可以用自然语言生成工作流节点（Dify 和 Coze 目前还没有类似功能）。

但不管是手动还是 AI 辅助，你最终得到的是什么？**一张流程图**。

然后呢？

1. 你还是要进入平台，看懂这张图
2. 运行，报错，回去改节点配置
3. 再运行，又报错，再改
4. 调试通过后，流程图跑起来了

**AI 帮你画了图，但调试、修改、维护——还是你自己干。**

用 frago：

```
/frago.run 从这个网站抓数据
```

没有流程图。AI 直接去干活——打开浏览器、点击、提取数据、处理错误。你等着就行。

完事了：

```
/frago.recipe
```

配方自动生成。下次：

```
/frago.exec 抓取类似网站
```

**你不需要进入任何平台，不需要看任何流程图。**

| | 编排工具（含 AI 辅助） | frago |
|--|----------------------|-------|
| AI 做什么 | 帮你画流程图 | 直接替你干活 |
| 你要做什么 | 进平台、看图、调试、改配置 | 说需求、等结果 |
| 产出物 | 一张需要维护的流程图 | 可复用的 recipe |

**编排工具的 AI 是你的"绘图助手"；frago 的 AI 是你的"执行者"。**

当然，如果你需要定时触发、可视化监控、团队协作审批——编排工具更合适。但如果你只是想把事情做完——frago 让你用嘴解决问题，不需要学任何平台。

---

## 资源管理

### 为什么需要资源同步命令

frago 是开源项目——任何人都可以通过 PyPI 安装。但**骨骼**是通用的，**大脑**是私人的。

每个人都有：
- 自己的应用场景
- 个性化知识（skills）
- 自定义自动化脚本（recipes）

这些个性化资源不应该存在于公开包中，它们属于你自己。

frago 的理念：**跨环境一致**。无论你在哪台机器、全新安装还是新项目，你的资源都应该随时可用。工具来自 PyPI；大脑来自你的私有仓库。

frago 暂时不提供社区级的云同步服务。取而代之的是，提供一套命令让你用自己的 Git 仓库管理同步。

### 资源流向概览

```
┌─────────────┐   publish   ┌─────────────┐    sync    ┌─────────────┐
│   项目目录   │ ──────────→ │   系统目录   │ ─────────→ │   远程仓库   │
│  .claude/   │             │ ~/.claude/  │            │  Git Repo   │
│  examples/  │             │ ~/.frago/   │            │             │
└─────────────┘             └─────────────┘            └─────────────┘
       ↑                          │                          │
       │       dev-load           │         deploy           │
       └──────────────────────────┴──────────────────────────┘
```

### 命令一览

| 命令 | 方向 | 用途 |
|------|------|------|
| `publish` | 项目 → 系统 | 将项目资源发布到系统目录 |
| `sync` | 系统 → 远程 | 将系统资源同步到你的私有 Git 仓库 |
| `deploy` | 远程 → 系统 | 从私有仓库拉取到系统目录 |
| `dev-load` | 系统 → 项目 | 将系统资源加载到当前项目（仅开发用） |

### 典型工作流

**开发者流程**（本地改动 → 云端）：
```bash
# 在项目中编辑完 recipes 后
frago publish              # 项目 → 系统
frago sync                 # 系统 → 远程 Git
```

**新设备流程**（云端 → 本地）：
```bash
# 在新机器上首次配置
frago sync --set-repo git@github.com:you/my-frago-resources.git
frago deploy               # 远程 Git → 系统
frago dev-load             # 系统 → 项目（如果你在开发 frago）
```

**普通用户**（只使用 frago）：
```bash
frago deploy               # 从你的仓库获取最新资源
# 资源现在在 ~/.claude/ 和 ~/.frago/，可以直接使用
```

### 同步范围

只同步 frago 专属资源：
- `frago.*.md` 命令（不动你的其他 Claude 命令）
- `frago-*` skills（不动你的其他 skills）
- `~/.frago/recipes/` 下的所有配方

你的个人非 frago 的 Claude 命令和 skills 永远不会被触及。

---

## 文档导航

- **[关键概念](docs/concepts.zh-CN.md)** - Skill、Recipe、Run 的定义与关系
- **[使用场景](docs/use-cases.md)** - 从 Recipe 创建到 Workflow 编排的完整流程
- **[技术架构](docs/architecture.md)** - 核心差异对比、技术选型、系统设计
- **[安装指南](docs/installation.md)** - 安装方式、依赖说明、可选功能
- **[使用指南](docs/user-guide.md)** - CDP 命令、Recipe 管理、Run 系统
- **[Recipe 系统](docs/recipes.md)** - AI-First 设计、元数据驱动、Workflow 编排
- **[开发指南](docs/development.md)** - 项目结构、开发规范、测试方法
- **[项目进展](docs/roadmap.md)** - 已完成功能、待办事项、版本规划

---

## 项目状态

📍 **当前阶段**：GUI 应用模式和 Agent 会话监控完成，四大系统协同工作

**已完成（Feature 008-010）**：

- ✅ GUI 应用模式 - pywebview 跨平台桌面界面
- ✅ GUI 设计重构 - GitHub Dark 配色方案
- ✅ Agent 会话监控 - 实时执行跟踪和数据持久化
- ✅ JSONL 增量解析 - watchdog 文件系统监控
- ✅ 多 Agent 支持 - 适配器模式（Claude Code、Cursor、Cline）

**核心基建**：

- ✅ 原生 CDP 协议层（直接控制 Chrome）
- ✅ Recipe 元数据驱动架构（多运行时支持）
- ✅ Run 命令系统（持久化上下文、JSONL 日志）
- ✅ Session 监控系统（实时执行跟踪）
- ✅ CLI 工具和命令系统
- ✅ 三级 Recipe 管理体系

详见 [项目进展](docs/roadmap.zh-CN.md)

---

## 许可证

AGPL-3.0 License - 详见 [LICENSE](LICENSE) 文件

## 贡献

欢迎提交 Issue 和 Pull Request！

- 项目问题：[提交 Issue](https://github.com/tsaijamey/Frago/issues)
- 技术讨论：[Discussions](https://github.com/tsaijamey/Frago/discussions)

### 贡献者

<a href="https://github.com/tsaijamey/Frago/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=tsaijamey/Frago" />
</a>

---

Created with Claude Code | 2025-11
