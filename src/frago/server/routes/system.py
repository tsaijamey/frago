"""System status and info API endpoints.

Provides endpoints for server health checks and information.
"""

from fastapi import APIRouter

from frago.server.models import SystemStatusResponse, ServerInfoResponse
from frago.server.services.system_service import SystemService
from frago.server.utils import get_server_info

router = APIRouter()


@router.get("/status", response_model=SystemStatusResponse)
async def get_status() -> SystemStatusResponse:
    """Get system status.

    Returns information about Chrome availability,
    running tasks, and monitored projects.
    """
    status = SystemService.get_status()

    return SystemStatusResponse(
        cpu_percent=status.get("cpu_percent", 0.0),
        memory_percent=status.get("memory_percent", 0.0),
        chrome_available=status.get("chrome_available", False),
        chrome_connected=status.get("chrome_connected", False),
        projects_count=status.get("projects_count", 0),
        tasks_running=status.get("tasks_running", 0),
    )


@router.get("/info", response_model=ServerInfoResponse)
async def get_info() -> ServerInfoResponse:
    """Get server information.

    Returns server version, host, port, and start time.
    """
    from datetime import datetime, timezone

    server_info = get_server_info()

    info = SystemService.get_info(
        host=server_info.get("host", "127.0.0.1"),
        port=server_info.get("port", 8080),
        started_at=server_info.get("started_at", datetime.now(timezone.utc).isoformat()),
    )

    return ServerInfoResponse(
        version=info.get("version", "0.0.0"),
        host=info.get("host", "127.0.0.1"),
        port=info.get("port", 8080),
        started_at=datetime.fromisoformat(info.get("started_at", datetime.now(timezone.utc).isoformat())),
    )
