"""激活到 opencode：写进它自己的 opencode.json，取消激活还原干净。

会话注入（``profile_env``）与激活（``profile_apply``）翻译同一条 profile，区别只在
落点。落点是用户的全局配置，所以这组测试盯的是"别弄坏人家的东西"：

1. 只动 frago 自己那一格 provider 和两个模型选择键，其它配置一个不碰；
2. 权限放行 NEVER 写进去——那是给无人值守 worker 的取舍，不是用户的选择；
3. 取消激活要还原成接管前的模型，而不是留一个"没有模型"或"指向已删 provider"的配置；
4. 反复激活不会把 frago 自己写的值当成"用户原值"记账。
"""

from __future__ import annotations

import json

import pytest

from frago.agent_driver.driver import load_driver
from frago.init.profile_manager import APIProfile


@pytest.fixture
def opencode_config(tmp_path, monkeypatch):
    """把 opencode 的全局配置与 frago 的备份账本都指到临时目录。"""
    config_dir = tmp_path / "opencode"
    config_dir.mkdir()
    monkeypatch.setattr(
        "frago.init.opencode_plugin.get_opencode_config_dir", lambda: config_dir
    )
    monkeypatch.setattr(
        "frago.init.profile_target_backup.BACKUP_PATH", tmp_path / "backup.json"
    )
    return config_dir / "opencode.json"


@pytest.fixture
def driver():
    return load_driver("opencode")


def _profile(**kw: object) -> APIProfile:
    base: dict[str, object] = {
        "name": "p",
        "endpoint_type": "deepseek",
        "api_key": "sk-test",
        "default_model": "deepseek-v4-flash",
        "haiku_model": "deepseek-v4-flash-lite",
    }
    base.update(kw)
    return APIProfile(**base)  # type: ignore[arg-type]


def _read(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ── 落盘 ───────────────────────────────────────────────────────────
def test_apply_writes_provider_and_model_selection(opencode_config, driver) -> None:
    driver.profile_apply(_profile())

    config = _read(opencode_config)
    assert config["model"] == "frago-profile/deepseek-v4-flash"
    assert config["small_model"] == "frago-profile/deepseek-v4-flash-lite"
    provider = config["provider"]["frago-profile"]
    assert provider["npm"] == "@ai-sdk/anthropic"
    assert provider["options"]["apiKey"] == "sk-test"
    # SDK 只补 /messages，所以地址这边要带版本段。
    assert provider["options"]["baseURL"].endswith("/v1")
    # 被引用的模型必须逐个声明，否则 opencode 静默回退到用户自己的 provider。
    assert set(provider["models"]) == {
        "deepseek-v4-flash",
        "deepseek-v4-flash-lite",
    }


def test_apply_creates_the_file_when_there_is_none(opencode_config, driver) -> None:
    assert not opencode_config.exists()
    driver.profile_apply(_profile())
    assert opencode_config.exists()


def test_apply_leaves_everything_else_alone(opencode_config, driver) -> None:
    """用户的 provider、MCP、LSP 设置在激活后原样还在。"""
    opencode_config.write_text(
        json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "model": "deepseek/deepseek-v4-flash",
                "lsp": True,
                "mcp": {"some-server": {"command": "x"}},
                "provider": {"openrouter": {"models": {"moonshotai/kimi-k3": {}}}},
            }
        ),
        encoding="utf-8",
    )

    driver.profile_apply(_profile())

    config = _read(opencode_config)
    assert config["$schema"] == "https://opencode.ai/config.json"
    assert config["lsp"] is True
    assert config["mcp"] == {"some-server": {"command": "x"}}
    assert "openrouter" in config["provider"]
    assert "frago-profile" in config["provider"]


def test_apply_never_writes_the_permission_bypass(opencode_config, driver) -> None:
    """权限放行只属于 frago 起的无人值守会话，NEVER 写进用户的全局配置。"""
    driver.profile_apply(_profile())
    assert "permission" not in _read(opencode_config)


def test_session_injection_still_carries_the_permission_bypass(driver) -> None:
    """反过来，会话注入那条路必须仍然带着放行，否则 worker 卡在权限询问上。"""
    injected = json.loads(driver.profile_env(_profile())["OPENCODE_CONFIG_CONTENT"])
    assert injected["permission"]["edit"] == "allow"
    assert injected["provider"]["frago-profile"]["npm"] == "@ai-sdk/anthropic"


def test_session_injection_does_not_touch_the_global_config(
    opencode_config, driver
) -> None:
    driver.profile_env(_profile())
    assert not opencode_config.exists()


# ── 还原 ───────────────────────────────────────────────────────────
def test_revert_restores_the_model_the_user_had(opencode_config, driver) -> None:
    """只删 frago 的部分会留下一个没有模型的配置——比激活前更糟。"""
    opencode_config.write_text(
        json.dumps({"model": "deepseek/deepseek-v4-flash", "lsp": True}),
        encoding="utf-8",
    )

    driver.profile_apply(_profile())
    driver.profile_revert()

    config = _read(opencode_config)
    assert config["model"] == "deepseek/deepseek-v4-flash"
    assert config["lsp"] is True
    assert "provider" not in config


def test_revert_drops_a_model_the_user_never_had(opencode_config, driver) -> None:
    """接管前就没有模型选择 → 还原后也不该凭空多出一个。"""
    opencode_config.write_text(json.dumps({"lsp": True}), encoding="utf-8")

    driver.profile_apply(_profile())
    driver.profile_revert()

    config = _read(opencode_config)
    assert "model" not in config
    assert "small_model" not in config


def test_revert_keeps_other_providers(opencode_config, driver) -> None:
    opencode_config.write_text(
        json.dumps({"provider": {"openrouter": {"models": {}}}}), encoding="utf-8"
    )

    driver.profile_apply(_profile())
    driver.profile_revert()

    config = _read(opencode_config)
    assert config["provider"] == {"openrouter": {"models": {}}}


def test_reactivating_does_not_lose_the_original_model(opencode_config, driver) -> None:
    """第二次激活看到的"原值"已经是 frago 写的；记进备份就把真原值弄丢了。"""
    opencode_config.write_text(
        json.dumps({"model": "deepseek/deepseek-v4-flash"}), encoding="utf-8"
    )

    driver.profile_apply(_profile())
    driver.profile_apply(_profile(default_model="other-model"))
    driver.profile_revert()

    assert _read(opencode_config)["model"] == "deepseek/deepseek-v4-flash"


def test_revert_without_a_backup_still_clears_frago_values(
    opencode_config, driver, tmp_path
) -> None:
    """备份文件被删了，也 NEVER 留下一个指向已删除 provider 的模型名。"""
    driver.profile_apply(_profile())
    (tmp_path / "backup.json").unlink(missing_ok=True)

    driver.profile_revert()

    config = _read(opencode_config)
    assert "model" not in config
    assert "small_model" not in config


def test_revert_on_a_machine_with_no_config_is_a_no_op(opencode_config, driver) -> None:
    driver.profile_revert()
    assert not opencode_config.exists()
