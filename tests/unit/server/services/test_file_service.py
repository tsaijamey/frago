"""Tests for frago.server.services.file_service module.

Tests project file operations.
"""
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from frago.server.services.file_service import (
    FileInfo,
    FileService,
    ProjectDetail,
    ProjectInfo,
)


class TestProjectInfo:
    """Test ProjectInfo dataclass."""

    def test_creation(self):
        """Should create ProjectInfo with all fields."""
        info = ProjectInfo(
            run_id="test-123",
            theme_description="Test project",
            created_at="2025-01-15T10:00:00",
            last_accessed="2025-01-15T12:00:00",
            status="active",
        )
        assert info.run_id == "test-123"
        assert info.status == "active"


class TestFileInfo:
    """Test FileInfo dataclass."""

    def test_file_info(self):
        """Should create FileInfo for a file."""
        info = FileInfo(
            name="test.txt",
            path="subdir/test.txt",
            is_directory=False,
            size=1024,
            modified="2025-01-15T10:00:00",
            mime_type="text/plain",
        )
        assert info.is_directory is False
        assert info.size == 1024

    def test_directory_info(self):
        """Should create FileInfo for a directory."""
        info = FileInfo(
            name="subdir",
            path="subdir",
            is_directory=True,
            size=0,
            modified="2025-01-15T10:00:00",
            mime_type=None,
        )
        assert info.is_directory is True
        assert info.mime_type is None


class TestFileServiceValidatePath:
    """Test FileService.validate_path() method."""

    def test_rejects_path_traversal_in_run_id(self, tmp_path, monkeypatch):
        """Should reject run_id with path traversal attempts."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        assert FileService.validate_path("../etc", "") is None
        assert FileService.validate_path("foo/../bar", "") is None
        assert FileService.validate_path("foo/bar", "") is None
        assert FileService.validate_path("foo\\bar", "") is None

    def test_rejects_nonexistent_project(self, tmp_path, monkeypatch):
        """Should return None for non-existent project."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        result = FileService.validate_path("nonexistent", "")

        assert result is None

    def test_accepts_valid_path(self, tmp_path, monkeypatch):
        """Should return path for valid project."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        project_dir = tmp_path / "valid-project"
        project_dir.mkdir()

        result = FileService.validate_path("valid-project", "")

        assert result == project_dir

    def test_accepts_valid_subpath(self, tmp_path, monkeypatch):
        """Should return path for valid subpath."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        subdir = project_dir / "subdir"
        subdir.mkdir()

        result = FileService.validate_path("project", "subdir")

        assert result == subdir

    def test_rejects_path_traversal_in_subpath(self, tmp_path, monkeypatch):
        """Should reject subpath that escapes project directory."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        result = FileService.validate_path("project", "../other")

        assert result is None


class TestFileServiceListProjects:
    """Test FileService.list_projects() method."""

    def test_returns_empty_when_no_projects_dir(self, tmp_path, monkeypatch):
        """Should return empty list when projects directory doesn't exist."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR",
            tmp_path / "nonexistent",
        )

        result = FileService.list_projects()

        assert result == []

    def test_lists_projects_with_metadata(self, tmp_path, monkeypatch):
        """Should list projects that have .metadata.json."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        # Create project with metadata
        project_dir = tmp_path / "test-project"
        project_dir.mkdir()
        metadata = {
            "run_id": "test-project",
            "theme_description": "Test description",
            "created_at": "2025-01-15T10:00:00",
            "last_accessed": "2025-01-15T12:00:00",
            "status": "active",
        }
        (project_dir / ".metadata.json").write_text(json.dumps(metadata))

        result = FileService.list_projects()

        assert len(result) == 1
        assert result[0].run_id == "test-project"
        assert result[0].theme_description == "Test description"

    def test_skips_projects_without_metadata(self, tmp_path, monkeypatch):
        """Should skip directories without .metadata.json."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        # Create directory without metadata
        (tmp_path / "no-metadata").mkdir()

        result = FileService.list_projects()

        assert result == []

    def test_sorts_by_last_accessed(self, tmp_path, monkeypatch):
        """Should sort projects by last_accessed (newest first)."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        # Create older project
        old_project = tmp_path / "old-project"
        old_project.mkdir()
        (old_project / ".metadata.json").write_text(
            json.dumps({"last_accessed": "2025-01-01T10:00:00"})
        )

        # Create newer project
        new_project = tmp_path / "new-project"
        new_project.mkdir()
        (new_project / ".metadata.json").write_text(
            json.dumps({"last_accessed": "2025-01-15T10:00:00"})
        )

        result = FileService.list_projects()

        assert len(result) == 2
        assert result[0].last_accessed == "2025-01-15T10:00:00"


class TestFileServiceGetProject:
    """Test FileService.get_project() method."""

    def test_returns_none_for_nonexistent(self, tmp_path, monkeypatch):
        """Should return None for non-existent project."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        result = FileService.get_project("nonexistent")

        assert result is None

    def test_returns_project_details(self, tmp_path, monkeypatch):
        """Should return ProjectDetail with file counts."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        project_dir = tmp_path / "test-project"
        project_dir.mkdir()
        (project_dir / ".metadata.json").write_text(
            json.dumps({
                "run_id": "test-project",
                "theme_description": "Test",
                "created_at": "2025-01-15T10:00:00",
                "last_accessed": "2025-01-15T12:00:00",
                "status": "active",
            })
        )

        # Create some files
        (project_dir / "file1.txt").write_text("content")
        subdir = project_dir / "subdir"
        subdir.mkdir()
        (subdir / "file2.txt").write_text("more content")

        result = FileService.get_project("test-project")

        assert result is not None
        assert result.run_id == "test-project"
        assert result.file_count == 2
        assert result.total_size > 0
        assert "subdir" in result.subdirectories


class TestFileServiceListFiles:
    """Test FileService.list_files() method."""

    def test_returns_empty_for_nonexistent(self, tmp_path, monkeypatch):
        """Should return empty list for non-existent path."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        result = FileService.list_files("nonexistent", "")

        assert result == []

    def test_lists_files_and_directories(self, tmp_path, monkeypatch):
        """Should list both files and directories."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "file.txt").write_text("content")
        (project_dir / "subdir").mkdir()

        result = FileService.list_files("project", "")

        assert len(result) == 2
        file_names = [f.name for f in result]
        assert "file.txt" in file_names
        assert "subdir" in file_names

    def test_skips_hidden_files(self, tmp_path, monkeypatch):
        """Should skip hidden files (starting with .)."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / ".hidden").write_text("hidden")
        (project_dir / "visible.txt").write_text("visible")

        result = FileService.list_files("project", "")

        assert len(result) == 1
        assert result[0].name == "visible.txt"

    def test_sorts_directories_first(self, tmp_path, monkeypatch):
        """Should sort directories before files."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "aaa_file.txt").write_text("content")
        (project_dir / "zzz_dir").mkdir()

        result = FileService.list_files("project", "")

        # Directory should come first despite name sorting
        assert result[0].name == "zzz_dir"
        assert result[0].is_directory is True
        assert result[1].name == "aaa_file.txt"


class TestFileServiceGetFilePath:
    """Test FileService.get_file_path() method."""

    def test_returns_none_for_nonexistent(self, tmp_path, monkeypatch):
        """Should return None for non-existent file."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        result = FileService.get_file_path("project", "nonexistent.txt")

        assert result is None

    def test_returns_none_for_directory(self, tmp_path, monkeypatch):
        """Should return None when path is a directory."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "subdir").mkdir()

        result = FileService.get_file_path("project", "subdir")

        assert result is None

    def test_returns_path_for_file(self, tmp_path, monkeypatch):
        """Should return path for existing file."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        file_path = project_dir / "test.txt"
        file_path.write_text("content")

        result = FileService.get_file_path("project", "test.txt")

        assert result == file_path


class TestFileServiceOpenInSystem:
    """Test FileService.open_in_system() method."""

    def test_returns_false_for_nonexistent(self, tmp_path, monkeypatch):
        """Should return False for non-existent path."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        result = FileService.open_in_system("nonexistent", "")

        assert result is False

    def test_opens_on_linux(self, tmp_path, monkeypatch):
        """Should use xdg-open on Linux."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        with (
            patch("platform.system", return_value="Linux"),
            patch("subprocess.Popen") as mock_popen,
        ):
            result = FileService.open_in_system("project", "")

        assert result is True
        mock_popen.assert_called_once()
        assert "xdg-open" in mock_popen.call_args[0][0]

    def test_opens_on_macos(self, tmp_path, monkeypatch):
        """Should use open on macOS."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        with (
            patch("platform.system", return_value="Darwin"),
            patch("subprocess.Popen") as mock_popen,
        ):
            result = FileService.open_in_system("project", "")

        assert result is True
        mock_popen.assert_called_once()
        assert "open" in mock_popen.call_args[0][0]

    def test_returns_false_for_unsupported_os(self, tmp_path, monkeypatch):
        """Should return False for unsupported operating system."""
        monkeypatch.setattr(
            "frago.server.services.file_service.PROJECTS_DIR", tmp_path
        )

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        with patch("platform.system", return_value="Unknown"):
            result = FileService.open_in_system("project", "")

        assert result is False
