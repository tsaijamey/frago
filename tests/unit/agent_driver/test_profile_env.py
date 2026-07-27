"""profile 翻译与认证方式单一事实（spec 20260725 Phase 4）。

三件事分别守住：
1. ``resolve_auth_style`` 是认证方式的唯一出处，两档语义 + 回退链；
2. claude 的 ``profile_env`` 与改造前 ``_resolve_profile_env`` 逐键一致（零回归）；
3. opencode 的 ``session_env`` / ``profile_env`` 产出的注入配置形状正确。
"""

from __future__ import annotations

import json

from frago.agent_driver.driver import LaunchCtx, load_driver
from frago.init.configurator import (
    AUTH_STYLE_API_KEY,
    AUTH_STYLE_AUTH_TOKEN,
    PRESET_ENDPOINTS,
    build_claude_env_config,
    resolve_auth_style,
)
from frago.init.profile_manager import APIProfile


def _profile(**kw: object) -> APIProfile:
    base: dict[str, object] = {
        "name": "p",
        "endpoint_type": "deepseek",
        "api_key": "sk-test",
    }
    base.update(kw)
    return APIProfile(**base)  # type: ignore[arg-type]


# ── 认证方式的公共出口 ─────────────────────────────────────────────
def test_auth_style_preset_declaring_auth_token() -> None:
    """预设自己声明了 auth_token 的端点 → 授权头。"""
    assert resolve_auth_style("tencent_maas") == AUTH_STYLE_AUTH_TOKEN
    assert resolve_auth_style("tencent_tokenplan") == AUTH_STYLE_AUTH_TOKEN


def test_auth_style_preset_without_declaration_is_api_key() -> None:
    """没有 auth 声明的预设端点 → 密钥头。"""
    assert resolve_auth_style("deepseek") == AUTH_STYLE_API_KEY
    assert resolve_auth_style("kimi") == AUTH_STYLE_API_KEY


def test_auth_style_custom_endpoint_falls_back_to_api_key() -> None:
    """自定义端点没有声明可查 → 密钥头；显式参数仍可覆盖。"""
    assert resolve_auth_style("custom") == AUTH_STYLE_API_KEY
    assert resolve_auth_style("custom", "auth_token") == AUTH_STYLE_AUTH_TOKEN


# ── 自定义端点的结构化推断 ─────────────────────────────────────────
def test_auth_style_infers_auth_token_from_key_prefix() -> None:
    """sk-or- 是 OpenRouter 的密钥格式 → 授权头（URL 无须参与）。"""
    assert (
        resolve_auth_style("custom", api_key="sk-or-v1-abcdef")
        == AUTH_STYLE_AUTH_TOKEN
    )
    assert (
        resolve_auth_style(
            "custom", api_key="sk-or-v1-abcdef", url="https://proxy.example.test/api"
        )
        == AUTH_STYLE_AUTH_TOKEN
    )


def test_auth_style_infers_auth_token_from_endpoint_host() -> None:
    """主机名是 openrouter.ai（含子域）→ 授权头，密钥前缀不特殊也照样命中。"""
    for url in (
        "https://openrouter.ai/api",
        "https://openrouter.ai/api/v1/",
        "https://gateway.openrouter.ai/api",
        "https://openrouter.ai:443/api",
    ):
        assert (
            resolve_auth_style("custom", api_key="plain-key", url=url)
            == AUTH_STYLE_AUTH_TOKEN
        ), url


def test_auth_style_unknown_custom_endpoint_stays_api_key() -> None:
    """两条依据都不命中的自定义端点 → 维持默认密钥头。"""
    assert (
        resolve_auth_style(
            "custom", api_key="sk-plain-123", url="https://example.test/anthropic"
        )
        == AUTH_STYLE_API_KEY
    )
    # 相似但不同的主机名不算命中，避免把无关服务商误判成 OpenRouter
    assert (
        resolve_auth_style("custom", api_key="k", url="https://notopenrouter.ai/api")
        == AUTH_STYLE_API_KEY
    )
    assert (
        resolve_auth_style("custom", api_key="k", url="https://openrouter.ai.evil.test")
        == AUTH_STYLE_API_KEY
    )


def test_auth_style_presets_unchanged_even_with_inference_inputs() -> None:
    """六个预设端点逐一断言：推断依据在场也绝不改变既有判定。"""
    expected = {
        "deepseek": AUTH_STYLE_API_KEY,
        "aliyun": AUTH_STYLE_API_KEY,
        "kimi": AUTH_STYLE_API_KEY,
        "minimax": AUTH_STYLE_API_KEY,
        "tencent_maas": AUTH_STYLE_AUTH_TOKEN,
        "tencent_tokenplan": AUTH_STYLE_AUTH_TOKEN,
    }
    assert set(expected) == set(PRESET_ENDPOINTS), "预设端点集合变了，断言表需同步"
    for endpoint_type, style in expected.items():
        assert resolve_auth_style(endpoint_type) == style, endpoint_type
        # 哪怕递上 OpenRouter 的密钥与主机名，预设的判定也不受推断影响
        assert (
            resolve_auth_style(
                endpoint_type,
                api_key="sk-or-v1-abcdef",
                url="https://openrouter.ai/api",
            )
            == style
        ), endpoint_type


def test_auth_style_backward_compatible_without_new_arguments() -> None:
    """不传新参数时行为与改前逐项一致：前两位仍是位置参数，回退链不变。"""
    for endpoint_type in (*PRESET_ENDPOINTS, "custom", "whatever-unknown"):
        legacy_default = (
            str(PRESET_ENDPOINTS.get(endpoint_type, {}).get("auth"))
            if PRESET_ENDPOINTS.get(endpoint_type, {}).get("auth")
            else AUTH_STYLE_API_KEY
        )
        assert resolve_auth_style(endpoint_type) == legacy_default, endpoint_type
        # 显式参数依然压过一切
        assert (
            resolve_auth_style(endpoint_type, AUTH_STYLE_AUTH_TOKEN)
            == AUTH_STYLE_AUTH_TOKEN
        )
        assert (
            resolve_auth_style(endpoint_type, AUTH_STYLE_API_KEY) == AUTH_STYLE_API_KEY
        )


# ── claude 零回归 ──────────────────────────────────────────────────
def _legacy_claude_env(profile: APIProfile) -> dict[str, str]:
    """改造前 ``cli/agent_command._resolve_profile_env`` 的原样实现，作为对照基线。"""
    env = build_claude_env_config(
        endpoint_type=profile.endpoint_type,
        api_key=profile.api_key,
        custom_url=profile.url if profile.endpoint_type == "custom" else None,
        default_model=profile.default_model,
        sonnet_model=profile.sonnet_model,
        haiku_model=profile.haiku_model,
    )
    return {k: str(v) for k, v in env.items()}


def test_claude_profile_env_matches_legacy_for_every_endpoint_type() -> None:
    """真实预设端点各一条 + 自定义端点，逐键与改造前一致。"""
    driver = load_driver("claude")
    assert driver.profile_env is not None
    cases = [
        _profile(endpoint_type="deepseek"),
        _profile(endpoint_type="aliyun"),
        _profile(endpoint_type="kimi"),
        _profile(endpoint_type="minimax"),
        _profile(endpoint_type="tencent_maas"),
        _profile(endpoint_type="tencent_tokenplan"),
        _profile(
            endpoint_type="custom",
            url="https://example.test/anthropic",
            default_model="m-big",
            sonnet_model="m-mid",
            haiku_model="m-small",
        ),
        _profile(endpoint_type="deepseek", default_model="override-big"),
    ]
    for profile in cases:
        assert driver.profile_env(profile) == _legacy_claude_env(profile), (
            profile.endpoint_type
        )


def test_claude_auth_token_endpoint_uses_authorization_variable() -> None:
    """授权头端点把凭据放 ANTHROPIC_AUTH_TOKEN 并把 API_KEY 清空。"""
    driver = load_driver("claude")
    assert driver.profile_env is not None
    env = driver.profile_env(_profile(endpoint_type="tencent_maas"))
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-test"
    assert env["ANTHROPIC_API_KEY"] == ""


def test_claude_has_no_session_env() -> None:
    """claude 不需要基线环境变量（权限确认靠启动开关）。"""
    assert load_driver("claude").session_env is None


# ── opencode 注入配置 ──────────────────────────────────────────────
def _opencode_session_config() -> dict:
    driver = load_driver("opencode")
    assert driver.session_env is not None
    env = driver.session_env(LaunchCtx(cwd="/tmp", session_id="s"))
    return json.loads(env["OPENCODE_CONFIG_CONTENT"])


def _opencode_profile_config(profile: APIProfile) -> dict:
    driver = load_driver("opencode")
    assert driver.profile_env is not None
    env = driver.profile_env(profile)
    return json.loads(env["OPENCODE_CONFIG_CONTENT"])


def _assert_permissions_allowed(config: dict) -> None:
    perm = config["permission"]
    assert perm["edit"] == "allow"
    assert perm["bash"] == "allow"
    assert perm["webfetch"] == "allow"


def test_opencode_session_env_is_parseable_and_allows_permissions() -> None:
    """基线配置能解析、含权限放行、不带 provider。"""
    config = _opencode_session_config()
    _assert_permissions_allowed(config)
    assert "provider" not in config


def test_opencode_profile_env_carries_permissions_itself() -> None:
    """profile 版覆盖基线，故 MUST 自带权限放行，NEVER 依赖合并。"""
    _assert_permissions_allowed(_opencode_profile_config(_profile()))


def test_opencode_api_key_endpoint_omits_authorization_header() -> None:
    config = _opencode_profile_config(_profile(endpoint_type="deepseek"))
    options = config["provider"]["frago-profile"]["options"]
    assert options["apiKey"] == "sk-test"
    assert options["baseURL"] == "https://api.deepseek.com/anthropic"
    assert "headers" not in options


def test_opencode_auth_token_endpoint_adds_authorization_header() -> None:
    config = _opencode_profile_config(_profile(endpoint_type="tencent_maas"))
    options = config["provider"]["frago-profile"]["options"]
    assert options["headers"] == {"Authorization": "Bearer sk-test"}


def test_opencode_provider_uses_anthropic_compatible_sdk() -> None:
    config = _opencode_profile_config(_profile())
    assert config["provider"]["frago-profile"]["npm"] == "@ai-sdk/anthropic"


def _assert_model_refs_are_declared(config: dict) -> None:
    """引用与声明 MUST 配套：被 model / small_model 引用的模型必须出现在同一
    provider 的 models 声明里。少了 models，opencode 解析不出这个引用，会静默
    回退到用户自己配的 provider——模型重名时人眼完全看不出来。"""
    declared = config["provider"]["frago-profile"].get("models", {})
    for key in ("model", "small_model"):
        ref = config.get(key)
        if ref is None:
            continue
        provider_id, _, model_name = ref.partition("/")
        assert provider_id == "frago-profile"
        assert model_name in declared, f"{key}={ref} 未在 models 中声明: {declared}"


def test_opencode_model_reference_is_always_declared_in_provider() -> None:
    for profile in (
        _profile(default_model="big-1"),
        _profile(default_model="big-1", haiku_model="small-1"),
        _profile(default_model="same", haiku_model="same"),
        _profile(haiku_model="small-only"),
    ):
        _assert_model_refs_are_declared(_opencode_profile_config(profile))


def test_opencode_maps_default_and_haiku_but_never_sonnet() -> None:
    """主模型 → model，快模型 → small_model，中档模型不出现（spec 已定）。"""
    config = _opencode_profile_config(
        _profile(default_model="big-1", sonnet_model="mid-1", haiku_model="small-1")
    )
    assert config["model"] == "frago-profile/big-1"
    assert config["small_model"] == "frago-profile/small-1"
    assert "mid-1" not in json.dumps(config)
    assert config["provider"]["frago-profile"]["models"] == {"big-1": {}, "small-1": {}}
    _assert_model_refs_are_declared(config)


def test_opencode_without_default_model_omits_model() -> None:
    """profile 没有主模型时不设 model，只提供 provider——模型仍听 opencode 自己的配置。"""
    config = _opencode_profile_config(
        _profile(endpoint_type="custom", url="https://example.test")
    )
    assert "model" not in config
    assert "provider" in config
    assert "models" not in config["provider"]["frago-profile"]


def test_opencode_custom_endpoint_uses_profile_url() -> None:
    config = _opencode_profile_config(
        _profile(endpoint_type="custom", url="https://example.test/anthropic")
    )
    options = config["provider"]["frago-profile"]["options"]
    assert options["baseURL"] == "https://example.test/anthropic"


# ── 真实 OpenRouter profile 端到端 ─────────────────────────────────
def _openrouter_profile() -> APIProfile:
    """线上那条 profile 的原样形状：自定义端点 + OpenRouter 的 URL 与密钥格式。"""
    return _profile(
        name="OpenRouter Kimi K3",
        endpoint_type="custom",
        url="https://openrouter.ai/api",
        api_key="sk-or-v1-secret",
    )


def test_opencode_openrouter_profile_gets_authorization_header() -> None:
    """OpenRouter 只认授权头，漏了这个头就是零产出跑满超时。"""
    config = _opencode_profile_config(_openrouter_profile())
    options = config["provider"]["frago-profile"]["options"]
    assert options["headers"] == {"Authorization": "Bearer sk-or-v1-secret"}
    assert options["baseURL"] == "https://openrouter.ai/api"


def test_claude_openrouter_profile_gets_authorization_variable() -> None:
    """同一条 profile 在 claude 侧也走授权头：凭据进 ANTHROPIC_AUTH_TOKEN，
    ANTHROPIC_API_KEY 清空——改前给的是密钥头，那份配置本来就是错的。"""
    driver = load_driver("claude")
    assert driver.profile_env is not None
    env = driver.profile_env(_openrouter_profile())
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-or-v1-secret"
    assert env["ANTHROPIC_API_KEY"] == ""
    assert env["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"
