"""Reflection tick regression — _fire must NOT create a board thread.

A reflection produces no Msg, so nothing can ever attach to a reflection
thread (decisions require an existing Msg). Creating one only left an empty
thread that bloated the timeline and re-folded into the board every boot.
_fire must keep the two real responsibilities: enqueue the trigger and write
the `thought` observability trace.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import frago.server.services.taskboard as tb
import frago.server.services.trace as trace_mod
from frago.server.services.reflection_tick import ReflectionTicker


def test_fire_enqueues_and_traces_without_board_thread(tmp_path: Path, monkeypatch):
    # isolate the trace sink to tmp
    traces_dir = tmp_path / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(trace_mod, "TRACE_DIR", traces_dir)

    # guard: _fire must not touch the board at all
    def _boom():
        raise AssertionError("reflection _fire must not touch the board")

    monkeypatch.setattr(tb, "get_board", _boom)

    enqueued: list[dict] = []

    async def _enqueue(m: dict) -> None:
        enqueued.append(m)

    ticker = ReflectionTicker(enqueue=_enqueue)
    tid = asyncio.run(ticker.fire_once())

    # 1) trigger enqueued
    assert len(enqueued) == 1
    m = enqueued[0]
    assert m["type"] == "internal_reflection"
    assert m["thread_id"] == tid
    assert m["msg_id"] == tid

    # 2) observability trace written (thought / subkind=reflection), in traces/
    files = list(traces_dir.glob("trace-*.jsonl"))
    assert files, "reflection thought trace was not written to TRACE_DIR"
    entries = [
        json.loads(line)
        for f in files
        for line in f.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    thoughts = [e for e in entries if e.get("data_type") == "thought"]
    assert len(thoughts) == 1
    assert thoughts[0].get("subkind") == "reflection"

    # 3) no board thread_created emitted anywhere (guard above would have raised)
    assert all(e.get("data_type") != "thread_created" for e in entries)
