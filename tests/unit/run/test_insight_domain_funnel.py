"""Spec 20260529-domain-routing-funnel-gap Phase 2.

insights 落域入口接 canonical 漏斗：显式 --domain 先过 lookup_domain，
alias 命中收敛到 canonical、未命中 slug 建新域。复用既有 lookup_domain，
不新建抽象、不碰 run init。
"""

from __future__ import annotations

from frago.cli import run_commands


def test_explicit_domain_alias_snaps_to_canonical(monkeypatch):
    """alias（如 etf-research）命中 → 收敛到 canonical，不 fork 近义新域。"""
    monkeypatch.setattr(run_commands, "lookup_domain", lambda _t: "quant-trading")
    assert run_commands._resolve_insight_domain("etf-research") == "quant-trading"


def test_explicit_domain_no_hit_falls_back_to_slug(monkeypatch):
    """未命中字典 → slug 建新域，保留显式声明新主题的意图。"""
    monkeypatch.setattr(run_commands, "lookup_domain", lambda _t: None)
    assert run_commands._resolve_insight_domain("Brand New Topic") == "brand-new-topic"


def test_explicit_canonical_name_is_idempotent(monkeypatch):
    """显式给 canonical 名本身 → 原样返回，无并入提示。"""
    monkeypatch.setattr(run_commands, "lookup_domain", lambda _t: "twitter")
    assert run_commands._resolve_insight_domain("twitter") == "twitter"


def test_alias_merge_emits_stderr_hint(monkeypatch, capsys):
    """命中且 canonical 与原名不同 → stderr 提示将并入。"""
    monkeypatch.setattr(run_commands, "lookup_domain", lambda _t: "quant-trading")
    run_commands._resolve_insight_domain("etf-research")
    err = capsys.readouterr().err
    assert "quant-trading" in err
    assert "并入" in err


def test_canonical_match_no_hint(monkeypatch, capsys):
    """命中即 canonical 本身 → 不应有并入提示。"""
    monkeypatch.setattr(run_commands, "lookup_domain", lambda _t: "twitter")
    run_commands._resolve_insight_domain("twitter")
    assert "并入" not in capsys.readouterr().err
