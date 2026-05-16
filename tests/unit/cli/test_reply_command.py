"""Tests for frago reply CLI command."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from click.testing import CliRunner

import frago.cli.reply_command as reply_mod
from frago.cli.reply_command import reply_cmd


def _set_config(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")


def _sample_config():
    return {
        "task_ingestion": {
            "channels": [
                {
                    "name": "email",
                    "poll_recipe": "poll_email",
                    "notify_recipe": "send_email_reply",
                },
                {
                    "name": "slack",
                    "poll_recipe": "poll_slack",
                    "notify_recipe": "send_slack_reply",
                },
            ]
        }
    }


class TestReplyCommand:
    def test_reply_success(self, tmp_path):
        config_file = tmp_path / "config.json"
        _set_config(config_file, _sample_config())

        orig = reply_mod.CONFIG_FILE
        reply_mod.CONFIG_FILE = config_file
        try:
            mock_runner = MagicMock()
            mock_runner.run.return_value = {"success": True}
            with patch("frago.recipes.RecipeRunner", return_value=mock_runner):
                runner = CliRunner()
                result = runner.invoke(
                    reply_cmd,
                    ["--channel", "email", "--params", '{"status": "completed"}'],
                )
                assert result.exit_code == 0, result.output
                assert "Reply sent via email" in result.output
                mock_runner.run.assert_called_once_with(
                    "send_email_reply", params={"status": "completed"}
                )
        finally:
            reply_mod.CONFIG_FILE = orig

    def test_reply_channel_not_found(self, tmp_path):
        config_file = tmp_path / "config.json"
        _set_config(config_file, _sample_config())

        orig = reply_mod.CONFIG_FILE
        reply_mod.CONFIG_FILE = config_file
        try:
            runner = CliRunner()
            result = runner.invoke(reply_cmd, ["--channel", "telegram"])
            assert result.exit_code != 0
            assert "telegram" in result.output
            assert "email" in result.output
        finally:
            reply_mod.CONFIG_FILE = orig

    def test_reply_no_config(self, tmp_path):
        config_file = tmp_path / "nonexistent" / "config.json"

        orig = reply_mod.CONFIG_FILE
        reply_mod.CONFIG_FILE = config_file
        try:
            runner = CliRunner()
            result = runner.invoke(reply_cmd, ["--channel", "email"])
            assert result.exit_code != 0
            assert "config.json not found" in result.output
        finally:
            reply_mod.CONFIG_FILE = orig

    def test_reply_recipe_failure(self, tmp_path):
        config_file = tmp_path / "config.json"
        _set_config(config_file, _sample_config())

        orig = reply_mod.CONFIG_FILE
        reply_mod.CONFIG_FILE = config_file
        try:
            mock_runner = MagicMock()
            mock_runner.run.return_value = {"success": False, "error": "smtp timeout"}
            with patch("frago.recipes.RecipeRunner", return_value=mock_runner):
                runner = CliRunner()
                result = runner.invoke(reply_cmd, ["--channel", "email"])
                assert result.exit_code != 0
                assert "smtp timeout" in result.output
        finally:
            reply_mod.CONFIG_FILE = orig

    def test_reply_invalid_params_json(self, tmp_path):
        config_file = tmp_path / "config.json"
        _set_config(config_file, _sample_config())

        orig = reply_mod.CONFIG_FILE
        reply_mod.CONFIG_FILE = config_file
        try:
            runner = CliRunner()
            result = runner.invoke(
                reply_cmd, ["--channel", "email", "--params", "not-json"]
            )
            assert result.exit_code != 0
            assert "Invalid params JSON" in result.output
        finally:
            reply_mod.CONFIG_FILE = orig

    def test_reply_selects_correct_channel(self, tmp_path):
        config_file = tmp_path / "config.json"
        _set_config(config_file, _sample_config())

        orig = reply_mod.CONFIG_FILE
        reply_mod.CONFIG_FILE = config_file
        try:
            mock_runner = MagicMock()
            mock_runner.run.return_value = {"success": True}
            with patch("frago.recipes.RecipeRunner", return_value=mock_runner):
                runner = CliRunner()
                result = runner.invoke(reply_cmd, ["--channel", "slack"])
                assert result.exit_code == 0, result.output
                mock_runner.run.assert_called_once_with(
                    "send_slack_reply", params={}
                )
        finally:
            reply_mod.CONFIG_FILE = orig
