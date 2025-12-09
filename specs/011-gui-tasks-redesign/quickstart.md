# Quickstart: Frago GUI Tasks Redesign

**Feature Branch**: `011-gui-tasks-redesign`
**Date**: 2025-12-08

## 快速开始

### 1. 环境准备

```bash
# 确保在项目根目录
cd /Users/chagee/Repos/frago

# 确保虚拟环境激活
uv sync

# 检查 GUI 依赖
uv run frago gui-deps --check
```

### 2. 启动 GUI

```bash
# 启动 GUI（开发模式）
uv run frago gui --debug

# 或通过 --gui 标志
uv run frago --gui
```

### 3. 验证功能

启动后，您应该看到：

1. **默认显示 Tips 页面** - 带有空状态提示
2. **导航菜单** - Tips | Tasks | Recipes | Skills | Settings
3. **点击 Tasks** - 显示任务列表（如果有运行过的 frago agent）

---

## 关键文件修改清单

### 后端文件

| 文件 | 修改类型 | 说明 |
|-----|---------|------|
| `src/frago/gui/api.py` | 扩展 | 新增 `get_tasks()`, `get_task_detail()`, `get_task_steps()`, `subscribe_task_updates()` |
| `src/frago/gui/models.py` | 扩展 | 新增 `TaskItem`, `TaskDetail`, `TaskStep`, `TaskSummary`, `TaskStatus` |
| `src/frago/session/storage.py` | 扩展 | 新增 `read_steps_paginated()`, `count_sessions()` |

### 前端文件

| 文件 | 修改类型 | 说明 |
|-----|---------|------|
| `src/frago/gui/assets/index.html` | 重构 | 新增 Tips/Tasks/TaskDetail 页面结构，更新导航 |
| `src/frago/gui/assets/scripts/app.js` | 扩展 | 新增页面交互：`loadTasks()`, `openTaskDetail()`, `loadMoreSteps()` |
| `src/frago/gui/assets/styles/main.css` | 扩展 | 任务状态颜色样式，新页面布局 |

---

## 开发指南

### 1. 后端 API 开发

#### 1.1 添加新的 GUI API 方法

```python
# src/frago/gui/api.py

def get_tasks(self, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """获取任务列表

    Args:
        limit: 每页数量 (1-100)
        offset: 偏移量

    Returns:
        {tasks: [...], total: int, offset: int, limit: int, has_more: bool}
    """
    # 参数验证
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    # 获取会话列表
    from frago.session.storage import list_sessions, count_sessions

    sessions = list_sessions(limit=limit + offset)
    total = count_sessions()

    # 转换并返回
    tasks = [TaskItem.from_session(s).model_dump(mode="json") for s in sessions[offset:]][:limit]

    return {
        "tasks": tasks,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(tasks) < total,
    }
```

#### 1.2 添加分页读取步骤

```python
# src/frago/session/storage.py

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
```

### 2. 前端开发

#### 2.1 添加新页面

```html
<!-- src/frago/gui/assets/index.html -->

<!-- Tips 页面（默认） -->
<section id="page-tips" class="page active">
  <div class="empty-state">
    <div class="empty-state__icon">💡</div>
    <h2 class="empty-state__title">Tips</h2>
    <p class="empty-state__description">使用技巧和新功能介绍即将推出...</p>
  </div>
</section>

<!-- Tasks 页面 -->
<section id="page-tasks" class="page">
  <div class="page-header">
    <h1>Tasks</h1>
    <button onclick="refreshTasks()" class="btn-icon" title="刷新">🔄</button>
  </div>
  <div id="tasks-list" class="tasks-list">
    <!-- 任务列表动态生成 -->
  </div>
  <div id="tasks-empty" class="empty-state" style="display: none;">
    <p>暂无任务记录</p>
  </div>
</section>

<!-- 任务详情页 -->
<section id="page-task-detail" class="page">
  <div class="page-header">
    <button onclick="backToTasks()" class="btn-back">← 返回</button>
    <h1 id="task-detail-title">任务详情</h1>
  </div>
  <div id="task-detail-content">
    <!-- 详情内容动态生成 -->
  </div>
</section>
```

#### 2.2 添加 JavaScript 交互

```javascript
// src/frago/gui/assets/scripts/app.js

// 全局状态
let currentTaskId = null;
let tasksScrollPosition = 0;

// 加载任务列表
async function loadTasks() {
  const response = await pywebview.api.get_tasks(50, 0);
  const container = document.getElementById('tasks-list');
  const emptyState = document.getElementById('tasks-empty');

  if (response.tasks.length === 0) {
    container.style.display = 'none';
    emptyState.style.display = 'block';
    return;
  }

  container.style.display = 'block';
  emptyState.style.display = 'none';

  container.innerHTML = response.tasks.map(task => `
    <div class="task-card" onclick="openTaskDetail('${task.session_id}')">
      <div class="task-card__header">
        <span class="task-status task-status--${task.status}">
          ${getStatusIcon(task.status)} ${getStatusLabel(task.status)}
        </span>
        <span class="task-card__time">${formatTime(task.started_at)}</span>
      </div>
      <div class="task-card__name">${escapeHtml(task.name)}</div>
      <div class="task-card__stats">
        <span>📝 ${task.step_count} 步骤</span>
        <span>🔧 ${task.tool_call_count} 工具调用</span>
      </div>
    </div>
  `).join('');
}

// 打开任务详情
async function openTaskDetail(sessionId) {
  // 保存滚动位置
  tasksScrollPosition = document.getElementById('tasks-list').scrollTop;

  currentTaskId = sessionId;
  switchPage('task_detail');

  const response = await pywebview.api.get_task_detail(sessionId);
  if (response.error) {
    showToast(response.error, 'error');
    return;
  }

  renderTaskDetail(response.task);

  // 如果任务正在运行，订阅更新
  if (response.task.status === 'running') {
    await pywebview.api.subscribe_task_updates(sessionId);
  }
}

// 返回任务列表
function backToTasks() {
  // 取消订阅
  if (currentTaskId) {
    pywebview.api.unsubscribe_task_updates(currentTaskId);
  }
  currentTaskId = null;

  switchPage('tasks');

  // 恢复滚动位置
  document.getElementById('tasks-list').scrollTop = tasksScrollPosition;
}

// 渲染任务详情
function renderTaskDetail(task) {
  const container = document.getElementById('task-detail-content');
  document.getElementById('task-detail-title').textContent = task.name;

  container.innerHTML = `
    <div class="task-detail__info">
      <div class="task-detail__status task-status--${task.status}">
        ${getStatusIcon(task.status)} ${getStatusLabel(task.status)}
      </div>
      <div class="task-detail__meta">
        <span>开始: ${formatTime(task.started_at)}</span>
        ${task.ended_at ? `<span>结束: ${formatTime(task.ended_at)}</span>` : ''}
        <span>耗时: ${formatDuration(task.duration_ms)}</span>
      </div>
      <div class="task-detail__stats">
        <span>步骤: ${task.step_count}</span>
        <span>工具调用: ${task.tool_call_count}</span>
        <span>用户消息: ${task.user_message_count}</span>
        <span>助手消息: ${task.assistant_message_count}</span>
      </div>
    </div>
    <div class="task-detail__steps" id="task-steps">
      ${renderSteps(task.steps)}
    </div>
    ${task.has_more_steps ? `
      <button class="btn-load-more" onclick="loadMoreSteps()">加载更多</button>
    ` : ''}
  `;
}

// 渲染步骤列表
function renderSteps(steps) {
  return steps.map(step => `
    <div class="step step--${step.type}">
      <div class="step__header">
        <span class="step__number">#${step.step_id}</span>
        <span class="step__type">${getStepTypeLabel(step.type)}</span>
        <span class="step__time">${formatTime(step.timestamp)}</span>
      </div>
      <div class="step__content">${escapeHtml(step.content)}</div>
    </div>
  `).join('');
}

// 处理任务更新推送
window.handleTaskUpdate = function(payload) {
  const { session_id, event, data } = payload;

  if (session_id !== currentTaskId) return;

  switch (event) {
    case 'step_added':
      appendStep(data.step);
      break;
    case 'status_changed':
      updateTaskStatus(data.status);
      break;
    case 'task_completed':
      updateTaskStatus('completed');
      showSummary(data.summary);
      break;
  }
};

// 辅助函数
function getStatusIcon(status) {
  const icons = { running: '●', completed: '✓', error: '✗', cancelled: '○' };
  return icons[status] || '?';
}

function getStatusLabel(status) {
  const labels = { running: '进行中', completed: '已完成', error: '出错', cancelled: '已取消' };
  return labels[status] || status;
}

function getStepTypeLabel(type) {
  const labels = {
    user_message: '用户',
    assistant_message: '助手',
    tool_call: '工具调用',
    tool_result: '工具结果',
    system_event: '系统'
  };
  return labels[type] || type;
}
```

#### 2.3 添加样式

```css
/* src/frago/gui/assets/styles/main.css */

/* 任务状态颜色 */
.task-status--running {
  color: var(--accent-warning);
  background: rgba(210, 153, 34, 0.15);
}

.task-status--completed {
  color: var(--accent-success);
  background: rgba(63, 185, 80, 0.15);
}

.task-status--error,
.task-status--cancelled {
  color: var(--accent-error);
  background: rgba(248, 81, 73, 0.15);
}

/* 任务卡片 */
.task-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
  margin-bottom: var(--spacing-sm);
  cursor: pointer;
  transition: var(--transition-fast);
}

.task-card:hover {
  border-color: var(--accent-primary);
  background: var(--bg-tertiary);
}

.task-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-xs);
}

.task-card__name {
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: var(--spacing-xs);
}

.task-card__stats {
  display: flex;
  gap: var(--spacing-md);
  font-size: 12px;
  color: var(--text-secondary);
}

/* 任务详情 */
.task-detail__info {
  background: var(--bg-card);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
  margin-bottom: var(--spacing-md);
}

.task-detail__status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 16px;
  font-size: 14px;
  margin-bottom: var(--spacing-sm);
}

/* 步骤列表 */
.step {
  background: var(--bg-card);
  border-left: 3px solid var(--border-color);
  padding: var(--spacing-sm) var(--spacing-md);
  margin-bottom: var(--spacing-xs);
}

.step--user_message {
  border-left-color: var(--accent-primary);
}

.step--assistant_message {
  border-left-color: var(--accent-success);
}

.step--tool_call,
.step--tool_result {
  border-left-color: var(--accent-warning);
}

.step__header {
  display: flex;
  gap: var(--spacing-md);
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: var(--spacing-xs);
}

.step__content {
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}
```

---

## 测试指南

### 1. 手动测试流程

```bash
# 1. 启动 GUI
uv run frago gui --debug

# 2. 在另一个终端运行一个 agent 任务
uv run frago agent "帮我查看项目结构"

# 3. 在 GUI 中验证：
#    - Tasks 页面显示新任务
#    - 状态为黄色（进行中）
#    - 点击进入详情页，看到实时更新的步骤
#    - 任务完成后状态变绿
```

### 2. API 测试

```python
# tests/unit/gui/test_api.py

def test_get_tasks_empty():
    """测试空任务列表"""
    api = FragoGuiApi()
    result = api.get_tasks()
    assert result["tasks"] == []
    assert result["total"] == 0

def test_get_tasks_with_sessions():
    """测试有任务时的列表"""
    # 需要先创建测试会话
    ...

def test_get_task_detail_not_found():
    """测试任务不存在"""
    api = FragoGuiApi()
    result = api.get_task_detail("nonexistent")
    assert "error" in result
```

---

## 调试技巧

### 1. 查看会话存储

```bash
# 查看会话目录
ls -la ~/.frago/sessions/claude/

# 查看单个会话元数据
cat ~/.frago/sessions/claude/<session_id>/metadata.json | jq

# 查看步骤日志
head -20 ~/.frago/sessions/claude/<session_id>/steps.jsonl
```

### 2. 开启调试日志

```bash
# 设置日志级别
export FRAGO_LOG_LEVEL=DEBUG
uv run frago gui --debug
```

### 3. 浏览器开发者工具

在 GUI 窗口中右键选择"Inspect Element"（需要 --debug 模式），可以：
- 查看 Console 日志
- 调试 JavaScript 代码
- 检查网络请求

---

## 常见问题

### Q: Tasks 页面不显示任何任务？

**A**: 检查会话目录是否存在：
```bash
ls ~/.frago/sessions/claude/
```
如果为空，说明还没有运行过 `frago agent` 命令。

### Q: 任务状态不更新？

**A**: 确保使用了最新版本的代码，并且 session/monitor.py 正在正确写入 metadata.json。

### Q: 详情页步骤加载很慢？

**A**: 对于大型会话（>1000 步骤），考虑使用虚拟滚动。查看 research.md 中的性能优化建议。

---

## 相关文档

- [spec.md](./spec.md) - 功能规格说明
- [research.md](./research.md) - 技术研究
- [data-model.md](./data-model.md) - 数据模型
- [contracts/gui-api.md](./contracts/gui-api.md) - API 契约
