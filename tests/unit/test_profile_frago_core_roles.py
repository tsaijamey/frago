"""Tests for the three roles frago-core serves — CoreAgent, the light agent, the observer.

frago-core can call a connection that carries its own key, and nothing else. These
tests pin which connection can go to which role, what "unbound" means for each, and
that the fields land where frago-core reads them.
"""

import json
from unittest.mock import patch

import pytest

from frago.init.profile_manager import (
    COREAGENT_ROLE,
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
def endpoint_profile():
    return APIProfile(
        id="ep000001",
        name="DeepSeek",
        endpoint_type="deepseek",
        api_key="sk-test-key-1234567890",
        default_model="deepseek-v4-flash",
    )


@pytest.fixture
def second_endpoint_profile():
    return APIProfile(
        id="ep000002",
        name="Volcengine plan",
        endpoint_type="custom",
        url="https://ark.cn-beijing.volces.com/api/plan",
        api_key="ark-test-key-1234567890",
        default_model="deepseek-v4.1-flash",
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


def _retired_workbuddy_row(profile_id: str) -> APIProfile:
    """A row of the shape saved before 2026-10-09, when borrowing the WorkBuddy
    login still worked. Written straight into the store, since adding one is
    refused now."""
    return APIProfile(
        id=profile_id,
        name="WorkBuddy legacy",
        kind=KIND_WORKBUDDY,
        endpoint_type=KIND_WORKBUDDY,
        default_model="deepseek-v4-flash",
    )


class TestWorkBuddyConnectionIsRetired:
    """借 WorkBuddy 登录这条连接 2026-10-09 下线：客户端把登录文件加密了，
    钥匙留在客户端自己手里，frago 读不到凭据。老记录还读得出来，只为让页面标出它，
    不再有任何角色能绑上去。"""

    def test_a_new_one_is_refused(self, tmp_profiles_path):
        with pytest.raises(ValueError, match="已下线"):
            add_profile(_retired_workbuddy_row("wb000001"))

    def test_a_saved_one_can_no_longer_be_bound(self, tmp_profiles_path):
        store = load_profiles()
        store.profiles.append(_retired_workbuddy_row("wb000002"))
        save_profiles(store)

        for role in ROLES_UNDER_TEST:
            with pytest.raises(ValueError, match="已下线"):
                bind_role(role, "wb000002")

    def test_it_cannot_be_written_into_a_cli(self, tmp_profiles_path):
        store = load_profiles()
        store.profiles.append(_retired_workbuddy_row("wb000003"))
        save_profiles(store)

        with pytest.raises(ValueError, match="已下线"):
            activate_profile("wb000003", ["claude"])
        assert load_profiles().active_profile_id is None


ROLES_UNDER_TEST = (MAIN_ROLE, WORKER_ROLE, LIGHTAGENT_ROLE, OBSERVER_ROLE, COREAGENT_ROLE)


class TestWhichConnectionGoesWhere:
    def test_frago_core_roles_take_a_key(self, tmp_profiles_path, endpoint_profile, second_endpoint_profile):
        add_profile(endpoint_profile)
        add_profile(second_endpoint_profile)
        bind_role(LIGHTAGENT_ROLE, endpoint_profile.id)
        bind_role(OBSERVER_ROLE, second_endpoint_profile.id)

        store = load_profiles()
        assert store.lightagent_profile_id == endpoint_profile.id
        assert store.observer_profile_id == second_endpoint_profile.id

    def test_frago_core_roles_refuse_a_vendor_cli(self, tmp_profiles_path, vendor_profile):
        add_profile(vendor_profile)
        for role in (LIGHTAGENT_ROLE, OBSERVER_ROLE):
            with pytest.raises(ValueError, match="frago-core cannot call"):
                bind_role(role, vendor_profile.id)

    def test_cli_roles_refuse_a_vendor_cli(self, tmp_profiles_path, vendor_profile):
        add_profile(vendor_profile)
        with pytest.raises(ValueError, match="own account"):
            bind_role(MAIN_ROLE, vendor_profile.id)

    def test_the_two_roles_move_independently(
        self, tmp_profiles_path, endpoint_profile, second_endpoint_profile
    ):
        add_profile(endpoint_profile)
        add_profile(second_endpoint_profile)
        with patch("frago.init.profile_manager.activate_profile") as activate:
            bind_role(OBSERVER_ROLE, second_endpoint_profile.id)
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
        self, tmp_profiles_path, second_endpoint_profile
    ):
        add_profile(second_endpoint_profile)
        bind_role(LIGHTAGENT_ROLE, second_endpoint_profile.id)
        bind_role(OBSERVER_ROLE, second_endpoint_profile.id)
        delete_profile(second_endpoint_profile.id)

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
        self, tmp_profiles_path, endpoint_profile, second_endpoint_profile
    ):
        """An undeclared key would be dropped by the next save the settings page makes."""
        add_profile(endpoint_profile)
        add_profile(second_endpoint_profile)
        bind_role(LIGHTAGENT_ROLE, endpoint_profile.id)
        bind_role(OBSERVER_ROLE, second_endpoint_profile.id)
        update_profile(endpoint_profile.id, {"name": "DeepSeek renamed"})

        raw = json.loads(tmp_profiles_path.read_text(encoding="utf-8"))
        assert raw["lightagent_profile_id"] == endpoint_profile.id
        assert raw["observer_profile_id"] == second_endpoint_profile.id


class TestCoreAgent:
    """CoreAgent 是后加的第三个 frago-core 角色。加它不能让前两个角色的绑定有任何变化。"""

    def test_binding_it_leaves_the_other_two_where_they_were(
        self, tmp_profiles_path, endpoint_profile, second_endpoint_profile
    ):
        add_profile(endpoint_profile)
        add_profile(second_endpoint_profile)
        bind_role(LIGHTAGENT_ROLE, endpoint_profile.id)
        bind_role(OBSERVER_ROLE, second_endpoint_profile.id)
        bind_role(COREAGENT_ROLE, second_endpoint_profile.id)

        raw = json.loads(tmp_profiles_path.read_text(encoding="utf-8"))
        assert raw["coreagent_profile_id"] == second_endpoint_profile.id
        assert raw["lightagent_profile_id"] == endpoint_profile.id
        assert raw["observer_profile_id"] == second_endpoint_profile.id

    def test_unbound_it_falls_back_like_the_light_agent(self, tmp_profiles_path, endpoint_profile):
        add_profile(endpoint_profile)
        assert role_binding_id(COREAGENT_ROLE) is None
        assert role_view(COREAGENT_ROLE).id == endpoint_profile.id

    def test_it_refuses_a_vendor_cli(self, tmp_profiles_path, vendor_profile):
        add_profile(vendor_profile)
        with pytest.raises(ValueError, match="frago-core cannot call"):
            bind_role(COREAGENT_ROLE, vendor_profile.id)

    def test_deleting_the_bound_row_unbinds_it(self, tmp_profiles_path, second_endpoint_profile):
        add_profile(second_endpoint_profile)
        bind_role(COREAGENT_ROLE, second_endpoint_profile.id)
        delete_profile(second_endpoint_profile.id)
        assert load_profiles().coreagent_profile_id is None

    def test_a_store_written_before_it_existed_still_loads(self, tmp_profiles_path):
        tmp_profiles_path.write_text(
            json.dumps({"lightagent_profile_id": None, "observer_profile_id": None, "profiles": []}),
            encoding="utf-8",
        )
        assert load_profiles().coreagent_profile_id is None
