"""Unit tests for controlled recipe self-secret writeback command & api_proxy renewal.

Covers:
1. Standard stdin writeback of declared secret for self.
2. Rejection of undeclared secret keys (whitelist enforced against recipe.md).
3. Anti-escalation refusal when caller attempts cross-recipe secret writeback.
4. Preservation of all other recipe sections and existing keys in recipes.local.json.
5. Safe creation and 0600 permission maintenance on recipes.local.json.
6. Zero plaintext token leakage in output, logs and return values.
7. Support for $ref section redirection.
8. CLI command interface via both `frago recipe set-secret` and `frago recipe secret set`.
9. `api_proxy` renewal integration call verification.
"""

import json
import os
import stat
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from frago.cli.recipe_commands import recipe_group
from frago.recipes.exceptions import (
    RecipeSecretPermissionError,
    RecipeSecretValidationError,
)
from frago.recipes.secrets import (
    get_secrets_path,
    load_recipe_secrets_file,
    save_recipe_secrets_file,
    update_recipe_self_secret,
)


@pytest.fixture
def mock_secrets_env(tmp_path, monkeypatch):
    """Fixture redirecting recipes.local.json to an isolated temp path."""
    target_file = tmp_path / "recipes.local.json"
    monkeypatch.setenv("FRAGO_RECIPES_LOCAL_PATH", str(target_file))
    return target_file


@pytest.fixture
def mock_metadata_registry(monkeypatch):
    """Fixture mocking declared recipe secrets schema."""
    schemas = {
        "api_proxy": {
            "uid": {"type": "string", "required": False},
            "accessToken": {"type": "string", "required": False},
            "refreshToken": {"type": "string", "required": False},
            "domain": {"type": "string", "required": False},
        },
        "other_recipe": {
            "token": {"type": "string", "required": True},
        },
    }

    def _get_secrets(name):
        if name in schemas:
            return schemas[name]
        from frago.recipes.exceptions import RecipeNotFoundError
        raise RecipeNotFoundError(name)

    monkeypatch.setattr("frago.recipes.secrets.get_recipe_declared_secrets", _get_secrets)
    return schemas


def test_update_declared_secret_success(mock_secrets_env, mock_metadata_registry):
    """Declared secret key should be written safely and atomically."""
    # Pre-seed existing configuration with other recipe
    initial_data = {
        "other_recipe": {"token": "preserve_me_123"},
        "api_proxy": {"uid": "user_42", "accessToken": "old_token"},
    }
    save_recipe_secrets_file(initial_data, mock_secrets_env)

    token_val = "new_secret_access_token_999"
    res = update_recipe_self_secret(
        "api_proxy",
        "accessToken",
        token_val,
        caller_identity="api_proxy",
        secrets_path=mock_secrets_env,
    )

    # 1. Check returned metadata summary (no plaintext)
    assert res["status"] == "ok"
    assert res["recipe"] == "api_proxy"
    assert res["key"] == "accessToken"
    assert res["length"] == len(token_val)
    assert "sha256_prefix" in res
    assert token_val not in str(res)

    # 2. Check persistence and section preservation
    saved = load_recipe_secrets_file(mock_secrets_env)
    assert saved["api_proxy"]["accessToken"] == token_val
    assert saved["api_proxy"]["uid"] == "user_42"
    assert saved["other_recipe"]["token"] == "preserve_me_123"

    # 3. File permissions must be 0600
    file_stat = mock_secrets_env.stat()
    assert (file_stat.st_mode & 0o777) == 0o600


def test_update_ref_target_section(mock_secrets_env, mock_metadata_registry):
    """When a recipe entry is a $ref, write to the referenced section."""
    initial_data = {
        "shared_auth": {"accessToken": "old_shared_token"},
        "api_proxy": {"$ref": "shared_auth"},
    }
    save_recipe_secrets_file(initial_data, mock_secrets_env)

    update_recipe_self_secret(
        "api_proxy",
        "accessToken",
        "fresh_shared_val",
        caller_identity="api_proxy",
        secrets_path=mock_secrets_env,
    )

    saved = load_recipe_secrets_file(mock_secrets_env)
    assert saved["shared_auth"]["accessToken"] == "fresh_shared_val"
    assert saved["api_proxy"] == {"$ref": "shared_auth"}


def test_reject_undeclared_secret_key(mock_secrets_env, mock_metadata_registry):
    """Keys not declared in recipe.md secrets whitelist must be rejected."""
    with pytest.raises(RecipeSecretValidationError) as exc:
        update_recipe_self_secret(
            "api_proxy",
            "malicious_unregistered_key",
            "evil_val",
            caller_identity="api_proxy",
            secrets_path=mock_secrets_env,
        )
    assert "未声明 secret" in str(exc.value)


def test_reject_cross_recipe_privilege_escalation(mock_secrets_env, mock_metadata_registry):
    """A recipe must not be allowed to modify another recipe's secret."""
    with pytest.raises(RecipeSecretPermissionError) as exc:
        update_recipe_self_secret(
            "other_recipe",
            "token",
            "stolen_val",
            caller_identity="api_proxy",
            secrets_path=mock_secrets_env,
        )
    assert "越权拒绝" in str(exc.value)
    assert "api_proxy" in str(exc.value)


def test_cli_set_secret_via_stdin_success(mock_secrets_env, mock_metadata_registry, monkeypatch):
    """CLI `frago recipe set-secret` reading token from stdin."""
    runner = CliRunner()
    monkeypatch.setenv("FRAGO_RECIPE_CALLER_NAME", "api_proxy")

    token_secret = "stdin_delivered_token_xyz"
    result = runner.invoke(
        recipe_group,
        ["set-secret", "accessToken", "--format", "json"],
        input=token_secret + "\n",
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["recipe"] == "api_proxy"
    assert data["key"] == "accessToken"
    # Plaintext must not be echoed in output
    assert token_secret not in result.output

    saved = load_recipe_secrets_file(mock_secrets_env)
    assert saved["api_proxy"]["accessToken"] == token_secret


def test_cli_secret_set_alias_success(mock_secrets_env, mock_metadata_registry, monkeypatch):
    """CLI `frago recipe secret set` reading token from stdin."""
    runner = CliRunner()
    monkeypatch.setenv("FRAGO_RECIPE_CALLER_NAME", "api_proxy")

    token_secret = "alias_command_token_abc"
    result = runner.invoke(
        recipe_group,
        ["secret", "set", "refreshToken"],
        input=token_secret,
    )

    assert result.exit_code == 0
    assert "[OK] 已安全更新配方 'api_proxy' 的凭证 'refreshToken'" in result.output
    assert token_secret not in result.output

    saved = load_recipe_secrets_file(mock_secrets_env)
    assert saved["api_proxy"]["refreshToken"] == token_secret


def test_cli_rejection_on_empty_stdin(mock_secrets_env, mock_metadata_registry, monkeypatch):
    """Empty stdin input should be rejected."""
    runner = CliRunner()
    monkeypatch.setenv("FRAGO_RECIPE_CALLER_NAME", "api_proxy")

    result = runner.invoke(
        recipe_group,
        ["set-secret", "accessToken"],
        input="",
    )
    assert result.exit_code != 0
    assert "标准输入内容为空" in result.output


def test_cli_rejection_on_cross_recipe_tampering(mock_secrets_env, mock_metadata_registry, monkeypatch):
    """CLI must reject when --recipe attempts to tamper with another recipe under controlled runtime."""
    runner = CliRunner()
    monkeypatch.setenv("FRAGO_RECIPE_CALLER_NAME", "api_proxy")

    result = runner.invoke(
        recipe_group,
        ["set-secret", "token", "--recipe", "other_recipe"],
        input="some_token",
    )
    assert result.exit_code != 0
    assert "越权拒绝" in result.output


def test_api_proxy_refresh_triggers_persist(monkeypatch):
    """Verify Recipe subclass _persist_secret contract via ask_frago (success & failure paths)."""
    import sys
    from pathlib import Path

    runtime_dir = str(Path(__file__).parents[3] / "src" / "frago" / "recipes" / "runtime")
    if runtime_dir not in sys.path:
        sys.path.insert(0, runtime_dir)

    from frago_recipe import Recipe

    class _DummyRefreshRecipe(Recipe):
        name = "api_proxy"

        def mode_serve(self):
            return {"ok": True}

        def _persist_secret(self, key: str, value: str) -> bool:
            try:
                res = self.ask_frago(["recipe", "set-secret", key], stdin=value)
                if res.get("code") == 0:
                    self.log(f"刷新：凭证 {key} 已受控写回持久化配置")
                    return True
                err_msg = res.get("stderr") or res.get("stdout") or "未知错误"
                self.warn(f"刷新：持久化凭证 {key} 失败（exit={res.get('code')}）：{err_msg.strip()}")
                return False
            except Exception as err:
                self.warn(f"刷新：持久化凭证 {key} 异常：{err}")
                return False

    proxy = _DummyRefreshRecipe()
    proxy.ask_frago = MagicMock(return_value={"code": 0, "stdout": "[OK]", "stderr": ""})
    proxy.log = MagicMock()
    proxy.warn = MagicMock()

    # Success path: delegates to controlled CLI command via stdin
    ok = proxy._persist_secret("accessToken", "fresh_token_123")
    assert ok is True
    proxy.ask_frago.assert_called_once_with(["recipe", "set-secret", "accessToken"], stdin="fresh_token_123")
    proxy.log.assert_called_once()
    proxy.warn.assert_not_called()

    # Non-zero exit code branch: returns False, warns without leaking plaintext token
    proxy.ask_frago = MagicMock(return_value={"code": 1, "stdout": "", "stderr": "越权拒绝"})
    proxy.log = MagicMock()
    proxy.warn = MagicMock()
    failed = proxy._persist_secret("refreshToken", "super_secret_refresh_999")
    assert failed is False
    proxy.ask_frago.assert_called_once_with(
        ["recipe", "set-secret", "refreshToken"], stdin="super_secret_refresh_999"
    )
    proxy.log.assert_not_called()
    proxy.warn.assert_called_once()
    assert "super_secret_refresh_999" not in proxy.warn.call_args[0][0]

    # Exception branch: catches and warns cleanly
    proxy.ask_frago = MagicMock(side_effect=RuntimeError("bus unavailable"))
    proxy.warn = MagicMock()
    errored = proxy._persist_secret("accessToken", "secret_val_err")
    assert errored is False
    proxy.warn.assert_called_once()
    assert "secret_val_err" not in proxy.warn.call_args[0][0]
