# GUI API Contract: Frago GUI Tasks Redesign

**Feature Branch**: `011-gui-tasks-redesign`
**Date**: 2025-12-08
**API 类型**: pywebview JavaScript API（`window.pywebview.api.*`）

---

## API 概览

| 方法 | 用途 | 状态 |
|------|------|------|
| `get_tasks(limit, offset)` | 获取任务列表 | **新增** |
| `get_task_detail(session_id)` | 获取任务详情 | **新增** |
| `get_task_steps(session_id, limit, offset)` | 分页获取任务步骤 | **新增** |
| `subscribe_task_updates(session_id)` | 订阅任务更新 | **新增** |
| `unsubscribe_task_updates(session_id)` | 取消订阅 | **新增** |
| `get_config()` | 获取用户配置 | 保留 |
| `update_config(config)` | 更新用户配置 | 保留 |
| `get_system_status()` | 获取系统状态 | 保留 |

---

## 1. 任务列表 API

### `get_tasks(limit?, offset?)`

获取任务列表，按最后活动时间倒序排列。

**请求参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|-------|------|
| `limit` | `int` | 50 | 每页数量（1-100） |
| `offset` | `int` | 0 | 偏移量 |

**返回类型**：`TaskListResponse`

```typescript
interface TaskListResponse {
  tasks: TaskItem[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}

interface TaskItem {
  session_id: string;
  name: string;
  status: 'running' | 'completed' | 'error' | 'cancelled';
  started_at: string;  // ISO 8601
  ended_at: string | null;
  duration_ms: number;
  step_count: number;
  tool_call_count: number;
  last_activity: string;
  project_path: string;
}
```

**示例调用**：

```javascript
// JavaScript (前端)
const response = await pywebview.api.get_tasks(50, 0);
console.log(response.tasks);
console.log(`Total: ${response.total}, Has more: ${response.has_more}`);
```

**示例响应**：

```json
{
  "tasks": [
    {
      "session_id": "abc12345-6789-def0-1234-567890abcdef",
      "name": "Task abc12345...",
      "status": "running",
      "started_at": "2025-12-08T10:30:00Z",
      "ended_at": null,
      "duration_ms": 125000,
      "step_count": 45,
      "tool_call_count": 12,
      "last_activity": "2025-12-08T10:32:05Z",
      "project_path": "/Users/chagee/Repos/frago"
    },
    {
      "session_id": "def67890-1234-abc5-6789-0123456789ab",
      "name": "Task def67890...",
      "status": "completed",
      "started_at": "2025-12-08T09:00:00Z",
      "ended_at": "2025-12-08T09:30:00Z",
      "duration_ms": 1800000,
      "step_count": 120,
      "tool_call_count": 35,
      "last_activity": "2025-12-08T09:30:00Z",
      "project_path": "/Users/chagee/Repos/frago"
    }
  ],
  "total": 15,
  "offset": 0,
  "limit": 50,
  "has_more": false
}
```

**错误处理**：

| 错误 | 说明 | 响应 |
|------|------|------|
| 无会话目录 | `~/.frago/sessions/` 不存在 | `{"tasks": [], "total": 0, ...}` |
| 参数无效 | limit/offset 超出范围 | 自动修正到有效范围 |

---

## 2. 任务详情 API

### `get_task_detail(session_id)`

获取单个任务的完整详情，包括基本信息、统计和首页步骤。

**请求参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `session_id` | `string` | 任务会话 ID |

**返回类型**：`TaskDetailResponse`

```typescript
interface TaskDetailResponse {
  task: TaskDetail;
}

interface TaskDetail {
  session_id: string;
  name: string;
  status: 'running' | 'completed' | 'error' | 'cancelled';
  started_at: string;
  ended_at: string | null;
  duration_ms: number;
  project_path: string;

  // 统计信息
  step_count: number;
  tool_call_count: number;
  user_message_count: number;
  assistant_message_count: number;

  // 会话内容（首页）
  steps: TaskStep[];
  steps_total: number;
  steps_offset: number;
  has_more_steps: boolean;

  // 摘要（已完成任务）
  summary: TaskSummary | null;
}

interface TaskStep {
  step_id: number;
  type: 'user_message' | 'assistant_message' | 'tool_call' | 'tool_result' | 'system_event';
  timestamp: string;
  content: string;
  tool_name?: string;
  tool_status?: 'pending' | 'success' | 'error';
}

interface TaskSummary {
  total_duration_ms: number;
  user_message_count: number;
  assistant_message_count: number;
  tool_call_count: number;
  tool_success_count: number;
  tool_error_count: number;
  most_used_tools: { name: string; count: number }[];
}
```

**示例调用**：

```javascript
const response = await pywebview.api.get_task_detail('abc12345-6789-def0-1234-567890abcdef');
console.log(response.task.status);
console.log(response.task.steps);
```

**示例响应**：

```json
{
  "task": {
    "session_id": "abc12345-6789-def0-1234-567890abcdef",
    "name": "Task abc12345...",
    "status": "completed",
    "started_at": "2025-12-08T10:30:00Z",
    "ended_at": "2025-12-08T10:35:00Z",
    "duration_ms": 300000,
    "project_path": "/Users/chagee/Repos/frago",
    "step_count": 45,
    "tool_call_count": 12,
    "user_message_count": 5,
    "assistant_message_count": 15,
    "steps": [
      {
        "step_id": 1,
        "type": "user_message",
        "timestamp": "2025-12-08T10:30:00Z",
        "content": "帮我分析这个代码库的结构..."
      },
      {
        "step_id": 2,
        "type": "assistant_message",
        "timestamp": "2025-12-08T10:30:05Z",
        "content": "好的，我来分析一下代码库结构..."
      },
      {
        "step_id": 3,
        "type": "tool_call",
        "timestamp": "2025-12-08T10:30:10Z",
        "content": "Glob: pattern=**/*.py",
        "tool_name": "Glob",
        "tool_status": "success"
      }
    ],
    "steps_total": 45,
    "steps_offset": 0,
    "has_more_steps": true,
    "summary": {
      "total_duration_ms": 300000,
      "user_message_count": 5,
      "assistant_message_count": 15,
      "tool_call_count": 12,
      "tool_success_count": 11,
      "tool_error_count": 1,
      "most_used_tools": [
        { "name": "Read", "count": 5 },
        { "name": "Glob", "count": 3 },
        { "name": "Grep", "count": 2 }
      ]
    }
  }
}
```

**错误处理**：

| 错误 | 说明 | 响应 |
|------|------|------|
| 任务不存在 | session_id 无效 | `{"error": "Task not found", "session_id": "..."}` |
| 数据损坏 | metadata.json 解析失败 | `{"error": "Invalid task data"}` |

---

## 3. 任务步骤分页 API

### `get_task_steps(session_id, limit?, offset?)`

分页获取任务步骤，用于加载更多内容。

**请求参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|-------|------|
| `session_id` | `string` | - | 任务会话 ID |
| `limit` | `int` | 50 | 每页数量（1-100） |
| `offset` | `int` | 0 | 偏移量 |

**返回类型**：`TaskStepsResponse`

```typescript
interface TaskStepsResponse {
  session_id: string;
  steps: TaskStep[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}
```

**示例调用**：

```javascript
// 加载更多步骤
const response = await pywebview.api.get_task_steps('abc12345...', 50, 50);
if (response.has_more) {
  // 可以继续加载下一页
}
```

**示例响应**：

```json
{
  "session_id": "abc12345-6789-def0-1234-567890abcdef",
  "steps": [
    {
      "step_id": 51,
      "type": "tool_result",
      "timestamp": "2025-12-08T10:32:00Z",
      "content": "Found 15 Python files..."
    }
  ],
  "total": 120,
  "offset": 50,
  "limit": 50,
  "has_more": true
}
```

---

## 4. 任务更新订阅 API

### `subscribe_task_updates(session_id)`

订阅指定任务的实时更新。订阅后，新步骤和状态变化会通过 `window.handleTaskUpdate()` 回调推送。

**请求参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `session_id` | `string` | 任务会话 ID |

**返回类型**：`SubscriptionResponse`

```typescript
interface SubscriptionResponse {
  success: boolean;
  session_id: string;
  message?: string;
}
```

**前端回调注册**：

```javascript
// 注册回调处理函数
window.handleTaskUpdate = function(payload) {
  const { session_id, event, data, timestamp } = payload;

  switch (event) {
    case 'step_added':
      // 新步骤
      appendStep(data.step);
      break;
    case 'status_changed':
      // 状态变化
      updateTaskStatus(session_id, data.status);
      break;
    case 'task_completed':
      // 任务完成
      showSummary(data.summary);
      break;
  }
};

// 订阅任务更新
await pywebview.api.subscribe_task_updates('abc12345...');
```

**推送事件类型**：

| 事件 | 数据 | 说明 |
|------|------|------|
| `step_added` | `{ step: TaskStep }` | 新步骤添加 |
| `status_changed` | `{ status: string }` | 状态变化 |
| `task_completed` | `{ summary: TaskSummary }` | 任务完成 |
| `task_error` | `{ error: string }` | 任务出错 |

### `unsubscribe_task_updates(session_id)`

取消订阅指定任务的更新。

**请求参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `session_id` | `string` | 任务会话 ID |

**返回类型**：`SubscriptionResponse`

---

## 5. 配置 API（扩展）

### `get_config()`

获取用户配置。**扩展**：新增默认页面配置。

**返回类型**：

```typescript
interface UserConfig {
  theme: 'dark' | 'light';
  font_size: number;
  show_system_status: boolean;
  confirm_on_exit: boolean;
  auto_scroll_output: boolean;
  max_history_items: number;
  default_page: 'tips' | 'tasks';  // 新增
  shortcuts: Record<string, string>;
}
```

### `update_config(config)`

更新用户配置。

---

## 6. Python 后端实现规范

### 6.1 API 类扩展

```python
# gui/api.py

class FragoGuiApi:
    """GUI API - pywebview 暴露给 JavaScript 的接口"""

    # === 任务列表 ===
    def get_tasks(self, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """获取任务列表"""
        # 验证参数
        limit = max(1, min(100, limit))
        offset = max(0, offset)

        # 获取会话列表
        sessions = list_sessions(agent_type=AgentType.CLAUDE, limit=limit + offset)
        total = count_sessions(agent_type=AgentType.CLAUDE)

        # 转换为 TaskItem
        tasks = [
            TaskItem.from_session(s).model_dump(mode="json")
            for s in sessions[offset:offset + limit]
        ]

        return {
            "tasks": tasks,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(tasks) < total,
        }

    # === 任务详情 ===
    def get_task_detail(self, session_id: str) -> Dict[str, Any]:
        """获取任务详情"""
        session = read_metadata(session_id)
        if not session:
            return {"error": "Task not found", "session_id": session_id}

        steps_data = read_steps_paginated(session_id, limit=50, offset=0)
        summary = read_summary(session_id)

        detail = TaskDetail.from_session_data(
            session=session,
            steps=steps_data["steps"],
            summary=summary,
            offset=0,
            limit=50,
        )

        return {"task": detail.model_dump(mode="json")}

    # === 任务步骤分页 ===
    def get_task_steps(
        self,
        session_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """分页获取任务步骤"""
        limit = max(1, min(100, limit))
        offset = max(0, offset)

        result = read_steps_paginated(session_id, limit=limit, offset=offset)
        steps = [TaskStep.from_session_step(s).model_dump(mode="json") for s in result["steps"]]

        return {
            "session_id": session_id,
            "steps": steps,
            "total": result["total"],
            "offset": offset,
            "limit": limit,
            "has_more": result["has_more"],
        }

    # === 任务更新订阅 ===
    def subscribe_task_updates(self, session_id: str) -> Dict[str, Any]:
        """订阅任务更新"""
        # 注册监听器
        self._task_subscriptions[session_id] = True

        # 如果任务正在运行，启动监控
        session = read_metadata(session_id)
        if session and session.status == SessionStatus.RUNNING:
            self._start_task_monitor(session_id)

        return {"success": True, "session_id": session_id}

    def unsubscribe_task_updates(self, session_id: str) -> Dict[str, Any]:
        """取消订阅"""
        if session_id in self._task_subscriptions:
            del self._task_subscriptions[session_id]
            self._stop_task_monitor(session_id)

        return {"success": True, "session_id": session_id}

    def _push_task_update(self, session_id: str, event: str, data: Dict) -> None:
        """推送任务更新到前端"""
        if not self.window:
            return

        payload = {
            "session_id": session_id,
            "event": event,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }

        js_code = f"window.handleTaskUpdate && window.handleTaskUpdate({json.dumps(payload)})"
        try:
            self.window.evaluate_js(js_code)
        except Exception as e:
            logger.error(f"Failed to push task update: {e}")
```

### 6.2 Storage 层扩展

```python
# session/storage.py

def read_steps_paginated(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """分页读取会话步骤"""
    all_steps = read_steps(session_id, agent_type)
    total = len(all_steps)

    return {
        "steps": all_steps[offset:offset + limit],
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


def count_sessions(
    agent_type: Optional[AgentType] = None,
    status: Optional[SessionStatus] = None,
) -> int:
    """统计会话数量"""
    sessions = list_sessions(agent_type=agent_type, status=status, limit=10000)
    return len(sessions)
```

---

## 7. 错误码规范

| 错误码 | HTTP 等价 | 说明 |
|-------|----------|------|
| `task_not_found` | 404 | 任务不存在 |
| `invalid_session_id` | 400 | session_id 格式无效 |
| `invalid_params` | 400 | 参数无效 |
| `storage_error` | 500 | 存储层错误 |
| `subscription_failed` | 500 | 订阅失败 |

**错误响应格式**：

```json
{
  "error": "task_not_found",
  "message": "Task with ID abc12345... not found",
  "session_id": "abc12345..."
}
```

---

## 8. 性能要求

| API | 响应时间目标 | 说明 |
|-----|-------------|------|
| `get_tasks()` | <500ms | 50 条任务 |
| `get_task_detail()` | <1000ms | 包含 50 条步骤 |
| `get_task_steps()` | <300ms | 单页 50 条 |
| `subscribe_task_updates()` | <100ms | 订阅注册 |

---

## 9. 版本兼容性

| API 版本 | 变更 |
|---------|------|
| v1.0 | 初始版本（本功能） |

**向后兼容策略**：
- 新增字段为可选（nullable）
- 删除字段前标记 deprecated
- 重大变更需要版本升级
