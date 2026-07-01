---
name: transcript_completion
type: atomic
runtime: python
version: "1.0.0"
description: "解析 Claude Code session JSONL，用权威 stop_reason 判定最新一轮是否答完并抽取该轮 assistant 最终文本。query 一次性查询 / watch 长驻事件式上报，watch 形态可由 daemon supervisor 托管"
use_cases:
  - "query：给定 session_id+cwd 或 path，同步判定 transcript 尾部最新一轮是否完成 + 取最终文本（供 tmux 完成判定采信权威信号而非读屏）"
  - "watch：watchdog 盯单个 jsonl，检测到一轮完成翻转时向 stdout 打一行 turn_complete 事件，供 daemon supervisor 流式消费"
  - "冻结恢复：拿到 session id → locate_transcript 定位文件 → 解析尾部"
output_targets:
  - stdout
tags:
  - transcript
  - jsonl
  - completion-detection
  - claude-session
  - tmux
  - daemon
  - watch
daemon: true
restart_policy: on-failure
inputs:
  session_id:
    type: string
    required: false
    description: "目标 Claude session id（确定性定位：~/.claude/projects/<encode(cwd)>/<session_id>.jsonl）"
  cwd:
    type: string
    required: false
    description: "目标会话的工作目录，配合 session_id 算编码路径；缺省时回退扫描所有 project 目录"
  path:
    type: string
    required: false
    description: "或直接给 transcript jsonl 的绝对路径（优先级高于 session_id）"
  mode:
    type: string
    required: false
    description: "query=一次性查询（默认） | watch=watchdog 长驻事件式上报"
outputs:
  type:
    type: string
    description: "事件类型：completion（query 结果）| turn_complete / turn_running（watch 事件）| error"
  done:
    type: boolean
    description: "最新一轮是否真答完（stop_reason ∈ {end_turn, stop_sequence, max_tokens}）"
  stop_reason:
    type: string
    description: "终结记录的 stop_reason（done 的依据）"
  final_text:
    type: string
    description: "该轮 assistant 最终文本（含 JSON 决策原文）"
  pending_tool_use:
    type: boolean
    description: "末尾是否还挂着 tool_use（stop_reason==tool_use）"
  session_id:
    type: string
    description: "关联的 session id"
  source_path:
    type: string
    description: "解析的 transcript 文件路径"
dependencies: []
flow:
  - step: 1
    action: "resolve_target"
    description: "由 path 或 (session_id + cwd) 经 locate_transcript 定位 jsonl 文件"
  - step: 2
    action: "evaluate_or_watch"
    description: "query：evaluate_file 判尾部一轮 + 抽文本，打一行 JSON；watch：SessionFileHandler 盯文件，done 翻转时打 turn_complete 事件行"
---

# transcript_completion

把 spec `20260624-transcript-completion-recipe` 的解析核心（`frago.session.transcript_completion`）封装成配方。完成判定的权威信号是 Claude Code 写进 session JSONL 的 `message.stop_reason`，不读屏。配方复用 `claude_sessions` / `monitor` / `parser` 的既有解析，自身不重写 JSONL 解析。

## 两种形态

- `mode=query`（默认）：被调用即解析当前 transcript 尾部，向 stdout 打一行结构化 JSON（`type=completion`），供 tmux 完成判定同步采信。
- `mode=watch`：用 watchdog 盯单个 jsonl，检测到「最新一轮是否答完」翻转为 True 时打一行 `type=turn_complete` 事件；进程常驻不退出，可声明 `daemon: true` 由工程一的 RecipeSupervisor 托管、崩溃自愈。

## 调用示例

```
# 一次性查询（直接给文件路径）
frago recipe run transcript_completion --params '{"path":"~/.claude/projects/-Users-frago-Repos-frago/<sid>.jsonl","mode":"query"}'

# 一次性查询（给 session_id + cwd，确定性定位）
frago recipe run transcript_completion --params '{"session_id":"<sid>","cwd":"/Users/frago/Repos/frago","mode":"query"}'

# 长驻 watch（供 supervisor 托管；会持续输出事件行、不退出）
frago recipe run transcript_completion --params '{"path":"<jsonl>","mode":"watch"}'
```

## 运行环境

配方导入 `frago` 包复用解析核心，需在已安装 frago 的环境（frago venv）下运行——这正是 `frago recipe run` 与 server 派生子进程的运行环境，因此脚本不带 PEP 723 隔离声明（带了会让 uv 用隔离环境、frago 不可导入）。`watch` 形态依赖 `watchdog`（frago 既有依赖）。
