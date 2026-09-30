"""Skills API endpoints.

- ``GET /skills``：frago 集中副本 ``~/.frago/skills/`` 里的 skill，会话页敲 ``/`` 时列的就是它；
- ``GET /skills/input-methods``：四家 agent 各自怎么点名 skill、默认从哪儿读；
- ``POST /skills/sync``：立刻扫一轮各家目录，不等定时那一轮。
"""

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter

from frago.server.models import SkillItemResponse
from frago.server.services.skill_service import SkillService, SkillSyncService
from frago.server.state import StateManager
from frago.skills.agent_skills import agent_skill_inputs

router = APIRouter()


@router.get("/skills", response_model=list[SkillItemResponse])
async def list_skills() -> list[SkillItemResponse]:
    """Get list of skills in frago's managed store."""
    state_manager = StateManager.get_instance()

    if state_manager.is_initialized():
        return [
            SkillItemResponse(
                name=s.name,
                description=s.description,
                file_path=s.file_path,
                source_path=s.source_path,
                agents=list(s.agents),
            )
            for s in state_manager.get_skills()
        ]

    return [SkillItemResponse(**s) for s in SkillService.get_skills()]


@router.get("/skills/input-methods")
async def list_skill_input_methods() -> list[dict[str, Any]]:
    """四家 agent 的 skill 原生输入方式与默认安装路径（不存在的路径也列出，带 ``exists``）。"""
    rows = []
    for agent in agent_skill_inputs():
        row = asdict(agent)
        row["roots"] = [
            {"path": str(r.path), "namespace": r.namespace, "exists": r.path.is_dir()}
            for r in agent.roots
        ]
        rows.append(row)
    return rows


@router.post("/skills/sync")
async def sync_skills() -> dict[str, Any]:
    """立刻扫一轮各家 agent 的 skill 目录并同步进集中副本。"""
    report = await SkillSyncService.get_instance().sync_now()
    return {
        "added": report.added,
        "updated": report.updated,
        "removed": report.removed,
        "unchanged": report.unchanged,
    }
