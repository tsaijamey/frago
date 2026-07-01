"""Contract tests for the resume_inbox writer half.

NOTE: as of this commit `grep -rn "ResumeInbox|resume_inbox|ResumeInjection"`
finds no Python or Rust importer of this module — the documented Rust reader
``frago-core/src/resume_inbox.rs`` does not exist in the tree. These tests pin
the current public contract so the module's behaviour is locked while the
keep-or-delete decision is pending.
"""
from __future__ import annotations

import json

import pytest

from frago.server.services import resume_inbox as ri
from frago.server.services.resume_inbox import (
    PENDING_DIR_NAME,
    SCHEMA_VERSION,
    ResumeInbox,
    ResumeInjection,
)


@pytest.fixture
def projects_root(tmp_path, monkeypatch):
    """Redirect the module-level PROJECTS_DIR at tmp_path."""
    root = tmp_path / "projects"
    monkeypatch.setattr(ri, "PROJECTS_DIR", root)
    return root


def test_append_returns_record_with_expected_fields(projects_root):
    inj = ResumeInbox.append(
        run_id="run1",
        claude_session_id="csid1",
        task_id="task1",
        prompt="hello",
    )
    assert isinstance(inj, ResumeInjection)
    assert inj.claude_session_id == "csid1"
    assert inj.task_id == "task1"
    assert inj.prompt == "hello"
    assert inj.pa_thread_id is None
    assert inj.schema_version == SCHEMA_VERSION
    # injection_id is a uuid string
    assert isinstance(inj.injection_id, str) and len(inj.injection_id) == 36
    # created_at is ISO8601 parseable
    assert "T" in inj.created_at


def test_append_writes_file_under_inbox_dir(projects_root):
    inj = ResumeInbox.append("run1", "csid1", "task1", "hi", pa_thread_id="pa9")
    inbox = projects_root / "run1" / "csid1" / PENDING_DIR_NAME
    assert inbox.is_dir()
    files = [p for p in inbox.iterdir() if p.name.endswith(".json")]
    assert len(files) == 1
    target = files[0]
    # filename: "<ts>__<uuid>.json", colon-free
    assert target.name.endswith(f"__{inj.injection_id}.json")
    assert ":" not in target.name
    # no leftover tmp file
    assert not any(p.name.endswith(".tmp") for p in inbox.iterdir())
    # on-disk payload round-trips the record
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["injection_id"] == inj.injection_id
    assert data["pa_thread_id"] == "pa9"
    assert data["schema_version"] == SCHEMA_VERSION


def test_list_pending_empty_when_no_dir(projects_root):
    assert ResumeInbox.list_pending("nope", "nope") == []


def test_list_pending_returns_appended_in_arrival_order(projects_root):
    a = ResumeInbox.append("run1", "csid1", "t1", "first")
    b = ResumeInbox.append("run1", "csid1", "t2", "second")
    pending = ResumeInbox.list_pending("run1", "csid1")
    ids = [p.injection_id for p in pending]
    assert ids == [a.injection_id, b.injection_id]
    assert [p.prompt for p in pending] == ["first", "second"]


def test_list_pending_isolated_by_session(projects_root):
    ResumeInbox.append("run1", "csidA", "t1", "x")
    assert ResumeInbox.list_pending("run1", "csidB") == []


def test_list_pending_skips_corrupt_and_hidden(projects_root):
    ResumeInbox.append("run1", "csid1", "t1", "good")
    inbox = projects_root / "run1" / "csid1" / PENDING_DIR_NAME
    (inbox / "broken.json").write_text("{ not json", encoding="utf-8")
    (inbox / ".hidden.json").write_text("{}", encoding="utf-8")
    pending = ResumeInbox.list_pending("run1", "csid1")
    assert [p.prompt for p in pending] == ["good"]


def test_append_preserves_non_ascii_prompt(projects_root):
    inj = ResumeInbox.append("run1", "csid1", "t1", "你好 héllo")
    pending = ResumeInbox.list_pending("run1", "csid1")
    assert pending[0].prompt == "你好 héllo"
    assert pending[0].injection_id == inj.injection_id
