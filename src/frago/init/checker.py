"""
Dependency checking module

Provides parallel checking of Node.js and Claude Code installation status.
"""

import platform
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from frago.compat import prepare_command_for_windows as _prepare_command_for_windows
from frago.init.models import DependencyCheckResult


# Default version requirements
DEFAULT_NODE_MIN_VERSION = "20.0.0"
DEFAULT_CLAUDE_CODE_MIN_VERSION = "1.0.0"


def compare_versions(current: str, required: str) -> int:
    """
    Compare version numbers

    Args:
        current: Current version (e.g., "20.10.0" or "v20.10.0")
        required: Required version (e.g., "20.0.0")

    Returns:
        > 0 if current > required
        = 0 if current == required
        < 0 if current < required
    """
    # Remove 'v' prefix
    current = current.lstrip("v")
    required = required.lstrip("v")

    # Split version numbers
    current_parts = [int(x) for x in current.split(".")]
    required_parts = [int(x) for x in required.split(".")]

    # Pad to same length
    max_len = max(len(current_parts), len(required_parts))
    current_parts.extend([0] * (max_len - len(current_parts)))
    required_parts.extend([0] * (max_len - len(required_parts)))

    # Compare each part
    for c, r in zip(current_parts, required_parts):
        if c > r:
            return 1
        elif c < r:
            return -1
    return 0


def check_node(min_version: str = DEFAULT_NODE_MIN_VERSION) -> DependencyCheckResult:
    """
    Check Node.js installation status

    Args:
        min_version: Minimum version requirement (default 20.0.0)

    Returns:
        DependencyCheckResult containing check results
    """
    result = DependencyCheckResult(
        name="node",
        required_version=min_version,
    )

    # Check if node command exists
    node_path = shutil.which("node")
    if not node_path:
        result.installed = False
        if platform.system() == "Windows":
            result.error = (
                "Node.js is not installed\n\n"
                "Recommended installation:\n"
                "  winget install OpenJS.NodeJS.LTS\n"
                "  or visit: https://nodejs.org/"
            )
        else:
            result.error = "Node.js is not installed"
        return result

    result.path = node_path

    try:
        # Get version
        version_output = subprocess.run(
            _prepare_command_for_windows(["node", "--version"]),
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=5,
        )

        if version_output.returncode == 0:
            version = version_output.stdout.strip().lstrip("v")
            result.installed = True
            result.version = version
            result.version_sufficient = compare_versions(version, min_version) >= 0
        else:
            result.installed = False
            result.error = f"Version detection failed: {version_output.stderr}"

    except subprocess.TimeoutExpired:
        result.installed = False
        result.error = "Detection timeout"
    except Exception as e:
        result.installed = False
        result.error = str(e)

    return result


def check_claude_code(
    min_version: str = DEFAULT_CLAUDE_CODE_MIN_VERSION,
) -> DependencyCheckResult:
    """
    Check Claude Code installation status

    Args:
        min_version: Minimum version requirement (default 1.0.0)

    Returns:
        DependencyCheckResult containing check results
    """
    result = DependencyCheckResult(
        name="claude-code",
        required_version=min_version,
    )

    # Check if claude command exists
    claude_path = shutil.which("claude")
    if not claude_path:
        result.installed = False
        result.error = "Claude Code is not installed"
        return result

    result.path = claude_path

    try:
        # Get version
        version_output = subprocess.run(
            _prepare_command_for_windows(["claude", "--version"]),
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=5,
        )

        if version_output.returncode == 0:
            # Claude Code version output format: "2.0.53 (Claude Code)" or "1.0.0"
            output = version_output.stdout.strip()
            # Extract version number (take the part before first space, remove 'v' prefix)
            version = output.split()[0].lstrip("v") if output else ""

            result.installed = True
            result.version = version
            result.version_sufficient = compare_versions(version, min_version) >= 0
        else:
            result.installed = False
            result.error = f"Version detection failed: {version_output.stderr}"

    except subprocess.TimeoutExpired:
        result.installed = False
        result.error = "Detection timeout"
    except FileNotFoundError:
        result.installed = False
        result.error = "Claude Code command does not exist"
    except Exception as e:
        result.installed = False
        result.error = str(e)

    return result


def parallel_dependency_check() -> Dict[str, DependencyCheckResult]:
    """
    Check all dependencies in parallel

    Uses ThreadPoolExecutor to execute Node.js and Claude Code checks in parallel,
    reducing total check time.

    Returns:
        Dict[str, DependencyCheckResult]: Mapping from dependency name to check result
    """
    results: Dict[str, DependencyCheckResult] = {}

    with ThreadPoolExecutor(max_workers=2) as executor:
        # Submit check tasks
        future_to_name = {
            executor.submit(check_node): "node",
            executor.submit(check_claude_code): "claude-code",
        }

        # Collect results
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results[name] = future.result()
            except Exception as e:
                # Catch any unexpected exceptions
                results[name] = DependencyCheckResult(
                    name=name,
                    installed=False,
                    error=f"Check failed: {str(e)}",
                    required_version=(
                        DEFAULT_NODE_MIN_VERSION
                        if name == "node"
                        else DEFAULT_CLAUDE_CODE_MIN_VERSION
                    ),
                )

    return results


def get_missing_dependencies(
    results: Dict[str, DependencyCheckResult],
) -> list[str]:
    """
    Get list of dependencies that need to be installed

    Args:
        results: Return value from parallel_dependency_check()

    Returns:
        List of dependency names that need to be installed
    """
    return [name for name, result in results.items() if result.needs_install()]


def format_check_results(results: Dict[str, DependencyCheckResult]) -> str:
    """
    Format check results for display

    Args:
        results: Return value from parallel_dependency_check()

    Returns:
        Formatted string
    """
    lines = ["Dependency check results:", ""]
    for name in ["node", "claude-code"]:
        if name in results:
            lines.append(f"  {results[name].display_status()}")
    return "\n".join(lines)
