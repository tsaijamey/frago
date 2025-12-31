"""Skills API endpoints.

Provides endpoints for listing available Claude Code skills.
"""

from typing import List

from fastapi import APIRouter

from frago.server.models import SkillItemResponse
from frago.server.services.cache_service import CacheService
from frago.server.services.skill_service import SkillService

router = APIRouter()


@router.get("/skills", response_model=List[SkillItemResponse])
async def list_skills() -> List[SkillItemResponse]:
    """Get list of available skills.

    Returns all Claude Code skills installed in ~/.claude/skills/
    Uses cache for fast response when available.
    """
    # Use cache if available
    cache = CacheService.get_instance()
    if cache.is_initialized():
        skills = await cache.get_skills()
    else:
        skills = SkillService.get_skills()

    return [
        SkillItemResponse(
            name=s.get("name", ""),
            description=s.get("description"),
            file_path=s.get("file_path"),
        )
        for s in skills
    ]
