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
    ActivateProfileRequest,
    UpdateProfileRequest,
    activate_profile_endpoint,
    get_activation_targets,
    get_endpoint_presets,
    get_profiles,
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


class TestActivationTargets:
    """激活时选目标这件事，WebUI 是唯一的入口，所以这几个端点就是全部的可达面。"""

    @pytest.mark.asyncio
    async def test_targets_endpoint_lists_every_agent_with_its_standing(self):
        response = await get_activation_targets()

        by_type = {t.agent_type: t for t in response.targets}
        assert set(by_type) == {"claude", "opencode", "codex"}
        # 接不了的那个也要出现，并带着能读懂的原因。
        assert by_type["codex"].supported is False
        assert by_type["codex"].selectable is False
        assert by_type["codex"].unsupported_reason
        assert response.default_targets == ["claude"]

    @pytest.mark.asyncio
    async def test_activating_without_a_body_keeps_the_old_behavior(
        self, saved_profile
    ):
        """旧客户端不带 body 发过来，仍然只写 Claude Code。"""
        with (
            patch("frago.init.configurator.build_claude_env_config", return_value={}),
            patch("frago.init.configurator.save_claude_settings") as mock_save,
            patch("frago.init.configurator.ensure_claude_json_for_custom_auth"),
            patch("frago.init.config_manager.load_config", return_value=MagicMock()),
            patch("frago.init.config_manager.save_config"),
            patch("frago.server.routes.settings.StateManager") as mock_state,
        ):
            mock_state.get_instance.return_value.refresh_config = _async_noop()
            result = await activate_profile_endpoint(saved_profile)

        assert result.status == "ok"
        mock_save.assert_called_once()
        assert load_profiles().active_targets == ["claude"]

    @pytest.mark.asyncio
    async def test_activating_on_a_named_target_records_it(self, saved_profile):
        applied = MagicMock()
        with (
            patch("frago.init.profile_targets._driver") as mock_driver,
            patch(
                "frago.init.profile_targets._installed_path",
                side_effect=lambda agent: f"/bin/{agent}",
            ),
            patch("frago.init.config_manager.load_config", return_value=MagicMock()),
            patch("frago.init.config_manager.save_config"),
            patch("frago.server.routes.settings.StateManager") as mock_state,
        ):
            mock_driver.return_value.profile_apply = applied
            mock_state.get_instance.return_value.refresh_config = _async_noop()
            result = await activate_profile_endpoint(
                saved_profile, ActivateProfileRequest(targets=["opencode"])
            )

        assert result.status == "ok"
        assert "opencode" in result.message
        assert load_profiles().active_targets == ["opencode"]

    @pytest.mark.asyncio
    async def test_a_refused_target_is_an_error_not_a_404(self, saved_profile):
        """目标不可用是"这台机器上不行"，不是"资源不存在"——404 会让 UI 报错报成
        profile 丢了。"""
        result = await activate_profile_endpoint(
            saved_profile, ActivateProfileRequest(targets=["codex"])
        )
        assert result.status == "error"
        assert "codex" in result.error.lower() or "Codex" in result.error

    @pytest.mark.asyncio
    async def test_the_list_says_where_the_active_profile_is_active(
        self, saved_profile
    ):
        store = load_profiles()
        store.active_profile_id = saved_profile
        store.active_targets = ["claude", "opencode"]
        from frago.init.profile_manager import save_profiles

        save_profiles(store)

        response = await get_profiles()
        assert response.active_targets == ["claude", "opencode"]


def _async_noop():
    """一个可 await 的空动作，替掉激活后广播配置那一步。"""

    async def _noop(*args, **kwargs):
        return None

    return _noop
