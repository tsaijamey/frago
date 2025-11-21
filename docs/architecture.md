# AuViMa 技术架构

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
  1. 用户：/auvima.recipe "提取YouTube字幕"
  2. AI：交互式定位按钮、提取文本
  3. 固化：youtube_extract_video_transcript.js + 元数据文档
  4. 复用：uv run auvima recipe run youtube_extract_video_transcript

  节省：每次3-5轮LLM推理 → 1次脚本执行（~100ms）
```

**使用Recipe的三种方式**：
```bash
# 方式1: 推荐 - 元数据驱动（参数验证、输出处理）
uv run auvima recipe run youtube_extract_video_transcript \
    --params '{"url": "https://youtube.com/..."}' \
    --output-file transcript.txt

# 方式2: 发现可用的Recipe
uv run auvima recipe list --format json

# 方式3: 传统方式 - 直接执行JS（绕过元数据系统）
uv run auvima exec-js examples/atomic/chrome/youtube_extract_video_transcript.js
```

**与Browser Use的差异**：
- Browser Use: 每次任务都需LLM推理（$$$）
- AuViMa: AI决策（分镜设计）+ Recipe加速（重复操作）

### Recipe元数据驱动架构（004迭代）

**设计理念：代码与资源分离**
- `src/auvima/recipes/` - Python引擎代码（元数据解析、注册表、执行器）
- `examples/atomic/chrome/` - 示例Recipe脚本 + 元数据文档
- `~/.auvima/recipes/` - 用户级Recipe（待实现）
- `.auvima/recipes/` - 项目级Recipe（待实现）

**元数据文件结构（Markdown + YAML frontmatter）**：
```markdown
---
name: youtube_extract_video_transcript
type: atomic                    # atomic | workflow
runtime: chrome-js              # chrome-js | python | shell
version: "1.0"
description: "提取YouTube视频完整字幕"
use_cases: ["视频内容分析", "字幕下载"]
tags: ["youtube", "transcript", "web-scraping"]
output_targets: [stdout, file]
inputs: {}
outputs:
  transcript:
    type: string
    description: "完整字幕文本"
---

# 功能描述
...详细说明...
```

**元数据字段说明**：
- **必需字段**：`name`, `type`, `runtime`, `version`, `inputs`, `outputs`
- **AI可理解字段**（用于发现和选择Recipe）：
  - `description`：简短功能描述（<200字符），帮助AI理解用途
  - `use_cases`：适用场景列表，帮助AI判断是否适用
  - `tags`：语义标签，用于分类和搜索
  - `output_targets`：支持的输出方式（stdout/file/clipboard），让AI选择正确的输出选项

**三级查找路径（优先级）**：
1. 项目级：`.auvima/recipes/`（当前工作目录）
2. 用户级：`~/.auvima/recipes/`（用户主目录）
3. 示例级：`examples/`（仓库根目录）

**三种运行时支持**：
- `chrome-js`：通过 `uv run auvima exec-js` 执行JavaScript
- `python`：通过Python解释器执行
- `shell`：通过Shell执行脚本

**三种输出目标**：
- `stdout`：打印到控制台
- `file`：保存到文件（`--output-file`）
- `clipboard`：复制到剪贴板（`--output-clipboard`）

**可用示例Recipe（4个）**：

| 名称 | 功能 | 支持输出 |
|------|------|----------|
| `test_inspect_tab` | 获取当前标签页诊断信息（标题、URL、DOM统计） | stdout |
| `youtube_extract_video_transcript` | 提取YouTube视频完整字幕 | stdout, file |
| `upwork_extract_job_details_as_markdown` | 提取Upwork职位详情为Markdown格式 | stdout, file |
| `x_extract_tweet_with_comments` | 提取X(Twitter)推文和评论 | stdout, file, clipboard |

```bash
# 查看所有Recipe
uv run auvima recipe list

# 查看Recipe详细信息
uv run auvima recipe info youtube_extract_video_transcript
```

### AI-First设计理念

Recipe系统的核心目标是**让AI Agent能够自主发现、理解和使用Recipe**，而不仅仅是人类开发者的工具。

**AI如何使用Recipe系统**：

```bash
# 1. AI发现可用的Recipe（通过JSON格式获取结构化数据）
uv run auvima recipe list --format json

# 2. AI分析元数据理解Recipe的能力
#    - description：这个Recipe做什么？
#    - use_cases：适合哪些场景？
#    - tags：语义分类
#    - output_targets：支持哪些输出方式？

# 3. AI根据任务需求选择合适的Recipe和输出方式
uv run auvima recipe run youtube_extract_video_transcript \
    --params '{"url": "https://youtube.com/..."}' \
    --output-file /tmp/transcript.txt  # AI判断需要文件输出

# 4. AI处理Recipe的执行结果（JSON格式）
#    成功：{"success": true, "data": {...}}
#    失败：{"success": false, "error": {...}}
```

**设计原则**：
- 所有元数据面向AI可理解性设计（语义描述 > 技术细节）
- JSON格式输出，便于AI解析和处理
- 错误信息结构化，便于AI理解失败原因并采取行动
- 输出目标明确声明，让AI选择正确的命令选项

**与人类用户的关系**：
- 人类用户：创建和维护Recipe（通过 `/auvima.recipe` 命令）
- AI Agent：发现和使用Recipe（通过 `recipe list/run` 命令）
- Recipe系统是连接两者的桥梁

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
