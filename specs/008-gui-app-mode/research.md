# Research: Frago GUI 应用模式

**Feature**: 008-gui-app-mode
**Date**: 2025-12-04

## 1. 框架选择：pywebview

### 决策

**选择 pywebview 6.1** 作为 GUI 框架。

### 理由

1. **轻量级**：不捆绑浏览器引擎，使用系统原生 WebView（WinForms/Cocoa/GTK/QT）
2. **Python 原生**：纯 Python 包，`pip install pywebview` 即可
3. **无边框支持**：原生支持 `frameless=True` 和 `easy_drag=True`
4. **双向通信**：内置 JS ↔ Python 桥接，无需额外配置
5. **活跃维护**：5.6k stars，最新版本 6.1（2025年10月）
6. **跨平台**：Linux、macOS、Windows、Android

### 考虑的替代方案

| 框架 | 评估结果 | 不选择原因 |
|------|----------|-----------|
| Electron + Python | ❌ | 包体积大（100MB+），需要 Node.js 环境 |
| Tauri + Python | ⚠️ | Rust 依赖，构建复杂，Python 集成不成熟 |
| PySide6 WebEngine | ⚠️ | Qt 依赖重（200MB+），许可证复杂 |
| Tkinter + tkhtmlview | ❌ | HTML/CSS 支持有限，无法实现现代 UI |
| NiceGUI | ⚠️ | 基于 web 服务器，非原生窗口 |

## 2. pywebview 核心机制

### 2.1 窗口创建

```python
import webview

# 无边框窗口，可拖动
window = webview.create_window(
    title='Frago GUI',
    url='index.html',  # 或 HTML 字符串
    width=600,
    height=1434,
    frameless=True,
    easy_drag=True,
    resizable=False,  # 固定尺寸
)
webview.start()
```

### 2.2 Python → JavaScript 通信

```python
# 执行 JS 代码并获取返回值
result = window.evaluate_js('document.title')

# 执行 JS 代码（无返回值）
window.run_js('console.log("Hello from Python")')
```

### 2.3 JavaScript → Python 通信

**方式一：js_api 参数（推荐）**

```python
class Api:
    def get_recipes(self):
        """返回配方列表"""
        return [{"name": "recipe1"}, {"name": "recipe2"}]

    def run_agent(self, prompt):
        """调用 frago agent"""
        # 返回 Promise 结果
        return {"status": "ok", "response": "..."}

window = webview.create_window('Frago', 'index.html', js_api=Api())
```

```javascript
// JavaScript 端调用
window.addEventListener('pywebviewready', async () => {
    const recipes = await pywebview.api.get_recipes();
    console.log(recipes);
});
```

**方式二：动态暴露（运行时）**

```python
def on_loaded():
    window.expose(some_function)  # 动态添加 API

webview.start(func=on_loaded)
```

### 2.4 共享状态

```python
# Python 端
window.state.update({'theme': 'dark', 'connected': True})

# JavaScript 端自动同步
console.log(pywebview.state.theme);  // 'dark'
```

## 3. 前端技术栈选择

### 决策

**使用原生 HTML/CSS/JavaScript**，不引入前端框架。

### 理由

1. **简单性**：GUI 页面数量少（4个），复杂度可控
2. **零依赖**：无需 npm/打包工具，资源文件直接嵌入
3. **加载速度**：无框架初始化开销，符合 <5s 启动目标
4. **维护成本**：团队已有 Python 技术栈，避免 JS 框架学习曲线

### 考虑的替代方案

| 方案 | 不选择原因 |
|------|-----------|
| Vue.js | 需要打包工具，增加构建复杂度 |
| React | 同上，且包体积较大 |
| Alpine.js | 可考虑作为后期优化，当前不必要 |
| HTMX | 适合服务端渲染，此场景不匹配 |

## 4. 关键技术点

### 4.1 stream-json 解析

`frago agent` 返回 stream-json 格式（每行一个 JSON）。前端需要：

```javascript
// 使用 fetch + ReadableStream 处理流式响应
async function streamAgent(prompt) {
    const response = await pywebview.api.run_agent_stream(prompt);
    // Python 端通过 evaluate_js 推送增量更新
}

// 或 Python 主动推送
window.evaluate_js(f'appendMessage({json.dumps(data)})')
```

### 4.2 任务单例控制

```python
class AppState:
    _current_task = None
    _lock = threading.Lock()

    def start_task(self, task):
        with self._lock:
            if self._current_task:
                raise TaskAlreadyRunningError()
            self._current_task = task
```

### 4.3 配置持久化

```python
from pathlib import Path

CONFIG_DIR = Path.home() / '.frago'
CONFIG_FILE = CONFIG_DIR / 'gui_config.json'

def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return DEFAULT_CONFIG
```

### 4.4 会话上下文（从 ~/.claude 提取）

```python
CLAUDE_DIR = Path.home() / '.claude'

def get_session_context():
    # 读取 Claude Code 的项目上下文
    projects_file = CLAUDE_DIR / 'projects.json'
    if projects_file.exists():
        return json.loads(projects_file.read_text())
    return {}
```

## 5. 跨平台兼容性

### Linux

- 后端选项：GTK（默认）或 QT
- 依赖：`pip install pywebview[gtk]` 或 `pip install pywebview[qt]`
- 系统依赖：`webkit2gtk` (GTK) 或 `PyQtWebEngine` (QT)

### macOS

- 后端：Cocoa（系统自带 WebKit）
- 无额外依赖

### Windows

- 后端：WinForms + EdgeChromium（默认）或 MSHTML
- 无额外依赖（Edge 已预装）

### Headless 环境检测

```python
import os

def can_start_gui():
    """检测是否支持 GUI"""
    if os.environ.get('DISPLAY') is None and os.name == 'posix':
        # Linux 无显示器
        return False
    return True
```

## 6. 安装依赖

### pyproject.toml 更新

```toml
[project.optional-dependencies]
gui = [
    "pywebview>=6.1",
]

# Linux GTK 后端
gui-gtk = [
    "pywebview[gtk]>=6.1",
]

# Linux QT 后端
gui-qt = [
    "pywebview[qt]>=6.1",
]
```

### 安装命令

```bash
# 基本安装（使用系统默认 WebView）
pip install frago-cli[gui]

# Linux GTK 后端
pip install frago-cli[gui-gtk]

# Linux QT 后端
pip install frago-cli[gui-qt]
```

## 7. 未解决问题

| 问题 | 状态 | 建议 |
|------|------|------|
| Linux WebView 后端选择（GTK vs QT） | 待确认 | 默认 GTK，提供 QT 可选 |
| Toast 通知实现 | 待设计 | 使用 CSS 动画 + JS 定时器 |
| 窗口关闭确认对话框 | 待设计 | 使用 pywebview 原生对话框 |

## 参考资源

- [pywebview 官方文档](https://pywebview.flowrl.com/)
- [pywebview GitHub](https://github.com/r0x0r/pywebview)
- [Frameless 窗口示例](https://pywebview.flowrl.com/examples/frameless.html)
- [JS-Python 桥接指南](https://pywebview.flowrl.com/guide/interdomain.html)
