"""Tests for frago.server.services.skill_service module.

技能清单读的是 frago 的集中副本 ``~/.frago/skills/``。用例照旧在 ``~/.claude/skills/``
里摆包，再扫一轮同步进副本，断言的是副本里读出来的样子。
"""


from frago.server.services.skill_service import SkillService as _SkillService
from frago.skills.agent_skills import scan_and_sync


class SkillService:
    """先把各家目录扫进集中副本，再读副本——服务端定时那一轮做的正是这件事。"""

    @staticmethod
    def get_skills(force_reload: bool = False):
        scan_and_sync()
        return _SkillService.get_skills(force_reload=force_reload)


class TestSkillServiceGetSkills:
    """Test SkillService.get_skills() method."""

    def test_empty_when_no_skills_dir(self, mock_home):
        """Should return empty list when skills directory doesn't exist."""
        # mock_home creates .claude/skills/ but it's empty
        result = SkillService.get_skills()
        assert result == []

    def test_loads_valid_skill(self, mock_home):
        """Should load skill with valid SKILL.md."""
        skills_dir = mock_home / ".claude" / "skills"
        skill_dir = skills_dir / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: test-skill
description: A test skill
---

# Test Skill
"""
        )

        result = SkillService.get_skills()

        assert len(result) == 1
        assert result[0]["name"] == "test-skill"
        assert result[0]["description"] == "A test skill"
        assert result[0]["file_path"].endswith(".frago/skills/test-skill/SKILL.md")
        assert result[0]["agents"] == ["claude-code", "opencode"]

    def test_uses_dir_name_as_fallback(self, mock_home):
        """Should use directory name if SKILL.md has no frontmatter."""
        skills_dir = mock_home / ".claude" / "skills"
        skill_dir = skills_dir / "fallback-skill"
        skill_dir.mkdir()
        # Create invalid YAML
        (skill_dir / "SKILL.md").write_text("Not valid frontmatter")

        result = SkillService.get_skills()

        assert len(result) == 1
        assert result[0]["name"] == "fallback-skill"
        assert result[0]["description"] is None

    def test_skips_non_directories(self, mock_home):
        """Should skip files in skills directory."""
        skills_dir = mock_home / ".claude" / "skills"
        (skills_dir / "not-a-skill.txt").write_text("just a file")

        result = SkillService.get_skills()

        assert result == []

    def test_skips_dirs_without_skill_md(self, mock_home):
        """Should skip directories without SKILL.md."""
        skills_dir = mock_home / ".claude" / "skills"
        (skills_dir / "incomplete-skill").mkdir()

        result = SkillService.get_skills()

        assert result == []

    def test_loads_multiple_skills(self, mock_home):
        """Should load multiple skills."""
        skills_dir = mock_home / ".claude" / "skills"

        for name in ["alpha", "beta", "gamma"]:
            skill_dir = skills_dir / f"{name}-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                f"""---
name: {name}
description: {name} skill
---
"""
            )

        result = SkillService.get_skills()

        assert len(result) == 3
        names = [s["name"] for s in result]
        assert "alpha" in names
        assert "beta" in names
        assert "gamma" in names

    def test_force_reload_parameter_ignored(self, mock_home):
        """force_reload parameter should be ignored (always fresh load)."""
        skills_dir = mock_home / ".claude" / "skills"
        skill_dir = skills_dir / "test"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: test
description: test
---
"""
        )

        result1 = SkillService.get_skills(force_reload=False)
        result2 = SkillService.get_skills(force_reload=True)

        # Both should work and return same data
        assert len(result1) == 1
        assert len(result2) == 1
