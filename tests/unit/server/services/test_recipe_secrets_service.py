"""Unit tests for RecipeSecretsService (Phase 5: 安全敏感、原零覆盖).

以单元测试为准：断言契约——值脱敏（只回 has_value）、$ref 解析与写穿、None 删键、
不覆盖 $ref 目标、IO 失败安全降级。SECRETS_PATH 指向 tmp，不碰真实 ~/.frago。
"""

import json
from types import SimpleNamespace

import pytest

from frago.server.services.recipe_secrets_service import RecipeSecretsService


@pytest.fixture
def secrets_path(tmp_path, monkeypatch):
    p = tmp_path / "recipes.local.json"
    monkeypatch.setattr(RecipeSecretsService, "SECRETS_PATH", p)
    return p


def _set_schema(monkeypatch, schema):
    monkeypatch.setattr(
        RecipeSecretsService, "_get_recipe_metadata",
        staticmethod(lambda name: SimpleNamespace(secrets=schema)),
    )


def test_load_missing_file_returns_empty(secrets_path):
    assert RecipeSecretsService._load_secrets_file() == {}


def test_save_then_load_roundtrip(secrets_path):
    RecipeSecretsService._save_secrets_file({"r": {"k": "v"}})
    assert secrets_path.exists()
    assert RecipeSecretsService._load_secrets_file() == {"r": {"k": "v"}}


def test_get_secrets_masks_values_and_reports_has_value(secrets_path, monkeypatch):
    _set_schema(monkeypatch, {
        "API_KEY": {"type": "string", "required": True, "description": "key"},
        "OPTIONAL": {"type": "string"},
    })
    secrets_path.write_text(json.dumps({"myrecipe": {"API_KEY": "secret123"}}), encoding="utf-8")

    out = RecipeSecretsService.get_recipe_secrets("myrecipe")

    assert out["recipe_name"] == "myrecipe"
    by_key = {f["key"]: f for f in out["fields"]}
    # 值不外泄，只报 has_value
    assert "secret123" not in json.dumps(out)
    assert by_key["API_KEY"]["has_value"] is True
    assert by_key["API_KEY"]["required"] is True
    assert by_key["OPTIONAL"]["has_value"] is False
    assert out["is_ref"] is False


def test_get_secrets_resolves_ref(secrets_path, monkeypatch):
    _set_schema(monkeypatch, {"TOKEN": {"type": "string"}})
    secrets_path.write_text(json.dumps({
        "child": {"$ref": "shared"},
        "shared": {"TOKEN": "abc"},
    }), encoding="utf-8")

    out = RecipeSecretsService.get_recipe_secrets("child")
    assert out["is_ref"] is True
    assert out["ref_target"] == "shared"
    assert {f["key"]: f["has_value"] for f in out["fields"]} == {"TOKEN": True}


def test_update_writes_and_none_removes(secrets_path, monkeypatch):
    _set_schema(monkeypatch, {})
    assert RecipeSecretsService.update_recipe_secrets("r", {"A": "1", "B": "2"}) == {"status": "ok"}
    assert RecipeSecretsService._load_secrets_file()["r"] == {"A": "1", "B": "2"}

    RecipeSecretsService.update_recipe_secrets("r", {"A": None})
    assert RecipeSecretsService._load_secrets_file()["r"] == {"B": "2"}


def test_update_through_ref_writes_to_target(secrets_path):
    secrets_path.write_text(json.dumps({"child": {"$ref": "shared"}, "shared": {}}), encoding="utf-8")
    RecipeSecretsService.update_recipe_secrets("child", {"TOKEN": "xyz"})
    cfg = RecipeSecretsService._load_secrets_file()
    assert cfg["shared"] == {"TOKEN": "xyz"}
    assert cfg["child"] == {"$ref": "shared"}  # ref entry untouched


def test_update_load_error_returns_error(secrets_path):
    secrets_path.write_text("{ not json", encoding="utf-8")
    res = RecipeSecretsService.update_recipe_secrets("r", {"A": "1"})
    assert res["status"] == "error"
