"""
Workspace Resource Management

Collects agent resources (skills, commands, CLAUDE.md, project memories, etc.)
from local machine into ~/.frago/workspaces/ for cross-device sync.

Architecture:
  - __system__: global ~/.claude/ resources
  - <canonical-id>: per-project .claude/ resources + project memory
"""

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from frago.compat import get_windows_subprocess_kwargs

logger = logging.getLogger(__name__)

# System-level directories
FRAGO_HOME = Path.home() / ".frago"
CLAUDE_HOME = Path.home() / ".claude"
WORKSPACES_DIR = FRAGO_HOME / "workspaces"
SYSTEM_WORKSPACE = WORKSPACES_DIR / "__system__"

# Files to always exclude when collecting project .claude/
PROJECT_CLAUDE_EXCLUDE = {
    "settings.local.json",
    ".mcp.local.json",
}

# Copy ignore patterns (cache, compiled files)
COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class ProjectInfo:
    """A discovered project on the local machine."""
    path: Path


@dataclass
class CollectResult:
    """Result of workspace collection."""
    system_collected: bool = False
    projects_collected: list[str] = field(default_factory=list)  # canonical IDs
    unidentified: list[Path] = field(default_factory=list)  # projects without canonical ID
    errors: list[str] = field(default_factory=list)


@dataclass
class WorkspaceChangeItem:
    """A single resource change detected in workspace after sync."""
    workspace: str       # "__system__" or canonical_id dirname (e.g. "github.com__user__repo")
    path: str            # relative path within workspace (e.g. "CLAUDE.md", "skills/git-linear-history")
    change_type: str     # "added", "modified", "deleted"

    @property
    def canonical_id(self) -> Optional[str]:
        """Convert dirname back to canonical ID, None for __system__."""
        if self.workspace == "__system__":
            return None
        return self.workspace.replace("__", "/")


@dataclass
class WorkspaceChanges:
    """Result of workspace change detection after sync."""
    items: list[WorkspaceChangeItem] = field(default_factory=list)
    source_device: Optional[str] = None

    @property
    def has_changes(self) -> bool:
        return len(self.items) > 0


# =============================================================================
# Canonical ID
# =============================================================================


def get_canonical_id(project_path: Path) -> Optional[str]:
    """Extract canonical ID from a project directory.

    Uses git remote origin URL, normalized to a stable form:
      https://github.com/user/repo.git  → github.com/user/repo
      git@github.com:user/repo.git      → github.com/user/repo

    Returns None for non-git projects or projects without a remote.
    """
    git_dir = project_path / ".git"
    if not git_dir.exists():
        return None

    try:
        result = subprocess.run(
            ["git", "-C", str(project_path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
            **get_windows_subprocess_kwargs(),
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return normalize_git_url(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def normalize_git_url(url: str) -> str:
    """Normalize a git remote URL to canonical form.

    Examples:
      https://github.com/user/repo.git → github.com/user/repo
      git@github.com:user/repo.git     → github.com/user/repo
      https://github.com/user/repo     → github.com/user/repo
    """
    url = url.strip()

    # SSH format: git@host:user/repo.git
    ssh_match = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", url)
    if ssh_match:
        host, path = ssh_match.group(1), ssh_match.group(2)
        return f"{host}/{path}"

    # HTTPS format: https://host/user/repo.git
    https_match = re.match(r"https?://([^/]+)/(.+?)(?:\.git)?$", url)
    if https_match:
        host, path = https_match.group(1), https_match.group(2)
        return f"{host}/{path}"

    return url


def canonical_id_to_dirname(canonical_id: str) -> str:
    """Convert canonical ID to directory name.

    github.com/user/repo → github.com__user__repo
    """
    return canonical_id.replace("/", "__")


# =============================================================================
# Project Discovery
# =============================================================================


def _discover_projects(
    scan_roots: list[str],
    exclude_patterns: list[str],
) -> list[ProjectInfo]:
    """Discover projects by scanning root directories.

    If scan_roots is empty, auto-detect common development directories
    under $HOME (repos, projects, work, src, dev, code, etc.).

    Only checks one level deep under each scan root.
    A directory is considered a project if it has .claude/ or .git/.
    """
    effective_roots = scan_roots if scan_roots else _auto_detect_scan_roots()

    projects: dict[str, ProjectInfo] = {}

    for root_str in effective_roots:
        root = Path(root_str).expanduser()
        if not root.exists() or not root.is_dir():
            continue
        try:
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                if _is_excluded(child, exclude_patterns):
                    continue
                if (child / ".claude").exists() or (child / ".git").exists():
                    projects[str(child)] = ProjectInfo(path=child)
        except PermissionError:
            logger.warning("Permission denied scanning: %s", root)

    return list(projects.values())


def _auto_detect_scan_roots() -> list[str]:
    """Auto-detect common development directories under $HOME.

    Scans well-known directory names that developers typically use.
    Returns only directories that actually exist.
    """
    home = Path.home()
    candidates = [
        "repos", "Repos",
        "projects", "Projects",
        "work", "Work",
        "src", "dev", "code",
        "workspace", "Workspace",
        "github", "GitHub",
    ]
    roots = []
    for name in candidates:
        path = home / name
        if path.is_dir():
            roots.append(str(path))

    if not roots:
        logger.debug("No common dev directories found, skipping auto-detect")

    return roots


def _is_excluded(path: Path, exclude_patterns: list[str]) -> bool:
    """Check if a path matches any exclude pattern."""
    name = path.name
    for pattern in exclude_patterns:
        if name == pattern:
            return True
        # Support simple glob: node_modules matches node_modules
        if pattern.startswith(".") and name == pattern:
            return True
    return False


def _encode_project_path(project_path: Path) -> str:
    """Encode project path to Claude Code's projects directory name.

    Path → encoded name is unambiguous (unlike the reverse direction).
    /Users/frago/Repos/frago → -Users-frago-Repos-frago
    """
    return "-" + str(project_path).lstrip("/").replace("/", "-")


# =============================================================================
# File Sync Utilities
# =============================================================================


def _sync_file(src: Path, dst: Path) -> bool:
    """Copy a single file if content differs. Returns True if copied."""
    if not src.exists() or not src.is_file():
        return False

    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists() and dst.is_file():
        # Compare content
        if src.read_bytes() == dst.read_bytes():
            return False

    shutil.copy2(src, dst)
    return True


def _sync_dir(
    src: Path,
    dst: Path,
    exclude_names: Optional[set[str]] = None,
) -> bool:
    """Sync a directory tree. Returns True if anything changed.

    Resolves symlinks to copy actual content.
    Handles exclude_names to skip specific files/dirs at the top level.
    """
    if not src.exists() or not src.is_dir():
        return False

    changed = False
    dst.mkdir(parents=True, exist_ok=True)

    # Track what exists in source (for deletion detection)
    src_names: set[str] = set()

    for item in src.iterdir():
        # Resolve symlinks
        real_item = item.resolve() if item.is_symlink() else item
        name = item.name

        if exclude_names and name in exclude_names:
            continue

        src_names.add(name)

        if real_item.is_file():
            if _sync_file(real_item, dst / name):
                changed = True
        elif real_item.is_dir():
            if _sync_dir(real_item, dst / name):
                changed = True

    # Remove entries in dst that no longer exist in src
    if dst.exists():
        for item in dst.iterdir():
            if item.name not in src_names:
                if exclude_names and item.name in exclude_names:
                    continue  # Don't delete excluded items
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
                changed = True

    return changed


def _is_file_git_tracked(project_path: Path, rel_path: str) -> bool:
    """Check if a file is tracked by the project's git."""
    try:
        result = subprocess.run(
            ["git", "-C", str(project_path), "ls-files", rel_path],
            capture_output=True,
            text=True,
            timeout=5,
            **get_windows_subprocess_kwargs(),
        )
        return bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return False


# =============================================================================
# Collection: System Workspace
# =============================================================================


def _collect_system_workspace(collected_memory_dirs: set[str]) -> bool:
    """Collect ~/.claude/ global resources → workspaces/__system__/.

    Resources collected:
      - CLAUDE.md (global agent instructions)
      - commands/ (slash commands)
      - skills/ (all skills, not just frago-*)
      - memories/ (Claude Code memories not mapped to any project)

    Returns True if anything changed.
    """
    target = SYSTEM_WORKSPACE
    changed = False

    # CLAUDE.md
    if _sync_file(CLAUDE_HOME / "CLAUDE.md", target / "CLAUDE.md"):
        changed = True

    # commands/ (slash commands, including subdirectories)
    if _sync_dir(CLAUDE_HOME / "commands", target / "commands"):
        changed = True

    # skills/ (ALL skills, not just frago-*)
    if _sync_dir(CLAUDE_HOME / "skills", target / "skills"):
        changed = True

    # Unmapped memories
    if _collect_unmapped_memories(target / "memories", collected_memory_dirs):
        changed = True

    return changed


def _collect_unmapped_memories(
    target: Path,
    collected_memory_dirs: set[str],
) -> bool:
    """Collect Claude Code memories not claimed by any project.

    These typically come from using Claude in home directory, repos root, etc.
    Stored with readable names (not path-encoded names, which are device-specific).
    """
    claude_projects = CLAUDE_HOME / "projects"
    if not claude_projects.exists():
        return False

    changed = False

    for encoded_dir in claude_projects.iterdir():
        if not encoded_dir.is_dir():
            continue
        if encoded_dir.name in collected_memory_dirs:
            continue  # Already claimed by a project

        memory_src = encoded_dir / "memory"
        if not memory_src.exists():
            continue

        # Generate readable name
        readable_name = _encoded_to_readable_name(encoded_dir.name)
        if _sync_dir(memory_src, target / readable_name):
            changed = True

    return changed


def _encoded_to_readable_name(encoded_name: str) -> str:
    """Convert Claude Code's path-encoded directory name to a readable name.

    -Users-frago → home (if it's the home directory)
    -Users-frago-Repos → repos-root
    """
    # Decode: -Users-frago-Repos-frago → /Users/frago/Repos/frago
    parts = encoded_name.lstrip("-").split("-")
    if not parts:
        return encoded_name

    # Reconstruct path
    path_str = "/" + "/".join(parts)
    path = Path(path_str)

    home = Path.home()

    if path == home:
        return "home"

    try:
        rel = path.relative_to(home)
        # ~/Repos → repos-root, ~/work → work-root
        return str(rel).lower().replace("/", "-") + "-root" if len(rel.parts) == 1 else str(rel).lower().replace("/", "-")
    except ValueError:
        # Not under home, use last component
        return path.name.lower() or encoded_name


# =============================================================================
# Collection: Project Workspace
# =============================================================================


def _collect_project_workspace(
    project: ProjectInfo,
    canonical_id: str,
) -> Optional[str]:
    """Collect project .claude/ → workspaces/<canonical-id>/.

    Returns the encoded memory directory name if project memory was found,
    None otherwise.
    """
    dirname = canonical_id_to_dirname(canonical_id)
    target = WORKSPACES_DIR / dirname

    # Project .claude/ contents (excluding device-specific files)
    src_claude = project.path / ".claude"
    if src_claude.exists():
        exclude = set(PROJECT_CLAUDE_EXCLUDE)

        # Conditionally exclude: if tracked by project git, project git manages it
        if _is_file_git_tracked(project.path, ".claude/settings.json"):
            exclude.add("settings.json")
        if _is_file_git_tracked(project.path, ".claude/.mcp.json"):
            exclude.add(".mcp.json")

        _sync_dir(src_claude, target / ".claude", exclude_names=exclude)

    # Project memory from Claude Code
    encoded_path = _encode_project_path(project.path)
    memory_src = CLAUDE_HOME / "projects" / encoded_path / "memory"
    if memory_src.exists():
        _sync_dir(memory_src, target / ".project-memory")
        return encoded_path

    return None


# =============================================================================
# Main Collection Entry Point
# =============================================================================


def collect_workspaces(
    scan_roots: list[str],
    exclude_patterns: list[str],
) -> CollectResult:
    """Collect all agent resources on this machine into workspaces.

    This is the main entry point called by sync().

    Steps:
      1. Discover projects via scan roots
      2. Collect each project's resources (+ project memory)
      3. Collect global resources → __system__ (+ unmapped memories)
    """
    result = CollectResult()

    # 1. Discover projects
    projects = _discover_projects(scan_roots, exclude_patterns)

    # 2. Collect each project
    collected_memory_dirs: set[str] = set()
    for project in projects:
        canonical_id = get_canonical_id(project.path)
        if canonical_id:
            encoded = _collect_project_workspace(project, canonical_id)
            if encoded:
                collected_memory_dirs.add(encoded)
            result.projects_collected.append(canonical_id)
        else:
            result.unidentified.append(project.path)

    # 3. Collect global resources → __system__
    _collect_system_workspace(collected_memory_dirs)
    result.system_collected = True

    return result


# =============================================================================
# Workspace Change Detection
# =============================================================================


def detect_workspace_changes(
    changed_files: list[tuple[str, str]],
) -> WorkspaceChanges:
    """Detect workspace changes from git diff output.

    Called after pull/rebase to identify what workspace resources were updated
    from remote.

    Args:
        changed_files: List of (status, file_path) from git diff --name-status.
                       status: "A" (added), "M" (modified), "D" (deleted)
                       file_path: relative to repo root

    Returns:
        WorkspaceChanges with items for each changed workspace resource.
    """
    changes = WorkspaceChanges()

    _STATUS_MAP = {"A": "added", "M": "modified", "D": "deleted"}

    for status, file_path in changed_files:
        if not file_path.startswith("workspaces/"):
            continue

        # workspaces/<workspace>/<rest>
        parts = file_path.split("/", 2)
        if len(parts) < 3:
            continue

        workspace = parts[1]
        rel_path = parts[2]
        change_type = _STATUS_MAP.get(status[0], "modified")

        # De-duplicate: group by workspace + top-level resource
        # e.g. "skills/git-xxx/file1.md" and "skills/git-xxx/file2.md"
        # both map to resource "skills/git-xxx"
        changes.items.append(WorkspaceChangeItem(
            workspace=workspace,
            path=rel_path,
            change_type=change_type,
        ))

    return changes


def summarize_workspace_changes(changes: WorkspaceChanges) -> list[dict]:
    """Summarize workspace changes into resource-level entries for display.

    Groups file-level changes into resource-level summaries:
      - skills/git-xxx/a.md + skills/git-xxx/b.md → "skills/git-xxx" (modified)
      - CLAUDE.md → "CLAUDE.md" (modified)

    Returns list of dicts: {"workspace", "resource", "change_type"}
    """
    seen: dict[tuple[str, str], str] = {}  # (workspace, resource) → change_type

    for item in changes.items:
        # Determine resource-level path (top-level resource within workspace)
        path_parts = item.path.split("/")
        if len(path_parts) >= 2:
            # e.g. skills/git-xxx/... → "skills/git-xxx"
            # e.g. .claude/docs/arch.md → ".claude/docs"
            resource = "/".join(path_parts[:2])
        else:
            resource = item.path

        key = (item.workspace, resource)
        # Prefer "added" > "modified" > "deleted" when merging
        if key not in seen:
            seen[key] = item.change_type
        elif seen[key] != item.change_type:
            seen[key] = "modified"  # mixed changes → modified

    return [
        {"workspace": ws, "resource": res, "change_type": ct}
        for (ws, res), ct in sorted(seen.items())
    ]


# =============================================================================
# Migration: Legacy ~/.frago/.claude/ → workspaces/__system__/
# =============================================================================


MIGRATION_FLAG = FRAGO_HOME / ".workspace_migrated"


def migrate_legacy_claude_dir() -> bool:
    """One-time migration: ~/.frago/.claude/ → ~/.frago/workspaces/__system__/.

    Moves existing skills from the old location to the new workspace structure.
    Uses a flag file to track migration state (not target directory existence,
    which can be created by collect_workspaces() running before migration).

    Returns True if migration was performed.
    """
    legacy = FRAGO_HOME / ".claude"

    # Already migrated (flag file exists)
    if MIGRATION_FLAG.exists():
        return False

    # Nothing to migrate
    if not legacy.exists():
        # No legacy dir, but mark as migrated so we don't check again
        MIGRATION_FLAG.write_text("migrated", encoding="utf-8")
        return False

    logger.info("Migrating ~/.frago/.claude/ → workspaces/__system__/")
    target = SYSTEM_WORKSPACE
    target.mkdir(parents=True, exist_ok=True)

    # Migrate skills (only if target doesn't already have them from collect)
    legacy_skills = legacy / "skills"
    target_skills = target / "skills"
    if legacy_skills.exists() and not target_skills.exists():
        shutil.copytree(
            legacy_skills,
            target_skills,
            ignore=COPY_IGNORE,
        )
        logger.info("Migrated %d skills", len(list(legacy_skills.iterdir())))

    # Migrate sync_metadata.json (adjust entry keys)
    legacy_metadata = legacy / "sync_metadata.json"
    if legacy_metadata.exists():
        _migrate_metadata_entries(legacy_metadata, target)

    # Git rm: remove old .claude/ files from git tracking
    _git_rm_legacy_claude(legacy)

    # Remove legacy directory from filesystem
    shutil.rmtree(legacy, ignore_errors=True)
    logger.info("Removed legacy ~/.frago/.claude/")

    # Write migration flag
    MIGRATION_FLAG.write_text("migrated", encoding="utf-8")

    return True


def _git_rm_legacy_claude(legacy: Path) -> None:
    """Remove legacy .claude/ files from git tracking.

    Uses `git rm -r --cached` to untrack without deleting working tree files
    (though we'll delete them right after anyway).
    """
    if not (FRAGO_HOME / ".git").exists():
        return

    try:
        result = subprocess.run(
            ["git", "-C", str(FRAGO_HOME), "rm", "-r", "--cached", "--ignore-unmatch",
             str(legacy.relative_to(FRAGO_HOME))],
            capture_output=True,
            text=True,
            timeout=10,
            **get_windows_subprocess_kwargs(),
        )
        if result.returncode == 0:
            logger.info("Removed .claude/ from git tracking")
        else:
            logger.warning("git rm failed: %s", result.stderr)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("git rm failed: %s", e)


def _migrate_metadata_entries(legacy_metadata_path: Path, target: Path) -> None:
    """Migrate sync_metadata.json entries to workspace-relative paths."""
    try:
        data = json.loads(legacy_metadata_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "entries" not in data:
            return

        new_entries = {}
        for key, value in data.get("entries", {}).items():
            # Remap: skills/frago-xxx → workspaces/__system__/skills/frago-xxx
            new_key = f"workspaces/__system__/{key}"
            new_entries[new_key] = value

        data["entries"] = new_entries
        data["version"] = 2  # Bump version

        out_path = target / "sync_metadata.json"
        out_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Failed to migrate sync metadata: %s", e)
