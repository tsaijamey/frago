"""Skills API endpoints.

Provides endpoints for listing available Claude Code skills.
Uses StateManager for unified state access.
"""

from typing import List

from fastapi import APIRouter

from frago.server.models import SkillItemResponse
from frago.server.state import StateManager
from frago.server.services.skill_service import SkillService

router = APIRouter()


@router.get("/skills", response_model=List[SkillItemResponse])
async def list_skills() -> List[SkillItemResponse]:
    """Get list of available skills.

    Returns all Claude Code skills installed in ~/.claude/skills/
    Uses StateManager for unified state access.
    """
    state_manager = StateManager.get_instance()

    # Use StateManager if initialized
    if state_manager.is_initialized():
        skills = state_manager.get_skills()
        return [
            SkillItemResponse(
                name=s.name,
                description=s.description,
                file_path=s.file_path,
            )
            for s in skills
        ]

    # Fallback to direct service call
    skills = SkillService.get_skills()
    return [
        SkillItemResponse(
            name=s.get("name", ""),
            description=s.get("description"),
            file_path=s.get("file_path"),
        )
        for s in skills
    ]
