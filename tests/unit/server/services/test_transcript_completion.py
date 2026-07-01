"""Tests for the transcript completion probe (spec 20260624-transcript-completion-recipe, Phase 1)."""

from __future__ import annotations

import json

from frago.session.transcript_completion import (
    evaluate_file,
    evaluate_records,
    locate_transcript,
)


def _assistant(request_id, stop_reason, content, *, uuid="u", sidechain=False, session_id="sess"):
    return {
        "type": "assistant",
        "uuid": uuid,
        "requestId": request_id,
        "sessionId": session_id,
        "isSidechain": sidechain,
        "message": {"role": "assistant", "stop_reason": stop_reason, "content": content},
    }


def _text(s):
    return [{"type": "text", "text": s}]


def _thinking(s):
    return [{"type": "thinking", "thinking": s}]


def _tool_use(name):
    return [{"type": "tool_use", "name": name, "id": "t1", "input": {}}]


# ── completion verdict by stop_reason ──────────────────────────────────────


def test_end_turn_is_done():
    recs = [_assistant("req1", "end_turn", _text("final answer"))]
    r = evaluate_records(recs)
    assert r.done is True
    assert r.stop_reason == "end_turn"
    assert r.final_text == "final answer"
    assert r.pending_tool_use is False
    assert r.request_id == "req1"


def test_stop_sequence_is_done():
    r = evaluate_records([_assistant("req1", "stop_sequence", _text("x"))])
    assert r.done is True


def test_tool_use_is_not_done():
    r = evaluate_records([_assistant("req1", "tool_use", _tool_use("Bash"))])
    assert r.done is False
    assert r.pending_tool_use is True
    assert r.stop_reason == "tool_use"


def test_none_stop_reason_is_not_done():
    r = evaluate_records([_assistant("req1", None, _text("partial"))])
    assert r.done is False
    assert r.pending_tool_use is False
    # partial text is still surfaced
    assert r.final_text == "partial"


def test_max_tokens_done_with_warning(caplog):
    with caplog.at_level("WARNING"):
        r = evaluate_records([_assistant("req1", "max_tokens", _text("cut"))], session_id="s9")
    assert r.done is True
    assert any("max_tokens" in rec.message for rec in caplog.records)


# ── text extraction by requestId group ─────────────────────────────────────


def test_multi_record_request_id_concatenates_text_blocks():
    # One turn split across three records sharing req1; only text blocks count.
    recs = [
        _assistant("req1", "tool_use", _thinking("hmm"), uuid="a"),
        _assistant("req1", "tool_use", _text("part one "), uuid="b"),
        _assistant("req1", "end_turn", _text("part two"), uuid="c"),
    ]
    r = evaluate_records(recs)
    assert r.done is True
    assert r.final_text == "part one part two"
    assert r.request_id == "req1"
    assert r.last_uuid == "c"


def test_only_terminal_turn_group_used_not_earlier_turns():
    recs = [
        _assistant("req0", "end_turn", _text("OLD ANSWER"), uuid="a"),
        _assistant("req1", "end_turn", _text("NEW ANSWER"), uuid="b"),
    ]
    r = evaluate_records(recs)
    assert r.final_text == "NEW ANSWER"


def test_end_turn_thinking_only_is_done_with_empty_text():
    r = evaluate_records([_assistant("req1", "end_turn", _thinking("only thinking"))])
    assert r.done is True
    assert r.final_text == ""


# ── sidechain filtering & meta-record tolerance ────────────────────────────


def test_sidechain_records_are_ignored():
    recs = [
        _assistant("req1", "end_turn", _text("main answer"), uuid="m"),
        _assistant("req2", "tool_use", _tool_use("X"), uuid="s", sidechain=True),
    ]
    r = evaluate_records(recs)
    # The sidechain tool_use must not flip the verdict to not-done.
    assert r.done is True
    assert r.final_text == "main answer"


def test_trailing_meta_records_do_not_affect_verdict():
    recs = [
        _assistant("req1", "end_turn", _text("done text")),
        {"type": "system", "subtype": "stop_hook_summary", "content": "x"},
        {"type": "system", "subtype": "turn_duration"},
        {"type": "last-prompt", "lastPrompt": "p"},
        {"type": "ai-title", "aiTitle": "t"},
    ]
    r = evaluate_records(recs)
    assert r.done is True
    assert r.final_text == "done text"


def test_no_assistant_records_is_not_done():
    recs = [{"type": "user", "message": {"role": "user", "content": "hi"}}]
    r = evaluate_records(recs)
    assert r.done is False
    assert r.final_text == ""
    assert r.request_id is None


# ── file IO wrapper ────────────────────────────────────────────────────────


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def test_evaluate_file_end_turn(tmp_path):
    f = tmp_path / "sid.jsonl"
    _write_jsonl(f, [_assistant("req1", "end_turn", _text("hello"))])
    r = evaluate_file(f)
    assert r.done is True
    assert r.final_text == "hello"
    assert r.source_path == str(f)


def test_evaluate_file_missing_is_not_done(tmp_path):
    r = evaluate_file(tmp_path / "nope.jsonl")
    assert r.done is False
    assert r.final_text == ""


def test_evaluate_file_empty_is_not_done(tmp_path):
    f = tmp_path / "empty.jsonl"
    f.write_text("", encoding="utf-8")
    r = evaluate_file(f)
    assert r.done is False


def test_evaluate_file_tolerates_bad_lines(tmp_path):
    f = tmp_path / "mixed.jsonl"
    f.write_text(
        "{ not json\n" + json.dumps(_assistant("req1", "end_turn", _text("ok"))) + "\n",
        encoding="utf-8",
    )
    r = evaluate_file(f)
    assert r.done is True
    assert r.final_text == "ok"


# ── transcript location ────────────────────────────────────────────────────


def test_locate_transcript_prefers_encoded_cwd(tmp_path):
    cwd = "/Users/frago/Repos/frago"
    # encode_project_path replaces '/' with '-'
    proj = tmp_path / "-Users-frago-Repos-frago"
    proj.mkdir()
    target = proj / "the-sid.jsonl"
    target.write_text("{}", encoding="utf-8")
    found = locate_transcript("the-sid", cwd=cwd, projects_root=tmp_path)
    assert found == target


def test_locate_transcript_falls_back_to_scan(tmp_path):
    proj = tmp_path / "some-other-dir"
    proj.mkdir()
    target = proj / "the-sid.jsonl"
    target.write_text("{}", encoding="utf-8")
    found = locate_transcript("the-sid", cwd="/unrelated/path", projects_root=tmp_path)
    assert found == target


def test_locate_transcript_missing_returns_none(tmp_path):
    assert locate_transcript("ghost", cwd=None, projects_root=tmp_path) is None
