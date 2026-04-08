"""Environment variable loader

Supports three-level priority configuration:
1. Project-level (.frago/.env) - Highest priority
2. User-level (~/.frago/.env)
3. System environment (os.environ) - Lowest priority

Also supports:
- Workflow context sharing
- CLI --env parameter overrides
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class WorkflowContext:
    """Workflow execution context for sharing environment variables across Recipes"""
    shared_env: dict[str, str] = field(default_factory=dict)

    def set(self, key: str, value: str) -> None:
        """Set shared environment variable"""
        self.shared_env[key] = value

    def get(self, key: str, default: str | None = None) -> str | None:
        """Get shared environment variable"""
        return self.shared_env.get(key, default)

    def update(self, env_dict: dict[str, str]) -> None:
        """Batch update shared environment variables"""
        self.shared_env.update(env_dict)

    def as_dict(self) -> dict[str, str]:
        """Return all shared environment variables"""
        return dict(self.shared_env)


class EnvLoader:
    """Environment variable loader"""

    # User-level config file path
    USER_ENV_PATH = Path.home() / ".frago" / ".env"
    # Project-level config file path (relative to current working directory)
    PROJECT_ENV_PATH = Path(".frago") / ".env"

    def __init__(self, project_root: Path | None = None):
        """
        Initialize environment variable loader

        Args:
            project_root: Project root directory, defaults to current working directory
        """
        self.project_root = project_root or Path.cwd()
        self._cache: dict[str, str] | None = None

    def load_env_file(self, path: Path) -> dict[str, str]:
        """
        Parse .env file

        Supported formats:
        - KEY=value
        - KEY="value with spaces"
        - KEY='value with spaces'
        - # comment lines
        - empty lines

        Args:
            path: .env file path

        Returns:
            Environment variable dictionary
        """
        env_vars: dict[str, str] = {}

        if not path.exists():
            return env_vars

        try:
            content = path.read_text(encoding='utf-8')
        except Exception:
            return env_vars

        for line in content.splitlines():
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue

            # Parse KEY=VALUE
            match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
            if not match:
                continue

            key = match.group(1)
            value = match.group(2).strip()

            # Remove quotes
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]

            env_vars[key] = value

        return env_vars

    def load_all(self, clear_cache: bool = False) -> dict[str, str]:
        """
        Load all levels of environment variables (merged by priority)

        Priority (high to low):
        1. Project-level (.frago/.env)
        2. User-level (~/.frago/.env)
        3. System environment (os.environ)

        Args:
            clear_cache: Whether to clear cache and reload

        Returns:
            Merged environment variable dictionary
        """
        if self._cache is not None and not clear_cache:
            return dict(self._cache)

        # Start from system environment (lowest priority)
        merged: dict[str, str] = dict(os.environ)

        # User-level override
        user_env = self.load_env_file(self.USER_ENV_PATH)
        merged.update(user_env)

        # Project-level override (highest priority)
        project_env_path = self.project_root / self.PROJECT_ENV_PATH
        project_env = self.load_env_file(project_env_path)
        merged.update(project_env)

        self._cache = merged
        return dict(merged)

    def resolve_for_recipe(
        self,
        env_definitions: dict[str, dict[str, Any]] | None = None,  # noqa: ARG002
        cli_overrides: dict[str, str] | None = None,
        workflow_context: WorkflowContext | None = None
    ) -> dict[str, str]:
        """
        Resolve environment variables for Recipe

        Priority (high to low):
        1. CLI --env parameter
        2. Workflow context shared variables
        3. Project-level .env
        4. User-level .env
        5. System environment

        Note: Credential validation has moved to runner._resolve_secrets().
        This method now only merges system/user/project env + workflow context + CLI overrides.

        Args:
            env_definitions: Deprecated, ignored. Kept for API compatibility.
            cli_overrides: Override values provided by CLI --env parameter
            workflow_context: Workflow execution context

        Returns:
            Complete environment variable dictionary (inherits system environment + config overrides)
        """
        cli_overrides = cli_overrides or {}

        # Load all levels
        merged = self.load_all()

        # Workflow context override
        if workflow_context:
            merged.update(workflow_context.as_dict())

        # CLI override (highest priority)
        merged.update(cli_overrides)

        return merged

