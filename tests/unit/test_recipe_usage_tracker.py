"""Tests for recipe usage tracker."""

import json
from unittest.mock import patch, MagicMock

import pytest

from frago.recipes.usage_tracker import (
    record_usage,
    get_usage,
    get_top_recipes,
    _load_usage,
    USAGE_FILE,
)


@pytest.fixture(autouse=True)
def tmp_usage_file(tmp_path, monkeypatch):
    """Redirect USAGE_FILE to a temp location."""
    fake_file = tmp_path / "recipe_usage.json"
    monkeypatch.setattr("frago.recipes.usage_tracker.USAGE_FILE", fake_file)
    return fake_file


class TestRecordUsage:
    def test_first_usage(self, tmp_usage_file):
        record_usage("my-recipe")
        data = json.loads(tmp_usage_file.read_text())
        assert data["my-recipe"]["run_count"] == 1
        assert data["my-recipe"]["last_used"] is not None

    def test_increments_count(self, tmp_usage_file):
        record_usage("my-recipe")
        record_usage("my-recipe")
        data = json.loads(tmp_usage_file.read_text())
        assert data["my-recipe"]["run_count"] == 2

    def test_multiple_recipes(self, tmp_usage_file):
        record_usage("recipe-a")
        record_usage("recipe-b")
        data = json.loads(tmp_usage_file.read_text())
        assert "recipe-a" in data
        assert "recipe-b" in data


class TestGetUsage:
    def test_nonexistent_recipe(self):
        result = get_usage("nonexistent")
        assert result == {"run_count": 0, "last_used": None}

    def test_existing_recipe(self, tmp_usage_file):
        record_usage("test-recipe")
        result = get_usage("test-recipe")
        assert result["run_count"] == 1
        assert result["last_used"] is not None


class TestGetTopRecipes:
    def test_empty(self):
        result = get_top_recipes()
        assert result == []

    def test_sorted_by_last_used(self, tmp_usage_file):
        # Record in order: a, b, c — c should be most recent
        record_usage("recipe-a")
        record_usage("recipe-b")
        record_usage("recipe-c")
        result = get_top_recipes(limit=5)
        # Most recently used first
        assert result[0] == "recipe-c"

    def test_limit(self, tmp_usage_file):
        for i in range(10):
            record_usage(f"recipe-{i}")
        result = get_top_recipes(limit=3)
        assert len(result) == 3

    def test_corrupted_file(self, tmp_usage_file):
        tmp_usage_file.write_text("not valid json")
        result = get_top_recipes()
        assert result == []


class TestExtractErrorSummary:
    """Test TaskService.extract_error_summary."""

    def test_returns_error_content(self):
        from frago.server.services.task_service import TaskService

        mock_step = MagicMock()
        mock_step.content_summary = "Error: Chrome disconnected during navigation"

        with patch(
            "frago.server.services.task_service.TaskService.extract_error_summary"
        ) as mock_method:
            # Direct test of the logic
            pass

        # Test actual method with mocked storage
        with patch("frago.session.storage.read_steps_paginated") as mock_read:
            mock_read.return_value = {"steps": [mock_step]}
            result = TaskService.extract_error_summary("fake-session-id")
            assert result is not None
            assert "Error" in result

    def test_returns_none_for_no_error(self):
        from frago.server.services.task_service import TaskService

        mock_step = MagicMock()
        mock_step.content_summary = "Successfully completed all steps"

        with patch("frago.session.storage.read_steps_paginated") as mock_read:
            mock_read.return_value = {"steps": [mock_step]}
            result = TaskService.extract_error_summary("fake-session-id")
            assert result is None

    def test_truncates_to_100_chars(self):
        from frago.server.services.task_service import TaskService

        mock_step = MagicMock()
        mock_step.content_summary = "Error: " + "x" * 200

        with patch("frago.session.storage.read_steps_paginated") as mock_read:
            mock_read.return_value = {"steps": [mock_step]}
            result = TaskService.extract_error_summary("fake-session-id")
            assert result is not None
            assert len(result) <= 100

    def test_handles_exception_gracefully(self):
        from frago.server.services.task_service import TaskService

        with patch("frago.session.storage.read_steps_paginated") as mock_read:
            mock_read.side_effect = Exception("Storage error")
            result = TaskService.extract_error_summary("fake-session-id")
            assert result is None
