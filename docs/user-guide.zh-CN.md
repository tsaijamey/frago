# Frago 使用指南

## 核心使用场景

Frago 适用于各类浏览器自动化和数据采集任务：

1. **网页数据采集** - 批量提取结构化信息
   - 示例：`"从Upwork提取职位详情并导出为Markdown"`

2. **社交媒体分析** - 收集和分析社交内容
   - 示例：`"提取Twitter/X帖子及评论"`

3. **内容转录** - 提取视频/音频的文本内容
   - 示例：`"下载YouTube视频的字幕文本"`

4. **自定义工作流** - 组合多个Recipe完成复杂任务
   - 示例：`"批量处理表单提交、截图归档"`

**典型工作流程**：
1. AI 分析任务需求，选择合适的 Recipe
2. 调用 CDP 命令控制 Chrome 执行操作
3. 记录执行日志到 JSONL 文件（100% 可解析）
4. 输出结构化数据（JSON/Markdown/文本）
5. 持久化任务上下文到 Run 实例

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

## Pipeline 完整执行流程

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
2. **信息收集**（/frago.start）→ start.done
3. **分镜规划**（/frago.storyboard）→ storyboard.done
4. **循环生成视频**（/frago.generate × N）→ generate.done
5. **素材评估**（/frago.evaluate）→ evaluate.done
6. **视频合成**（/frago.merge）→ merge.done
7. **环境清理**，输出最终视频

整个流程完全自动化，通过.done文件进行阶段同步。

## CDP命令使用指南

### 基础CDP命令

所有CDP功能通过统一的CLI接口（`uv run frago <command>`）访问。

```bash
# 导航网页
uv run frago navigate <url>

# 点击元素
uv run frago click <selector>

# 执行JavaScript
uv run frago exec-js <expression>

# 截图
uv run frago screenshot <output_file>

# 其他命令
uv run frago --help
```

### 代理配置

Frago的CDP集成支持代理配置，适用于需要通过代理访问网络的环境。

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
uv run frago navigate https://example.com \
    --proxy-host proxy.example.com \
    --proxy-port 8080

# 绕过代理
uv run frago navigate https://example.com --no-proxy
```

### 重试机制

CDP连接支持智能重试机制，特别针对代理环境优化：

- **默认重试策略**：最多3次，指数退避延迟
- **代理连接重试策略**：最多5次，更短延迟，适用于代理环境
- **连接超时**：默认30秒
- **命令超时**：默认60秒

重试机制会自动识别代理连接失败并提供诊断信息。

## Recipe管理和使用

Recipe系统提供元数据驱动的自动化脚本管理。

### Recipe管理命令

```bash
# 列出所有可用的Recipe
uv run frago recipe list

# 以JSON格式列出（便于AI解析）
uv run frago recipe list --format json

# 查看Recipe详细信息
uv run frago recipe info youtube_extract_video_transcript

# 执行Recipe（推荐方式）
uv run frago recipe run youtube_extract_video_transcript \
    --params '{"url": "https://youtube.com/watch?v=..."}' \
    --output-file transcript.txt

# 输出到剪贴板
uv run frago recipe run upwork_extract_job_details_as_markdown \
    --params '{"url": "..."}' \
    --output-clipboard
```

**支持选项**：
- `--format [table/json/names]` - 输出格式（list命令）
- `--source [project/user/example/all]` - 过滤Recipe来源（list命令）
- `--type [atomic/workflow/all]` - 过滤Recipe类型（list命令）
- `--params '{...}'` - JSON参数（run命令）
- `--params-file <path>` - 从文件读取参数（run命令）
- `--output-file <path>` - 保存输出到文件
- `--output-clipboard` - 复制输出到剪贴板
- `--timeout <seconds>` - 执行超时时间

### 使用Recipe的三种方式

```bash
# 方式1: 推荐 - 元数据驱动（参数验证、输出处理）
uv run frago recipe run youtube_extract_video_transcript \
    --params '{"url": "https://youtube.com/..."}' \
    --output-file transcript.txt

# 方式2: 发现可用的Recipe
uv run frago recipe list --format json

# 方式3: 传统方式 - 直接执行JS（绕过元数据系统）
uv run frago exec-js examples/atomic/chrome/youtube_extract_video_transcript.js
```

### 可用的示例Recipe

当前提供4个示例Recipe：

| 名称 | 功能 | 支持输出 |
|------|------|----------|
| `test_inspect_tab` | 获取当前标签页诊断信息（标题、URL、DOM统计） | stdout |
| `youtube_extract_video_transcript` | 提取YouTube视频完整字幕 | stdout, file |
| `upwork_extract_job_details_as_markdown` | 提取Upwork职位详情为Markdown格式 | stdout, file |
| `x_extract_tweet_with_comments` | 提取X(Twitter)推文和评论 | stdout, file, clipboard |

### 创建和更新Recipe

通过 `/frago.recipe` 命令（Claude Code Slash Command）管理Recipe：

```
# 创建新Recipe（AI交互式引导）
/frago.recipe create "在YouTube视频页面提取完整字幕内容"

# 更新现有Recipe
/frago.recipe update youtube_extract_subtitles "YouTube改版后字幕按钮失效了"

# 列出所有Recipe
/frago.recipe list
```

### Recipe存储结构

- **位置**: `src/frago/recipes/`（引擎代码），`examples/atomic/chrome/`（示例Recipe）
- **命名约定**: `<平台>_<功能描述>.js`（例如 `youtube_extract_subtitles.js`）
- **配套文档**: 每个Recipe脚本(.js)都有对应的Markdown文档(.md)
- **执行方式**: `uv run frago recipe run <recipe_name>`

## 项目目录结构

每个视频项目会在 `projects/<project_name>/` 目录下创建以下结构：

```
projects/<project_name>/
├── research/                # AI信息收集输出
│   ├── report.json
│   └── screenshots/
├── shots/                   # AI分镜规划输出
│   └── shot_xxx.json
├── clips/                   # AI生成的视频片段
│   ├── shot_xxx_record.sh   # AI创作的录制脚本
│   ├── shot_xxx.mp4
│   └── shot_xxx_audio.mp3
├── outputs/                 # 最终视频输出
└── logs/                    # 执行日志
```

## 资源管理

Frago 是开源项目——任何人都可以通过 PyPI 安装。但**骨骼**是通用的，**大脑**是私人的。每个人都有自己的应用场景、个性化知识（skills）和自定义自动化脚本（recipes）。

Frago 的理念：**跨环境一致**。无论你在哪台机器、全新安装还是新项目，你的资源都应该随时可用。工具来自 PyPI；大脑来自你的私有仓库。

### 资源流向

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

### 资源管理命令

| 命令 | 方向 | 用途 |
|------|------|------|
| `publish` | 项目 → 系统 | 将项目资源发布到系统目录 |
| `sync` | 系统 → 远程 | 将系统资源同步到你的私有 Git 仓库 |
| `deploy` | 远程 → 系统 | 从私有仓库拉取到系统目录 |
| `dev-load` | 系统 → 项目 | 将系统资源加载到当前项目（仅开发用） |

### 命令用法

#### 配置私有仓库

```bash
# 首次使用：配置你的私有仓库
frago sync --set-repo git@github.com:you/my-frago-resources.git
```

#### 发布本地改动

```bash
# 在项目中编辑完 recipes/skills 后
frago publish              # 项目 → 系统（~/.claude/, ~/.frago/）
frago publish --dry-run    # 预览将要发布的内容
frago publish --force      # 强制覆盖已存在文件

# 推送到远程仓库
frago sync                 # 系统 → 远程 Git
frago sync --no-push       # 仅提交，不推送
frago sync -m "message"    # 自定义提交信息
```

#### 部署到新设备

```bash
# 从私有仓库拉取
frago deploy               # 远程 Git → 系统
frago deploy --dry-run     # 预览将要部署的内容
frago deploy --force       # 强制覆盖已存在文件

# Frago 开发者：加载到项目目录
frago dev-load             # 系统 → 项目
frago dev-load --dry-run   # 预览将要加载的内容
```

### 同步范围

只同步 Frago 专属资源，保护你的个人配置：

| 资源类型 | 模式 | 位置 |
|---------|------|------|
| 命令 | `frago.*.md` | `~/.claude/commands/` |
| 命令规则 | `frago/` 目录 | `~/.claude/commands/frago/` |
| Skills | `frago-*` 前缀 | `~/.claude/skills/` |
| Recipes | 所有配方 | `~/.frago/recipes/` |

你的个人非 Frago 的 Claude 命令和 skills **永远不会被触及**。

### 典型工作流

**开发者流程**（本地改动 → 云端）：
```bash
# 1. 在项目中编辑 recipes（examples/）
# 2. 发布到系统目录
frago publish
# 3. 同步到私有仓库
frago sync
```

**新设备流程**（云端 → 本地）：
```bash
# 1. 配置仓库（仅首次）
frago sync --set-repo git@github.com:you/my-frago-resources.git
# 2. 从仓库部署
frago deploy
# 3.（可选）如果开发 Frago，加载到项目
frago dev-load
```

**普通用户**（只使用 Frago）：
```bash
# 从你的仓库获取最新资源
frago deploy
# 资源现在在 ~/.claude/ 和 ~/.frago/，可以直接使用
```

---

## 注意事项

1. Chrome必须通过CDP启动器运行，保持9222端口可用
2. 录制前需要授权屏幕录制权限
3. 所有截图必须使用绝对路径
4. 视频长度必须大于等于音频总长度
5. 每个分镜完成后必须创建`.completed`标记文件
