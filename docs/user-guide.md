# AuViMa 使用指南

## 支持的内容类型

AuViMa专注于制作4类教学/演示视频：

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
2. **信息收集**（/auvima.start）→ start.done
3. **分镜规划**（/auvima.storyboard）→ storyboard.done
4. **循环生成视频**（/auvima.generate × N）→ generate.done
5. **素材评估**（/auvima.evaluate）→ evaluate.done
6. **视频合成**（/auvima.merge）→ merge.done
7. **环境清理**，输出最终视频

整个流程完全自动化，通过.done文件进行阶段同步。

## CDP命令使用指南

### 基础CDP命令

所有CDP功能通过统一的CLI接口（`uv run auvima <command>`）访问。

```bash
# 导航网页
uv run auvima navigate <url>

# 点击元素
uv run auvima click <selector>

# 执行JavaScript
uv run auvima exec-js <expression>

# 截图
uv run auvima screenshot <output_file>

# 其他命令
uv run auvima --help
```

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
uv run auvima recipe list

# 以JSON格式列出（便于AI解析）
uv run auvima recipe list --format json

# 查看Recipe详细信息
uv run auvima recipe info youtube_extract_video_transcript

# 执行Recipe（推荐方式）
uv run auvima recipe run youtube_extract_video_transcript \
    --params '{"url": "https://youtube.com/watch?v=..."}' \
    --output-file transcript.txt

# 输出到剪贴板
uv run auvima recipe run upwork_extract_job_details_as_markdown \
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
uv run auvima recipe run youtube_extract_video_transcript \
    --params '{"url": "https://youtube.com/..."}' \
    --output-file transcript.txt

# 方式2: 发现可用的Recipe
uv run auvima recipe list --format json

# 方式3: 传统方式 - 直接执行JS（绕过元数据系统）
uv run auvima exec-js examples/atomic/chrome/youtube_extract_video_transcript.js
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

通过 `/auvima.recipe` 命令（Claude Code Slash Command）管理Recipe：

```
# 创建新Recipe（AI交互式引导）
/auvima.recipe create "在YouTube视频页面提取完整字幕内容"

# 更新现有Recipe
/auvima.recipe update youtube_extract_subtitles "YouTube改版后字幕按钮失效了"

# 列出所有Recipe
/auvima.recipe list
```

### Recipe存储结构

- **位置**: `src/auvima/recipes/`（引擎代码），`examples/atomic/chrome/`（示例Recipe）
- **命名约定**: `<平台>_<功能描述>.js`（例如 `youtube_extract_subtitles.js`）
- **配套文档**: 每个Recipe脚本(.js)都有对应的Markdown文档(.md)
- **执行方式**: `uv run auvima recipe run <recipe_name>`

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

## 注意事项

1. Chrome必须通过CDP启动器运行，保持9222端口可用
2. 录制前需要授权屏幕录制权限
3. 所有截图必须使用绝对路径
4. 视频长度必须大于等于音频总长度
5. 每个分镜完成后必须创建`.completed`标记文件
