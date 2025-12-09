# Research: Frago GUI Tasks Redesign

**Feature Branch**: `011-gui-tasks-redesign`
**Date**: 2025-12-08

## 研究主题概览

| 研究领域 | 关键决策 | 备选方案 |
|---------|---------|---------|
| 实时数据推送 | 混合模式（轮询 + 推送） | 纯 WebSocket（不适用于 pywebview） |
| 会话内容加载 | 后端分页 + 前端虚拟滚动 | 一次全量加载（大会话不可行） |
| 任务状态监控 | SessionMonitorPool 多会话管理 | 单会话模式（当前实现） |
| 页面导航 | JavaScript 路由（单页应用） | 多 HTML 文件（增加复杂度） |

---

## 1. pywebview 实时数据更新

### 1.1 现有实现模式

**推送机制**：使用 `evaluate_js()` 从 Python 向前端推送数据
```python
def _push_stream_message(self, message: StreamMessage) -> None:
    if self.window:
        js_code = f"window.handleStreamMessage && window.handleStreamMessage({json.dumps(message.to_dict())})"
        self.window.evaluate_js(js_code)
```

**轮询 vs 推送对比**：

| 场景 | 当前模式 | 间隔 | 位置 |
|------|---------|------|------|
| 任务状态 | 轮询 | 500ms | `app.js:159-180` |
| 系统状态 | 轮询 | 5000ms | `app.js:580-603` |
| 流消息 | 推送 | 实时 | `api.py:279-309` |
| 列表刷新 | 按需拉取 | N/A | `app.js:237-247` |

### 1.2 推荐方案

**决策**：采用混合模式
- **任务列表**：智能轮询（任务运行中 2s，空闲时 10s）
- **任务详情**：推送模式（复用现有 `handleStreamMessage`）
- **状态变化**：推送通知 + 用户手动刷新

**理由**：
- pywebview 不支持 WebSocket，推送基于 `evaluate_js()`
- 轮询适合状态概览，推送适合详细日志流
- 混合模式在性能和实时性间取得平衡

**考虑的替代方案**：
- 纯轮询（200ms）：实时性好但 CPU 占用高，已拒绝
- 纯推送：需要维护消息队列，实现复杂度高，可作为未来优化

### 1.3 线程安全考虑

**问题识别**：现有实现从工作线程调用 `evaluate_js()`，存在潜在竞态条件

**推荐改进**：
```python
# 添加异常捕获，确保推送失败不中断业务
def _push_stream_message(self, message: StreamMessage) -> None:
    if not self.window:
        return
    try:
        js_code = (
            f"try {{ "
            f"window.handleStreamMessage && "
            f"window.handleStreamMessage({json.dumps(message.to_dict())}); "
            f"}} catch(e) {{ console.error('Stream error:', e); }}"
        )
        self.window.evaluate_js(js_code)
    except Exception as e:
        import logging
        logging.exception(f"Failed to push stream message: {e}")
```

---

## 2. 会话内容增量加载

### 2.1 现有数据结构

**会话存储位置**：`~/.frago/sessions/{agent_type}/{session_id}/`
```
├── metadata.json   # 会话元数据
├── steps.jsonl     # 步骤日志（Line-delimited JSON）
└── summary.json    # 会话摘要
```

**数据模型**（`SessionStep`）：
```python
class SessionStep(BaseModel):
    step_id: int              # 步骤序号
    session_id: str           # 会话 ID
    type: StepType            # user_message/assistant_message/tool_call/tool_result/system_event
    timestamp: datetime       # 时间戳
    content_summary: str      # 内容摘要（200 字符截断）
    raw_uuid: str            # 原始记录 UUID
    parent_uuid: Optional[str]
```

**数据大小估算**：

| 任务类型 | 记录数 | 文件大小 | 加载时间（全量） |
|---------|--------|---------|----------------|
| 简单爬虫 | 50-100 | 10-30KB | 5-10ms |
| 中等自动化 | 200-500 | 50-150KB | 20-50ms |
| 复杂分析 | 1000+ | 200KB+ | 100ms+ |
| 长流程（>1h） | 5000+ | 1MB+ | 500ms+ |

### 2.2 推荐方案

**决策**：后端分页 API + 前端虚拟滚动

**后端扩展** - 新增 `read_steps_paginated()`：
```python
def read_steps_paginated(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """分页读取会话步骤"""
    steps = read_steps(session_id, agent_type)
    total = len(steps)
    return {
        "steps": steps[offset:offset+limit],
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total
    }
```

**前端虚拟滚动** - 基于 IntersectionObserver：
- 仅渲染可见区域（~10 条）
- 滚动到底部自动加载下一页
- 保持滚动位置不丢失

**理由**：
- 分页减少序列化时间：从 250-500ms 降至 20-30ms/页
- 虚拟滚动确保大列表流畅（60fps）
- 内存占用恒定，支持超大会话

**考虑的替代方案**：
- 一次全量加载：大会话（>1MB）卡顿，已拒绝
- 流式传输（NDJSON）：实现复杂，作为 P2 优化

### 2.3 性能阈值决策

| 会话大小 | 加载策略 |
|---------|---------|
| <100KB | 一次加载 |
| 100KB-500KB | 分页（limit=100） |
| 500KB-2MB | 分页（limit=50）+ 虚拟滚动 |
| >2MB | 分页（limit=20）+ 虚拟滚动 + 进度指示 |

---

## 3. 任务状态实时监控

### 3.1 现有架构

**SessionMonitor** 核心机制：
- Watchdog 文件监听：`~/.claude/projects/{encoded_path}/*.jsonl`
- 增量解析：`IncrementalParser` 只处理新增行
- 会话关联：启动时间戳 + 项目路径匹配（10s 窗口）
- 无活动超时：300s 后自动标记为 COMPLETED

**SessionStatus 状态枚举**：
```python
class SessionStatus(str, Enum):
    RUNNING = "running"      # 黄色
    COMPLETED = "completed"  # 绿色
    ERROR = "error"          # 红色
    CANCELLED = "cancelled"  # 红色
```

### 3.2 推荐方案

**决策**：扩展为 SessionMonitorPool 多会话管理

**核心组件设计**：
```python
class SessionMonitorPool:
    """多会话监控池"""
    _monitors: Dict[str, SessionMonitor]     # session_id → monitor
    _active_sessions: Dict[str, MonitoredSession]

    def get_active_sessions(self) -> List[MonitoredSession]:
        """获取所有活跃会话（供 Tasks 页面使用）"""

    def subscribe_session(self, session_id: str, callback: Callable):
        """订阅单个会话更新（供任务详情页使用）"""
```

**GUI API 扩展**：
```python
# api.py 新增方法
def get_tasks(self, limit: int = 50, offset: int = 0) -> Dict:
    """获取任务列表（Tasks 页面）"""
    sessions = list_sessions(limit=limit)
    return {
        "tasks": [self._session_to_task_item(s) for s in sessions],
        "total": count_sessions(),
        "offset": offset,
        "limit": limit
    }

def get_task_detail(self, session_id: str) -> Dict:
    """获取任务详情"""
    session = read_metadata(session_id)
    steps = read_steps_paginated(session_id, limit=50, offset=0)
    return {
        "metadata": session.model_dump(mode="json"),
        "steps": steps
    }

def subscribe_task_updates(self, session_id: str) -> None:
    """订阅任务更新推送"""
    # 建立 watchdog 监听，推送新步骤
```

**理由**：
- 复用现有 SessionMonitor 架构
- 支持多任务并发监控
- 与现有存储机制无缝集成

**考虑的替代方案**：
- 单独的任务队列系统（Redis/RabbitMQ）：过度设计，已拒绝
- 纯轮询任务列表：可行但实时性差，作为降级方案

### 3.3 活跃会话检测

**检测逻辑**：
1. 定期扫描 `~/.frago/sessions/claude/` 目录（5s 间隔）
2. 检查 `metadata.json` 中的 `status` 和 `last_activity`
3. 超过 300s 无活动的 RUNNING 会话自动标记为 COMPLETED

**关键参数**：

| 参数 | 值 | 说明 |
|------|---|------|
| SESSION_MATCH_WINDOW | 10s | 会话关联时间窗口 |
| INACTIVITY_TIMEOUT | 300s | 无活动超时 |
| POLL_INTERVAL | 5s | 任务列表刷新间隔 |

---

## 4. 页面结构与导航设计

### 4.1 现有页面结构

当前 `index.html` 包含 5 个页面：
- `page-home`：主页（输入区 + 输出区）
- `page-recipes`：配方列表
- `page-recipe-detail`：配方详情
- `page-skills`：Skills 列表
- `page-history`：执行历史
- `page-settings`：设置

### 4.2 推荐方案

**决策**：重构为 6 个页面，JavaScript 单页路由

**新页面结构**：
```html
<main class="main-content">
  <section id="page-tips" class="page active">       <!-- 新增：Tips（默认页） -->
  <section id="page-tasks" class="page">             <!-- 重命名：Tasks（原主页） -->
  <section id="page-task-detail" class="page">       <!-- 新增：任务详情 -->
  <section id="page-recipes" class="page">           <!-- 保留 -->
  <section id="page-skills" class="page">            <!-- 保留 -->
  <section id="page-settings" class="page">          <!-- 保留 -->
</main>
```

**导航菜单更新**：
```html
<nav class="nav-tabs">
  <button data-page="tips" class="nav-tab active">Tips</button>    <!-- 默认激活 -->
  <button data-page="tasks" class="nav-tab">Tasks</button>         <!-- 原"主页" -->
  <button data-page="recipes" class="nav-tab">Recipes</button>
  <button data-page="skills" class="nav-tab">Skills</button>
  <button data-page="settings" class="nav-tab">Settings</button>
</nav>
```

**路由状态**：
- 使用 `data-page` 属性标识当前页面
- 任务详情页通过 `data-task-id` 属性绑定会话 ID
- 支持返回按钮保持浏览历史

**理由**：
- 保持单 HTML 文件架构（pywebview 限制）
- 符合现有 `switchPage()` 函数模式
- 最小化改动现有导航代码

---

## 5. 状态颜色与可访问性

### 5.1 决策

**颜色映射**（符合 GitHub Dark 主题）：

| 状态 | 颜色 | CSS 变量 | 说明 |
|------|-----|---------|------|
| RUNNING | 黄色 | `--accent-warning: #d29922` | 进行中 |
| COMPLETED | 绿色 | `--accent-success: #3fb950` | 已完成 |
| ERROR | 红色 | `--accent-error: #f85149` | 出错 |
| CANCELLED | 红色 | `--accent-error: #f85149` | 已取消 |

**可访问性**（FR 边缘案例：色盲用户）：
- 除颜色外，添加图标/文字标签
- 状态指示器样式：圆形 + 文字（如 "● Running"）

### 5.2 CSS 实现

```css
.task-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 12px;
}

.task-status--running {
  background: rgba(210, 153, 34, 0.15);
  color: var(--accent-warning);
}

.task-status--completed {
  background: rgba(63, 185, 80, 0.15);
  color: var(--accent-success);
}

.task-status--error,
.task-status--cancelled {
  background: rgba(248, 81, 73, 0.15);
  color: var(--accent-error);
}

/* 状态图标 */
.task-status::before {
  content: "";
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}
```

---

## 6. Tips 页面内容策略

### 6.1 决策

**根据 FR-013**：Tips 页面内容暂时留空

**空状态设计**：
```html
<section id="page-tips" class="page">
  <div class="empty-state">
    <div class="empty-state__icon">💡</div>
    <h2 class="empty-state__title">Tips</h2>
    <p class="empty-state__description">
      使用技巧和新功能介绍即将推出...
    </p>
  </div>
</section>
```

**未来扩展**：
- 可通过 `~/.frago/tips.json` 或远程 API 加载内容
- 支持 Markdown 渲染
- 版本更新时显示新功能亮点

---

## 7. 实现优先级

| 优先级 | 组件 | 工作量 | 依赖 |
|--------|-----|--------|-----|
| P0 | 后端分页 API | 2h | - |
| P0 | Tasks 页面 UI | 3h | - |
| P0 | 任务状态颜色 | 1h | - |
| P1 | 任务详情页面 | 4h | P0 |
| P1 | 会话内容加载 | 3h | 分页 API |
| P1 | Tips 空状态页 | 1h | - |
| P2 | 虚拟滚动 | 4h | P1 |
| P2 | 实时状态推送 | 3h | P1 |
| P3 | SessionMonitorPool | 6h | P2 |

**总预估工作量**：20-27h

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解策略 |
|------|-----|---------|
| 大会话加载卡顿 | 高 | 分页 + 虚拟滚动 |
| 线程安全竞态 | 中 | 添加异常捕获 + 日志 |
| 状态更新延迟 | 中 | 优化轮询间隔 + 手动刷新 |
| 多会话内存占用 | 低 | 限制并发监控数量 |

---

## 9. 关键文件修改清单

| 文件 | 修改类型 | 内容 |
|-----|---------|-----|
| `gui/api.py` | 扩展 | 新增 `get_tasks()`, `get_task_detail()`, `subscribe_task_updates()` |
| `gui/models.py` | 扩展 | 新增 `TaskItem`, `TaskDetail` 数据类 |
| `gui/assets/index.html` | 重构 | 新增 Tips/Tasks/TaskDetail 页面结构 |
| `gui/assets/scripts/app.js` | 扩展 | 新增页面交互逻辑、虚拟滚动 |
| `gui/assets/styles/main.css` | 扩展 | 任务状态颜色、新页面样式 |
| `session/storage.py` | 扩展 | 新增 `read_steps_paginated()` |
