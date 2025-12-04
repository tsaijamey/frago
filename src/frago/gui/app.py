"""Frago GUI Application.

Main application class for the Frago GUI using pywebview.
"""

import platform
import sys
from pathlib import Path
from typing import Optional

try:
    import webview
except ImportError:
    webview = None


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

    def create_window(self) -> "webview.Window":
        """Create the GUI window.

        Returns:
            webview.Window instance.
        """
        from frago.gui.api import FragoGuiApi

        self._api = FragoGuiApi()
        index_path = get_asset_path("index.html")

        if index_path.exists():
            url = f"file://{index_path}"
        else:
            url = self._get_fallback_html()

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

    def _get_fallback_html(self) -> str:
        """Get fallback HTML content when index.html is not found.

        Returns:
            HTML string for fallback content.
        """
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Frago GUI</title>
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #1a1a2e;
                    color: #eee;
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
                    color: #00d9ff;
                    margin-bottom: 20px;
                }
                p {
                    color: #888;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🚀 Frago GUI</h1>
                <p>Welcome to Frago GUI Mode</p>
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
        """Close the GUI window."""
        if self.window:
            self.window.destroy()


def start_gui(debug: bool = False) -> None:
    """Start the Frago GUI application.

    Args:
        debug: Enable debug mode.

    Raises:
        GuiNotAvailableError: If GUI cannot be started.
    """
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
