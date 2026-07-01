"""Unit tests for StateLoader extracted from StateManager (Phase 3).

以单元测试为准：断言 loader 把下层 service 返回的原始数据正确映射成 state model，
并在下层异常时安全降级（返回空/默认）。下层 service 全部 mock。
"""

from unittest.mock import MagicMock, patch

from frago.server.state.loader import StateLoader
from frago.server.state.models import Project, Recipe, Skill


def test_load_recipes_maps_fields():
    raw = [{"name": "r1", "category": "atomic", "tags": ["a"], "runtime": "python"}]
    with patch("frago.server.services.recipe_service.RecipeService.get_recipes", return_value=raw):
        out = StateLoader.load_recipes()
    assert len(out) == 1
    assert isinstance(out[0], Recipe)
    assert out[0].name == "r1"
    assert out[0].runtime == "python"


def test_load_recipes_degrades_on_error():
    with patch("frago.server.services.recipe_service.RecipeService.get_recipes", side_effect=RuntimeError("boom")):
        assert StateLoader.load_recipes() == []


def test_load_skills_maps_fields():
    raw = [{"name": "s1", "description": "d", "file_path": "/p"}]
    with patch("frago.server.services.skill_service.SkillService.get_skills", return_value=raw):
        out = StateLoader.load_skills()
    assert len(out) == 1 and isinstance(out[0], Skill) and out[0].name == "s1"


def test_load_projects_parses_last_accessed():
    p = MagicMock(run_id="run1", theme_description="theme", last_accessed="2026-06-29T10:00:00")
    with patch("frago.server.services.file_service.FileService.list_projects", return_value=[p]):
        out = StateLoader.load_projects()
    assert len(out) == 1 and isinstance(out[0], Project)
    assert out[0].name == "theme"
    assert out[0].last_accessed is not None


def test_load_projects_tolerates_bad_timestamp():
    p = MagicMock(run_id="run1", theme_description=None, last_accessed="not-a-date")
    with patch("frago.server.services.file_service.FileService.list_projects", return_value=[p]):
        out = StateLoader.load_projects()
    assert out[0].name == "run1"  # falls back to run_id
    assert out[0].last_accessed is None


def test_load_config_delegates():
    with patch("frago.server.services.main_config_service.MainConfigService.get_config", return_value={"k": "v"}):
        assert StateLoader.load_config() == {"k": "v"}


def test_load_gh_status_default_on_error():
    with patch("frago.server.services.github_service.GitHubService.check_gh_cli", side_effect=RuntimeError):
        out = StateLoader.load_gh_status()
    assert out == {"installed": False, "authenticated": False, "username": None}
