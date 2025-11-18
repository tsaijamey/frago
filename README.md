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

### 支持的内容类型

1. **资讯深度分析** - 基于核心观点的论证型内容
   - 示例：`"AI将如何改变教育行业 - 观点：个性化学习是核心"`

2. **GitHub项目解析** - 开源项目的深度介绍
   - 示例：`"分析 https://github.com/langchain-ai/langchain"`

3. **产品介绍** - 软件产品的功能演示
   - 示例：`"介绍 Notion 的核心功能"`

4. **MVP开发演示** - 从想法到产品的开发过程
   - 示例：`"用React开发一个番茄钟应用"`

**工作流程**（录制真实操作，非AI生成画面）：
1. AI分析主题，收集网页/代码信息
2. AI设计分镜脚本（精确到秒的时间轴）
3. AI创作录制脚本，控制Chrome执行操作并录屏
4. TTS生成配音音频
5. 合成视频+音频为最终成品

## 🎯 核心差异对比

### AuViMa vs Playwright / Selenium

| 维度 | **Playwright / Selenium** | **AuViMa** |
|------|--------------------------|-----------|
| **核心定位** | 测试自动化框架 | AI驱动的视频制作工具 |
| **设计目标** | 验证软件质量 | 创作视频内容 |
| **主要场景** | E2E测试、UI自动化测试 | 视频教程录制、演示视频制作 |
| **浏览器管理** | 完整生命周期（启动→测试→关闭） | 连接现有CDP实例（持久会话） |
| **输出产物** | 测试报告（✅❌统计） | 视频素材 + 成品视频 |
| **核心能力** | 断言验证、并发测试 | 视觉效果、屏幕录制、分镜设计 |
| **依赖体积** | ~400MB + Node.js运行时 | ~2MB (纯Python WebSocket) |
| **架构特点** | 双RPC（Python→Node.js→Browser） | 直连CDP（Python→Browser） |
| **适用场景** | 质量保障、回归测试 | 内容创作、知识传播 |

**关键差异**：
- ✅ **持久化浏览器会话** - Playwright每次测试启动新浏览器，AuViMa连接已运行的Chrome实例
- ✅ **视觉增强优先** - 提供spotlight、highlight、annotate等录制优化的UI叠加效果
- ✅ **零中继层** - 直接WebSocket连接CDP，无Node.js中继，延迟更低
- ✅ **轻量级部署** - 无需Node.js环境，纯Python实现

### AuViMa vs Browser Use

| 维度 | **Browser Use** | **AuViMa** |
|------|----------------|-----------|
| **核心定位** | 通用AI自动化平台 | 视频制作专业工具 |
| **AI角色** | 任务执行者（用户说"做什么"） | 创作流程执行者（Pipeline说"执行哪个阶段"） |
| **执行模式** | 单一自然语言任务 → AI自主完成 | 视频主题 → Pipeline调度 → Claude AI分阶段创作 |
| **决策范围** | 如何完成单个任务（如填表、抓数据） | 如何设计并制作整个视频（分镜、时间轴、视觉效果） |
| **复杂度处理** | AI动态适应DOM变化 | 精确控制+Recipe固化高频操作 |
| **结果可控性** | 中（AI可能走偏） | 高（精确到秒的时间轴控制） |
| **执行速度** | 慢（需LLM推理+试错） | 快（直接命令执行/Recipe复用） |
| **成本模式** | 云服务$500/月 + LLM API调用 | 自托管免费（可选Claude API） |
| **典型用例** | 自动填写表单、数据抓取 | 教学视频、产品演示、项目解析 |

**核心差异**：
- 🎬 **创作导向** - Browser Use通用自动化，AuViMa专注视频内容制作
- 📦 **Recipe系统** - 不是替代AI，而是让AI避免重复推理高频DOM操作（省时省token）
- 🎨 **视觉工具链** - 为录制优化的spotlight/highlight/annotate，Browser Use无此需求
- ⚡ **混合策略** - AI自主决策（分镜设计）+ 精确控制（录制脚本）+ Recipe加速（YouTube字幕提取）

## 🏗️ 技术架构选型

### 为什么选择原生CDP而非Playwright？

**Browser Use的经验教训**（他们从Playwright迁移到原生CDP）：

1. **性能瓶颈消除**
   ```
   Playwright: Python → Node.js中继 → CDP → Chrome
   AuViMa:     Python → CDP → Chrome
   ```
   - 双RPC架构在大量CDP调用时产生明显延迟
   - 迁移后："Massively increased speed for element extraction and screenshots"

2. **已知的Playwright限制**
   - ❌ `fullPage=True` 截图在 >16,000px 页面时崩溃
   - ❌ Tab崩溃时Node.js进程无限挂起
   - ❌ 跨域iframe（OOPIF）支持缺口
   - ✅ 原生CDP可直接访问完整协议，无抽象层限制

3. **依赖轻量化**
   - Playwright: ~400MB + Node.js运行时
   - AuViMa: ~2MB (websocket-client)

**结论**：对于需要**频繁CDP调用、大量截图、持久会话**的视频制作场景，原生CDP是更优选择。

### Recipe系统：AI的加速器

**设计理念**：
- ❌ **不是**替代AI自主决策
- ✅ **是**避免AI重复推理相同的DOM操作

**工作机制**：
```
高频操作路径：
  首次遇到 → AI交互式探索 → 固化为Recipe → 后续直接复用

  例如：YouTube字幕提取
  1. 用户：/auvima.recipe create "提取YouTube字幕"
  2. AI：交互式定位按钮、提取文本
  3. 固化：youtube_extract_subtitles.js
  4. 复用：uv run auvima exec-js recipes/youtube_extract_subtitles.js

  节省：每次3-5轮LLM推理 → 1次脚本执行（~100ms）
```

**与Browser Use的差异**：
- Browser Use: 每次任务都需LLM推理（$$$）
- AuViMa: AI决策（分镜设计）+ Recipe加速（重复操作）

## 系统架构

### 三层架构设计

```
┌─────────────────────────────────────────────────────────┐
│  Pipeline Master (Python调度器)                          │
│  - 启动Chrome CDP                                        │
│  - 调度5个阶段                                            │
│  - 通过.done文件同步                                     │
└──────────────────┬──────────────────────────────────────┘
                   │ 调用slash commands
                   ↓
┌─────────────────────────────────────────────────────────┐
│  Claude AI (创作执行者)                                   │
│  - /auvima.start:      AI自主决策信息收集策略            │
│  - /auvima.storyboard: AI自主设计分镜和时间轴            │
│  - /auvima.generate:   AI为每个clip创作录制脚本          │
│  - /auvima.evaluate:   AI自主评估质量问题                │
│  - /auvima.merge:      AI自主合成视频                    │
└──────────────────┬──────────────────────────────────────┘
                   │ 使用工具层
                   ↓
┌─────────────────────────────────────────────────────────┐
│  CDP工具层 (直连Chrome)                                   │
│  - uv run auvima <command>                               │
│  - Recipe系统（可选加速）                                 │
│  - 原生WebSocket连接（无Node.js中继）                    │
└──────────────────┬──────────────────────────────────────┘
                   ↓
             Chrome浏览器
```

### AI自主决策的体现

**每个阶段都是AI创作过程**，不是简单的脚本执行：

#### 阶段0: 环境准备
- **执行者**：Pipeline Master
- **任务**：启动Chrome CDP (端口9222)
- **输出**：Chrome进程持久运行

#### 阶段1: 信息收集 (`/auvima.start`)
- **执行者**：**Claude AI**
- **输入**：视频主题
- **AI决策内容**：
  - 识别主题类型（资讯/GitHub/产品/MVP）
  - 规划信息源和收集策略
  - 判断哪些截图和内容是核心
  - 决定使用哪些工具（CDP/Git/Recipe）
- **输出**：
  - `research/report.json` - 信息报告
  - `research/screenshots/` - 截图素材
  - `start.done` - 完成标记

#### 阶段2: 分镜规划 (`/auvima.storyboard`)
- **执行者**：**Claude AI**
- **输入**：`research/report.json`
- **AI决策内容**：
  - 设计叙事结构和逻辑流程
  - 规划每个镜头的重点和时长
  - 设计精确到秒的动作时间轴
  - 选择合适的视觉效果（spotlight/highlight）
- **输出**：
  - `shots/shot_xxx.json` - 分镜序列（含详细action_timeline）
  - `storyboard.done` - 完成标记

#### 阶段3: 视频生成循环 (`/auvima.generate`)
**Pipeline控制循环，AI创作每个clip**：

```
for each shot_xxx.json:
    ├── AI分析分镜需求
    ├── AI编写专属录制脚本 (clips/shot_xxx_record.sh)
    │   - 精确控制每个动作的时间点
    │   - 设计视觉效果的出现和消失
    │   - 协调录制和操作的同步
    ├── 执行脚本录制 shot_xxx.mp4
    ├── 生成音频 shot_xxx_audio.mp3
    ├── AI验证质量（时长、内容、同步）
    └── 创建标记 shot_xxx.done
```

- **执行者**：**Claude AI** (每次都是独立创作)
- **核心理念**：不是批量处理，而是为每个clip定制脚本
- **Recipe角色**：加速高频DOM操作（如YouTube字幕提取），避免重复LLM推理
- **完成标记**：`generate.done`

#### 阶段4: 素材评估 (`/auvima.evaluate`)
- **执行者**：**Claude AI**
- **AI决策内容**：
  - 分析所有clips的完整性
  - 识别质量问题（模糊、截断、时长不匹配）
  - 提出修复建议或自动修复
  - 验证音视频同步
- **输出**：
  - `evaluation_report.json` - 评估报告
  - `evaluate.done` - 完成标记

#### 阶段5: 视频合成 (`/auvima.merge`)
- **执行者**：**Claude AI**
- **AI决策内容**：
  - 确定合并顺序和过渡效果
  - 处理音频同步和平滑
  - 添加片头片尾（如需要）
  - 选择输出格式和质量参数
- **输出**：
  - `outputs/final_output.mp4` - 最终视频
  - `merge.done` - 完成标记

#### 阶段6: 清理环境
- **执行者**：Pipeline Master
- **任务**：关闭Chrome，清理临时文件

### 核心设计理念

1. **AI是创作者，不是执行器**
   - 每个阶段AI都在做创作决策
   - Pipeline只负责调度和同步
   - Recipe是给AI用的加速工具

2. **混合策略的优势**
   ```
   新场景：AI探索 → 理解 → 执行
   熟悉场景：Recipe直接复用（省时省token）
   复杂场景：AI创作 + Recipe加速高频部分
   ```

3. **与Browser Use的本质不同**
   - Browser Use: 通用任务自动化（适应性强）
   - AuViMa: 视频创作流程化（控制力强）

## 目录结构

```
AuViMa/
├── README.md                        # 项目说明
├── CLAUDE.md                        # 项目配置（技术栈、代码风格）
├── .claude/
│   ├── commands/                    # Claude Code Slash Commands
│   │   ├── auvima_start.md          # AI信息收集命令
│   │   ├── auvima_storyboard.md     # AI分镜规划命令
│   │   ├── auvima_generate.md       # AI视频生成命令（创作录制脚本）
│   │   ├── auvima_evaluate.md       # AI素材评估命令
│   │   ├── auvima_merge.md          # AI视频合成命令
│   │   └── auvima_recipe.md         # Recipe管理命令（创建/更新/列表）
│   └── settings.local.json          # 项目配置
│
├── src/                             # 核心Python代码
│   ├── auvima/                      # AuViMa核心包
│   │   ├── cdp/                     # CDP协议实现（原生WebSocket）
│   │   │   ├── client.py            # CDP客户端基类
│   │   │   ├── session.py           # 会话管理（连接/重试/事件）
│   │   │   ├── config.py            # 配置管理（代理支持）
│   │   │   ├── logger.py            # 日志系统
│   │   │   ├── retry.py             # 重试策略
│   │   │   ├── exceptions.py        # 异常定义
│   │   │   ├── types.py             # 数据类型
│   │   │   └── commands/            # CDP命令实现
│   │   │       ├── page.py          # 页面操作（导航/标题/内容）
│   │   │       ├── screenshot.py    # 截图功能
│   │   │       ├── runtime.py       # JavaScript执行
│   │   │       ├── input.py         # 输入操作（点击）
│   │   │       ├── scroll.py        # 滚动操作
│   │   │       ├── wait.py          # 等待操作
│   │   │       ├── zoom.py          # 缩放操作
│   │   │       ├── status.py        # 状态检查
│   │   │       └── visual_effects.py # 视觉效果（spotlight/highlight）
│   │   ├── cli/                     # 命令行接口
│   │   │   ├── main.py              # CLI入口（Click框架）
│   │   │   └── commands.py          # 所有CLI命令实现
│   │   ├── recipes/                 # Recipe脚本库（AI加速工具）
│   │   │   ├── youtube_extract_subtitles.js    # YouTube字幕提取
│   │   │   ├── youtube_extract_subtitles.md    # 知识文档
│   │   │   └── ... (其他平台配方)
│   │   └── tools/                   # 开发工具
│   │       └── function_mapping.py  # CDP功能映射验证工具
│   ├── chrome_cdp_launcher.py       # Chrome CDP启动器（跨平台）
│   ├── pipeline_master.py           # Pipeline主控制器
│   └── requirements.txt             # Python依赖
│
├── specs/                           # 功能规格和迭代记录
│   ├── 001-standardize-cdp-scripts/ # CDP脚本标准化
│   ├── 002-cdp-integration-refactor/# CDP集成重构（Python实现）
│   └── 003-skill-automation/        # Recipe系统设计
│
├── projects/                        # 视频项目工作目录
│   └── <project_name>/
│       ├── research/                # AI信息收集输出
│       │   ├── report.json
│       │   └── screenshots/
│       ├── shots/                   # AI分镜规划输出
│       │   └── shot_xxx.json
│       ├── clips/                   # AI生成的视频片段
│       │   ├── shot_xxx_record.sh   # AI创作的录制脚本
│       │   ├── shot_xxx.mp4
│       │   └── shot_xxx_audio.mp3
│       ├── outputs/                 # 最终视频输出
│       └── logs/                    # 执行日志
│
├── chrome_profile/                  # Chrome用户配置
└── pyproject.toml                   # Python包配置（uv管理）
```

## 技术栈

- **AI导演**：Claude Code（设计分镜、创作录制脚本）
- **浏览器控制**：Chrome DevTools Protocol (CDP) - 原生WebSocket
- **屏幕录制**：ffmpeg + AVFoundation (macOS)
- **脚本编排**：Python 3.12（Pipeline调度 + CDP工具层）
- **配音合成**：火山引擎声音克隆API（待集成）

## CDP集成使用指南

### 代理配置

AuViMa的CDP集成支持代理配置，适用于需要通过代理访问网络的环境。

#### 环境变量配置

通过环境变量设置全局代理：

```bash
export HTTP_PROXY=http://proxy.example.com:8080
export HTTPS_PROXY=http://proxy.example.com:8080
export NO_PROXY=localhost,127.0.0.1
```

#### CLI参数配置

所有CDP命令都支持代理参数：

```bash
# 使用代理
uv run auvima navigate https://example.com \
    --proxy-host proxy.example.com \
    --proxy-port 8080

# 绕过代理
uv run auvima navigate https://example.com --no-proxy
```

### 功能映射验证工具

功能映射工具用于验证所有CDP功能的完整性和一致性。

#### 运行功能映射验证

```bash
# 生成控制台报告
uv run python -m auvima.tools.function_mapping

# 生成详细HTML报告
uv run python -m auvima.tools.function_mapping --format html --output function_mapping_report.html

# 生成JSON报告
uv run python -m auvima.tools.function_mapping --format json --output function_mapping_report.json
```

#### 查看功能覆盖率

工具会扫描所有CDP功能实现，生成覆盖率报告：

```
================================
功能映射验证报告
================================
总功能数: 18
已实现: 18 (100.0%)
行为一致: 18 (100.0%)
================================
```

### CDP命令目录结构

CDP功能按类型组织在 `src/auvima/cdp/commands/` 目录下：

```
src/auvima/cdp/commands/
├── __init__.py         # 命令模块导出
├── page.py             # 页面操作（导航、获取标题/内容）
├── screenshot.py       # 截图功能
├── runtime.py          # JavaScript执行
├── input.py            # 输入操作（点击）
├── scroll.py           # 滚动操作
├── wait.py             # 等待操作
├── zoom.py             # 缩放操作
├── status.py           # 状态检查
└── visual_effects.py   # 视觉效果（高亮、指针、聚光灯、标注）
```

所有CDP功能通过统一的CLI接口（`uv run auvima <command>`）访问。

### 重试机制

CDP连接支持智能重试机制，特别针对代理环境优化：

- **默认重试策略**：最多3次，指数退避延迟
- **代理连接重试策略**：最多5次，更短延迟，适用于代理环境
- **连接超时**：默认30秒
- **命令超时**：默认60秒

重试机制会自动识别代理连接失败并提供诊断信息。

## 已完成功能 ✅

### 核心CDP实现（迭代001-002）
- [x] **原生CDP协议层**（~3,763行Python代码）
  - WebSocket直连Chrome（无Node.js中继）
  - 智能重试机制（代理环境优化）
  - 完整的命令模块（page/screenshot/runtime/input/scroll/wait/zoom/status/visual_effects）
  - 类型安全配置系统
- [x] **CLI工具**（Click框架）
  - `uv run auvima <command>` - 所有CDP功能统一接口
  - 代理配置支持（环境变量 + CLI参数）
  - 功能映射验证工具（100%覆盖率）
- [x] **跨平台Chrome启动器**
  - macOS/Linux支持
  - 自动profile初始化
  - 窗口尺寸控制（1280x960，位置20,20）

### Pipeline系统
- [x] **Pipeline Master控制器**
  - 5阶段调度（start/storyboard/generate/evaluate/merge）
  - .done文件同步机制
  - Chrome自动启动和清理
  - 完整日志系统
- [x] **Slash Commands配置**（5个AI阶段命令）
  - `/auvima.start` - AI自主信息收集
  - `/auvima.storyboard` - AI自主分镜设计
  - `/auvima.generate` - AI创作录制脚本
  - `/auvima.evaluate` - AI质量评估
  - `/auvima.merge` - AI视频合成

### Recipe系统（迭代003）
- [x] **Recipe管理命令** (`/auvima.recipe`)
  - `create` - AI交互式探索创建Recipe
  - `update` - 基于反馈迭代Recipe
  - `list` - 展示所有可用Recipe
- [x] **Recipe存储结构**
  - 扁平目录设计（`src/auvima/recipes/`）
  - 描述性命名（`<平台>_<操作>_<对象>.js`）
  - 配套知识文档（6章节标准）
  - 版本历史追踪（在.md中）

### 项目迭代记录
- [x] **Spec系统**（3次迭代）
  - 001: CDP脚本标准化（websocat方法统一）
  - 002: CDP集成重构（Python实现 + 代理支持）
  - 003: Recipe自动化系统设计

## 待完成功能 📝

### 高优先级
- [ ] **AI Slash Commands实现**
  - [ ] `/auvima.start` - AI信息收集逻辑
  - [ ] `/auvima.storyboard` - AI分镜设计逻辑
  - [ ] `/auvima.generate` - AI录制脚本生成
  - [ ] `/auvima.evaluate` - AI质量评估
  - [ ] `/auvima.merge` - AI视频合成
- [ ] **Recipe系统实现**
  - [ ] `/auvima.recipe create` - 交互式探索和固化
  - [ ] `/auvima.recipe update` - 迭代更新机制
  - [ ] Recipe执行器（`exec-js`命令）
- [ ] **Pipeline集成**
  - [ ] Pipeline与Claude CLI的集成
  - [ ] .done文件监控和阶段切换
  - [ ] 错误处理和重试机制

### 中优先级
- [ ] **音频生成**
  - [ ] 火山引擎声音克隆API集成
  - [ ] 音视频时长同步验证
  - [ ] 多音频片段支持
- [ ] **录制优化**
  - [ ] 录制脚本模板系统
  - [ ] 视觉效果时间轴控制
  - [ ] 关键帧质量检查
- [ ] **Recipe生态**
  - [ ] 常用平台配方库（YouTube/GitHub/Twitter）
  - [ ] Recipe分享和导入机制
  - [ ] Recipe性能优化

### 低优先级
- [ ] 代码展示录制（VS Code录制）
- [ ] 本地静态页面生成（for MVP演示）
- [ ] 进度监控Dashboard
- [ ] Recipe版本管理系统
- [ ] 多语言配音支持

## 使用流程

### 一键启动Pipeline

```bash
# 启动完整pipeline
uv run python src/pipeline_master.py "<主题>" <项目名>
```

### 示例命令

```bash
# 类型1：资讯深度分析
uv run python src/pipeline_master.py "AI教育革命 - 观点：个性化学习将取代传统课堂" ai_education

# 类型2：GitHub项目解析
uv run python src/pipeline_master.py "https://github.com/openai/whisper" whisper_intro

# 类型3：产品介绍
uv run python src/pipeline_master.py "Notion产品功能介绍" notion_demo

# 类型4：MVP开发演示
uv run python src/pipeline_master.py "React开发待办事项应用MVP" todo_mvp
```

### Pipeline执行流程

1. **自动启动Chrome CDP**（端口9222）
2. **信息收集**（/auvima.start）→ start.done
3. **分镜规划**（/auvima.storyboard）→ storyboard.done
4. **循环生成视频**（/auvima.generate × N）→ generate.done
5. **素材评估**（/auvima.evaluate）→ evaluate.done
6. **视频合成**（/auvima.merge）→ merge.done
7. **环境清理**，输出最终视频

整个流程完全自动化，通过.done文件进行阶段同步。

## 分镜JSON示例

```json
{
  "shot_id": "shot_001",
  "duration": 10,
  "type": "browser_recording",
  "description": "展示GitHub首页",
  "actions": [
    {
      "action": "navigate",
      "url": "https://github.com",
      "wait": 3
    },
    {
      "action": "scroll",
      "direction": "down",
      "pixels": 500,
      "wait": 2
    }
  ],
  "narration": "GitHub是全球最大的代码托管平台...",
  "audio_config": {
    "voice": "default",
    "speed": 1.0
  },
  "source_reference": "https://github.com/about"
}
```

## 环境要求

- macOS（用于AVFoundation录制）
- Chrome浏览器
- Python 3.12+
- ffmpeg 8.0+
- uv包管理器
- 屏幕录制权限（系统设置 > 隐私与安全性 > 屏幕录制）

## 依赖安装

```bash
# 系统依赖（如未安装）
brew install ffmpeg
brew install uv

# Python依赖（uv自动管理虚拟环境）
uv sync
```

## 开发规范

1. **脚本位置**：
   - 命令实现脚本放在 `scripts/`
   - Python核心脚本放在 `src/`

2. **文件命名**：
   - 视频片段：`shot_xxx.mp4`（基于时间戳）
   - 音频片段：`shot_xxx_audio.mp3` 或 `shot_xxx_1.mp3`
   - 截图文件：必须使用绝对路径保存

3. **Chrome CDP使用**：
   - prepare阶段：仅用于信息收集
   - generate阶段：加入视觉引导效果

## 注意事项

1. Chrome必须通过CDP启动器运行，保持9222端口可用
2. 录制前需要授权屏幕录制权限
3. 所有截图必须使用绝对路径
4. 视频长度必须大于等于音频总长度
5. 每个分镜完成后必须创建`.completed`标记文件

## 项目状态

📍 **当前阶段**：核心架构完成，AI命令系统实现中

**已完成**：
- ✅ 原生CDP协议层（~3,763行Python）
- ✅ CLI工具和命令系统
- ✅ Pipeline调度框架
- ✅ Recipe系统设计

**正在进行**：
- 🔄 AI Slash Commands实现（5个阶段命令）
- 🔄 Recipe系统实现（create/update/list）
- 🔄 Pipeline与Claude AI集成

**技术亮点**：
- 🏆 原生CDP（无Playwright/Selenium依赖）
- 🏆 AI导演录制（设计分镜+编写脚本，非生成画面）
- 🏆 Recipe加速系统（固化高频操作）
- 🏆 轻量级部署（~2MB依赖）

## 🤝 贡献

欢迎提交Issue和Pull Request！

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 🌟 Star History

如果这个项目对你有帮助，请给个Star支持一下！

## 📮 联系方式

- 项目问题：[提交Issue](https://github.com/yourusername/AuViMa/issues)
- 技术讨论：[Discussions](https://github.com/yourusername/AuViMa/discussions)

---

Created by Claude Code with Human | 2025-11