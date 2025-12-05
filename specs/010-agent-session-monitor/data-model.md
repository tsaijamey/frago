# 数据模型: Agent 会话监控

**特性分支**: `010-agent-session-monitor`
**日期**: 2025-12-05

## 1. 核心实体

### 1.1 MonitoredSession（监控会话）

表示一个被 Frago 监控的 Agent 执行会话。

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| `session_id` | UUID | 是 | Claude Code 会话 ID |
| `agent_type` | string | 是 | Agent 类型标识（如 `claude`） |
| `project_path` | string | 是 | 项目绝对路径 |
| `source_file` | string | 是 | 原始会话文件路径 |
| `started_at` | datetime | 是 | 监控开始时间 |
| `ended_at` | datetime | 否 | 监控结束时间 |
| `status` | enum | 是 | `running` \| `completed` \| `error` |
| `step_count` | int | 是 | 已记录步骤数 |
| `tool_call_count` | int | 是 | 工具调用次数 |
| `last_activity` | datetime | 是 | 最后活动时间 |

### 1.2 SessionStep（会话步骤）

表示会话中的一个执行步骤。

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| `step_id` | int | 是 | 步骤序号（从 1 开始） |
| `session_id` | UUID | 是 | 所属会话 ID |
| `type` | enum | 是 | `user_message` \| `assistant_message` \| `tool_call` \| `tool_result` \| `system_event` |
| `timestamp` | datetime | 是 | 步骤时间戳 |
| `content_summary` | string | 是 | 内容摘要（截断至 200 字符） |
| `raw_uuid` | UUID | 是 | 原始记录的 uuid |
| `parent_uuid` | UUID | 否 | 父消息的 uuid |

### 1.3 ToolCallRecord（工具调用记录）

表示一次工具调用的详细信息。

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| `tool_call_id` | string | 是 | 工具调用 ID（来自 Claude） |
| `session_id` | UUID | 是 | 所属会话 ID |
| `step_id` | int | 是 | 关联的步骤序号 |
| `tool_name` | string | 是 | 工具名称 |
| `input_summary` | string | 是 | 输入参数摘要 |
| `called_at` | datetime | 是 | 调用时间 |
| `result_summary` | string | 否 | 执行结果摘要 |
| `completed_at` | datetime | 否 | 完成时间 |
| `duration_ms` | int | 否 | 执行耗时（毫秒） |
| `status` | enum | 是 | `pending` \| `success` \| `error` |

### 1.4 SessionSummary（会话摘要）

会话结束后的统计摘要。

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| `session_id` | UUID | 是 | 会话 ID |
| `total_duration_ms` | int | 是 | 总耗时（毫秒） |
| `user_message_count` | int | 是 | 用户消息数 |
| `assistant_message_count` | int | 是 | 助手消息数 |
| `tool_call_count` | int | 是 | 工具调用总数 |
| `tool_success_count` | int | 是 | 成功的工具调用数 |
| `tool_error_count` | int | 是 | 失败的工具调用数 |
| `most_used_tools` | list | 是 | 使用最多的工具（前 5） |
| `model` | string | 否 | 使用的模型 |
| `final_status` | enum | 是 | `completed` \| `error` \| `cancelled` |

---

## 2. 枚举类型

### 2.1 AgentType

```
claude      # Claude Code
cursor      # Cursor（预留）
cline       # Cline（预留）
```

### 2.2 SessionStatus

```
running     # 正在执行
completed   # 正常完成
error       # 异常终止
cancelled   # 用户取消
```

### 2.3 StepType

```
user_message       # 用户输入消息
assistant_message  # 助手回复消息
tool_call          # 工具调用请求
tool_result        # 工具执行结果
system_event       # 系统事件（错误、重试等）
```

### 2.4 ToolCallStatus

```
pending    # 等待执行
success    # 执行成功
error      # 执行失败
```

---

## 3. 实体关系

```
MonitoredSession (1) ────< SessionStep (N)
       │
       └────< ToolCallRecord (N)
       │
       └──── SessionSummary (1)
```

- 一个 `MonitoredSession` 包含多个 `SessionStep`
- 一个 `MonitoredSession` 包含多个 `ToolCallRecord`
- 一个 `MonitoredSession` 对应一个 `SessionSummary`（会话结束后生成）

---

## 4. 存储格式

### 4.1 metadata.json

```json
{
  "session_id": "48c10a46-9f16-4d56-8c65-26de8a5af65c",
  "agent_type": "claude",
  "project_path": "/home/yammi/repos/Frago",
  "source_file": "~/.claude/projects/-home-yammi-repos-Frago/48c10a46-9f16-4d56-8c65-26de8a5af65c.jsonl",
  "started_at": "2025-12-05T10:30:00Z",
  "ended_at": null,
  "status": "running",
  "step_count": 15,
  "tool_call_count": 8,
  "last_activity": "2025-12-05T10:35:20Z"
}
```

### 4.2 steps.jsonl

每行一个 `SessionStep` 记录：

```jsonl
{"step_id": 1, "session_id": "48c10a46-...", "type": "user_message", "timestamp": "2025-12-05T10:30:00Z", "content_summary": "搜索某个信息", "raw_uuid": "abc...", "parent_uuid": null}
{"step_id": 2, "session_id": "48c10a46-...", "type": "assistant_message", "timestamp": "2025-12-05T10:30:05Z", "content_summary": "我来帮你搜索...", "raw_uuid": "def...", "parent_uuid": "abc..."}
{"step_id": 3, "session_id": "48c10a46-...", "type": "tool_call", "timestamp": "2025-12-05T10:30:06Z", "content_summary": "[WebSearch] query=...", "raw_uuid": "ghi...", "parent_uuid": "def..."}
```

### 4.3 summary.json

```json
{
  "session_id": "48c10a46-9f16-4d56-8c65-26de8a5af65c",
  "total_duration_ms": 320000,
  "user_message_count": 3,
  "assistant_message_count": 12,
  "tool_call_count": 8,
  "tool_success_count": 7,
  "tool_error_count": 1,
  "most_used_tools": ["Read", "Bash", "Edit", "Grep", "Write"],
  "model": "claude-opus-4-5-20251101",
  "final_status": "completed"
}
```

---

## 5. 验证规则

### 5.1 MonitoredSession

- `session_id` 必须是有效的 UUID 格式
- `project_path` 必须是存在的目录
- `started_at` 不能晚于 `ended_at`
- `step_count` 和 `tool_call_count` 必须 >= 0

### 5.2 SessionStep

- `step_id` 在同一会话内必须唯一且递增
- `timestamp` 必须在会话的 `started_at` 和当前时间之间
- `content_summary` 长度不超过 200 字符

### 5.3 ToolCallRecord

- `duration_ms` 仅在 `completed_at` 存在时有效
- `result_summary` 仅在 `status` 为 `success` 或 `error` 时有效
