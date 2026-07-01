"""StateLoader — server 全局状态的数据加载层（唯一做加载 IO 的地方）。

从 StateManager 拆出：这些方法原本是 StateManager 上不依赖任何实例状态的纯加载函数
（只调下层 service 再映射成 state model）。抽成静态方法后，StateManager 退化为门面，
加载逻辑集中在此，便于单测与复用。行为与原 StateManager._load_* 完全一致。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from frago.server.state.models import Project, Recipe, Skill

logger = logging.getLogger(__name__)


class StateLoader:
    """server 状态的数据加载器。所有方法为静态、纯加载（无实例状态）。"""

    @staticmethod
    def load_recipes() -> List[Recipe]:
        """Load recipes from storage."""
        try:
            from frago.server.services.recipe_service import RecipeService

            raw_recipes = RecipeService.get_recipes(force_reload=True)
            recipes = []
            for r in raw_recipes:
                recipes.append(
                    Recipe(
                        name=r.get("name", ""),
                        description=r.get("description"),
                        category=r.get("category", "atomic"),
                        icon=r.get("icon"),
                        tags=r.get("tags", []),
                        path=r.get("path"),
                        source=r.get("source"),
                        runtime=r.get("runtime"),
                    )
                )
            return recipes
        except Exception as e:
            logger.error(f"Failed to load recipes: {e}")
            return []

    @staticmethod
    def load_skills() -> List[Skill]:
        """Load skills from storage."""
        try:
            from frago.server.services.skill_service import SkillService

            raw_skills = SkillService.get_skills(force_reload=True)
            skills = []
            for s in raw_skills:
                skills.append(
                    Skill(
                        name=s.get("name", ""),
                        description=s.get("description"),
                        file_path=s.get("file_path"),
                    )
                )
            return skills
        except Exception as e:
            logger.error(f"Failed to load skills: {e}")
            return []

    @staticmethod
    def load_projects() -> List[Project]:
        """Load projects from storage."""
        try:
            from datetime import datetime
            from pathlib import Path

            from frago.server.services.file_service import FileService

            projects_dir = Path.home() / ".frago" / "projects"
            raw_projects = FileService.list_projects()
            projects = []
            for p in raw_projects:
                # Parse last_accessed from ISO format string to datetime
                last_accessed = None
                if p.last_accessed:
                    try:
                        last_accessed = datetime.fromisoformat(p.last_accessed)
                    except (ValueError, TypeError):
                        pass

                projects.append(
                    Project(
                        path=str(projects_dir / p.run_id),
                        name=p.theme_description or p.run_id,
                        last_accessed=last_accessed,
                    )
                )
            return projects
        except Exception as e:
            logger.error(f"Failed to load projects: {e}")
            return []

    @staticmethod
    def load_config() -> Dict[str, Any]:
        """Load main config from storage."""
        try:
            from frago.server.services.main_config_service import MainConfigService

            return MainConfigService.get_config()
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return {}

    @staticmethod
    def load_gh_status() -> Dict[str, Any]:
        """Load GitHub CLI status."""
        try:
            from frago.server.services.github_service import GitHubService

            return GitHubService.check_gh_cli()
        except Exception as e:
            logger.error(f"Failed to load gh status: {e}")
            return {"installed": False, "authenticated": False, "username": None}
