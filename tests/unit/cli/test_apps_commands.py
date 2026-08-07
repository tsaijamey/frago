"""CLI tests for `frago apps` — built-in delivery capabilities.

渲染链路（frago browser -b cdp 无头）不在单测里真起浏览器：那是集成测试。
单测覆盖 registry 逻辑、命令解析、dispatch 与错误路径，渲染函数 mock 隔离。
"""

import json

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


def test_extract_exec_result_parses_value():
    class FakeResult:
        returncode = 0
        stdout = "2026-08-07, success, Execution result: <svg>xyz</svg>\n" \
                 "2026-08-07, success, Page title: x\n"

    assert apps_commands._extract_exec_result(FakeResult()) == "<svg>xyz</svg>"


def test_extract_exec_result_none_value_returns_none():
    class FakeResult:
        returncode = 0
        stdout = "2026-08-07, success, Execution result: None\n"

    assert apps_commands._extract_exec_result(FakeResult()) is None


def test_extract_exec_result_failure_returns_none():
    class FakeResult:
        returncode = 1
        stdout = "error\n"

    assert apps_commands._extract_exec_result(FakeResult()) is None


def test_apps_group_uses_agent_friendly_group():
    # 命令族必须走 AgentFriendly 三层机制（错误提示 + 用法示例）。
    assert apps_group.__class__.__name__ == "AgentFriendlyGroup"


def test_render_uses_dedicated_group():
    # 渲染固定用独立 group，不碰用户 group。
    assert APPS_GROUP == "frago-apps"
