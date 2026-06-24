"""Tests for the transcript_completion recipe (spec 20260624, Phase 2).

Covers recipe metadata (daemon capability declaration + validity) and the
query-mode behaviour of the recipe script.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from frago.recipes.metadata import parse_metadata_file, validate_metadata

RECIPE_DIR = (
    Path(__file__).resolve().parents[4]
    / "src/frago/resources/recipes/atomic/system/transcript_completion"
)


def _load_recipe_module():
    """Load recipe.py by path (it lives outside the import package)."""
    spec = importlib.util.spec_from_file_location(
        "transcript_completion_recipe", RECIPE_DIR / "recipe.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _assistant(request_id, stop_reason, text, *, uuid="u"):
    return {
        "type": "assistant",
        "uuid": uuid,
        "requestId": request_id,
        "sessionId": "sess",
        "isSidechain": False,
        "message": {
            "role": "assistant",
            "stop_reason": stop_reason,
            "content": [{"type": "text", "text": text}],
        },
    }


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


# ── metadata ───────────────────────────────────────────────────────────────


def test_recipe_metadata_valid_and_declares_daemon():
    meta = parse_metadata_file(RECIPE_DIR / "recipe.md")
    validate_metadata(meta)  # raises on invalid
    assert meta.name == "transcript_completion"
    assert meta.type == "atomic"
    assert meta.runtime == "python"
    assert meta.daemon is True
    assert meta.restart_policy == "on-failure"
    assert "mode" in meta.inputs


def test_recipe_script_file_present():
    assert (RECIPE_DIR / "recipe.py").exists()


# ── query mode ─────────────────────────────────────────────────────────────


def test_query_mode_end_turn(tmp_path, monkeypatch, capsys):
    mod = _load_recipe_module()
    f = tmp_path / "sid.jsonl"
    _write_jsonl(f, [_assistant("req1", "end_turn", "hello world")])
    monkeypatch.setattr("sys.argv", ["recipe.py", json.dumps({"path": str(f), "mode": "query"})])
    rc = mod.main()
    out = json.loads(capsys.readouterr().out.strip())
    assert rc == 0
    assert out["type"] == "completion"
    assert out["done"] is True
    assert out["stop_reason"] == "end_turn"
    assert out["final_text"] == "hello world"
    assert out["pending_tool_use"] is False


def test_query_mode_tool_use_not_done(tmp_path, monkeypatch, capsys):
    mod = _load_recipe_module()
    f = tmp_path / "sid.jsonl"
    _write_jsonl(f, [_assistant("req1", "tool_use", "")])
    monkeypatch.setattr("sys.argv", ["recipe.py", json.dumps({"path": str(f)})])  # mode defaults to query
    rc = mod.main()
    out = json.loads(capsys.readouterr().out.strip())
    assert rc == 0
    assert out["done"] is False
    assert out["pending_tool_use"] is True


def test_query_mode_missing_target_errors(monkeypatch, capsys):
    mod = _load_recipe_module()
    monkeypatch.setattr("sys.argv", ["recipe.py", json.dumps({"mode": "query"})])
    rc = mod.main()
    out = json.loads(capsys.readouterr().out.strip())
    assert rc == 1
    assert out["type"] == "error"


def test_unknown_mode_errors(tmp_path, monkeypatch, capsys):
    mod = _load_recipe_module()
    f = tmp_path / "sid.jsonl"
    _write_jsonl(f, [_assistant("req1", "end_turn", "x")])
    monkeypatch.setattr("sys.argv", ["recipe.py", json.dumps({"path": str(f), "mode": "bogus"})])
    rc = mod.main()
    out = json.loads(capsys.readouterr().out.strip())
    assert rc == 1
    assert out["type"] == "error"


def test_parse_params_handles_no_args(monkeypatch):
    mod = _load_recipe_module()
    monkeypatch.setattr("sys.argv", ["recipe.py"])
    assert mod.parse_params() == {}


def test_resolve_target_expands_user():
    mod = _load_recipe_module()
    target = mod.resolve_target({"path": "~/some/file.jsonl"})
    assert str(target).startswith(str(Path.home()))
