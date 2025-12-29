"""Initialization service for web-based frago init functionality.

Provides API methods for:
- Dependency checking (Node.js, Claude Code)
- Dependency installation
- Resource installation (commands, skills, recipes)
- Initialization status tracking
"""

import logging
import platform
from typing import Any, Dict, Optional

from frago import __version__
from frago.init.checker import (
    DEFAULT_CLAUDE_CODE_MIN_VERSION,
    DEFAULT_NODE_MIN_VERSION,
    parallel_dependency_check,
)
from frago.init.config_manager import load_config, save_config, update_config
from frago.init.installer import (
    get_platform_node_install_guide,
    install_claude_code,
    install_node,
)
from frago.init.models import DependencyCheckResult
from frago.init.resources import get_resources_status, install_all_resources

logger = logging.getLogger(__name__)


def _get_claude_code_install_guide() -> str:
    """Get Claude Code installation guide."""
    return (
        "Install Claude Code via npm:\n"
        "  npm install -g @anthropic-ai/claude-code\n\n"
        "Or visit: https://docs.anthropic.com/en/docs/claude-code"
    )


def _dependency_to_dict(result: DependencyCheckResult) -> Dict[str, Any]:
    """Convert DependencyCheckResult to API response dictionary."""
    # Get installation guide based on dependency type
    if result.name == "node":
        install_guide = get_platform_node_install_guide()
    else:
        install_guide = _get_claude_code_install_guide()

    return {
        "name": result.name,
        "installed": result.installed,
        "version": result.version,
        "path": result.path,
        "version_sufficient": result.version_sufficient,
        "required_version": result.required_version,
        "error": result.error,
        "install_guide": install_guide,
    }


class InitService:
    """Service for initialization operations in web context."""

    @staticmethod
    def get_init_status() -> Dict[str, Any]:
        """Get comprehensive initialization status.

        Returns:
            Dictionary containing:
            - init_completed: bool
            - node: DependencyStatus dict
            - claude_code: DependencyStatus dict
            - resources_installed: bool
            - resources_version: str or None
            - resources_update_available: bool
            - auth_configured: bool
            - auth_method: str or None
        """
        # Load current config
        config = load_config()

        # Check dependencies
        dep_results = parallel_dependency_check()
        node_status = _dependency_to_dict(dep_results.get("node", DependencyCheckResult(
            name="node",
            required_version=DEFAULT_NODE_MIN_VERSION,
        )))
        claude_code_status = _dependency_to_dict(dep_results.get("claude-code", DependencyCheckResult(
            name="claude-code",
            required_version=DEFAULT_CLAUDE_CODE_MIN_VERSION,
        )))

        # Get resource status
        resources_info = get_resources_status()

        # Check if resources need update (compare versions)
        current_version = __version__
        installed_version = config.resources_version
        resources_update_available = False
        if installed_version and current_version != installed_version:
            resources_update_available = True

        # Check auth configuration
        auth_configured = config.auth_method is not None
        if config.auth_method == "custom" and config.api_endpoint is None:
            auth_configured = False

        return {
            "init_completed": config.init_completed,
            "node": node_status,
            "claude_code": claude_code_status,
            "resources_installed": config.resources_installed,
            "resources_version": config.resources_version,
            "resources_update_available": resources_update_available,
            "current_frago_version": current_version,
            "auth_configured": auth_configured,
            "auth_method": config.auth_method,
            "resources_info": resources_info,
        }

    @staticmethod
    def check_dependencies() -> Dict[str, Any]:
        """Run fresh dependency check.

        Returns:
            Dictionary containing:
            - node: DependencyStatus dict
            - claude_code: DependencyStatus dict
            - all_satisfied: bool
        """
        dep_results = parallel_dependency_check()

        node_result = dep_results.get("node")
        claude_code_result = dep_results.get("claude-code")

        node_status = _dependency_to_dict(node_result) if node_result else {
            "name": "node",
            "installed": False,
            "version": None,
            "path": None,
            "version_sufficient": False,
            "required_version": DEFAULT_NODE_MIN_VERSION,
            "error": "Check failed",
            "install_guide": get_platform_node_install_guide(),
        }

        claude_code_status = _dependency_to_dict(claude_code_result) if claude_code_result else {
            "name": "claude-code",
            "installed": False,
            "version": None,
            "path": None,
            "version_sufficient": False,
            "required_version": DEFAULT_CLAUDE_CODE_MIN_VERSION,
            "error": "Check failed",
            "install_guide": _get_claude_code_install_guide(),
        }

        # All satisfied if both are installed with sufficient versions
        all_satisfied = (
            node_status.get("installed", False) and
            node_status.get("version_sufficient", False) and
            claude_code_status.get("installed", False) and
            claude_code_status.get("version_sufficient", False)
        )

        return {
            "node": node_status,
            "claude_code": claude_code_status,
            "all_satisfied": all_satisfied,
        }

    @staticmethod
    def install_dependency(name: str) -> Dict[str, Any]:
        """Install a specific dependency.

        Args:
            name: Dependency name ("node" or "claude-code")

        Returns:
            Dictionary containing:
            - status: "ok" or "error"
            - message: Success or error message
            - requires_restart: bool (terminal restart needed)
            - warning: Optional warning message
        """
        from frago.init.exceptions import CommandError

        # Validate dependency name
        if name not in ("node", "claude-code"):
            return {
                "status": "error",
                "message": f"Unknown dependency: {name}",
                "requires_restart": False,
            }

        # Windows does not support automatic Node.js installation
        if name == "node" and platform.system() == "Windows":
            return {
                "status": "error",
                "message": "Automatic Node.js installation is not supported on Windows",
                "requires_restart": False,
                "install_guide": get_platform_node_install_guide(),
            }

        try:
            if name == "node":
                success, requires_restart = install_node()
                return {
                    "status": "ok" if success else "error",
                    "message": "Node.js installed successfully" if success else "Installation failed",
                    "requires_restart": requires_restart,
                }
            else:  # claude-code
                # Try with nvm fallback for non-Windows
                use_nvm = platform.system() != "Windows"
                success, warning = install_claude_code(use_nvm_fallback=use_nvm)
                return {
                    "status": "ok" if success else "error",
                    "message": "Claude Code installed successfully" if success else "Installation failed",
                    "requires_restart": False,
                    "warning": warning,
                }
        except CommandError as e:
            return {
                "status": "error",
                "message": str(e.message),
                "requires_restart": False,
                "error_code": e.code.name if e.code else None,
                "details": e.details,
            }
        except Exception as e:
            logger.exception("Unexpected error during dependency installation")
            return {
                "status": "error",
                "message": f"Installation failed: {str(e)}",
                "requires_restart": False,
            }

    @staticmethod
    def install_resources(force_update: bool = False) -> Dict[str, Any]:
        """Install or update resources (commands, skills, recipes).

        Args:
            force_update: Whether to force update existing resources

        Returns:
            Dictionary containing:
            - status: "ok", "partial", or "error"
            - commands: InstallResultSummary
            - skills: InstallResultSummary
            - recipes: InstallResultSummary
            - total_installed: int
            - total_skipped: int
            - errors: list of error messages
        """
        try:
            result = install_all_resources(force_update=force_update)

            # Build summary
            commands_summary = {
                "installed": len(result.commands.installed) if result.commands else 0,
                "skipped": len(result.commands.skipped) if result.commands else 0,
                "errors": result.commands.errors if result.commands else [],
            }
            skills_summary = {
                "installed": len(result.skills.installed) if result.skills else 0,
                "skipped": len(result.skills.skipped) if result.skills else 0,
                "errors": result.skills.errors if result.skills else [],
            }
            recipes_summary = {
                "installed": len(result.recipes.installed) if result.recipes else 0,
                "skipped": len(result.recipes.skipped) if result.recipes else 0,
                "errors": result.recipes.errors if result.recipes else [],
            }

            total_installed = (
                commands_summary["installed"] +
                skills_summary["installed"] +
                recipes_summary["installed"]
            )
            total_skipped = (
                commands_summary["skipped"] +
                skills_summary["skipped"] +
                recipes_summary["skipped"]
            )

            all_errors = (
                commands_summary["errors"] +
                skills_summary["errors"] +
                recipes_summary["errors"]
            )

            # Determine overall status
            if all_errors and total_installed == 0:
                status = "error"
            elif all_errors:
                status = "partial"
            else:
                status = "ok"

            # Update config to mark resources as installed
            if status in ("ok", "partial"):
                update_config({
                    "resources_installed": True,
                    "resources_version": __version__,
                })

            return {
                "status": status,
                "commands": commands_summary,
                "skills": skills_summary,
                "recipes": recipes_summary,
                "total_installed": total_installed,
                "total_skipped": total_skipped,
                "errors": all_errors,
                "frago_version": result.frago_version,
            }
        except Exception as e:
            logger.exception("Failed to install resources")
            return {
                "status": "error",
                "message": str(e),
                "commands": {"installed": 0, "skipped": 0, "errors": []},
                "skills": {"installed": 0, "skipped": 0, "errors": []},
                "recipes": {"installed": 0, "skipped": 0, "errors": []},
                "total_installed": 0,
                "total_skipped": 0,
                "errors": [str(e)],
            }

    @staticmethod
    def mark_init_complete() -> Dict[str, Any]:
        """Mark initialization as complete in config.

        Returns:
            Dictionary containing:
            - status: "ok" or "error"
            - message: Success or error message
        """
        try:
            config = update_config({"init_completed": True})
            return {
                "status": "ok",
                "message": "Initialization marked as complete",
                "init_completed": config.init_completed,
            }
        except Exception as e:
            logger.exception("Failed to mark init complete")
            return {
                "status": "error",
                "message": str(e),
            }

    @staticmethod
    def reset_init_status() -> Dict[str, Any]:
        """Reset initialization status (for re-running wizard).

        Returns:
            Dictionary containing:
            - status: "ok" or "error"
            - message: Success or error message
        """
        try:
            update_config({"init_completed": False})
            return {
                "status": "ok",
                "message": "Initialization status reset",
            }
        except Exception as e:
            logger.exception("Failed to reset init status")
            return {
                "status": "error",
                "message": str(e),
            }
