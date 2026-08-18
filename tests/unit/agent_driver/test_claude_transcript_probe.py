"""Phase 3: tmux completion-probe integration + claude transcript probe.

Verifies the pluggable authoritative completion strategy:
  - a driver with completion_probe lets the JSONL verdict drive done + text,
  - marker advancement past a pre-submit baseline prevents a resident session
    from mistaking the previous turn's end_turn for the current turn,
  - probe returning None falls back per-frame to the pane done_signal,
  - drivers without a probe (opencode/codex) are unchanged,
  - the claude driver probe locates and reads a real transcript file.
"""

from __future__ import annotations

import json
import uuid

from frago.agent_driver.driver import AgentDriver, CompletionVerdict, PaneMatcher
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


def _driver(*, probe=None, done_pattern=r"DONE", read_answer=None) -> AgentDriver:
    return AgentDriver(
        agent_type="fake",
        launch_command=lambda _ctx: "fake",
        ready_signal=PaneMatcher(name="ready", pattern=r"READY"),
        submit=lambda _session, _prompt: None,
        done_signal=PaneMatcher(name="done", pattern=done_pattern),
        extract=lambda delta: delta.strip(),
        read_answer=read_answer,
        completion_probe=probe,
    )


def _session(driver: AgentDriver, panes: list[str]) -> TmuxAgentSession:
    return TmuxAgentSession(
        session_id="s1",
        driver=driver,
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

    sess = _session(_driver(probe=probe), panes=["busy pane no done"])
    res = sess.send("hi", timeout_s=1.0)
    assert res.status == "ok"
    assert res.text == "AUTHORITATIVE ANSWER"


def test_probe_marker_must_advance_past_baseline():
    # Resident multi-turn: tail already done at submit (baseline marker == m0).
    # The probe keeps returning the *same* stale verdict -> never counts as this
    # turn's completion, so the run times out rather than采上一轮.
    stale = CompletionVerdict(done=True, text="OLD TURN", marker="m0")
    sess = _session(_driver(probe=lambda _s: stale), panes=["pane"])
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

    sess = _session(_driver(probe=probe), panes=["pane"])
    res = sess.send("hi", timeout_s=1.0)
    assert res.status == "ok"
    assert res.text == "NEW ANSWER"


# ── graceful fallback to pane ──────────────────────────────────────────────


def test_probe_none_falls_back_to_pane_done_signal():
    # Probe unavailable (returns None) -> pane DONE drives completion, and the
    # normal read_answer/delta path supplies the text.
    sess = _session(
        _driver(probe=lambda _s: None, read_answer=lambda _pane, _prompt: "FROM PANE"),
        panes=["... DONE ..."],
    )
    res = sess.send("hi", timeout_s=1.0)
    assert res.status == "ok"
    assert res.text == "FROM PANE"


def test_probe_raising_falls_back_to_pane():
    def boom(_s):
        raise RuntimeError("transcript unreadable")

    sess = _session(
        _driver(probe=boom, read_answer=lambda _pane, _prompt: "PANE TEXT"),
        panes=["DONE here"],
    )
    res = sess.send("hi", timeout_s=1.0)
    assert res.status == "ok"
    assert res.text == "PANE TEXT"


def test_no_probe_driver_unchanged():
    # opencode/codex shape: no completion_probe -> pure pane + delta path.
    sess = _session(_driver(probe=None), panes=["READY", "answer text\nDONE"])
    res = sess.send("hi", timeout_s=1.0)
    assert res.status == "ok"


# ── claude driver probe (real transcript file) ─────────────────────────────


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
    from frago.agent_driver.drivers import claude as claude_driver
    from frago.session import transcript_completion as tc

    monkeypatch.setattr(tc, "CLAUDE_PROJECTS_DIR", tmp_path)

    cwd = "/Users/frago/Repos/frago"
    sid = claude_driver._claude_session_uuid("frago-sess-1")
    # transcript lives at <projects_root>/<encode(cwd)>/<sid>.jsonl
    from frago.session.monitor import encode_project_path

    proj = tmp_path / encode_project_path(cwd)
    proj.mkdir(parents=True)
    (proj / f"{sid}.jsonl").write_text(
        json.dumps(_assistant("end_turn", "claude final answer")), encoding="utf-8"
    )

    session = TmuxAgentSession(
        session_id="frago-sess-1",
        driver=load_claude_driver(),
        cwd=cwd,
        runner=FakeTmux(["pane"]),
        sleep=_no_sleep,
    )
    verdict = claude_driver._completion_probe(session)
    assert verdict is not None
    assert verdict.done is True
    assert verdict.text == "claude final answer"
    assert verdict.marker == "u1"


def test_claude_probe_missing_file_returns_none(tmp_path, monkeypatch):
    from frago.agent_driver.drivers import claude as claude_driver
    from frago.session import transcript_completion as tc

    monkeypatch.setattr(tc, "CLAUDE_PROJECTS_DIR", tmp_path)
    session = TmuxAgentSession(
        session_id="no-such-session",
        driver=load_claude_driver(),
        cwd="/Users/frago/Repos/frago",
        runner=FakeTmux(["pane"]),
        sleep=_no_sleep,
    )
    assert claude_driver._completion_probe(session) is None


def test_claude_launch_injects_session_id(tmp_path, monkeypatch):
    from frago.agent_driver.driver import LaunchCtx
    from frago.agent_driver.drivers import claude as claude_driver

    # _launch 起会话前会把 cwd 写进 claude 的信任登记；把配置目录指到 tmp，
    # 免得单测污染开发者真实的 ~/.claude.json。
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    cmd = claude_driver._launch(LaunchCtx(cwd="/tmp", session_id="abc"))
    sid = claude_driver._claude_session_uuid("abc")
    assert "--dangerously-skip-permissions" in cmd
    assert f"--session-id {sid}" in cmd
    # deterministic + valid uuid
    uuid.UUID(sid)


def _read_trust(config_dir, cwd) -> object:
    import json
    import os

    data = json.loads((config_dir / ".claude.json").read_text(encoding="utf-8"))
    return data["projects"][os.path.abspath(cwd)]["hasTrustDialogAccepted"]


def test_launch_pretrusts_cwd(tmp_path, monkeypatch):
    """起会话前，cwd 被写进 claude 的 per-project 信任登记（免弹信任菜单）。"""
    from frago.agent_driver.driver import LaunchCtx
    from frago.agent_driver.drivers import claude as claude_driver

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    claude_driver._launch(LaunchCtx(cwd="/work/project", session_id="s1"))
    assert _read_trust(tmp_path, "/work/project") is True


def test_ensure_trusted_preserves_existing_config(tmp_path, monkeypatch):
    """写信任只补 projects 一枝，claude 已有的其他配置与其他项目原样保留。"""
    import json

    from frago.agent_driver.drivers import claude as claude_driver

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    cfg = tmp_path / ".claude.json"
    cfg.write_text(
        json.dumps(
            {
                "userID": "keep-me",
                "projects": {"/other": {"hasTrustDialogAccepted": True, "note": "x"}},
            }
        ),
        encoding="utf-8",
    )

    claude_driver._ensure_workspace_trusted("/new/dir")

    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["userID"] == "keep-me"                       # 顶层其他键不丢
    assert data["projects"]["/other"] == {"hasTrustDialogAccepted": True, "note": "x"}
    assert data["projects"]["/new/dir"]["hasTrustDialogAccepted"] is True


def test_ensure_trusted_idempotent_skips_write(tmp_path, monkeypatch):
    """已信任的目录不再重写文件——不与运行中的 claude 抢盘。"""
    import json

    from frago.agent_driver.drivers import claude as claude_driver

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    cfg = tmp_path / ".claude.json"
    cfg.write_text(
        json.dumps({"projects": {"/abs/x": {"hasTrustDialogAccepted": True}}}),
        encoding="utf-8",
    )
    before = cfg.stat().st_mtime_ns
    claude_driver._ensure_workspace_trusted("/abs/x")
    assert cfg.stat().st_mtime_ns == before                  # 没写


def test_ensure_trusted_tolerates_corrupt_config(tmp_path, monkeypatch):
    """配置文件损坏时不炸：从空表重建，仍把信任写进去。"""
    import json

    from frago.agent_driver.drivers import claude as claude_driver

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    cfg = tmp_path / ".claude.json"
    cfg.write_text("{not json", encoding="utf-8")

    claude_driver._ensure_workspace_trusted("/abs/y")

    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["projects"]["/abs/y"]["hasTrustDialogAccepted"] is True


def test_ensure_trusted_never_raises(tmp_path, monkeypatch):
    """写不动配置时是尽力而为——只告警、不抛异常，NEVER 把 launch 打死。"""
    from frago.agent_driver.drivers import claude as claude_driver

    # 配置目录指向一个"已被文件占位"的路径，parent.mkdir 会失败。
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a dir", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(blocker / "nested"))

    # 不抛即通过。
    claude_driver._ensure_workspace_trusted("/abs/z")


def load_claude_driver() -> AgentDriver:
    from frago.agent_driver.driver import load_driver

    return load_driver("claude")
