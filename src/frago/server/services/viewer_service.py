"""Viewer service for content preview.

Manages content preparation and resources for the viewer functionality.
Content is stored in ~/.frago/viewer/ with automatic cleanup of old content.
"""

import hashlib
import shutil
import time
from pathlib import Path
from typing import Literal, Optional

# Viewer directory structure
VIEWER_DIR = Path.home() / ".frago" / "viewer"
CONTENT_DIR = VIEWER_DIR / "content"
RESOURCES_DIR = VIEWER_DIR / "resources"

# Content expiration (24 hours in seconds)
CONTENT_MAX_AGE = 24 * 60 * 60

# Media type extensions
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".m4v"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"}
THREE_EXTENSIONS = {".gltf", ".glb"}


def get_package_resources_path() -> Path:
    """Get path to viewer resources in the package."""
    return Path(__file__).parent.parent.parent / "resources" / "viewer"


class ViewerService:
    """Service for managing viewer content and resources."""

    @staticmethod
    def ensure_directories() -> None:
        """Ensure viewer directory structure exists."""
        CONTENT_DIR.mkdir(parents=True, exist_ok=True)
        RESOURCES_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def ensure_resources() -> None:
        """Copy viewer resources from package if not present or outdated.

        Resources include: reveal.js, highlight.js, pdfjs, mermaid, three.js
        """
        ViewerService.ensure_directories()

        package_resources = get_package_resources_path()
        if not package_resources.exists():
            return

        # Resource directories to copy
        resource_dirs = ["reveal", "highlight", "pdfjs", "mermaid", "three"]

        for res_dir in resource_dirs:
            src = package_resources / res_dir
            dst = RESOURCES_DIR / res_dir

            if src.exists():
                # Copy if destination doesn't exist or source is newer
                if not dst.exists():
                    shutil.copytree(src, dst)

    @staticmethod
    def generate_content_id(content: str, file_path: Optional[Path] = None) -> str:
        """Generate a unique content ID based on content hash.

        Args:
            content: Content string
            file_path: Optional file path for additional uniqueness

        Returns:
            Short hash string suitable for URL
        """
        hash_input = content
        if file_path:
            hash_input += str(file_path.resolve())
        # Add timestamp for uniqueness (content changes)
        hash_input += str(time.time())

        return hashlib.sha256(hash_input.encode()).hexdigest()[:12]

    @staticmethod
    def prepare_content(
        content: str | Path,
        mode: Literal["auto", "present", "doc"] = "auto",
        theme: str = "github-dark",
        title: Optional[str] = None,
    ) -> str:
        """Prepare content for viewing and return content_id.

        Args:
            content: File path or raw content string
            mode: Display mode - "auto", "present", or "doc"
            theme: Code highlighting theme
            title: Content title

        Returns:
            content_id for constructing the viewer URL
        """
        ViewerService.ensure_resources()
        ViewerService.cleanup_old_content()

        # Determine content source
        if isinstance(content, Path) or (isinstance(content, str) and Path(content).exists()):
            file_path = Path(content)
            is_file = True
            content_str = ""
            title = title or file_path.name
        else:
            file_path = None
            is_file = False
            content_str = content
            title = title or "frago view"

        # Detect content type early for binary file handling
        content_type = ViewerService._get_content_type(file_path)
        is_binary = content_type in {"video", "image", "audio", "3d", "pdf"}

        # Generate content ID
        if is_file and is_binary:
            # For binary files, use file path and mtime for hash
            content_id = ViewerService.generate_content_id(
                str(file_path.stat().st_mtime),
                file_path,
            )
        else:
            content_id = ViewerService.generate_content_id(
                content_str if not is_file else file_path.read_text(encoding="utf-8", errors="replace"),
                file_path,
            )

        # Create content directory
        content_dir = CONTENT_DIR / content_id
        content_dir.mkdir(parents=True, exist_ok=True)

        # Handle media types
        if content_type in {"video", "image", "audio", "3d"}:
            html_content = ViewerService._render_media_html(
                file_path, content_type, title, content_dir
            )
            (content_dir / "index.html").write_text(html_content, encoding="utf-8")
            return content_id

        # Detect mode for non-media content
        detected_mode = ViewerService._detect_mode(file_path, content_str) if mode == "auto" else mode

        # Generate HTML
        if detected_mode == "present":
            html_content = ViewerService._render_present_html(
                file_path, content_str, is_file, content_type, theme, title
            )
        else:
            html_content = ViewerService._render_doc_html(
                file_path, content_str, is_file, content_type, theme, title
            )

        # Write index.html
        (content_dir / "index.html").write_text(html_content, encoding="utf-8")

        # Copy source file if PDF
        if file_path and file_path.suffix.lower() == ".pdf":
            shutil.copy(file_path, content_dir / "source.pdf")

        # Copy relative resources from source file directory
        if file_path:
            source_dir = file_path.parent
            for subdir in ["images", "assets", "img", "media", "figures", "videos", "styles"]:
                src_subdir = source_dir / subdir
                if src_subdir.exists() and src_subdir.is_dir():
                    dst_subdir = content_dir / subdir
                    if not dst_subdir.exists():
                        shutil.copytree(src_subdir, dst_subdir)

        return content_id

    @staticmethod
    def _detect_mode(file_path: Optional[Path], content_str: str) -> Literal["present", "doc"]:
        """Auto-detect the display mode based on content type."""
        if file_path:
            ext = file_path.suffix.lower()
            if ext in {".pdf", ".md"}:
                return "doc"
            if ext in {".html", ".htm"}:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                if 'class="reveal"' in content or 'class="slides"' in content:
                    return "present"
                return "doc"
        return "doc"

    @staticmethod
    def _get_content_type(file_path: Optional[Path]) -> str:
        """Get the content type for routing to appropriate handler."""
        if file_path:
            ext = file_path.suffix.lower()
            if ext == ".pdf":
                return "pdf"
            if ext == ".md":
                return "markdown"
            if ext in {".html", ".htm"}:
                return "html"
            if ext == ".json":
                return "json"
            if ext in VIDEO_EXTENSIONS:
                return "video"
            if ext in IMAGE_EXTENSIONS:
                return "image"
            if ext in AUDIO_EXTENSIONS:
                return "audio"
            if ext in THREE_EXTENSIONS:
                return "3d"
            return "code"
        return "markdown"

    @staticmethod
    def _render_present_html(
        file_path: Optional[Path],
        content_str: str,
        is_file: bool,
        content_type: str,
        theme: str,
        title: str,
    ) -> str:
        """Render reveal.js presentation HTML."""
        from frago.viewer.modes.present import render_presentation

        if is_file:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        else:
            content = content_str

        return render_presentation(
            content=content,
            content_type=content_type,
            theme=theme,
            title=title,
            resources_base="/viewer/resources",
        )

    @staticmethod
    def _render_doc_html(
        file_path: Optional[Path],
        content_str: str,
        is_file: bool,
        content_type: str,
        theme: str,
        title: str,
    ) -> str:
        """Render document HTML."""
        from frago.viewer.modes.document import render_document

        if content_type == "pdf":
            content = ""
        elif is_file:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        else:
            content = content_str

        return render_document(
            content=content,
            content_type=content_type,
            theme=theme,
            title=title,
            resources_base="/viewer/resources",
        )

    @staticmethod
    def _render_media_html(
        file_path: Path,
        content_type: str,
        title: str,
        content_dir: Path,
    ) -> str:
        """Render media content (video, image, audio, 3D).

        Copies source file to content directory and generates appropriate HTML.
        """
        from frago.viewer.modes.media import (
            render_video,
            render_image,
            render_audio,
            render_3d,
        )

        # Copy source file to content directory
        source_filename = f"source{file_path.suffix.lower()}"
        shutil.copy(file_path, content_dir / source_filename)

        resources_base = "/viewer/resources"

        if content_type == "video":
            return render_video(title, source_filename, resources_base)
        elif content_type == "image":
            return render_image(title, source_filename)
        elif content_type == "audio":
            return render_audio(title, source_filename)
        elif content_type == "3d":
            return render_3d(title, source_filename, resources_base)
        else:
            # Fallback - should not happen
            return f"<html><body><p>Unsupported media type: {content_type}</p></body></html>"

    @staticmethod
    def cleanup_old_content(max_age_seconds: int = CONTENT_MAX_AGE) -> int:
        """Remove content directories older than max_age.

        Args:
            max_age_seconds: Maximum age in seconds (default 24 hours)

        Returns:
            Number of directories removed
        """
        if not CONTENT_DIR.exists():
            return 0

        current_time = time.time()
        removed = 0

        for content_dir in CONTENT_DIR.iterdir():
            if not content_dir.is_dir():
                continue

            try:
                # Check directory modification time
                mtime = content_dir.stat().st_mtime
                if current_time - mtime > max_age_seconds:
                    shutil.rmtree(content_dir, ignore_errors=True)
                    removed += 1
            except (OSError, ValueError):
                continue

        return removed

    @staticmethod
    def get_content_path(content_id: str) -> Optional[Path]:
        """Get the path to a content directory.

        Args:
            content_id: Content identifier

        Returns:
            Path to content directory if exists, None otherwise
        """
        content_dir = CONTENT_DIR / content_id
        if content_dir.exists() and content_dir.is_dir():
            return content_dir
        return None
