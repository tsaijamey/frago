"""Profile settings endpoints — the only door the WebUI has to API profiles.

The CLI is read-only here by design ("增删改激活走 WebUI 设置"), so whatever
these endpoints refuse to do, a user simply cannot do.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from frago.init.configurator import PRESET_ENDPOINTS
from frago.init.profile_manager import APIProfile, add_profile, load_profiles
from frago.server.routes.settings import (
    UpdateProfileRequest,
    get_endpoint_presets,
    update_profile_endpoint,
)


@pytest.fixture
def tmp_profiles_path(tmp_path):
    profiles_path = tmp_path / "profiles.json"
    with patch("frago.init.profile_manager.PROFILES_PATH", profiles_path):
        yield profiles_path


@pytest.fixture
def saved_profile(tmp_profiles_path):
    add_profile(
        APIProfile(
            id="prof0001",
            name="DeepSeek",
            endpoint_type="deepseek",
            api_key="sk-original-key",
            default_model="deepseek-v4-flash",
        )
    )
    return "prof0001"


class TestEndpointPresets:
    """The UI used to carry its own copy of this table and it drifted —
    the Tencent endpoints were unreachable and the model names were stale."""

    @pytest.mark.asyncio
    async def test_every_backend_preset_is_offered(self):
        response = await get_endpoint_presets()
        assert {p.id for p in response.presets} == set(PRESET_ENDPOINTS)

    @pytest.mark.asyncio
    async def test_each_preset_carries_the_models_it_will_actually_use(self):
        response = await get_endpoint_presets()
        by_id = {p.id: p for p in response.presets}
        for key, preset in PRESET_ENDPOINTS.items():
            assert by_id[key].default_model == preset["ANTHROPIC_MODEL"]
            assert by_id[key].base_url == preset["ANTHROPIC_BASE_URL"]


class TestUpdatingAProfile:
    @pytest.mark.asyncio
    async def test_an_untouched_field_keeps_its_value(self, saved_profile):
        result = await update_profile_endpoint(
            saved_profile, UpdateProfileRequest(name="Renamed")
        )
        assert result.status == "ok"
        profile = load_profiles().profiles[0]
        assert profile.name == "Renamed"
        assert profile.default_model == "deepseek-v4-flash"

    @pytest.mark.asyncio
    async def test_an_emptied_field_is_actually_cleared(self, saved_profile):
        """The form used to drop blanks on the way out, so a deleted override
        was saved as "unchanged" and reappeared on the next open."""
        result = await update_profile_endpoint(
            saved_profile, UpdateProfileRequest(default_model="")
        )
        assert result.status == "ok"
        assert load_profiles().profiles[0].default_model is None

    @pytest.mark.asyncio
    async def test_an_empty_api_key_still_means_keep_the_old_one(self, saved_profile):
        """The key field is never prefilled, so blank has to mean unchanged."""
        await update_profile_endpoint(saved_profile, UpdateProfileRequest(api_key=""))
        assert load_profiles().profiles[0].api_key == "sk-original-key"

    @pytest.mark.asyncio
    async def test_an_unusable_edit_is_reported_not_saved(self, saved_profile):
        result = await update_profile_endpoint(
            saved_profile, UpdateProfileRequest(endpoint_type="custom", url="")
        )
        assert result.status == "error"
        assert "URL" in (result.error or "")
        assert load_profiles().profiles[0].endpoint_type == "deepseek"

    @pytest.mark.asyncio
    async def test_a_missing_profile_is_a_404(self, tmp_profiles_path):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as excinfo:
            await update_profile_endpoint("nope", UpdateProfileRequest(name="X"))
        assert excinfo.value.status_code == 404

    @pytest.mark.asyncio
    async def test_editing_the_active_profile_reaches_claude_settings(
        self, saved_profile
    ):
        store = load_profiles()
        store.active_profile_id = saved_profile
        from frago.init.profile_manager import save_profiles

        save_profiles(store)

        with (
            patch(
                "frago.init.configurator.build_claude_env_config", return_value={}
            ) as mock_build,
            patch("frago.init.configurator.save_claude_settings") as mock_save,
            patch("frago.init.configurator.ensure_claude_json_for_custom_auth"),
            patch("frago.init.config_manager.load_config", return_value=MagicMock()),
            patch("frago.init.config_manager.save_config"),
        ):
            result = await update_profile_endpoint(
                saved_profile,
                UpdateProfileRequest(default_model="deepseek-v4-flash-vision-exp"),
            )

        assert result.status == "ok"
        mock_save.assert_called_once()
        assert mock_build.call_args.kwargs["default_model"] == (
            "deepseek-v4-flash-vision-exp"
        )
