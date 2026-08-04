"""Tests for opencode plugin deployment."""

import json
from pathlib import Path

import pytest

from frago.init import opencode_plugin
from frago.init.opencode_plugin import (
    PLUGIN_FILENAME,
    PLUGIN_FILES,
    TOOL_NAME_MAP_FILENAME,
    VISION_CONTEXT_FILENAME,
    deploy_opencode_plugin,
    get_bundled_plugin_path,
    get_tool_name_map,
    is_opencode_present,
)


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Redirect Path.home() so deployment writes into a temp tree."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def test_bundled_plugin_is_packaged():
    """The plugin resource must ship with the package."""
    src = get_bundled_plugin_path()
    assert src.exists()
    assert src.read_text(encoding="utf-8").strip()


def test_bundled_plugin_registers_expected_hooks():
    """Guard the opencode -> Claude Code event mapping against silent drift."""
    body = get_bundled_plugin_path().read_text(encoding="utf-8")
    for hook in ("chat.message", "tool.execute.before", "tool.execute.after"):
        assert f'"{hook}"' in body
    for event in ("SessionStart", "UserPromptSubmit", "PreToolUse"):
        assert event in body


def test_bundled_plugin_translates_tool_shape():
    """opencode's lowercase tool names and camelCase args must be normalised.

    The routing rules are written against the Claude Code shape; without this
    translation every tool-name and path rule silently stops matching.
    """
    body = get_bundled_plugin_path().read_text(encoding="utf-8")
    # The table is loaded from the shared file, never inlined — `frago
    # hook-rules add` normalises against the same one.
    assert TOOL_NAME_MAP_FILENAME in body
    assert 'bash: "Bash"' not in body
    assert "filePath" in body
    assert "file_path" in body


def test_tool_name_map_covers_the_core_tools():
    mapping = get_tool_name_map()
    assert mapping["bash"] == "Bash"
    assert mapping["read"] == "Read"
    assert mapping["write"] == "Write"
    assert mapping["edit"] == "Edit"
    # Tools whose names differ by more than case — the reason a plain
    # case-insensitive comparison would not have been enough.
    assert mapping["list"] == "LS"
    assert mapping["webfetch"] == "WebFetch"


def test_vision_config_ships_with_usable_defaults():
    """The image-reading feature is configured entirely from this file."""
    cfg = json.loads(get_bundled_plugin_path(VISION_CONTEXT_FILENAME).read_text(encoding="utf-8"))
    assert cfg["enabled"] is True
    assert cfg["recipe"] == "openrouter_vision_classify"
    assert cfg["prompt"].strip()
    # The gate is what keeps the spend narrow: models that can already see an
    # image must not pay for a second model to describe it.
    assert "deepseek" in cfg["model_gate"]
    assert cfg["timeout_ms"] >= 20_000


def test_bundled_plugin_reads_images_through_the_recipe():
    """The vision call goes through frago's recipe layer, not a raw endpoint.

    Credentials, model defaults and retry policy live in the recipe; a direct
    HTTP call from the bridge would fork all three.
    """
    body = get_bundled_plugin_path().read_text(encoding="utf-8")
    assert VISION_CONTEXT_FILENAME in body
    assert '"recipe", "run"' in body
    assert "openrouter.ai" not in body
    assert "api_key" not in body


def test_user_edits_to_vision_config_survive_redeploy(fake_home, monkeypatch):
    """Turning the feature off must not be undone by the next server start."""
    monkeypatch.setattr(opencode_plugin.shutil, "which", lambda _: "/usr/local/bin/opencode")
    deploy_opencode_plugin()
    dst = fake_home / ".config" / "opencode" / "plugin" / VISION_CONTEXT_FILENAME
    dst.write_text(json.dumps({"enabled": False}), encoding="utf-8")

    deploy_opencode_plugin()

    assert json.loads(dst.read_text(encoding="utf-8"))["enabled"] is False

    # force is the deliberate way back to the shipped defaults.
    deploy_opencode_plugin(force=True)
    assert json.loads(dst.read_text(encoding="utf-8"))["enabled"] is True


def test_both_plugin_files_are_deployed(fake_home, monkeypatch):
    """The plugin reads the map from its own directory — both must land."""
    monkeypatch.setattr(opencode_plugin.shutil, "which", lambda _: "/usr/local/bin/opencode")

    deploy_opencode_plugin()

    plugin_dir = fake_home / ".config" / "opencode" / "plugin"
    for filename in PLUGIN_FILES:
        assert (plugin_dir / filename).exists()


def test_skips_when_opencode_absent(fake_home, monkeypatch):
    """No opencode, no config tree — deployment must not invent one."""
    monkeypatch.setattr(opencode_plugin.shutil, "which", lambda _: None)

    assert is_opencode_present() is False
    assert deploy_opencode_plugin() is None
    assert not (fake_home / ".config" / "opencode").exists()


def test_deploys_when_opencode_on_path(fake_home, monkeypatch):
    monkeypatch.setattr(opencode_plugin.shutil, "which", lambda _: "/usr/local/bin/opencode")

    dst = deploy_opencode_plugin()

    assert dst == fake_home / ".config" / "opencode" / "plugin" / PLUGIN_FILENAME
    assert dst.read_text(encoding="utf-8") == get_bundled_plugin_path().read_text(
        encoding="utf-8"
    )


def test_deploys_when_config_dir_exists(fake_home, monkeypatch):
    """A config dir alone is enough — opencode need not be on PATH."""
    monkeypatch.setattr(opencode_plugin.shutil, "which", lambda _: None)
    (fake_home / ".config" / "opencode").mkdir(parents=True)

    assert is_opencode_present() is True
    assert deploy_opencode_plugin() is not None


@pytest.mark.usefixtures("fake_home")
def test_redeploy_is_idempotent(monkeypatch):
    """An unchanged plugin must not be rewritten on every server start."""
    monkeypatch.setattr(opencode_plugin.shutil, "which", lambda _: "/usr/local/bin/opencode")

    first = deploy_opencode_plugin()
    stamp = first.stat().st_mtime_ns

    second = deploy_opencode_plugin()

    assert second == first
    assert second.stat().st_mtime_ns == stamp


@pytest.mark.usefixtures("fake_home")
def test_stale_plugin_is_refreshed(monkeypatch):
    """A drifted deployed copy gets overwritten with the packaged version."""
    monkeypatch.setattr(opencode_plugin.shutil, "which", lambda _: "/usr/local/bin/opencode")

    dst = deploy_opencode_plugin()
    dst.write_text("// stale", encoding="utf-8")

    deploy_opencode_plugin()

    assert dst.read_text(encoding="utf-8") == get_bundled_plugin_path().read_text(
        encoding="utf-8"
    )
