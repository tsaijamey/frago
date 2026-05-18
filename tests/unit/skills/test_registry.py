"""Tests for frago.skills.registry module.

Tests skill scanning and YAML frontmatter parsing.
"""
from pathlib import Path

import pytest

from frago.skills.registry import InvalidSkill, Skill, SkillRegistry


class TestSkillRegistry:
    """Test SkillRegistry class."""

    @pytest.fixture
    def skills_dir(self, tmp_path: Path) -> Path:
        """Create temp skills directory."""
        skills = tmp_path / "skills"
        skills.mkdir()
        return skills

    @pytest.fixture
    def registry(self, skills_dir: Path) -> SkillRegistry:
        """Create SkillRegistry with temp directory."""
        return SkillRegistry(skills_dir=skills_dir)

    def test_empty_directory(self, registry: SkillRegistry):
        """Empty directory should result in no skills."""
        registry.scan()

        assert len(registry.skills) == 0
        assert len(registry.invalid_skills) == 0

    def test_nonexistent_directory(self, tmp_path: Path):
        """Non-existent directory should not fail."""
        registry = SkillRegistry(skills_dir=tmp_path / "nonexistent")
        registry.scan()

        assert len(registry.skills) == 0

    def test_valid_skill(self, skills_dir: Path, registry: SkillRegistry):
        """Valid skill directory should be loaded."""
        # Create valid skill
        skill_dir = skills_dir / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: test-skill
description: A test skill for testing
---

# Test Skill

Content here.
"""
        )

        registry.scan()

        assert len(registry.skills) == 1
        assert registry.skills[0].name == "test-skill"
        assert registry.skills[0].description == "A test skill for testing"
        assert registry.skills[0].path == skill_dir

    def test_missing_skill_md(self, skills_dir: Path, registry: SkillRegistry):
        """Directory without SKILL.md should be invalid."""
        # Create directory without SKILL.md
        skill_dir = skills_dir / "invalid-skill"
        skill_dir.mkdir()

        registry.scan()

        assert len(registry.skills) == 0
        assert len(registry.invalid_skills) == 1
        assert registry.invalid_skills[0].reason == "Missing SKILL.md file"

    def test_missing_name_field(self, skills_dir: Path, registry: SkillRegistry):
        """Skill without name field should be invalid."""
        skill_dir = skills_dir / "no-name"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
description: Has description but no name
---

Content.
"""
        )

        registry.scan()

        assert len(registry.skills) == 0
        assert len(registry.invalid_skills) == 1
        assert "name" in registry.invalid_skills[0].reason.lower()

    def test_missing_description_field(self, skills_dir: Path, registry: SkillRegistry):
        """Skill without description field should be invalid."""
        skill_dir = skills_dir / "no-desc"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: no-desc-skill
---

Content.
"""
        )

        registry.scan()

        assert len(registry.skills) == 0
        assert len(registry.invalid_skills) == 1
        assert "description" in registry.invalid_skills[0].reason.lower()

    def test_invalid_yaml(self, skills_dir: Path, registry: SkillRegistry):
        """Invalid YAML should result in invalid skill."""
        skill_dir = skills_dir / "bad-yaml"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: [invalid yaml
description: missing bracket
---

Content.
"""
        )

        registry.scan()

        assert len(registry.skills) == 0
        assert len(registry.invalid_skills) == 1
        assert "yaml" in registry.invalid_skills[0].reason.lower()

    def test_no_frontmatter(self, skills_dir: Path, registry: SkillRegistry):
        """File without frontmatter should be invalid."""
        skill_dir = skills_dir / "no-frontmatter"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """# Just a markdown file

No YAML frontmatter here.
"""
        )

        registry.scan()

        assert len(registry.skills) == 0
        assert len(registry.invalid_skills) == 1
        assert "---" in registry.invalid_skills[0].reason

    def test_skip_hidden_directories(self, skills_dir: Path, registry: SkillRegistry):
        """Hidden directories should be skipped."""
        # Create hidden directory
        hidden_dir = skills_dir / ".hidden-skill"
        hidden_dir.mkdir()
        (hidden_dir / "SKILL.md").write_text(
            """---
name: hidden
description: Should be skipped
---
"""
        )

        # Create valid skill
        valid_dir = skills_dir / "valid-skill"
        valid_dir.mkdir()
        (valid_dir / "SKILL.md").write_text(
            """---
name: valid
description: Should be included
---
"""
        )

        registry.scan()

        assert len(registry.skills) == 1
        assert registry.skills[0].name == "valid"

    def test_skip_files(self, skills_dir: Path, registry: SkillRegistry):
        """Non-directory entries should be skipped."""
        # Create a file (not directory)
        (skills_dir / "not-a-dir.txt").write_text("just a file")

        # Create valid skill
        valid_dir = skills_dir / "valid"
        valid_dir.mkdir()
        (valid_dir / "SKILL.md").write_text(
            """---
name: valid
description: Valid skill
---
"""
        )

        registry.scan()

        assert len(registry.skills) == 1

    def test_multiple_skills_sorted(self, skills_dir: Path, registry: SkillRegistry):
        """Multiple skills should be sorted by name."""
        for name in ["zebra", "apple", "mango"]:
            skill_dir = skills_dir / f"{name}-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                f"""---
name: {name}
description: {name} skill
---
"""
            )

        registry.scan()
        result = registry.list_all()

        assert len(result) == 3
        assert result[0].name == "apple"
        assert result[1].name == "mango"
        assert result[2].name == "zebra"

    def test_rescan_clears_previous(self, skills_dir: Path, registry: SkillRegistry):
        """Rescanning should clear previous results."""
        # First scan with one skill
        skill_dir = skills_dir / "first"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: first
description: First skill
---
"""
        )
        registry.scan()
        assert len(registry.skills) == 1

        # Add invalid skill and rescan
        invalid_dir = skills_dir / "invalid"
        invalid_dir.mkdir()
        # No SKILL.md

        registry.scan()

        assert len(registry.skills) == 1
        assert len(registry.invalid_skills) == 1


class TestParseSkillMd:
    """Test _parse_skill_md() method."""

    @pytest.fixture
    def registry(self, tmp_path: Path) -> SkillRegistry:
        """Create registry."""
        return SkillRegistry(skills_dir=tmp_path)

    def test_parse_valid_frontmatter(self, tmp_path: Path, registry: SkillRegistry):
        """Should parse valid YAML frontmatter."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(
            """---
name: test
description: Test skill
extra_field: extra value
---

# Content
"""
        )

        result = registry._parse_skill_md(skill_md)

        assert result["name"] == "test"
        assert result["description"] == "Test skill"
        assert result["extra_field"] == "extra value"

    def test_unclosed_frontmatter(self, tmp_path: Path, registry: SkillRegistry):
        """Should raise on unclosed frontmatter."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(
            """---
name: test
description: No closing marker
"""
        )

        with pytest.raises(Exception) as exc:
            registry._parse_skill_md(skill_md)

        assert "---" in str(exc.value)

    def test_non_dict_yaml(self, tmp_path: Path, registry: SkillRegistry):
        """Should raise if YAML is not a dict."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(
            """---
- item1
- item2
---

Content.
"""
        )

        with pytest.raises(Exception) as exc:
            registry._parse_skill_md(skill_md)

        assert "dictionary" in str(exc.value).lower()
