"""Skill registry - Scan and manage Claude Code Skills"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class Skill:
    """Valid Skill"""
    name: str
    description: str
    path: Path


@dataclass
class InvalidSkill:
    """Invalid Skill (does not conform to specification)"""
    dir_name: str
    path: Path
    reason: str


class SkillRegistry:
    """Skill registry

    Scans all skills in ~/.claude/skills/ directory,
    parses YAML frontmatter of SKILL.md to get metadata.
    """

    def __init__(self, skills_dir: Optional[Path] = None):
        """Initialize SkillRegistry

        Args:
            skills_dir: skills directory path, defaults to ~/.claude/skills/
        """
        self.skills_dir = skills_dir or (Path.home() / '.claude' / 'skills')
        self.skills: list[Skill] = []
        self.invalid_skills: list[InvalidSkill] = []

    def scan(self) -> None:
        """Scan skills directory, load all valid skills"""
        self.skills.clear()
        self.invalid_skills.clear()

        if not self.skills_dir.exists():
            return

        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue

            # Skip hidden directories
            if skill_dir.name.startswith('.'):
                continue

            skill_md = skill_dir / 'SKILL.md'

            # Check if SKILL.md exists
            if not skill_md.exists():
                self.invalid_skills.append(InvalidSkill(
                    dir_name=skill_dir.name,
                    path=skill_dir,
                    reason="Missing SKILL.md file"
                ))
                continue

            # Parse SKILL.md
            try:
                metadata = self._parse_skill_md(skill_md)
            except Exception as e:
                self.invalid_skills.append(InvalidSkill(
                    dir_name=skill_dir.name,
                    path=skill_dir,
                    reason=str(e)
                ))
                continue

            # Validate required fields
            name = metadata.get('name')
            description = metadata.get('description')

            if not name:
                self.invalid_skills.append(InvalidSkill(
                    dir_name=skill_dir.name,
                    path=skill_dir,
                    reason="Missing name field"
                ))
                continue

            if not description:
                self.invalid_skills.append(InvalidSkill(
                    dir_name=skill_dir.name,
                    path=skill_dir,
                    reason="Missing description field"
                ))
                continue

            # Add valid skill
            self.skills.append(Skill(
                name=name,
                description=description,
                path=skill_dir
            ))

    def _parse_skill_md(self, path: Path) -> dict:
        """Parse YAML frontmatter of SKILL.md file

        Args:
            path: SKILL.md file path

        Returns:
            Parsed metadata dictionary

        Raises:
            Exception: Raised when parsing fails
        """
        content = path.read_text(encoding='utf-8')

        # Check frontmatter start
        if not content.startswith('---'):
            raise Exception("File does not start with '---', missing YAML frontmatter")

        # Split to get YAML section
        parts = content.split('---', 2)
        if len(parts) < 3:
            raise Exception("YAML frontmatter format error, missing closing '---'")

        yaml_content = parts[1].strip()

        # Parse YAML
        try:
            data = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise Exception(f"YAML parsing failed: {e}")

        if not isinstance(data, dict):
            raise Exception("YAML frontmatter must be in dictionary format")

        return data

    def list_all(self) -> list[Skill]:
        """Get list of all valid skills (sorted by name)"""
        return sorted(self.skills, key=lambda s: s.name)

    def get_invalid(self) -> list[InvalidSkill]:
        """Get list of all invalid skills"""
        return self.invalid_skills
