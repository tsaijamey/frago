# AuViMa Development Guidelines

Auto-generated from all feature plans. Last updated: 2025-11-15

## Active Technologies
- Python 3.9+（已有pyproject.toml要求 >=3.9） (003-skill-automation)
- 文件系统存储 (003-skill-automation)

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
- 003-skill-automation: Added Python 3.9+（已有pyproject.toml要求 >=3.9）

- 001-standardize-cdp-scripts: Added Bash/Shell Script (POSIX兼容) + websocat工具，Chrome DevTools Protocol

<!-- MANUAL ADDITIONS START -->

## 核心使用方式

### Chrome CDP操作（Python CLI）

**正确方式**: 使用 `uv run auvima <command>`

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

**不要使用**: ~~`./scripts/share/cdp_*.sh`~~ （已废弃删除）

### Recipes（配方）系统

从003-skill-automation开始，AuViMa支持将重复性网页操作固化为可复用的JavaScript配方。

#### 管理配方：`/auvima.recipe` 命令

**创建新配方**:
```
/auvima.recipe create "在YouTube视频页面提取完整字幕内容"
```
Claude Code会交互式引导你探索页面，自动生成配方脚本和知识文档。

**更新现有配方**:
```
/auvima.recipe update youtube_extract_subtitles "YouTube改版后字幕按钮失效了"
```

**列出所有配方**:
```
/auvima.recipe list
```

#### 使用配方

**配方位置**: `src/auvima/recipes/`

**命名约定**: `<平台>_<功能描述>.js`（例如 `youtube_extract_subtitles.js`）

**执行方式**:
```bash
uv run auvima exec-js recipes/<配方名>.js
```

**配方结构**: 扁平目录，无子文件夹，所有配方通过描述性文件名区分用途

**知识文档**: 每个配方脚本(.js)都有对应的Markdown文档(.md)，包含6个标准章节：
1. 功能描述
2. 使用方法
3. 前置条件
4. 预期输出
5. 注意事项
6. 更新历史

**版本管理**: 覆盖原文件，历史记录在.md的"更新历史"章节

### 项目结构简化

```
src/auvima/
├── cdp/                  # CDP核心模块
│   └── commands/         # CDP命令实现
├── cli/                  # 命令行接口
├── recipes/              # 可复用操作配方（003新增）
└── tools/                # 辅助工具

.claude/commands/         # Claude Code命令配置
projects/                 # 视频项目工作目录
```

<!-- MANUAL ADDITIONS END -->
