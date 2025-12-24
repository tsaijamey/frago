"""Frago GUI Application.

Main application class for the Frago GUI using pywebview.
"""

import os
import platform
import sys
from pathlib import Path
from typing import Optional

# Lazy import webview, import after dependency check in start_gui()
webview = None


def _lazy_import_webview():
    """Lazy import webview to avoid triggering backend loading before dependency check."""
    global webview
    if webview is None:
        import webview as _webview
        webview = _webview
    return webview


def _get_install_instructions() -> str:
    """Get platform-specific installation instructions."""
    system = platform.system()

    if system == "Linux":
        # Detect distribution
        try:
            with open("/etc/os-release") as f:
                os_info = f.read().lower()
        except FileNotFoundError:
            os_info = ""

        if "ubuntu" in os_info or "debian" in os_info:
            return """
Run the following commands to install GUI dependencies:

    sudo apt install -y python3-gi python3-gi-cairo gir1.2-webkit2-4.1
    pip install pywebview

Or install with compilation:

    sudo apt install -y libcairo2-dev libgirepository1.0-dev \\
        libgirepository-2.0-dev gir1.2-webkit2-4.1 python3-dev
    pip install pywebview PyGObject
"""
        elif "fedora" in os_info or "rhel" in os_info or "centos" in os_info:
            return """
Run the following commands to install GUI dependencies:

    sudo dnf install -y python3-gobject python3-gobject-base webkit2gtk4.1
    pip install pywebview
"""
        elif "arch" in os_info:
            return """
Run the following commands to install GUI dependencies:

    sudo pacman -S python-gobject webkit2gtk-4.1
    pip install pywebview
"""
        else:
            return """
Please install the following dependencies:
    - PyGObject (python3-gi)
    - WebKit2GTK (gir1.2-webkit2-4.1)
    - pywebview

Then run: pip install pywebview
"""
    elif system == "Darwin":
        return """
Run the following command to install GUI dependencies:

    pip install pywebview
"""
    elif system == "Windows":
        return """
Run the following command to install GUI dependencies:

    pip install pywebview

Recommended to install Edge WebView2 Runtime for better performance:
    Download: https://developer.microsoft.com/en-us/microsoft-edge/webview2/

Or use winget:
    winget install Microsoft.EdgeWebView2Runtime
"""
    else:
        return "Please install pywebview: pip install pywebview"

from frago.gui_deprecated.exceptions import GuiNotAvailableError
from frago.gui_deprecated.models import WindowConfig
from frago.gui_deprecated.utils import can_start_gui, get_asset_path, get_gui_unavailable_reason, is_debug_mode


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
        self._font_scale: float = 1.0  # Font scale factor, calculated in create_window

    def _calculate_window_size(self) -> tuple[int, int, float]:
        """Calculate window size and font scale based on screen dimensions.

        Returns:
            Tuple of (width, height, font_scale):
            - width, height: calculated as 80% of screen height with aspect ratio
            - font_scale: scaling factor for font size (1.0 = 14px base)
        """
        # Original aspect ratio
        original_width = 600
        original_height = 1434
        aspect_ratio = original_width / original_height

        # Reference height: 800px corresponds to font scale 1.0
        reference_height = 800

        try:
            screens = webview.screens
            if screens:
                # Get primary screen (first screen)
                primary_screen = screens[0]
                screen_height = primary_screen.height
                screen_width = primary_screen.width

                # Calculate target height as 80% of screen height
                target_height = int(screen_height * 0.8)
                target_width = int(target_height * aspect_ratio)

                # Ensure width does not exceed 90% of screen width
                max_width = int(screen_width * 0.9)
                if target_width > max_width:
                    target_width = max_width
                    target_height = int(target_width / aspect_ratio)

                # Ensure not smaller than minimum size
                target_width = max(target_width, self.config.min_width)
                target_height = max(target_height, self.config.min_height)

                # Calculate font scale (based on window height)
                font_scale = target_height / reference_height
                # Limit range: 0.75 ~ 1.5
                font_scale = max(0.75, min(1.5, font_scale))

                return target_width, target_height, font_scale
        except Exception:
            # If screen info cannot be obtained, use default values
            pass

        return original_width, original_height, 1.0

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
            # Development mode: check if Vite server is running
            if not self._check_dev_server():
                import logging

                logger = logging.getLogger(__name__)
                logger.warning(
                    "Vite dev server is not running. Please run: cd src/frago/gui/frontend && npm run dev"
                )
                # Return error page
                return self._get_dev_server_error_html()
            return "http://localhost:5173"

        # Production mode: serve static files using built-in HTTP server
        # WebKit2GTK cannot load external JS files via file:// protocol
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
        from frago.gui_deprecated.api import FragoGuiApi

        self._api = FragoGuiApi()
        url = self._get_url()

        # Dynamically calculate window size and font scale
        width, height, self._font_scale = self._calculate_window_size()

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
            confirm_close=False,  # Disable confirmation, use native window behavior
        )

        self.window.events.closing += self._on_closing
        self._api.set_window(self.window)
        return self.window

    def _on_closing(self) -> bool:
        """Handle window closing event.

        Since using native window title bar and no confirmation needed, always allow closing.

        Returns:
            True to allow closing.
        """
        # Using native window title bar, no confirmation needed, always allow closing
        import logging
        logger = logging.getLogger(__name__)
        logger.debug("Window close event triggered, allowing close")
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
            title="Dev Server Not Running",
            message="Cannot connect to Vite dev server. Please start the dev server first.",
            hint="cd src/frago/gui/frontend && npm run dev",
        )

    def _get_build_missing_html(self) -> str:
        """Get HTML for missing build output error."""
        return self._get_error_html(
            title="Build Output Missing",
            message="Frontend build output not found. Please build the frontend first.",
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

    def _get_icon_path(self) -> Optional[str]:
        """Get the application icon path based on platform.

        Returns:
            Path to icon file, or None if not found.
        """
        # Icon files are in gui/assets/icons/ directory
        icons_dir = Path(__file__).parent / "assets" / "icons"
        system = platform.system()

        if system == "Windows":
            icon_file = icons_dir / "frago.ico"
        else:
            icon_file = icons_dir / "frago.png"

        if icon_file.exists():
            return str(icon_file)
        return None

    def _set_macos_dock_icon(self, icon_path: str) -> None:
        """Set macOS Dock icon using pyobjc.

        Args:
            icon_path: Path to the icon file.
        """
        try:
            from AppKit import NSApplication, NSImage
            app = NSApplication.sharedApplication()
            icon = NSImage.alloc().initWithContentsOfFile_(icon_path)
            if icon:
                app.setApplicationIconImage_(icon)
        except ImportError:
            pass  # pyobjc not installed, skip

    def start(self) -> None:
        """Start the GUI application.

        Raises:
            GuiNotAvailableError: If GUI cannot be started.
        """
        if not can_start_gui():
            reason = get_gui_unavailable_reason()
            raise GuiNotAvailableError(reason)

        self.create_window()

        # Get icon path
        icon_path = self._get_icon_path()
        system = platform.system()

        # macOS: use pyobjc to set Dock icon
        if system == "Darwin" and icon_path:
            self._set_macos_dock_icon(icon_path)

        # Linux (GTK/QT): use icon parameter of webview.start
        # Windows: not supported in dev mode, set by packager in production
        start_kwargs = {
            "func": self._on_loaded,
            "debug": self.debug,
        }
        if system == "Linux" and icon_path:
            start_kwargs["icon"] = icon_path

        webview.start(**start_kwargs)

    def _on_loaded(self) -> None:
        """Callback when the window is loaded.

        Injects CSS variables for font scaling and platform-specific adjustments.
        """
        if self.window and hasattr(self, '_font_scale'):
            system = platform.system()

            # macOS renders fonts thinner, Windows/Linux renders thicker, adjust font weight to compensate
            weights = {
                'Darwin': ('400', '500', '600'),
                'Windows': ('400', '450', '550'),
                'Linux': ('400', '450', '550'),
            }.get(system, ('400', '500', '600'))

            js_code = f"""
                document.documentElement.style.setProperty('--font-scale', '{self._font_scale:.3f}');
                document.documentElement.style.setProperty('--font-weight-normal', '{weights[0]}');
                document.documentElement.style.setProperty('--font-weight-medium', '{weights[1]}');
                document.documentElement.style.setProperty('--font-weight-bold', '{weights[2]}');
                document.documentElement.setAttribute('data-platform', '{system.lower()}');
            """
            self.window.evaluate_js(js_code)

    def close(self) -> None:
        """Close the GUI window and cleanup resources."""
        if self._http_server:
            self._http_server.shutdown()
            self._http_server = None
        if self.window:
            self.window.destroy()


def start_gui(debug: bool = False, _background: bool = False) -> None:
    """Start the Frago GUI application.

    Args:
        debug: Enable debug mode.
        _background: Internal flag, True when running as background process.
                     Do not use directly - set automatically by subprocess launch.

    Raises:
        GuiNotAvailableError: If GUI cannot be started.
    """
    # Background mode logic (non-debug mode and not already running as background process)
    # Use subprocess to start new process, allowing terminal to return immediately
    if not debug and not _background:
        import shutil
        import subprocess

        system = platform.system()
        popen_kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }

        if system == "Windows":
            # Windows: use CREATE_NEW_PROCESS_GROUP and DETACHED_PROCESS
            # CREATE_NEW_PROCESS_GROUP (0x200): create new process group
            # DETACHED_PROCESS (0x8): detach from console
            popen_kwargs["creationflags"] = 0x200 | 0x8
        else:
            # Unix: use start_new_session to create new session, detach from terminal
            popen_kwargs["start_new_session"] = True

        # Prefer using frago entry point script (for pip/uv tool install)
        # This ensures subprocess has correct Python environment and module paths
        frago_cmd = shutil.which("frago")
        if frago_cmd:
            # Use entry point script, add --gui-background internal flag
            subprocess.Popen(
                [frago_cmd, "--gui-background"],
                **popen_kwargs,
            )
        else:
            # Fallback: use python -m in dev mode (works in uv run environment)
            subprocess.Popen(
                [sys.executable, "-m", "frago.gui.app", "--background"],
                **popen_kwargs,
            )
        return  # Parent process returns immediately

    # In non-debug mode, suppress GTK/GLib warning messages
    if not debug:
        os.environ['G_MESSAGES_DEBUG'] = ''
        os.environ['PYWEBVIEW_LOG'] = 'error'
        # Suppress all GLib warnings and debug info
        os.environ['G_DEBUG'] = 'fatal-criticals'

    # Linux dependency check and auto-install (must be before import webview)
    if platform.system() == "Linux":
        from frago.gui_deprecated.deps import ensure_gui_deps

        can_start, msg = ensure_gui_deps()
        if not can_start:
            sys.exit(1)
        if msg == "restart":
            # Restart after dependencies installed successfully
            os.execv(sys.executable, [sys.executable] + sys.argv)

    # Import webview after dependency check passes (triggers backend loading)
    try:
        # Temporarily suppress stderr to avoid pywebview/GTK backend debug warnings
        import io
        import contextlib

        stderr_buffer = io.StringIO()
        with contextlib.redirect_stderr(stderr_buffer):
            _lazy_import_webview()

        # Suppress pywebview logs
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


# Module entry point for subprocess calls
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Frago GUI Application")
    parser.add_argument("--background", action="store_true", help="Run as background process")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    start_gui(debug=args.debug, _background=args.background)
