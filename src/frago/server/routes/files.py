"""File API routes for project file access.

Provides endpoints to browse and access run instance files.
"""

from dataclasses import asdict
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from frago.server.services.file_service import FileService
from frago.server.services.viewer_service import ViewerService


router = APIRouter(tags=["files"])


class ProjectInfoResponse(BaseModel):
    """Project info response model."""
    run_id: str
    theme_description: str
    created_at: str
    last_accessed: str
    status: str


class ProjectDetailResponse(ProjectInfoResponse):
    """Project detail response model."""
    file_count: int
    total_size: int
    subdirectories: List[str]


class FileInfoResponse(BaseModel):
    """File info response model."""
    name: str
    path: str
    is_directory: bool
    size: int
    modified: str
    mime_type: Optional[str]


class OpenResponse(BaseModel):
    """Response for open operations."""
    success: bool
    message: str


class ViewResponse(BaseModel):
    """Response for view operations."""
    success: bool
    url: Optional[str]
    message: str


@router.get("/projects", response_model=List[ProjectInfoResponse])
async def list_projects():
    """List all run instances.

    Returns a list of all projects sorted by last accessed time (newest first).
    """
    projects = FileService.list_projects()
    return [asdict(p) for p in projects]


@router.get("/projects/{run_id}", response_model=ProjectDetailResponse)
async def get_project(run_id: str):
    """Get detailed project information.

    Args:
        run_id: Project identifier

    Returns:
        Project details including file counts and subdirectories
    """
    project = FileService.get_project(run_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {run_id}")
    return asdict(project)


@router.get("/projects/{run_id}/files", response_model=List[FileInfoResponse])
async def list_files(
    run_id: str,
    path: str = Query("", description="Relative path within project"),
):
    """List files and directories in a project path.

    Args:
        run_id: Project identifier
        path: Relative path within project (empty for root)

    Returns:
        List of files and directories sorted by type then name
    """
    # Validate project exists
    project_dir = FileService.get_project_dir(run_id)
    if project_dir is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {run_id}")

    files = FileService.list_files(run_id, path)
    return [asdict(f) for f in files]


@router.get("/projects/{run_id}/files/{file_path:path}")
async def get_file(run_id: str, file_path: str):
    """Get or download a file.

    Args:
        run_id: Project identifier
        file_path: Relative path to file within project

    Returns:
        File content with appropriate MIME type
    """
    absolute_path = FileService.get_file_path(run_id, file_path)
    if absolute_path is None:
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    return FileResponse(
        path=absolute_path,
        filename=absolute_path.name,
    )


@router.post("/projects/{run_id}/open", response_model=OpenResponse)
async def open_in_file_manager(
    run_id: str,
    path: str = Query("", description="Relative path within project"),
):
    """Open a path in the system file manager.

    Args:
        run_id: Project identifier
        path: Relative path within project (empty for project root)

    Returns:
        Success status and message
    """
    success = FileService.open_in_system(run_id, path)
    if success:
        return OpenResponse(
            success=True,
            message=f"Opened in file manager: {path or run_id}",
        )
    else:
        return OpenResponse(
            success=False,
            message="Failed to open in file manager",
        )


@router.post("/projects/{run_id}/view", response_model=ViewResponse)
async def view_file(
    run_id: str,
    path: str = Query(..., description="Relative path to file"),
):
    """Preview a file using frago view.

    Opens the file in Chrome via the viewer service.

    Args:
        run_id: Project identifier
        path: Relative path to file within project

    Returns:
        Viewer URL and success status
    """
    absolute_path = FileService.get_file_path(run_id, path)
    if absolute_path is None:
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    try:
        # Prepare content and get viewer URL
        content_id = ViewerService.prepare_content(
            content=absolute_path,
            title=absolute_path.name,
        )
        url = f"http://127.0.0.1:8093/viewer/content/{content_id}/index.html"

        return ViewResponse(
            success=True,
            url=url,
            message=f"Viewer ready for: {path}",
        )
    except Exception as e:
        return ViewResponse(
            success=False,
            url=None,
            message=f"Failed to prepare viewer: {str(e)}",
        )
