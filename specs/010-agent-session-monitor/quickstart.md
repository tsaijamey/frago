# 快速开始: Agent 会话监控

**特性分支**: `010-agent-session-monitor`

## 概述

本特性为 `frago agent` 命令添加实时会话监控能力，通过解析 Claude Code 的会话数据文件，提供结构化的执行状态展示。

## 核心功能

1. **实时状态展示** - 在终端显示 Agent 执行进度、工具调用等信息
2. **会话数据持久化** - 将解析后的数据保存到 `~/.frago/sessions/`
3. **多 Agent 支持** - 预留扩展性，支持未来接入其他 Agent 工具

## 使用方式

### 基本用法

```bash
# 正常执行，自动显示实时状态
frago agent "帮我搜索 Python 3.12 的新特性"
```

输出示例：
```
[10:30:05] 🚀 会话已启动 (session: 48c10a46...)
[10:30:10] 📝 用户: 帮我搜索 Python 3.12 的新特性
[10:30:15] 🔧 工具调用: WebSearch
[10:30:18] ✅ WebSearch 完成 (1.2s)
[10:30:25] 🤖 助手: Python 3.12 主要新特性包括...
[10:31:00] ✨ 会话完成 (耗时: 55s, 工具调用: 3次)
```

### 静默模式

```bash
# 不显示状态，只显示原始输出
frago agent "执行任务" --quiet
```

### 查看历史会话

```bash
# 列出最近的会话
frago session list

# 查看特定会话详情
frago session show 48c10a46

# 显示步骤历史
frago session show 48c10a46 --steps
```

### 实时监控

```bash
# 在另一个终端监控正在执行的会话
frago session watch
```

## 数据存储

会话数据保存在：
```
~/.frago/sessions/claude/{session_id}/
├── metadata.json    # 会话元数据
├── steps.jsonl      # 步骤记录
└── summary.json     # 会话摘要
```

## 技术实现

1. 监听 `~/.claude/projects/` 目录的文件变化
2. 增量解析 JSONL 会话文件
3. 提取消息、工具调用等关键信息
4. 格式化输出到终端 + 持久化到本地

## 依赖

- `watchdog` - 文件系统监听
- 现有 Frago 依赖（click, pydantic 等）
