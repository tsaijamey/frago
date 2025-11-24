# AuViMa - Multi-Runtime Automation Infrastructure

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey)](https://github.com/tsaijamey/AuViMa)
[![Chrome](https://img.shields.io/badge/requires-Chrome-green)](https://www.google.com/chrome/)
[![Claude Code](https://img.shields.io/badge/powered%20by-Claude%20Code-purple)](https://claude.ai/code)

为 AI agent 设计的多运行时自动化基建，提供持久化上下文管理和可复用的 Recipe 系统。

---

## AuViMa 解决什么问题

AI agent 在执行自动化任务时，面临三个核心痛点：

### 1. 无工作记忆

每次任务都从零开始，无法记住之前做过什么：

- 重复推理相同的操作流程（浏览器 DOM 结构、系统命令、API 调用）
- 验证过的脚本和方法无法积累
- 相似任务需要重新探索，浪费 token 和时间

### 2. 工具发现困难

不知道有哪些可用的自动化能力：

- 没有标准化的工具清单和能力描述
- 验证过的自动化脚本散落在对话历史中
- AI 无法自动发现和调用已有的工具

### 3. 需要持续人工介入

无法自主完成复杂多步骤任务：

- 缺少任务上下文管理，难以处理中断和恢复
- 缺少标准化的执行日志，无法回溯和审计
- 复杂任务需要人类持续参与每个步骤

---

## 解决方案

AuViMa 提供三个核心系统来解决上述问题：

### 🧠 Run 系统 - AI 的工作记忆

持久化任务上下文，记录完整的探索过程：

```bash
# 创建任务实例
uv run auvima run init "调研 YouTube 字幕提取方法"

# 所有后续操作自动关联到该实例
uv run auvima navigate https://youtube.com/watch?v=...
uv run auvima screenshot step1.png
uv run auvima run log --step "定位字幕按钮" --data '{"selector": "..."}'

# 持久化存储
projects/youtube-transcript-research/
├── logs/execution.jsonl          # 结构化日志
├── screenshots/                  # 截图归档
├── scripts/                      # 验证脚本
└── outputs/                      # 输出文件
```

**价值**：避免重复探索，积累可审计的执行历史。

### 📚 Recipe 系统 - AI 的“肌肉记忆”

元数据驱动的可复用自动化脚本，AI 可自动发现和使用：

```yaml
# examples/atomic/chrome/youtube_extract_video_transcript.md
---
name: youtube_extract_video_transcript
type: atomic
runtime: chrome-js
description: "提取 YouTube 视频的完整转录文本"
use_cases:
  - "批量提取视频字幕内容用于文本分析"
  - "为视频创建索引或摘要"
output_targets: [stdout, file]
---
```

```bash
# AI 发现可用 Recipe
uv run auvima recipe list --format json

# 执行 Recipe
uv run auvima recipe run youtube_extract_video_transcript \
  --params '{"url": "..."}' \
  --output-file transcript.txt
```

**价值**：固化高频操作，避免重复 AI 推理，支持三级优先级管理（Project > User > Example）。

### ⚡ 原生 CDP - 轻量级执行引擎

直连 Chrome DevTools Protocol，无需 Playwright/Selenium 依赖：

```bash
# 导航
uv run auvima navigate https://github.com

# 点击元素
uv run auvima click 'button[type="submit"]'

# 执行 JavaScript
uv run auvima exec-js 'document.title' --return-value

# 截图
uv run auvima screenshot output.png
```

**架构对比**：

```
Playwright:  Python → Node.js 中继 → CDP → Chrome  (~100MB)
AuViMa:      Python → CDP → Chrome                  (~2MB)
```

**价值**：轻量级部署，持久浏览器会话，直连无中继延迟。

---

## 核心特性

| 特性                          | 说明                                          |
| ----------------------------- | --------------------------------------------- |
| 🧠**Run 命令系统**      | 主题型任务管理，持久化上下文和 JSONL 日志     |
| 📚**Recipe 元数据驱动** | 可复用脚本，AI 可发现和使用，支持三级优先级   |
| ⚡**原生 CDP**          | ~2MB 轻量级，直连 Chrome，无 Node.js 依赖     |
| 🔄**多运行时**          | Chrome JS、Python、Shell 三种运行时支持       |
| 📊**结构化日志**        | JSONL 格式，100% 可程序解析和审计             |
| 🤖**AI 主持任务**       | Claude Code slash 命令集成（`/auvima.run`） |

---

## 快速开始

### 安装

```bash
# 基础安装（核心功能）
pip install auvima
# 或使用 uv（推荐）
uv add auvima

# 开发环境
git clone https://github.com/tsaijamey/AuViMa.git
cd AuViMa
uv sync --all-extras --dev
```

详见 [安装指南](docs/installation.md)

### 基础使用

#### 1. 创建并管理 Run 实例

```bash
# 创建任务实例
uv run auvima run init "在 Upwork 上搜索 Python 职位"

# 设置当前工作上下文
uv run auvima run set-context <run_id>

# 执行操作并记录日志
uv run auvima navigate https://upwork.com/search
uv run auvima run log \
  --step "导航到搜索页" \
  --status "success" \
  --action-type "navigation" \
  --execution-method "command"

# 查看实例详情
uv run auvima run info <run_id>
```

#### 2. 使用 Recipe

```bash
# 列出可用 Recipe
uv run auvima recipe list

# 查看 Recipe 详情
uv run auvima recipe info youtube_extract_video_transcript

# 执行 Recipe
uv run auvima recipe run youtube_extract_video_transcript \
  --params '{"url": "https://youtube.com/watch?v=..."}' \
  --output-file transcript.txt
```

#### 3. Claude Code 集成（AI 主持任务）

在 Claude Code 中使用 slash 命令：

```
/auvima.run 在 Upwork 上搜索 Python 职位并分析技能要求
```

AI 将自动：

1. 发现或创建 Run 实例
2. 调用 CDP 命令和 Recipe
3. 记录所有操作到结构化日志
4. 生成执行报告和输出文件

---

## 与其他工具的对比

### AuViMa vs Playwright/Selenium

| 维度                 | Playwright/Selenium                | AuViMa                            |
| -------------------- | ---------------------------------- | --------------------------------- |
| **设计目标**   | 测试自动化框架                     | AI 驱动的多运行时自动化基建       |
| **核心场景**   | E2E 测试、UI 测试                  | 数据采集、工作流编排、AI 辅助任务 |
| **浏览器管理** | 完整生命周期（启动→测试→关闭）   | 连接现有 CDP 实例（持久会话）     |
| **部署体积**   | ~100MB + Node.js                   | ~2MB（纯 Python WebSocket）       |
| **架构**       | 双 RPC（Python→Node.js→Browser） | 直连 CDP（Python→Browser）       |
| **知识沉淀**   | 无                                 | Recipe 元数据驱动系统             |

**适用场景选择**：

- 需要质量保障、回归测试 → Playwright/Selenium
- 需要数据采集、AI 辅助自动化、知识积累 → AuViMa

详见 [技术架构对比](docs/architecture.md#核心差异对比)

---

## 文档导航

- **[使用场景](docs/use-cases.md)** - 从 Recipe 创建到 Workflow 编排的完整流程
- **[技术架构](docs/architecture.md)** - 核心差异对比、技术选型、系统设计
- **[安装指南](docs/installation.md)** - 安装方式、依赖说明、可选功能
- **[使用指南](docs/user-guide.md)** - CDP 命令、Recipe 管理、Run 系统
- **[Recipe 系统](docs/recipes.md)** - AI-First 设计、元数据驱动、Workflow 编排
- **[开发指南](docs/development.md)** - 项目结构、开发规范、测试方法
- **[项目进展](docs/roadmap.md)** - 已完成功能、待办事项、版本规划

---

## 项目状态

📍 **当前阶段**：Run 命令系统完成，多运行时自动化基建就绪

**已完成（Feature 005）**：

- ✅ Run 命令系统 - 主题型任务管理和上下文积累
- ✅ 结构化日志 - JSONL 格式的执行记录
- ✅ AI 主持任务执行 - `/auvima.run` slash 命令集成
- ✅ Run 实例自动发现 - 基于 RapidFuzz 的模糊匹配
- ✅ 完整测试覆盖 - 单元测试、集成测试、契约测试

**核心基建**：

- ✅ 原生 CDP 协议层（直接控制 Chrome）
- ✅ Recipe 元数据驱动架构（多运行时支持）
- ✅ CLI 工具和命令系统
- ✅ 三级 Recipe 管理体系

详见 [项目进展](docs/roadmap.md) 和 [Run 命令系统规格说明](specs/005-run-command-system/spec.md)

---

## 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 作者

**Jamey Tsai** - [caijia@frago.ai](mailto:caijia@frago.ai)

项目创始人和主要维护者

## 贡献

欢迎提交 Issue 和 Pull Request！

- 项目问题：[提交 Issue](https://github.com/tsaijamey/AuViMa/issues)
- 技术讨论：[Discussions](https://github.com/tsaijamey/AuViMa/discussions)

---

Created with Claude Code | 2025-11
