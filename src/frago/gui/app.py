"""Frago GUI Application.

Main application class for the Frago GUI using pywebview.
"""

import os
import platform
import sys
from pathlib import Path
from typing import Optional

# 延迟导入 webview，在 start_gui() 中依赖检查通过后再导入
webview = None


def _lazy_import_webview():
    """延迟导入 webview，避免在依赖检查前触发后端加载."""
    global webview
    if webview is None:
        import webview as _webview
        webview = _webview
    return webview


def _get_install_instructions() -> str:
    """Get platform-specific installation instructions."""
    system = platform.system()

    if system == "Linux":
        # 检测发行版
        try:
            with open("/etc/os-release") as f:
                os_info = f.read().lower()
        except FileNotFoundError:
            os_info = ""

        if "ubuntu" in os_info or "debian" in os_info:
            return """
请运行以下命令安装 GUI 依赖：

    sudo apt install -y python3-gi python3-gi-cairo gir1.2-webkit2-4.1
    pip install pywebview

或者一键安装（需要编译）：

    sudo apt install -y libcairo2-dev libgirepository1.0-dev \\
        libgirepository-2.0-dev gir1.2-webkit2-4.1 python3-dev
    pip install pywebview PyGObject
"""
        elif "fedora" in os_info or "rhel" in os_info or "centos" in os_info:
            return """
请运行以下命令安装 GUI 依赖：

    sudo dnf install -y python3-gobject python3-gobject-base webkit2gtk4.1
    pip install pywebview
"""
        elif "arch" in os_info:
            return """
请运行以下命令安装 GUI 依赖：

    sudo pacman -S python-gobject webkit2gtk-4.1
    pip install pywebview
"""
        else:
            return """
请安装以下依赖：
    - PyGObject (python3-gi)
    - WebKit2GTK (gir1.2-webkit2-4.1)
    - pywebview

然后运行: pip install pywebview
"""
    elif system == "Darwin":
        return """
请运行以下命令安装 GUI 依赖：

    pip install pywebview
"""
    elif system == "Windows":
        return """
请运行以下命令安装 GUI 依赖：

    pip install pywebview

推荐安装 Edge WebView2 Runtime 以获得更好的性能：
    下载地址: https://developer.microsoft.com/en-us/microsoft-edge/webview2/

或使用 winget:
    winget install Microsoft.EdgeWebView2Runtime
"""
    else:
        return "请安装 pywebview: pip install pywebview"

from frago.gui.exceptions import GuiNotAvailableError
from frago.gui.models import WindowConfig
from frago.gui.utils import can_start_gui, get_asset_path, get_gui_unavailable_reason, is_debug_mode


class FragoGuiApp:
    """Frago GUI Application class."""

    def __init__(
        self,
        config: Optional[WindowConfig] = None,
        debug: bool = False,
    ) -> None:
        """Initialize the GUI application.

        Args:
            config: Window configuration. Uses defaults if not provided.
            debug: Enable debug mode (developer tools, verbose logging).
        """
        if webview is None:
            raise ImportError(
                "pywebview is not installed. Install with: pip install frago-cli[gui]"
            )

        self.config = config or WindowConfig()
        self.debug = debug or is_debug_mode()
        self.window: Optional["webview.Window"] = None
        self._api: Optional["FragoGuiApi"] = None
        self._http_server: Optional["HTTPServer"] = None

    def _calculate_window_size(self) -> tuple[int, int]:
        """Calculate window size based on screen dimensions.

        Returns:
            Tuple of (width, height) calculated as 80% of screen height
            with the original aspect ratio (600:1434 ≈ 1:2.39).
        """
        # 原始宽高比
        original_width = 600
        original_height = 1434
        aspect_ratio = original_width / original_height

        try:
            screens = webview.screens
            if screens:
                # 获取主屏幕（第一个屏幕）
                primary_screen = screens[0]
                screen_height = primary_screen.height
                screen_width = primary_screen.width

                # 计算目标高度为屏幕高度的 80%
                target_height = int(screen_height * 0.8)
                target_width = int(target_height * aspect_ratio)

                # 确保宽度不超过屏幕宽度的 90%
                max_width = int(screen_width * 0.9)
                if target_width > max_width:
                    target_width = max_width
                    target_height = int(target_width / aspect_ratio)

                # 确保不小于最小尺寸
                target_width = max(target_width, self.config.min_width)
                target_height = max(target_height, self.config.min_height)

                return target_width, target_height
        except Exception:
            # 如果获取屏幕信息失败，使用默认值
            pass

        return original_width, original_height

    def _is_dev_mode(self) -> bool:
        """Check if running in development mode.

        Development mode is enabled by setting FRAGO_GUI_DEV=1 environment variable.
        In dev mode, the frontend is loaded from Vite dev server.

        Returns:
            True if in development mode.
        """
        return os.getenv("FRAGO_GUI_DEV") == "1"

    def _check_dev_server(self) -> bool:
        """Check if Vite dev server is running.

        Returns:
            True if dev server is accessible.
        """
        import socket

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(("localhost", 5173))
            sock.close()
            return result == 0
        except Exception:
            return False

    def _start_static_server(self) -> int:
        """Start a local HTTP server for serving static files.

        WebKit2GTK cannot load external JS files via file:// protocol due to
        security restrictions. This method starts a simple HTTP server to
        serve the built assets.

        Returns:
            Port number the server is running on.
        """
        import socket
        import threading
        from http.server import HTTPServer, SimpleHTTPRequestHandler

        assets_dir = str(get_asset_path(""))

        # Find an available port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            port = s.getsockname()[1]

        # Create a handler that serves from assets directory and suppresses logs
        class QuietHandler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=assets_dir, **kwargs)

            def log_message(self, format, *args):
                pass

        self._http_server = HTTPServer(("127.0.0.1", port), QuietHandler)

        # Run server in background thread
        thread = threading.Thread(target=self._http_server.serve_forever, daemon=True)
        thread.start()

        return port

    def _get_url(self) -> str:
        """Get the URL to load based on dev/prod mode.

        Returns:
            URL string for the GUI.
        """
        if self._is_dev_mode():
            # 开发模式：检查 Vite 服务器是否运行
            if not self._check_dev_server():
                import logging

                logger = logging.getLogger(__name__)
                logger.warning(
                    "Vite 开发服务器未运行。请先运行: cd src/frago/gui/frontend && npm run dev"
                )
                # 返回错误页面
                return self._get_dev_server_error_html()
            return "http://localhost:5173"

        # 生产模式：使用内置 HTTP 服务器提供静态文件
        # WebKit2GTK 无法在 file:// 协议下加载外部 JS 文件
        index_path = get_asset_path("index.html")
        if index_path.exists():
            port = self._start_static_server()
            return f"http://127.0.0.1:{port}/index.html"
        else:
            return self._get_build_missing_html()

    def create_window(self) -> "webview.Window":
        """Create the GUI window.

        Returns:
            webview.Window instance.
        """
        from frago.gui.api import FragoGuiApi

        self._api = FragoGuiApi()
        url = self._get_url()

        # 动态计算窗口尺寸
        width, height = self._calculate_window_size()

        self.window = webview.create_window(
            title=self.config.title,
            url=url,
            width=width,
            height=height,
            frameless=self.config.frameless,
            resizable=self.config.resizable,
            min_size=(self.config.min_width, self.config.min_height),
            easy_drag=self.config.easy_drag,
            x=self.config.x,
            y=self.config.y,
            js_api=self._api,
            confirm_close=False,  # 禁用确认，使用原生窗口行为
        )

        self.window.events.closing += self._on_closing
        self._api.set_window(self.window)
        return self.window

    def _on_closing(self) -> bool:
        """Handle window closing event.

        由于使用原生窗口标题栏且不需要确认，总是允许关闭。

        Returns:
            True to allow closing.
        """
        # 使用原生窗口标题栏，不需要确认，总是允许关闭
        import logging
        logger = logging.getLogger(__name__)
        logger.debug("窗口关闭事件触发，允许关闭")
        return True

    def _get_error_html(self, title: str, message: str, hint: str = "") -> str:
        """Get error page HTML.

        Args:
            title: Error title.
            message: Error message.
            hint: Optional hint for resolution.

        Returns:
            HTML string for error page.
        """
        hint_html = f'<p class="hint">{hint}</p>' if hint else ""
        return f"""data:text/html,
        <!DOCTYPE html>
        <html data-theme="dark">
        <head>
            <meta charset="UTF-8">
            <title>frago - Error</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #0d1117;
                    color: #e6edf3;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                }}
                .container {{
                    text-align: center;
                    padding: 40px;
                    max-width: 500px;
                }}
                h1 {{
                    color: #f85149;
                    margin-bottom: 20px;
                    font-size: 24px;
                }}
                p {{
                    color: #8b949e;
                    line-height: 1.6;
                }}
                .hint {{
                    background: #161b22;
                    border: 1px solid #30363d;
                    border-radius: 6px;
                    padding: 16px;
                    margin-top: 20px;
                    font-family: 'SF Mono', Monaco, Consolas, monospace;
                    font-size: 13px;
                    text-align: left;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>{title}</h1>
                <p>{message}</p>
                {hint_html}
            </div>
        </body>
        </html>
        """

    def _get_dev_server_error_html(self) -> str:
        """Get HTML for dev server not running error."""
        return self._get_error_html(
            title="开发服务器未运行",
            message="Vite 开发服务器无法连接。请先启动开发服务器。",
            hint="cd src/frago/gui/frontend && npm run dev",
        )

    def _get_build_missing_html(self) -> str:
        """Get HTML for missing build output error."""
        return self._get_error_html(
            title="构建产物缺失",
            message="前端构建产物未找到。请先构建前端。",
            hint="cd src/frago/gui/frontend && npm run build",
        )

    def _get_fallback_html(self) -> str:
        """Get fallback HTML content when index.html is not found.

        Returns:
            HTML string for fallback content.
        """
        return """data:text/html,
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>frago</title>
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #0d1117;
                    color: #e6edf3;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                }
                .container {
                    text-align: center;
                    padding: 40px;
                }
                h1 {
                    color: #58a6ff;
                    margin-bottom: 20px;
                }
                p {
                    color: #8b949e;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>frago</h1>
                <p>Welcome to frago</p>
                <p id="status">Loading...</p>
            </div>
            <script>
                window.addEventListener('pywebviewready', () => {
                    document.getElementById('status').textContent = 'Ready';
                });
            </script>
        </body>
        </html>
        """

    def start(self) -> None:
        """Start the GUI application.

        Raises:
            GuiNotAvailableError: If GUI cannot be started.
        """
        if not can_start_gui():
            reason = get_gui_unavailable_reason()
            raise GuiNotAvailableError(reason)

        self.create_window()

        webview.start(
            func=self._on_loaded,
            debug=self.debug,
        )

    def _on_loaded(self) -> None:
        """Callback when the window is loaded."""
        pass

    def close(self) -> None:
        """Close the GUI window and cleanup resources."""
        if self._http_server:
            self._http_server.shutdown()
            self._http_server = None
        if self.window:
            self.window.destroy()


def start_gui(debug: bool = False) -> None:
    """Start the Frago GUI application.

    Args:
        debug: Enable debug mode.

    Raises:
        GuiNotAvailableError: If GUI cannot be started.
    """
    # 在非调试模式下，后台运行 GUI
    if not debug and platform.system() != "Windows":
        # Fork 到后台（仅 Unix 系统）
        try:
            pid = os.fork()
            if pid > 0:
                # 父进程立即退出
                sys.exit(0)
        except OSError as e:
            print(f"Fork 失败: {e}", file=sys.stderr)
            sys.exit(1)

        # 子进程：detach from terminal
        os.setsid()

        # 重定向标准输入输出到 /dev/null
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, sys.stdin.fileno())
        os.dup2(devnull, sys.stdout.fileno())
        os.dup2(devnull, sys.stderr.fileno())
        os.close(devnull)

    # 在非调试模式下，抑制 GTK/GLib 的警告消息
    if not debug:
        os.environ['G_MESSAGES_DEBUG'] = ''
        os.environ['PYWEBVIEW_LOG'] = 'error'
        # 抑制 GLib 的所有警告和调试信息
        os.environ['G_DEBUG'] = 'fatal-criticals'

    # Linux 依赖检查和自动安装（必须在 import webview 之前）
    if platform.system() == "Linux":
        from frago.gui.deps import ensure_gui_deps

        can_start, msg = ensure_gui_deps()
        if not can_start:
            sys.exit(1)
        if msg == "restart":
            # 依赖安装成功后重启
            os.execv(sys.executable, [sys.executable] + sys.argv)

    # 依赖检查通过后，才导入 webview（会触发后端加载）
    try:
        # 临时抑制 stderr，避免 pywebview/GTK 后端的调试警告
        import io
        import contextlib

        stderr_buffer = io.StringIO()
        with contextlib.redirect_stderr(stderr_buffer):
            _lazy_import_webview()

        # 抑制 pywebview 的日志
        import logging
        logging.getLogger('pywebview').setLevel(logging.ERROR)
    except ImportError as e:
        print(f"Error: {e}", file=sys.stderr)
        print(_get_install_instructions(), file=sys.stderr)
        sys.exit(1)

    if not can_start_gui():
        reason = get_gui_unavailable_reason()
        print(f"Error: Cannot start GUI. {reason}", file=sys.stderr)
        print("Hint: Run this command in a graphical desktop environment.", file=sys.stderr)
        sys.exit(1)

    try:
        app = FragoGuiApp(debug=debug)
        app.start()
    except ImportError as e:
        print(f"Error: {e}", file=sys.stderr)
        print(_get_install_instructions(), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        # Check if it's a backend loading error (GTK/QT not available)
        error_str = str(e).lower()
        if "gtk" in error_str or "qt" in error_str or "backend" in error_str or "webview" in error_str:
            print(f"Error: GUI backend not available. {e}", file=sys.stderr)
            print(_get_install_instructions(), file=sys.stderr)
        else:
            print(f"Error starting GUI: {e}", file=sys.stderr)
        sys.exit(1)
