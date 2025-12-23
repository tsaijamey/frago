"""Run Context Manager

Responsible for reading and writing ~/.frago/current_run configuration file, with environment variable priority support
"""

import json
import os
from pathlib import Path
from typing import Optional

from .exceptions import (
    ContextAlreadySetError,
    ContextNotSetError,
    FileSystemError,
    RunNotFoundError,
)
from .models import CurrentRunContext


class ContextManager:
    """Run Context Manager"""

    def __init__(self, frago_home: Path, projects_dir: Path):
        """Initialize context manager

        Args:
            frago_home: Frago user directory (~/.frago)
            projects_dir: projects directory path
        """
        self.frago_home = frago_home
        self.projects_dir = projects_dir
        self.config_dir = frago_home
        self.config_file = self.config_dir / "current_run"

    def get_current_run(self) -> CurrentRunContext:
        """Get current run context

        Priority: FRAGO_CURRENT_RUN environment variable > configuration file

        Returns:
            CurrentRunContext instance

        Raises:
            ContextNotSetError: context not set
            RunNotFoundError: referenced run does not exist
        """
        # 1. Check environment variable (highest priority)
        env_run_id = os.getenv("FRAGO_CURRENT_RUN")
        if env_run_id:
            run_dir = self.projects_dir / env_run_id
            if not run_dir.exists():
                raise RunNotFoundError(env_run_id)

            # Read theme description from metadata
            metadata_file = run_dir / ".metadata.json"
            if metadata_file.exists():
                metadata = json.loads(metadata_file.read_text())
                from datetime import datetime

                return CurrentRunContext(
                    run_id=env_run_id,
                    last_accessed=datetime.now(),
                    theme_description=metadata.get("theme_description", env_run_id),
                )
            else:
                from datetime import datetime

                return CurrentRunContext(
                    run_id=env_run_id,
                    last_accessed=datetime.now(),
                    theme_description=env_run_id,
                )

        # 2. Read configuration file
        if not self.config_file.exists():
            raise ContextNotSetError()

        try:
            data = json.loads(self.config_file.read_text())
            context = CurrentRunContext.from_dict(data)
        except Exception as e:
            raise FileSystemError("read", str(self.config_file), str(e))

        # 3. Verify run directory exists
        run_dir = self.projects_dir / context.run_id
        if not run_dir.exists():
            # Clear invalid configuration
            self._clear_context()
            raise RunNotFoundError(context.run_id)

        return context

    def set_current_run(self, run_id: str, theme_description: str) -> CurrentRunContext:
        """Set current run context

        Args:
            run_id: target run ID
            theme_description: theme description

        Returns:
            CurrentRunContext instance

        Raises:
            RunNotFoundError: run_id does not exist
            ContextAlreadySetError: another run is already active
            FileSystemError: configuration file write failed
        """
        # Mutual exclusion check: reject if another context exists and it's not the same run
        if self.config_file.exists():
            try:
                data = json.loads(self.config_file.read_text())
                existing_run_id = data.get("run_id")
                if existing_run_id and existing_run_id != run_id:
                    raise ContextAlreadySetError(existing_run_id)
            except json.JSONDecodeError:
                pass  # Configuration file corrupted, allow overwrite

        # Verify run exists
        run_dir = self.projects_dir / run_id
        if not run_dir.exists():
            raise RunNotFoundError(run_id)

        # Create configuration directory
        from .utils import ensure_directory_exists

        ensure_directory_exists(self.config_dir)

        # Write configuration
        from datetime import datetime

        context = CurrentRunContext(
            run_id=run_id,
            last_accessed=datetime.now(),
            theme_description=theme_description,
            projects_dir=str(self.projects_dir),
        )

        try:
            self.config_file.write_text(json.dumps(context.to_dict(), indent=2))
        except Exception as e:
            raise FileSystemError("write", str(self.config_file), str(e))

        # Update run's last_accessed
        metadata_file = run_dir / ".metadata.json"
        if metadata_file.exists():
            metadata = json.loads(metadata_file.read_text())
            metadata["last_accessed"] = context.last_accessed.isoformat().replace(
                "+00:00", "Z"
            )
            metadata_file.write_text(json.dumps(metadata, indent=2))

        return context

    def _clear_context(self) -> None:
        """Clear context configuration (internal method)"""
        if self.config_file.exists():
            try:
                self.config_file.unlink()
            except Exception:
                pass  # Ignore clear failure

    def release_context(self) -> Optional[str]:
        """Release current context (public method)

        Returns:
            released run_id, or None if no context exists
        """
        released_run_id = None
        if self.config_file.exists():
            try:
                data = json.loads(self.config_file.read_text())
                released_run_id = data.get("run_id")
            except json.JSONDecodeError:
                pass
            self._clear_context()
        return released_run_id

    def get_current_run_id(self) -> Optional[str]:
        """Get current run_id (does not raise exceptions)

        Returns:
            run_id or None
        """
        try:
            context = self.get_current_run()
            return context.run_id
        except (ContextNotSetError, RunNotFoundError):
            return None
