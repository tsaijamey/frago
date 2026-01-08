"""File service for project file operations.

Provides safe access to run instance directories in ~/.frago/projects/.
"""

import json
import mimetypes
import os
import platform
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional


PROJECTS_DIR = Path.home() / ".frago" / "projects"


@dataclass
class ProjectInfo:
    """Basic project information."""
    run_id: str
    theme_description: str
    created_at: str
    last_accessed: str
    status: str


@dataclass
class ProjectDetail(ProjectInfo):
    """Detailed project information including file counts."""
    file_count: int
    total_size: int  # bytes
    subdirectories: List[str]


@dataclass
class FileInfo:
    """File or directory information."""
    name: str
    path: str  # relative path from project root
    is_directory: bool
    size: int  # bytes, 0 for directories
    modified: str  # ISO format
    mime_type: Optional[str]  # None for directories


class FileService:
    """Service for managing project file operations."""

    @staticmethod
    def list_projects() -> List[ProjectInfo]:
        """List all run instances.

        Uses os.scandir() for better Windows performance.

        Returns:
            List of ProjectInfo objects sorted by last_accessed (newest first)
        """
        if not PROJECTS_DIR.exists():
            return []

        projects = []
        # Use os.scandir() instead of iterdir() for better Windows performance
        # DirEntry.is_dir() uses cached attributes from directory enumeration
        with os.scandir(PROJECTS_DIR) as entries:
            for entry in entries:
                # Windows: entry.is_dir() may raise OSError for symlinks/junctions
                try:
                    if not entry.is_dir():
                        continue
                except OSError:
                    continue  # Skip entries that cannot be checked

                metadata_file = Path(entry.path) / ".metadata.json"
                # Windows: exists() may raise OSError for permission/encoding issues
                try:
                    if not metadata_file.exists():
                        continue  # Skip directories without .metadata.json
                except OSError:
                    continue  # Skip directories with inaccessible metadata

                try:
                    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
                    projects.append(ProjectInfo(
                        run_id=metadata.get("run_id", entry.name),
                        theme_description=metadata.get("theme_description", ""),
                        created_at=metadata.get("created_at", ""),
                        last_accessed=metadata.get("last_accessed", ""),
                        status=metadata.get("status", "active"),
                    ))
                except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                    continue  # Skip directories with invalid .metadata.json

        # Sort by last_accessed (newest first)
        projects.sort(key=lambda p: p.last_accessed, reverse=True)
        return projects

    @staticmethod
    def get_project(run_id: str) -> Optional[ProjectDetail]:
        """Get detailed project information.

        Uses os.scandir() and os.walk() for better Windows performance.

        Args:
            run_id: Project identifier

        Returns:
            ProjectDetail or None if not found
        """
        project_dir = FileService.validate_path(run_id, "")
        if project_dir is None or not project_dir.exists():
            return None

        # Load metadata
        metadata_file = project_dir / ".metadata.json"
        metadata = {}
        if metadata_file.exists():
            try:
                metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                pass

        # Get subdirectories list (fast operation)
        subdirectories = []
        with os.scandir(project_dir) as entries:
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    subdirectories.append(entry.name)

        # Count files and size using os.walk() + scandir() for optimal performance
        file_count = 0
        total_size = 0
        for dirpath, dirnames, _ in os.walk(project_dir):
            # Skip hidden directories
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]

            try:
                with os.scandir(dirpath) as entries:
                    for entry in entries:
                        if entry.name.startswith("."):
                            continue
                        if entry.is_file():
                            file_count += 1
                            try:
                                # DirEntry.stat() is cached on Windows
                                total_size += entry.stat().st_size
                            except OSError:
                                pass
            except OSError:
                pass

        return ProjectDetail(
            run_id=metadata.get("run_id", run_id),
            theme_description=metadata.get("theme_description", ""),
            created_at=metadata.get("created_at", ""),
            last_accessed=metadata.get("last_accessed", ""),
            status=metadata.get("status", "active"),
            file_count=file_count,
            total_size=total_size,
            subdirectories=sorted(subdirectories),
        )

    @staticmethod
    def list_files(run_id: str, subpath: str = "") -> List[FileInfo]:
        """List files and directories in a project path.

        Uses os.scandir() for better Windows performance.

        Args:
            run_id: Project identifier
            subpath: Relative path within project (empty for root)

        Returns:
            List of FileInfo objects sorted by type (dirs first) then name
        """
        target_path = FileService.validate_path(run_id, subpath)
        if target_path is None or not target_path.exists():
            return []

        if not target_path.is_dir():
            return []

        files = []
        # Use os.scandir() for better Windows performance
        # DirEntry.stat() is cached on Windows
        with os.scandir(target_path) as entries:
            for entry in entries:
                # Skip hidden files
                if entry.name.startswith("."):
                    continue

                rel_path = (Path(subpath) / entry.name).as_posix() if subpath else entry.name

                try:
                    # Get stat once - cached on Windows via DirEntry
                    stat_result = entry.stat()
                except OSError:
                    continue  # Skip files we cannot stat

                if entry.is_dir():
                    files.append(FileInfo(
                        name=entry.name,
                        path=rel_path,
                        is_directory=True,
                        size=0,
                        modified=datetime.fromtimestamp(stat_result.st_mtime).isoformat(),
                        mime_type=None,
                    ))
                else:
                    mime_type, _ = mimetypes.guess_type(entry.name)
                    files.append(FileInfo(
                        name=entry.name,
                        path=rel_path,
                        is_directory=False,
                        size=stat_result.st_size,
                        modified=datetime.fromtimestamp(stat_result.st_mtime).isoformat(),
                        mime_type=mime_type,
                    ))

        # Sort: directories first, then by name
        files.sort(key=lambda f: (not f.is_directory, f.name.lower()))
        return files

    @staticmethod
    def get_file_path(run_id: str, subpath: str) -> Optional[Path]:
        """Get the absolute path to a file.

        Args:
            run_id: Project identifier
            subpath: Relative path to file within project

        Returns:
            Absolute path or None if invalid/not found
        """
        file_path = FileService.validate_path(run_id, subpath)
        if file_path is None or not file_path.exists():
            return None
        if not file_path.is_file():
            return None
        return file_path

    @staticmethod
    def open_in_system(run_id: str, subpath: str = "") -> bool:
        """Open a path in the system file manager.

        Args:
            run_id: Project identifier
            subpath: Relative path within project (empty for project root)

        Returns:
            True if successful, False otherwise
        """
        target_path = FileService.validate_path(run_id, subpath)
        if target_path is None or not target_path.exists():
            return False

        system = platform.system()
        try:
            if system == "Linux":
                subprocess.Popen(["xdg-open", str(target_path)])
            elif system == "Darwin":
                subprocess.Popen(["open", str(target_path)])
            elif system == "Windows":
                subprocess.Popen(["explorer", str(target_path)])
            else:
                return False
            return True
        except (OSError, subprocess.SubprocessError):
            return False

    @staticmethod
    def validate_path(run_id: str, subpath: str) -> Optional[Path]:
        """Validate and resolve a path safely.

        Prevents path traversal attacks by ensuring the resolved path
        is within the projects directory.

        Args:
            run_id: Project identifier
            subpath: Relative path within project

        Returns:
            Resolved Path if valid, None otherwise
        """
        # Reject suspicious characters in run_id
        if ".." in run_id or "/" in run_id or "\\" in run_id:
            return None

        project_dir = PROJECTS_DIR / run_id
        if not project_dir.exists():
            return None

        if not subpath:
            return project_dir

        # Normalize and resolve the path
        try:
            target = (project_dir / subpath).resolve()
        except (OSError, ValueError):
            return None

        # Ensure the resolved path is within the project directory
        try:
            target.relative_to(project_dir.resolve())
        except ValueError:
            # Path is outside project directory (path traversal attempt)
            return None

        return target

    @staticmethod
    def get_project_dir(run_id: str) -> Optional[Path]:
        """Get the project directory path.

        Args:
            run_id: Project identifier

        Returns:
            Project directory path or None if not found
        """
        return FileService.validate_path(run_id, "")
