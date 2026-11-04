"""CoreAgent 在 tmux 窗格内运行、无 tmux 自动回退，以及工作台 Terminal View 抓屏接口单测。"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from frago.agent_driver import coreagent_pane_host as host
from frago.agent_driver import kernel_backend
from frago.server.services import agent_sessions_service as asvc
from frago.server.services import coreagent_runner as cr
from frago.server.services import tmux_sessions_service as tsvc


class TestPaneFormatting:
    """把 frago-core 的 stream-json 事件流转成终端可读的 ANSI 行。"""

    def test_formats_init_assistant_tool_and_result(self):
        init_line = '{"type":"system","subtype":"init","session_id":"core_1","model":"deepseek","cwd":"/repo"}'
        assert "session=core_1" in host.format_stream_line_for_pane(init_line)

        asst_line = (
            '{"type":"assistant","message":{"content":['
            '{"type":"text","text":"先查一下目录"},'
            '{"type":"tool_use","name":"Bash","input":{"command":"ls -la"}}'
            "]}}"
        )
        rendered_asst = host.format_stream_line_for_pane(asst_line)
        assert "先查一下目录" in rendered_asst
        assert "Bash" in rendered_asst
        assert "ls -la" in rendered_asst

        user_line = (
            '{"type":"user","message":{"content":['
            '{"type":"tool_result","is_error":false,"content":"〔rules guidance〕x〔tool output〕file1.py\\nfile2.py"}'
            "]}}"
        )
        rendered_user = host.format_stream_line_for_pane(user_line)
        assert "file1.py" in rendered_user
        assert "rules guidance" not in rendered_user

        res_line = '{"type":"result","subtype":"success","is_error":false,"num_turns":2,"duration_ms":350,"result":"搞定了"}'
        rendered_res = host.format_stream_line_for_pane(res_line)
        assert "Turn complete" in rendered_res
        assert "350ms" in rendered_res

    def test_formats_user_prompt_banner(self):
        out = host.format_user_prompt_for_pane("帮我检查配置")
        assert "❯" in out
        assert "帮我检查配置" in out


class TestNoTmuxFallback:
    """当环境无 tmux（或显式设了 FRAGO_COREAGENT_NO_TMUX=1）时，WebUI 与 CLI Worker 自动回退直跑。"""

    def test_tmux_available_respects_env_disable(self, monkeypatch):
        monkeypatch.setenv("FRAGO_COREAGENT_NO_TMUX", "1")
        assert host.tmux_available() is False
        assert kernel_backend._should_use_tmux() is False
        assert cr._should_use_tmux() is False

    def test_kernel_run_turn_falls_back_to_direct_process_without_tmux(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("FRAGO_COREAGENT_NO_TMUX", "1")
        fake_bin = tmp_path / "frago-core"
        fake_bin.write_text(
            "#!/bin/sh\n"
            "cat >/dev/null\n"
            'echo \'{"type":"result","subtype":"success","is_error":false,"result":"FALLBACK_OK"}\'\n',
            encoding="utf-8",
        )
        fake_bin.chmod(0o755)
        monkeypatch.setattr(kernel_backend, "kernel_path", lambda: fake_bin)

        spawned: list[tuple[int, str | None]] = []
        turn = kernel_backend.run_turn(
            "ping",
            session_id="core_fallback_test",
            cwd=str(tmp_path),
            on_spawn=lambda pid, tmux_name=None: spawned.append((pid, tmux_name)),
        )
        assert turn.status == "ok"
        assert turn.text == "FALLBACK_OK"
        assert turn.tmux_name is None
        assert len(spawned) == 1
        assert spawned[0][1] is None


@pytest.mark.skipif(shutil.which("tmux") is None, reason="需要本机安装 tmux")
class TestRealTmuxCoreAgentExecution:
    """在真实 tmux 会话里跑单轮与常驻 CoreAgent 替身，验证读屏、环境变量与结果回传。"""

    def test_kernel_run_turn_runs_in_tmux_and_returns_exact_result(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("FRAGO_COREAGENT_NO_TMUX", raising=False)
        monkeypatch.setenv("FRAGO_COREAGENT_PANES_DIR", str(tmp_path / "panes"))

        fake_bin = tmp_path / "frago-core"
        fake_bin.write_text(
            "#!/bin/sh\n"
            "Prompt=$(cat)\n"
            'echo "progress on stderr: role=$FRAGO_AGENT_ROLE" >&2\n'
            'echo \'{"type":"assistant","message":{"content":[{"type":"text","text":"正在处理任务"}]}}\'\n'
            'echo \'{"type":"result","subtype":"success","is_error":false,"num_turns":1,"duration_ms":12,"result":"TMUX_WORKER_DONE"}\'\n',
            encoding="utf-8",
        )
        fake_bin.chmod(0o755)
        monkeypatch.setattr(kernel_backend, "kernel_path", lambda: fake_bin)

        sid = f"core_tmux_oneshot_{os.getpid()}"
        spawned: list[tuple[int, str | None]] = []
        turn = kernel_backend.run_turn(
            "请执行子任务",
            session_id=sid,
            cwd=str(tmp_path),
            env={"FRAGO_AGENT_ROLE": "worker"},
            on_spawn=lambda pid, tmux_name=None: spawned.append((pid, tmux_name)),
        )

        assert turn.status == "ok"
        assert turn.text == "TMUX_WORKER_DONE"
        assert turn.tmux_name == f"frago-agent-{sid}"
        assert spawned and spawned[0][1] == f"frago-agent-{sid}"

        # 单轮跑完后 tmux 已退出，但留底终端日志里完整保留了提问、思考、stderr 与完成标记
        saved_log = host.read_saved_pane_log(sid)
        assert "请执行子任务" in saved_log
        assert "正在处理任务" in saved_log
        assert "role=worker" in saved_log
        assert "Turn complete" in saved_log

    def test_resident_coreagent_in_tmux_can_be_captured_live(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("FRAGO_COREAGENT_NO_TMUX", raising=False)
        monkeypatch.setenv("FRAGO_COREAGENT_PANES_DIR", str(tmp_path / "panes"))

        fake_bin = tmp_path / "frago-core"
        fake_bin.write_text(
            "#!/usr/bin/env python3\n"
            "import os, sys, json\n"
            "sys.stderr.write(f'booted review={os.environ.get(\"FRAGO_REVIEW\")}\\n')\n"
            "sys.stderr.flush()\n"
            "for line in sys.stdin:\n"
            "    if not line.strip(): continue\n"
            "    sys.stdout.write(json.dumps({'type':'assistant','message':{'content':[{'type':'text','text':'收到常驻指令'}]}}, ensure_ascii=False) + '\\n')\n"
            "    sys.stdout.write(json.dumps({'type':'result','subtype':'success','is_error':False,'num_turns':1,'duration_ms':5,'result':'RESIDENT_OK'}, ensure_ascii=False) + '\\n')\n"
            "    sys.stdout.flush()\n",
            encoding="utf-8",
        )
        fake_bin.chmod(0o755)

        sid = f"core_tmux_resident_{os.getpid()}"
        proc = host.TmuxCoreProcess(
            session_id=sid,
            cmd=[str(fake_bin), "--mode", "agent", "--input-format", "stream-json", "--output-format", "stream-json"],
            cwd=str(tmp_path),
            env={"FRAGO_REVIEW": "off"},
            mode="resident",
        )
        try:
            proc.stdin.write(cr._user_line("第一轮常驻指令") + "\n")
            lines = []
            for ln in proc.stdout:
                lines.append(ln)
                if '"type": "result"' in ln or '"type":"result"' in ln:
                    break
            assert any("RESIDENT_OK" in ln for ln in lines)

            # 此时常驻进程仍活在 tmux 里，capture_session_terminal 能直接抓到实时屏幕
            snap = tsvc.capture_session_terminal(sid)
            assert snap["alive"] is True
            assert snap["source"] == "tmux"
            assert snap["tmux_name"] == f"frago-agent-{sid}"
            assert "第一轮常驻指令" in snap["content"]
            assert "收到常驻指令" in snap["content"]
        finally:
            proc.kill()
            proc.cleanup_runtime_dir()


class TestTerminalApiAndDeduplication:
    """验证 /api/workbench/sessions/{sid}/terminal 端点与会话计数去重。"""

    def test_terminal_endpoint_returns_live_or_saved_content(self, monkeypatch, tmp_path):
        from frago.server.app import create_app

        monkeypatch.setenv("FRAGO_COREAGENT_PANES_DIR", str(tmp_path / "panes"))
        sid = "core_api_term_test"
        log_file = host.saved_pane_log_path(sid)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("saved terminal output line 1\nline 2\n", encoding="utf-8")

        monkeypatch.setattr(tsvc, "find_for_session", lambda _sid: None)
        client = TestClient(create_app(), client=("127.0.0.1", 50000))
        resp = client.get(f"/api/workbench/sessions/{sid}/terminal?lines=200")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == sid
        assert body["alive"] is False
        assert body["source"] == "saved_pane"
        assert "saved terminal output line 1" in body["content"]

    def test_agent_sessions_service_deduplicates_tmux_backed_coreagent(self, monkeypatch):
        snap = cr.LiveSessionSnapshot(
            session_id="core_dup1",
            state="busy",
            pid=999,
            cwd="/repo",
            title="Core Task",
            touched_at=time.time(),
            tmux_name="frago-agent-core_dup1",
        )
        monkeypatch.setattr(cr, "live_snapshot", lambda: [snap])
        monkeypatch.setattr(
            tsvc,
            "count_sessions",
            lambda: {"total": 1, "total_memory_mb": 120},
        )
        monkeypatch.setattr(
            tsvc,
            "open_session_names",
            lambda: {"frago-agent-core_dup1"},
        )
        monkeypatch.setattr(tsvc, "memory_by_pid", lambda: {999: 120})

        counted = asvc.count_sessions()
        # 已经在 tmux 里的 CoreAgent 不得被重复累加第二次
        assert counted["total"] == 1
        assert counted["total_memory_mb"] == 120
