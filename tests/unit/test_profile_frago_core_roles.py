"""Tests for the two roles frago-core serves — the light agent and the session observer.

frago-core can call a connection that carries its own key, or one that borrows the
WorkBuddy client's login, and nothing else. These tests pin which connection can go
to which role, what "unbound" means for each, and that the fields land where
frago-core reads them.
"""

import json
from unittest.mock import patch

import pytest

from frago.init.profile_manager import (
    KIND_VENDOR_CLI,
    KIND_WORKBUDDY,
    LIGHTAGENT_ROLE,
    MAIN_ROLE,
    OBSERVER_ROLE,
    OFFICIAL_ID,
    WORKER_ROLE,
    APIProfile,
    activate_profile,
    add_profile,
    bind_role,
    delete_profile,
    load_profiles,
    role_binding_id,
    role_connection,
    role_view,
    save_profiles,
    update_profile,
)


@pytest.fixture
def tmp_profiles_path(tmp_path):
    profiles_path = tmp_path / "profiles.json"
    with patch("frago.init.profile_manager.PROFILES_PATH", profiles_path):
        yield profiles_path


@pytest.fixture
def probed(tmp_path):
    """A probe result: deepseek-v4-flash answered, hy3 thought itself out of budget."""
    path = tmp_path / "workbuddy-models.json"
    path.write_text(
        json.dumps(
            {
                "probed_at": "2026-09-11T12:00:00.000000",
                "gateway": "https://copilot.tencent.com",
                "models": [
                    {"id": "deepseek-v4-flash", "ok": True, "wire": "openai", "first_ms": 793},
                    {"id": "hy3", "ok": False, "thinks": True, "error": "思考把预算吃光了"},
                ],
            }
        ),
        encoding="utf-8",
    )
    with patch("frago.init.profile_manager.WORKBUDDY_MODELS_PATH", path):
        yield path


@pytest.fixture
def endpoint_profile():
    return APIProfile(
        id="ep000001",
        name="DeepSeek",
        endpoint_type="deepseek",
        api_key="sk-test-key-1234567890",
        default_model="deepseek-v4-flash",
    )


@pytest.fixture
def workbuddy_profile():
    return APIProfile(
        id="wb000001",
        name="WorkBuddy flash",
        kind=KIND_WORKBUDDY,
        endpoint_type=KIND_WORKBUDDY,
        default_model="deepseek-v4-flash",
    )


@pytest.fixture
def vendor_profile():
    return APIProfile(
        id="vc000001",
        name="WorkBuddy hy4",
        kind=KIND_VENDOR_CLI,
        endpoint_type=KIND_VENDOR_CLI,
        agent_type="codebuddy",
        default_model="hy4-preview",
    )


class TestWorkBuddyConnection:
    """No key is stored, and the model can only be one the last probe found usable."""

    def test_saved_without_a_key(self, tmp_profiles_path, probed, workbuddy_profile):
        add_profile(workbuddy_profile)
        saved = load_profiles().profiles[0]
        assert saved.kind == KIND_WORKBUDDY
        assert saved.api_key == ""

    def test_refused_before_any_probe(self, tmp_profiles_path, tmp_path, workbuddy_profile):
        with (
            patch("frago.init.profile_manager.WORKBUDDY_MODELS_PATH", tmp_path / "none.json"),
            pytest.raises(ValueError, match="probe-workbuddy"),
        ):
            add_profile(workbuddy_profile)

    def test_a_model_that_failed_the_probe_is_refused(
        self, tmp_profiles_path, probed, workbuddy_profile
    ):
        workbuddy_profile.default_model = "hy3"
        with pytest.raises(ValueError, match="hy3"):
            add_profile(workbuddy_profile)

    def test_the_cheap_tier_is_held_to_the_probe_too(
        self, tmp_profiles_path, probed, workbuddy_profile
    ):
        add_profile(workbuddy_profile)
        with pytest.raises(ValueError, match="hy3"):
            update_profile(workbuddy_profile.id, {"haiku_model": "hy3"})

    def test_endpoint_type_must_say_workbuddy(self, tmp_profiles_path, probed, workbuddy_profile):
        workbuddy_profile.endpoint_type = "custom"
        with pytest.raises(ValueError, match="endpoint type"):
            add_profile(workbuddy_profile)


class TestWhichConnectionGoesWhere:
    def test_frago_core_roles_take_a_key_or_the_workbuddy_login(
        self, tmp_profiles_path, probed, endpoint_profile, workbuddy_profile
    ):
        add_profile(endpoint_profile)
        add_profile(workbuddy_profile)
        bind_role(LIGHTAGENT_ROLE, endpoint_profile.id)
        bind_role(OBSERVER_ROLE, workbuddy_profile.id)

        store = load_profiles()
        assert store.lightagent_profile_id == endpoint_profile.id
        assert store.observer_profile_id == workbuddy_profile.id

    def test_frago_core_roles_refuse_a_vendor_cli(self, tmp_profiles_path, vendor_profile):
        add_profile(vendor_profile)
        for role in (LIGHTAGENT_ROLE, OBSERVER_ROLE):
            with pytest.raises(ValueError, match="frago-core cannot call"):
                bind_role(role, vendor_profile.id)

    def test_cli_roles_refuse_the_workbuddy_login(
        self, tmp_profiles_path, probed, workbuddy_profile
    ):
        """There is no agent CLI configuration it could be written into."""
        add_profile(workbuddy_profile)
        for role in (MAIN_ROLE, WORKER_ROLE):
            with pytest.raises(ValueError, match="light agent or the session observer"):
                bind_role(role, workbuddy_profile.id)
        with pytest.raises(ValueError, match="light agent or the session observer"):
            activate_profile(workbuddy_profile.id, ["claude"])
        assert load_profiles().active_profile_id is None

    def test_the_two_roles_move_independently(
        self, tmp_profiles_path, probed, endpoint_profile, workbuddy_profile
    ):
        add_profile(endpoint_profile)
        add_profile(workbuddy_profile)
        with patch("frago.init.profile_manager.activate_profile") as activate:
            bind_role(OBSERVER_ROLE, workbuddy_profile.id)
        activate.assert_not_called()
        assert role_binding_id(LIGHTAGENT_ROLE) is None
        assert role_binding_id(MAIN_ROLE) is None


class TestUnbound:
    def test_empty_id_or_subscription_unbinds(self, tmp_profiles_path, endpoint_profile):
        add_profile(endpoint_profile)
        bind_role(OBSERVER_ROLE, endpoint_profile.id)
        assert bind_role(OBSERVER_ROLE, "") is None
        assert load_profiles().observer_profile_id is None

        bind_role(LIGHTAGENT_ROLE, endpoint_profile.id)
        assert bind_role(LIGHTAGENT_ROLE, OFFICIAL_ID) is None
        assert load_profiles().lightagent_profile_id is None

    def test_an_unbound_light_agent_shows_what_frago_core_will_try(
        self, tmp_profiles_path, endpoint_profile
    ):
        """The same fallback frago-core uses: active, else the first saved profile."""
        add_profile(endpoint_profile)
        assert role_view(LIGHTAGENT_ROLE).id == endpoint_profile.id

    def test_an_unbound_observer_runs_on_nothing(self, tmp_profiles_path, endpoint_profile):
        add_profile(endpoint_profile)
        assert role_view(OBSERVER_ROLE) is None

    def test_the_frago_core_roles_have_no_subscription_to_fall_back_to(self, tmp_profiles_path):
        with pytest.raises(ValueError, match="role_view"):
            role_connection(OBSERVER_ROLE)

    def test_deleting_the_bound_row_unbinds_both(
        self, tmp_profiles_path, probed, workbuddy_profile
    ):
        add_profile(workbuddy_profile)
        bind_role(LIGHTAGENT_ROLE, workbuddy_profile.id)
        bind_role(OBSERVER_ROLE, workbuddy_profile.id)
        delete_profile(workbuddy_profile.id)

        store = load_profiles()
        assert store.lightagent_profile_id is None
        assert store.observer_profile_id is None

    def test_a_stale_id_reads_as_unbound(self, tmp_profiles_path):
        from frago.init.profile_manager import ProfileStore

        save_profiles(ProfileStore(observer_profile_id="gone1234", lightagent_profile_id="official"))
        assert role_binding_id(OBSERVER_ROLE) is None
        assert role_binding_id(LIGHTAGENT_ROLE) is None


class TestWhereFragoCoreReadsIt:
    def test_both_fields_survive_a_save_under_the_names_frago_core_reads(
        self, tmp_profiles_path, probed, endpoint_profile, workbuddy_profile
    ):
        """An undeclared key would be dropped by the next save the settings page makes."""
        add_profile(endpoint_profile)
        add_profile(workbuddy_profile)
        bind_role(LIGHTAGENT_ROLE, endpoint_profile.id)
        bind_role(OBSERVER_ROLE, workbuddy_profile.id)
        update_profile(endpoint_profile.id, {"name": "DeepSeek renamed"})

        raw = json.loads(tmp_profiles_path.read_text(encoding="utf-8"))
        assert raw["lightagent_profile_id"] == endpoint_profile.id
        assert raw["observer_profile_id"] == workbuddy_profile.id
        row = next(p for p in raw["profiles"] if p["id"] == workbuddy_profile.id)
        assert row["endpoint_type"] == "workbuddy"
        assert row["api_key"] == ""
