# Frago 开发指南

## 项目目录结构

```
Frago/
├── README.md                        # 项目说明
├── CLAUDE.md                        # 项目配置（技术栈、代码风格）
├── .claude/
│   ├── commands/                    # Claude Code Slash Commands
│   │   ├── frago_start.md          # AI信息收集命令
│   │   ├── frago_storyboard.md     # AI分镜规划命令
│   │   ├── frago_generate.md       # AI视频生成命令（创作录制脚本）
│   │   ├── frago_evaluate.md       # AI素材评估命令
│   │   ├── frago_merge.md          # AI视频合成命令
│   │   └── frago_recipe.md         # Recipe管理命令（创建/更新/列表）
│   └── settings.local.json          # 项目配置
│
├── src/                             # 核心Python代码
│   ├── frago/                      # Frago核心包
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
│   │   │   ├── commands.py          # 基础CDP命令实现
│   │   │   └── recipe_commands.py   # Recipe管理命令（list/info/run）
│   │   ├── recipes/                 # Recipe引擎代码（元数据驱动架构）
│   │   │   ├── __init__.py          # 模块导出
│   │   │   ├── metadata.py          # 元数据解析和验证
│   │   │   ├── registry.py          # Recipe注册表和发现
│   │   │   ├── runner.py            # Recipe执行器
│   │   │   ├── output_handler.py    # 输出处理（stdout/file/clipboard）
│   │   │   └── exceptions.py        # Recipe异常定义
│   │   ├── run/                      # Run命令系统（Feature 005）
│   │   │   ├── manager.py            # Run实例管理
│   │   │   ├── logger.py             # JSONL结构化日志
│   │   │   └── discovery.py          # 基于RapidFuzz的自动发现
│   │   ├── session/                   # 会话监控（Feature 010）
│   │   │   ├── monitor.py             # 文件系统监控（watchdog）
│   │   │   ├── parser.py              # JSONL增量解析
│   │   │   ├── storage.py             # 会话数据持久化
│   │   │   ├── models.py              # 数据模型（Session、Step、ToolCall）
│   │   │   └── formatter.py           # 输出格式化（终端/JSON）
│   │   ├── gui/                        # GUI应用模式（Feature 008-009）
│   │   │   ├── app.py                  # 主应用（pywebview）
│   │   │   ├── api.py                  # JS-Python桥接API
│   │   │   ├── models.py               # GUI配置模型
│   │   │   └── assets/                 # HTML/CSS/JS前端
│   │   │       └── index.html
│   │   └── tools/                   # 开发工具
│   │       └── function_mapping.py  # CDP功能映射验证工具
│   ├── chrome_cdp_launcher.py       # Chrome CDP启动器（跨平台）
│   ├── pipeline_master.py           # Pipeline主控制器
│   └── requirements.txt             # Python依赖
│
├── examples/                        # 示例Recipe（不打包到wheel）
│   └── atomic/
│       └── chrome/
│           ├── test_inspect_tab.js/.md                  # 页面检查诊断
│           ├── youtube_extract_video_transcript.js/.md  # YouTube字幕提取
│           ├── upwork_extract_job_details_as_markdown.js/.md  # Upwork职位详情
│           └── x_extract_tweet_with_comments.js/.md    # X(Twitter)推文+评论提取
│
├── specs/                           # 功能规格和迭代记录
│   ├── 001-standardize-cdp-scripts/ # CDP脚本标准化
│   ├── 002-cdp-integration-refactor/# CDP集成重构（Python实现）
│   ├── 003-skill-automation/        # Recipe系统设计
│   ├── 004-recipe-architecture-refactor/ # Recipe架构重构
│   ├── 005-run-command-system/      # Run命令系统
│   ├── 006-init-command/            # Init命令
│   ├── 007-init-commands-setup/     # 命令资源安装
│   ├── 008-gui-app-mode/            # GUI应用模式
│   ├── 009-gui-design-redesign/     # GUI设计重构
│   └── 010-agent-session-monitor/   # Agent会话监控
│
├── docs/                            # 项目文档
│   ├── architecture.md              # 技术架构
│   ├── user-guide.md                # 使用指南
│   ├── development.md               # 开发指南
│   ├── roadmap.md                   # 项目进展
│   └── examples.md                  # 示例参考
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

## CDP命令目录结构

CDP功能按类型组织在 `src/frago/cdp/commands/` 目录下：

```
src/frago/cdp/commands/
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

所有CDP功能通过统一的CLI接口（`uv run frago <command>`）访问。

## 技术栈

- **AI编排**：Claude Code（任务分析、Recipe调度、工作流设计）
- **浏览器控制**：Chrome DevTools Protocol (CDP) - 原生WebSocket
- **多运行时支持**：Chrome JS、Python、Shell
- **任务管理**：Run命令系统（持久化上下文、JSONL日志）
- **会话监控**：watchdog文件系统监控 + JSONL增量解析
- **GUI框架**：pywebview（跨平台桌面应用）
- **脚本编排**：Python 3.9+（Recipe系统 + CDP工具层）

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

## 功能映射验证工具

功能映射工具用于验证所有CDP功能的完整性和一致性。

### 运行功能映射验证

```bash
# 生成控制台报告
uv run python -m frago.tools.function_mapping

# 生成详细HTML报告
uv run python -m frago.tools.function_mapping --format html --output function_mapping_report.html

# 生成JSON报告
uv run python -m frago.tools.function_mapping --format json --output function_mapping_report.json
```

### 查看功能覆盖率

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

## 注意事项

1. Chrome必须通过CDP启动器运行，保持9222端口可用
2. 录制前需要授权屏幕录制权限
3. 所有截图必须使用绝对路径
4. 视频长度必须大于等于音频总长度
5. 每个分镜完成后必须创建`.completed`标记文件

## Recipe开发规范

### Recipe文件结构

每个Recipe包含两个文件：
- `<recipe_name>.js`/`.py`/`.sh` - 执行脚本
- `<recipe_name>.md` - 元数据和文档（YAML frontmatter）

### 元数据规范

```yaml
---
name: recipe_name
type: atomic                    # atomic | workflow
runtime: chrome-js              # chrome-js | python | shell
version: "1.0"
description: "简短功能描述（<200字符）"
use_cases: ["场景1", "场景2"]
tags: ["标签1", "标签2"]
output_targets: [stdout, file]  # stdout | file | clipboard
inputs:
  param1:
    type: string
    description: "参数说明"
    required: true
outputs:
  result1:
    type: string
    description: "输出说明"
---
```

### Markdown文档结构

标准的6个章节：
1. 功能描述
2. 使用方法
3. 前置条件
4. 预期输出
5. 注意事项
6. 更新历史

### Recipe命名规范

描述性命名：`<平台>_<操作>_<对象>.js`

例如：
- `youtube_extract_video_transcript.js`
- `upwork_extract_job_details_as_markdown.js`
- `x_extract_tweet_with_comments.js`

## Recipe存储结构

- **代码与资源分离**：
  - `src/frago/recipes/` - Python引擎代码（不包含Recipe脚本）
  - `examples/atomic/chrome/` - 示例Recipe脚本 + 元数据文档
  - `~/.frago/recipes/` - 用户级Recipe（待实现）
  - `.frago/recipes/` - 项目级Recipe（待实现）

- **查找优先级**：项目级 > 用户级 > 示例级

## 测试

```bash
# 运行所有测试
uv run pytest

# 运行特定测试
uv run pytest tests/integration/recipe/

# 测试Recipe执行
uv run pytest tests/integration/recipe/test_recipe_execution.py
```

## 贡献指南

1. Fork项目
2. 创建特性分支（`git checkout -b feature/AmazingFeature`）
3. 提交更改（`git commit -m 'Add some AmazingFeature'`）
4. 推送到分支（`git push origin feature/AmazingFeature`）
5. 开启Pull Request

## 代码审查清单

- [ ] 所有CDP命令都有对应的CLI接口
- [ ] Recipe元数据完整且符合规范
- [ ] 新增功能有测试覆盖
- [ ] 代码符合项目规范
- [ ] 文档已更新
