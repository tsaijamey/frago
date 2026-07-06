"""config.json round-trip 保真性（回归：20260704 save_config 丢 daemons 段）。

config.json 是多方共写的文件：`frago daemon enable` 等以 raw JSON 直写自己的段。
Config 模型 MUST 对未知键透传（extra="allow"），任何 load→save round-trip 都不得
静默丢段——否则 `frago channel add` 这类正当操作会吃掉别人的配置（桌宠守护曾因此
随 server 重启消失）。
"""

import json

import pytest

from frago.init import config_manager
from frago.init.models import Config


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_manager, "CONFIG_PATH", path)
    return path


def _base_config_data() -> dict:
    return {
        "schema_version": "1.0",
        "auth_method": "official",
        "init_completed": True,
    }


class TestDaemonsSectionSurvivesRoundTrip:
    def test_load_save_preserves_daemons(self, config_path):
        data = _base_config_data()
        data["daemons"] = {
            "enabled": True,
            "items": [{"recipe": "voice_desktop_hud", "enabled": True}],
        }
        config_path.write_text(json.dumps(data), encoding="utf-8")

        config_manager.save_config(config_manager.load_config())

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert saved["daemons"]["enabled"] is True
        assert saved["daemons"]["items"] == [{"recipe": "voice_desktop_hud", "enabled": True}]

    def test_update_config_preserves_daemons(self, config_path):
        data = _base_config_data()
        data["daemons"] = {"enabled": True, "items": [{"recipe": "voice_desktop_hud"}]}
        config_path.write_text(json.dumps(data), encoding="utf-8")

        config_manager.update_config({"ccr_enabled": True})

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert saved["ccr_enabled"] is True
        assert saved["daemons"]["items"][0]["recipe"] == "voice_desktop_hud"

    def test_daemon_item_extra_fields_survive(self, config_path):
        """restart_policy 等未建模的 per-item 覆盖项同样透传。"""
        data = _base_config_data()
        data["daemons"] = {
            "enabled": True,
            "items": [{"recipe": "x", "enabled": True, "restart_policy": "always"}],
        }
        config_path.write_text(json.dumps(data), encoding="utf-8")

        config_manager.save_config(config_manager.load_config())

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert saved["daemons"]["items"][0]["restart_policy"] == "always"


class TestUnknownKeysSurviveRoundTrip:
    def test_unknown_top_level_key_preserved(self, config_path):
        """未来任何 raw 直写的新段都不得被 save_config 吃掉。"""
        data = _base_config_data()
        data["some_future_section"] = {"k": [1, 2, 3]}
        config_path.write_text(json.dumps(data), encoding="utf-8")

        config_manager.save_config(config_manager.load_config())

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert saved["some_future_section"] == {"k": [1, 2, 3]}

    def test_absent_daemons_stays_null_not_fabricated(self, config_path):
        """无 daemons 段时 round-trip 不得凭空捏造出启用状态。"""
        config_path.write_text(json.dumps(_base_config_data()), encoding="utf-8")

        config_manager.save_config(config_manager.load_config())

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert saved.get("daemons") is None

    def test_default_config_model_still_validates(self):
        assert Config().daemons is None
