"""Tests for frago.server.services.viewer_service module.

Tests content preview and viewer functionality.
"""
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from frago.server.services.viewer_service import (
    AUDIO_EXTENSIONS,
    CONTENT_DIR,
    IMAGE_EXTENSIONS,
    THREE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    ViewerService,
    get_package_resources_path,
)


class TestConstants:
    """Test module-level constants."""

    def test_video_extensions(self):
        """Should include common video extensions."""
        assert ".mp4" in VIDEO_EXTENSIONS
        assert ".webm" in VIDEO_EXTENSIONS
        assert ".mov" in VIDEO_EXTENSIONS

    def test_image_extensions(self):
        """Should include common image extensions."""
        assert ".png" in IMAGE_EXTENSIONS
        assert ".jpg" in IMAGE_EXTENSIONS
        assert ".svg" in IMAGE_EXTENSIONS

    def test_audio_extensions(self):
        """Should include common audio extensions."""
        assert ".mp3" in AUDIO_EXTENSIONS
        assert ".wav" in AUDIO_EXTENSIONS
        assert ".ogg" in AUDIO_EXTENSIONS

    def test_3d_extensions(self):
        """Should include 3D model extensions."""
        assert ".gltf" in THREE_EXTENSIONS
        assert ".glb" in THREE_EXTENSIONS


class TestGetPackageResourcesPath:
    """Test get_package_resources_path() function."""

    def test_returns_path(self):
        """Should return a Path object."""
        result = get_package_resources_path()
        assert isinstance(result, Path)

    def test_path_ends_with_viewer(self):
        """Should point to viewer resources directory."""
        result = get_package_resources_path()
        assert result.name == "viewer"


class TestViewerServiceEnsureDirectories:
    """Test ViewerService.ensure_directories() method."""

    def test_creates_content_dir(self, tmp_path, monkeypatch):
        """Should create content directory."""
        content_dir = tmp_path / ".frago" / "viewer" / "content"
        resources_dir = tmp_path / ".frago" / "viewer" / "resources"

        monkeypatch.setattr(
            "frago.server.services.viewer_service.CONTENT_DIR", content_dir
        )
        monkeypatch.setattr(
            "frago.server.services.viewer_service.RESOURCES_DIR", resources_dir
        )

        ViewerService.ensure_directories()

        assert content_dir.exists()
        assert resources_dir.exists()


class TestViewerServiceGenerateContentId:
    """Test ViewerService.generate_content_id() method."""

    def test_generates_12_char_hash(self):
        """Should generate 12 character content ID."""
        content_id = ViewerService.generate_content_id("test content")
        assert len(content_id) == 12

    def test_different_content_different_id(self):
        """Should generate different IDs for different content."""
        id1 = ViewerService.generate_content_id("content 1")
        # Sleep briefly to ensure different timestamp
        time.sleep(0.01)
        id2 = ViewerService.generate_content_id("content 2")
        assert id1 != id2

    def test_file_path_affects_id(self):
        """Should include file path in hash calculation."""
        id1 = ViewerService.generate_content_id("content", Path("/path/1.txt"))
        time.sleep(0.01)
        id2 = ViewerService.generate_content_id("content", Path("/path/2.txt"))
        assert id1 != id2


class TestViewerServiceDetectMode:
    """Test ViewerService._detect_mode() method."""

    def test_pdf_returns_doc(self, tmp_path):
        """Should return 'doc' for PDF files."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"PDF content")

        result = ViewerService._detect_mode(pdf_file, "")
        assert result == "doc"

    def test_md_returns_doc(self, tmp_path):
        """Should return 'doc' for Markdown files."""
        md_file = tmp_path / "test.md"
        md_file.write_text("# Markdown")

        result = ViewerService._detect_mode(md_file, "")
        assert result == "doc"

    def test_html_with_reveal_returns_present(self, tmp_path):
        """Should return 'present' for reveal.js HTML."""
        html_file = tmp_path / "slides.html"
        html_file.write_text('<div class="reveal"><div class="slides"></div></div>')

        result = ViewerService._detect_mode(html_file, "")
        assert result == "present"

    def test_plain_html_returns_doc(self, tmp_path):
        """Should return 'doc' for plain HTML."""
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body>Content</body></html>")

        result = ViewerService._detect_mode(html_file, "")
        assert result == "doc"

    def test_no_file_returns_doc(self):
        """Should return 'doc' when no file provided."""
        result = ViewerService._detect_mode(None, "some content")
        assert result == "doc"


class TestViewerServiceGetContentType:
    """Test ViewerService._get_content_type() method."""

    def test_pdf(self, tmp_path):
        """Should identify PDF files."""
        pdf = tmp_path / "test.pdf"
        result = ViewerService._get_content_type(pdf)
        assert result == "pdf"

    def test_markdown(self, tmp_path):
        """Should identify Markdown files."""
        md = tmp_path / "test.md"
        result = ViewerService._get_content_type(md)
        assert result == "markdown"

    def test_html(self, tmp_path):
        """Should identify HTML files."""
        html = tmp_path / "test.html"
        result = ViewerService._get_content_type(html)
        assert result == "html"

    def test_json(self, tmp_path):
        """Should identify JSON files."""
        json_file = tmp_path / "test.json"
        result = ViewerService._get_content_type(json_file)
        assert result == "json"

    def test_video(self, tmp_path):
        """Should identify video files."""
        video = tmp_path / "test.mp4"
        result = ViewerService._get_content_type(video)
        assert result == "video"

    def test_image(self, tmp_path):
        """Should identify image files."""
        image = tmp_path / "test.png"
        result = ViewerService._get_content_type(image)
        assert result == "image"

    def test_audio(self, tmp_path):
        """Should identify audio files."""
        audio = tmp_path / "test.mp3"
        result = ViewerService._get_content_type(audio)
        assert result == "audio"

    def test_3d(self, tmp_path):
        """Should identify 3D model files."""
        model = tmp_path / "test.glb"
        result = ViewerService._get_content_type(model)
        assert result == "3d"

    def test_unknown_returns_code(self, tmp_path):
        """Should return 'code' for unknown extensions."""
        code = tmp_path / "test.py"
        result = ViewerService._get_content_type(code)
        assert result == "code"

    def test_none_returns_markdown(self):
        """Should return 'markdown' when no file provided."""
        result = ViewerService._get_content_type(None)
        assert result == "markdown"


class TestViewerServiceCleanupOldContent:
    """Test ViewerService.cleanup_old_content() method."""

    def test_returns_zero_when_no_dir(self, tmp_path, monkeypatch):
        """Should return 0 when content directory doesn't exist."""
        nonexistent = tmp_path / "nonexistent"
        monkeypatch.setattr(
            "frago.server.services.viewer_service.CONTENT_DIR", nonexistent
        )

        result = ViewerService.cleanup_old_content()
        assert result == 0

    def test_removes_old_directories(self, tmp_path, monkeypatch):
        """Should remove directories older than max_age."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        # Create old directory
        old_dir = content_dir / "old-content"
        old_dir.mkdir()
        # Set mtime to past
        import os
        old_time = time.time() - 86400 * 2  # 2 days ago
        os.utime(old_dir, (old_time, old_time))

        monkeypatch.setattr(
            "frago.server.services.viewer_service.CONTENT_DIR", content_dir
        )

        result = ViewerService.cleanup_old_content(max_age_seconds=86400)

        assert result == 1
        assert not old_dir.exists()

    def test_keeps_recent_directories(self, tmp_path, monkeypatch):
        """Should keep directories newer than max_age."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        # Create recent directory
        recent_dir = content_dir / "recent-content"
        recent_dir.mkdir()

        monkeypatch.setattr(
            "frago.server.services.viewer_service.CONTENT_DIR", content_dir
        )

        result = ViewerService.cleanup_old_content(max_age_seconds=86400)

        assert result == 0
        assert recent_dir.exists()


class TestViewerServiceGetContentPath:
    """Test ViewerService.get_content_path() method."""

    def test_returns_none_for_nonexistent(self, tmp_path, monkeypatch):
        """Should return None when content doesn't exist."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        monkeypatch.setattr(
            "frago.server.services.viewer_service.CONTENT_DIR", content_dir
        )

        result = ViewerService.get_content_path("nonexistent")
        assert result is None

    def test_returns_path_for_existing(self, tmp_path, monkeypatch):
        """Should return path when content exists."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        existing = content_dir / "existing-id"
        existing.mkdir()

        monkeypatch.setattr(
            "frago.server.services.viewer_service.CONTENT_DIR", content_dir
        )

        result = ViewerService.get_content_path("existing-id")
        assert result == existing

    def test_returns_none_for_file(self, tmp_path, monkeypatch):
        """Should return None when path is a file, not directory."""
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        file_path = content_dir / "is-a-file"
        file_path.write_text("content")

        monkeypatch.setattr(
            "frago.server.services.viewer_service.CONTENT_DIR", content_dir
        )

        result = ViewerService.get_content_path("is-a-file")
        assert result is None
