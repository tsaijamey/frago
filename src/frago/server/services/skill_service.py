"""Skill management service.

Provides functionality to list and load skills from ~/.claude/skills/ directory.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import frontmatter

logger = logging.getLogger(__name__)


class SkillService:
    """Service for skill management operations."""

    # Cache for loaded skills
    _cache: Optional[List[Dict[str, Any]]] = None

    @classmethod
    def get_skills(cls, force_reload: bool = False) -> List[Dict[str, Any]]:
        """Get list of available skills.

        Args:
            force_reload: If True, bypass cache and reload from filesystem.

        Returns:
            List of skill dictionaries with name, description, file_path.
        """
        if cls._cache is None or force_reload:
            cls._cache = cls._load_skills()
        return cls._cache

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the skill cache."""
        cls._cache = None

    @staticmethod
    def _load_skills() -> List[Dict[str, Any]]:
        """Load skills from ~/.claude/skills/ directory.

        Skills are organized as directories with SKILL.md files containing
        YAML frontmatter for name and description.

        Returns:
            List of skill dictionaries.
        """
        skills = []
        skills_dir = Path.home() / ".claude" / "skills"

        if not skills_dir.exists():
            logger.debug("Skills directory does not exist: %s", skills_dir)
            return skills

        for skill_path in skills_dir.iterdir():
            if not skill_path.is_dir():
                continue

            skill_file = skill_path / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                post = frontmatter.load(skill_file)
                name = post.get("name", skill_path.name)
                description = post.get("description")

                skills.append({
                    "name": name,
                    "description": description,
                    "file_path": str(skill_file),
                })
            except Exception as e:
                logger.warning(
                    "Failed to parse skill file %s: %s",
                    skill_file,
                    e,
                )
                # Fallback: use directory name
                skills.append({
                    "name": skill_path.name,
                    "description": None,
                    "file_path": str(skill_file),
                })

        logger.debug("Loaded %d skills from %s", len(skills), skills_dir)
        return skills
