"""
Sync 模块 - 将 ~/.frago/ 整体作为 Git 仓库同步

将 ~/.frago/ 作为 Git 工作目录，同步到用户配置的远程仓库。
支持与 ~/.claude/ 之间的幂等性检查，确保资源不丢失。
"""

import filecmp
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import click

# 系统级目录
FRAGO_HOME = Path.home() / ".frago"
CLAUDE_HOME = Path.home() / ".claude"

# ~/.frago/.claude/ 子目录（Git 追踪）
FRAGO_CLAUDE_DIR = FRAGO_HOME / ".claude"
FRAGO_COMMANDS_DIR = FRAGO_CLAUDE_DIR / "commands"
FRAGO_SKILLS_DIR = FRAGO_CLAUDE_DIR / "skills"
FRAGO_RECIPES_DIR = FRAGO_HOME / "recipes"

# ~/.claude/ 运行时目录
CLAUDE_COMMANDS_DIR = CLAUDE_HOME / "commands"
CLAUDE_SKILLS_DIR = CLAUDE_HOME / "skills"


@dataclass
class FileChange:
    """文件变更信息"""

    type: str  # "命令", "Skill", "Recipe", "其他"
    name: str
    operation: str  # "修改", "新增", "删除"
    timestamp: Optional[datetime] = None


@dataclass
class SyncResult:
    """同步结果"""

    success: bool = False
    local_changes: list[FileChange] = field(default_factory=list)
    remote_updates: list[FileChange] = field(default_factory=list)
    pushed_to_remote: bool = False
    conflicts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class FileConflict:
    """文件冲突信息"""

    file_path: str
    local_mtime: datetime
    remote_mtime: datetime


def _run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """执行 git 命令"""
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=check,
    )


def _is_git_repo(path: Path) -> bool:
    """检查目录是否是 Git 仓库"""
    return (path / ".git").exists()


def _has_uncommitted_changes(repo_dir: Path) -> bool:
    """检查是否有未提交的修改"""
    result = _run_git(["status", "--porcelain"], repo_dir, check=False)
    return bool(result.stdout.strip())


def _get_changed_files(repo_dir: Path) -> list[str]:
    """获取已修改的文件列表"""
    result = _run_git(["status", "--porcelain"], repo_dir, check=False)
    files = []
    for line in result.stdout.strip().split("\n"):
        if line:
            # 格式: XY filename 或 XY -> renamed
            parts = line[3:].split(" -> ")
            files.append(parts[-1])
    return files


def _ensure_gitignore(repo_dir: Path) -> None:
    """确保 .gitignore 文件存在且包含正确的排除规则"""
    gitignore_path = repo_dir / ".gitignore"
    gitignore_content = """# 运行时数据（不同步）
sessions/
chrome_profile/
current_run

# 配置文件（包含敏感信息）
config.json

# 系统文件
.DS_Store
__pycache__/
*.pyc
*.bak
"""

    if not gitignore_path.exists():
        gitignore_path.write_text(gitignore_content)
    else:
        # 检查现有内容，如果缺少关键规则则追加
        existing = gitignore_path.read_text()
        needed_rules = ["sessions/", "chrome_profile/", "current_run", "config.json"]
        missing = [rule for rule in needed_rules if rule not in existing]
        if missing:
            with open(gitignore_path, "a") as f:
                f.write("\n# Auto-added by frago sync\n")
                for rule in missing:
                    f.write(f"{rule}\n")


def _classify_file(file_path: str) -> tuple[str, str]:
    """分类文件类型和名称

    Args:
        file_path: 相对于仓库根目录的文件路径

    Returns:
        (类型, 名称) 元组
    """
    path_obj = Path(file_path)

    if file_path.startswith(".claude/commands/"):
        # 命令文件：frago.xxx.md -> frago.xxx
        if path_obj.suffix == ".md":
            return ("命令", path_obj.stem)
        # frago/ 目录下的文件
        return ("命令", path_obj.name)
    elif file_path.startswith(".claude/skills/"):
        # Skills 是目录：.claude/skills/frago-xxx/... -> frago-xxx
        parts = path_obj.parts
        if len(parts) >= 3:
            return ("Skill", parts[2])
        return ("Skill", path_obj.name)
    elif file_path.startswith("recipes/"):
        # Recipe：recipes/atomic/xxx.json -> xxx
        # 或：recipes/workflows/yyy/ -> yyy
        parts = path_obj.parts
        if len(parts) >= 3:
            # 提取文件名（不含扩展名）或目录名
            name = parts[2]
            if path_obj.suffix == ".json":
                name = path_obj.stem
            return ("Recipe", name)
        return ("Recipe", path_obj.name)

    return ("其他", path_obj.name)


def _get_file_change_info(repo_dir: Path, file_path: str) -> FileChange:
    """获取文件变更详细信息

    Args:
        repo_dir: Git 仓库目录
        file_path: 相对于仓库根目录的文件路径

    Returns:
        FileChange 对象
    """
    file_type, name = _classify_file(file_path)

    # 尝试从 Git 获取时间戳
    result = _run_git(["log", "--format=%aI", "-1", "--", file_path], repo_dir, check=False)
    timestamp = None

    if result.returncode == 0 and result.stdout.strip():
        try:
            # 去除时区标记 'Z' 或转换为 Python 支持的格式
            iso_time = result.stdout.strip()
            if iso_time.endswith('Z'):
                iso_time = iso_time[:-1] + '+00:00'
            timestamp = datetime.fromisoformat(iso_time)
        except ValueError:
            pass

    # 如果没有 Git 历史，使用文件系统时间
    if timestamp is None:
        full_path = repo_dir / file_path
        if full_path.exists():
            if full_path.is_file():
                mtime = os.path.getmtime(full_path)
                timestamp = datetime.fromtimestamp(mtime)
            elif full_path.is_dir():
                # 对于目录，使用目录本身的 mtime
                mtime = os.path.getmtime(full_path)
                timestamp = datetime.fromtimestamp(mtime)

    # 检测操作类型
    status_result = _run_git(["status", "--porcelain", "--", file_path], repo_dir, check=False)
    operation = "修改"
    if status_result.stdout:
        status_code = status_result.stdout[:2]
        if 'A' in status_code:
            operation = "新增"
        elif 'D' in status_code:
            operation = "删除"
        elif 'M' in status_code:
            operation = "修改"

    return FileChange(type=file_type, name=name, operation=operation, timestamp=timestamp)


def _format_table(changes: list[FileChange], title: str) -> str:
    """格式化变更表格

    Args:
        changes: 文件变更列表
        title: 表格标题

    Returns:
        格式化的表格字符串
    """
    if not changes:
        return ""

    lines = [f"\n{title}:"]
    lines.append(f"{'类型':<10} {'名称':<40} {'操作':<8} {'时间':<20}")
    lines.append("─" * 80)

    for change in changes:
        time_str = change.timestamp.strftime("%Y-%m-%d %H:%M") if change.timestamp else "—"
        lines.append(f"{change.type:<10} {change.name:<40} {change.operation:<8} {time_str:<20}")

    return "\n".join(lines)


def _init_git_repo(repo_dir: Path, remote_url: str) -> None:
    """初始化 Git 仓库"""
    repo_dir.mkdir(parents=True, exist_ok=True)

    # 初始化
    _run_git(["init"], repo_dir)

    # 添加远程
    _run_git(["remote", "add", "origin", remote_url], repo_dir, check=False)

    # 创建 .gitignore
    _ensure_gitignore(repo_dir)


def _safe_copy_tree(src: Path, dst: Path) -> None:
    """安全地复制目录树，跳过特殊文件（socket、symlink 等）"""
    dst.mkdir(parents=True, exist_ok=True)

    for item in src.iterdir():
        src_item = item
        dst_item = dst / item.name

        if src_item.is_symlink():
            # 跳过符号链接
            continue
        elif src_item.is_file():
            try:
                shutil.copy2(src_item, dst_item)
            except (OSError, IOError):
                # 跳过无法复制的文件（socket、特殊设备等）
                pass
        elif src_item.is_dir():
            _safe_copy_tree(src_item, dst_item)


def _clone_or_init_repo(repo_url: str) -> tuple[bool, str]:
    """
    克隆或初始化仓库

    如果远程仓库存在，则克隆到 ~/.frago/
    如果远程仓库为空或不存在，则初始化本地仓库

    Returns:
        (success, message)
    """
    if _is_git_repo(FRAGO_HOME):
        return True, "仓库已存在"

    # 尝试克隆到临时目录
    temp_dir = FRAGO_HOME.parent / ".frago_clone_temp"
    # 需要保留的运行时目录/文件（不包括 projects，因为它会被同步）
    runtime_items = ["sessions", "chrome_profile", "config.json", "current_run"]

    try:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

        result = subprocess.run(
            ["git", "clone", repo_url, str(temp_dir)],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            # 克隆成功，移动内容到 ~/.frago/
            # 保留现有的运行时目录
            preserved = {}

            for item in runtime_items:
                src = FRAGO_HOME / item
                if src.exists():
                    preserved[item] = temp_dir.parent / f".frago_preserve_{item}"
                    if src.is_file():
                        shutil.copy2(src, preserved[item])
                    elif src.is_dir():
                        _safe_copy_tree(src, preserved[item])

            # 移动克隆内容
            if FRAGO_HOME.exists():
                shutil.rmtree(FRAGO_HOME)
            shutil.move(str(temp_dir), str(FRAGO_HOME))

            # 恢复运行时目录
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
            return True, "已从您的仓库获取资源"
        else:
            # 克隆失败，可能是空仓库，初始化本地
            _init_git_repo(FRAGO_HOME, repo_url)
            return True, "已初始化本地仓库（您的仓库为空或不存在）"

    except Exception as e:
        return False, f"初始化失败: {e}"
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        # 清理可能残留的 preserve 目录
        for item in runtime_items:
            preserve_path = FRAGO_HOME.parent / f".frago_preserve_{item}"
            if preserve_path.exists():
                if preserve_path.is_dir():
                    shutil.rmtree(preserve_path)
                else:
                    preserve_path.unlink()


def _files_are_identical(file1: Path, file2: Path) -> bool:
    """比较两个文件是否内容相同"""
    if not file1.exists() or not file2.exists():
        return False
    return filecmp.cmp(file1, file2, shallow=False)


def _dir_files_identical(dir1: Path, dir2: Path) -> bool:
    """比较两个目录的内容是否相同"""
    if not dir1.exists() or not dir2.exists():
        return dir1.exists() == dir2.exists()

    # 获取所有文件
    files1 = set(f.relative_to(dir1) for f in dir1.rglob("*") if f.is_file())
    files2 = set(f.relative_to(dir2) for f in dir2.rglob("*") if f.is_file())

    if files1 != files2:
        return False

    for rel_path in files1:
        if not _files_are_identical(dir1 / rel_path, dir2 / rel_path):
            return False

    return True


def _get_file_mtime(path: Path) -> float:
    """获取文件的修改时间"""
    if path.exists() and path.is_file():
        return os.path.getmtime(path)
    return 0.0


def _get_dir_latest_mtime(dir_path: Path) -> float:
    """获取目录中最新文件的修改时间"""
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
    """检查源文件/目录是否比目标更新

    Args:
        src: 源路径
        target: 目标路径

    Returns:
        True 如果源比目标更新，或目标不存在
    """
    if not target.exists():
        return True

    if src.is_file():
        return _get_file_mtime(src) > _get_file_mtime(target)
    elif src.is_dir():
        return _get_dir_latest_mtime(src) > _get_dir_latest_mtime(target)

    return False


def _sync_claude_to_frago(result: SyncResult, dry_run: bool = False) -> None:
    """
    将 ~/.claude/ 中的修改同步到 ~/.frago/.claude/

    检查 ~/.claude/commands/frago.*.md 和 ~/.claude/skills/frago-*
    只有当 ~/.claude/ 中的版本比 ~/.frago/.claude/ 更新时才复制
    """
    # 同步 commands
    if CLAUDE_COMMANDS_DIR.exists():
        FRAGO_COMMANDS_DIR.mkdir(parents=True, exist_ok=True)

        # frago.*.md 文件
        for src_file in CLAUDE_COMMANDS_DIR.glob("frago.*.md"):
            if not src_file.is_file():
                continue

            target_file = FRAGO_COMMANDS_DIR / src_file.name

            # 只有当内容不同且源文件更新时才复制
            if not _files_are_identical(src_file, target_file) and _is_source_newer(src_file, target_file):
                if not dry_run:
                    shutil.copy2(src_file, target_file)
                # 收集变更信息
                file_path = f".claude/commands/{src_file.name}"
                change = _get_file_change_info(FRAGO_HOME, file_path)
                result.local_changes.append(change)

        # frago/ 子目录
        frago_src = CLAUDE_COMMANDS_DIR / "frago"
        frago_target = FRAGO_COMMANDS_DIR / "frago"

        if frago_src.exists() and frago_src.is_dir():
            # 只有当内容不同且源目录更新时才复制
            if not _dir_files_identical(frago_src, frago_target) and _is_source_newer(frago_src, frago_target):
                if not dry_run:
                    if frago_target.exists():
                        shutil.rmtree(frago_target)
                    shutil.copytree(
                        frago_src, frago_target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
                    )
                # 收集 frago/ 目录的变更（选择一个代表性文件）
                file_path = ".claude/commands/frago"
                change = _get_file_change_info(FRAGO_HOME, file_path)
                result.local_changes.append(change)

    # 同步 skills
    if CLAUDE_SKILLS_DIR.exists():
        FRAGO_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

        for skill_dir in CLAUDE_SKILLS_DIR.iterdir():
            if not skill_dir.is_dir():
                continue
            if not skill_dir.name.startswith("frago-"):
                continue

            target_skill_dir = FRAGO_SKILLS_DIR / skill_dir.name

            # 只有当内容不同且源目录更新时才复制
            if not _dir_files_identical(skill_dir, target_skill_dir) and _is_source_newer(skill_dir, target_skill_dir):
                if not dry_run:
                    if target_skill_dir.exists():
                        shutil.rmtree(target_skill_dir)
                    shutil.copytree(
                        skill_dir, target_skill_dir, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
                    )
                # 收集变更信息
                file_path = f".claude/skills/{skill_dir.name}"
                change = _get_file_change_info(FRAGO_HOME, file_path)
                result.local_changes.append(change)

    # 立即显示表格
    if result.local_changes:
        click.echo(_format_table(result.local_changes, "本地修改"))


def _sync_frago_to_claude(result: SyncResult, dry_run: bool = False) -> None:
    """
    将 ~/.frago/.claude/ 的内容同步到 ~/.claude/

    从仓库获取更新后，将资源部署到 Claude Code 运行时目录
    """
    # 同步 commands
    if FRAGO_COMMANDS_DIR.exists():
        CLAUDE_COMMANDS_DIR.mkdir(parents=True, exist_ok=True)

        # frago.*.md 文件
        for src_file in FRAGO_COMMANDS_DIR.glob("frago.*.md"):
            if not src_file.is_file():
                continue

            target_file = CLAUDE_COMMANDS_DIR / src_file.name

            if not target_file.exists() or not _files_are_identical(src_file, target_file):
                if not dry_run:
                    shutil.copy2(src_file, target_file)

        # frago/ 子目录
        frago_src = FRAGO_COMMANDS_DIR / "frago"
        frago_target = CLAUDE_COMMANDS_DIR / "frago"

        if frago_src.exists() and frago_src.is_dir():
            if not _dir_files_identical(frago_src, frago_target):
                if not dry_run:
                    if frago_target.exists():
                        shutil.rmtree(frago_target)
                    shutil.copytree(
                        frago_src, frago_target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
                    )

    # 同步 skills
    if FRAGO_SKILLS_DIR.exists():
        CLAUDE_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

        for skill_dir in FRAGO_SKILLS_DIR.iterdir():
            if not skill_dir.is_dir():
                continue
            if not skill_dir.name.startswith("frago-"):
                continue

            target_skill_dir = CLAUDE_SKILLS_DIR / skill_dir.name

            if not _dir_files_identical(skill_dir, target_skill_dir):
                if not dry_run:
                    if target_skill_dir.exists():
                        shutil.rmtree(target_skill_dir)
                    shutil.copytree(
                        skill_dir, target_skill_dir, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
                    )


def _save_local_changes(result: SyncResult, message: Optional[str], dry_run: bool = False) -> bool:
    """
    保存本地修改（git add + commit）

    Returns:
        是否有修改被保存
    """
    if not _has_uncommitted_changes(FRAGO_HOME):
        return False

    changed_files = _get_changed_files(FRAGO_HOME)

    if dry_run:
        return True

    # git add
    _run_git(["add", "."], FRAGO_HOME)

    # git commit
    commit_message = message or f"sync: 保存本地修改 ({len(changed_files)} 个文件)"
    _run_git(["commit", "-m", commit_message], FRAGO_HOME)

    return True


def _pull_remote_updates(result: SyncResult, dry_run: bool = False) -> bool:
    """
    拉取远程更新

    Returns:
        是否有冲突
    """
    if dry_run:
        return False

    # 检查是否有远程仓库
    remote_result = _run_git(["remote", "-v"], FRAGO_HOME, check=False)
    if not remote_result.stdout.strip():
        return False

    # fetch
    click.echo("正在从您的仓库获取最新资源...")
    fetch_result = _run_git(["fetch", "origin"], FRAGO_HOME, check=False)
    if fetch_result.returncode != 0:
        # 可能是新仓库，没有远程分支
        return False

    # 检查是否有远程分支
    branch_result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], FRAGO_HOME, check=False)
    current_branch = branch_result.stdout.strip() or "main"

    # 检查远程分支是否存在
    remote_branch_result = _run_git(
        ["rev-parse", "--verify", f"origin/{current_branch}"], FRAGO_HOME, check=False
    )
    if remote_branch_result.returncode != 0:
        return False

    # 保存当前 HEAD，用于后续比较
    old_head_result = _run_git(["rev-parse", "HEAD"], FRAGO_HOME, check=False)
    old_head = old_head_result.stdout.strip() if old_head_result.returncode == 0 else None

    # 尝试 rebase
    rebase_result = _run_git(["rebase", f"origin/{current_branch}"], FRAGO_HOME, check=False)

    if rebase_result.returncode != 0:
        # 有冲突
        _run_git(["rebase", "--abort"], FRAGO_HOME, check=False)

        # 获取冲突文件
        result.conflicts = _get_changed_files(FRAGO_HOME)
        return True

    # 获取新的 HEAD
    new_head_result = _run_git(["rev-parse", "HEAD"], FRAGO_HOME, check=False)
    new_head = new_head_result.stdout.strip() if new_head_result.returncode == 0 else None

    # 只有当 HEAD 真的移动了（有新提交），才收集更新信息
    if old_head and new_head and old_head != new_head:
        # 使用 git diff --name-status 获取文件变更
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

        # 立即显示表格
        if result.remote_updates:
            click.echo(_format_table(result.remote_updates, "从您的仓库获取的更新"))

    return False


def _push_to_remote(result: SyncResult, dry_run: bool = False) -> bool:
    """
    推送到远程

    Returns:
        是否成功
    """
    if dry_run:
        return True

    # 检查是否有远程仓库
    remote_result = _run_git(["remote", "-v"], FRAGO_HOME, check=False)
    if not remote_result.stdout.strip():
        return True

    # 检查是否有提交
    log_result = _run_git(["log", "--oneline", "-1"], FRAGO_HOME, check=False)
    if not log_result.stdout.strip():
        return True

    # 获取当前分支
    branch_result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], FRAGO_HOME, check=False)
    current_branch = branch_result.stdout.strip() or "main"

    # 推送
    click.echo("正在推送到您的仓库...")
    push_result = _run_git(["push", "-u", "origin", current_branch], FRAGO_HOME, check=False)

    if push_result.returncode == 0:
        result.pushed_to_remote = True
        return True
    else:
        result.errors.append(f"推送失败: {push_result.stderr}")
        return False


def sync(
    repo_url: Optional[str] = None,
    message: Optional[str] = None,
    dry_run: bool = False,
    no_push: bool = False,
) -> SyncResult:
    """
    主同步函数

    流程:
    1. 安全检查 - 保存本地修改，同步 ~/.claude/ 的修改
    2. 获取远程更新 - 拉取并处理冲突
    3. 更新本地 Claude Code - 同步到 ~/.claude/
    4. 推送到您的仓库 - 如果允许推送

    Args:
        repo_url: 远程仓库 URL（首次使用时需要）
        message: 自定义提交信息
        dry_run: 仅预览不执行
        no_push: 不推送到远程

    Returns:
        SyncResult 包含同步结果
    """
    result = SyncResult()

    try:
        # 0. 确保仓库存在
        if not _is_git_repo(FRAGO_HOME):
            if not repo_url:
                result.errors.append("未配置同步仓库，请先使用 frago sync --set-repo <url> 配置")
                return result

            success, msg = _clone_or_init_repo(repo_url)
            if not success:
                result.errors.append(msg)
                return result
            click.echo(msg)

        # 确保 .gitignore 存在
        _ensure_gitignore(FRAGO_HOME)

        # 1. 安全检查 - 同步 ~/.claude/ 的修改到 ~/.frago/.claude/
        click.echo("检查本地资源修改...")
        _sync_claude_to_frago(result, dry_run)

        # 1b. 保存本地修改
        if result.local_changes or _has_uncommitted_changes(FRAGO_HOME):
            click.echo("保存本地修改...")
            _save_local_changes(result, message, dry_run)

        # 2. 获取远程更新
        has_conflicts = _pull_remote_updates(result, dry_run)

        if has_conflicts:
            result.errors.append("检测到资源冲突，请手动解决后重新同步")
            # 返回但不标记失败，让用户看到冲突信息
            return result

        # 3. 更新本地 Claude Code
        click.echo("更新 Claude Code 资源...")
        _sync_frago_to_claude(result, dry_run)

        # 4. 推送到您的仓库
        if not no_push:
            _push_to_remote(result, dry_run)

        result.success = True

    except subprocess.CalledProcessError as e:
        result.errors.append(f"Git 操作失败: {e.stderr}")
    except PermissionError as e:
        result.errors.append(f"权限错误: {e}")
    except Exception as e:
        result.errors.append(f"同步失败: {e}")

    return result
