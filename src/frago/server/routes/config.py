"""Configuration API endpoints.

Provides endpoints for reading and updating user configuration.
"""

from fastapi import APIRouter, HTTPException

from frago.server.adapter import FragoApiAdapter
from frago.server.models import ConfigUpdateRequest, UserConfigResponse

router = APIRouter()


@router.get("/config", response_model=UserConfigResponse)
async def get_config() -> UserConfigResponse:
    """Get user configuration.

    Returns current user preferences including theme, font size, etc.
    """
    adapter = FragoApiAdapter.get_instance()
    config = adapter.get_config()

    return UserConfigResponse(
        theme=config.get("theme", "dark"),
        font_size=config.get("font_size", 14),
        show_system_status=config.get("show_system_status", True),
        confirm_on_exit=config.get("confirm_on_exit", True),
        auto_scroll_output=config.get("auto_scroll_output", True),
        max_history_items=config.get("max_history_items", 100),
        shortcuts=config.get("shortcuts", {}),
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
    adapter = FragoApiAdapter.get_instance()

    # Build update dict from non-None fields
    updates = {}
    if request.theme is not None:
        updates["theme"] = request.theme
    if request.font_size is not None:
        updates["font_size"] = request.font_size
    if request.show_system_status is not None:
        updates["show_system_status"] = request.show_system_status
    if request.confirm_on_exit is not None:
        updates["confirm_on_exit"] = request.confirm_on_exit
    if request.auto_scroll_output is not None:
        updates["auto_scroll_output"] = request.auto_scroll_output
    if request.max_history_items is not None:
        updates["max_history_items"] = request.max_history_items
    if request.shortcuts is not None:
        updates["shortcuts"] = request.shortcuts

    if not updates:
        # No updates, just return current config
        return await get_config()

    result = adapter.update_config(updates)

    # Check for error
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=400, detail=result.get("error"))

    return UserConfigResponse(
        theme=result.get("theme", "dark"),
        font_size=result.get("font_size", 14),
        show_system_status=result.get("show_system_status", True),
        confirm_on_exit=result.get("confirm_on_exit", True),
        auto_scroll_output=result.get("auto_scroll_output", True),
        max_history_items=result.get("max_history_items", 100),
        shortcuts=result.get("shortcuts", {}),
    )
