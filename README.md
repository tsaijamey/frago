# AuViMa - 多运行时自动化基建

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey)](https://github.com/tsaijamey/AuViMa)
[![Chrome](https://img.shields.io/badge/requires-Chrome-green)](https://www.google.com/chrome/)
[![Claude Code](https://img.shields.io/badge/powered%20by-Claude%20Code-purple)](https://claude.ai/code)

🚀 多运行时自动化基建 - 支持 Chrome CDP、Python、Shell 的自动化任务执行和管理框架，提供 Run 命令系统进行任务持久化和上下文积累。

## ✨ 核心特性

- 🚀 **Run命令系统** - 主题型任务管理，支持信息持续积累和上下文复用
- 🤖 **AI主持的任务执行** - 通过 `/auvima.run` slash 命令，让 Claude AI 自动化执行复杂任务
- 📹 **原生CDP协议** - 直接控制 Chrome 浏览器，无需 Playwright/Selenium 依赖
- ⚡ **Recipe系统** - 元数据驱动的可复用自动化脚本，支持多运行时（Chrome JS、Python、Shell）
- 📊 **结构化日志** - JSONL 格式的执行记录，100% 可程序解析和分析
- 🔄 **Workflow编排** - Python Recipe 可调用多个 atomic Recipe，构建复杂自动化流程
- 🎯 **三级优先级** - Project > User > Example 的 Recipe 管理体系

## 项目概述

AuViMa是一个AI导演的屏幕录制自动化系统，专注于制作4类教学/演示视频：

**支持的内容类型**：
- **资讯深度分析** - 基于核心观点的论证型内容
- **GitHub项目解析** - 开源项目的深度介绍
- **产品介绍** - 软件产品的功能演示
- **MVP开发演示** - 从想法到产品的开发过程

**工作流程**（录制真实操作，非AI生成画面）：
1. AI分析主题，收集网页/代码信息
2. AI设计分镜脚本（精确到秒的时间轴）
3. AI创作录制脚本，控制Chrome执行操作并录屏
4. TTS生成配音音频
5. 合成视频+音频为最终成品

## 📚 文档导航

- **[安装指南](docs/installation.md)** - 安装方式、依赖说明、可选功能
- **[技术架构](docs/architecture.md)** - 核心差异对比、技术选型、系统架构详解
- **[使用指南](docs/user-guide.md)** - 完整使用流程、CDP命令、Recipe管理
- **[Recipe系统指南](docs/recipes.md)** - AI-First设计、元数据驱动、Workflow编排
- **[开发指南](docs/development.md)** - 项目结构、开发规范、测试方法
- **[项目进展](docs/roadmap.md)** - 已完成功能、待办事项、版本规划
- **[示例参考](docs/examples.md)** - 分镜示例、Recipe脚本、典型场景

## 快速开始

### 环境要求

- **操作系统**：macOS 或 Linux（录制方式需适配）
  - macOS: 使用 AVFoundation 录制
  - Linux: 需要适配录制方案
- Chrome浏览器
- Python 3.12+
- ffmpeg 8.0+
- uv包管理器

### 安装

**基础安装**（核心功能）:
```bash
pip install auvima
# 或使用 uv（推荐）
uv add auvima
```

**完整安装**（包含所有可选功能）:
```bash
pip install auvima[all]
# 或
uv add "auvima[all]"
```

**开发环境**:
```bash
git clone https://github.com/tsaijamey/AuViMa.git
cd AuViMa
uv sync --all-extras --dev
```

详见 [安装指南](docs/installation.md)

### 基础使用

#### Run命令系统 - 任务管理

```bash
# 1. 创建并初始化run实例
uv run auvima run init "在Upwork上搜索Python职位"
# 输出: { "run_id": "zai-upwork-shang-sou-suo-python-zhi-wei", ... }

# 2. 设置为当前工作run
uv run auvima run set-context zai-upwork-shang-sou-suo-python-zhi-wei

# 3. 执行任务并记录日志
uv run auvima navigate https://upwork.com/search
uv run auvima run log \
  --step "导航到Upwork搜索页" \
  --status "success" \
  --action-type "navigation" \
  --execution-method "command" \
  --data '{"command": "uv run auvima navigate https://upwork.com/search"}'

# 4. 查看run详情和执行历史
uv run auvima run info zai-upwork-shang-sou-suo-python-zhi-wei

# 5. 列出所有run实例
uv run auvima run list

# 6. 归档已完成的run
uv run auvima run archive zai-upwork-shang-sou-suo-python-zhi-wei
```

#### Chrome CDP 命令

```bash
# 页面导航
uv run auvima navigate https://github.com

# 截图
uv run auvima screenshot output.png

# 点击元素
uv run auvima click 'button[type="submit"]'

# 执行JavaScript
uv run auvima exec-js 'document.title'
```

#### Recipe管理

```bash
# 列出所有Recipe
uv run auvima recipe list

# 查看Recipe详情
uv run auvima recipe info youtube_extract_video_transcript

# 执行Recipe
uv run auvima recipe run youtube_extract_video_transcript \
    --params '{"url": "..."}' \
    --output-file transcript.txt

# 复制示例Recipe到用户级
uv run auvima recipe copy upwork_extract_job_details_as_markdown
```

#### Claude Code集成（AI主持任务）

在 Claude Code 中使用 slash 命令：
```
/auvima.run 在Upwork上搜索Python职位并分析技能要求
```

AI 将自动：
1. 发现或创建run实例
2. 调用CDP命令和Recipe
3. 记录所有操作到结构化日志
4. 生成执行报告和输出文件

## 技术亮点

- 🏆 **原生CDP** - 无Playwright/Selenium依赖，~2MB轻量级部署
- 🏆 **AI导演录制** - 设计分镜+编写脚本，非生成画面
- 🏆 **Recipe加速系统** - 固化高频操作，避免重复AI推理
- 🏆 **持久化会话** - 直连Chrome实例，WebSocket零中继

## 项目状态

📍 **当前阶段**：Run命令系统完成，多运行时自动化基建就绪

**已完成（Feature 005）**：
- ✅ Run命令系统 - 主题型任务管理和上下文积累
- ✅ 结构化日志 - JSONL格式的执行记录
- ✅ AI主持任务执行 - `/auvima.run` slash命令集成
- ✅ Run实例自动发现 - 基于RapidFuzz的模糊匹配
- ✅ 完整测试覆盖 - 单元测试、集成测试、契约测试

**核心基建**：
- ✅ 原生CDP协议层（直接控制Chrome）
- ✅ Recipe元数据驱动架构（多运行时支持）
- ✅ CLI工具和命令系统
- ✅ 三级Recipe管理体系

详见 [项目进展](docs/roadmap.md) 和 [Run命令系统规格说明](specs/005-run-command-system/spec.md)

## 🤝 贡献

欢迎提交Issue和Pull Request！

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 👤 作者

**Jamey Tsai** - [caijia@frago.ai](mailto:caijia@frago.ai)

项目创始人和主要维护者

## 🤝 贡献者

感谢所有为本项目做出贡献的开发者！

<a href="https://github.com/tsaijamey/AuViMa/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=tsaijamey/AuViMa" />
</a>

欢迎提交 Issue 和 Pull Request！

## 📮 联系方式

- 项目问题：[提交Issue](https://github.com/tsaijamey/AuViMa/issues)
- 技术讨论：[Discussions](https://github.com/tsaijamey/AuViMa/discussions)

---

Created with Claude Code | 2025-11