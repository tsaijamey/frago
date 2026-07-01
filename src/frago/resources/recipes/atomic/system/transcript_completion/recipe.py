"""Recipe: transcript_completion.

Parse a Claude Code session JSONL and report whether the latest turn finished
plus the assistant's final text, using the authoritative ``stop_reason`` signal.

Two forms, sharing the Phase-1 pure core (``frago.session.transcript_completion``):
  - mode=query (default): one-shot — emit a single JSON line for the tail verdict.
  - mode=watch: long-running — watch the file, emit an event line each time the
    "latest turn done" verdict flips. Runs forever; meant to be supervised by the
    daemon supervisor (spec 20260624-recipe-daemon-supervisor).

No PEP 723 block on purpose: this recipe imports the ``frago`` package, so it must
run inside the frago venv (where ``frago recipe run`` and server-spawned children
already run). A PEP 723 block would make uv use an isolated env where frago is
not importable.
"""

import json
import os
import sys

from frago.session.transcript_completion import (
    TurnCompletion,
    evaluate_file,
    locate_transcript,
)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def parse_params() -> dict:
    """Recipe params arrive as a JSON string in argv[1] (see runner._run_python)."""
    if len(sys.argv) > 1 and sys.argv[1].strip():
        try:
            data = json.loads(sys.argv[1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {}


def resolve_target(params: dict):
    """Return the transcript Path from ``path`` or ``session_id`` (+ optional cwd)."""
    raw_path = params.get("path")
    if isinstance(raw_path, str) and raw_path.strip():
        from pathlib import Path

        return Path(os.path.expanduser(raw_path.strip()))
    session_id = params.get("session_id")
    if isinstance(session_id, str) and session_id.strip():
        cwd = params.get("cwd")
        return locate_transcript(session_id.strip(), cwd=cwd if isinstance(cwd, str) else None)
    return None


def _verdict_payload(event_type: str, tc: TurnCompletion) -> dict:
    return {
        "type": event_type,
        "done": tc.done,
        "stop_reason": tc.stop_reason,
        "final_text": tc.final_text,
        "pending_tool_use": tc.pending_tool_use,
        "request_id": tc.request_id,
        "session_id": tc.session_id,
        "source_path": tc.source_path,
    }


def run_query(target) -> int:
    if target is None:
        emit({"type": "error", "error": "could not resolve transcript (need path or session_id)"})
        return 1
    tc = evaluate_file(target)
    emit(_verdict_payload("completion", tc))
    return 0


def run_watch(target) -> int:
    """Watch a single transcript; emit an event each time the done-verdict flips."""
    if target is None:
        emit({"type": "error", "error": "could not resolve transcript (need path or session_id)"})
        return 1

    import threading

    from watchdog.observers import Observer

    from frago.session.monitor import SessionFileHandler

    # Resolve symlinks so the watchdog event path (which the OS may report via
    # the real path, e.g. /private/var on macOS) matches the handler's exact
    # target-file filter.
    target = target.resolve()
    target_str = str(target)
    state = {"last_done": None}

    def evaluate_and_emit() -> None:
        # Completion is a tail property; re-read the file via the reused core
        # rather than threading incremental record accumulation.
        tc = evaluate_file(target)
        if tc.done != state["last_done"]:
            state["last_done"] = tc.done
            emit(_verdict_payload("turn_complete" if tc.done else "turn_running", tc))

    # SessionFileHandler fires on_new_records only when the target file gains
    # records; we use it purely as a "something changed" signal and re-evaluate.
    handler = SessionFileHandler(
        on_new_records=lambda _path, _records: evaluate_and_emit(),
        target_file=target_str,
    )

    # Emit the initial verdict so consumers get current state immediately.
    if target.exists():
        evaluate_and_emit()

    observer = Observer()
    observer.schedule(handler, os.path.dirname(target_str), recursive=False)
    observer.start()
    log(f"transcript_completion watching {target_str}")
    try:
        threading.Event().wait()  # run until killed by the supervisor
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join(timeout=2)
    return 0


def main() -> int:
    params = parse_params()
    mode = params.get("mode") or "query"
    target = resolve_target(params)
    if mode == "watch":
        return run_watch(target)
    if mode != "query":
        emit({"type": "error", "error": f"unknown mode: {mode!r} (expected query|watch)"})
        return 1
    return run_query(target)


if __name__ == "__main__":
    sys.exit(main())
