"""Phase 1 单测：claude driver 的 launch_command 拼入 --dangerously-skip-permissions。

tmux 后端注入 prompt 时若卡在权限弹窗，就绪信号永不出现，故启动命令默认免权限确认。
"""

from __future__ import annotations

# 触发 driver 注册
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
    derived = claude_driver._claude_session_uuid("thread-xyz")
    assert f"--session-id {derived}" in cmd
    assert "thread-xyz" not in cmd  # 原始标识不直接出现


def test_launch_resumes_when_transcript_exists(monkeypatch, tmp_path) -> None:
    """非 native：派生 sid 的 transcript 已存在 → 走 --resume 续接（Phase 5）。

    --session-id 撞已存在 transcript 会 'already in use' 退出；重启 / 空闲回收 /
    token 轮换后同一 conv_key 重新拉起即属此情形，必须切 --resume。
    """
    import frago.server.services.transcript_completion as tc

    derived = claude_driver._claude_session_uuid("thread-xyz")
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
    import frago.server.services.transcript_completion as tc

    monkeypatch.setattr(tc, "locate_transcript", lambda *_a, **_k: None)

    driver = load_driver("claude")
    derived = claude_driver._claude_session_uuid("thread-new")
    cmd = driver.launch_command(LaunchCtx(cwd="/home/u", session_id="thread-new"))
    assert f"--session-id {derived}" in cmd
    assert "--resume" not in cmd


def test_launch_resumes_raw_id_when_native() -> None:
    """native_session_id=True：用 --resume 原样带真实 id 续接已存在的 claude 会话。

    这是 WebUI 续接已存在会话的关键。NEVER 用 --session-id——那是"新建"，撞上
    已存在会话会 'already in use' 报错退出（端到端实测确认）。
    """
    real_sid = "7f3c2a10-0b1d-4e2f-9a8b-1c2d3e4f5a6b"
    driver = load_driver("claude")
    cmd = driver.launch_command(
        LaunchCtx(cwd="/tmp", session_id=real_sid, native_session_id=True)
    )
    assert f"--resume {real_sid}" in cmd
    assert "--session-id" not in cmd
    # 没有被套一层 uuid5。
    assert claude_driver._claude_session_uuid(real_sid) not in cmd
