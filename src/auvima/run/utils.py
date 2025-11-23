"""Run命令系统工具函数

提供主题slug生成、路径处理等辅助功能
"""

import time
from pathlib import Path
from typing import List

import pypinyin
from slugify import slugify as _slugify


def generate_theme_slug(description: str, max_length: int = 50) -> str:
    """生成主题slug（直接slug化，保留英文和数字）

    Args:
        description: 原始任务描述（应为AI生成的简洁主题短句）
        max_length: 最大长度限制

    Returns:
        slug化的主题名（小写字母、数字、连字符）

    Examples:
        >>> generate_theme_slug("nano-banana-pro image api research")
        'nano-banana-pro-image-api-research'
        >>> generate_theme_slug("upwork python jobs search")
        'upwork-python-jobs-search'

    Note:
        AI应该直接提供英文主题短句（3-5个词），避免中文转拼音导致的不可读性
    """
    # 直接slug化（保留英文、数字，移除中文和特殊字符）
    slug = _slugify(description, max_length=max_length)

    # 如果为空（纯符号输入或纯中文），回退到timestamp
    if not slug:
        slug = f"task-{int(time.time())}"

    return slug


def is_valid_run_id(run_id: str) -> bool:
    """验证run_id格式是否合法

    Args:
        run_id: 待验证的run ID

    Returns:
        True if valid, False otherwise
    """
    import re

    pattern = r"^[a-z0-9-]{1,50}$"
    return bool(re.match(pattern, run_id))


def scan_run_directories(projects_dir: Path) -> List[str]:
    """扫描projects目录，返回所有run_id列表

    Args:
        projects_dir: projects目录路径

    Returns:
        run_id列表（按最后修改时间降序）
    """
    if not projects_dir.exists() or not projects_dir.is_dir():
        return []

    run_ids = []
    for item in projects_dir.iterdir():
        if item.is_dir() and is_valid_run_id(item.name):
            run_ids.append(item.name)

    # 按最后修改时间排序（最近的在前）
    run_ids.sort(key=lambda rid: (projects_dir / rid).stat().st_mtime, reverse=True)

    return run_ids


def ensure_directory_exists(path: Path) -> None:
    """确保目录存在（如不存在则创建）

    Args:
        path: 目录路径

    Raises:
        FileSystemError: 创建目录失败
    """
    from .exceptions import FileSystemError

    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise FileSystemError("create directory", str(path), str(e))
