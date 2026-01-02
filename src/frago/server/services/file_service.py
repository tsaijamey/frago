"""File service for project file operations.

Provides safe access to run instance directories in ~/.frago/projects/.
"""

import json
import mimetypes
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

        Returns:
            List of ProjectInfo objects sorted by last_accessed (newest first)
        """
        if not PROJECTS_DIR.exists():
            return []

        projects = []
        for project_dir in PROJECTS_DIR.iterdir():
            if not project_dir.is_dir():
                continue

            metadata_file = project_dir / ".metadata.json"
            if metadata_file.exists():
                try:
                    metadata = json.loads(metadata_file.read_text())
                    projects.append(ProjectInfo(
                        run_id=metadata.get("run_id", project_dir.name),
                        theme_description=metadata.get("theme_description", ""),
                        created_at=metadata.get("created_at", ""),
                        last_accessed=metadata.get("last_accessed", ""),
                        status=metadata.get("status", "active"),
                    ))
                except (json.JSONDecodeError, OSError):
                    # Fallback for projects without valid metadata
                    projects.append(ProjectInfo(
                        run_id=project_dir.name,
                        theme_description="",
                        created_at="",
                        last_accessed="",
                        status="unknown",
                    ))
            else:
                # Project without metadata
                projects.append(ProjectInfo(
                    run_id=project_dir.name,
                    theme_description="",
                    created_at="",
                    last_accessed="",
                    status="unknown",
                ))

        # Sort by last_accessed (newest first)
        projects.sort(key=lambda p: p.last_accessed, reverse=True)
        return projects

    @staticmethod
    def get_project(run_id: str) -> Optional[ProjectDetail]:
        """Get detailed project information.

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
                metadata = json.loads(metadata_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        # Count files and size
        file_count = 0
        total_size = 0
        subdirectories = []

        for item in project_dir.iterdir():
            if item.name.startswith("."):
                continue
            if item.is_dir():
                subdirectories.append(item.name)
                # Count files in subdirectory
                for f in item.rglob("*"):
                    if f.is_file():
                        file_count += 1
                        total_size += f.stat().st_size
            elif item.is_file():
                file_count += 1
                total_size += item.stat().st_size

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
        for item in target_path.iterdir():
            # Skip hidden files
            if item.name.startswith("."):
                continue

            rel_path = str(Path(subpath) / item.name) if subpath else item.name

            if item.is_dir():
                files.append(FileInfo(
                    name=item.name,
                    path=rel_path,
                    is_directory=True,
                    size=0,
                    modified=datetime.fromtimestamp(item.stat().st_mtime).isoformat(),
                    mime_type=None,
                ))
            else:
                mime_type, _ = mimetypes.guess_type(item.name)
                files.append(FileInfo(
                    name=item.name,
                    path=rel_path,
                    is_directory=False,
                    size=item.stat().st_size,
                    modified=datetime.fromtimestamp(item.stat().st_mtime).isoformat(),
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
