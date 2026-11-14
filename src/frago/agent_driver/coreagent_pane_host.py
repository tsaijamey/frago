"""CoreAgent 的 tmux 面板宿主 —— 让 ``frago-core`` 跑在真实的 tmux 窗格里。

为什么需要这一层宿主（而不是裸调 ``tmux send-keys``）：

- ``frago-core`` 是流式 JSON 协议进程（``--input-format stream-json`` 或 ``-p -``），
  不是带输入框的 TUI，不能靠 ``send-keys`` 往屏幕上敲字驱动。
- 直接把 ``frago-core`` 挂在后台管道上（旧做法），机器能读到 ``stdout`` 的 JSON，
  但没有 tmux 窗格，用户在工作台切到 Terminal 视图时看不到任何终端运行画面。
- 本模块跑在 ``tmux new-session -d -s frago-agent-<sid>`` 的窗格内：
  1. 原样保留调用方给的全部启动参数、工作目录与环境变量（``launch.json`` + ``tmux -e``）；
  2. 把 ``frago-core`` 的原始 ``stdout`` 逐行实时落入 ``stdout.jsonl``，供外层
     ``coreagent_runner``（常驻多轮）或 ``kernel_backend``（CLI 单轮 worker）
     做零损解析；
  3. 同时把用户提问、思考过程、工具调用、工具回执、``stderr`` 进度与本轮结论渲染成
     带 ANSI 色彩的可读终端流，直接打在 tmux 窗格上，并同步留存一份快照到
     ``~/.frago/coreagent/panes/<sid>.log``（方便单轮 worker 跑完退出 tmux 后，
     用户在工作台 Terminal 档仍能回看完整终端输出）。
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from frago.agent_driver.tmux_session import (
    _PROXY_ENV_NAMES,
    _WINDOWS,
    _is_windows_stub_bash,
    _windows_git_companion_dirs,
    _windows_posix_shell,
    tmux_name_for,
)


def tmux_available() -> bool:
    """本机是否可用 tmux 承载 CoreAgent。

    允许通过 ``FRAGO_COREAGENT_NO_TMUX=1`` 显式关闭（供回退分支测试或受限容器使用）。
    """
    if os.environ.get("FRAGO_COREAGENT_NO_TMUX") == "1":
        return False
    return shutil.which("tmux") is not None


def panes_dir() -> Path:
    """CoreAgent 终端输出留底目录（``~/.frago/coreagent/panes``）。"""
    override = os.environ.get("FRAGO_COREAGENT_PANES_DIR")
    base = Path(override) if override else Path.home() / ".frago" / "coreagent" / "panes"
    with contextlib.suppress(OSError):
        base.mkdir(parents=True, exist_ok=True)
    return base


def saved_pane_log_path(session_id: str) -> Path:
    """某场 CoreAgent 会话的终端屏幕留底文件路径。"""
    safe = "".join(c if (c.isalnum() or c in "_-") else "_" for c in session_id)
    return panes_dir() / f"{safe}.log"


def active_run_marker_path(session_id: str) -> Path:
    """某场 CoreAgent 会话当前持有 tmux 窗格的活跃 run_dir 登记文件路径。"""
    safe = "".join(c if (c.isalnum() or c in "_-") else "_" for c in session_id)
    return panes_dir() / f"{safe}.active_run"


def read_saved_pane_log(session_id: str, *, max_lines: int = 500) -> str:
    """读取留底的终端屏幕输出（tmux 已退出时兜底展示）。找不到返回空串。"""
    if not session_id:
        return ""
    path = saved_pane_log_path(session_id)
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if max_lines > 0:
        lines = text.splitlines()
        if len(lines) > max_lines:
            return "\n".join(lines[-max_lines:])
    return text


def merged_coreagent_env(base_env: Mapping[str, str] | None, *, session_id: str) -> dict[str, str]:
    """合并 CoreAgent 启动所需的完整环境变量（UTF-8 + 代理 + 会话身份 + 调用方显式键值）。

    Windows 下额外把定位到的 Git Bash 写入 ``SHELL``，并将其同仓的 ``bin``、``usr\\bin``、
    ``mingw64\\bin``、``cmd`` 前置写入 ``PATH``（通过 ``launch.json`` 直接传给 ``frago-core.exe``），
    避免依赖常驻 ``tmux.exe`` 服务端过期的全局环境或落到 ``C:\\Windows\\System32\\bash.exe``。
    """
    env: dict[str, str] = {
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
    }
    for proxy_name in _PROXY_ENV_NAMES:
        val = os.environ.get(proxy_name)
        if val:
            env.setdefault(proxy_name, val)
    if session_id:
        env["FRAGO_SESSION_ID"] = session_id
        env["FRAGO_CONV_KEY"] = os.environ.get("FRAGO_CONV_KEY") or session_id
    if base_env:
        for k, v in base_env.items():
            if v is not None:
                env[str(k)] = str(v)
    if _WINDOWS:
        bash = _windows_posix_shell()
        if bash:
            existing_shell = env.get("SHELL", "").strip()
            if (
                not existing_shell
                or existing_shell.startswith("/")
                or _is_windows_stub_bash(existing_shell)
                or not os.path.isfile(existing_shell)
            ):
                env["SHELL"] = bash
            companion_dirs = _windows_git_companion_dirs(bash)
            if companion_dirs:
                raw_path = (
                    env.get("PATH")
                    or env.get("Path")
                    or os.environ.get("PATH")
                    or os.environ.get("Path")  # noqa: SIM112
                    or ""
                )
                sep = ";"
                merged_parts: list[str] = list(companion_dirs)
                seen_lower = {p.lower() for p in merged_parts}
                for part in raw_path.split(sep):
                    cleaned = part.strip()
                    if cleaned and cleaned.lower() not in seen_lower:
                        seen_lower.add(cleaned.lower())
                        merged_parts.append(cleaned)
                env["PATH"] = sep.join(merged_parts)
    return env


def format_user_prompt_for_pane(prompt: str) -> str:
    """把投喂给内核的用户指令格式化成终端可见的提示行。"""
    text = (prompt or "").strip()
    if not text:
        return ""
    preview = text if len(text) <= 1200 else text[:1200] + f" … (+{len(text) - 1200} chars)"
    return f"\n\x1b[1;32m❯\x1b[0m {preview}\n"


def format_stream_line_for_pane(raw_line: str) -> str:
    """把 ``frago-core`` 的一行 ``stream-json`` / ``json`` 输出转成可读的 ANSI 终端文本。"""
    line = (raw_line or "").strip()
    if not line:
        return ""
    if not line.startswith("{"):
        return line + "\n"
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return line + "\n"
    if not isinstance(obj, dict):
        return line + "\n"

    kind = obj.get("type")
    if kind == "system":
        sub = obj.get("subtype")
        if sub == "init":
            model = obj.get("model") or "default"
            cwd = obj.get("cwd") or ""
            sid = obj.get("session_id") or ""
            return (
                f"\x1b[2m[init] session={sid} model={model} cwd={cwd}\x1b[0m\n"
            )
        if sub == "hook_response":
            ev = obj.get("hook_event") or "hook"
            outcome = obj.get("outcome") or "ok"
            if outcome != "ok":
                return f"\x1b[33m[hook:{ev}] outcome={outcome}\x1b[0m\n"
            return ""
        return ""

    if kind == "assistant":
        msg = obj.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            return ""
        chunks: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                txt = (block.get("text") or "").strip()
                if txt:
                    chunks.append(f"\x1b[1;36m⏺\x1b[0m {txt}\n")
            elif btype == "tool_use":
                tname = block.get("name") or "tool"
                tinput = block.get("input")
                summary = _summarize_tool_input(tname, tinput)
                chunks.append(f"\x1b[1;33m⚙ {tname}\x1b[0m\x1b[2m({summary})\x1b[0m\n")
        return "".join(chunks)

    if kind == "user":
        msg = obj.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            return ""
        chunks = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            is_err = bool(block.get("is_error"))
            out_txt = _extract_tool_result_text(block.get("content")).strip()
            if not out_txt:
                continue
            first_lines = [ln for ln in out_txt.splitlines() if not ln.startswith("〔rules guidance〕")]
            preview = "\n".join(first_lines[:6]).strip()
            if len(first_lines) > 6:
                preview += f"\n  … (+{len(first_lines) - 6} lines)"
            if len(preview) > 500:
                preview = preview[:500] + "…"
            color = "\x1b[31m" if is_err else "\x1b[2m"
            prefix = "✗" if is_err else "↳"
            indented = "\n  ".join(preview.splitlines())
            chunks.append(f"  {color}{prefix} {indented}\x1b[0m\n")
        return "".join(chunks)

    if kind == "result" and "tool_call_id" not in obj:
        is_err = bool(obj.get("is_error"))
        turns = obj.get("num_turns") or 1
        dur = obj.get("duration_ms") or 0
        body = str(obj.get("result") or "").strip()
        if is_err:
            return f"\x1b[1;31m✗ Turn failed ({turns} turns, {dur}ms): {body}\x1b[0m\n"
        return f"\x1b[1;32m✓ Turn complete ({turns} turns, {dur}ms)\x1b[0m\n"

    if kind == "final":
        ok = bool(obj.get("ok"))
        dur = obj.get("duration_ms") or 0
        if ok:
            return f"\x1b[1;32m✓ Final ({dur}ms)\x1b[0m\n"
        err = obj.get("error") or obj.get("text") or ""
        return f"\x1b[1;31m✗ Error ({dur}ms): {err}\x1b[0m\n"

    return ""


def _summarize_tool_input(tool_name: str, tool_input: Any) -> str:
    if not isinstance(tool_input, dict):
        return ""
    if tool_name == "Bash":
        cmd = str(tool_input.get("command") or "").strip().replace("\n", " ")
        return cmd[:100] + ("…" if len(cmd) > 100 else "")
    for key in ("file_path", "path", "pattern", "query", "url", "skill"):
        if key in tool_input and tool_input[key]:
            val = str(tool_input[key])
            return f"{key}={val[:80]}"
    raw = json.dumps(tool_input, ensure_ascii=False)
    return raw[:80] + ("…" if len(raw) > 80 else "")


def _extract_tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        if "〔tool output〕" in content:
            return content.split("〔tool output〕", 1)[1]
        return content
    if isinstance(content, list):
        return "\n".join(
            str(b.get("text") or "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return "" if content is None else str(content)


# ── Tmux 进程包装器（对齐 subprocess.Popen 接口，供 coreagent_runner 与 kernel_backend 共用） ──


class _TmuxStdin:
    """通过 ``stdin.jsonl`` + ``stdin.eof`` 向 tmux 内的宿主投喂输入。"""

    def __init__(self, run_dir: Path, is_alive_fn) -> None:
        self._stdin_file = run_dir / "stdin.jsonl"
        self._eof_file = run_dir / "stdin.eof"
        self._is_alive = is_alive_fn
        self._lock = threading.Lock()
        self.closed = False

    def write(self, text: str) -> int:
        with self._lock:
            if self.closed:
                raise ValueError("I/O operation on closed file.")
            if not self._is_alive():
                raise BrokenPipeError("CoreAgent tmux session is no longer alive.")
            with self._stdin_file.open("a", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
            return len(text)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        with self._lock:
            if self.closed:
                return
            self.closed = True
            with contextlib.suppress(OSError):
                self._eof_file.write_text("eof\n", encoding="utf-8")


class _TmuxStdout:
    """按行流式跟随 ``stdout.jsonl``，直到宿主写出 ``exit.code`` 或 tmux 会话消失。"""

    def __init__(self, run_dir: Path, is_alive_fn) -> None:
        self._stdout_file = run_dir / "stdout.jsonl"
        self._exit_file = run_dir / "exit.code"
        self._is_alive = is_alive_fn
        self._closed = False

    def close(self) -> None:
        self._closed = True

    def __iter__(self) -> Iterator[str]:
        return self._line_generator()

    def _line_generator(self) -> Iterator[str]:
        offset = 0
        partial = ""
        # 给 tmux 刚启动那几百毫秒宽限期，免得第一拍还没建起文件就误判退出。
        grace_until = time.monotonic() + 3.0
        while not self._closed:
            chunk = ""
            if self._stdout_file.is_file():
                try:
                    with self._stdout_file.open("r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(offset)
                        chunk = fh.read()
                        offset = fh.tell()
                except OSError:
                    chunk = ""
            if chunk:
                data = partial + chunk
                lines = data.splitlines(keepends=True)
                partial = (
                    lines.pop() if lines and not lines[-1].endswith(("\n", "\r")) else ""
                )
                for ln in lines:
                    yield ln
                continue

            if self._exit_file.is_file():
                if partial:
                    yield partial
                return

            if time.monotonic() >= grace_until and not self._is_alive():
                # 再读最后一次防止尾行遗漏
                if self._stdout_file.is_file():
                    with (
                        contextlib.suppress(OSError),
                        self._stdout_file.open("r", encoding="utf-8", errors="replace") as fh,
                    ):
                        fh.seek(offset)
                        tail = partial + fh.read()
                        for ln in tail.splitlines(keepends=True):
                            yield ln
                return

            time.sleep(0.04)


class TmuxCoreProcess:
    """在 ``frago-agent-<session_id>`` tmux 会话内托管 ``frago-core`` 的进程句柄。

    完整实现 ``stdin`` / ``stdout`` / ``pid`` / ``returncode`` / ``wait`` / ``terminate`` / ``kill``，
    使上层 ``coreagent_runner`` 与 ``kernel_backend`` 无需重写状态机即可无缝接入。
    """

    def __init__(
        self,
        *,
        session_id: str,
        cmd: list[str],
        cwd: str,
        env: Mapping[str, str] | None,
        mode: str = "resident",
        prompt_text: str | None = None,
        width: int = 200,
        height: int = 50,
    ) -> None:
        self.session_id = session_id
        self.tmux_name = tmux_name_for(session_id)
        self.cwd = cwd
        self.mode = mode
        self.run_dir = Path(
            tempfile.mkdtemp(prefix=f"frago-core-tmux-{session_id[:20]}-")
        )
        self._stdout_file = self.run_dir / "stdout.jsonl"
        self._stderr_file = self.run_dir / "stderr.log"
        self._pid_file = self.run_dir / "core.pid"
        self._exit_file = self.run_dir / "exit.code"
        self._superseded_file = self.run_dir / "superseded"
        self._stdout_file.write_text("", encoding="utf-8")
        self._stderr_file.write_text("", encoding="utf-8")
        (self.run_dir / "stdin.jsonl").write_text("", encoding="utf-8")

        if prompt_text is not None:
            (self.run_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")

        # 单轮模式下将 --output-format json 升级为 stream-json，使窗格能实时打印思考与工具调用，
        # 而末尾的 {"type":"result",...} 行与 json 模式完全一致。
        effective_cmd = list(cmd)
        if mode == "oneshot":
            for i, tok in enumerate(effective_cmd[:-1]):
                if tok == "--output-format" and effective_cmd[i + 1] == "json":
                    effective_cmd[i + 1] = "stream-json"

        full_env = merged_coreagent_env(env, session_id=session_id)
        launch_spec = {
            "session_id": session_id,
            "mode": mode,
            "cmd": effective_cmd,
            "cwd": cwd,
            "env": full_env,
            "pane_log": str(saved_pane_log_path(session_id)),
        }
        (self.run_dir / "launch.json").write_text(
            json.dumps(launch_spec, ensure_ascii=False), encoding="utf-8"
        )

        self._start_tmux_session(full_env, width=width, height=height)
        self.stdin = _TmuxStdin(self.run_dir, self.is_alive)
        self.stdout = _TmuxStdout(self.run_dir, self.is_alive)
        self.pid = self._wait_for_pid()

    def _start_tmux_session(
        self, full_env: Mapping[str, str], *, width: int, height: int
    ) -> None:
        # 若同 session_id 的前序运行仍登记在册，先写 superseded 标记通知旧等待进程立即停止陪跑
        marker = active_run_marker_path(self.session_id)
        with contextlib.suppress(OSError):
            if marker.is_file():
                prev_run = marker.read_text(encoding="utf-8", errors="replace").strip()
                if prev_run:
                    prev_dir = Path(prev_run)
                    if prev_dir != self.run_dir and prev_dir.is_dir():
                        (prev_dir / "superseded").write_text(
                            f"{self.run_dir}\n", encoding="utf-8"
                        )
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(f"{self.run_dir}\n", encoding="utf-8")

        # 若同名旧壳残留，先清掉以免 new-session 撞名退非零
        with contextlib.suppress(Exception):
            subprocess.run(
                ["tmux", "kill-session", "-t", self.tmux_name],
                capture_output=True,
                timeout=5,
            )

        if _WINDOWS:
            bash = _windows_posix_shell()
            if bash:
                with contextlib.suppress(Exception):
                    subprocess.run(
                        ["tmux", "set-option", "-g", "default-shell", bash],
                        capture_output=True,
                        timeout=5,
                    )
                with contextlib.suppress(Exception):
                    subprocess.run(
                        ["tmux", "set-environment", "-g", "SHELL", bash],
                        capture_output=True,
                        timeout=5,
                    )

        argv = [
            "tmux",
            "new-session",
            "-d",
            "-s",
            self.tmux_name,
            "-x",
            str(width),
            "-y",
            str(height),
        ]
        if not _WINDOWS and os.path.isdir(self.cwd):
            argv += ["-c", self.cwd]

        # 注入关键环境变量到 tmux 会话层，满足外部诊断与子进程继承
        for k, v in full_env.items():
            if "\n" not in v and "\x00" not in v and len(v) < 1024:
                argv += ["-e", f"{k}={v}"]

        argv += [
            sys.executable,
            "-u",
            "-m",
            "frago.agent_driver.coreagent_pane_host",
            str(self.run_dir),
        ]
        subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=15,
        )

    def _wait_for_pid(self, timeout_s: float = 3.0) -> int | None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._pid_file.is_file():
                with contextlib.suppress(ValueError, OSError):
                    return int(self._pid_file.read_text(encoding="utf-8").strip())
            if self._exit_file.is_file():
                break
            time.sleep(0.03)
        # 兜底取 tmux pane 的前台 pid
        try:
            proc = subprocess.run(
                ["tmux", "list-panes", "-t", self.tmux_name, "-F", "#{pane_pid}"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            first = (proc.stdout or "").strip().splitlines()
            if first:
                return int(first[0].strip())
        except Exception:
            pass
        return None

    def is_superseded(self) -> bool:
        """判断本轮运行对应的 tmux 窗格是否已被同 session_id 的新一轮运行抢占取代。"""
        if self._superseded_file.is_file():
            return True
        marker = active_run_marker_path(self.session_id)
        if marker.is_file():
            with contextlib.suppress(OSError):
                active = marker.read_text(encoding="utf-8", errors="replace").strip()
                if active and Path(active) != self.run_dir:
                    return True
        return False

    def is_alive(self) -> bool:
        if self._exit_file.is_file() or self.is_superseded():
            return False
        try:
            res = subprocess.run(
                ["tmux", "has-session", "-t", self.tmux_name],
                capture_output=True,
                timeout=5,
            )
            return res.returncode == 0
        except Exception:
            return False

    @property
    def returncode(self) -> int | None:
        if self._exit_file.is_file():
            with contextlib.suppress(ValueError, OSError):
                return int(self._exit_file.read_text(encoding="utf-8").strip())
        if self.is_superseded():
            return 130
        if not self.is_alive():
            return 1
        return None

    def read_stdout(self) -> str:
        if not self._stdout_file.is_file():
            return ""
        with contextlib.suppress(OSError):
            return self._stdout_file.read_text(encoding="utf-8", errors="replace")
        return ""

    def read_stderr(self) -> str:
        if not self._stderr_file.is_file():
            return ""
        with contextlib.suppress(OSError):
            return self._stderr_file.read_text(encoding="utf-8", errors="replace")
        return ""

    def wait(self, timeout: float | None = None) -> int:
        deadline = (time.monotonic() + timeout) if (timeout is not None and timeout > 0) else None
        while True:
            rc = self.returncode
            if rc is not None:
                if not self.is_superseded():
                    self._kill_tmux_quietly()
                return rc
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(cmd=self.tmux_name, timeout=timeout or 0)
            time.sleep(0.05)

    def send_signal(self, sig: int) -> None:
        if sig == signal.SIGTERM:
            self.terminate()
        elif sig == getattr(signal, "SIGKILL", 9):
            self.kill()
        elif self.pid:
            with contextlib.suppress(OSError):
                os.kill(self.pid, sig)

    def terminate(self) -> None:
        self.stdin.close()
        pid = self._wait_for_pid(timeout_s=0.1) or self.pid
        if pid:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGTERM)

    def kill(self) -> None:
        self.stdin.close()
        pid = self._wait_for_pid(timeout_s=0.1) or self.pid
        if pid:
            with contextlib.suppress(OSError):
                os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        self._kill_tmux_quietly()
        self.stdout.close()

    def _kill_tmux_quietly(self) -> None:
        with contextlib.suppress(Exception):
            subprocess.run(
                ["tmux", "kill-session", "-t", self.tmux_name],
                capture_output=True,
                timeout=5,
            )

    def cleanup_runtime_dir(self) -> None:
        with contextlib.suppress(Exception):
            marker = active_run_marker_path(self.session_id)
            if marker.is_file():
                active = marker.read_text(encoding="utf-8", errors="replace").strip()
                if active and Path(active) == self.run_dir:
                    marker.unlink(missing_ok=True)
        with contextlib.suppress(Exception):
            shutil.rmtree(self.run_dir, ignore_errors=True)


# ── Tmux 窗格内宿主入口（由 ``python -u -m frago.agent_driver.coreagent_pane_host <run_dir>`` 拉起） ──


def _pane_host_stop_signals() -> tuple[int, ...]:
    """返回宿主进程需要拦截并级联转发的终止信号集合（非 Windows 含 SIGHUP）。"""
    sigs: list[int] = [signal.SIGTERM, signal.SIGINT]
    if hasattr(signal, "SIGHUP"):
        sigs.append(signal.SIGHUP)
    return tuple(sigs)


def _terminate_process_tree(
    proc: subprocess.Popen[Any] | None,
    grace_timeout: float = 1.0,
) -> None:
    """级联优雅终止 ``proc`` 及其派生的整棵子孙进程树，超时后补发 SIGKILL。

    必须在终止父进程之前先通过 ``psutil.Process(proc.pid).children(recursive=True)``
    收集全部后代快照，防止父进程退出后独立进程组子孙过继为 ``PPID=1`` 孤儿进程。
    对 ``psutil.NoSuchProcess`` / ``AccessDenied`` 全程吞异常防御；无 ``psutil`` 时
    回退至 ``proc.terminate()`` / ``proc.kill()``。
    """
    if proc is None:
        return

    try:
        import psutil
    except ImportError:
        psutil = None  # type: ignore[assignment]

    if psutil is not None:
        targets: list[Any] = []
        parent: Any = None
        try:
            parent = psutil.Process(proc.pid)
            with contextlib.suppress(psutil.Error, OSError):
                targets.extend(parent.children(recursive=True))
            targets.append(parent)
        except (psutil.Error, OSError):
            parent = None

        if targets:
            for target in targets:
                with contextlib.suppress(psutil.Error, OSError):
                    target.terminate()

            _, alive = psutil.wait_procs(targets, timeout=max(0.0, grace_timeout))
            if parent is not None:
                with contextlib.suppress(psutil.Error, OSError):
                    for extra in parent.children(recursive=True):
                        if extra not in alive:
                            alive.append(extra)
            if alive:
                for survivor in alive:
                    with contextlib.suppress(psutil.Error, OSError):
                        survivor.kill()
                with contextlib.suppress(psutil.Error, OSError):
                    psutil.wait_procs(alive, timeout=0.3)

    if proc.poll() is None:
        with contextlib.suppress(Exception):
            proc.terminate()
        try:
            proc.wait(timeout=max(0.1, grace_timeout if psutil is None else 0.2))
        except Exception:  # noqa: BLE001
            with contextlib.suppress(Exception):
                proc.kill()
            with contextlib.suppress(Exception):
                proc.wait(timeout=0.2)


def _run_pane_host(run_dir: Path) -> int:
    launch_path = run_dir / "launch.json"
    spec = json.loads(launch_path.read_text(encoding="utf-8"))
    session_id: str = spec["session_id"]
    mode: str = spec["mode"]
    cmd: list[str] = spec["cmd"]
    cwd: str = spec["cwd"]
    env: dict[str, str] = {**os.environ, **(spec.get("env") or {})}
    pane_log_path = Path(spec["pane_log"]) if spec.get("pane_log") else None

    stdin_file = run_dir / "stdin.jsonl"
    eof_file = run_dir / "stdin.eof"
    stdout_file = run_dir / "stdout.jsonl"
    stderr_file = run_dir / "stderr.log"
    pid_file = run_dir / "core.pid"
    exit_file = run_dir / "exit.code"

    pane_log_lock = threading.Lock()

    def _emit_to_pane(text: str, *, is_err: bool = False) -> None:
        if not text:
            return
        stream = sys.stderr if is_err else sys.stdout
        with contextlib.suppress(OSError):
            stream.write(text)
            stream.flush()
        if pane_log_path is not None:
            with pane_log_lock, contextlib.suppress(OSError):
                pane_log_path.parent.mkdir(parents=True, exist_ok=True)
                with pane_log_path.open("a", encoding="utf-8") as fh:
                    fh.write(text)

    banner = (
        f"\x1b[1;36m━━━ CoreAgent ({mode}) · {session_id} ━━━\x1b[0m\n"
        f"\x1b[2mcwd: {cwd}\x1b[0m\n"
    )
    _emit_to_pane(banner)

    try:
        proc = subprocess.Popen(  # noqa: S603
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd if os.path.isdir(cwd) else None,
            env=env,
            bufsize=1,
        )
    except Exception as exc:  # noqa: BLE001
        msg = f"Failed to spawn frago-core: {type(exc).__name__}: {exc}\n"
        _emit_to_pane(f"\x1b[1;31m{msg}\x1b[0m", is_err=True)
        with contextlib.suppress(OSError):
            stderr_file.write_text(msg, encoding="utf-8")
            exit_file.write_text("2\n", encoding="utf-8")
        return 2

    with contextlib.suppress(OSError):
        pid_file.write_text(f"{proc.pid}\n", encoding="utf-8")

    stop_event = threading.Event()
    received_sig: list[int] = []

    def _forward_sig(signum: int, _frame: Any) -> None:
        if not received_sig:
            received_sig.append(signum)
        stop_event.set()
        with contextlib.suppress(Exception):
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        _terminate_process_tree(proc, grace_timeout=0.8)

    prev_handlers: dict[int, Any] = {}
    for sig in _pane_host_stop_signals():
        with contextlib.suppress(Exception):
            prev_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, _forward_sig)

    def _stderr_pump() -> None:
        if proc.stderr is None:
            return
        try:
            for err_line in proc.stderr:
                with (
                    contextlib.suppress(OSError),
                    stderr_file.open("a", encoding="utf-8") as ef,
                ):
                    ef.write(err_line)
                    ef.flush()
                _emit_to_pane(f"\x1b[2m{err_line}\x1b[0m", is_err=True)
        except Exception:  # noqa: BLE001
            pass

    rc: int = 1
    stderr_thread = threading.Thread(target=_stderr_pump, daemon=True)
    try:
        stderr_thread.start()

        if mode == "oneshot":
            prompt_path = run_dir / "prompt.txt"
            prompt_text = prompt_path.read_text(encoding="utf-8") if prompt_path.is_file() else ""
            _emit_to_pane(format_user_prompt_for_pane(prompt_text))
            with contextlib.suppress(Exception):
                if proc.stdin:
                    proc.stdin.write(prompt_text)
                    proc.stdin.flush()
                    proc.stdin.close()
        else:
            def _stdin_pump() -> None:
                offset = 0
                partial = ""
                while not stop_event.is_set() and proc.poll() is None:
                    chunk = ""
                    if stdin_file.is_file():
                        try:
                            with stdin_file.open("r", encoding="utf-8", errors="replace") as sf:
                                sf.seek(offset)
                                chunk = sf.read()
                                offset = sf.tell()
                        except OSError:
                            chunk = ""
                    if chunk:
                        data = partial + chunk
                        lines = data.splitlines(keepends=True)
                        partial = (
                            lines.pop()
                            if lines and not lines[-1].endswith(("\n", "\r"))
                            else ""
                        )
                        for ln in lines:
                            _echo_user_line_to_pane(ln, _emit_to_pane)
                            try:
                                if proc.stdin and not proc.stdin.closed:
                                    proc.stdin.write(ln)
                                    proc.stdin.flush()
                            except Exception:  # noqa: BLE001
                                return
                        continue
                    if eof_file.is_file():
                        with contextlib.suppress(Exception):
                            if proc.stdin and not proc.stdin.closed:
                                proc.stdin.close()
                        return
                    time.sleep(0.03)

            stdin_thread = threading.Thread(target=_stdin_pump, daemon=True)
            stdin_thread.start()

        if proc.stdout is not None:
            try:
                for out_line in proc.stdout:
                    with (
                        contextlib.suppress(OSError),
                        stdout_file.open("a", encoding="utf-8") as of,
                    ):
                        of.write(out_line)
                        of.flush()
                    rendered = format_stream_line_for_pane(out_line)
                    if rendered:
                        _emit_to_pane(rendered)
            except Exception:  # noqa: BLE001
                pass

        stderr_thread.join(timeout=1.0)
    finally:
        stop_event.set()
        with contextlib.suppress(Exception):
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        _terminate_process_tree(proc, grace_timeout=1.0)
        for sig, prev in prev_handlers.items():
            with contextlib.suppress(Exception):
                signal.signal(sig, prev)
        polled = proc.poll()
        if polled is None:
            with contextlib.suppress(Exception):
                polled = proc.wait(timeout=0.5)
        if polled is not None:
            rc = polled
        elif received_sig:
            rc = 128 + received_sig[0]
        with contextlib.suppress(OSError):
            exit_file.write_text(f"{rc}\n", encoding="utf-8")
    return rc


def _echo_user_line_to_pane(raw_line: str, emit_fn) -> None:
    with contextlib.suppress(Exception):
        obj = json.loads(raw_line)
        content = ((obj.get("message") or {}).get("content")) or ""
        if isinstance(content, str) and content.strip():
            emit_fn(format_user_prompt_for_pane(content))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(2)
    sys.exit(_run_pane_host(Path(sys.argv[1])))
