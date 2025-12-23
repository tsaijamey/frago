"""Screenshot Auto-numbering and Saving

Provides screenshot file naming, numbering, and atomic write functionality
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
    """Get next screenshot sequence number

    Args:
        screenshots_dir: screenshots directory path

    Returns:
        next sequence number (1-999)
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
    """Capture screenshot and save

    Args:
        description: screenshot description
        screenshots_dir: screenshots directory path

    Returns:
        (file path, sequence number)

    Raises:
        FileSystemError: screenshot save failed
    """
    # Get sequence number
    seq = get_next_screenshot_number(screenshots_dir)

    # Slugify description
    desc_slug = slugify(description, max_length=40)

    # Construct filename
    filename = f"{seq:03d}_{desc_slug}.png"
    final_path = screenshots_dir / filename
    temp_path = screenshots_dir / f".tmp_{filename}"

    try:
        # Use CDP session to capture screenshot
        with CDPSession() as session:
            result = session.screenshot.capture()
            screenshot_data = base64.b64decode(result.get("data", ""))

        # Atomic write (write to temp file first, then rename)
        ensure_directory_exists(screenshots_dir)
        temp_path.write_bytes(screenshot_data)
        temp_path.rename(final_path)

        return final_path, seq

    except Exception as e:
        # Clean up temp file
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise FileSystemError("save screenshot", str(final_path), str(e))
