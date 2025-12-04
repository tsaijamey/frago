# API Contract: JavaScript ↔ Python Bridge

**Feature**: 008-gui-app-mode
**Date**: 2025-12-04

## 概述

Frago GUI 使用 pywebview 的双向通信机制实现前端（JavaScript）与后端（Python）的交互。

- **Python → JS**: `window.evaluate_js()` / `window.run_js()`
- **JS → Python**: `pywebview.api.<method>()` (Promise-based)

## 1. Python API 类定义

### 1.1 完整 API 类

```python
class FragoGuiApi:
    """暴露给 JavaScript 的 Python API"""

    # === 配方管理 ===

    def get_recipes(self) -> List[Dict]:
        """获取配方列表

        Returns:
            [{"name": str, "description": str, "category": str, "tags": [str]}]
        """
        pass

    def run_recipe(self, name: str, params: Optional[Dict] = None) -> Dict:
        """执行配方

        Args:
            name: 配方名称
            params: 可选参数

        Returns:
            {"status": "ok"|"error", "output": str, "error": str|None}
        """
        pass

    # === Skills 管理 ===

    def get_skills(self) -> List[Dict]:
        """获取技能列表

        Returns:
            [{"name": str, "description": str, "file_path": str}]
        """
        pass

    # === Agent 交互 ===

    def run_agent(self, prompt: str) -> str:
        """调用 frago agent（阻塞式）

        Args:
            prompt: 用户输入

        Returns:
            task_id: 任务 ID，用于后续查询

        Raises:
            TaskAlreadyRunningError: 已有任务运行中
        """
        pass

    def cancel_agent(self) -> Dict:
        """取消当前运行的 agent 任务

        Returns:
            {"status": "ok"|"error", "message": str}
        """
        pass

    def get_task_status(self) -> Dict:
        """获取当前任务状态

        Returns:
            {"status": "idle"|"running"|"completed"|"error",
             "progress": float,
             "task_id": str|None}
        """
        pass

    # === 历史记录 ===

    def get_history(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        """获取命令历史

        Args:
            limit: 返回条数
            offset: 偏移量

        Returns:
            [{"id": str, "timestamp": str, "input_text": str,
              "status": str, "output": str}]
        """
        pass

    def clear_history(self) -> Dict:
        """清空历史记录

        Returns:
            {"status": "ok", "cleared_count": int}
        """
        pass

    # === 配置管理 ===

    def get_config(self) -> Dict:
        """获取用户配置

        Returns:
            UserConfig 的 dict 形式
        """
        pass

    def update_config(self, config: Dict) -> Dict:
        """更新用户配置

        Args:
            config: 要更新的配置项

        Returns:
            {"status": "ok"|"error", "config": Dict}
        """
        pass

    # === 系统状态 ===

    def get_system_status(self) -> Dict:
        """获取系统状态

        Returns:
            {"cpu_percent": float,
             "memory_percent": float,
             "chrome_connected": bool}
        """
        pass

    def check_connection(self) -> Dict:
        """检查连接状态

        Returns:
            {"connected": bool, "message": str}
        """
        pass

    # === 窗口操作 ===

    def minimize_window(self) -> None:
        """最小化窗口"""
        pass

    def close_window(self, force: bool = False) -> Dict:
        """关闭窗口

        Args:
            force: 是否强制关闭（跳过确认）

        Returns:
            {"should_close": bool, "has_running_task": bool}
        """
        pass
```

## 2. JavaScript 调用示例

### 2.1 初始化

```javascript
// 等待 pywebview API 就绪
window.addEventListener('pywebviewready', () => {
    initApp();
});

async function initApp() {
    // 加载配置
    const config = await pywebview.api.get_config();
    applyTheme(config.theme);

    // 加载配方列表
    const recipes = await pywebview.api.get_recipes();
    renderRecipeList(recipes);

    // 加载技能列表
    const skills = await pywebview.api.get_skills();
    renderSkillList(skills);

    // 加载历史记录
    const history = await pywebview.api.get_history(50, 0);
    renderHistory(history);
}
```

### 2.2 执行 Agent

```javascript
async function sendMessage(prompt) {
    try {
        // 检查是否有运行中的任务
        const status = await pywebview.api.get_task_status();
        if (status.status === 'running') {
            showToast('已有任务运行中，请等待完成', 'warning');
            return;
        }

        // 启动任务
        const taskId = await pywebview.api.run_agent(prompt);
        showProgress(true);

        // 轮询状态（或由 Python 主动推送）
        pollTaskStatus(taskId);

    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function pollTaskStatus(taskId) {
    const status = await pywebview.api.get_task_status();

    if (status.status === 'running') {
        updateProgress(status.progress);
        setTimeout(() => pollTaskStatus(taskId), 500);
    } else if (status.status === 'completed') {
        showProgress(false);
        refreshHistory();
    } else if (status.status === 'error') {
        showProgress(false);
        showToast(status.error, 'error');
    }
}
```

### 2.3 执行配方

```javascript
async function runRecipe(recipeName) {
    try {
        const result = await pywebview.api.run_recipe(recipeName);

        if (result.status === 'ok') {
            appendOutput(result.output);
        } else {
            showToast(result.error, 'error');
        }
    } catch (error) {
        showToast(error.message, 'error');
    }
}
```

## 3. Python → JavaScript 推送

### 3.1 流式消息推送

```python
def push_stream_message(self, message: StreamMessage):
    """推送流式消息到前端"""
    js_code = f'''
        window.handleStreamMessage({json.dumps(asdict(message))});
    '''
    self.window.evaluate_js(js_code)
```

### 3.2 进度更新

```python
def update_progress(self, progress: float, step: str = ""):
    """更新任务进度"""
    js_code = f'''
        window.updateProgress({progress}, "{step}");
    '''
    self.window.evaluate_js(js_code)
```

### 3.3 Toast 通知

```python
def show_toast(self, message: str, type: str = "info"):
    """显示 Toast 通知

    Args:
        message: 消息内容
        type: "info" | "success" | "warning" | "error"
    """
    js_code = f'''
        window.showToast("{message}", "{type}");
    '''
    self.window.evaluate_js(js_code)
```

## 4. JavaScript 全局处理函数

```javascript
// 必须在 window 对象上定义，供 Python 调用

window.handleStreamMessage = function(message) {
    // message: {type, content, timestamp, metadata, progress, step}
    const output = document.getElementById('output');

    if (message.type === 'assistant') {
        appendAssistantMessage(message.content);
    } else if (message.type === 'progress') {
        updateProgressBar(message.progress, message.step);
    } else if (message.type === 'error') {
        showError(message.content);
    }
};

window.updateProgress = function(progress, step) {
    const bar = document.getElementById('progress-bar');
    bar.style.width = `${progress * 100}%`;
    document.getElementById('progress-step').textContent = step;
};

window.showToast = function(message, type) {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => toast.remove(), 3000);
};
```

## 5. 错误处理

### 5.1 Python 端异常

```python
class GuiApiError(Exception):
    """GUI API 异常基类"""
    pass

class TaskAlreadyRunningError(GuiApiError):
    """已有任务运行中"""
    pass

class RecipeNotFoundError(GuiApiError):
    """配方不存在"""
    pass

class ConfigValidationError(GuiApiError):
    """配置验证失败"""
    pass
```

### 5.2 JavaScript 端处理

```javascript
async function safeApiCall(apiMethod, ...args) {
    try {
        return await apiMethod(...args);
    } catch (error) {
        // pywebview 将 Python 异常包装为 Error 对象
        console.error('API Error:', error.message);
        console.error('Stack:', error.stack);

        // 显示用户友好的错误消息
        showToast(error.message, 'error');
        return null;
    }
}
```

## 6. 类型定义（TypeScript 风格注释）

```typescript
// 仅供文档参考，实际使用原生 JS

interface Recipe {
    name: string;
    description: string | null;
    category: 'atomic' | 'workflow';
    tags: string[];
}

interface Skill {
    name: string;
    description: string | null;
    file_path: string;
}

interface TaskStatus {
    status: 'idle' | 'running' | 'completed' | 'error';
    progress: number;  // 0.0 - 1.0
    task_id: string | null;
    error?: string;
}

interface CommandRecord {
    id: string;
    timestamp: string;  // ISO 8601
    input_text: string;
    status: 'completed' | 'error' | 'cancelled';
    duration_ms?: number;
    output?: string;
    error?: string;
}

interface UserConfig {
    theme: 'dark' | 'light';
    font_size: number;
    show_system_status: boolean;
    confirm_on_exit: boolean;
    auto_scroll_output: boolean;
    max_history_items: number;
    shortcuts: Record<string, string>;
}

interface SystemStatus {
    cpu_percent: number;
    memory_percent: number;
    chrome_connected: boolean;
}
```
