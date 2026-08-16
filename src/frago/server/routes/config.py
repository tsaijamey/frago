"""Configuration API endpoints.

Provides endpoints for reading and updating user configuration.
"""

from fastapi import APIRouter, HTTPException

from frago.init.config_manager import load_config
from frago.server.models import (
    ConfigUpdateRequest,
    UserConfigResponse,
    WebuiSessionsResponse,
)
from frago.config.config_service import ConfigService, ConfigValidationError
from frago.server.state import StateManager

router = APIRouter()


def _webui_sessions_response() -> WebuiSessionsResponse:
    """Read webui_sessions from ~/.frago/config.json (缺省自愈在 load_config 内完成)."""
    ws = load_config().webui_sessions
    return WebuiSessionsResponse(
        max_resident=ws.max_resident,
        idle_timeout_secs=ws.idle_timeout_secs,
    )


@router.get("/config", response_model=UserConfigResponse)
async def get_config() -> UserConfigResponse:
    """Get user configuration.

    Returns current user preferences including theme, font size, etc.
    """
    config = ConfigService.get_config()

    return UserConfigResponse(
        theme=config.get("theme", "dark"),
        language=config.get("language", "en"),
        font_size=config.get("font_size", 14),
        max_history_items=config.get("max_history_items", 100),
        shortcuts=config.get("shortcuts", {}),
        ai_title_enabled=config.get("ai_title_enabled", False),
        webui_sessions=_webui_sessions_response(),
    )


@router.put("/config", response_model=UserConfigResponse)
async def update_config(request: ConfigUpdateRequest) -> UserConfigResponse:
    """Update user configuration.

    Args:
        request: Configuration updates (partial update supported)

    Returns:
        Updated configuration

    Raises:
        HTTPException: 400 if configuration is invalid
    """
    # Build update dict from non-None fields
    updates = {}
    if request.theme is not None:
        updates["theme"] = request.theme
    if request.language is not None:
        updates["language"] = request.language
    if request.font_size is not None:
        updates["font_size"] = request.font_size
    if request.max_history_items is not None:
        updates["max_history_items"] = request.max_history_items
    if request.shortcuts is not None:
        updates["shortcuts"] = request.shortcuts
    if request.ai_title_enabled is not None:
        updates["ai_title_enabled"] = request.ai_title_enabled

    if not updates:
        # No updates, just return current config
        return await get_config()

    try:
        result = ConfigService.update_config(updates)
    except ConfigValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Refresh cache after update
    state_manager = StateManager.get_instance()
    await state_manager.refresh_config(broadcast=True)

    return UserConfigResponse(
        theme=result.get("theme", "dark"),
        language=result.get("language", "en"),
        font_size=result.get("font_size", 14),
        max_history_items=result.get("max_history_items", 100),
        shortcuts=result.get("shortcuts", {}),
        ai_title_enabled=result.get("ai_title_enabled", False),
        webui_sessions=_webui_sessions_response(),
    )
