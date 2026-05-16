"""Tests for frago.init.profile_manager module.

Tests CRUD operations, activation/deactivation, and edge cases.
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from frago.init.profile_manager import (
    APIProfile,
    ProfileStore,
    add_profile,
    activate_profile,
    create_profile_from_current,
    deactivate_profile,
    delete_profile,
    get_profile,
    load_profiles,
    save_profiles,
    update_profile,
)


@pytest.fixture
def tmp_profiles_path(tmp_path):
    """Patch PROFILES_PATH to use a temp directory."""
    profiles_path = tmp_path / "profiles.json"
    with patch("frago.init.profile_manager.PROFILES_PATH", profiles_path):
        yield profiles_path


@pytest.fixture
def sample_profile():
    """Create a sample APIProfile for testing."""
    return APIProfile(
        id="test1234",
        name="Test DeepSeek",
        endpoint_type="deepseek",
        api_key="sk-test-key-1234567890",
    )


@pytest.fixture
def sample_store(sample_profile):
    """Create a ProfileStore with one profile."""
    return ProfileStore(profiles=[sample_profile])


class TestLoadSaveProfiles:
    """Test load_profiles and save_profiles."""

    def test_load_empty_when_no_file(self, tmp_profiles_path):
        """Returns empty ProfileStore when file doesn't exist."""
        store = load_profiles()
        assert store.profiles == []
        assert store.active_profile_id is None

    def test_save_and_load(self, tmp_profiles_path, sample_store):
        """Save and load preserves data."""
        save_profiles(sample_store)
        loaded = load_profiles()
        assert len(loaded.profiles) == 1
        assert loaded.profiles[0].id == "test1234"
        assert loaded.profiles[0].name == "Test DeepSeek"
        assert loaded.profiles[0].api_key == "sk-test-key-1234567890"

    def test_load_corrupted_file(self, tmp_profiles_path):
        """Returns empty store on corrupted JSON."""
        tmp_profiles_path.write_text("not json", encoding="utf-8")
        store = load_profiles()
        assert store.profiles == []

    def test_save_creates_parent_dir(self, tmp_path):
        """save_profiles creates parent directory."""
        nested_path = tmp_path / "subdir" / "profiles.json"
        with patch("frago.init.profile_manager.PROFILES_PATH", nested_path):
            save_profiles(ProfileStore())
        assert nested_path.exists()


class TestAddProfile:
    """Test add_profile."""

    def test_add_to_empty(self, tmp_profiles_path, sample_profile):
        """Add profile to empty store."""
        store = add_profile(sample_profile)
        assert len(store.profiles) == 1
        assert store.profiles[0].name == "Test DeepSeek"

    def test_add_multiple(self, tmp_profiles_path, sample_profile):
        """Add multiple profiles."""
        add_profile(sample_profile)
        second = APIProfile(
            id="test5678",
            name="Test Kimi",
            endpoint_type="kimi",
            api_key="sk-kimi-key",
        )
        store = add_profile(second)
        assert len(store.profiles) == 2


class TestUpdateProfile:
    """Test update_profile."""

    def test_update_name(self, tmp_profiles_path, sample_profile):
        """Update profile name."""
        add_profile(sample_profile)
        store = update_profile("test1234", {"name": "Updated Name"})
        assert store.profiles[0].name == "Updated Name"

    def test_update_preserves_api_key_on_empty(self, tmp_profiles_path, sample_profile):
        """Empty api_key in updates preserves existing key."""
        add_profile(sample_profile)
        store = update_profile("test1234", {"name": "New", "api_key": ""})
        assert store.profiles[0].api_key == "sk-test-key-1234567890"

    def test_update_nonexistent_raises(self, tmp_profiles_path):
        """Raises ValueError for nonexistent profile."""
        with pytest.raises(ValueError, match="Profile not found"):
            update_profile("nonexistent", {"name": "Test"})

    def test_update_ignores_id(self, tmp_profiles_path, sample_profile):
        """Cannot update profile ID."""
        add_profile(sample_profile)
        store = update_profile("test1234", {"id": "hacked"})
        assert store.profiles[0].id == "test1234"


class TestDeleteProfile:
    """Test delete_profile."""

    def test_delete_existing(self, tmp_profiles_path, sample_profile):
        """Delete existing profile."""
        add_profile(sample_profile)
        store = delete_profile("test1234")
        assert len(store.profiles) == 0

    def test_delete_nonexistent_raises(self, tmp_profiles_path):
        """Raises ValueError for nonexistent profile."""
        with pytest.raises(ValueError, match="Profile not found"):
            delete_profile("nonexistent")

    def test_delete_active_clears_active_id(self, tmp_profiles_path, sample_profile):
        """Deleting active profile sets active_profile_id to None."""
        add_profile(sample_profile)
        store = load_profiles()
        store.active_profile_id = "test1234"
        save_profiles(store)

        store = delete_profile("test1234")
        assert store.active_profile_id is None


class TestGetProfile:
    """Test get_profile."""

    def test_get_existing(self, tmp_profiles_path, sample_profile):
        """Get existing profile by ID."""
        add_profile(sample_profile)
        profile = get_profile("test1234")
        assert profile is not None
        assert profile.name == "Test DeepSeek"

    def test_get_nonexistent(self, tmp_profiles_path):
        """Returns None for nonexistent profile."""
        profile = get_profile("nonexistent")
        assert profile is None


class TestActivateProfile:
    """Test activate_profile."""

    def test_activate_writes_settings(self, tmp_profiles_path, sample_profile):
        """Activate profile calls configurator functions and updates active_profile_id."""
        add_profile(sample_profile)

        with (
            patch("frago.init.configurator.build_claude_env_config") as mock_build,
            patch("frago.init.configurator.save_claude_settings") as mock_save_settings,
            patch("frago.init.configurator.ensure_claude_json_for_custom_auth") as mock_ensure,
            patch("frago.init.config_manager.load_config") as mock_load_config,
            patch("frago.init.config_manager.save_config") as mock_save_config,
        ):
            mock_config = MagicMock()
            mock_load_config.return_value = mock_config
            mock_build.return_value = {"ANTHROPIC_API_KEY": "sk-test-key-1234567890"}

            activate_profile("test1234")

            mock_build.assert_called_once_with(
                endpoint_type="deepseek",
                api_key="sk-test-key-1234567890",
                custom_url=None,
                default_model=None,
                sonnet_model=None,
                haiku_model=None,
            )
            mock_ensure.assert_called_once()
            mock_save_settings.assert_called_once()
            mock_save_config.assert_called_once()
            assert mock_config.auth_method == "custom"

        # Verify active_profile_id is set
        store = load_profiles()
        assert store.active_profile_id == "test1234"

    def test_activate_nonexistent_raises(self, tmp_profiles_path):
        """Raises ValueError for nonexistent profile."""
        with pytest.raises(ValueError, match="Profile not found"):
            activate_profile("nonexistent")

    def test_activate_custom_type_passes_url(self, tmp_profiles_path):
        """Custom endpoint type passes URL to build function."""
        profile = APIProfile(
            id="custom01",
            name="Custom",
            endpoint_type="custom",
            api_key="sk-custom",
            url="https://api.example.com/anthropic",
        )
        add_profile(profile)

        with (
            patch("frago.init.configurator.build_claude_env_config") as mock_build,
            patch("frago.init.configurator.save_claude_settings"),
            patch("frago.init.configurator.ensure_claude_json_for_custom_auth"),
            patch("frago.init.config_manager.load_config") as mock_load_config,
            patch("frago.init.config_manager.save_config"),
        ):
            mock_load_config.return_value = MagicMock()
            mock_build.return_value = {}

            activate_profile("custom01")

            mock_build.assert_called_once_with(
                endpoint_type="custom",
                api_key="sk-custom",
                custom_url="https://api.example.com/anthropic",
                default_model=None,
                sonnet_model=None,
                haiku_model=None,
            )


class TestDeactivateProfile:
    """Test deactivate_profile."""

    def test_deactivate_clears_settings(self, tmp_profiles_path, sample_profile):
        """Deactivate clears API config and sets official auth."""
        add_profile(sample_profile)
        store = load_profiles()
        store.active_profile_id = "test1234"
        save_profiles(store)

        with (
            patch("frago.init.configurator.clear_api_env_from_settings") as mock_clear,
            patch("frago.init.config_manager.load_config") as mock_load_config,
            patch("frago.init.config_manager.save_config") as mock_save_config,
        ):
            mock_config = MagicMock()
            mock_load_config.return_value = mock_config

            deactivate_profile()

            mock_clear.assert_called_once()
            mock_save_config.assert_called_once()
            assert mock_config.auth_method == "official"

        store = load_profiles()
        assert store.active_profile_id is None


class TestCreateProfileFromCurrent:
    """Test create_profile_from_current."""

    def test_creates_from_settings(self, tmp_profiles_path):
        """Creates profile from current ~/.claude/settings.json."""
        mock_settings = {
            "env": {
                "ANTHROPIC_API_KEY": "sk-from-settings",
                "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
                "ANTHROPIC_MODEL": "deepseek-reason",
                "ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-reason",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-chat",
            }
        }

        with patch("frago.init.configurator.load_claude_settings", return_value=mock_settings):
            profile = create_profile_from_current("My Config")

        assert profile is not None
        assert profile.name == "My Config"
        assert profile.endpoint_type == "deepseek"
        assert profile.api_key == "sk-from-settings"

        # Should be marked as active
        store = load_profiles()
        assert store.active_profile_id == profile.id

    def test_returns_none_when_no_config(self, tmp_profiles_path):
        """Returns None when no custom API config exists."""
        with patch("frago.init.configurator.load_claude_settings", return_value={}):
            profile = create_profile_from_current("Empty")
        assert profile is None
