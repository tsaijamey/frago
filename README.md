# AuViMa - Automated Video Maker

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)
[![macOS](https://img.shields.io/badge/platform-macOS-lightgrey)](https://www.apple.com/macos/)
[![Chrome](https://img.shields.io/badge/requires-Chrome-green)](https://www.google.com/chrome/)
[![Claude Code](https://img.shields.io/badge/powered%20by-Claude%20Code-purple)](https://claude.ai/code)

🎬 AI导演的屏幕录制工具 - Claude AI设计分镜和录制脚本，自动化录制浏览器操作生成教学视频。

## ✨ 核心特性

- 🎬 **真实录制，非AI生成** - 录制真实浏览器操作，不是文生视频
- 🤖 **AI创作录制脚本** - Claude AI设计分镜、编写每个clip的录制脚本
- 🎯 **四类内容场景** - 资讯分析、GitHub项目、产品演示、MVP开发
- 📹 **精准屏幕捕获** - 基于Chrome CDP的毫秒级操作控制
- 🎨 **视觉引导增强** - 自动添加spotlight/highlight/annotate效果
- 🎤 **TTS配音合成** - 集成声音克隆API生成解说音频
- ⚡ **Recipe加速系统** - 固化高频操作，避免重复AI推理

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

- **[技术架构](docs/architecture.md)** - 核心差异对比、技术选型、系统架构详解
- **[使用指南](docs/user-guide.md)** - 完整使用流程、CDP命令、Recipe管理
- **[开发指南](docs/development.md)** - 项目结构、开发规范、测试方法
- **[项目进展](docs/roadmap.md)** - 已完成功能、待办事项、版本规划
- **[示例参考](docs/examples.md)** - 分镜示例、Recipe脚本、典型场景

## 快速开始

### 环境要求

- macOS（用于AVFoundation录制）
- Chrome浏览器
- Python 3.12+
- ffmpeg 8.0+
- uv包管理器

### 安装依赖

```bash
# 系统依赖
brew install ffmpeg uv

# Python依赖
uv sync
```

### 基础使用

```bash
# 启动Pipeline（完整视频制作流程）
uv run python src/pipeline_master.py "<主题>" <项目名>

# CDP命令示例
uv run auvima navigate https://github.com
uv run auvima screenshot output.png

# Recipe管理
uv run auvima recipe list
uv run auvima recipe run youtube_extract_video_transcript \
    --params '{"url": "..."}' \
    --output-file transcript.txt
```

## 技术亮点

- 🏆 **原生CDP** - 无Playwright/Selenium依赖，~2MB轻量级部署
- 🏆 **AI导演录制** - 设计分镜+编写脚本，非生成画面
- 🏆 **Recipe加速系统** - 固化高频操作，避免重复AI推理
- 🏆 **持久化会话** - 直连Chrome实例，WebSocket零中继

## 项目状态

📍 **当前阶段**：核心架构完成，AI命令系统实现中

**已完成**：
- ✅ 原生CDP协议层（~3,763行Python）
- ✅ Recipe元数据驱动架构
- ✅ CLI工具和命令系统
- ✅ Pipeline调度框架

**正在进行**：
- 🔄 AI Slash Commands实现
- 🔄 Recipe系统完善
- 🔄 Pipeline与Claude AI集成

详见 [项目进展](docs/roadmap.md)

## 🤝 贡献

欢迎提交Issue和Pull Request！

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 📮 联系方式

- 项目问题：[提交Issue](https://github.com/yourusername/AuViMa/issues)
- 技术讨论：[Discussions](https://github.com/yourusername/AuViMa/discussions)

---

Created by Claude Code with Human | 2025-11