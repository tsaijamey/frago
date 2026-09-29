"""CLI tests for `frago apps` — built-in delivery capabilities.

渲染链路（frago browser 扩展桥）不在单测里真起浏览器：那是集成测试。
单测覆盖 registry 逻辑、命令解析、dispatch 与错误路径，渲染函数 mock 隔离。
"""

import json

import click
import pytest
from click.testing import CliRunner

from frago.cli import apps_commands
from frago.cli.apps_commands import (
    APPS_GROUP,
    _list_apps,
    _render_mermaid,
    apps_group,
)


@pytest.fixture
def runner():
    return CliRunner()


# ── registry ─────────────────────────────────────────────────────────

def test_list_apps_contains_mermaid():
    apps = _list_apps()
    names = [a.name for a in apps]
    assert "mermaid" in names
    mermaid = apps[names.index("mermaid")]
    assert mermaid.input_kind == "mermaid 文本"
    assert mermaid.output_kind == "SVG"
    assert callable(mermaid.render)


def test_mermaid_render_is_builtin_function():
    # render 是 registry 直接持有的可调用，use 拿到即可调，无第二入口。
    assert callable(_render_mermaid)


# ── command: list ────────────────────────────────────────────────────

def test_apps_list_table(runner):
    res = runner.invoke(apps_group, ["list"])
    assert res.exit_code == 0, res.output
    assert "mermaid" in res.output
    assert "SVG" in res.output


def test_apps_list_json(runner):
    res = runner.invoke(apps_group, ["list", "--format", "json"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert isinstance(data, list)
    assert any(app["name"] == "mermaid" for app in data)


# ── command: use ─────────────────────────────────────────────────────

def test_apps_use_unknown_app_errors(runner):
    res = runner.invoke(apps_group, ["use", "nope", "input"])
    assert res.exit_code == 2
    assert "unknown app" in res.output.lower()


@pytest.fixture
def fake_mermaid_render(monkeypatch):
    """把 registry 里 mermaid 的 render 换成桩，隔离真实浏览器渲染。

    ``apps use`` 调的是 registry 持有的 app.render 引用，不是模块函数，
    所以 patch 目标是 _APPS["mermaid"].render。
    """
    calls = []

    def fake(text):
        calls.append(text)
        return f"<svg>{text}</svg>"

    monkeypatch.setattr(apps_commands._APPS["mermaid"], "render", fake)
    return calls


def test_apps_use_renders_to_stdout(runner, fake_mermaid_render):
    res = runner.invoke(apps_group, ["use", "mermaid", "A --> B"])
    assert res.exit_code == 0, res.output
    assert "<svg>A --> B</svg>" in res.output
    assert fake_mermaid_render == ["A --> B"]


def test_apps_use_writes_output_file(runner, tmp_path, fake_mermaid_render):  # noqa: ARG001
    out = tmp_path / "out.svg"
    res = runner.invoke(apps_group, ["use", "mermaid", "--output", str(out), "A --> B"])
    assert res.exit_code == 0, res.output
    assert out.read_text(encoding="utf-8") == "<svg>A --> B</svg>"
    assert "Wrote" in res.output


def test_apps_use_passes_through_render_failure(runner, monkeypatch):
    def boom(_text):
        raise RuntimeError("boom")
    monkeypatch.setattr(apps_commands._APPS["mermaid"], "render", boom)
    res = runner.invoke(apps_group, ["use", "mermaid", "bad"])
    assert res.exit_code != 0


# ── render 单元：HTML 拼装与 SVG 提取 ───────────────────────────────

def test_mermaid_asset_is_readable():
    asset = apps_commands._mermaid_asset()
    assert "mermaid" in asset.lower()
    assert len(asset) > 1000


class _Result:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def test_extract_exec_result_parses_value():
    res = _Result(stdout='{\n  "value": "<svg>xyz</svg>"\n}\n')
    assert apps_commands._extract_exec_result(res) == "<svg>xyz</svg>"


def test_extract_exec_result_null_value_returns_none():
    assert apps_commands._extract_exec_result(_Result(stdout='{"value": null}')) is None


def test_extract_exec_result_failure_returns_none():
    assert apps_commands._extract_exec_result(_Result(returncode=1, stdout="error\n")) is None


def test_extract_exec_result_non_json_returns_none():
    assert apps_commands._extract_exec_result(_Result(stdout="Execution result: x")) is None


# ── 浏览器后端：走默认扩展桥，不碰 -b cdp / 9222 ──────────────────────

def test_browser_command_uses_default_backend():
    cmd = apps_commands._browser_command("navigate", "file:///x")
    assert cmd == ["frago", "browser", "navigate", "file:///x"]
    assert "-b" not in cmd and "cdp" not in cmd


def test_ensure_browser_up_skips_start_when_bridge_connected(monkeypatch):
    calls = []

    def fake_run(*args):
        calls.append(args)
        return _Result(stdout='{"backend": "extension", "ok": true}')

    monkeypatch.setattr(apps_commands, "_run_browser", fake_run)
    apps_commands._ensure_browser_up()
    assert calls == [("status",)]


def test_ensure_browser_up_starts_bridge_when_disconnected(monkeypatch):
    calls = []

    def fake_run(*args):
        calls.append(args)
        if args == ("status",):
            return _Result(returncode=1, stdout='{"ok": false}')
        return _Result()

    monkeypatch.setattr(apps_commands, "_run_browser", fake_run)
    apps_commands._ensure_browser_up()
    assert calls == [("status",), ("start",)]


def test_ensure_browser_up_raises_when_start_fails(monkeypatch):
    def fake_run(*args):
        return _Result(returncode=1, stdout='{"ok": false}')

    monkeypatch.setattr(apps_commands, "_run_browser", fake_run)
    with pytest.raises(click.ClickException):
        apps_commands._ensure_browser_up()


def test_apps_group_uses_agent_friendly_group():
    # 命令族必须走 AgentFriendly 三层机制（错误提示 + 用法示例）。
    assert apps_group.__class__.__name__ == "AgentFriendlyGroup"


def test_render_uses_dedicated_group():
    # 渲染固定用独立 group，不碰用户 group。
    assert APPS_GROUP == "frago-apps"
