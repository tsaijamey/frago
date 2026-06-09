"""API route handlers for Frago Web Service.

This package contains FastAPI routers for different API domains:
- system: Server status and info endpoints
- dashboard: Dashboard overview data
- recipes: Recipe listing and execution
- tasks: Task/session management
- config: User configuration
- agent: Agent task execution
- skills: Claude Code skills
- settings: Main config, env vars, GitHub integration
- github_star: Star/unstar the frago repository
- init: Web-based initialization (dependency check, resource install)
- viewer: Content preview file serving
- guide: Tutorial and FAQ content
"""

from frago.server.routes.agent import router as agent_router
from frago.server.routes.chrome_dashboard import router as chrome_dashboard_router
from frago.server.routes.claude_sessions import router as claude_sessions_router
from frago.server.routes.config import router as config_router
from frago.server.routes.files import router as files_router
from frago.server.routes.github_star import router as github_star_router
from frago.server.routes.guide import router as guide_router
from frago.server.routes.init import router as init_router
from frago.server.routes.pa import router as pa_router
from frago.server.routes.recipes import router as recipes_router
from frago.server.routes.settings import router as settings_router
from frago.server.routes.skills import router as skills_router
from frago.server.routes.system import router as system_router
from frago.server.routes.viewer import router as viewer_router
from frago.server.routes.workspace import router as workspace_router

__all__ = [
    "system_router",
    "recipes_router",
    "agent_router",
    "config_router",
    "skills_router",
    "settings_router",
    "github_star_router",
    "init_router",
    "viewer_router",
    "files_router",
    "workspace_router",
    "guide_router",
    "pa_router",
    "chrome_dashboard_router",
    "claude_sessions_router",
]
