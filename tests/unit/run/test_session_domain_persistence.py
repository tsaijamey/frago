"""Spec 20260529-domain-routing-funnel-gap Phase 0.

session->domain 落盘链路：executor 在 spawn 时把 csid->真实域记入 sidecar，
daemon 侧 sync 经 resolve_domain_for_session 按 csid 读回，不再恒落 misc。
"""

from __future__ import annotations

from frago.run.manager import RunManager


def test_record_then_resolve_by_csid(tmp_path, monkeypatch):
    monkeypatch.delenv("FRAGO_DOMAIN", raising=False)
    mgr = RunManager(tmp_path / "projects")
    mgr.record_session_domain("csid-abc", "twitter")
    assert mgr.lookup_session_domain("csid-abc") == "twitter"
    # sync 走 resolve_domain_for_session(session_id=csid) → 拿到真实域而非 misc
    assert mgr.resolve_domain_for_session("csid-abc", "/some/path") == "twitter"


def test_lookup_none_for_synthetic_or_missing(tmp_path):
    mgr = RunManager(tmp_path / "projects")
    assert mgr.lookup_session_domain("missing-csid") is None
    mgr.record_session_domain("c-misc", "misc")
    assert mgr.lookup_session_domain("c-misc") is None  # 兜底域不算真实域
    mgr.record_session_domain("c-resume", "resume-deadbeef0000")
    assert mgr.lookup_session_domain("c-resume") is None  # 合成 id 不算真实域


def test_resolve_falls_through_to_misc_without_record(tmp_path, monkeypatch):
    monkeypatch.delenv("FRAGO_DOMAIN", raising=False)
    mgr = RunManager(tmp_path / "projects")
    # 无 sidecar 记录、无 env、无 current_run → 维持原兜底 misc（交互式/历史 session）
    assert mgr.resolve_domain_for_session("unknown-csid", "/p") == "misc"


def test_record_is_noop_on_empty(tmp_path):
    mgr = RunManager(tmp_path / "projects")
    mgr.record_session_domain("", "twitter")
    mgr.record_session_domain("csid", "")
    assert mgr.lookup_session_domain("") is None
    assert mgr.lookup_session_domain("csid") is None
