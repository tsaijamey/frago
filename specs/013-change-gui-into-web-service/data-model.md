# Data Model: Web Service Based GUI

**Date**: 2025-12-23
**Feature**: 013-change-gui-into-web-service

## Overview

This document defines the data models for the web service API. Most entities already exist in the codebase (`src/frago/gui/models.py`) and will be reused. This document focuses on the new entities needed for the HTTP/WebSocket transport layer.

## Existing Entities (Reused)

These entities already exist and will be serialized to JSON for the REST API:

### RecipeItem

| Field | Type | Description |
|-------|------|-------------|
| name | string | Recipe name (unique identifier) |
| description | string? | Human-readable description |
| category | string | "atomic" or "workflow" |
| icon | string? | Emoji or icon identifier |
| tags | string[] | Searchable tags |
| path | string? | File path |
| source | string? | Source file content |
| runtime | string? | Execution runtime |

### TaskItem

| Field | Type | Description |
|-------|------|-------------|
| id | string | Unique task identifier |
| title | string | Task title/description |
| status | GUITaskStatus | running/completed/error/cancelled |
| project_path | string? | Associated project path |
| agent_type | string | Agent type (claude/frago) |
| started_at | datetime | Task start time (ISO format) |
| completed_at | datetime? | Task completion time |
| duration_ms | int? | Duration in milliseconds |

### TaskDetail

| Field | Type | Description |
|-------|------|-------------|
| id | string | Task identifier |
| title | string | Task title |
| status | GUITaskStatus | Current status |
| steps | TaskStep[] | Execution steps |
| summary | TaskSummary? | Summary after completion |

### TaskStep

| Field | Type | Description |
|-------|------|-------------|
| timestamp | datetime | Step timestamp (ISO format) |
| type | string | Step type (user/assistant/tool) |
| content | string | Step content |
| tool_name | string? | Tool name if tool call |
| tool_result | string? | Tool result |

### UserConfig

| Field | Type | Description |
|-------|------|-------------|
| theme | string | "dark" or "light" |
| font_size | int | Font size (10-24) |
| show_system_status | bool | Show system status bar |
| confirm_on_exit | bool | Confirm before exit |
| auto_scroll_output | bool | Auto-scroll output |
| max_history_items | int | Max history items (10-1000) |
| shortcuts | object | Keyboard shortcuts |

## New Entities

### WebSocketMessage

Real-time message sent over WebSocket connection.

| Field | Type | Description |
|-------|------|-------------|
| type | string | Message type |
| payload | object | Message payload (varies by type) |
| timestamp | datetime | Message timestamp (ISO format) |

**Message Types**:

| Type | Payload | Description |
|------|---------|-------------|
| `session_sync` | `{ tasks: TaskItem[] }` | Session list updated |
| `task_started` | `{ task: TaskItem }` | New task started |
| `task_updated` | `{ task_id: string, status: string, step?: TaskStep }` | Task progress update |
| `task_completed` | `{ task_id: string, status: string, summary?: TaskSummary }` | Task completed |
| `connection` | `{ status: string }` | Connection status change |

### SystemStatus

System health and resource status.

| Field | Type | Description |
|-------|------|-------------|
| chrome_available | bool | Chrome browser available |
| chrome_connected | bool | CDP connection active |
| projects_count | int | Number of monitored projects |
| tasks_running | int | Currently running tasks |

### ServerInfo

Web server information.

| Field | Type | Description |
|-------|------|-------------|
| version | string | Frago version |
| host | string | Server host (127.0.0.1) |
| port | int | Server port |
| started_at | datetime | Server start time |

## State Transitions

### TaskStatus State Machine

```
            ┌─────────────┐
            │   (start)   │
            └──────┬──────┘
                   │
                   ▼
            ┌─────────────┐
            │   RUNNING   │
            └──────┬──────┘
                   │
     ┌─────────────┼─────────────┐
     │             │             │
     ▼             ▼             ▼
┌─────────┐  ┌─────────┐  ┌─────────┐
│COMPLETED│  │  ERROR  │  │CANCELLED│
└─────────┘  └─────────┘  └─────────┘
```

### Connection Lifecycle

```
Browser connects → WebSocket handshake → Connected
                                              │
                                              ▼
                              ┌───────────────────────────┐
                              │  Receive real-time events │◄──┐
                              └─────────────┬─────────────┘   │
                                            │                 │
                              ┌─────────────▼─────────────┐   │
                              │ Connection lost/timeout   │   │
                              └─────────────┬─────────────┘   │
                                            │                 │
                              ┌─────────────▼─────────────┐   │
                              │   Auto-reconnect (3s)     │───┘
                              └───────────────────────────┘
```

## Validation Rules

### RecipeItem

- `name`: Required, non-empty string
- `category`: Must be "atomic" or "workflow"

### UserConfig

- `theme`: Must be "dark" or "light"
- `font_size`: Must be 10-24
- `max_history_items`: Must be 10-1000

### API Request Parameters

- `port`: Must be 1024-65535
- `task_id`: Must be valid UUID format
- `recipe_name`: Must exist in recipe list
