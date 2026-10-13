"""Workspace file access routes for Frago Web Service.

Provides general filesystem access for recipes and static HTML+JS:
- GET /api/file: Read file content
- POST /api/file: Write file content (supports base64 encoding for binary files)
- GET /api/files: List directory contents
- GET /api/file/view: Hand a file to the viewer, get back where it renders
"""

import asyncio
import base64
import mimetypes
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from frago.server.services.system_service import SystemService, UnsupportedPlatformError
from frago.server.services.viewer_service import ViewerService

router = APIRouter()


class WriteFileRequest(BaseModel):
    """Request body for writing file content."""

    content: str
    encoding: str | None = None  # None for text, "base64" for binary


@router.get("/file")
async def get_file(
    path: str = Query(..., description="Absolute path to file"),
    disposition: str | None = Query(
        None,
        description=(
            "Set to 'inline' to serve the file for in-page rendering. "
            "Default keeps the historical attachment disposition."
        ),
    ),
):
    """Serve a file from the filesystem.

    Args:
        path: Absolute path to the file
        disposition: "inline" to drop the Content-Disposition attachment header

    Returns:
        File content with appropriate MIME type

    Note:
        Passing filename= makes Starlette emit `Content-Disposition: attachment`,
        which Chrome treats as a download and refuses to render in <video>/<audio>
        elements. Interactive recipes that play project media through this route
        must request disposition=inline. The default is left untouched so existing
        callers keep getting the download behaviour they rely on.
    """
    file_path = Path(path)

    if not file_path.is_absolute():
        raise HTTPException(status_code=400, detail="Path must be absolute")

    try:
        resolved = file_path.resolve(strict=True)
    except (FileNotFoundError, OSError) as err:
        raise HTTPException(status_code=404, detail=f"File not found: {path}") from err

    if not resolved.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")

    mime_type, _ = mimetypes.guess_type(str(resolved))

    if disposition == "inline":
        return FileResponse(resolved, media_type=mime_type or "application/octet-stream")

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
            raise HTTPException(status_code=400, detail=f"Invalid base64 data: {e}") from e
    else:
        # Write as text (default behavior)
        file_path.write_text(request.content, encoding="utf-8")

    return {"status": "ok", "path": str(file_path)}


@router.get("/files")
async def list_files(
    path: str | None = Query(
        None,
        description="Absolute path to directory; omitted means the home directory",
    ),
):
    """List files in a directory.

    Args:
        path: Absolute path to the directory; omitted for the home directory

    Returns:
        The resolved directory and the entries with name, is_dir, size and modified.
        Nothing is filtered out — hidden entries and unreadable ones are the caller's
        to show or skip, and a file browser wants both.
    """
    if path is None:
        resolved = Path.home()
    else:
        dir_path = Path(path)

        if not dir_path.is_absolute():
            raise HTTPException(status_code=400, detail="Path must be absolute")

        try:
            resolved = dir_path.resolve(strict=True)
        except (FileNotFoundError, OSError) as err:
            raise HTTPException(status_code=404, detail=f"Directory not found: {path}") from err

    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    entries = []
    for entry in sorted(resolved.iterdir(), key=lambda e: e.name):
        try:
            stat = entry.stat()
            is_dir = entry.is_dir()
            entries.append(
                {
                    "name": entry.name,
                    "is_dir": is_dir,
                    "size": None if is_dir else stat.st_size,
                    # 目录也要有时间：人按时间找东西时，目录后面跟着一串空白会更难看。
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                }
            )
        except (PermissionError, OSError):
            # 断链的符号链接、读不到属性的条目：跳过，不让一条坏的拖垮整次列举。
            continue

    return {
        "path": str(resolved),
        "entries": sorted(entries, key=lambda e: (not e["is_dir"], e["name"])),
    }


#: 交给 viewer 去读的文本上限。视频、图片这些是按字节拷进 viewer 目录的，不读进内存，
#: 所以只卡文本。超了这一档的不再往下走：服务端读一份几百兆的日志既慢，浏览器那头也
#: 没人看得完，不如当场说清楚。
_VIEW_MAX_TEXT_BYTES = 8 * 1024 * 1024

#: 按字节搬运、不读成文本的几类（与 ViewerService 的分法一致）。
_BINARY_KINDS = frozenset({"video", "image", "audio", "3d", "pdf"})


@router.get("/file/view")
async def view_file(path: str = Query(..., description="Absolute path to file")):
    """把这份文件交给 viewer 渲染，回一个能在页面里内嵌的地址。

    渲染本身不在这里做——用的是 `frago view` 那一条现成的管线
    （:meth:`~frago.server.services.viewer_service.ViewerService.prepare_content`），
    它认 markdown、html、pdf、图片、音视频、3D 与各种代码。这里只负责把它接出来：
    渲染结果由同一个服务发在 `/viewer/content/<编号>/` 下，与 WebUI 同源，页面直接
    嵌一个 iframe 就看到了，人不用离开工作台。

    页面那边传绝对路径过来，这里不做目录白名单——这条口与 `/api/file`、`/api/files`
    是同一档，服务本来就只监听本机，这三条口读的是同一片文件系统。真正的边界是
    「不越出这台机器」，不是「只准读某个目录」。
    """
    file_path = Path(path)

    if not file_path.is_absolute():
        raise HTTPException(status_code=400, detail="Path must be absolute")

    try:
        resolved = file_path.resolve(strict=True)
    except (FileNotFoundError, OSError) as err:
        raise HTTPException(status_code=404, detail=f"File not found: {path}") from err

    if not resolved.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")

    kind = ViewerService.content_type_of(resolved)
    if kind not in _BINARY_KINDS and resolved.stat().st_size > _VIEW_MAX_TEXT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is too large to render: {resolved.stat().st_size} bytes",
        )

    try:
        content_id = await asyncio.to_thread(
            ViewerService.prepare_content,
            resolved,
            "auto",
            "github-dark",
            resolved.name,
        )
    except (OSError, ValueError) as err:
        raise HTTPException(status_code=500, detail=f"Failed to prepare viewer: {err}") from err

    return {
        "content_id": content_id,
        "url": f"/viewer/content/{content_id}/index.html",
        "title": resolved.name,
    }


@router.post("/reveal")
async def reveal_path(path: str = Query(..., description="Absolute path to open")):
    """在**跑 frago 的那台机器**上打开这个路径：是文件就选中它，是目录就打开它。

    浏览器自己开不了本机目录，这一下要绕服务端。跟 `/api/file`、`/api/files` 同一档：
    服务只监听本机，这一条读的是同一片文件系统，真正的边界是「不越出这台机器」。

    跨平台怎么开在 :meth:`~frago.server.services.system_service.SystemService.reveal_or_open`
    里，这里不重复一遍平台判断。
    """
    target = Path(path)

    if not target.is_absolute():
        raise HTTPException(status_code=400, detail="Path must be absolute")

    try:
        resolved = target.resolve(strict=True)
    except (FileNotFoundError, OSError) as err:
        raise HTTPException(status_code=404, detail=f"Path not found: {path}") from err

    try:
        if resolved.is_dir():
            await asyncio.to_thread(SystemService.open_directory, str(resolved))
        else:
            await asyncio.to_thread(SystemService.reveal_or_open, str(resolved), True)
    except UnsupportedPlatformError as err:
        raise HTTPException(status_code=501, detail=str(err)) from err
    except (subprocess.CalledProcessError, OSError) as err:
        raise HTTPException(status_code=500, detail=f"Failed to open {resolved}: {err}") from err

    return {"status": "ok", "opened": str(resolved)}
