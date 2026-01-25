"""Server state management module.

Provides unified state management for all server data with:
- Type-safe data models
- Single source of truth
- Centralized refresh mechanism
- WebSocket broadcast on changes
"""

from frago.server.state.manager import StateManager
from frago.server.state.models import (
    ServerState,
    TaskItem,
    TaskDetail,
    TaskStep,
    Recipe,
    Skill,
    Project,
    DashboardData,
)

__all__ = [
    "StateManager",
    "ServerState",
    "TaskItem",
    "TaskDetail",
    "TaskStep",
    "Recipe",
    "Skill",
    "Project",
    "DashboardData",
]
