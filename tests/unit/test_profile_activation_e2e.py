"""激活一条 profile，两个 agent cli 的配置文件真的变了；取消后真的变回来。

上面几个测试各自打了桩：profile_manager 的测试把 driver 换成 mock，driver 的测试
把 profile_manager 撇在一边。两边都绿而接线错了是完全可能的——所以这里一根桩都不
打 driver，走真实注册表，落到真实文件上（HOME 指向临时目录），验的是端到端。
"""

from __future__ import annotations

import json

import pytest

from frago.init.profile_manager import (
    APIProfile,
    activate_profile,
    add_profile,
    deactivate_profile,
    load_profiles,
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """把三份会被写到的配置、加 frago 自己的账本，全指到临时目录。"""
    claude_settings = tmp_path / ".claude" / "settings.json"
    claude_settings.parent.mkdir(parents=True)
    opencode_dir = tmp_path / ".config" / "opencode"
    opencode_dir.mkdir(parents=True)

    monkeypatch.setattr(
        "frago.init.configurator.CLAUDE_SETTINGS_PATH", claude_settings
    )
    monkeypatch.setattr(
        "frago.init.configurator.CLAUDE_JSON_PATH", tmp_path / ".claude.json"
    )
    monkeypatch.setattr(
        "frago.init.opencode_plugin.get_opencode_config_dir", lambda: opencode_dir
    )
    monkeypatch.setattr(
        "frago.init.profile_manager.PROFILES_PATH", tmp_path / "profiles.json"
    )
    monkeypatch.setattr(
        "frago.init.profile_target_backup.BACKUP_PATH", tmp_path / "backup.json"
    )
    # frago 自己的 config.json 不是本测试的对象，但激活会写它。
    monkeypatch.setattr(
        "frago.init.config_manager.CONFIG_PATH", tmp_path / "config.json"
    )
    # 本机装没装 claude / opencode 与这条链路无关，统一当作装了。
    monkeypatch.setattr(
        "frago.init.profile_targets._installed_path",
        lambda agent: f"/bin/{agent}",
    )

    return type(
        "Home",
        (),
        {
            "claude_settings": claude_settings,
            "opencode_config": opencode_dir / "opencode.json",
        },
    )


@pytest.fixture
def saved(home):
    add_profile(
        APIProfile(
            id="e2e00001",
            name="DeepSeek",
            endpoint_type="deepseek",
            api_key="sk-e2e-key",
            default_model="deepseek-v4-flash",
            haiku_model="deepseek-v4-flash-lite",
        )
    )
    return "e2e00001"


def _read(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_activating_on_both_writes_both_configs(home, saved) -> None:
    activate_profile(saved, ["claude", "opencode"])

    claude_env = _read(home.claude_settings)["env"]
    assert claude_env["ANTHROPIC_MODEL"] == "deepseek-v4-flash"
    assert claude_env["ANTHROPIC_API_KEY"] == "sk-e2e-key"

    opencode = _read(home.opencode_config)
    assert opencode["model"] == "frago-profile/deepseek-v4-flash"
    assert (
        opencode["provider"]["frago-profile"]["options"]["apiKey"] == "sk-e2e-key"
    )


def test_activating_on_claude_alone_leaves_opencode_untouched(home, saved) -> None:
    """这正是原来那个隐形行为——现在它是一个被明确选择的结果，而不是默认。"""
    activate_profile(saved, ["claude"])

    assert home.claude_settings.exists()
    assert not home.opencode_config.exists()


def test_deactivating_restores_both(home, saved) -> None:
    home.opencode_config.write_text(
        json.dumps({"model": "deepseek/deepseek-v4-flash", "lsp": True}),
        encoding="utf-8",
    )

    activate_profile(saved, ["claude", "opencode"])
    deactivate_profile()

    assert "ANTHROPIC_MODEL" not in _read(home.claude_settings).get("env", {})
    opencode = _read(home.opencode_config)
    assert opencode["model"] == "deepseek/deepseek-v4-flash"
    assert "provider" not in opencode

    store = load_profiles()
    assert store.active_profile_id is None
    assert store.active_targets == []


def test_unchecking_opencode_hands_it_back_immediately(home, saved) -> None:
    """改激活范围时，被去掉的那个必须当场还原——不是等到取消激活。"""
    home.opencode_config.write_text(
        json.dumps({"model": "deepseek/deepseek-v4-flash"}), encoding="utf-8"
    )
    activate_profile(saved, ["claude", "opencode"])

    activate_profile(saved, ["claude"])

    opencode = _read(home.opencode_config)
    assert opencode["model"] == "deepseek/deepseek-v4-flash"
    assert "provider" not in opencode
    # claude 那边不受影响，仍在这条 profile 上。
    assert _read(home.claude_settings)["env"]["ANTHROPIC_MODEL"] == "deepseek-v4-flash"


def test_editing_the_active_profile_reaches_both(home, saved) -> None:
    from frago.init.profile_manager import update_profile

    activate_profile(saved, ["claude", "opencode"])
    update_profile(saved, {"default_model": "deepseek-v4-flash-vision-exp"})

    assert (
        _read(home.claude_settings)["env"]["ANTHROPIC_MODEL"]
        == "deepseek-v4-flash-vision-exp"
    )
    assert (
        _read(home.opencode_config)["model"]
        == "frago-profile/deepseek-v4-flash-vision-exp"
    )
