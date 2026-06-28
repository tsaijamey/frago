"""Phase 8（spec 20260627 交付即核心）：conv outbox 落盘原语 + attach 自解析 conv_key。

覆盖：append 登记进以 conv_key 为键的 outbox、drain 读取并清空、文件按扩展名分
image/file、attach 命令从 FRAGO_CONV_KEY env 自解析 conv_key 并登记。
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from frago.server.services import pa_outbox


@pytest.fixture(autouse=True)
def _isolate_outbox(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAGO_OUTBOX_DIR", str(tmp_path / "outbox"))


def test_append_then_drain_roundtrip(tmp_path):
    f = tmp_path / "report.md"
    f.write_text("hi", encoding="utf-8")
    conv = "feishu:oc_abc"

    recs = pa_outbox.append(conv, files=[str(f)])
    assert len(recs) == 1
    assert recs[0]["kind"] == "file"
    assert recs[0]["conv_key"] == conv

    drained = pa_outbox.drain(conv)
    assert len(drained) == 1
    assert drained[0]["path"] == str(f.resolve())
    # drain 后清空：再 drain 返回空。
    assert pa_outbox.drain(conv) == []


def test_image_extension_classified_as_image(tmp_path):
    img = tmp_path / "chart.PNG"
    img.write_text("x", encoding="utf-8")
    recs = pa_outbox.append("voice:u1", files=[str(img)])
    assert recs[0]["kind"] == "image"


def test_dirs_registered_as_dir(tmp_path):
    d = tmp_path / "build"
    d.mkdir()
    recs = pa_outbox.append("feishu:oc_x", dirs=[str(d)])
    assert recs[0]["kind"] == "dir"
    assert recs[0]["path"] == str(d.resolve())


def test_append_is_additive(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("a", encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text("b", encoding="utf-8")
    conv = "feishu:oc_add"
    pa_outbox.append(conv, files=[str(a)])
    pa_outbox.append(conv, files=[str(b)])
    drained = pa_outbox.drain(conv)
    assert {r["path"] for r in drained} == {str(a.resolve()), str(b.resolve())}


def test_drain_missing_conv_returns_empty():
    assert pa_outbox.drain("feishu:nonexistent") == []


def test_keys_isolated_per_conv(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("a", encoding="utf-8")
    pa_outbox.append("feishu:c1", files=[str(a)])
    assert pa_outbox.drain("feishu:c2") == []
    assert len(pa_outbox.drain("feishu:c1")) == 1


# ── frago agent attach 命令 ────────────────────────────────────────
def test_attach_command_self_resolves_conv_key_from_env(tmp_path, monkeypatch):
    from frago.cli.agent_command import agent

    f = tmp_path / "out.md"
    f.write_text("done", encoding="utf-8")
    monkeypatch.setenv("FRAGO_CONV_KEY", "feishu:oc_env")

    result = CliRunner().invoke(
        agent, ["attach", "--files", json.dumps([str(f)])]
    )
    assert result.exit_code == 0, result.output
    drained = pa_outbox.drain("feishu:oc_env")
    assert len(drained) == 1
    assert drained[0]["path"] == str(f.resolve())


def test_attach_command_conv_key_override(tmp_path, monkeypatch):
    from frago.cli.agent_command import agent

    f = tmp_path / "out.md"
    f.write_text("done", encoding="utf-8")
    monkeypatch.delenv("FRAGO_CONV_KEY", raising=False)

    result = CliRunner().invoke(
        agent,
        ["attach", "--files", json.dumps([str(f)]), "--conv-key", "feishu:oc_ovr"],
    )
    assert result.exit_code == 0, result.output
    assert len(pa_outbox.drain("feishu:oc_ovr")) == 1


def test_attach_command_errors_without_conv_key(tmp_path, monkeypatch):
    from frago.cli.agent_command import agent

    f = tmp_path / "out.md"
    f.write_text("done", encoding="utf-8")
    monkeypatch.delenv("FRAGO_CONV_KEY", raising=False)

    result = CliRunner().invoke(agent, ["attach", "--files", json.dumps([str(f)])])
    assert result.exit_code == 1
    assert "conv_key" in result.output


def test_attach_command_rejects_bad_json(monkeypatch):
    from frago.cli.agent_command import agent

    monkeypatch.setenv("FRAGO_CONV_KEY", "feishu:oc_env")
    result = CliRunner().invoke(agent, ["attach", "--files", "not-json"])
    assert result.exit_code == 1
    assert "JSON array" in result.output
