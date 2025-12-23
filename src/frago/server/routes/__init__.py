"""API route handlers for Frago Web Service.

This package contains FastAPI routers for different API domains:
- system: Server status and info endpoints
- recipes: Recipe listing and execution
- tasks: Task/session management
- config: User configuration
- agent: Agent task execution
- skills: Claude Code skills
- settings: Main config, env vars, GitHub integration
"""

from frago.server.routes.system import router as system_router
from frago.server.routes.recipes import router as recipes_router
from frago.server.routes.tasks import router as tasks_router
from frago.server.routes.agent import router as agent_router
from frago.server.routes.config import router as config_router
from frago.server.routes.skills import router as skills_router
from frago.server.routes.settings import router as settings_router

__all__ = [
    "system_router",
    "recipes_router",
    "tasks_router",
    "agent_router",
    "config_router",
    "skills_router",
    "settings_router",
]
