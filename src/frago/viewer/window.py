"""ViewerWindow - Universal content viewer window.

Provides a lightweight pywebview-based window for displaying content in two modes:
- present: reveal.js-powered slideshows
- doc: scrollable documents with syntax highlighting
"""

import mimetypes
import socket
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Literal, Optional

# Lazy import webview
webview = None


def _lazy_import_webview():
    """Lazy import webview to avoid loading backend before dependency check."""
    global webview
    if webview is None:
        import webview as _webview
        webview = _webview
    return webview


def get_resources_path() -> Path:
    """Get path to viewer resources directory."""
    return Path(__file__).parent.parent / "resources" / "viewer"


def get_template_path(name: str) -> Path:
    """Get path to a template file."""
    return Path(__file__).parent / "templates" / name


class ViewerWindow:
    """Universal content viewer window."""

    SUPPORTED_EXTENSIONS = {
        "present": {".md", ".html", ".htm"},
        "doc": {".md", ".html", ".htm", ".pdf", ".json", ".py", ".js", ".ts", ".css", ".yaml", ".yml", ".toml", ".xml", ".txt"},
    }

    def __init__(
        self,
        content: str | Path,
        mode: Literal["auto", "present", "doc"] = "auto",
        theme: str = "black",
        title: Optional[str] = None,
        width: int = 1280,
        height: int = 800,
        fullscreen: bool = False,
        code_theme: str = "github-dark",
    ):
        """Initialize the viewer window.

        Args:
            content: File path or raw content string
            mode: Display mode - "auto", "present" (reveal.js), or "doc" (scrollable)
            theme: Theme name (reveal.js theme for present, code theme for doc)
            title: Window title (defaults to filename or "frago view")
            width: Window width in pixels
            height: Window height in pixels
            fullscreen: Start in fullscreen mode
            code_theme: Code highlighting theme for doc mode
        """
        self.content = content
        self.theme = theme
        self.width = width
        self.height = height
        self.fullscreen = fullscreen
        self.code_theme = code_theme
        self._http_server: Optional[HTTPServer] = None
        self._temp_dir: Optional[Path] = None

        # Determine content source
        if isinstance(content, Path) or (isinstance(content, str) and Path(content).exists()):
            self.file_path = Path(content)
            self.is_file = True
            self.title = title or self.file_path.name
        else:
            self.file_path = None
            self.is_file = False
            self.title = title or "frago view"

        # Detect mode
        self.mode = self._detect_mode() if mode == "auto" else mode

    def _detect_mode(self) -> Literal["present", "doc"]:
        """Auto-detect the display mode based on content type."""
        if self.file_path:
            ext = self.file_path.suffix.lower()
            # PDF and Markdown always use doc mode
            if ext in {".pdf", ".md"}:
                return "doc"
            # HTML with reveal.js class
            if ext in {".html", ".htm"}:
                content = self.file_path.read_text(encoding="utf-8")
                if 'class="reveal"' in content or 'class="slides"' in content:
                    return "present"
                return "doc"
        # Default to doc mode for raw content
        return "doc"

    def _get_content_type(self) -> str:
        """Get the content type for routing to appropriate handler."""
        if self.file_path:
            ext = self.file_path.suffix.lower()
            if ext == ".pdf":
                return "pdf"
            if ext == ".md":
                return "markdown"
            if ext in {".html", ".htm"}:
                return "html"
            if ext == ".json":
                return "json"
            # Code files
            return "code"
        # Raw content - assume markdown
        return "markdown"

    def _start_static_server(self, serve_dir: Path) -> int:
        """Start a local HTTP server for serving static files.

        Args:
            serve_dir: Directory to serve files from

        Returns:
            Port number the server is running on
        """
        serve_path = str(serve_dir)

        # Find available port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            port = s.getsockname()[1]

        class QuietHandler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=serve_path, **kwargs)

            def log_message(self, format, *args):
                pass  # Suppress logging

            def end_headers(self):
                # Add CORS headers for local development
                self.send_header("Access-Control-Allow-Origin", "*")
                super().end_headers()

        self._http_server = HTTPServer(("127.0.0.1", port), QuietHandler)
        thread = threading.Thread(target=self._http_server.serve_forever, daemon=True)
        thread.start()

        return port

    def _prepare_content(self) -> tuple[Path, str]:
        """Prepare content and return (serve_dir, entry_file).

        Returns:
            Tuple of (directory to serve, entry HTML file name)
        """
        import tempfile
        import shutil

        # Create temp directory for serving
        self._temp_dir = Path(tempfile.mkdtemp(prefix="frago_viewer_"))

        # Copy resources
        resources = get_resources_path()
        if resources.exists():
            # Copy reveal.js
            reveal_src = resources / "reveal"
            if reveal_src.exists():
                shutil.copytree(reveal_src, self._temp_dir / "reveal")

            # Copy highlight.js
            highlight_src = resources / "highlight"
            if highlight_src.exists():
                shutil.copytree(highlight_src, self._temp_dir / "highlight")

            # Copy pdfjs
            pdfjs_src = resources / "pdfjs"
            if pdfjs_src.exists():
                shutil.copytree(pdfjs_src, self._temp_dir / "pdfjs")

            # Copy mermaid
            mermaid_src = resources / "mermaid"
            if mermaid_src.exists():
                shutil.copytree(mermaid_src, self._temp_dir / "mermaid")

        # Generate HTML based on mode
        if self.mode == "present":
            html = self._render_present_html()
        else:
            html = self._render_doc_html()

        # Write entry HTML
        entry_file = "index.html"
        (self._temp_dir / entry_file).write_text(html, encoding="utf-8")

        # Copy source file if needed (for PDF)
        if self.file_path and self.file_path.suffix.lower() == ".pdf":
            shutil.copy(self.file_path, self._temp_dir / "source.pdf")

        # Copy relative resources from source file directory (images, etc.)
        if self.file_path:
            source_dir = self.file_path.parent
            # Common resource directories to copy
            for subdir in ["images", "assets", "img", "media", "figures"]:
                src_subdir = source_dir / subdir
                if src_subdir.exists() and src_subdir.is_dir():
                    shutil.copytree(src_subdir, self._temp_dir / subdir)

        return self._temp_dir, entry_file

    def _render_present_html(self) -> str:
        """Render reveal.js presentation HTML."""
        from frago.viewer.modes.present import render_presentation

        # Get content
        if self.is_file:
            content = self.file_path.read_text(encoding="utf-8")
            content_type = self._get_content_type()
        else:
            content = self.content
            content_type = "markdown"

        return render_presentation(
            content=content,
            content_type=content_type,
            theme=self.theme,
            title=self.title,
        )

    def _render_doc_html(self) -> str:
        """Render document HTML."""
        from frago.viewer.modes.document import render_document

        content_type = self._get_content_type()

        # Get content (except PDF which is loaded client-side)
        if content_type == "pdf":
            content = ""  # PDF loaded via PDF.js
        elif self.is_file:
            content = self.file_path.read_text(encoding="utf-8")
        else:
            content = self.content

        return render_document(
            content=content,
            content_type=content_type,
            theme=self.code_theme,
            title=self.title,
        )

    def show(self):
        """Display the viewer window."""
        _lazy_import_webview()

        # Prepare content and start server
        serve_dir, entry_file = self._prepare_content()
        port = self._start_static_server(serve_dir)
        url = f"http://127.0.0.1:{port}/{entry_file}"

        # Create window
        window = webview.create_window(
            title=self.title,
            url=url,
            width=self.width,
            height=self.height,
            fullscreen=self.fullscreen,
            resizable=True,
        )

        # Start webview
        webview.start()

        # Cleanup
        self._cleanup()

    def _cleanup(self):
        """Clean up resources."""
        if self._http_server:
            self._http_server.shutdown()
        if self._temp_dir and self._temp_dir.exists():
            import shutil
            shutil.rmtree(self._temp_dir, ignore_errors=True)


def show_content(
    content: str | Path,
    mode: Literal["auto", "present", "doc"] = "auto",
    theme: str = "black",
    title: Optional[str] = None,
    width: int = 1280,
    height: int = 800,
    fullscreen: bool = False,
):
    """Convenience function to show content in a viewer window.

    Args:
        content: File path or raw content string
        mode: Display mode - "auto", "present", or "doc"
        theme: Theme name
        title: Window title
        width: Window width
        height: Window height
        fullscreen: Start in fullscreen
    """
    viewer = ViewerWindow(
        content=content,
        mode=mode,
        theme=theme,
        title=title,
        width=width,
        height=height,
        fullscreen=fullscreen,
    )
    viewer.show()
