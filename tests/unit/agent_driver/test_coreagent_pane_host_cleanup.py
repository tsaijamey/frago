"""coreagent_pane_host SIGHUP 信号转发与退出时子孙进程树级联清理单测（P1）。

不触碰宿主真实 tmux，仅使用本机轻量 Python 子进程树验证：
1. ``_terminate_process_tree`` 能级联终止派生了独立进程组（``start_new_session=True``）的孙进程；
2. 忽略 ``SIGTERM`` 的顽固孙进程在宽限期后被补发 ``SIGKILL`` 强杀清理；
3. 非 Windows 平台 ``_pane_host_stop_signals`` 包含 ``SIGHUP``，且 ``_run_pane_host`` 收到
   ``SIGHUP`` 时级联清理整棵工具子进程树并落盘 ``exit.code``。
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from frago.agent_driver.coreagent_pane_host import (
    _pane_host_stop_signals,
    _terminate_process_tree,
)


def _wait_for_pid_file(pid_file: Path, timeout_s: float = 5.0) -> int:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if pid_file.is_file():
            raw = pid_file.read_text(encoding="utf-8").strip()
            if raw.isdigit():
                return int(raw)
        time.sleep(0.03)
    raise TimeoutError(f"PID file not written within {timeout_s}s: {pid_file}")


def _is_pid_running(pid: int) -> bool:
    try:
        proc = psutil.Process(pid)
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def test_terminate_process_tree_kills_detached_grandchild(tmp_path: Path) -> None:
    """父进程派生了独立会话/进程组的孙进程时，_terminate_process_tree 必须一并清理。"""
    grandchild_pid_file = tmp_path / "grandchild.pid"
    parent_script = tmp_path / "parent.py"
    parent_script.write_text(
        "import subprocess, sys, time\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen(\n"
        "    [sys.executable, '-c', 'import time; time.sleep(60)'],\n"
        "    start_new_session=True,\n"
        ")\n"
        f"Path({str(grandchild_pid_file)!r}).write_text(str(child.pid), encoding='utf-8')\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )

    parent_proc = subprocess.Popen([sys.executable, str(parent_script)])
    grandchild_pid: int | None = None
    try:
        grandchild_pid = _wait_for_pid_file(grandchild_pid_file)
        assert _is_pid_running(parent_proc.pid)
        assert _is_pid_running(grandchild_pid)

        _terminate_process_tree(parent_proc, grace_timeout=0.8)

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and _is_pid_running(grandchild_pid):
            time.sleep(0.05)

        assert not _is_pid_running(parent_proc.pid)
        assert not _is_pid_running(grandchild_pid)
    finally:
        if parent_proc.poll() is None:
            parent_proc.kill()
            parent_proc.wait(timeout=1.0)
        if grandchild_pid and _is_pid_running(grandchild_pid):
            with contextlib.suppress(OSError):
                os.kill(grandchild_pid, getattr(signal, "SIGKILL", signal.SIGTERM))


def test_terminate_process_tree_sigkills_sigterm_ignoring_descendant(
    tmp_path: Path,
) -> None:
    """当孙进程忽略 SIGTERM 时，宽限期过后必须补发 SIGKILL 彻底清除。"""
    grandchild_pid_file = tmp_path / "stubborn_grandchild.pid"
    grandchild_script = tmp_path / "stubborn.py"
    grandchild_script.write_text(
        "import os, signal, time\n"
        "from pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"Path({str(grandchild_pid_file)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    parent_script = tmp_path / "parent_stubborn.py"
    parent_script.write_text(
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, {str(grandchild_script)!r}], start_new_session=True)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )

    parent_proc = subprocess.Popen([sys.executable, str(parent_script)])
    grandchild_pid: int | None = None
    try:
        grandchild_pid = _wait_for_pid_file(grandchild_pid_file)
        assert _is_pid_running(grandchild_pid)

        _terminate_process_tree(parent_proc, grace_timeout=0.2)

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and _is_pid_running(grandchild_pid):
            time.sleep(0.05)

        assert not _is_pid_running(grandchild_pid)
    finally:
        if parent_proc.poll() is None:
            parent_proc.kill()
            parent_proc.wait(timeout=1.0)
        if grandchild_pid and _is_pid_running(grandchild_pid):
            with contextlib.suppress(OSError):
                os.kill(grandchild_pid, getattr(signal, "SIGKILL", signal.SIGTERM))


@pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="POSIX SIGHUP required")
def test_pane_host_registers_sighup_and_cascades_tree_cleanup(tmp_path: Path) -> None:
    """模拟 tmux kill-session 向 pane_host 发送 SIGHUP，验证整棵子孙进程树被级联清理。"""
    assert signal.SIGHUP in _pane_host_stop_signals()

    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "stdout.jsonl").write_text("", encoding="utf-8")
    (run_dir / "stderr.log").write_text("", encoding="utf-8")
    (run_dir / "stdin.jsonl").write_text("", encoding="utf-8")
    (run_dir / "prompt.txt").write_text("run long bash tool", encoding="utf-8")

    grandchild_pid_file = tmp_path / "tool_grandchild.pid"
    fake_core = tmp_path / "fake_frago_core.py"
    fake_core.write_text(
        "import json, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "_ = sys.stdin.read()\n"
        "tool_proc = subprocess.Popen(\n"
        "    [sys.executable, '-c', 'import time; time.sleep(60)'],\n"
        "    start_new_session=True,\n"
        ")\n"
        f"Path({str(grandchild_pid_file)!r}).write_text(str(tool_proc.pid), encoding='utf-8')\n"
        "sys.stdout.write(json.dumps({'type':'assistant','message':{'content':[{'type':'tool_use','name':'Bash','input':{'command':'sleep 60'}}]}}) + '\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )

    launch_spec = {
        "session_id": "core_sighup_test",
        "mode": "oneshot",
        "cmd": [sys.executable, "-u", str(fake_core)],
        "cwd": str(tmp_path),
        "env": {},
        "pane_log": str(tmp_path / "pane.log"),
    }
    (run_dir / "launch.json").write_text(
        json.dumps(launch_spec, ensure_ascii=False), encoding="utf-8"
    )

    host_proc = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-m",
            "frago.agent_driver.coreagent_pane_host",
            str(run_dir),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    core_pid: int | None = None
    grandchild_pid: int | None = None
    try:
        core_pid = _wait_for_pid_file(run_dir / "core.pid")
        grandchild_pid = _wait_for_pid_file(grandchild_pid_file)
        assert _is_pid_running(core_pid)
        assert _is_pid_running(grandchild_pid)

        # 向宿主进程发送 SIGHUP（等价于 tmux kill-session 默认信号）
        os.kill(host_proc.pid, signal.SIGHUP)
        host_proc.wait(timeout=5.0)

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and (
            _is_pid_running(core_pid) or _is_pid_running(grandchild_pid)
        ):
            time.sleep(0.05)

        assert not _is_pid_running(core_pid)
        assert not _is_pid_running(grandchild_pid)
        assert (run_dir / "exit.code").is_file()
    finally:
        if host_proc.poll() is None:
            host_proc.kill()
            host_proc.wait(timeout=1.0)
        for pid in (core_pid, grandchild_pid):
            if pid and _is_pid_running(pid):
                with contextlib.suppress(OSError):
                    os.kill(pid, signal.SIGKILL)
