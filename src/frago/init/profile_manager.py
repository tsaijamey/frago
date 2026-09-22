"""Connection profile management.

Provides CRUD operations for ~/.frago/profiles.json.

A profile is one usable connection. There are three shapes of connection and
they are not variations of one another:

- ``endpoint`` — an Anthropic-protocol endpoint plus a key. This is what a
  profile used to be, and every profile saved before kinds existed is one.
- ``official`` — the agent CLI's own subscription login. It has no endpoint and
  no key: it is what a CLI runs on when frago has written nothing into it. It
  is built on demand rather than stored, so that it cannot be deleted and the
  role pickers always have something to fall back to.
- ``vendor_cli`` — a vendor's own CLI running on its own account (CodeBuddy /
  WorkBuddy). Its credential is that CLI's login, not a key frago holds, so
  there is nothing to write into anyone else's config; what a profile of this
  kind carries is which core to run and which model to ask it for.
- ``workbuddy`` — frago-core calling the WorkBuddy model gateway directly on the
  WorkBuddy client's own login. No key is stored: the client rotates its token,
  so a copy would go stale within days, and refreshing it from here would fight
  the client over the same file. frago-core reads the login each call. What the
  profile carries is the model, picked from what the last probe found usable.

Two roles consume connections, and they consume them differently:

- **main** — the agent the person talks to. Binding here means writing the
  connection into the agent CLI's own configuration, so sessions started by
  hand pick it up too. That is what ``activate_profile`` has always done, and
  ``active_profile_id`` remains the single record of it — there is no second
  copy of "what main is on" to drift out of step.
- **worker** — the sessions ``frago agent`` starts. Binding here writes nothing
  anywhere; it is read at launch and applied to that one session. Recorded in
  ``worker_profile_id``.

Two more roles are served by frago-core rather than by an agent CLI, and frago-core
can only call a connection that carries its own key or borrows the WorkBuddy login:

- **lightagent** — the hook's review passes. Unbound, it keeps what it always
  used: the active profile, else the first saved one. ``lightagent_profile_id``.
- **observer** — the session page's side panel. Unbound, it does not run.
  ``observer_profile_id``.
"""

import json
import logging
import os
import platform
import uuid
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from frago.init.profile_targets import DEFAULT_TARGETS

logger = logging.getLogger(__name__)

PROFILES_PATH = Path.home() / ".frago" / "profiles.json"

# The three shapes of connection. See the module docstring for what separates
# them; the short version is what supplies the credential — frago holds it
# (endpoint), the CLI's own login holds it (official, vendor_cli).
KIND_ENDPOINT = "endpoint"
KIND_OFFICIAL = "official"
KIND_VENDOR_CLI = "vendor_cli"
KIND_WORKBUDDY = "workbuddy"
PROFILE_KINDS = (KIND_ENDPOINT, KIND_OFFICIAL, KIND_VENDOR_CLI, KIND_WORKBUDDY)

# Written by `frago-core models probe-workbuddy`: which WorkBuddy models answer, and
# on which wire. The catalog WorkBuddy hands out cannot stand in for it — measured,
# 15 of its entries do not answer and 4 models that do are not on it.
WORKBUDDY_MODELS_PATH = Path.home() / ".frago" / "workbuddy-models.json"

# The plain subscription is a fixed id rather than a saved row: nothing about
# it is editable, and a row could be deleted out from under a binding.
OFFICIAL_ID = "official"

MAIN_ROLE = "main"
WORKER_ROLE = "worker"
LIGHTAGENT_ROLE = "lightagent"
OBSERVER_ROLE = "observer"
COREAGENT_ROLE = "coreagent"
#: The roles whose connection an agent CLI runs on.
CLI_ROLES = (MAIN_ROLE, WORKER_ROLE)
#: The roles frago-core asks the model for. It can call a connection with its own
#: key or one that borrows the WorkBuddy login, and nothing else.
FRAGO_CORE_ROLES = (LIGHTAGENT_ROLE, OBSERVER_ROLE, COREAGENT_ROLE)
#: frago-core role → the profiles.json field frago-core reads it from.
_FRAGO_CORE_FIELDS = {
    LIGHTAGENT_ROLE: "lightagent_profile_id",
    OBSERVER_ROLE: "observer_profile_id",
    COREAGENT_ROLE: "coreagent_profile_id",
}
ROLES = CLI_ROLES + FRAGO_CORE_ROLES
_FRAGO_CORE_KINDS = (KIND_ENDPOINT, KIND_WORKBUDDY)


class APIProfile(BaseModel):
    """One usable connection."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    # Which shape of connection this is. Absent from every profile saved before
    # kinds existed, and those are all endpoint profiles — hence the default.
    kind: str = KIND_ENDPOINT
    endpoint_type: str  # deepseek, aliyun, kimi, minimax, custom
    # Empty for the kinds whose credential is not frago's to hold.
    api_key: str = ""
    url: str | None = None
    # vendor_cli only: which agent CLI to run. Meaningless for the other kinds,
    # where the core is whatever the caller is already running.
    agent_type: str | None = None
    default_model: str | None = None
    sonnet_model: str | None = None
    haiku_model: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ProfileStore(BaseModel):
    """Container for all saved profiles."""

    schema_version: str = "1.0"
    # What the main role is bound to: the profile written into the agent CLIs'
    # own configuration. None means nothing was written, which is the plain
    # subscription.
    active_profile_id: str | None = None
    # Which agent CLIs the active profile was written into. Empty when nothing
    # is active. A store written before targets existed has no such key at all,
    # and load_profiles fills it in — see there for why.
    active_targets: list[str] = Field(default_factory=list)
    # What the worker role is bound to. Unlike the main binding this writes
    # nothing anywhere — it is read when `frago agent` opens a session and
    # applied to that session alone, so a worker can run somewhere the person's
    # own agent does not.
    worker_profile_id: str | None = None
    # What the light agent is bound to. None keeps what it always used: the active
    # profile, else the first saved one. frago-core reads this field directly, so
    # it has to be declared here — an undeclared key is dropped on the next save.
    lightagent_profile_id: str | None = None
    # What the session observer is bound to. None means it does not run.
    observer_profile_id: str | None = None
    # What CoreAgent (frago-core's own agent loop) is bound to. None falls back the
    # way the light agent does: the active profile, else the first saved one.
    coreagent_profile_id: str | None = None
    profiles: list[APIProfile] = Field(default_factory=list)


def load_profiles() -> ProfileStore:
    """Load profiles from ~/.frago/profiles.json.

    Returns empty ProfileStore if file doesn't exist or is corrupted.

    A store saved before activation had targets records an active profile with
    no target list. That profile is in force in Claude Code right now, so the
    missing list is read as ``["claude"]`` rather than "nowhere" — otherwise the
    first deactivation after upgrading would decide there was nothing to undo
    and leave the endpoint in settings.json forever.
    """
    if not PROFILES_PATH.exists():
        return ProfileStore()

    try:
        data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
        store = ProfileStore(**data)
        if data.get("active_profile_id") and "active_targets" not in data:
            store.active_targets = list(DEFAULT_TARGETS)
        return store
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Failed to load profiles.json: %s. Using empty store.", e)
        return ProfileStore()


def save_profiles(store: ProfileStore) -> None:
    """Save profiles to ~/.frago/profiles.json with 0o600 permissions on Unix."""
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)

    content = json.dumps(store.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    PROFILES_PATH.write_text(content, encoding="utf-8")

    # Set file permissions on Unix
    if platform.system() != "Windows":
        os.chmod(PROFILES_PATH, 0o600)


def workbuddy_usable_models() -> list[str] | None:
    """The WorkBuddy models that answered on the last probe; None if never probed."""
    try:
        data = json.loads(WORKBUDDY_MODELS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    models = data.get("models") if isinstance(data, dict) else None
    return [
        m["id"]
        for m in models or []
        if isinstance(m, dict) and m.get("ok") and isinstance(m.get("id"), str)
    ]


#: 探过多久就该提醒重探。探一轮是四十多个模型的实调，天数定得比「常看常新」宽。
WORKBUDDY_STALE_DAYS = 14


def workbuddy_login() -> dict[str, str] | None:
    """调 WorkBuddy 网关要用的那几项身份，读不到或不全就是 None。

    每次现读，不缓存——令牌随时被客户端换掉。
    """
    try:
        data = json.loads(workbuddy_login_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    def field(section: str, key: str) -> str:
        block = data.get(section)
        value = block.get(key) if isinstance(block, dict) else None
        return value.strip() if isinstance(value, str) else ""

    uid, token = field("account", "uid"), field("auth", "accessToken")
    if not uid or not token:
        return None
    login = {"uid": uid, "access_token": token}
    for section, key, name in (
        ("account", "enterpriseId", "enterprise_id"),
        ("auth", "domain", "domain"),
    ):
        if value := field(section, key):
            login[name] = value
    return login


def workbuddy_login_state() -> str:
    """本机的 WorkBuddy 客户端此刻能不能鉴权过去。

    ``ok`` / ``logged_out`` / ``no_client``。只看登录文件在不在是不够的：客户端退出
    登录时文件留在原处，里面的令牌字段变空，界面照样显示「已登录」，等第一次真调用才
    失败。frago-core 读这个文件时本来就分得清这两种，这里跟它对齐。
    """
    if not workbuddy_login_path().is_file():
        return "no_client"
    return "ok" if workbuddy_login() else "logged_out"


def workbuddy_login_path() -> Path:
    """Where the WorkBuddy client keeps its login. Mirrors frago-core's lookup."""
    rel = ("CodeBuddyExtension", "Data", "Public", "auth", "workbuddy-desktop.info")
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path.home() / ".local" / "share"
    return base.joinpath(*rel)


def _frago_core_only(name: str) -> str:
    return (
        f"'{name}' borrows the WorkBuddy client's login and is called by frago-core "
        "directly, so there is no agent CLI configuration it could go into. Bind it "
        "to CoreAgent, the light agent or the session observer."
    )


def official_connection() -> APIProfile:
    """The plain subscription: what a CLI runs on when frago has written nothing.

    Built rather than stored. It carries no endpoint and no key, so there would
    be nothing to save; and if it were a row it could be deleted, leaving both
    role pickers with an id that resolves to nothing and no listed way back to
    the subscription the person started from.
    """
    return APIProfile(
        id=OFFICIAL_ID,
        name="Official subscription",
        kind=KIND_OFFICIAL,
        endpoint_type=KIND_OFFICIAL,
    )


def list_connections() -> list[APIProfile]:
    """Every connection a role can be bound to, subscription first.

    The subscription leads because it is the state everything starts in and
    falls back to; a picker that lists only the saved endpoints makes "just use
    my own login" look like something frago cannot do.
    """
    return [official_connection(), *load_profiles().profiles]


def find_connection(profile_id: str | None) -> APIProfile | None:
    """Resolve an id to a connection, including the built-in subscription."""
    if not profile_id:
        return None
    if profile_id == OFFICIAL_ID:
        return official_connection()
    return get_profile(profile_id)


def _validate_profile(
    name: str,
    endpoint_type: str,
    url: str | None,
    kind: str = KIND_ENDPOINT,
    agent_type: str | None = None,
    models: Sequence[str | None] = (),
) -> None:
    """Reject the profile shapes that break something later and quietly.

    A nameless profile is unreachable in any list and, worse, is written to
    disk as a null the store cannot parse back — one blank field would take
    every other saved profile down with it. An unknown endpoint type falls
    through to the "custom" branch when settings are built, and a custom
    endpoint with no URL writes a null base URL; neither fails at save time,
    they fail at the first request with a connection error that says nothing
    about which profile caused it. Catching all three here means the person
    editing the profile hears about it while still looking at the form.

    The endpoint checks only apply to endpoint profiles. A vendor_cli profile
    has no endpoint to check and is instead held to naming a core this build
    actually knows how to launch — an unknown core would otherwise fail much
    later, at session open, as "no driver registered".

    Raises:
        ValueError: With a message meant to be shown to the user as-is.
    """
    from frago.init.configurator import PRESET_ENDPOINTS, validate_endpoint_url

    if not (name or "").strip():
        raise ValueError("Profile name cannot be empty")

    if kind not in PROFILE_KINDS:
        raise ValueError(f"Unknown profile kind '{kind}' (expected one of: {', '.join(PROFILE_KINDS)})")

    if kind == KIND_OFFICIAL:
        # There is exactly one subscription connection and frago builds it. A
        # saved copy would be a second, editable, deletable "official" that
        # means something different from the one the pickers fall back to.
        raise ValueError("The official subscription is built in and cannot be saved as a profile")

    if kind == KIND_VENDOR_CLI:
        from frago.agent_driver.driver import registered_drivers

        known = registered_drivers()
        if not agent_type:
            raise ValueError("A vendor CLI profile needs an agent core (e.g. codebuddy)")
        if agent_type not in known:
            raise ValueError(
                f"Unknown agent core '{agent_type}' (known: {', '.join(sorted(known))})"
            )
        return

    if kind == KIND_WORKBUDDY:
        # The model can only come from what the last probe found usable. Half the
        # names WorkBuddy hands out do not answer; typing one that was never probed
        # puts off finding that out until the first time the connection is used.
        if endpoint_type != KIND_WORKBUDDY:
            raise ValueError("A WorkBuddy connection's endpoint type must be 'workbuddy'")
        usable = workbuddy_usable_models()
        if usable is None:
            raise ValueError(
                "No WorkBuddy models have been probed yet — run `frago-core models probe-workbuddy` first"
            )
        chosen = [m for m in models if m]
        if not chosen:
            raise ValueError("A WorkBuddy connection needs a model")
        unusable = [m for m in chosen if m not in usable]
        if unusable:
            raise ValueError(
                f"Not among the WorkBuddy models that answered on the last probe: {', '.join(unusable)}"
            )
        return

    if endpoint_type != "custom" and endpoint_type not in PRESET_ENDPOINTS:
        known_types = ", ".join([*PRESET_ENDPOINTS, "custom"])
        raise ValueError(f"Unknown endpoint type '{endpoint_type}' (expected one of: {known_types})")

    if endpoint_type == "custom" and not validate_endpoint_url(url or ""):
        raise ValueError("A custom endpoint needs an API URL starting with http:// or https://")


def add_profile(profile: APIProfile) -> ProfileStore:
    """Add a new profile and save.

    Raises:
        ValueError: If the endpoint type / URL combination is unusable.
    """
    _validate_profile(
        profile.name,
        profile.endpoint_type,
        profile.url,
        profile.kind,
        profile.agent_type,
        (profile.default_model, profile.sonnet_model, profile.haiku_model),
    )
    store = load_profiles()
    store.profiles.append(profile)
    save_profiles(store)
    return store


def update_profile(profile_id: str, updates: dict) -> ProfileStore:
    """Update an existing profile's fields.

    If the edited profile is the active one, the change is re-applied to every
    agent CLI it was activated on. Without that, editing the profile that is
    currently in force saved the new model to disk and left the old one
    running: the UI said "saved", and the next session still talked to the
    endpoint the user thought they had just replaced. The stored target list is
    passed back in so that re-applying does not quietly narrow an activation
    that covered several CLIs down to Claude Code alone.

    Args:
        profile_id: Profile ID to update.
        updates: Dict of fields to update. Keys that don't exist are ignored.
                 api_key=None or api_key="" means keep existing key.

    Raises:
        ValueError: If profile not found, or the result would be unusable.
    """
    store = load_profiles()

    for profile in store.profiles:
        if profile.id == profile_id:
            _validate_profile(
                updates.get("name", profile.name),
                updates.get("endpoint_type") or profile.endpoint_type,
                updates.get("url", profile.url),
                updates.get("kind") or profile.kind,
                updates.get("agent_type", profile.agent_type),
                tuple(
                    updates.get(key, getattr(profile, key))
                    for key in ("default_model", "sonnet_model", "haiku_model")
                ),
            )
            for key, value in updates.items():
                if key == "api_key" and not value:
                    continue  # Preserve existing key
                if hasattr(profile, key) and key not in ("id", "created_at"):
                    setattr(profile, key, value)
            profile.updated_at = datetime.now()
            save_profiles(store)

            if store.active_profile_id == profile_id:
                activate_profile(profile_id, store.active_targets or None)
            return store

    raise ValueError(f"Profile not found: {profile_id}")


def delete_profile(profile_id: str) -> ProfileStore:
    """Delete a profile. If active, sets active_profile_id to None
    but does NOT clear the agent CLIs it was written into.

    Raises:
        ValueError: If profile not found.
    """
    store = load_profiles()

    original_len = len(store.profiles)
    store.profiles = [p for p in store.profiles if p.id != profile_id]

    if len(store.profiles) == original_len:
        raise ValueError(f"Profile not found: {profile_id}")

    if store.active_profile_id == profile_id:
        store.active_profile_id = None
        store.active_targets = []

    # A worker binding that outlives the profile it names is worse than no
    # binding: `frago agent` would resolve it to nothing and silently fall back
    # to the subscription, while the settings page still showed the deleted
    # profile's name as the worker's connection.
    if store.worker_profile_id == profile_id:
        store.worker_profile_id = None
    if store.lightagent_profile_id == profile_id:
        store.lightagent_profile_id = None
    if store.observer_profile_id == profile_id:
        store.observer_profile_id = None
    if store.coreagent_profile_id == profile_id:
        store.coreagent_profile_id = None

    save_profiles(store)
    return store


def get_profile(profile_id: str) -> APIProfile | None:
    """Get a single profile by ID."""
    store = load_profiles()
    for profile in store.profiles:
        if profile.id == profile_id:
            return profile
    return None


def activate_profile(
    profile_id: str, targets: Sequence[str] | None = None
) -> list[str]:
    """Activate a profile on the chosen agent CLIs.

    Each target gets this profile written into its own configuration, so that
    sessions the person starts by hand pick it up too — not just the ones frago
    launches.

    Args:
        profile_id: Profile to activate.
        targets: Agent CLIs to write it into. ``None`` keeps the historical
            behavior (Claude Code only), so callers that predate targets are
            unaffected.

    Returns:
        The targets the profile is now active on.

    Raises:
        ValueError: If the profile is not found, or a requested target cannot
            take a frago profile / is not installed here.
    """
    from frago.init.config_manager import load_config, save_config
    from frago.init.profile_targets import apply_profile, resolve_targets, revert_targets

    # Validate the request before touching anything: a half-applied activation
    # is worse than a refused one, because nothing on screen would say which
    # half went through.
    resolved = resolve_targets(targets)

    store = load_profiles()
    profile = None
    for p in store.profiles:
        if p.id == profile_id:
            profile = p
            break

    if not profile:
        raise ValueError(f"Profile not found: {profile_id}")

    # Checked here and not only in bind_role because this is also reachable
    # directly (the activate endpoint, the older API clients). Letting it
    # through would write a profile with no endpoint and no key into Claude
    # Code's settings and leave it unable to reach anything.
    if profile.kind == KIND_VENDOR_CLI:
        raise ValueError(
            f"'{profile.name}' runs on {profile.agent_type}'s own account, so frago has "
            "nothing to write into another CLI's configuration. It can be bound to the "
            "worker role, or started directly as your own agent."
        )
    if profile.kind == KIND_WORKBUDDY:
        raise ValueError(_frago_core_only(profile.name))

    previous = list(store.active_targets)
    apply_profile(profile, resolved)

    # Targets that were in force and are not chosen this time have to be handed
    # back. Skipping this is the silent-stale-config bug: unchecking opencode
    # would leave it running the old profile while the UI showed it as off.
    dropped = [t for t in previous if t not in resolved]
    if dropped:
        revert_targets(dropped)

    # frago's own auth_method describes Claude Code specifically — it is what
    # the init flow and the WebUI status card read. It only moves when claude's
    # own state moves.
    if "claude" in resolved:
        config = load_config()
        config.auth_method = "custom"
        config.api_endpoint = None
        save_config(config)
    elif "claude" in dropped:
        config = load_config()
        config.auth_method = "official"
        config.api_endpoint = None
        save_config(config)

    store.active_profile_id = profile_id
    store.active_targets = resolved
    save_profiles(store)
    return resolved


def deactivate_profile(targets: Sequence[str] | None = None) -> list[str]:
    """Deactivate the current profile, restoring each target's own config.

    Args:
        targets: Agent CLIs to hand back. ``None`` means all the ones this
            profile is currently active on.

    Returns:
        The targets that were handed back.
    """
    from frago.init.config_manager import load_config, save_config
    from frago.init.profile_targets import DEFAULT_TARGETS, revert_targets

    store = load_profiles()
    # An empty stored list on a store that predates targets still means Claude
    # Code — see load_profiles. Falling back here as well covers a store whose
    # active id was set directly rather than through activate_profile.
    active = list(store.active_targets) or list(DEFAULT_TARGETS)
    handing_back = [t for t in active if t in targets] if targets is not None else active

    revert_targets(handing_back)

    if "claude" in handing_back:
        config = load_config()
        config.auth_method = "official"
        config.api_endpoint = None
        save_config(config)

    remaining = [t for t in active if t not in handing_back]
    store.active_targets = remaining
    if not remaining:
        store.active_profile_id = None
    save_profiles(store)
    return handing_back


def role_binding_id(role: str) -> str | None:
    """The raw id a role is bound to, or None when it is on the subscription.

    Reads the main binding out of ``active_profile_id`` rather than a field of
    its own. Main's binding *is* the activation — the profile written into the
    agent CLIs' configuration — and a second field recording the same fact
    would be a second truth to keep in step with it.
    """
    if role not in ROLES:
        raise ValueError(f"Unknown role '{role}' (expected one of: {', '.join(ROLES)})")
    store = load_profiles()
    stored = {
        MAIN_ROLE: store.active_profile_id,
        WORKER_ROLE: store.worker_profile_id,
        LIGHTAGENT_ROLE: store.lightagent_profile_id,
        OBSERVER_ROLE: store.observer_profile_id,
        COREAGENT_ROLE: store.coreagent_profile_id,
    }[role]
    if role in FRAGO_CORE_ROLES:
        # These only ever name a saved row: the subscription is not one, and
        # frago-core could not call it anyway.
        return stored if stored and get_profile(stored) else None
    # An id left behind by a profile that no longer exists reads as unbound,
    # which is also what actually happens at launch.
    return stored if find_connection(stored) else None


def role_connection(role: str) -> APIProfile:
    """What an agent-CLI role runs on right now. Unbound resolves to the subscription.

    The two frago-core roles have no subscription to fall back to; ask
    :func:`role_view` for them.
    """
    if role in FRAGO_CORE_ROLES:
        raise ValueError(f"'{role}' has no subscription to fall back to; use role_view()")
    return find_connection(role_binding_id(role)) or official_connection()


def role_view(role: str) -> APIProfile | None:
    """What a role runs on right now, resolved the way the thing running it does.

    - main / worker: the bound connection, else the subscription.
    - lightagent: the bound connection, else what frago-core falls back to — the
      active profile, else the first saved one. Shown as-is even when frago-core
      cannot call it, so the page says what will actually be tried.
    - observer: the bound connection, else nothing. An unbound observer does not run.
    - coreagent: like the light agent — the bound connection, else the active
      profile, else the first saved one.
    """
    if role in CLI_ROLES:
        return role_connection(role)
    bound = role_binding_id(role)
    if bound:
        return get_profile(bound)
    if role == OBSERVER_ROLE:
        return None
    store = load_profiles()
    active = next((p for p in store.profiles if p.id == store.active_profile_id), None)
    return active or (store.profiles[0] if store.profiles else None)


def bind_role(
    role: str, profile_id: str, targets: Sequence[str] | None = None
) -> APIProfile | None:
    """Point a role at a connection.

    The two roles differ in what binding *does*, not just in what it records:

    - **main** writes the connection into the agent CLIs' own configuration, so
      it is the same act as activating, and binding the subscription is the
      same act as deactivating. ``targets`` says which CLIs, exactly as it does
      for ``activate_profile``.
    - **worker** only records the choice. Nothing is written anywhere; the
      binding is read when ``frago agent`` opens a session and applied to that
      session alone.

    A vendor CLI connection can only be bound to the worker role. Its
    credential is that CLI's own login, so there is nothing frago could write
    into Claude Code to put the person's own agent on it — the honest answer is
    to say so rather than to accept the binding and change nothing.

    The two frago-core roles only record the choice, like worker. An empty id or
    the subscription unbinds them: the light agent goes back to what it always
    used, the observer stops.

    Returns:
        The connection now bound to that role; None when a frago-core role was
        unbound.

    Raises:
        ValueError: Unknown role, unknown profile, or a binding this kind of
            connection cannot serve.
    """
    if role not in ROLES:
        raise ValueError(f"Unknown role '{role}' (expected one of: {', '.join(ROLES)})")

    if role in FRAGO_CORE_ROLES:
        return _bind_frago_core_role(role, profile_id)

    connection = find_connection(profile_id)
    if connection is None:
        raise ValueError(f"Profile not found: {profile_id}")
    if connection.kind == KIND_WORKBUDDY:
        raise ValueError(_frago_core_only(connection.name))

    if role == MAIN_ROLE:
        if connection.kind == KIND_VENDOR_CLI:
            raise ValueError(
                f"'{connection.name}' runs on {connection.agent_type}'s own account, so frago "
                "has nothing to write into another CLI's configuration. It can be bound to the "
                "worker role, or started directly as your own agent."
            )
        if connection.kind == KIND_OFFICIAL:
            deactivate_profile()
        else:
            activate_profile(connection.id, targets)
        return connection

    store = load_profiles()
    store.worker_profile_id = None if connection.kind == KIND_OFFICIAL else connection.id
    save_profiles(store)
    return connection


def _bind_frago_core_role(role: str, profile_id: str) -> APIProfile | None:
    store = load_profiles()
    field = _FRAGO_CORE_FIELDS[role]
    if not profile_id or profile_id == OFFICIAL_ID:
        setattr(store, field, None)
        save_profiles(store)
        return None
    connection = get_profile(profile_id)
    if connection is None:
        raise ValueError(f"Profile not found: {profile_id}")
    if connection.kind not in _FRAGO_CORE_KINDS:
        raise ValueError(
            f"'{connection.name}' runs on its own CLI's login, which frago-core cannot call. "
            "The light agent, the session observer and CoreAgent take a connection with its own key, "
            "or one that borrows the WorkBuddy login."
        )
    setattr(store, field, connection.id)
    save_profiles(store)
    return connection


def create_profile_from_current(name: str) -> APIProfile | None:
    """Create a profile from the current ~/.claude/settings.json configuration.

    Args:
        name: Name for the new profile.

    Returns:
        The created APIProfile, or None if no custom config is active.
    """
    from frago.init.configurator import (
        _infer_endpoint_type_from_url,
        load_claude_settings,
    )

    settings = load_claude_settings()
    env = settings.get("env", {})
    # Bearer-style endpoints (Tencent, OpenRouter) keep the credential in
    # ANTHROPIC_AUTH_TOKEN and blank out ANTHROPIC_API_KEY. Reading only the
    # latter reported "no custom configuration found" to users who were, at
    # that very moment, running on one.
    api_key = env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN") or ""

    if not api_key:
        return None

    base_url = env.get("ANTHROPIC_BASE_URL", "")
    endpoint_type = _infer_endpoint_type_from_url(base_url)

    profile = APIProfile(
        name=name,
        endpoint_type=endpoint_type,
        api_key=api_key,
        url=base_url if endpoint_type == "custom" else None,
        default_model=env.get("ANTHROPIC_MODEL"),
        sonnet_model=env.get("ANTHROPIC_DEFAULT_SONNET_MODEL"),
        haiku_model=env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL"),
    )

    store = load_profiles()
    store.profiles.append(profile)
    # Mark this profile as active since it matches current config. The config it
    # was read from is Claude Code's, so that is the one target it is active on
    # — claiming any other CLI here would be claiming a file frago never wrote.
    store.active_profile_id = profile.id
    store.active_targets = list(DEFAULT_TARGETS)
    save_profiles(store)

    return profile
