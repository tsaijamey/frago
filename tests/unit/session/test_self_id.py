"""「我是谁」的解析规则（frago session self）。

盯三件事：显式声明压过一切；没有声明时只肯给一个标着「推断」的结果；连推断的依据
都没有时老老实实说不知道——NEVER 编一个会话 id 出来。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from frago.session.monitor import encode_project_path
from frago.session.self_id import resolve_self


def _transcript(root: Path, cwd: str, sid: str, age_s: float = 0.0) -> Path:
    proj = root / encode_project_path(cwd)
    proj.mkdir(parents=True, exist_ok=True)
    path = proj / f"{sid}.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    if age_s:
        stamp = time.time() - age_s
        os.utime(path, (stamp, stamp))
    return path


def test_explicit_declaration_wins(tmp_path):
    found = resolve_self(
        cwd="/work/repo",
        projects_root=tmp_path,
        env={"FRAGO_SESSION_ID": "declared", "CLAUDE_CODE_SESSION_ID": "claude-one"},
    )
    assert found is not None
    assert found.session_id == "declared"
    assert found.source == "env:FRAGO_SESSION_ID"
    assert found.certain is True


def test_claude_env_is_matched_with_its_transcript(tmp_path):
    path = _transcript(tmp_path, "/work/repo", "claude-one")
    found = resolve_self(
        cwd="/work/repo",
        projects_root=tmp_path,
        env={"CLAUDE_CODE_SESSION_ID": "claude-one"},
    )
    assert found is not None
    assert found.session_id == "claude-one"
    assert found.certain is True
    assert found.agent == "claude"
    assert found.transcript == str(path)
    assert found.resume_command == "claude --resume claude-one"


def test_declared_id_without_transcript_still_reported(tmp_path):
    found = resolve_self(cwd="/work/repo", projects_root=tmp_path, env={"FRAGO_SESSION_ID": "x"})
    assert found is not None
    assert found.session_id == "x"
    assert found.transcript is None
    assert found.agent == "unknown"
    assert found.note  # 说明记录没找到，但 id 本身仍算数


def test_fallback_picks_freshest_and_admits_it_is_a_guess(tmp_path):
    _transcript(tmp_path, "/work/repo", "older", age_s=120)
    _transcript(tmp_path, "/work/repo", "newest")
    found = resolve_self(cwd="/work/repo", projects_root=tmp_path, env={})
    assert found is not None
    assert found.session_id == "newest"
    assert found.source == "transcript-mtime"
    assert found.certain is False
    # 同一目录下还有一份同样新鲜的记录，note 必须把「可能挑错」说出来
    assert "可能挑错" in (found.note or "")


def test_stale_transcripts_are_not_this_session(tmp_path):
    _transcript(tmp_path, "/work/repo", "yesterday", age_s=86400)
    assert resolve_self(cwd="/work/repo", projects_root=tmp_path, env={}) is None


def test_no_evidence_at_all_returns_none(tmp_path):
    assert resolve_self(cwd="/work/elsewhere", projects_root=tmp_path, env={}) is None
