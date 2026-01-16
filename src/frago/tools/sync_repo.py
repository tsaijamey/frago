"""
Sync module - Sync ~/.frago/ as a Git repository

Treat ~/.frago/ as a Git working directory and sync to user-configured remote repository.
Supports idempotency checks with ~/.claude/ to ensure resources are not lost.
"""

import filecmp
import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import click

from frago.compat import get_windows_subprocess_kwargs

# System-level directories
FRAGO_HOME = Path.home() / ".frago"
CLAUDE_HOME = Path.home() / ".claude"

# ~/.frago/.claude/ subdirectory (Git tracked)
FRAGO_CLAUDE_DIR = FRAGO_HOME / ".claude"
FRAGO_SKILLS_DIR = FRAGO_CLAUDE_DIR / "skills"
FRAGO_RECIPES_DIR = FRAGO_HOME / "recipes"

# ~/.claude/ runtime directory
CLAUDE_SKILLS_DIR = CLAUDE_HOME / "skills"

# Metadata file for tracking skill mtimes (stored in repo, synced across devices)
SKILLS_METADATA_FILE = FRAGO_CLAUDE_DIR / "skills_metadata.json"
SKILLS_METADATA_VERSION = 1


@dataclass
class FileChange:
    """File change information"""

    type: str  # "Command", "Skill", "Recipe", "Other"
    name: str
    operation: str  # "Modified", "Added", "Deleted"
    timestamp: Optional[datetime] = None


@dataclass
class SyncResult:
    """Sync result"""

    success: bool = False
    local_changes: list[FileChange] = field(default_factory=list)
    remote_updates: list[FileChange] = field(default_factory=list)
    pushed_to_remote: bool = False
    conflicts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)  # Warning messages
    is_public_repo: bool = False  # Whether it's a public repository


@dataclass
class FileConflict:
    """File conflict information"""

    file_path: str
    local_mtime: datetime
    remote_mtime: datetime


def _get_subprocess_kwargs() -> Dict[str, Any]:
    """Get subprocess kwargs with Windows hidden window support."""
    return get_windows_subprocess_kwargs()


def _run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """Execute git command"""
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=check,
        **_get_subprocess_kwargs(),
    )


def _is_git_repo(path: Path) -> bool:
    """Check if directory is a Git repository"""
    return (path / ".git").exists()


def _ensure_git_user_config(repo_dir: Path) -> tuple[bool, str]:
    """Ensure git user.name and user.email are configured.

    If not configured, fetch from gh CLI and set locally.

    Args:
        repo_dir: Git repository directory

    Returns:
        (success, error_message) tuple
    """
    # Check if already configured (local or global)
    name_result = _run_git(["config", "user.name"], repo_dir, check=False)
    email_result = _run_git(["config", "user.email"], repo_dir, check=False)

    if name_result.returncode == 0 and email_result.returncode == 0:
        if name_result.stdout.strip() and email_result.stdout.strip():
            return True, ""

    # Fetch from gh api user
    try:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login,.email"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=10,
            **_get_subprocess_kwargs(),
        )
        if result.returncode != 0:
            return False, "Failed to get user info from gh CLI. Run 'gh auth login' first."

        lines = result.stdout.strip().split('\n')
        if len(lines) < 2:
            return False, "Failed to parse user info from gh CLI"

        username = lines[0].strip()
        email = lines[1].strip()

        # Handle null/empty email (GitHub privacy setting)
        if not email or email == "null":
            email = f"{username}@users.noreply.github.com"

        # Set local git config (not global)
        _run_git(["config", "user.name", username], repo_dir)
        _run_git(["config", "user.email", email], repo_dir)

        return True, ""
    except FileNotFoundError:
        return False, "gh CLI not found. Please install GitHub CLI first."
    except subprocess.TimeoutExpired:
        return False, "gh CLI timed out"


def _has_uncommitted_changes(repo_dir: Path) -> bool:
    """Check if there are uncommitted changes"""
    result = _run_git(["status", "--porcelain"], repo_dir, check=False)
    return bool(result.stdout.strip())


def _get_changed_files(repo_dir: Path) -> list[str]:
    """Get list of modified files"""
    result = _run_git(["status", "--porcelain"], repo_dir, check=False)
    files = []
    for line in result.stdout.strip().split("\n"):
        if line:
            # Format: XY filename or XY -> renamed
            parts = line[3:].split(" -> ")
            files.append(parts[-1])
    return files


def _ensure_gitignore(repo_dir: Path) -> None:
    """Ensure .gitignore file exists and contains correct exclusion rules"""
    gitignore_path = repo_dir / ".gitignore"
    gitignore_content = """# Runtime data (not synced)
sessions/
sessions.json
chrome_profile/
current_run
projects/.tmp/

# Commands directory (managed by frago itself, not synced)
.claude/commands/

# Local metadata (device-specific, not synced)
.claude/skills_metadata.json
.claude/settings.local.json

# Config files (contain sensitive information)
config.json

# Environment variable files (sensitive information)
.env
.env.*
.env.local
.env.*.local

# System files
.DS_Store
__pycache__/
*.pyc
*.bak
*.bak.*
server.pid
gui_history.jsonl

# Video files
*.mp4
*.avi
*.mov
*.mkv
*.wmv
*.flv
*.webm

# Audio files
*.wav
*.mp3
*.aac
*.flac
*.ogg
*.m4a

# Log files
logs/
*.log

# Archives and other large files
*.zip
*.tar
*.tar.gz
*.rar
*.7z
*.pdf
*.psd
*.ai
"""

    if not gitignore_path.exists():
        gitignore_path.write_text(gitignore_content, encoding="utf-8")
    else:
        # Check existing content, append if missing key rules
        existing = gitignore_path.read_text(encoding="utf-8")
        needed_rules = [
            # Runtime data
            "sessions/", "sessions.json", "chrome_profile/", "current_run", "config.json", "projects/.tmp/", ".env",
            # Commands directory (managed by frago itself)
            ".claude/commands/",
            # Local metadata (device-specific)
            ".claude/skills_metadata.json", ".claude/settings.local.json",
            # System files
            ".DS_Store", "__pycache__/", "server.pid", "gui_history.jsonl",
            # Large file types
            "*.mp4", "*.wav", "*.log", "logs/", "*.pdf", "*.psd", "*.ai",
        ]
        missing = [rule for rule in needed_rules if rule not in existing]
        if missing:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.write("\n# Auto-added by frago sync\n")
                for rule in missing:
                    f.write(f"{rule}\n")

    # Automatically untrack .tmp directory (if already tracked)
    _untrack_ignored_paths(repo_dir)


def _untrack_ignored_paths(repo_dir: Path) -> None:
    """Untrack paths that should be ignored but are still tracked

    Fixes issue where .tmp, .claude/commands, .DS_Store etc. are already tracked on existing devices.
    """
    # Path patterns that need to be untracked
    paths_to_untrack = [
        # Directories
        "projects/.tmp/", ".claude/commands/",
        # System files
        ".DS_Store", "**/.DS_Store", "*.pyc", "*.bak", "*.bak.*", "*.log",
        # Video files
        "*.mp4", "*.avi", "*.mov", "*.mkv", "*.wmv", "*.flv", "*.webm",
        # Audio files
        "*.wav", "*.mp3", "*.aac", "*.flac", "*.ogg", "*.m4a",
        # Archives and large files
        "*.zip", "*.tar", "*.tar.gz", "*.rar", "*.7z", "*.pdf", "*.psd", "*.ai",
    ]

    for path_pattern in paths_to_untrack:
        # For glob patterns like *.pdf, also match in subdirectories
        patterns = [path_pattern]
        if path_pattern.startswith("*."):
            patterns.append(f"**/{path_pattern}")

        # Check if any files matching the pattern are tracked
        result = _run_git(
            ["ls-files", "-z", "--"] + patterns,
            repo_dir,
            check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            # Files are tracked, untrack them one by one (handles special chars in filenames)
            tracked_files = [f for f in result.stdout.split('\0') if f]
            for tracked_file in tracked_files:
                _run_git(
                    ["rm", "--cached", "--quiet", "--", tracked_file],
                    repo_dir,
                    check=False
                )


def _parse_repo_owner_name(repo_url: str) -> tuple[Optional[str], Optional[str]]:
    """Parse owner and repo name from repository URL

    Supported formats:
    - git@github.com:owner/repo.git
    - https://github.com/owner/repo.git
    - https://github.com/owner/repo

    Returns:
        (owner, repo) tuple, returns (None, None) if parsing fails
    """
    import re

    # SSH format: git@github.com:owner/repo.git
    ssh_match = re.match(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", repo_url)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)

    # HTTPS format: https://github.com/owner/repo.git
    https_match = re.match(r"https://github\.com/([^/]+)/([^/]+?)(?:\.git)?$", repo_url)
    if https_match:
        return https_match.group(1), https_match.group(2)

    return None, None


def _check_repo_visibility(repo_url: str) -> Optional[str]:
    """Check GitHub repository visibility

    Args:
        repo_url: Repository URL (SSH or HTTPS format)

    Returns:
        "public" / "private" / None (unable to detect)
    """
    owner, repo = _parse_repo_owner_name(repo_url)
    if not owner or not repo:
        return None

    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{owner}/{repo}", "--jq", ".visibility"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=10,
            **_get_subprocess_kwargs(),
        )
        if result.returncode == 0:
            visibility = result.stdout.strip().lower()
            if visibility in ("public", "private"):
                return visibility
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # gh command timed out or not installed
        pass

    return None


def _check_and_remove_tracked_env(repo_dir: Path) -> list[str]:
    """Check and remove .env files that are already tracked by git

    If .env related files are already tracked by git, execute git rm --cached to remove but keep local files

    Args:
        repo_dir: Git repository directory

    Returns:
        List of removed files
    """
    removed_files = []

    # Check which .env files are tracked
    result = _run_git(["ls-files", "--", ".env", ".env.*"], repo_dir, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return removed_files

    tracked_env_files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]

    for env_file in tracked_env_files:
        # Remove from git index but keep local file
        rm_result = _run_git(["rm", "--cached", env_file], repo_dir, check=False)
        if rm_result.returncode == 0:
            removed_files.append(env_file)

    return removed_files


def _classify_file(file_path: str) -> tuple[str, str]:
    """Classify file type and name

    Args:
        file_path: File path relative to repository root

    Returns:
        (type, name) tuple
    """
    path_obj = Path(file_path)

    if file_path.startswith(".claude/skills/"):
        # Skills are directories: .claude/skills/frago-xxx/... -> frago-xxx
        parts = path_obj.parts
        if len(parts) >= 3:
            return ("Skill", parts[2])
        return ("Skill", path_obj.name)
    elif file_path.startswith("recipes/"):
        # Recipe: recipes/atomic/xxx.json -> xxx
        # Or: recipes/workflows/yyy/ -> yyy
        parts = path_obj.parts
        if len(parts) >= 3:
            # Extract filename (without extension) or directory name
            name = parts[2]
            if path_obj.suffix == ".json":
                name = path_obj.stem
            return ("Recipe", name)
        return ("Recipe", path_obj.name)

    return ("Other", path_obj.name)


def _get_file_change_info(repo_dir: Path, file_path: str) -> FileChange:
    """Get detailed file change information

    Args:
        repo_dir: Git repository directory
        file_path: File path relative to repository root

    Returns:
        FileChange object
    """
    file_type, name = _classify_file(file_path)

    # Try to get timestamp from Git
    result = _run_git(["log", "--format=%aI", "-1", "--", file_path], repo_dir, check=False)
    timestamp = None

    if result.returncode == 0 and result.stdout.strip():
        try:
            # Remove timezone marker 'Z' or convert to Python-supported format
            iso_time = result.stdout.strip()
            if iso_time.endswith('Z'):
                iso_time = iso_time[:-1] + '+00:00'
            timestamp = datetime.fromisoformat(iso_time)
        except ValueError:
            pass

    # If no Git history, use filesystem time
    if timestamp is None:
        full_path = repo_dir / file_path
        if full_path.exists():
            if full_path.is_file():
                mtime = os.path.getmtime(full_path)
                timestamp = datetime.fromtimestamp(mtime)
            elif full_path.is_dir():
                # For directories, use directory's own mtime
                mtime = os.path.getmtime(full_path)
                timestamp = datetime.fromtimestamp(mtime)

    # Detect operation type
    status_result = _run_git(["status", "--porcelain", "--", file_path], repo_dir, check=False)
    operation = "Modified"
    if status_result.stdout:
        status_code = status_result.stdout[:2]
        if 'A' in status_code:
            operation = "Added"
        elif 'D' in status_code:
            operation = "Deleted"
        elif 'M' in status_code:
            operation = "Modified"

    return FileChange(type=file_type, name=name, operation=operation, timestamp=timestamp)


def _format_table(changes: list[FileChange], title: str) -> str:
    """Format change table

    Args:
        changes: File change list
        title: Table title

    Returns:
        Formatted table string
    """
    if not changes:
        return ""

    lines = [f"\n{title}:"]
    lines.append(f"{'Type':<10} {'Name':<40} {'Operation':<10} {'Time':<20}")
    lines.append("─" * 80)

    for change in changes:
        time_str = change.timestamp.strftime("%Y-%m-%d %H:%M") if change.timestamp else "—"
        lines.append(f"{change.type:<10} {change.name:<40} {change.operation:<10} {time_str:<20}")

    return "\n".join(lines)


def _init_git_repo(repo_dir: Path, remote_url: str) -> None:
    """Initialize Git repository"""
    repo_dir.mkdir(parents=True, exist_ok=True)

    # Initialize
    _run_git(["init"], repo_dir)

    # Add remote
    _run_git(["remote", "add", "origin", remote_url], repo_dir, check=False)

    # Create .gitignore
    _ensure_gitignore(repo_dir)


def _safe_copy_tree(src: Path, dst: Path) -> None:
    """Safely copy directory tree, skipping special files (socket, symlink, etc.)"""
    dst.mkdir(parents=True, exist_ok=True)

    for item in src.iterdir():
        src_item = item
        dst_item = dst / item.name

        if src_item.is_symlink():
            # Skip symbolic links
            continue
        elif src_item.is_file():
            try:
                shutil.copy2(src_item, dst_item)
            except (OSError, IOError):
                # Skip files that cannot be copied (socket, special devices, etc.)
                pass
        elif src_item.is_dir():
            _safe_copy_tree(src_item, dst_item)


def _clone_or_init_repo(repo_url: str) -> tuple[bool, str]:
    """
    Clone or initialize repository

    If remote repository exists, clone to ~/.frago/
    If remote repository is empty or doesn't exist, initialize local repository

    Returns:
        (success, message)
    """
    if _is_git_repo(FRAGO_HOME):
        return True, "Repository already exists"

    # Try to clone to temporary directory
    temp_dir = FRAGO_HOME.parent / ".frago_clone_temp"
    # Runtime directories/files to preserve (excluding projects, as it will be synced)
    runtime_items = ["sessions", "chrome_profile", "config.json", "current_run"]

    try:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

        result = subprocess.run(
            ["git", "clone", repo_url, str(temp_dir)],
            capture_output=True,
            text=True,
            encoding='utf-8',
            **_get_subprocess_kwargs(),
        )

        if result.returncode == 0:
            # Clone successful, move content to ~/.frago/
            # Preserve existing runtime directories
            preserved = {}

            for item in runtime_items:
                src = FRAGO_HOME / item
                if src.exists():
                    preserved[item] = temp_dir.parent / f".frago_preserve_{item}"
                    if src.is_file():
                        shutil.copy2(src, preserved[item])
                    elif src.is_dir():
                        _safe_copy_tree(src, preserved[item])

            # Move cloned content
            if FRAGO_HOME.exists():
                shutil.rmtree(FRAGO_HOME)
            shutil.move(str(temp_dir), str(FRAGO_HOME))

            # Restore runtime directories
            for item, preserved_path in preserved.items():
                target = FRAGO_HOME / item
                if preserved_path.exists():
                    if preserved_path.is_file():
                        shutil.copy2(preserved_path, target)
                        preserved_path.unlink()
                    elif preserved_path.is_dir():
                        if target.exists():
                            shutil.rmtree(target)
                        shutil.move(str(preserved_path), str(target))

            _ensure_gitignore(FRAGO_HOME)
            return True, "Fetched resources from your repository"
        else:
            # Clone failed, possibly empty repository, initialize local
            _init_git_repo(FRAGO_HOME, repo_url)
            return True, "Initialized local repository (your repository is empty or doesn't exist)"

    except Exception as e:
        return False, f"Initialization failed: {e}"
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        # Clean up potentially leftover preserve directories
        for item in runtime_items:
            preserve_path = FRAGO_HOME.parent / f".frago_preserve_{item}"
            if preserve_path.exists():
                if preserve_path.is_dir():
                    shutil.rmtree(preserve_path)
                else:
                    preserve_path.unlink()


def _files_are_identical(file1: Path, file2: Path) -> bool:
    """Compare if two files have identical content"""
    if not file1.exists() or not file2.exists():
        return False
    return filecmp.cmp(file1, file2, shallow=False)


def _dir_files_identical(dir1: Path, dir2: Path) -> bool:
    """Compare if contents of two directories are identical"""
    if not dir1.exists() or not dir2.exists():
        return dir1.exists() == dir2.exists()

    # Get all files
    files1 = set(f.relative_to(dir1) for f in dir1.rglob("*") if f.is_file())
    files2 = set(f.relative_to(dir2) for f in dir2.rglob("*") if f.is_file())

    if files1 != files2:
        return False

    for rel_path in files1:
        if not _files_are_identical(dir1 / rel_path, dir2 / rel_path):
            return False

    return True


def _get_file_mtime(path: Path) -> float:
    """Get file modification time"""
    if path.exists() and path.is_file():
        return os.path.getmtime(path)
    return 0.0


def _get_dir_latest_mtime(dir_path: Path) -> float:
    """Get latest file modification time in directory"""
    if not dir_path.exists() or not dir_path.is_dir():
        return 0.0

    latest_mtime = 0.0
    for f in dir_path.rglob("*"):
        if f.is_file():
            mtime = os.path.getmtime(f)
            if mtime > latest_mtime:
                latest_mtime = mtime
    return latest_mtime


def _is_source_newer(src: Path, target: Path) -> bool:
    """Check if source file/directory is newer than target

    Args:
        src: Source path
        target: Target path

    Returns:
        True if source is newer than target, or target doesn't exist
    """
    if not target.exists():
        return True

    if src.is_file():
        return _get_file_mtime(src) > _get_file_mtime(target)
    elif src.is_dir():
        return _get_dir_latest_mtime(src) > _get_dir_latest_mtime(target)

    return False


def _get_git_commit_time(repo_dir: Path, rel_path: str) -> float:
    """Get the git commit time (author date) for a file/directory

    Args:
        repo_dir: Git repository root directory
        rel_path: Relative path from repo root

    Returns:
        Unix timestamp of last commit, or 0.0 if not tracked
    """
    result = _run_git(["log", "-1", "--format=%at", "--", rel_path], repo_dir, check=False)
    if result.returncode == 0 and result.stdout.strip():
        try:
            return float(result.stdout.strip())
        except ValueError:
            return 0.0
    return 0.0


def _is_repo_newer_than_local(repo_dir: Path, repo_rel_path: str, local_path: Path) -> bool:
    """Check if repo version is newer than local version

    Compares git commit time (repo) vs file mtime (local).
    This is more reliable than comparing mtimes, since git pull
    sets mtime to checkout time, not original commit time.

    Args:
        repo_dir: Git repository root
        repo_rel_path: Relative path in repo
        local_path: Local file/directory path

    Returns:
        True if repo version is newer, or local doesn't exist
    """
    if not local_path.exists():
        return True

    repo_commit_time = _get_git_commit_time(repo_dir, repo_rel_path)
    if repo_commit_time == 0.0:
        # Not tracked in git, fall back to mtime comparison
        repo_path = repo_dir / repo_rel_path
        if repo_path.is_dir():
            return _get_dir_latest_mtime(repo_path) > _get_dir_latest_mtime(local_path)
        return False

    if local_path.is_dir():
        local_mtime = _get_dir_latest_mtime(local_path)
    else:
        local_mtime = _get_file_mtime(local_path)

    return repo_commit_time > local_mtime


# =============================================================================
# Skills Metadata Management
# =============================================================================


def _load_skills_metadata() -> Dict[str, Any]:
    """Load skills metadata from JSON file

    Returns a dict with structure:
    {
        "version": 1,
        "skills": {
            "skill-name": {"mtime": 1234567890.0},
            ...
        }
    }

    Error handling:
    - File not exists: return empty structure
    - JSON parse error: log warning, return empty structure
    - Version mismatch: migrate or return empty structure
    """
    empty_metadata = {"version": SKILLS_METADATA_VERSION, "skills": {}}

    if not SKILLS_METADATA_FILE.exists():
        return empty_metadata

    try:
        content = SKILLS_METADATA_FILE.read_text(encoding="utf-8")
        metadata = json.loads(content)

        # Validate structure
        if not isinstance(metadata, dict):
            click.echo(f"Warning: Invalid metadata format, recreating", err=True)
            return empty_metadata

        # Check version
        version = metadata.get("version", 0)
        if version != SKILLS_METADATA_VERSION:
            # Future: implement migration logic here
            click.echo(f"Warning: Metadata version mismatch ({version} != {SKILLS_METADATA_VERSION}), recreating", err=True)
            return empty_metadata

        # Ensure skills dict exists
        if "skills" not in metadata or not isinstance(metadata["skills"], dict):
            metadata["skills"] = {}

        return metadata

    except json.JSONDecodeError as e:
        click.echo(f"Warning: Failed to parse metadata file: {e}, recreating", err=True)
        return empty_metadata
    except Exception as e:
        click.echo(f"Warning: Failed to load metadata file: {e}, recreating", err=True)
        return empty_metadata


def _save_skills_metadata(metadata: Dict[str, Any]) -> bool:
    """Save skills metadata to JSON file

    Returns:
        True if saved successfully, False otherwise
    """
    try:
        # Ensure parent directory exists
        SKILLS_METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Ensure version is set
        metadata["version"] = SKILLS_METADATA_VERSION

        content = json.dumps(metadata, indent=2, ensure_ascii=False)
        SKILLS_METADATA_FILE.write_text(content, encoding="utf-8")
        return True

    except Exception as e:
        click.echo(f"Warning: Failed to save metadata file: {e}", err=True)
        return False


def _update_skill_metadata(metadata: Dict[str, Any], skill_name: str, mtime: float) -> None:
    """Update a single skill's metadata

    Args:
        metadata: The metadata dict to update (modified in place)
        skill_name: Name of the skill
        mtime: The modification time to record
    """
    if "skills" not in metadata:
        metadata["skills"] = {}
    metadata["skills"][skill_name] = {"mtime": mtime}


def _remove_skill_metadata(metadata: Dict[str, Any], skill_name: str) -> None:
    """Remove a skill from metadata

    Args:
        metadata: The metadata dict to update (modified in place)
        skill_name: Name of the skill to remove
    """
    if "skills" in metadata and skill_name in metadata["skills"]:
        del metadata["skills"][skill_name]


def _get_skill_metadata_mtime(metadata: Dict[str, Any], skill_name: str) -> Optional[float]:
    """Get a skill's mtime from metadata

    Returns:
        The recorded mtime, or None if not found
    """
    skills = metadata.get("skills", {})
    skill_data = skills.get(skill_name, {})
    return skill_data.get("mtime")


def _is_metadata_newer_than_local(metadata: Dict[str, Any], skill_name: str, local_path: Path) -> bool:
    """Check if metadata mtime is newer than local file mtime

    This is used to determine if the repo version should overwrite local.
    The metadata records the actual mtime when a skill was synced,
    which is more reliable than git commit time or file checkout time.

    Args:
        metadata: The loaded metadata dict
        skill_name: Name of the skill
        local_path: Local skill directory path

    Returns:
        True if metadata mtime > local mtime (should overwrite)
        False if metadata mtime <= local mtime (keep local)
        False if metadata has no record for this skill (conservative: don't overwrite)
    """
    metadata_mtime = _get_skill_metadata_mtime(metadata, skill_name)

    # If no metadata record, be conservative and don't overwrite local
    if metadata_mtime is None:
        return False

    # If local doesn't exist, allow sync
    if not local_path.exists():
        return True

    # Compare metadata mtime with local mtime
    if local_path.is_dir():
        local_mtime = _get_dir_latest_mtime(local_path)
    else:
        local_mtime = _get_file_mtime(local_path)

    return metadata_mtime > local_mtime


def _sync_claude_to_frago(result: SyncResult, dry_run: bool = False) -> None:
    """
    Sync changes from ~/.claude/ to ~/.frago/.claude/

    Check ~/.claude/skills/frago-*
    Only copy when version in ~/.claude/ is newer than ~/.frago/.claude/
    Also detect deletions: remove from repo if deleted locally
    Records mtime metadata for cross-device sync comparison.
    """
    # Load existing metadata
    metadata = _load_skills_metadata()
    metadata_changed = False

    # Sync skills - copy new/updated
    if CLAUDE_SKILLS_DIR.exists():
        FRAGO_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

        for skill_dir in CLAUDE_SKILLS_DIR.iterdir():
            if not skill_dir.is_dir():
                continue
            if not skill_dir.name.startswith("frago-"):
                continue

            target_skill_dir = FRAGO_SKILLS_DIR / skill_dir.name
            local_mtime = _get_dir_latest_mtime(skill_dir)

            # Only copy when content differs and source directory is newer
            if not _dir_files_identical(skill_dir, target_skill_dir) and _is_source_newer(skill_dir, target_skill_dir):
                if not dry_run:
                    if target_skill_dir.exists():
                        shutil.rmtree(target_skill_dir)
                    shutil.copytree(
                        skill_dir, target_skill_dir, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
                    )
                    # Record mtime in metadata
                    _update_skill_metadata(metadata, skill_dir.name, local_mtime)
                    metadata_changed = True
                # Collect change information
                file_path = f".claude/skills/{skill_dir.name}"
                change = _get_file_change_info(FRAGO_HOME, file_path)
                result.local_changes.append(change)
            else:
                # Even if not syncing, ensure metadata is up-to-date for existing skills
                existing_mtime = _get_skill_metadata_mtime(metadata, skill_dir.name)
                if existing_mtime is None or abs(existing_mtime - local_mtime) > 1.0:
                    if not dry_run:
                        _update_skill_metadata(metadata, skill_dir.name, local_mtime)
                        metadata_changed = True

    # Sync skills - detect deletions (repo has but local doesn't)
    if FRAGO_SKILLS_DIR.exists() and CLAUDE_SKILLS_DIR.exists():
        local_skills = {d.name for d in CLAUDE_SKILLS_DIR.iterdir() if d.is_dir() and d.name.startswith("frago-")}

        for repo_skill_dir in list(FRAGO_SKILLS_DIR.iterdir()):
            if not repo_skill_dir.is_dir():
                continue
            if not repo_skill_dir.name.startswith("frago-"):
                continue

            # If repo has skill but local doesn't, delete from repo
            if repo_skill_dir.name not in local_skills:
                if not dry_run:
                    shutil.rmtree(repo_skill_dir)
                    # Remove from metadata
                    _remove_skill_metadata(metadata, repo_skill_dir.name)
                    metadata_changed = True
                # Record deletion
                result.local_changes.append(
                    FileChange(
                        type="Skill",
                        name=repo_skill_dir.name,
                        operation="Deleted",
                        timestamp=None,
                    )
                )

    # Save metadata if changed
    if metadata_changed and not dry_run:
        _save_skills_metadata(metadata)

    # Display table immediately
    if result.local_changes:
        click.echo(_format_table(result.local_changes, "Local Changes"))


def _sync_frago_to_claude(result: SyncResult, dry_run: bool = False) -> None:
    """
    Sync content from ~/.frago/.claude/ to ~/.claude/

    After fetching updates from repository, deploy resources to Claude Code runtime directory.
    Uses metadata mtime comparison to avoid overwriting local changes with stale remote versions.

    The metadata file (skills_metadata.json) records the actual mtime when each skill was synced,
    which is more reliable than git commit time (which reflects commit time, not file mtime)
    or file checkout time (which reflects pull time, not original mtime).
    """
    # Load metadata for comparison
    metadata = _load_skills_metadata()

    # Sync skills
    if FRAGO_SKILLS_DIR.exists():
        CLAUDE_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

        for skill_dir in FRAGO_SKILLS_DIR.iterdir():
            if not skill_dir.is_dir():
                continue
            if not skill_dir.name.startswith("frago-"):
                continue

            target_skill_dir = CLAUDE_SKILLS_DIR / skill_dir.name

            # Only copy when content differs AND metadata mtime is newer than local mtime
            if not _dir_files_identical(skill_dir, target_skill_dir) and _is_metadata_newer_than_local(
                metadata, skill_dir.name, target_skill_dir
            ):
                if not dry_run:
                    if target_skill_dir.exists():
                        shutil.rmtree(target_skill_dir)
                    shutil.copytree(
                        skill_dir, target_skill_dir, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
                    )


def _save_local_changes(result: SyncResult, message: Optional[str], dry_run: bool = False) -> bool:
    """
    Save local changes (git add + commit)

    Returns:
        Whether changes were saved
    """
    if not _has_uncommitted_changes(FRAGO_HOME):
        return False

    changed_files = _get_changed_files(FRAGO_HOME)

    if dry_run:
        return True

    # Ensure git user is configured before commit
    success, error = _ensure_git_user_config(FRAGO_HOME)
    if not success:
        result.errors.append(error)
        return False

    # git add
    _run_git(["add", "."], FRAGO_HOME)

    # git commit
    commit_message = message or f"sync: Save local changes ({len(changed_files)} files)"
    _run_git(["commit", "-m", commit_message], FRAGO_HOME)

    return True


def _pull_remote_updates(result: SyncResult, dry_run: bool = False) -> bool:
    """
    Pull remote updates

    Returns:
        Whether there are conflicts
    """
    if dry_run:
        return False

    # Check if there's a remote repository
    remote_result = _run_git(["remote", "-v"], FRAGO_HOME, check=False)
    if not remote_result.stdout.strip():
        return False

    # fetch
    click.echo("Fetching latest resources from your repository...")
    fetch_result = _run_git(["fetch", "origin"], FRAGO_HOME, check=False)
    if fetch_result.returncode != 0:
        # Possibly new repository, no remote branch
        return False

    # Check if remote branch exists
    branch_result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], FRAGO_HOME, check=False)
    current_branch = branch_result.stdout.strip() or "main"

    # Check if remote branch exists
    remote_branch_result = _run_git(
        ["rev-parse", "--verify", f"origin/{current_branch}"], FRAGO_HOME, check=False
    )
    if remote_branch_result.returncode != 0:
        return False

    # Save current HEAD for later comparison
    old_head_result = _run_git(["rev-parse", "HEAD"], FRAGO_HOME, check=False)
    old_head = old_head_result.stdout.strip() if old_head_result.returncode == 0 else None

    # Try rebase
    rebase_result = _run_git(["rebase", f"origin/{current_branch}"], FRAGO_HOME, check=False)

    if rebase_result.returncode != 0:
        # There are conflicts
        _run_git(["rebase", "--abort"], FRAGO_HOME, check=False)

        # Get conflict files
        result.conflicts = _get_changed_files(FRAGO_HOME)
        return True

    # Get new HEAD
    new_head_result = _run_git(["rev-parse", "HEAD"], FRAGO_HOME, check=False)
    new_head = new_head_result.stdout.strip() if new_head_result.returncode == 0 else None

    # Only collect update info when HEAD actually moved (has new commits)
    if old_head and new_head and old_head != new_head:
        # Use git diff --name-status to get file changes
        diff_result = _run_git(
            ["diff", "--name-status", f"{old_head}..{new_head}"],
            FRAGO_HOME,
            check=False
        )
        for line in diff_result.stdout.strip().split("\n"):
            if line:
                parts = line.split("\t")
                if len(parts) >= 2:
                    file_path = parts[1]
                    change = _get_file_change_info(FRAGO_HOME, file_path)
                    result.remote_updates.append(change)

        # Display table immediately
        if result.remote_updates:
            click.echo(_format_table(result.remote_updates, "Updates Fetched from Your Repository"))
    else:
        click.echo("No new changes from remote")

    return False


def _push_to_remote(result: SyncResult, dry_run: bool = False) -> bool:
    """
    Push to remote

    Returns:
        Whether successful
    """
    if dry_run:
        return True

    # Check if there's a remote repository
    remote_result = _run_git(["remote", "-v"], FRAGO_HOME, check=False)
    if not remote_result.stdout.strip():
        return True

    # Check if there are commits
    log_result = _run_git(["log", "--oneline", "-1"], FRAGO_HOME, check=False)
    if not log_result.stdout.strip():
        return True

    # Get current branch
    branch_result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], FRAGO_HOME, check=False)
    current_branch = branch_result.stdout.strip() or "main"

    # Push
    click.echo("Pushing to your repository...")
    push_result = _run_git(["push", "-u", "origin", current_branch], FRAGO_HOME, check=False)

    if push_result.returncode == 0:
        result.pushed_to_remote = True
        return True
    else:
        result.errors.append(f"Push failed: {push_result.stderr}")
        return False


def sync(
    repo_url: Optional[str] = None,
    message: Optional[str] = None,
    dry_run: bool = False,
    no_push: bool = False,
) -> SyncResult:
    """
    Main sync function

    Workflow:
    1. Safety check - Save local changes, sync changes from ~/.claude/
    2. Fetch remote updates - Pull and handle conflicts
    3. Update local Claude Code - Sync to ~/.claude/
    4. Push to your repository - If push is allowed

    Args:
        repo_url: Remote repository URL (required on first use)
        message: Custom commit message
        dry_run: Preview only, don't execute
        no_push: Don't push to remote

    Returns:
        SyncResult containing sync results
    """
    result = SyncResult()

    try:
        # 0. Configure gh credential helper (if gh is installed)
        # This allows git to use gh's OAuth token for HTTPS authentication
        if not dry_run:
            try:
                subprocess.run(
                    ["gh", "auth", "setup-git"],
                    capture_output=True,
                    timeout=10,
                    **_get_subprocess_kwargs(),
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass  # gh not installed or timeout, ignore

        # 1. Ensure repository exists
        if not _is_git_repo(FRAGO_HOME):
            if not repo_url:
                result.errors.append("Sync repository not configured. Please configure using frago sync --set-repo <url>")
                return result

            success, msg = _clone_or_init_repo(repo_url)
            if not success:
                result.errors.append(msg)
                return result
            click.echo(msg)

        # Ensure .gitignore exists
        _ensure_gitignore(FRAGO_HOME)

        # Check and remove tracked .env files
        if not dry_run:
            removed_env_files = _check_and_remove_tracked_env(FRAGO_HOME)
            if removed_env_files:
                warning_msg = f"Removed sensitive files from git tracking: {', '.join(removed_env_files)} (local files preserved)"
                result.warnings.append(warning_msg)
                click.echo(f"⚠️  {warning_msg}")

        # Check repository visibility
        actual_repo_url = repo_url
        if not actual_repo_url:
            # Get URL from git remote
            remote_result = _run_git(["remote", "get-url", "origin"], FRAGO_HOME, check=False)
            if remote_result.returncode == 0:
                actual_repo_url = remote_result.stdout.strip()

        # Automatically convert SSH URL to HTTPS URL (works with gh credential helper)
        if actual_repo_url and actual_repo_url.startswith("git@github.com:"):
            import re
            ssh_match = re.match(r'git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$', actual_repo_url)
            if ssh_match:
                owner, repo = ssh_match.group(1), ssh_match.group(2)
                https_url = f"https://github.com/{owner}/{repo}.git"
                if not dry_run:
                    # Update git remote URL
                    _run_git(["remote", "set-url", "origin", https_url], FRAGO_HOME, check=False)
                    click.echo(f"Converted repository URL from SSH to HTTPS: {https_url}")
                actual_repo_url = https_url

        if actual_repo_url:
            visibility = _check_repo_visibility(actual_repo_url)
            if visibility == "public":
                result.is_public_repo = True
                warning_msg = "Warning: Current sync repository is public, sensitive information may be exposed. Recommend using a private repository."
                result.warnings.append(warning_msg)
                click.echo(f"⚠️  {warning_msg}")

        # 1. Safety check - Sync changes from ~/.claude/ to ~/.frago/.claude/
        click.echo("Checking local resource changes...")
        _sync_claude_to_frago(result, dry_run)

        # 1b. Save local changes
        if result.local_changes or _has_uncommitted_changes(FRAGO_HOME):
            click.echo("Saving local changes...")
            _save_local_changes(result, message, dry_run)

        # 2. Fetch remote updates
        has_conflicts = _pull_remote_updates(result, dry_run)

        if has_conflicts:
            result.errors.append("Resource conflicts detected, please resolve manually and sync again")
            # Return without marking as failed, let user see conflict info
            return result

        # 2b. Re-run untrack after rebase (remote may have tracked files that should be ignored)
        if not dry_run:
            _untrack_ignored_paths(FRAGO_HOME)
            # Commit if there are changes from untracking
            if _has_uncommitted_changes(FRAGO_HOME):
                _run_git(["add", "."], FRAGO_HOME, check=False)
                _run_git(["commit", "-m", "chore: untrack ignored files after sync"], FRAGO_HOME, check=False)

        # 3. Update local Claude Code
        click.echo("Updating Claude Code resources...")
        _sync_frago_to_claude(result, dry_run)

        # 4. Push to your repository
        if not no_push:
            _push_to_remote(result, dry_run)

        result.success = True

    except subprocess.CalledProcessError as e:
        result.errors.append(f"Git operation failed: {e.stderr}")
    except PermissionError as e:
        result.errors.append(f"Permission error: {e}")
    except Exception as e:
        result.errors.append(f"Sync failed: {e}")

    return result
