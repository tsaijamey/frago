"""Phase 3: tmux completion-probe integration + claude transcript probe.

Verifies the pluggable authoritative completion strategy:
  - a recipe with completion_probe lets the JSONL verdict drive done + text,
  - marker advancement past a pre-submit baseline prevents a resident session
    from mistaking the previous turn's end_turn for the current turn,
  - probe returning None falls back per-frame to the pane done_signal,
  - recipes without a probe (opencode/codex) are unchanged,
  - the claude recipe probe locates and reads a real transcript file.
"""

from __future__ import annotations

import json
import uuid

from frago.agent_driver.recipe import AgentRecipe, CompletionVerdict, PaneMatcher
from frago.agent_driver.tmux_session import TmuxAgentSession


class FakeTmux:
    """Scripted tmux stand-in: capture-pane returns queued panes (last sticks)."""

    def __init__(self, panes: list[str]) -> None:
        self._panes = list(panes)
        self.commands: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.commands.append(argv)
        if argv[1:2] == ["capture-pane"]:
            return self._panes.pop(0) if len(self._panes) > 1 else self._panes[0]
        return ""


def _no_sleep(_: float) -> None:
    return None


def _recipe(*, probe=None, done_pattern=r"DONE", read_answer=None) -> AgentRecipe:
    return AgentRecipe(
        agent_type="fake",
        launch_command=lambda _ctx: "fake",
        ready_signal=PaneMatcher(name="ready", pattern=r"READY"),
        submit=lambda _session, _prompt: None,
        done_signal=PaneMatcher(name="done", pattern=done_pattern),
        extract=lambda delta: delta.strip(),
        read_answer=read_answer,
        completion_probe=probe,
    )


def _session(recipe: AgentRecipe, panes: list[str]) -> TmuxAgentSession:
    return TmuxAgentSession(
        session_id="s1",
        recipe=recipe,
        cwd="/tmp/x",
        runner=FakeTmux(panes),
        poll_interval_s=0.0,
        sleep=_no_sleep,
    )


# ── probe drives done + text ───────────────────────────────────────────────


def test_probe_verdict_supplies_done_and_text():
    # pane never shows DONE; only the probe says done -> authoritative. Pre-submit
    # baseline has no completed turn (None); the new turn's marker then advances.
    seq = [None, CompletionVerdict(done=True, text="AUTHORITATIVE ANSWER", marker="m1")]
    calls = {"i": 0}

    def probe(_s):
        v = seq[min(calls["i"], len(seq) - 1)]
        calls["i"] += 1
        return v

    sess = _session(_recipe(probe=probe), panes=["busy pane no done"])
    res = sess.send("hi", timeout_s=1.0)
    assert res.status == "ok"
    assert res.text == "AUTHORITATIVE ANSWER"


def test_probe_marker_must_advance_past_baseline():
    # Resident multi-turn: tail already done at submit (baseline marker == m0).
    # The probe keeps returning the *same* stale verdict -> never counts as this
    # turn's completion, so the run times out rather than采上一轮.
    stale = CompletionVerdict(done=True, text="OLD TURN", marker="m0")
    sess = _session(_recipe(probe=lambda _s: stale), panes=["pane"])
    res = sess.send("hi", timeout_s=0.05)
    assert res.status == "timeout"
    assert res.text != "OLD TURN"


def test_probe_fires_when_new_marker_appears():
    # First poll returns the stale (baseline) verdict; subsequent polls return a
    # new-turn verdict whose marker advanced -> done with the new text.
    seq = [
        CompletionVerdict(done=True, text="OLD", marker="m0"),  # baseline (pre-submit)
        CompletionVerdict(done=True, text="OLD", marker="m0"),  # still old turn
        CompletionVerdict(done=True, text="NEW ANSWER", marker="m1"),  # new turn done
    ]
    calls = {"i": 0}

    def probe(_s):
        i = min(calls["i"], len(seq) - 1)
        calls["i"] += 1
        return seq[i]

    sess = _session(_recipe(probe=probe), panes=["pane"])
    res = sess.send("hi", timeout_s=1.0)
    assert res.status == "ok"
    assert res.text == "NEW ANSWER"


# ── graceful fallback to pane ──────────────────────────────────────────────


def test_probe_none_falls_back_to_pane_done_signal():
    # Probe unavailable (returns None) -> pane DONE drives completion, and the
    # normal read_answer/delta path supplies the text.
    sess = _session(
        _recipe(probe=lambda _s: None, read_answer=lambda _pane, _prompt: "FROM PANE"),
        panes=["... DONE ..."],
    )
    res = sess.send("hi", timeout_s=1.0)
    assert res.status == "ok"
    assert res.text == "FROM PANE"


def test_probe_raising_falls_back_to_pane():
    def boom(_s):
        raise RuntimeError("transcript unreadable")

    sess = _session(
        _recipe(probe=boom, read_answer=lambda _pane, _prompt: "PANE TEXT"),
        panes=["DONE here"],
    )
    res = sess.send("hi", timeout_s=1.0)
    assert res.status == "ok"
    assert res.text == "PANE TEXT"


def test_no_probe_recipe_unchanged():
    # opencode/codex shape: no completion_probe -> pure pane + delta path.
    sess = _session(_recipe(probe=None), panes=["READY", "answer text\nDONE"])
    res = sess.send("hi", timeout_s=1.0)
    assert res.status == "ok"


# ── claude recipe probe (real transcript file) ─────────────────────────────


def _assistant(stop_reason, text, *, uuid_="u1"):
    return {
        "type": "assistant",
        "uuid": uuid_,
        "requestId": "req1",
        "sessionId": "sess",
        "isSidechain": False,
        "message": {
            "role": "assistant",
            "stop_reason": stop_reason,
            "content": [{"type": "text", "text": text}],
        },
    }


def test_claude_probe_reads_transcript(tmp_path, monkeypatch):
    from frago.agent_driver.recipes import claude as claude_recipe
    from frago.server.services import transcript_completion as tc

    monkeypatch.setattr(tc, "CLAUDE_PROJECTS_DIR", tmp_path)

    cwd = "/Users/frago/Repos/frago"
    sid = claude_recipe._claude_session_uuid("frago-sess-1")
    # transcript lives at <projects_root>/<encode(cwd)>/<sid>.jsonl
    from frago.session.monitor import encode_project_path

    proj = tmp_path / encode_project_path(cwd)
    proj.mkdir(parents=True)
    (proj / f"{sid}.jsonl").write_text(
        json.dumps(_assistant("end_turn", "claude final answer")), encoding="utf-8"
    )

    session = TmuxAgentSession(
        session_id="frago-sess-1",
        recipe=load_claude_recipe(),
        cwd=cwd,
        runner=FakeTmux(["pane"]),
        sleep=_no_sleep,
    )
    verdict = claude_recipe._completion_probe(session)
    assert verdict is not None
    assert verdict.done is True
    assert verdict.text == "claude final answer"
    assert verdict.marker == "u1"


def test_claude_probe_missing_file_returns_none(tmp_path, monkeypatch):
    from frago.agent_driver.recipes import claude as claude_recipe
    from frago.server.services import transcript_completion as tc

    monkeypatch.setattr(tc, "CLAUDE_PROJECTS_DIR", tmp_path)
    session = TmuxAgentSession(
        session_id="no-such-session",
        recipe=load_claude_recipe(),
        cwd="/Users/frago/Repos/frago",
        runner=FakeTmux(["pane"]),
        sleep=_no_sleep,
    )
    assert claude_recipe._completion_probe(session) is None


def test_claude_launch_injects_session_id():
    from frago.agent_driver.recipe import LaunchCtx
    from frago.agent_driver.recipes import claude as claude_recipe

    cmd = claude_recipe._launch(LaunchCtx(cwd="/tmp", session_id="abc"))
    sid = claude_recipe._claude_session_uuid("abc")
    assert "--dangerously-skip-permissions" in cmd
    assert f"--session-id {sid}" in cmd
    # deterministic + valid uuid
    uuid.UUID(sid)


def load_claude_recipe() -> AgentRecipe:
    from frago.agent_driver.recipe import load_recipe

    return load_recipe("claude")
