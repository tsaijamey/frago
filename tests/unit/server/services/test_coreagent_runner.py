"""CoreAgent 那条投喂路：一轮就是一个进程，接着说话靠续接。

盯四件事：

1. 交给内核的那条命令带着**这一场的编号**——续接的全部就在这一句上，缺了它内核会从零开始。
2. 一场会话同一时刻只许一个进程：第二句话当场拒掉，NEVER 收下再让它去搅同一份记录。
3. 那一轮结束后占位要放掉，下一句话照常发得出去。
4. 程序自己发起的会话拿到的是 ``core_`` 开头的编号，并且归进「本机管理」那一组。

不起真进程：跑子进程那一步换成替身。
"""

from __future__ import annotations

import pytest

from frago.server.services import coreagent_runner as cr


@pytest.fixture(autouse=True)
def clean_slate():
    """每条用例都从"没有任何一场在跑"开始。占位是模块级的，用例之间会互相干扰。"""
    cr._running.clear()
    yield
    cr._running.clear()


@pytest.fixture
def fake_binary(monkeypatch, tmp_path):
    binary = tmp_path / "frago-core"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(cr, "binary", lambda: binary)
    return binary


class TestCommand:
    def test_这条命令带着这一场的编号和名字(self, fake_binary):
        cmd = cr.build_command("core_abc", "接着办", cwd="/repos/x", title="定时任务：分类")
        assert "--session-id" in cmd
        assert cmd[cmd.index("--session-id") + 1] == "core_abc"
        assert cmd[cmd.index("--title") + 1] == "定时任务：分类"
        assert cmd[cmd.index("--cwd") + 1] == "/repos/x"
        assert cmd[cmd.index("--prompt") + 1] == "接着办"

    def test_不给名字就不带那个开关(self, fake_binary):
        assert "--title" not in cr.build_command("core_abc", "接着办", cwd="/repos/x")


class TestOneProcessPerSession:
    def test_那一场还在跑时第二句话当场被拒(self, fake_binary, monkeypatch):
        import threading

        started = threading.Event()
        release = threading.Event()

        def slow(*_a, **_k):
            started.set()
            release.wait(5)

        monkeypatch.setattr(cr, "_run", slow)
        cr.send_queued("core_busy", "第一句", cwd="/tmp")
        assert started.wait(2)
        assert cr.running("core_busy")
        with pytest.raises(cr.CoreAgentBusy) as caught:
            cr.send_queued("core_busy", "第二句", cwd="/tmp")
        assert "还在跑" in str(caught.value)
        release.set()

    def test_跑完之后占位放掉下一句照常发(self, fake_binary, monkeypatch):
        calls: list[str] = []

        def quick(session_id, prompt, **kwargs):
            calls.append(prompt)
            kwargs["result"]["text"] = "办好了"
            cr._release(session_id)

        monkeypatch.setattr(cr, "_run", quick)
        first = cr.send("core_ok", "第一句", cwd="/tmp")
        assert first.text == "办好了"
        assert not cr.running("core_ok")
        cr.send("core_ok", "第二句", cwd="/tmp")
        assert calls == ["第一句", "第二句"]

    def test_一轮失败时把原因抛出来(self, fake_binary, monkeypatch):
        def failing(session_id, _prompt, **kwargs):
            kwargs["result"]["error"] = "CoreAgent 还没配连接"
            cr._release(session_id)

        monkeypatch.setattr(cr, "_run", failing)
        with pytest.raises(cr.CoreAgentUnavailable) as caught:
            cr.send("core_bad", "办件事", cwd="/tmp")
        assert "还没配连接" in str(caught.value)

    def test_等不到就先回在跑而不是报错(self, fake_binary, monkeypatch):
        import threading

        release = threading.Event()
        monkeypatch.setattr(cr, "_run", lambda *a, **k: release.wait(5))
        activation = cr.send("core_slow", "办件大事", cwd="/tmp", wait_s=0.2)
        assert activation.status == "activating"
        assert activation.text == ""
        assert cr.running("core_slow"), "还在跑，占位不能提前放掉"
        release.set()


class TestLocalOpsSession:
    def test_编号带core前缀并且归进本机管理组(self, monkeypatch, tmp_path):
        """编号的前缀是会话页认出这一家的判据；归组是为了别把人自己那几场埋掉。"""
        from frago.server.services import workbench_groups as wg

        monkeypatch.setattr(wg, "GROUPS_FILE", tmp_path / "groups.json")
        sid = cr.start_local_ops("待办拟稿")
        assert sid.startswith("core_")

        state = wg.load()
        tag = next(t for t in state["tags"] if t["name"] == wg.LOCAL_OPS_TAG)
        assert state["sessions"][tag["id"]] == [sid]
        assert tag["source"] == "system"

    def test_归组失败不影响这一场跑起来(self, monkeypatch, tmp_path):
        """归类不成是左栏难看，让一次定时任务因此不跑是另一个量级的事。"""
        from frago.server.services import workbench_groups as wg

        def boom(*_a, **_k):
            raise OSError("盘满了")

        monkeypatch.setattr(wg, "file_under", boom)
        assert cr.start_local_ops("定时任务：分类").startswith("core_")
