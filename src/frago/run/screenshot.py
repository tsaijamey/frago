"""截图自动编号和保存

提供截图文件命名、编号、原子性写入功能
"""

import base64
import re
from pathlib import Path
from typing import Tuple

from slugify import slugify

from ..cdp.session import CDPSession
from .exceptions import FileSystemError
from .utils import ensure_directory_exists


def get_next_screenshot_number(screenshots_dir: Path) -> int:
    """获取下一个截图序号

    Args:
        screenshots_dir: 截图目录路径

    Returns:
        下一个序号（1-999）
    """
    ensure_directory_exists(screenshots_dir)

    max_num = 0
    for file in screenshots_dir.glob("*.png"):
        match = re.match(r"^(\d{3})_", file.name)
        if match:
            num = int(match.group(1))
            max_num = max(max_num, num)

    return max_num + 1


def capture_screenshot(description: str, screenshots_dir: Path) -> Tuple[Path, int]:
    """捕获截图并保存

    Args:
        description: 截图描述
        screenshots_dir: 截图目录路径

    Returns:
        (文件路径, 序号)

    Raises:
        FileSystemError: 截图保存失败
    """
    # 获取序号
    seq = get_next_screenshot_number(screenshots_dir)

    # Slug化描述
    desc_slug = slugify(description, max_length=40)

    # 构造文件名
    filename = f"{seq:03d}_{desc_slug}.png"
    final_path = screenshots_dir / filename
    temp_path = screenshots_dir / f".tmp_{filename}"

    try:
        # 使用CDP会话截图
        with CDPSession() as session:
            result = session.screenshot.capture()
            screenshot_data = base64.b64decode(result.get("data", ""))

        # 原子性写入（先写临时文件，再重命名）
        ensure_directory_exists(screenshots_dir)
        temp_path.write_bytes(screenshot_data)
        temp_path.rename(final_path)

        return final_path, seq

    except Exception as e:
        # 清理临时文件
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise FileSystemError("save screenshot", str(final_path), str(e))
