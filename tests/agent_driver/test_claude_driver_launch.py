"""Phase 1 单测：claude driver 的 launch_command 拼入 --dangerously-skip-permissions。

tmux 后端注入 prompt 时若卡在权限弹窗，就绪信号永不出现，故启动命令默认免权限确认。
"""

from __future__ import annotations

import json
import stat

# 触发 driver 注册
from pathlib import Path

import frago.agent_driver.drivers.claude as claude_driver  # noqa: F401
from frago.agent_driver import load_driver
from frago.agent_driver.driver import LaunchCtx


def test_launch_command_includes_skip_permissions() -> None:
    driver = load_driver("claude")
    cmd = driver.launch_command(LaunchCtx(cwd="/tmp", session_id="s1"))
    assert "--dangerously-skip-permissions" in cmd
    assert cmd.startswith("claude")


def test_launch_derives_uuid5_by_default() -> None:
    """默认（非 native）：frago 标识经 uuid5 派生成合法 claude 会话 id。"""
    driver = load_driver("claude")
    cmd = driver.launch_command(LaunchCtx(cwd="/tmp", session_id="thread-xyz"))
    derived = claude_driver.claude_session_uuid("thread-xyz")
    assert f"--session-id {derived}" in cmd
    assert "thread-xyz" not in cmd  # 原始标识不直接出现


def test_launch_resumes_when_transcript_exists(monkeypatch, tmp_path) -> None:
    """非 native：派生 sid 的 transcript 已存在 → 走 --resume 续接（Phase 5）。

    --session-id 撞已存在 transcript 会 'already in use' 退出；重启 / 空闲回收 /
    token 轮换后同一 conv_key 重新拉起即属此情形，必须切 --resume。
    """
    import frago.session.transcript_completion as tc

    derived = claude_driver.claude_session_uuid("thread-xyz")
    fake = tmp_path / f"{derived}.jsonl"
    fake.write_text("{}\n")

    def _locate(session_id, cwd=None, projects_root=None):  # noqa: ARG001
        return fake if session_id == derived else None

    monkeypatch.setattr(tc, "locate_transcript", _locate)

    driver = load_driver("claude")
    cmd = driver.launch_command(LaunchCtx(cwd="/home/u", session_id="thread-xyz"))
    assert f"--resume {derived}" in cmd
    assert "--session-id" not in cmd


def test_launch_session_id_when_transcript_absent(monkeypatch) -> None:
    """非 native：派生 sid 的 transcript 不存在 → 首次创建走 --session-id。"""
    import frago.session.transcript_completion as tc

    monkeypatch.setattr(tc, "locate_transcript", lambda *_a, **_k: None)

    driver = load_driver("claude")
    derived = claude_driver.claude_session_uuid("thread-new")
    cmd = driver.launch_command(LaunchCtx(cwd="/home/u", session_id="thread-new"))
    assert f"--session-id {derived}" in cmd
    assert "--resume" not in cmd


def test_launch_resumes_raw_id_when_native_and_transcript_exists(monkeypatch) -> None:
    """native + transcript 已存在：用 --resume 原样带真实 id 续接。

    这是 WebUI 点开页面上某个已有会话的路径。此时 NEVER 用 --session-id——那是
    "新建"，撞上已存在会话会 'already in use' 报错退出（端到端实测确认）。
    """
    import frago.session.transcript_completion as tc

    monkeypatch.setattr(tc, "locate_transcript", lambda *_a, **_k: Path("/tmp/x.jsonl"))

    real_sid = "7f3c2a10-0b1d-4e2f-9a8b-1c2d3e4f5a6b"
    driver = load_driver("claude")
    cmd = driver.launch_command(
        LaunchCtx(cwd="/tmp", session_id=real_sid, native_session_id=True)
    )
    assert f"--resume {real_sid}" in cmd
    assert "--session-id" not in cmd
    # 没有被套一层 uuid5。
    assert claude_driver.claude_session_uuid(real_sid) not in cmd


def test_launch_creates_raw_id_when_native_and_no_transcript(monkeypatch) -> None:
    """native + transcript 不存在：用 --session-id 以该真实 id 新建会话。

    这是 WebUI「新建会话」的路径——页面先 mint 一个 uuid 再发第一轮。对不存在的
    id 用 --resume 同样起不来，故这个二分是必须的。
    """
    import frago.session.transcript_completion as tc

    monkeypatch.setattr(tc, "locate_transcript", lambda *_a, **_k: None)

    fresh_sid = "1c9e5d84-77aa-4a31-8f60-2b5d9c3e7a04"
    driver = load_driver("claude")
    cmd = driver.launch_command(
        LaunchCtx(cwd="/tmp", session_id=fresh_sid, native_session_id=True)
    )
    assert f"--session-id {fresh_sid}" in cmd
    assert "--resume" not in cmd
    # 同样不套 uuid5：页面读的就是这个 id。
    assert claude_driver.claude_session_uuid(fresh_sid) not in cmd


def test_launch_without_profile_env_has_no_settings_flag() -> None:
    """没点名连接、也没绑 worker 连接时，启动命令与从前一字不差。

    只有会话身份（FRAGO_*）那几项时不加 ``--settings``：它们与 settings.json 不同名，
    照旧走会话环境。
    """
    driver = load_driver("claude")
    cmd = driver.launch_command(
        LaunchCtx(cwd="/tmp", session_id="s1", env={"FRAGO_CONV_KEY": "x"})
    )
    assert "--settings" not in cmd


def test_launch_passes_profile_env_through_settings_file(monkeypatch, tmp_path) -> None:
    """点名了连接：值经 ``--settings`` 递进去，它压得过用户 settings.json 的 env 段。

    2026-10-16 隔离实验判死的那一层：claude 启动时把 ``~/.claude/settings.json`` 的
    env 段套进自己的进程环境，光靠 tmux ``-e`` 注入的连接一次都生效不了——会话看着
    正常，其实跑在用户全局那条连接上。``--settings`` 的优先级在用户设置之上。
    """
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    driver = load_driver("claude")
    cmd = driver.launch_command(
        LaunchCtx(
            cwd="/tmp",
            session_id="sess-1",
            env={
                "ANTHROPIC_BASE_URL": "http://127.0.0.1:8787/agy",
                "ANTHROPIC_API_KEY": "local-proxy",
                "FRAGO_SESSION_ID": "sess-1",
            },
        )
    )

    path = claude_driver._session_settings_path("sess-1")
    assert str(path) in cmd
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8787/agy"
    assert payload["env"]["ANTHROPIC_API_KEY"] == "local-proxy"
    # 会话身份不绕这一道。
    assert "FRAGO_SESSION_ID" not in payload["env"]
    # 里面是连接密钥，文件权限收紧到只有主人可读。
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # 值走文件、命令行上只有路径：启动命令会原样留在 pane 与记录里。
    assert "local-proxy" not in cmd


def test_launch_settings_file_is_overwritten_per_session(monkeypatch, tmp_path) -> None:
    """同一场会话重新拉起时，设置文件被这一轮的值覆盖，不留上一轮的残留。"""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    driver = load_driver("claude")
    for key in ("first-key", "second-key"):
        driver.launch_command(
            LaunchCtx(
                cwd="/tmp",
                session_id="sess-2",
                env={"ANTHROPIC_API_KEY": key},
            )
        )
    payload = json.loads(
        claude_driver._session_settings_path("sess-2").read_text(encoding="utf-8")
    )
    assert payload["env"]["ANTHROPIC_API_KEY"] == "second-key"
