# Claude Code Session File Format Specification

> **Purpose**: Track Claude Code session message format changes for rapid iteration updates.
> **Last Updated**: 2025-12-26
> **Claude Code Version Tested**: 2.0.76+

## Overview

Claude Code stores conversation sessions as JSONL files in:
```
~/.claude/projects/{encoded_project_path}/{session_id}.jsonl
```

Where:
- `encoded_project_path`: Project path with `/` replaced by `-` (e.g., `/Users/chagee/Repos/frago` → `-Users-chagee-Repos-frago`)
- `session_id`: UUID v4 format (e.g., `6c75e29d-01ec-4987-acf7-096af67c8031`)

---

## Record Types

### 1. `queue-operation` (Metadata - Skipped)

Queue management metadata, not part of conversation content.

```json
{
  "type": "queue-operation",
  "operation": "dequeue",
  "timestamp": "2025-12-24T06:00:57.005Z",
  "sessionId": "6c75e29d-01ec-4987-acf7-096af67c8031"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | ✅ | Always `"queue-operation"` |
| `operation` | string | ✅ | Operation type: `"dequeue"`, `"enqueue"` |
| `timestamp` | ISO8601 | ✅ | Operation timestamp |
| `sessionId` | UUID | ✅ | Session identifier |

**frago Handling**: Skipped by parser.

---

### 2. `user` (User Message / Tool Result)

User input or tool execution results.

```json
{
  "parentUuid": "44a06ba8-bc55-491d-ab7e-f1015608a0bd",
  "isSidechain": false,
  "userType": "external",
  "cwd": "/Users/chagee/Repos/frago",
  "sessionId": "6c75e29d-01ec-4987-acf7-096af67c8031",
  "version": "2.0.76",
  "gitBranch": "main",
  "slug": "gleaming-jumping-key",
  "type": "user",
  "message": {
    "role": "user",
    "content": "..." | [...]
  },
  "uuid": "d4e8ac2e-61e4-4fcb-8674-5e36e2349cfb",
  "timestamp": "2025-12-24T06:01:50.097Z",
  "toolUseResult": {
    "stdout": "...",
    "stderr": "...",
    "interrupted": false,
    "isImage": false
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | ✅ | Always `"user"` |
| `uuid` | UUID | ✅ | Record unique identifier |
| `sessionId` | UUID | ✅ | Session identifier |
| `timestamp` | ISO8601 | ✅ | Record timestamp |
| `parentUuid` | UUID | ❌ | Parent message UUID (conversation threading) |
| `isSidechain` | boolean | ✅ | Whether this is an agent subthread |
| `userType` | string | ✅ | User type: `"external"` |
| `cwd` | string | ✅ | Current working directory |
| `version` | string | ✅ | Claude Code version |
| `gitBranch` | string | ❌ | Current git branch |
| `slug` | string | ❌ | Session slug (human-readable name) |
| `message` | object | ✅ | Message content container |
| `message.role` | string | ✅ | Always `"user"` |
| `message.content` | string\|array | ✅ | Message content (see Content Blocks) |
| `toolUseResult` | object\|string | ❌ | Tool result metadata (object) or error string |
| `isMeta` | boolean | ❌ | Whether this is a meta message (skill expansion) |
| `sourceToolUseID` | string | ❌ | Source tool_use ID for meta messages |

**Content Variants**:

1. **Plain Text Message**:
   ```json
   { "role": "user", "content": "Hello, help me with..." }
   ```

2. **Tool Result**:
   ```json
   {
     "role": "user",
     "content": [{
       "type": "tool_result",
       "tool_use_id": "toolu_01KSVptpVLQCxH4b5AbX4qmt",
       "content": "Command output here...",
       "is_error": false
     }]
   }
   ```

**frago Handling**:
- Plain text → `StepType.USER_MESSAGE`
- Tool result → `StepType.TOOL_RESULT`

---

### 3. `assistant` (Model Response)

Claude model responses, may contain text and/or tool calls.

```json
{
  "parentUuid": "2929705d-301e-4738-8dcb-59ce27ea8b8d",
  "isSidechain": false,
  "userType": "external",
  "cwd": "/Users/chagee/Repos/frago",
  "sessionId": "6c75e29d-01ec-4987-acf7-096af67c8031",
  "version": "2.0.76",
  "gitBranch": "main",
  "slug": "gleaming-jumping-key",
  "message": {
    "model": "claude-opus-4-5-20251101",
    "id": "msg_016LbwtJ1q7MzjSDWGyCk3po",
    "type": "message",
    "role": "assistant",
    "content": [...],
    "stop_reason": null,
    "stop_sequence": null,
    "usage": {
      "input_tokens": 2,
      "cache_creation_input_tokens": 38543,
      "cache_read_input_tokens": 0,
      "cache_creation": {
        "ephemeral_5m_input_tokens": 38543,
        "ephemeral_1h_input_tokens": 0
      },
      "output_tokens": 256,
      "service_tier": "standard"
    }
  },
  "requestId": "req_011CWR17SrQKmvuFrMEWhaoM",
  "type": "assistant",
  "uuid": "a682167b-d530-43f1-a63b-a5566a35e40d",
  "timestamp": "2025-12-24T06:01:06.384Z"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | ✅ | Always `"assistant"` |
| `uuid` | UUID | ✅ | Record unique identifier |
| `sessionId` | UUID | ✅ | Session identifier |
| `timestamp` | ISO8601 | ✅ | Record timestamp |
| `parentUuid` | UUID | ❌ | Parent message UUID |
| `isSidechain` | boolean | ✅ | Whether this is an agent subthread |
| `requestId` | string | ❌ | API request identifier (may be absent in streaming) |
| `message` | object | ✅ | API response container |
| `message.model` | string | ✅ | Model identifier |
| `message.id` | string | ✅ | Message ID from API |
| `message.type` | string | ✅ | Always `"message"` |
| `message.role` | string | ✅ | Always `"assistant"` |
| `message.content` | array | ✅ | Content blocks array |
| `message.stop_reason` | string\|null | ✅ | Stop reason: `"end_turn"`, `"tool_use"`, null |
| `message.stop_sequence` | string\|null | ✅ | Stop sequence if triggered |
| `message.usage` | object | ✅ | Token usage statistics |

**Content Block Types**:

1. **Text Block**:
   ```json
   { "type": "text", "text": "I'll help you with..." }
   ```

2. **Tool Use Block**:
   ```json
   {
     "type": "tool_use",
     "id": "toolu_01KSVptpVLQCxH4b5AbX4qmt",
     "name": "Bash",
     "input": {
       "command": "ls -la",
       "description": "List files"
     }
   }
   ```

**frago Handling**:
- Text only → `StepType.ASSISTANT_MESSAGE`
- Contains tool_use → `StepType.TOOL_CALL` + `ToolCallRecord`

---

### 4. `system` (Metadata - Skipped)

System events such as errors, retries, and internal state changes.

```json
{
  "type": "system",
  "uuid": "...",
  "sessionId": "...",
  "timestamp": "2025-12-24T06:01:50.097Z",
  "subtype": "error",
  "level": "error",
  "content": "Error message...",
  "error": { ... },
  "cause": "...",
  "retryAttempt": 1,
  "maxRetries": 3,
  "retryInMs": 1000
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | ✅ | Always `"system"` |
| `uuid` | UUID | ❌ | Record identifier |
| `sessionId` | UUID | ❌ | Session identifier |
| `timestamp` | ISO8601 | ❌ | Record timestamp |
| `subtype` | string | ❌ | System event subtype: `"error"`, etc. |
| `level` | string | ❌ | Log level: `"error"`, `"warn"`, `"info"` |
| `content` | string | ❌ | Event content/message |
| `error` | object | ❌ | Error details |
| `cause` | string | ❌ | Error cause |
| `retryAttempt` | int | ❌ | Current retry attempt |
| `maxRetries` | int | ❌ | Maximum retries allowed |
| `retryInMs` | int | ❌ | Retry delay in milliseconds |
| `compactMetadata` | object | ❌ | Compact summary metadata |
| `logicalParentUuid` | UUID | ❌ | Logical parent for threading |

**frago Handling**: Skipped by parser.

---

### 5. `summary` (Metadata - Skipped)

Session summary generated at end.

```json
{
  "type": "summary",
  "sessionId": "...",
  "leafUuid": "...",
  "summary": "Session summary text..."
}
```

**frago Handling**: Skipped by parser, used for status inference.

---

### 6. `file-history-snapshot` (Metadata - Skipped)

File system state snapshot for undo/redo functionality.

```json
{
  "type": "file-history-snapshot",
  "sessionId": "...",
  "messageId": "...",
  "snapshot": { ... },
  "isSnapshotUpdate": false
}
```

**frago Handling**: Skipped by parser.

---

## Content Block Reference

### Text Block
```json
{
  "type": "text",
  "text": "Content string here..."
}
```

### Tool Use Block
```json
{
  "type": "tool_use",
  "id": "toolu_xxxxx",
  "name": "ToolName",
  "input": { ... }
}
```

**Known Tool Types**:

| Tool Name | Input Parameters | Description | Since Version |
|-----------|------------------|-------------|---------------|
| `Bash` | `command`, `description`, `timeout?`, `run_in_background?` | Execute shell commands | - |
| `Read` | `file_path`, `offset?`, `limit?` | Read file contents | - |
| `Write` | `file_path`, `content` | Write file contents | - |
| `Edit` | `file_path`, `old_string`, `new_string`, `replace_all?` | Edit file with string replacement | - |
| `Glob` | `pattern`, `path?` | Find files by glob pattern | - |
| `Grep` | `pattern`, `path?`, `glob?`, `type?`, `output_mode?` | Search file contents | - |
| `Task` | `prompt`, `description`, `subagent_type`, `model?`, `run_in_background?`, `resume?` | Launch subagent for complex tasks | - |
| `TaskOutput` | `task_id`, `block?`, `timeout?` | Get output from background task | - |
| `WebFetch` | `url`, `prompt` | Fetch and analyze web content | - |
| `WebSearch` | `query`, `allowed_domains?`, `blocked_domains?` | Search the web | - |
| `TodoWrite` | `todos` | Manage task list | - |
| `AskUserQuestion` | `questions` | Ask user for clarification | - |
| `Skill` | `skill`, `args?` | Execute a skill | - |
| `BashOutput` | `bash_id` | Get output from background bash command | 2.0.55 |
| `SlashCommand` | `command` | Execute slash command (deprecated, use Skill) | 2.0.58 |

### Tool Result Block
```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_xxxxx",
  "content": "Result string or...",
  "is_error": false
}
```

**Tool Result Content Variants**:
- String: Direct output text
- Array of blocks: Complex results with text/images

### Image Block
```json
{
  "type": "image",
  "source": {
    "type": "base64",
    "media_type": "image/png",
    "data": "base64_encoded_data..."
  }
}
```

### Thinking Block (Extended Thinking)
```json
{
  "type": "thinking",
  "thinking": "Internal reasoning content..."
}
```

**Note**: Thinking blocks appear when extended thinking is enabled.

---

## Usage Statistics Object

```json
{
  "input_tokens": 2,
  "cache_creation_input_tokens": 38543,
  "cache_read_input_tokens": 0,
  "cache_creation": {
    "ephemeral_5m_input_tokens": 38543,
    "ephemeral_1h_input_tokens": 0
  },
  "output_tokens": 256,
  "service_tier": "standard"
}
```

| Field | Description |
|-------|-------------|
| `input_tokens` | Non-cached input tokens |
| `cache_creation_input_tokens` | Tokens written to cache |
| `cache_read_input_tokens` | Tokens read from cache |
| `cache_creation.ephemeral_5m_input_tokens` | 5-minute ephemeral cache |
| `cache_creation.ephemeral_1h_input_tokens` | 1-hour ephemeral cache |
| `output_tokens` | Generated output tokens |
| `service_tier` | Service tier: `"standard"` |

**frago Handling**: Currently discarded (not stored).

---

## Special Message Patterns

### Skill Expansion (Meta Message)

When a skill is invoked, Claude Code inserts an expanded prompt:

```json
{
  "type": "user",
  "isMeta": true,
  "sourceToolUseID": "toolu_01KSVptpVLQCxH4b5AbX4qmt",
  "message": {
    "role": "user",
    "content": [{ "type": "text", "text": "# /frago.run - Research Explorer\n..." }]
  }
}
```

### Agent Subthread (Sidechain)

Agent tool spawns child sessions marked with:
```json
{
  "isSidechain": true,
  "agentId": "a59831a"
}
```

**frago Handling**: Sidechain sessions are skipped during sync.

---

## frago Implementation Reference

### Data Flow

```
Claude JSONL → Parser → SessionStep → Storage → GUI Models
```

### Source Files

| Component | File Path | Purpose |
|-----------|-----------|---------|
| Record Parser | `src/frago/session/parser.py` | Parse JSONL records, extract content |
| Data Models | `src/frago/session/models.py` | SessionStep, ToolCallRecord, etc. |
| Storage | `src/frago/session/storage.py` | Read/write steps.jsonl, metadata.json |
| Sync Logic | `src/frago/session/sync.py` | Sync from Claude → frago format |
| GUI Models | `src/frago/gui/models.py` | TaskItem, TaskStep, TaskDetail |
| API Adapter | `src/frago/server/adapter.py` | HTTP API wrapper |

### Data Transformation

| Claude Field | frago Field | Notes |
|--------------|-------------|-------|
| `sessionId` | `MonitoredSession.session_id` | Direct mapping |
| `uuid` | `SessionStep.raw_uuid` | Preserved for reference |
| `parentUuid` | `SessionStep.parent_uuid` | Preserved for threading |
| `timestamp` | `SessionStep.timestamp` | ISO8601 → datetime |
| `type: user` (no tool_result) | `StepType.USER_MESSAGE` | |
| `type: user` (with tool_result) | `StepType.TOOL_RESULT` | |
| `type: assistant` (no tool_use) | `StepType.ASSISTANT_MESSAGE` | |
| `type: assistant` (with tool_use) | `StepType.TOOL_CALL` | |
| `message.content` (text) | `SessionStep.content_summary` | Truncated to 200 chars |
| `message.model` | — | Discarded |
| `message.usage` | — | Discarded |
| `requestId` | — | Discarded |
| `cwd`, `gitBranch`, `version` | — | Discarded |

### Filtering Rules

**Parser Level** (`parser.py:172-175`):
```python
METADATA_TYPES = {"file-history-snapshot", "queue-operation", "summary"}
```

**Sync Level** (`sync.py`):
- Skip empty files
- Skip non-UUID filenames (e.g., `agent-*.jsonl`)
- Skip records with `isSidechain: true`

**GUI Level** (`models.py:587-649`):
- Always show: `status == RUNNING`
- Always show: `step_count >= 10`
- Hide: `step_count < 5 && status == COMPLETED`
- Hide: `step_count < 10 && no assistant_message`

---

## Schema Validation Script

Use `check_claude_session_format.py` (in this directory) to validate session files against known schema:

```bash
# Check single file
uv run python project_management/claude_session_format/check_claude_session_format.py /path/to/session.jsonl

# Check all sessions in a project
uv run python project_management/claude_session_format/check_claude_session_format.py ~/.claude/projects/-Users-chagee-Repos-frago/
```

See script for detailed output interpretation.

---

## Changelog Tracking

When Claude Code updates, check for:

1. **New record types** - Run schema check, look for `UNKNOWN_TYPE` warnings
2. **New fields** - Run schema check, look for `NEW_FIELD` warnings
3. **Changed field types** - Run schema check, look for `TYPE_MISMATCH` warnings
4. **Removed fields** - Run schema check, look for `MISSING_FIELD` warnings

Update this document and relevant frago code when changes are detected.
