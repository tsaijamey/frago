"""Unit tests for MainConfigService (Phase 5: 关键配置 CRUD、原零覆盖).

以单元测试为准：断言契约——get_config 注入 working_directory_display、异常时降级到
默认 Config；update_config 成功回 ok+config、ValidationError / 其它异常回 error。
下层 frago.init.config_manager 全部 mock，不碰真实 ~/.frago/config.json。
"""

from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from frago.server.services.main_config_service import MainConfigService


def _cfg(d):
    return SimpleNamespace(model_dump=lambda mode="json": dict(d))


def test_get_config_injects_display_path():
    with patch("frago.init.config_manager.load_config", return_value=_cfg({"auth_method": "official"})):
        out = MainConfigService.get_config()
    assert out["auth_method"] == "official"
    assert "working_directory_display" in out
    assert out["working_directory_display"].endswith("projects")


def test_get_config_degrades_to_default_on_error():
    with patch("frago.init.config_manager.load_config", side_effect=RuntimeError("boom")), \
         patch("frago.init.models.Config", return_value=_cfg({"auth_method": "official"})):
        out = MainConfigService.get_config()
    assert "working_directory_display" in out  # still returns a usable default shape


def test_update_config_ok():
    with patch("frago.init.config_manager.update_config", return_value=_cfg({"working_directory": "~/.frago"})):
        res = MainConfigService.update_config({"working_directory": "~/.frago"})
    assert res["status"] == "ok"
    assert res["config"]["working_directory"] == "~/.frago"
    assert "working_directory_display" in res["config"]


def test_update_config_validation_error():
    err = ValidationError.from_exception_data("Config", [])
    with patch("frago.init.config_manager.update_config", side_effect=err):
        res = MainConfigService.update_config({"bad": 1})
    assert res["status"] == "error"
    assert "validation" in res["error"].lower()


def test_update_config_generic_error():
    with patch("frago.init.config_manager.update_config", side_effect=OSError("disk full")):
        res = MainConfigService.update_config({"x": 1})
    assert res["status"] == "error"
    assert "disk full" in res["error"]
