# Data Model: Vite React 前端重构

**Date**: 2025-12-09
**Feature**: 012-vite-react-frontend

## 概述

前端数据模型基于现有 Python 后端模型，使用 TypeScript 接口定义。所有数据通过 `window.pywebview.api` 传输，格式为 JSON。

## 实体定义

### 1. 页面类型 (PageType)

```typescript
type PageType =
  | 'tips'
  | 'tasks'
  | 'task_detail'
  | 'recipes'
  | 'recipe_detail'
  | 'skills'
  | 'settings';
```

**状态转换**：
- `tips` ↔ `tasks` ↔ `recipes` ↔ `skills` ↔ `settings`（通过 NavTabs 切换）
- `tasks` → `task_detail`（点击任务卡片）
- `recipes` → `recipe_detail`（点击配方卡片）
- `task_detail` → `tasks`（返回按钮）
- `recipe_detail` → `recipes`（返回按钮）

---

### 2. 任务状态 (TaskStatus)

```typescript
type TaskStatus = 'running' | 'completed' | 'error' | 'cancelled';
```

**颜色映射**：

| 状态 | 颜色变量 | 图标 | 标签 |
|------|---------|------|------|
| running | `--accent-warning` | ● | 进行中 |
| completed | `--accent-success` | ✓ | 已完成 |
| error | `--accent-error` | ✗ | 出错 |
| cancelled | `--accent-error` | ○ | 已取消 |

---

### 3. 任务列表项 (TaskItem)

```typescript
interface TaskItem {
  session_id: string;      // 会话 ID（唯一标识）
  name: string;            // 任务名称
  status: TaskStatus;      // 任务状态
  started_at: string;      // 开始时间 (ISO 8601)
  ended_at: string | null; // 结束时间 (ISO 8601)
  duration_ms: number;     // 持续时间（毫秒）
  step_count: number;      // 步骤总数
  tool_call_count: number; // 工具调用次数
  last_activity: string;   // 最后活动时间 (ISO 8601)
  project_path: string;    // 关联项目路径
}
```

**来源**：`window.pywebview.api.get_tasks()`

---

### 4. 任务详情 (TaskDetail)

```typescript
interface TaskDetail {
  // 基本信息
  session_id: string;
  name: string;
  status: TaskStatus;
  started_at: string;
  ended_at: string | null;
  duration_ms: number;
  project_path: string;

  // 统计信息
  step_count: number;
  tool_call_count: number;
  user_message_count: number;
  assistant_message_count: number;

  // 步骤分页
  steps: TaskStep[];
  steps_total: number;
  steps_offset: number;
  has_more_steps: boolean;

  // 摘要（可选）
  summary: TaskSummary | null;
}
```

**来源**：`window.pywebview.api.get_task_detail()`

---

### 5. 任务步骤 (TaskStep)

```typescript
interface TaskStep {
  step_id: number;           // 步骤序号（从 1 开始）
  type: StepType;            // 步骤类型
  timestamp: string;         // 时间戳 (ISO 8601)
  content: string;           // 内容摘要
  tool_name: string | null;  // 工具名称（仅工具调用）
  tool_status: string | null;// 工具状态（仅工具调用）
}

type StepType =
  | 'user_message'
  | 'assistant_message'
  | 'tool_use'
  | 'tool_result'
  | 'system';
```

---

### 6. 任务摘要 (TaskSummary)

```typescript
interface TaskSummary {
  total_duration_ms: number;
  user_message_count: number;
  assistant_message_count: number;
  tool_call_count: number;
  tool_success_count: number;
  tool_error_count: number;
  most_used_tools: ToolUsageStat[];
}

interface ToolUsageStat {
  name: string;
  count: number;
}
```

---

### 7. 配方项 (RecipeItem)

```typescript
interface RecipeItem {
  name: string;
  description: string | null;
  category: 'atomic' | 'workflow';
  icon: string | null;
  tags: string[];
  path: string | null;
  source: 'User' | 'Project' | 'System' | null;
  runtime: 'js' | 'python' | 'shell' | null;
}
```

**来源**：`window.pywebview.api.get_recipes()`

---

### 8. 技能项 (SkillItem)

```typescript
interface SkillItem {
  name: string;
  description: string | null;
  icon: string | null;
  file_path: string;
}
```

**来源**：`window.pywebview.api.get_skills()`

---

### 9. 用户配置 (UserConfig)

```typescript
interface UserConfig {
  theme: 'dark' | 'light';
  font_size: number;           // 10-24
  show_system_status: boolean;
  confirm_on_exit: boolean;
  auto_scroll_output: boolean;
  max_history_items: number;   // 10-1000
  shortcuts: Record<string, string>;
}
```

**验证规则**：
- `font_size`: 10 ≤ value ≤ 24
- `max_history_items`: 10 ≤ value ≤ 1000

**来源**：`window.pywebview.api.get_config()`
**更新**：`window.pywebview.api.update_config()`

---

### 10. 系统状态 (SystemStatus)

```typescript
interface SystemStatus {
  cpu_percent: number;      // 0-100
  memory_percent: number;   // 0-100
  chrome_connected: boolean;
}
```

**来源**：`window.pywebview.api.get_system_status()`

---

### 11. Linux 发行版信息 (DistroInfo)

```typescript
interface DistroInfo {
  id: string;          // 如 'ubuntu', 'fedora', 'arch'
  name: string;        // 如 'Ubuntu 24.04 LTS'
  version_id: string;  // 如 '24.04'
  supported: boolean;  // 是否支持自动安装
  packages: string[];  // 需要安装的包列表
  install_cmd: string; // 安装命令
}
```

**用途**：Linux 依赖自动安装流程

---

## 状态管理 (Zustand Store)

```typescript
interface AppState {
  // 页面状态
  currentPage: PageType;
  currentTaskId: string | null;
  currentRecipeName: string | null;

  // 数据缓存
  config: UserConfig;
  tasks: TaskItem[];
  taskDetail: TaskDetail | null;
  recipes: RecipeItem[];
  skills: SkillItem[];
  systemStatus: SystemStatus;

  // UI 状态
  isLoading: boolean;
  toasts: Toast[];

  // Actions
  switchPage: (page: PageType) => void;
  loadTasks: () => Promise<void>;
  openTaskDetail: (sessionId: string) => Promise<void>;
  loadRecipes: () => Promise<void>;
  loadSkills: () => Promise<void>;
  updateConfig: (config: Partial<UserConfig>) => Promise<void>;
  showToast: (message: string, type: ToastType) => void;
}
```

---

## 数据流

```
┌─────────────────────────────────────────────────────────────┐
│                        React 组件                            │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│  │TaskList │  │TaskCard │  │Settings │  │StatusBar│        │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘        │
│       │            │            │            │              │
│       └────────────┴────────────┴────────────┘              │
│                          │                                   │
│                    ┌─────▼─────┐                            │
│                    │  Zustand  │                            │
│                    │   Store   │                            │
│                    └─────┬─────┘                            │
│                          │                                   │
└──────────────────────────┼──────────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │ pywebview   │
                    │    API      │
                    └──────┬──────┘
                           │
┌──────────────────────────┼──────────────────────────────────┐
│                    Python 后端                               │
│                    ┌─────▼─────┐                            │
│                    │FragoGuiApi│                            │
│                    └─────┬─────┘                            │
│                          │                                   │
│     ┌────────────────────┼────────────────────┐             │
│     │                    │                    │             │
│ ┌───▼───┐          ┌─────▼─────┐        ┌────▼────┐        │
│ │Session│          │  Config   │        │ Recipe  │        │
│ │Storage│          │  Storage  │        │  CLI    │        │
│ └───────┘          └───────────┘        └─────────┘        │
└─────────────────────────────────────────────────────────────┘
```
