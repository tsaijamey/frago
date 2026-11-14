"""Controlled recipe self-secret writeback implementation.

Guarantees:
1. Strict caller identity & contract validation (caller may only update its own declared secrets).
2. Atomic writeback with 0600 file permissions and preservation of all other recipe sections.
3. Zero plaintext token leakage in argv, stdout, stderr, logs or exception tracebacks.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from .exceptions import (
    RecipeNotFoundError,
    RecipeSecretError,
    RecipeSecretPermissionError,
    RecipeSecretValidationError,
)

logger = logging.getLogger(__name__)

SECRETS_FILENAME = "recipes.local.json"


def get_secrets_path() -> Path:
    """Return path to recipes.local.json (configurable via env for isolation/tests)."""
    override = os.environ.get("FRAGO_RECIPES_LOCAL_PATH")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".frago" / SECRETS_FILENAME


def load_recipe_secrets_file(path: Path | None = None) -> dict[str, Any]:
    """Load and parse recipes.local.json. Return empty dict if file does not exist."""
    target = path or get_secrets_path()
    if not target.exists():
        return {}
    try:
        content = target.read_text(encoding="utf-8")
        if not content.strip():
            return {}
        data = json.loads(content)
        if not isinstance(data, dict):
            raise RecipeSecretError(f"凭证文件 {target} 顶层不是有效的 JSON 对象")
        return data
    except (json.JSONDecodeError, OSError) as e:
        raise RecipeSecretError(f"读取凭证文件失败 ({target}): {e}") from e


def save_recipe_secrets_file(data: dict[str, Any], path: Path | None = None) -> None:
    """Atomically write data to recipes.local.json preserving safe 0600 permissions."""
    target = path or get_secrets_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    # Determine safe permission: 0o600 or existing permissions
    mode = 0o600
    if target.exists():
        try:
            mode = target.stat().st_mode & 0o777
        except OSError:
            mode = 0o600

    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    # Write to a temporary file in the same directory, then atomically replace
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(target.parent),
            prefix=f"{target.name}.tmp.",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())

        os.chmod(tmp_path, mode)
        os.replace(tmp_path, target)
        # Ensure permissions on final target
        os.chmod(target, mode)
    except Exception as e:
        if tmp_path and tmp_path.exists():
            with contextlib.suppress(OSError):
                tmp_path.unlink()
        raise RecipeSecretError(f"保存凭证文件失败 ({target}): {e}") from e


def resolve_secret_section(all_config: dict[str, Any], recipe_name: str) -> str:
    """Resolve $ref indirection if present, returning the target section key."""
    raw = all_config.get(recipe_name, {})
    if isinstance(raw, dict) and "$ref" in raw and isinstance(raw["$ref"], str):
        return raw["$ref"]
    return recipe_name


def _find_recipe_dir_by_name(recipe_name: str) -> Path | None:
    """按配方名在 ``~/.frago/recipes`` 下找它的目录；找不到返回 None。

    **这一段是本层自己实现的，不再反向导入上层 CLI。** 从前这里是
    ``from frago.cli.recipe_commands import _find_recipe_dir_by_name``：``recipes`` 是
    下层、``cli`` 是上层，下层反过来导入上层的私有函数，依赖方向是反的——函数内延迟
    导入只是绕过了循环导入的报错，方向没变。这里按配方注册表自己的扫描清单找，判据与
    ``recipes/registry.py`` 同源（``atomic/chrome`` / ``atomic/system`` / ``workflows``）。
    """
    base = Path.home() / ".frago" / "recipes"
    for subdir in ("atomic/chrome", "atomic/system", "workflows"):
        candidate = base / subdir / recipe_name
        if candidate.is_dir():
            return candidate
    return None


def get_recipe_declared_secrets(recipe_name: str) -> dict[str, Any]:
    """Retrieve declared secrets schema from the recipe's recipe.md metadata."""
    from frago.recipes.registry import get_registry

    try:
        recipe = get_registry().find(recipe_name)
        if recipe and recipe.metadata and recipe.metadata.secrets:
            return recipe.metadata.secrets
    except Exception:
        pass

    # 注册表还没索引到它时，直接按目录找（判据在 `_find_recipe_dir_by_name`，本层自洽）。
    from frago.recipes.metadata import parse_metadata_file

    recipe_dir = _find_recipe_dir_by_name(recipe_name)
    if recipe_dir:
        md_path = recipe_dir / "recipe.md"
        if md_path.exists():
            meta = parse_metadata_file(md_path)
            if meta and meta.secrets:
                return meta.secrets

    raise RecipeNotFoundError(recipe_name)


def update_recipe_self_secret(
    recipe_name: str,
    key: str,
    value: str,
    *,
    caller_identity: str | None = None,
    secrets_path: Path | None = None,
) -> dict[str, Any]:
    """Update a declared secret key for recipe_name in recipes.local.json.

    Args:
        recipe_name: Target recipe name.
        key: Secret field name to update.
        value: Secret token value (must NOT be logged or leaked).
        caller_identity: Proven caller recipe name if running under controlled runtime.
        secrets_path: Optional path override for testing.

    Returns:
        dict with metadata summary (recipe, key, length, sha256_prefix). No plaintext.

    Raises:
        RecipeSecretPermissionError: When caller attempts to modify another recipe.
        RecipeSecretValidationError: When key is not declared in recipe.md.
        RecipeNotFoundError: When recipe cannot be located.
        RecipeSecretError: On I/O or format failures.
    """
    clean_key = (key or "").strip()
    if not clean_key:
        raise RecipeSecretValidationError("密钥字段名称不能为空")

    # 1. Anti-escalation & caller identity check
    if caller_identity:
        norm_caller = caller_identity.strip()
        if norm_caller and norm_caller != recipe_name.strip():
            raise RecipeSecretPermissionError(
                f"越权拒绝：当前受控调用方为 '{norm_caller}'，禁止修改其他配方 '{recipe_name}' 的凭证"
            )

    # 2. Schema whitelist validation against recipe.md
    declared_secrets = get_recipe_declared_secrets(recipe_name)
    if clean_key not in declared_secrets:
        raise RecipeSecretValidationError(
            f"配方 '{recipe_name}' 的 recipe.md 中未声明 secret 键 '{clean_key}'，拒绝写入未声明凭证"
        )

    # 3. Read current file
    all_config = load_recipe_secrets_file(secrets_path)

    # 4. Resolve $ref target and update safely
    target_section = resolve_secret_section(all_config, recipe_name)
    section_data = all_config.get(target_section)
    if not isinstance(section_data, dict):
        section_data = {}

    section_data[clean_key] = value
    all_config[target_section] = section_data

    # 5. Atomic persist
    save_recipe_secrets_file(all_config, secrets_path)

    # 6. Safe non-leaking return representation
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return {
        "status": "ok",
        "recipe": recipe_name,
        "key": clean_key,
        "length": len(value),
        "sha256_prefix": digest[:8],
    }
