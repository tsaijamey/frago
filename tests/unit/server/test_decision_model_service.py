"""Unit tests for DecisionModelService and /settings/decision-model routes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from frago.init.models import Config
from frago.init.profile_manager import APIProfile, ProfileStore, load_profiles, save_profiles
from frago.server.services.decision_model_service import DecisionModelService


@pytest.fixture()
def isolated_frago_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect config.json and profiles.json to a temporary directory."""
    config_file = tmp_path / "config.json"
    profiles_file = tmp_path / "profiles.json"

    monkeypatch.setattr("frago.init.config_manager.CONFIG_PATH", config_file)
    monkeypatch.setattr("frago.init.profile_manager.PROFILES_PATH", profiles_file)
    return tmp_path


def test_default_unconfigured_state_has_no_presets(isolated_frago_home: Path) -> None:
    """When config.json has no decision_model, get_settings reports blank fields and no presets."""
    settings = DecisionModelService.get_settings()
    assert settings["configured"] is False
    assert settings["enabled"] is False
    assert settings["wire"] == "decisions"
    assert settings["url"] is None
    assert settings["model"] == ""
    assert settings["temperature"] is None
    assert "presets" not in settings


def test_update_custom_ollama_decision_model(isolated_frago_home: Path) -> None:
    """Saving a custom Ollama decision model persists user-entered URL, model, and temperature."""
    saved = DecisionModelService.update_settings(
        enabled=True,
        wire="ollama",
        url="http://127.0.0.1:11434",
        model="intern-decision:0.8b",
        temperature=None,
    )
    assert saved["configured"] is True
    assert saved["enabled"] is True
    assert saved["wire"] == "ollama"
    assert saved["url"] == "http://127.0.0.1:11434"
    assert saved["model"] == "intern-decision:0.8b"
    assert saved["temperature"] is None

    raw = json.loads((isolated_frago_home / "config.json").read_text(encoding="utf-8"))
    assert raw["decision_model"]["wire"] == "ollama"
    assert raw["decision_model"]["model"] == "intern-decision:0.8b"


def test_update_external_decisions_endpoint_and_key_preservation(
    isolated_frago_home: Path,
) -> None:
    """Saving an external HTTP Decision API endpoint masks key, preserves it on blank update, and syncs to profiles.json."""
    store = ProfileStore(
        active_profile_id="p1",
        profiles=[
            APIProfile(
                id="p1",
                name="Main Endpoint",
                endpoint_type="custom",
                url="https://api.example.com",
                api_key="sk-main-12345678",
            )
        ],
    )
    save_profiles(store)

    saved = DecisionModelService.update_settings(
        enabled=True,
        wire="decisions",
        url="https://openrouter.ai/api/alpha/decisions",
        model="clef",
        api_key="sk-or-v1-secretkey9876",
    )
    assert saved["configured"] is True
    assert saved["wire"] == "decisions"
    assert saved["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert saved["model"] == "clef"
    assert saved["has_api_key"] is True
    assert "secretkey" not in saved["api_key_masked"]

    reloaded_store = load_profiles()
    assert (
        reloaded_store.profiles[0].decision_url
        == "https://openrouter.ai/api/alpha/decisions"
    )
    assert reloaded_store.profiles[0].decision_model == "clef"
    assert reloaded_store.profiles[0].decision_api_key == "sk-or-v1-secretkey9876"

    # Subsequent update with blank api_key preserves existing key
    updated = DecisionModelService.update_settings(
        enabled=True,
        wire="decisions",
        url="https://custom.decisions.example/v1/decisions",
        model="custom-decision-v1",
        api_key="",
    )
    assert updated["has_api_key"] is True
    assert updated["url"] == "https://custom.decisions.example/v1/decisions"
    assert updated["model"] == "custom-decision-v1"

    # Clear API key explicitly
    cleared_key = DecisionModelService.update_settings(
        enabled=True,
        wire="decisions",
        url="https://custom.decisions.example/v1/decisions",
        model="custom-decision-v1",
        clear_api_key=True,
    )
    assert cleared_key["has_api_key"] is False
    assert cleared_key["api_key_masked"] == ""

    # Reset clears decision_model from config.json and profiles.json
    reset = DecisionModelService.reset_settings()
    assert reset["configured"] is False
    reloaded_after_reset = load_profiles()
    assert reloaded_after_reset.profiles[0].decision_url is None
    assert reloaded_after_reset.profiles[0].decision_model is None
    assert reloaded_after_reset.profiles[0].decision_api_key is None


def test_validation_rejects_missing_url_or_model(
    isolated_frago_home: Path,
) -> None:
    """Both request modes require explicit endpoint URL and model name."""
    with pytest.raises(ValueError, match="Endpoint URL is required"):
        DecisionModelService.update_settings(
            enabled=True,
            wire="ollama",
            url="",
            model="intern-decision:0.8b",
        )

    with pytest.raises(ValueError, match="Model name is required"):
        DecisionModelService.update_settings(
            enabled=True,
            wire="decisions",
            url="https://openrouter.ai/api/alpha/decisions",
            model="   ",
        )

    assert (isolated_frago_home / "config.json").exists() is False or (
        Config.model_validate_json(
            (isolated_frago_home / "config.json").read_text(encoding="utf-8")
        ).decision_model
        is None
    )
