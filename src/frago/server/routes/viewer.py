"""Viewer routes for serving content preview files.

Serves static files from ~/.frago/viewer/ directory structure:
- /viewer/content/{content_id}/{file_path} - Per-view content
- /viewer/resources/{file_path} - Shared viewer resources
"""

import json
import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

# Viewer directory location
VIEWER_DIR = Path.home() / ".frago" / "viewer"

router = APIRouter()


def get_mime_type(file_path: Path) -> str:
    """Get MIME type for a file based on extension."""
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type is None:
        # Default to binary if unknown
        return "application/octet-stream"
    return mime_type


def _file_at_source(content_id: str, file_path: str) -> Path | None:
    """内容目录里没有这一份时，按文档原来的位置去解。

    页面里的图片、样式地址是照文档原样写的相对地址（`docs/images/logo.png` 这种）。准备
    阶段只把文档旁边那几个**约定名字**的资源目录搬进内容目录，写在别处的搬不到——地址一个
    都解不出来，页面上就是一排破图。准备时留下的 `meta.json` 记着文档原来住在哪个目录，
    这里按它去解同一份文件。

    **只在文档自己那一层底下解。** 解出来的东西爬出了那个目录就当没有——这条口宁可窄，
    不能开成「按请求读这台机器上随便哪个文件」。解不出来、不是文件，都返回 None，由调用
    方回 404。
    """
    meta_path = VIEWER_DIR / "content" / content_id / "meta.json"
    if not meta_path.is_file():
        return None

    try:
        source_dir = Path(json.loads(meta_path.read_text(encoding="utf-8"))["source_dir"]).resolve()
        candidate = (source_dir / file_path).resolve()
        candidate.relative_to(source_dir)
    except (OSError, ValueError, KeyError, TypeError):
        return None

    return candidate if candidate.is_file() else None


@router.get("/content/{content_id}/{file_path:path}")
async def serve_viewer_content(content_id: str, file_path: str):
    """Serve content files for a specific view session.

    Args:
        content_id: Unique identifier for the view session
        file_path: Path to file within content directory

    Returns:
        FileResponse with appropriate MIME type
    """
    # Validate content_id (prevent path traversal)
    if ".." in content_id or "/" in content_id:
        raise HTTPException(status_code=400, detail="Invalid content_id")

    # Build full path
    full_path = VIEWER_DIR / "content" / content_id / file_path

    # Security check: ensure path is within viewer directory
    try:
        full_path = full_path.resolve()
        if not str(full_path).startswith(str(VIEWER_DIR.resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid path") from None

    # Check file exists
    if not full_path.exists() or not full_path.is_file():
        fallback = _file_at_source(content_id, file_path)
        if fallback is None:
            raise HTTPException(status_code=404, detail="File not found")
        full_path = fallback

    return FileResponse(
        path=full_path,
        media_type=get_mime_type(full_path),
    )


@router.get("/resources/{file_path:path}")
async def serve_viewer_resources(file_path: str):
    """Serve shared viewer resources (JS/CSS libraries).

    Args:
        file_path: Path to resource file

    Returns:
        FileResponse with appropriate MIME type
    """
    # Build full path
    full_path = VIEWER_DIR / "resources" / file_path

    # Security check: ensure path is within resources directory
    try:
        full_path = full_path.resolve()
        resources_dir = (VIEWER_DIR / "resources").resolve()
        if not str(full_path).startswith(str(resources_dir)):
            raise HTTPException(status_code=403, detail="Access denied")
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid path") from None

    # Check file exists
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="Resource not found")

    return FileResponse(
        path=full_path,
        media_type=get_mime_type(full_path),
    )
