# Data Model: Frago GUI Tasks Redesign

**Feature Branch**: `011-gui-tasks-redesign`
**Date**: 2025-12-08

## 实体关系图

```
┌─────────────────────────────────────────────────────────────────────┐
│                          GUI Layer                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│   ┌───────────────┐     ┌───────────────┐     ┌───────────────┐     │
│   │   TaskItem    │────>│  TaskDetail   │────>│  SessionStep  │     │
│   │  (列表项)      │     │  (详情页)      │     │  (步骤记录)    │     │
│   └───────────────┘     └───────────────┘     └───────────────┘     │
│          │                      │                      │             │
│          │                      │                      │             │
│          ▼                      ▼                      ▼             │
│   ┌─────────────────────────────────────────────────────────┐       │
│   │                    TaskStatus                            │       │
│   │   RUNNING (黄) | COMPLETED (绿) | ERROR (红) | CANCELLED │       │
│   └─────────────────────────────────────────────────────────┘       │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ 数据映射
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Session Storage Layer                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│   ┌───────────────────┐                                              │
│   │  MonitoredSession │ ──────────────────────────────────────┐     │
│   │  (会话元数据)       │                                       │     │
│   │                   │     ┌───────────────┐                  │     │
│   │  session_id ◀─────│─────│  SessionStep  │──┐               │     │
│   │  status           │     │  (步骤日志)     │  │               │     │
│   │  started_at       │     └───────────────┘  │ (1:N)         │     │
│   │  step_count       │                        │               │     │
│   │  tool_call_count  │     ┌───────────────┐  │               │     │
│   │  last_activity    │     │ ToolCallRecord│──┘               │     │
│   └───────────────────┘     │ (工具调用记录) │                   │     │
│                             └───────────────┘                   │     │
│                                                                 │     │
│   存储位置: ~/.frago/sessions/{agent_type}/{session_id}/       │     │
│   ├── metadata.json  ◀──────────────────────────────────────────┘     │
│   ├── steps.jsonl                                                     │
│   └── summary.json                                                    │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 1. GUI 层数据模型（新增）

### 1.1 TaskItem（任务列表项）

**用途**：Tasks 页面列表展示

```python
class TaskItem(BaseModel):
    """任务列表项 - 用于 Tasks 页面"""

    session_id: str = Field(..., description="会话 ID（唯一标识）")
    name: str = Field(..., description="任务名称（从首条消息提取）")
    status: TaskStatus = Field(..., description="任务状态")
    started_at: datetime = Field(..., description="开始时间")
    ended_at: Optional[datetime] = Field(None, description="结束时间")
    duration_ms: int = Field(0, ge=0, description="持续时间（毫秒）")
    step_count: int = Field(0, ge=0, description="步骤总数")
    tool_call_count: int = Field(0, ge=0, description="工具调用次数")
    last_activity: datetime = Field(..., description="最后活动时间")
    project_path: str = Field(..., description="关联项目路径")

    @classmethod
    def from_session(cls, session: MonitoredSession) -> "TaskItem":
        """从 MonitoredSession 转换"""
        # 计算持续时间
        if session.ended_at:
            duration = session.ended_at - session.started_at
        else:
            duration = datetime.now(timezone.utc) - session.started_at

        # 从 session_id 或首条消息提取任务名称
        name = cls._extract_task_name(session)

        return cls(
            session_id=session.session_id,
            name=name,
            status=TaskStatus(session.status.value),
            started_at=session.started_at,
            ended_at=session.ended_at,
            duration_ms=int(duration.total_seconds() * 1000),
            step_count=session.step_count,
            tool_call_count=session.tool_call_count,
            last_activity=session.last_activity,
            project_path=session.project_path,
        )

    @staticmethod
    def _extract_task_name(session: MonitoredSession) -> str:
        """提取任务名称"""
        # 优先使用 session_id 前 8 位作为名称
        return f"Task {session.session_id[:8]}..."
```

**JSON 序列化格式**：
```json
{
  "session_id": "abc12345-6789-...",
  "name": "Task abc12345...",
  "status": "running",
  "started_at": "2025-12-08T10:30:00Z",
  "ended_at": null,
  "duration_ms": 125000,
  "step_count": 45,
  "tool_call_count": 12,
  "last_activity": "2025-12-08T10:32:05Z",
  "project_path": "/Users/chagee/Repos/frago"
}
```

### 1.2 TaskStatus（任务状态枚举）

**用途**：GUI 展示状态颜色映射

```python
class TaskStatus(str, Enum):
    """任务状态（GUI 展示用）"""

    RUNNING = "running"        # 进行中 - 黄色
    COMPLETED = "completed"    # 已完成 - 绿色
    ERROR = "error"            # 出错 - 红色
    CANCELLED = "cancelled"    # 已取消 - 红色

    @property
    def color(self) -> str:
        """返回状态对应的 CSS 颜色变量"""
        colors = {
            TaskStatus.RUNNING: "var(--accent-warning)",
            TaskStatus.COMPLETED: "var(--accent-success)",
            TaskStatus.ERROR: "var(--accent-error)",
            TaskStatus.CANCELLED: "var(--accent-error)",
        }
        return colors[self]

    @property
    def icon(self) -> str:
        """返回状态图标"""
        icons = {
            TaskStatus.RUNNING: "●",
            TaskStatus.COMPLETED: "✓",
            TaskStatus.ERROR: "✗",
            TaskStatus.CANCELLED: "○",
        }
        return icons[self]

    @property
    def label(self) -> str:
        """返回状态标签（中文）"""
        labels = {
            TaskStatus.RUNNING: "进行中",
            TaskStatus.COMPLETED: "已完成",
            TaskStatus.ERROR: "出错",
            TaskStatus.CANCELLED: "已取消",
        }
        return labels[self]
```

### 1.3 TaskDetail（任务详情）

**用途**：任务详情页面展示

```python
class TaskDetail(BaseModel):
    """任务详情 - 用于任务详情页"""

    # 基本信息（来自 TaskItem）
    session_id: str
    name: str
    status: TaskStatus
    started_at: datetime
    ended_at: Optional[datetime]
    duration_ms: int
    project_path: str

    # 统计信息
    step_count: int = Field(0, description="步骤总数")
    tool_call_count: int = Field(0, description="工具调用次数")
    user_message_count: int = Field(0, description="用户消息数")
    assistant_message_count: int = Field(0, description="助手消息数")

    # 会话内容（分页）
    steps: List["TaskStep"] = Field(default_factory=list, description="步骤列表")
    steps_total: int = Field(0, description="步骤总数")
    steps_offset: int = Field(0, description="当前偏移量")
    has_more_steps: bool = Field(False, description="是否有更多步骤")

    # 摘要（会话完成后）
    summary: Optional["TaskSummary"] = Field(None, description="会话摘要")

    @classmethod
    def from_session_data(
        cls,
        session: MonitoredSession,
        steps: List[SessionStep],
        summary: Optional[SessionSummary] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> "TaskDetail":
        """从会话数据构建任务详情"""
        # 计算消息统计
        user_count = sum(1 for s in steps if s.type == StepType.USER_MESSAGE)
        assistant_count = sum(1 for s in steps if s.type == StepType.ASSISTANT_MESSAGE)
        total_steps = session.step_count

        return cls(
            session_id=session.session_id,
            name=f"Task {session.session_id[:8]}...",
            status=TaskStatus(session.status.value),
            started_at=session.started_at,
            ended_at=session.ended_at,
            duration_ms=int((session.ended_at or datetime.now(timezone.utc) - session.started_at).total_seconds() * 1000),
            project_path=session.project_path,
            step_count=total_steps,
            tool_call_count=session.tool_call_count,
            user_message_count=user_count,
            assistant_message_count=assistant_count,
            steps=[TaskStep.from_session_step(s) for s in steps],
            steps_total=total_steps,
            steps_offset=offset,
            has_more_steps=offset + len(steps) < total_steps,
            summary=TaskSummary.from_session_summary(summary) if summary else None,
        )
```

### 1.4 TaskStep（任务步骤）

**用途**：任务详情页步骤展示

```python
class TaskStep(BaseModel):
    """任务步骤 - GUI 展示用"""

    step_id: int = Field(..., ge=1, description="步骤序号")
    type: StepType = Field(..., description="步骤类型")
    timestamp: datetime = Field(..., description="时间戳")
    content: str = Field(..., description="内容摘要")

    # 工具调用相关
    tool_name: Optional[str] = Field(None, description="工具名称")
    tool_status: Optional[ToolCallStatus] = Field(None, description="工具调用状态")

    @classmethod
    def from_session_step(cls, step: SessionStep) -> "TaskStep":
        """从 SessionStep 转换"""
        return cls(
            step_id=step.step_id,
            type=step.type,
            timestamp=step.timestamp,
            content=step.content_summary,
            tool_name=None,  # 从 content 中解析
            tool_status=None,
        )
```

**步骤类型（复用现有）**：
```python
class StepType(str, Enum):
    """步骤类型"""

    USER_MESSAGE = "user_message"          # 用户输入
    ASSISTANT_MESSAGE = "assistant_message" # 助手回复
    TOOL_CALL = "tool_call"                # 工具调用
    TOOL_RESULT = "tool_result"            # 工具结果
    SYSTEM_EVENT = "system_event"          # 系统事件
```

### 1.5 TaskSummary（任务摘要）

**用途**：已完成任务的统计摘要

```python
class TaskSummary(BaseModel):
    """任务摘要 - 会话完成后生成"""

    total_duration_ms: int = Field(..., ge=0, description="总耗时")
    user_message_count: int = Field(0, description="用户消息数")
    assistant_message_count: int = Field(0, description="助手消息数")
    tool_call_count: int = Field(0, description="工具调用总数")
    tool_success_count: int = Field(0, description="成功的工具调用")
    tool_error_count: int = Field(0, description="失败的工具调用")
    most_used_tools: List[ToolUsageStat] = Field(default_factory=list, description="最常用工具")

    @classmethod
    def from_session_summary(cls, summary: SessionSummary) -> "TaskSummary":
        """从 SessionSummary 转换"""
        return cls(
            total_duration_ms=summary.total_duration_ms,
            user_message_count=summary.user_message_count,
            assistant_message_count=summary.assistant_message_count,
            tool_call_count=summary.tool_call_count,
            tool_success_count=summary.tool_success_count,
            tool_error_count=summary.tool_error_count,
            most_used_tools=[
                ToolUsageStat(name=t.tool_name, count=t.count)
                for t in summary.most_used_tools
            ],
        )


class ToolUsageStat(BaseModel):
    """工具使用统计"""

    name: str = Field(..., description="工具名称")
    count: int = Field(..., ge=0, description="使用次数")
```

---

## 2. 页面状态模型（扩展现有）

### 2.1 PageType（页面类型枚举）

**修改**：扩展现有枚举

```python
class PageType(str, Enum):
    """页面类型"""

    TIPS = "tips"                # 新增：Tips 页面（默认）
    TASKS = "tasks"              # 新增：Tasks 页面（原 home）
    TASK_DETAIL = "task_detail"  # 新增：任务详情页
    RECIPES = "recipes"          # 保留
    RECIPE_DETAIL = "recipe_detail"  # 保留
    SKILLS = "skills"            # 保留
    SETTINGS = "settings"        # 保留
    # HISTORY = "history"        # 移除：合并到 Tasks
```

### 2.2 AppState（应用状态）

**修改**：扩展现有状态

```python
class AppState(BaseModel):
    """应用运行时状态"""

    # 页面状态
    current_page: PageType = Field(
        default=PageType.TIPS,  # 修改：默认改为 TIPS
        description="当前页面"
    )

    # 任务状态（多任务支持）
    current_task_id: Optional[str] = Field(
        None,
        description="当前查看的任务 ID（任务详情页）"
    )

    # 保留现有字段...
    task_status: TaskStatus = Field(default=TaskStatus.IDLE)
    connection_status: ConnectionStatus = Field(default=ConnectionStatus.DISCONNECTED)
    current_task_progress: float = Field(default=0.0)
    last_error: Optional[str] = Field(None)
```

---

## 3. API 数据传输模型（新增）

### 3.1 TaskListResponse（任务列表响应）

```python
class TaskListResponse(BaseModel):
    """任务列表 API 响应"""

    tasks: List[TaskItem] = Field(default_factory=list, description="任务列表")
    total: int = Field(0, ge=0, description="总数")
    offset: int = Field(0, ge=0, description="偏移量")
    limit: int = Field(50, ge=1, le=100, description="每页数量")
    has_more: bool = Field(False, description="是否有更多")
```

**JSON 格式**：
```json
{
  "tasks": [
    {
      "session_id": "abc12345...",
      "name": "Task abc12345...",
      "status": "running",
      "started_at": "2025-12-08T10:30:00Z",
      "duration_ms": 125000,
      "step_count": 45,
      "tool_call_count": 12
    }
  ],
  "total": 15,
  "offset": 0,
  "limit": 50,
  "has_more": false
}
```

### 3.2 TaskDetailResponse（任务详情响应）

```python
class TaskDetailResponse(BaseModel):
    """任务详情 API 响应"""

    task: TaskDetail = Field(..., description="任务详情")
```

### 3.3 TaskStepsResponse（任务步骤响应）

```python
class TaskStepsResponse(BaseModel):
    """任务步骤分页 API 响应"""

    session_id: str = Field(..., description="会话 ID")
    steps: List[TaskStep] = Field(default_factory=list, description="步骤列表")
    total: int = Field(0, ge=0, description="总数")
    offset: int = Field(0, ge=0, description="偏移量")
    limit: int = Field(50, ge=1, le=100, description="每页数量")
    has_more: bool = Field(False, description="是否有更多")
```

---

## 4. 验证规则

### 4.1 TaskItem 验证

| 字段 | 规则 | 错误处理 |
|------|------|---------|
| session_id | 非空字符串 | 必填 |
| status | 有效枚举值 | 默认 RUNNING |
| started_at | ISO 8601 时间 | 必填 |
| duration_ms | >= 0 | 默认 0 |
| step_count | >= 0 | 默认 0 |

### 4.2 TaskStep 验证

| 字段 | 规则 | 错误处理 |
|------|------|---------|
| step_id | >= 1 | 必填 |
| type | 有效枚举值 | 必填 |
| content | 最大 500 字符 | 截断 |

---

## 5. 状态转换

### 5.1 TaskStatus 状态机

```
                    ┌──────────────┐
                    │   RUNNING    │ (黄色)
                    │   进行中      │
                    └──────┬───────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
           ▼               ▼               ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │  COMPLETED   │ │    ERROR     │ │  CANCELLED   │
    │   已完成      │ │    出错      │ │   已取消      │
    │   (绿色)      │ │   (红色)     │ │   (红色)      │
    └──────────────┘ └──────────────┘ └──────────────┘

状态转换触发条件：
- RUNNING → COMPLETED: 无活动超时（300s）或正常结束
- RUNNING → ERROR: 会话异常终止
- RUNNING → CANCELLED: 用户主动取消
```

### 5.2 页面导航状态

```
┌───────────────────────────────────────────────────────────────┐
│                         导航菜单                               │
├───────────────────────────────────────────────────────────────┤
│   Tips ◀────┐                                                 │
│   Tasks ────┼──▶ TaskDetail ──────┐                          │
│   Recipes   │                     │ (返回)                    │
│   Skills    │                     ▼                           │
│   Settings  └──────────────────── Tasks                       │
└───────────────────────────────────────────────────────────────┘

默认启动页: Tips
页面切换: switchPage(PageType)
详情页进入: openTaskDetail(session_id)
详情页返回: backToTasks()（保持滚动位置）
```

---

## 6. 数据存储映射

### 6.1 GUI 模型 ↔ Session 模型映射

| GUI 模型 | Session 模型 | 转换方法 |
|---------|-------------|---------|
| TaskItem | MonitoredSession | `TaskItem.from_session()` |
| TaskStatus | SessionStatus | 直接映射（值相同） |
| TaskStep | SessionStep | `TaskStep.from_session_step()` |
| TaskSummary | SessionSummary | `TaskSummary.from_session_summary()` |
| TaskDetail | MonitoredSession + steps + summary | `TaskDetail.from_session_data()` |

### 6.2 文件存储结构（复用现有）

```
~/.frago/sessions/claude/{session_id}/
├── metadata.json    ──▶ MonitoredSession ──▶ TaskItem/TaskDetail
├── steps.jsonl      ──▶ List[SessionStep] ──▶ List[TaskStep]
└── summary.json     ──▶ SessionSummary ──▶ TaskSummary
```

---

## 7. 索引与查询优化

### 7.1 任务列表查询

**查询模式**：
```python
# 按最后活动时间倒序（最新在前）
list_sessions(agent_type=AgentType.CLAUDE, limit=50)

# 按状态筛选
list_sessions(status=SessionStatus.RUNNING)
```

**排序规则**：
1. 默认：按 `last_activity` 倒序
2. FR-011：按 `started_at` 倒序

### 7.2 步骤分页查询

**查询模式**：
```python
# 分页读取（新 API）
read_steps_paginated(session_id, limit=50, offset=0)

# 返回结构
{
    "steps": [...],
    "total": 150,
    "offset": 0,
    "limit": 50,
    "has_more": True
}
```

---

## 8. 前端数据模型（TypeScript 类型定义参考）

```typescript
// TaskItem - 任务列表项
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

// TaskDetail - 任务详情
interface TaskDetail extends TaskItem {
  user_message_count: number;
  assistant_message_count: number;
  steps: TaskStep[];
  steps_total: number;
  steps_offset: number;
  has_more_steps: boolean;
  summary: TaskSummary | null;
}

// TaskStep - 任务步骤
interface TaskStep {
  step_id: number;
  type: 'user_message' | 'assistant_message' | 'tool_call' | 'tool_result' | 'system_event';
  timestamp: string;
  content: string;
  tool_name?: string;
  tool_status?: 'pending' | 'success' | 'error';
}

// TaskSummary - 任务摘要
interface TaskSummary {
  total_duration_ms: number;
  user_message_count: number;
  assistant_message_count: number;
  tool_call_count: number;
  tool_success_count: number;
  tool_error_count: number;
  most_used_tools: { name: string; count: number }[];
}

// API 响应类型
interface TaskListResponse {
  tasks: TaskItem[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}
```
