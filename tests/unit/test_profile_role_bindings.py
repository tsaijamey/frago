"""Tests for role bindings — which connection main and worker each run on.

The two roles differ in what binding *does*, and that difference is what these
tests pin: binding main writes the connection into the agent CLIs' own config
(so hand-started sessions get it too), binding worker records a choice that is
read when `frago agent` opens a session and written nowhere.
"""

from unittest.mock import patch

import pytest

from frago.init.profile_manager import (
    KIND_OFFICIAL,
    KIND_VENDOR_CLI,
    MAIN_ROLE,
    OFFICIAL_ID,
    WORKER_ROLE,
    APIProfile,
    ProfileStore,
    add_profile,
    bind_role,
    delete_profile,
    find_connection,
    list_connections,
    load_profiles,
    official_connection,
    role_binding_id,
    role_connection,
    save_profiles,
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
def vendor_profile():
    return APIProfile(
        id="vc000001",
        name="Antigravity own account",
        kind=KIND_VENDOR_CLI,
        endpoint_type=KIND_VENDOR_CLI,
        agent_type="agy",
        default_model="gemini-3.8-flash",
    )


class TestOfficialConnection:
    """The subscription is built, not stored — it has to survive an empty store."""

    def test_listed_first_even_with_no_profiles(self, tmp_profiles_path):
        connections = list_connections()
        assert [c.id for c in connections] == [OFFICIAL_ID]
        assert connections[0].kind == KIND_OFFICIAL

    def test_cannot_be_saved_as_a_profile(self, tmp_profiles_path):
        with pytest.raises(ValueError, match="built in"):
            add_profile(APIProfile(name="Fake official", kind=KIND_OFFICIAL, endpoint_type="official"))

    def test_both_roles_start_on_it(self, tmp_profiles_path):
        assert role_connection(MAIN_ROLE).kind == KIND_OFFICIAL
        assert role_connection(WORKER_ROLE).kind == KIND_OFFICIAL
        assert role_binding_id(MAIN_ROLE) is None
        assert role_binding_id(WORKER_ROLE) is None


class TestWorkerBinding:
    """Binding worker records a choice and writes nothing anywhere."""

    def test_binds_endpoint_profile(self, tmp_profiles_path, endpoint_profile):
        add_profile(endpoint_profile)
        bound = bind_role(WORKER_ROLE, endpoint_profile.id)

        assert bound.id == endpoint_profile.id
        assert load_profiles().worker_profile_id == endpoint_profile.id
        assert role_connection(WORKER_ROLE).id == endpoint_profile.id

    def test_leaves_main_alone(self, tmp_profiles_path, endpoint_profile):
        """The whole point of two roles: moving one does not move the other."""
        add_profile(endpoint_profile)
        with patch("frago.init.profile_manager.activate_profile") as activate:
            bind_role(WORKER_ROLE, endpoint_profile.id)

        activate.assert_not_called()
        assert load_profiles().active_profile_id is None
        assert role_connection(MAIN_ROLE).kind == KIND_OFFICIAL

    def test_accepts_a_vendor_cli(self, tmp_profiles_path, vendor_profile):
        add_profile(vendor_profile)
        bound = bind_role(WORKER_ROLE, vendor_profile.id)

        assert bound.agent_type == "agy"
        assert bound.default_model == "gemini-3.8-flash"
        assert role_connection(WORKER_ROLE).id == vendor_profile.id

    def test_binding_official_clears_it(self, tmp_profiles_path, endpoint_profile):
        add_profile(endpoint_profile)
        bind_role(WORKER_ROLE, endpoint_profile.id)
        bind_role(WORKER_ROLE, OFFICIAL_ID)

        assert load_profiles().worker_profile_id is None
        assert role_connection(WORKER_ROLE).kind == KIND_OFFICIAL


class TestMainBinding:
    """Binding main is the activation: it writes into the CLIs' own config."""

    def test_binds_through_activate(self, tmp_profiles_path, endpoint_profile):
        add_profile(endpoint_profile)
        with patch("frago.init.profile_manager.activate_profile") as activate:
            bind_role(MAIN_ROLE, endpoint_profile.id, ["claude"])

        activate.assert_called_once_with(endpoint_profile.id, ["claude"])

    def test_binding_official_deactivates(self, tmp_profiles_path, endpoint_profile):
        add_profile(endpoint_profile)
        with patch("frago.init.profile_manager.deactivate_profile") as deactivate:
            bind_role(MAIN_ROLE, OFFICIAL_ID)

        deactivate.assert_called_once_with()

    def test_refuses_a_vendor_cli(self, tmp_profiles_path, vendor_profile):
        """There is nothing frago could write into another CLI's config for it."""
        add_profile(vendor_profile)
        with pytest.raises(ValueError, match="own account"):
            bind_role(MAIN_ROLE, vendor_profile.id)

        assert load_profiles().active_profile_id is None

    def test_activating_a_vendor_cli_directly_is_refused_too(
        self, tmp_profiles_path, vendor_profile
    ):
        """The activate path is reachable without going through bind_role."""
        from frago.init.profile_manager import activate_profile

        add_profile(vendor_profile)
        with pytest.raises(ValueError, match="own account"):
            activate_profile(vendor_profile.id, ["claude"])

    def test_reads_back_from_the_activation_record(self, tmp_profiles_path, endpoint_profile):
        """Main's binding has one home — there is no second field to drift."""
        add_profile(endpoint_profile)
        store = load_profiles()
        store.active_profile_id = endpoint_profile.id
        store.active_targets = ["claude"]
        save_profiles(store)

        assert role_binding_id(MAIN_ROLE) == endpoint_profile.id
        assert role_connection(MAIN_ROLE).name == "DeepSeek"


class TestDanglingBindings:
    """A binding that outlives its profile must read as unbound, not as broken."""

    def test_delete_clears_worker_binding(self, tmp_profiles_path, endpoint_profile):
        add_profile(endpoint_profile)
        bind_role(WORKER_ROLE, endpoint_profile.id)
        delete_profile(endpoint_profile.id)

        assert load_profiles().worker_profile_id is None
        assert role_connection(WORKER_ROLE).kind == KIND_OFFICIAL

    def test_stale_id_resolves_to_the_subscription(self, tmp_profiles_path):
        save_profiles(ProfileStore(worker_profile_id="gone1234"))

        assert role_binding_id(WORKER_ROLE) is None
        assert role_connection(WORKER_ROLE).kind == KIND_OFFICIAL

    def test_unknown_role_is_rejected(self, tmp_profiles_path):
        with pytest.raises(ValueError, match="Unknown role"):
            role_connection("supervisor")


class TestValidation:
    """Vendor CLI profiles are held to naming a core this build can launch."""

    def test_vendor_cli_needs_a_core(self, tmp_profiles_path):
        with pytest.raises(ValueError, match="needs an agent core"):
            add_profile(
                APIProfile(name="No core", kind=KIND_VENDOR_CLI, endpoint_type=KIND_VENDOR_CLI)
            )

    def test_vendor_cli_rejects_unknown_core(self, tmp_profiles_path):
        with pytest.raises(ValueError, match="Unknown agent core"):
            add_profile(
                APIProfile(
                    name="Bad core",
                    kind=KIND_VENDOR_CLI,
                    endpoint_type=KIND_VENDOR_CLI,
                    agent_type="nosuchcli",
                )
            )

    def test_legacy_profiles_load_as_endpoint_kind(self, tmp_profiles_path):
        """Every profile saved before kinds existed is an endpoint profile."""
        tmp_profiles_path.write_text(
            '{"schema_version": "1.0", "profiles": [{"id": "old12345", "name": "Old", '
            '"endpoint_type": "deepseek", "api_key": "sk-old"}]}',
            encoding="utf-8",
        )
        profile = find_connection("old12345")

        assert profile is not None
        assert profile.kind == "endpoint"
        assert profile.agent_type is None

    def test_official_connection_carries_no_credential(self, tmp_profiles_path):
        official = official_connection()

        assert official.api_key == ""
        assert official.url is None
