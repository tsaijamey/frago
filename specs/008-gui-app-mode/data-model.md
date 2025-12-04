# Data Model: Frago GUI 应用模式

**Feature**: 008-gui-app-mode
**Date**: 2025-12-04

## 1. 实体定义

### 1.1 WindowConfig（窗口配置）

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class WindowConfig:
    """GUI 窗口显示配置"""
    width: int = 600
    height: int = 1434
    title: str = "Frago GUI"
    frameless: bool = True
    resizable: bool = False
    min_width: int = 400
    min_height: int = 600

    # 窗口位置（None 表示居中）
    x: Optional[int] = None
    y: Optional[int] = None
```

### 1.2 AppState（应用状态）

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List
from datetime import datetime

class TaskStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"

class ConnectionStatus(Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CHECKING = "checking"

class PageType(Enum):
    HOME = "home"
    RECIPES = "recipes"
    SKILLS = "skills"
    HISTORY = "history"
    SETTINGS = "settings"

@dataclass
class AppState:
    """GUI 应用运行时状态"""
    current_page: PageType = PageType.HOME
    task_status: TaskStatus = TaskStatus.IDLE
    connection_status: ConnectionStatus = ConnectionStatus.CHECKING
    current_task_id: Optional[str] = None
    current_task_progress: float = 0.0  # 0.0 - 1.0
    last_error: Optional[str] = None
```

### 1.3 UserConfig（用户配置）

```python
from dataclasses import dataclass, field
from typing import Dict, Any

@dataclass
class UserConfig:
    """用户偏好设置，持久化到 ~/.frago/gui_config.json"""
    theme: str = "dark"  # "dark" | "light"
    font_size: int = 14
    show_system_status: bool = True
    confirm_on_exit: bool = True
    auto_scroll_output: bool = True
    max_history_items: int = 100

    # 快捷键配置
    shortcuts: Dict[str, str] = field(default_factory=lambda: {
        "send": "Ctrl+Enter",
        "clear": "Ctrl+L",
        "settings": "Ctrl+,",
    })
```

### 1.4 CommandRecord（命令执行记录）

```python
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

class CommandType(Enum):
    AGENT = "agent"       # frago agent 调用
    RECIPE = "recipe"     # 配方执行
    CHROME = "chrome"     # Chrome 操作

@dataclass
class CommandRecord:
    """命令执行历史记录"""
    id: str                              # UUID
    timestamp: datetime
    command_type: CommandType
    input_text: str                      # 用户输入
    status: TaskStatus
    duration_ms: Optional[int] = None   # 执行耗时
    output: Optional[str] = None        # 输出结果
    error: Optional[str] = None         # 错误信息
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### 1.5 RecipeItem（配方项）

```python
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class RecipeItem:
    """配方列表项（从 frago recipe list 获取）"""
    name: str
    description: Optional[str] = None
    category: str = "atomic"  # "atomic" | "workflow"
    icon: Optional[str] = None
    tags: List[str] = field(default_factory=list)
```

### 1.6 SkillItem（技能项）

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class SkillItem:
    """技能列表项（从 ~/.claude/skills/ 获取）"""
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    file_path: str
```

### 1.7 StreamMessage（流式消息）

```python
from dataclasses import dataclass
from typing import Optional, Dict, Any
from enum import Enum

class MessageType(Enum):
    USER = "user"           # 用户输入
    ASSISTANT = "assistant" # Agent 响应
    SYSTEM = "system"       # 系统消息
    PROGRESS = "progress"   # 进度更新
    ERROR = "error"         # 错误消息

@dataclass
class StreamMessage:
    """stream-json 解析后的消息"""
    type: MessageType
    content: str
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 进度类型消息专用
    progress: Optional[float] = None
    step: Optional[str] = None
```

## 2. 关系图

```
┌─────────────────────────────────────────────────────────┐
│                    Frago GUI App                        │
└─────────────────────────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
   ┌──────────┐      ┌──────────┐      ┌──────────┐
   │WindowConfig│    │ AppState │      │UserConfig│
   │ (runtime) │    │ (runtime)│      │(persisted)│
   └──────────┘      └──────────┘      └──────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
   ┌──────────┐      ┌──────────┐      ┌──────────┐
   │RecipeItem│      │SkillItem │      │CommandRecord│
   │ (cached) │      │ (cached) │      │ (persisted) │
   └──────────┘      └──────────┘      └──────────┘
                                              │
                                              ▼
                                       ┌──────────┐
                                       │StreamMessage│
                                       │ (runtime) │
                                       └──────────┘
```

## 3. 状态转换

### 3.1 TaskStatus 状态机

```
         ┌──────────────────────────────┐
         │                              │
         ▼                              │
     ┌──────┐  start_task()  ┌─────────┐│
     │ IDLE │ ─────────────► │ RUNNING ││
     └──────┘                └─────────┘│
         ▲                       │ │    │
         │      complete()       │ │    │
         ├───────────────────────┘ │    │
         │                         │    │
         │       error()           │    │
         │  ┌──────────────────────┘    │
         │  ▼                           │
     ┌───────┐                          │
     │ ERROR │──────────────────────────┘
     └───────┘     reset()

     cancel() 可从 RUNNING 直接回到 IDLE
```

### 3.2 PageType 导航

```
    HOME ◄──────► RECIPES
      ▲              ▲
      │              │
      ▼              ▼
  SETTINGS ◄────► SKILLS
      ▲              ▲
      │              │
      └──► HISTORY ◄─┘
```

## 4. 验证规则

### 4.1 WindowConfig

- `width >= min_width`（400）
- `height >= min_height`（600）
- `title` 非空

### 4.2 UserConfig

- `theme` ∈ {"dark", "light"}
- `font_size` ∈ [10, 24]
- `max_history_items` ∈ [10, 1000]

### 4.3 CommandRecord

- `id` 必须是有效 UUID
- `timestamp` 必须是有效 datetime
- `input_text` 非空
- 如果 `status == COMPLETED`，则 `duration_ms` 必须有值
- 如果 `status == ERROR`，则 `error` 必须有值

## 5. 持久化映射

### 文件结构

```
~/.frago/
├── gui_config.json      # UserConfig
└── gui_history.jsonl    # CommandRecord (每行一条)
```

### gui_config.json 示例

```json
{
  "theme": "dark",
  "font_size": 14,
  "show_system_status": true,
  "confirm_on_exit": true,
  "auto_scroll_output": true,
  "max_history_items": 100,
  "shortcuts": {
    "send": "Ctrl+Enter",
    "clear": "Ctrl+L",
    "settings": "Ctrl+,"
  }
}
```

### gui_history.jsonl 示例

```jsonl
{"id":"uuid1","timestamp":"2025-12-04T10:00:00Z","command_type":"agent","input_text":"打开浏览器","status":"completed","duration_ms":2500,"output":"已打开 Chrome"}
{"id":"uuid2","timestamp":"2025-12-04T10:01:00Z","command_type":"recipe","input_text":"run google-search","status":"error","error":"Recipe not found"}
```

## 6. 索引和查询

### 历史记录查询

```python
def get_history(
    limit: int = 50,
    offset: int = 0,
    command_type: Optional[CommandType] = None,
    status: Optional[TaskStatus] = None,
) -> List[CommandRecord]:
    """分页查询历史记录"""
    pass
```

### 配方/技能缓存

```python
# 启动时加载，运行时缓存
_recipe_cache: List[RecipeItem] = []
_skill_cache: List[SkillItem] = []

def refresh_recipes() -> List[RecipeItem]:
    """从 frago recipe list 刷新配方列表"""
    pass

def refresh_skills() -> List[SkillItem]:
    """从 ~/.claude/skills/ 刷新技能列表"""
    pass
```
