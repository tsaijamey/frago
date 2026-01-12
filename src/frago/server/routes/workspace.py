"""Workspace file access routes for Frago Web Service.

Provides general filesystem access for recipes and static HTML+JS:
- GET /api/file: Read file content
- POST /api/file: Write file content (supports base64 encoding for binary files)
- GET /api/files: List directory contents
"""

import base64
import mimetypes
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel


router = APIRouter()


class WriteFileRequest(BaseModel):
    """Request body for writing file content."""

    content: str
    encoding: Optional[str] = None  # None for text, "base64" for binary


@router.get("/file")
async def get_file(path: str = Query(..., description="Absolute path to file")):
    """Serve a file from the filesystem.

    Args:
        path: Absolute path to the file

    Returns:
        File content with appropriate MIME type
    """
    file_path = Path(path)

    if not file_path.is_absolute():
        raise HTTPException(status_code=400, detail="Path must be absolute")

    try:
        resolved = file_path.resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    if not resolved.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")

    mime_type, _ = mimetypes.guess_type(str(resolved))

    return FileResponse(
        resolved,
        media_type=mime_type or "application/octet-stream",
        filename=resolved.name,
    )


@router.post("/file")
async def write_file(
    request: WriteFileRequest,
    path: str = Query(..., description="Absolute path to file"),
):
    """Write content to a file.

    Args:
        path: Absolute path to the file
        request: Request body containing file content and optional encoding

    Returns:
        Status and written file path
    """
    file_path = Path(path)

    if not file_path.is_absolute():
        raise HTTPException(status_code=400, detail="Path must be absolute")

    file_path.parent.mkdir(parents=True, exist_ok=True)

    if request.encoding == "base64":
        # Decode base64 and write as binary
        try:
            binary_data = base64.b64decode(request.content)
            file_path.write_bytes(binary_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid base64 data: {e}")
    else:
        # Write as text (default behavior)
        file_path.write_text(request.content, encoding="utf-8")

    return {"status": "ok", "path": str(file_path)}


@router.get("/files")
async def list_files(path: str = Query(..., description="Absolute path to directory")):
    """List files in a directory.

    Args:
        path: Absolute path to the directory

    Returns:
        Directory path and list of entries with name, is_dir, and size
    """
    dir_path = Path(path)

    if not dir_path.is_absolute():
        raise HTTPException(status_code=400, detail="Path must be absolute")

    try:
        resolved = dir_path.resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise HTTPException(status_code=404, detail=f"Directory not found: {path}")

    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    entries = []
    for entry in resolved.iterdir():
        try:
            entries.append(
                {
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": entry.stat().st_size if entry.is_file() else None,
                }
            )
        except (PermissionError, OSError):
            continue

    return {
        "path": str(resolved),
        "entries": sorted(entries, key=lambda e: (not e["is_dir"], e["name"])),
    }
