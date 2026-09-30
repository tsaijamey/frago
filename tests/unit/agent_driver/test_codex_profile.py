"""codex 吃 profile 的两个作用域：frago 起的会话，与写进 ~/.codex/config.toml 的激活。

守住的事：
1. 密钥 NEVER 上启动命令行（那行字是打进 pane 的 shell 执行的，会进历史、留在屏上）；
2. 写配置只动两个顶层键和 frago 自己那张 provider 表，其余原样；
3. 撤销后回到接管前的样子，frago 的表连同明文密钥一起消失；
4. 没有 Responses 通道的 profile 说清缺什么，不悄悄跑在别的模型上。
"""

from __future__ import annotations

import tomllib

import pytest

from frago.agent_driver.driver import LaunchCtx, load_driver
from frago.agent_driver.drivers import codex
from frago.init.profile_manager import APIProfile, ProfileChannel
from frago.session import codex_store

_ORIGINAL = """model = "deepseek-v4-flash-vision-exp"
model_provider = "deepseek"
model_reasoning_effort = "high"

# 用户自己的注释
[model_providers.deepseek]
name = "DeepSeek"
base_url = "https://api.deepseek.com/"
wire_api = "responses"

[projects."/Users/someone/repo"]
trust_level = "trusted"
"""


@pytest.fixture
def config():
    path = codex_store.get_codex_home() / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_ORIGINAL, encoding="utf-8")
    return path


def _ark(**extra) -> APIProfile:
    return APIProfile(
        name="Ark",
        endpoint_type="custom",
        api_key="ark-secret",
        url="https://ark.cn-beijing.volces.com/api/plan",
        default_model="deepseek-v4.1-flash",
        channels=[
            ProfileChannel(protocol="responses", url="https://ark.cn-beijing.volces.com/api/plan/v3")
        ],
        **extra,
    )


def test_codex_driver_takes_profiles_on_the_responses_channel() -> None:
    driver = load_driver("codex")
    assert driver.profile_protocol == "responses"
    assert driver.profile_env and driver.profile_apply and driver.profile_revert


def test_session_env_carries_key_url_and_model() -> None:
    env = codex._profile_env(_ark())
    assert env == {
        "FRAGO_CODEX_KEY": "ark-secret",
        "FRAGO_CODEX_BASE_URL": "https://ark.cn-beijing.volces.com/api/plan/v3",
        "FRAGO_CODEX_MODEL": "deepseek-v4.1-flash",
    }


def test_channel_model_wins_over_the_profile_default() -> None:
    profile = APIProfile(name="DS", endpoint_type="deepseek", api_key="k", default_model="deepseek-pro")
    assert codex._profile_env(profile)["FRAGO_CODEX_MODEL"] == "deepseek-v4-flash"


def test_profile_without_responses_channel_is_refused() -> None:
    profile = APIProfile(name="Only A", endpoint_type="custom", api_key="k", url="https://x.example.com")
    with pytest.raises(ValueError, match="Responses"):
        codex._profile_env(profile)


def test_launch_command_names_provider_but_never_the_key(tmp_path) -> None:
    env = codex._profile_env(_ark())
    cmd = codex._launch(LaunchCtx(cwd=str(tmp_path), session_id="s1", env=env))
    assert "ark-secret" not in cmd
    assert 'model_provider="frago-profile"' in cmd
    assert "api/plan/v3" in cmd
    assert 'env_key="FRAGO_CODEX_KEY"' in cmd
    assert 'wire_api="responses"' in cmd


def test_launch_without_profile_is_unchanged(tmp_path) -> None:
    cmd = codex._launch(LaunchCtx(cwd=str(tmp_path), session_id="s2"))
    assert "model_provider" not in cmd


def test_apply_merges_and_revert_restores(config) -> None:
    codex._profile_apply(_ark())

    text = config.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    assert data["model_provider"] == "frago-profile"
    assert data["model"] == "deepseek-v4.1-flash"
    frago = data["model_providers"]["frago-profile"]
    assert frago["base_url"] == "https://ark.cn-beijing.volces.com/api/plan/v3"
    assert frago["wire_api"] == "responses"
    assert frago["experimental_bearer_token"] == "ark-secret"
    # 其余原样：用户的 provider、注释、项目信任、其它顶层键都在。
    assert data["model_providers"]["deepseek"]["name"] == "DeepSeek"
    assert "# 用户自己的注释" in text
    assert data["projects"]["/Users/someone/repo"]["trust_level"] == "trusted"
    assert data["model_reasoning_effort"] == "high"
    assert oct(config.stat().st_mode & 0o777) == "0o600"
    assert (config.parent / "config.toml.frago-backup").read_text(encoding="utf-8") == _ORIGINAL

    codex._profile_revert()

    assert config.read_text(encoding="utf-8") == _ORIGINAL


def test_switching_profiles_keeps_the_real_original(config) -> None:
    codex._profile_apply(_ark())
    other = _ark()
    other.api_key = "second-secret"
    codex._profile_apply(other)

    text = config.read_text(encoding="utf-8")
    assert text.count("[model_providers.frago-profile]") == 1
    assert "second-secret" in text and "ark-secret" not in text

    codex._profile_revert()
    assert config.read_text(encoding="utf-8") == _ORIGINAL


def test_revert_with_nothing_taken_over_leaves_the_file_alone(config) -> None:
    codex._profile_revert()
    assert config.read_text(encoding="utf-8") == _ORIGINAL


def test_apply_on_a_machine_without_a_codex_config(tmp_path) -> None:
    path = codex_store.get_codex_home() / "config.toml"
    assert not path.exists()

    codex._profile_apply(_ark())
    assert tomllib.loads(path.read_text(encoding="utf-8"))["model_provider"] == "frago-profile"

    codex._profile_revert()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert "model_provider" not in data and "model" not in data
