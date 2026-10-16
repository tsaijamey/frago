"""派活记账的编号换算：这一场 worker 在清单上那一行的编号是什么。

三种情形各一条：三家 CLI 的编号要派生（清单上摆的是派生值）、内核的编号落盘就是它本身、
认不出编号的那几家不记。最后一条是安全边——写一个对不上任何会话的编号进账本，等于在
清单上凭空多出一行点不开的卡片。
"""

from __future__ import annotations

from frago.agent_driver.drivers.claude import claude_session_uuid
from frago.cli import agent_command
from frago.session import session_origin

# frago 那一侧的编号，claude 的编号由它派生。
FRAGO_SID = "d5813c9e-ee2f-48ae-9bb3-f3002134ff2b"
CORE_SID = "core_0123456789abcdef0123456789abcdef"


class TestWorkerChildId:
    def test_claude的编号要派生(self):
        assert (
            agent_command._worker_child_id(FRAGO_SID, agent_type="claude", native_session_id=False)
            == claude_session_uuid(FRAGO_SID)
        )

    def test_claude续接时原样用(self):
        # --resume 带的是 claude 那边的真实编号，再派生一次就对不上了。
        real = "7f55e46e-0cc5-4e80-8f4f-1debd649d7b0"
        assert (
            agent_command._worker_child_id(real, agent_type="claude", native_session_id=True) == real
        )

    def test_内核的编号原样用(self):
        # 内核这一场编号就是 frago 现发的 core_ 前缀，落盘的就是它，不走派生那条路。
        assert (
            agent_command._worker_child_id(CORE_SID, agent_type="coreagent", native_session_id=False)
            == CORE_SID
        )

    def test_认不出编号的那几家不记(self):
        for agent_type in ("opencode", "codex", "agy"):
            assert (
                agent_command._worker_child_id("ses_x", agent_type=agent_type, native_session_id=False)
                is None
            )


class TestRecordWorkerLaunch:
    def test_内核派活记进账本(self, tmp_path, monkeypatch):
        monkeypatch.setattr(session_origin, "LAUNCH_LEDGER", tmp_path / "agent-launches.json")
        monkeypatch.setattr(session_origin, "parent_from_env", lambda: "parent-1")
        agent_command._record_worker_launch(
            sid=CORE_SID,
            agent_type="coreagent",
            cwd="/tmp",
            prompt_text="去把 A 做了",
            native_session_id=False,
        )
        entry = session_origin.find_relation(CORE_SID)
        assert entry is not None
        assert entry["kind"] == "dispatch"
        assert entry["parent"] == "parent-1"

    def test_认不出编号的不写账(self, tmp_path, monkeypatch):
        monkeypatch.setattr(session_origin, "LAUNCH_LEDGER", tmp_path / "agent-launches.json")
        agent_command._record_worker_launch(
            sid="ses_x",
            agent_type="opencode",
            cwd="/tmp",
            prompt_text="",
            native_session_id=False,
        )
        assert not session_origin.LAUNCH_LEDGER.exists()
