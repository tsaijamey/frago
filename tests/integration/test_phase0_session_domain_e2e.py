"""Spec 20260529-domain-routing-funnel-gap Phase 0 — 集成（档2）.

驱动真实的 `sync_session` 生产函数，验证 executor 在 spawn 时写的 csid→domain sidecar
能让 daemon 侧 sync 把 session 的 metadata.domain 落成真实域，而非恒 misc。

隔离：storage 认 FRAGO_PROJECTS_DIR / FRAGO_SESSION_DIR 环境变量（storage.py:47/58），
setenv 到 tmp 即可让 RunManager(sidecar) 与 storage 读写全部落临时目录，不碰真实 ~/.frago。
"""

from __future__ import annotations

import json

import pytest

from frago.run.manager import RunManager
from frago.session.models import AgentType
from frago.session.storage import read_metadata
from frago.session.sync import sync_session


def _write_session_jsonl(path, csid):
    """造一个最小但合法的 Claude session jsonl（形态同 fixtures/valid_session.jsonl）。"""
    rows = [
        {"type": "user", "uuid": "m1", "sessionId": csid,
         "timestamp": "2026-05-30T10:00:00Z", "message": {"content": "帮我看看 twitter 上的动态"}},
        {"type": "assistant", "uuid": "m2", "sessionId": csid,
         "timestamp": "2026-05-30T10:00:05Z", "message": {"content": "好的"}},
        {"type": "user", "uuid": "m3", "sessionId": csid,
         "timestamp": "2026-05-30T10:00:30Z", "message": {"content": "继续"}},
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")


@pytest.fixture
def isolated_frago(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    sessions = tmp_path / "sessions"
    projects.mkdir()
    monkeypatch.setenv("FRAGO_PROJECTS_DIR", str(projects))
    monkeypatch.setenv("FRAGO_SESSION_DIR", str(sessions))
    monkeypatch.delenv("FRAGO_DOMAIN", raising=False)
    return projects


def test_synced_session_carries_recorded_real_domain(isolated_frago, tmp_path):
    """executor 记过 csid→twitter 后，sync 落盘的 metadata.domain 应为 twitter（非 misc）。"""
    projects = isolated_frago
    csid = "test-csid-phase0-real"

    # 模拟 executor 在 _launch_agent 起 sub-agent 时写的 sidecar
    RunManager(projects).record_session_domain(csid, "twitter")

    jsonl = tmp_path / f"{csid}.jsonl"
    _write_session_jsonl(jsonl, csid)

    # 真实生产函数
    result = sync_session(jsonl, project_path="/tmp/some-project")
    assert result == csid

    meta = read_metadata(csid, AgentType.CLAUDE)
    assert meta is not None, "metadata 未写出"
    assert meta.domain == "twitter", f"期望真实域 twitter，实得 {meta.domain!r}"
    # 落盘位置也应在 projects/twitter/<csid>/ 下
    assert (projects / "twitter" / csid / "metadata.json").exists()


@pytest.mark.usefixtures("isolated_frago")
def test_synced_session_without_record_falls_back_to_misc(tmp_path):
    """没有 sidecar 记录（交互式/历史 session）时，维持原兜底 misc，不误塞域。"""
    csid = "test-csid-phase0-none"
    jsonl = tmp_path / f"{csid}.jsonl"
    _write_session_jsonl(jsonl, csid)

    result = sync_session(jsonl, project_path="/tmp/some-project")
    assert result == csid

    meta = read_metadata(csid, AgentType.CLAUDE)
    assert meta is not None
    assert meta.domain == "misc", f"无记录时应兜底 misc，实得 {meta.domain!r}"


def test_synthetic_resume_domain_is_ignored(isolated_frago, tmp_path):
    """sidecar 里若是 resume-/misc 脏域，视为无真实域，仍兜底 misc（防脏域繁殖）。"""
    projects = isolated_frago
    csid = "test-csid-phase0-dirty"
    RunManager(projects).record_session_domain(csid, "resume-deadbeef0000")

    jsonl = tmp_path / f"{csid}.jsonl"
    _write_session_jsonl(jsonl, csid)

    sync_session(jsonl, project_path="/tmp/some-project")
    meta = read_metadata(csid, AgentType.CLAUDE)
    assert meta is not None
    assert meta.domain == "misc", f"脏域应被忽略并兜底 misc，实得 {meta.domain!r}"
