"""Viewer routes for serving content preview files.

Serves static files from ~/.frago/viewer/ directory structure:
- /viewer/content/{content_id}/{file_path} - Per-view content
- /viewer/resources/{file_path} - Shared viewer resources
"""

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
        raise HTTPException(status_code=400, detail="Invalid path")

    # Check file exists
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

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
        raise HTTPException(status_code=400, detail="Invalid path")

    # Check file exists
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="Resource not found")

    return FileResponse(
        path=full_path,
        media_type=get_mime_type(full_path),
    )
