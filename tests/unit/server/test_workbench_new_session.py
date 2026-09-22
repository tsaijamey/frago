"""页面新建一场会话 —— 两条路各走一遍。

盯的是"编号什么时候才有"这件事上最容易出的四种错：

1. claude 的编号是页面这边定的，点完创建**当场**就该有，NEVER 让它也去等；
2. codex / opencode 的编号得等认领，那一段空窗要如实报成"还没有"。假装有了，界面会
   跳进一场并不存在的会话，人看到一片空记录流，以为刚开的会话丢了；
3. 认到编号之后，池里那一场 MUST 同时认这两个名字。不然人接着再发一句话，池里查不到，
   于是又起一个 tmux 去 resume 同一场——两个 TUI 写一份记录，话被吞掉或答案交错；
4. 把手在形状上 NEVER 像某一家的会话编号，否则它会被拿去翻档案、翻出空的，看起来像
   "这场会话没记录"，而它压根不是个会话编号。

全程用假的 runner，不拉真实 tmux。
"""

from __future__ import annotations

import threading

import pytest

from frago.server.services import workbench_agents, workbench_new_session
from frago.session import record_reader
from frago.session.record_reader import UnknownSessionFamily


class FakeRunner:
    """记下每一轮是怎么发的，并让用例决定这一轮什么时候结束。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.aliases: list[tuple[str, str]] = []
        self.evicted: list[str] = []
        self.release = threading.Event()
        self.started = threading.Event()
        self.fail_with: Exception | None = None

    def send(self, session_id, text, *, agent_type, cwd, timeout_s, native_session_id):
        self.calls.append(
            {
                "session_id": session_id,
                "text": text,
                "agent_type": agent_type,
                "cwd": cwd,
                "native_session_id": native_session_id,
            }
        )
        self.started.set()
        self.release.wait(timeout=5)
        if self.fail_with is not None:
            raise self.fail_with
        return None

    def alias(self, alias_id, session_id):
        self.aliases.append((alias_id, session_id))
        return True

    def evict(self, session_id):
        self.evicted.append(session_id)
        return True


@pytest.fixture
def runner(monkeypatch):
    fake = FakeRunner()
    monkeypatch.setattr(
        "frago.server.services.ui_session_runner.get_runner", lambda: fake, raising=False
    )
    return fake


@pytest.fixture
def selectable(monkeypatch):
    """让三家都可挑，免得用例的答案取决于跑它的这台机器上装了什么。"""

    def fake_require(agent_type: str):
        origins = {
            "claude": "caller",
            "codex": "claimed",
            "opencode": "claimed",
            "coreagent": "caller",
        }
        if agent_type not in origins:
            raise workbench_agents.AgentUnavailable(agent_type)
        return workbench_agents.WorkbenchAgent(
            agent_type=agent_type,
            display_name=agent_type,
            installed=True,
            path=f"/bin/{agent_type}",
            family=agent_type,
            selectable=True,
            reason=None,
            id_origin=origins[agent_type],
        )

    monkeypatch.setattr(workbench_agents, "require_selectable", fake_require)


@pytest.fixture
def bindings(monkeypatch):
    """codex 的认领映射：用例往里写一条，就等于"driver 刚认领到了"。"""
    table: dict[str, str] = {}
    monkeypatch.setattr(
        "frago.session.codex_store.get_binding", lambda handle: table.get(handle)
    )
    return table


@pytest.fixture(autouse=True)
def _no_webui_registration(monkeypatch):
    monkeypatch.setattr(
        "frago.session.claude_sessions.register_webui_session", lambda sid: None
    )


def _finish(runner: FakeRunner) -> None:
    """放这一轮走完，并等后台线程收尾（别名、驱逐都在收尾里做）。"""
    runner.release.set()
    for thread in threading.enumerate():
        if thread.name.startswith(("webui-new-session-", "webui-claim-")):
            thread.join(timeout=5)


class _KernelCalls(list):
    """交给内核的那几轮，外加一格"这一轮让它失败"。"""

    def __init__(self) -> None:
        super().__init__()
        self.fail_with: list[Exception] = []


class TestCoreAgent:
    """第三条路：编号当场就有，但第一句话不交给 tmux。

    它没有可挂的 TUI——交一件事、跑完就退。把它当另外三家去起，等来的是一个永远找不到
    的 pane，而页面上只会显示"还在起"。
    """

    @pytest.fixture
    def kernel(self, monkeypatch):
        """记下交给内核的那一轮，不真起进程。"""
        calls = _KernelCalls()

        def fake_send(session_id, prompt, *, cwd, title=None, wait_s=None):
            calls.append(
                {"session_id": session_id, "prompt": prompt, "cwd": cwd, "title": title}
            )
            if calls.fail_with:
                raise calls.fail_with[0]
            return None

        monkeypatch.setattr(
            "frago.server.services.coreagent_runner.send", fake_send, raising=False
        )
        return calls

    @staticmethod
    def _join() -> None:
        for thread in threading.enumerate():
            if thread.name.startswith("webui-new-coreagent-"):
                thread.join(timeout=5)

    def test_编号当场就有且会话页认得出这一家(self, runner, selectable, kernel):
        launch = workbench_new_session.start("coreagent", "/tmp/repo", "帮我把这件事办完")
        self._join()

        assert launch.session_id == launch.handle
        # ``core_`` 前缀是会话页认出这一家的唯一判据，形状不对记录就永远读不回来。
        assert record_reader.detect_family(launch.session_id) == "coreagent"

    def test_第一句话交给内核而不是tmux(self, runner, selectable, kernel):
        launch = workbench_new_session.start("coreagent", "/tmp/repo", "帮我把这件事办完")
        self._join()

        assert runner.calls == [], "CoreAgent MUST NOT 走起 tmux 那条路"
        assert kernel[0]["session_id"] == launch.session_id
        assert kernel[0]["prompt"] == "帮我把这件事办完"
        assert kernel[0]["cwd"] == "/tmp/repo"

    def test_不给它起名字左栏就拿开口第一句当标题(self, runner, selectable, kernel):
        """定时任务那几处才需要 --title：它们的开口第一句是一整段说明书。

        人自己开的这一场相反——开口第一句就是他交代的那件事，与另外三家一致。
        """
        workbench_new_session.start("coreagent", "/tmp/repo", "帮我把这件事办完")
        self._join()
        assert kernel[0]["title"] is None

    def test_调用方给的编号照它那串十六进制拼(self, runner, selectable, kernel):
        """页面把附件落在以调用方那个编号命名的目录下，两边得对得上是哪一场。"""
        given = "550e8400-e29b-41d4-a716-446655440000"
        launch = workbench_new_session.start_with_id(
            "coreagent", "/tmp/repo", "干活", session_id=given
        )
        self._join()
        assert launch.session_id == "core_550e8400e29b41d4a716446655440000"

    def test_内核起不来时如实记下(self, runner, selectable, kernel):
        """没配连接这类失败发生在写下任何一行记录之前，页面上没有别的线索。"""
        kernel.fail_with.append(RuntimeError("还没给 CoreAgent 配连接"))
        launch = workbench_new_session.start("coreagent", "/tmp/repo", "干活")
        self._join()

        assert launch.finished is True
        assert "配连接" in (launch.error or "")


class TestCallerMintsTheId:
    def test_claude_点完创建当场就有编号(self, runner, selectable):
        launch = workbench_new_session.start("claude", "/tmp/repo", "干活")
        assert launch.session_id == launch.handle
        assert launch.session_id and not launch.session_id.startswith(
            workbench_new_session.HANDLE_PREFIX
        )
        runner.started.wait(timeout=5)
        assert runner.calls[0]["native_session_id"] is True
        assert runner.calls[0]["cwd"] == "/tmp/repo"
        _finish(runner)

    def test_编号是一个能被工作台认出来的claude会话编号(self, runner, selectable):
        """页面拿它去问记录、去发下一句话，两条路都靠这一步判家族。"""
        launch = workbench_new_session.start("claude", "/tmp/repo", "干活")
        assert record_reader.detect_family(launch.session_id) == "claude-code"
        _finish(runner)


class TestClaimedId:
    def test_codex_创建那一刻还没有编号(self, runner, selectable, bindings):
        launch = workbench_new_session.start("codex", "/tmp/repo", "干活")
        assert launch.session_id is None, "编号还没认到就 MUST 报没有，NEVER 编一个"
        runner.started.wait(timeout=5)
        assert runner.calls[0]["native_session_id"] is False
        _finish(runner)

    def test_把手形状上不像任何一家的会话编号(self, runner, selectable, bindings):
        """像的话它会被拿去翻档案、翻出空的，看起来像"这场会话没记录"。"""
        launch = workbench_new_session.start("codex", "/tmp/repo", "干活")
        assert launch.handle.startswith(workbench_new_session.HANDLE_PREFIX)
        with pytest.raises(UnknownSessionFamily):
            record_reader.detect_family(launch.handle)
        _finish(runner)

    def test_认领到编号后报出来并让池里那一场也认这个名字(
        self, runner, selectable, bindings
    ):
        launch = workbench_new_session.start("codex", "/tmp/repo", "干活")
        runner.started.wait(timeout=5)

        # driver 在首轮进行当中认领到了编号。
        bindings[launch.handle] = "01a01a98-82e9-7013-b24e-e5e91b03995a"

        deadline = threading.Event()
        for _ in range(40):
            status = workbench_new_session.status(launch.handle)
            if status and status.session_id:
                break
            deadline.wait(0.1)
        status = workbench_new_session.status(launch.handle)
        assert status.session_id == "01a01a98-82e9-7013-b24e-e5e91b03995a"
        # 同一个 TUI 两个名字，池里只有一份——不然下一句话会起第二个 tmux。
        assert (
            "01a01a98-82e9-7013-b24e-e5e91b03995a",
            launch.handle,
        ) in runner.aliases
        _finish(runner)

    def test_首轮跑完就把以把手为键的那一场收走(self, runner, selectable, bindings):
        """别名只是进程内的一张表，服务一重启就没了；留着 tmux 会让下一次 resume
        撞上一个还活着的同一场会话。"""
        launch = workbench_new_session.start("codex", "/tmp/repo", "干活")
        runner.started.wait(timeout=5)
        _finish(runner)
        assert runner.evicted == [launch.handle]


class TestFailures:
    def test_起不来时把原话记下来而不是无限等(self, runner, selectable, bindings):
        runner.fail_with = RuntimeError("tmux 没起来")
        launch = workbench_new_session.start("codex", "/tmp/repo", "干活")
        runner.started.wait(timeout=5)
        _finish(runner)

        status = workbench_new_session.status(launch.handle)
        assert status.finished is True
        assert status.session_id is None
        assert "tmux 没起来" in status.error

    def test_挑不了的那一家在起会话之前就拦下(self, runner, selectable):
        with pytest.raises(workbench_agents.AgentUnavailable):
            workbench_new_session.start("codebuddy", "/tmp/repo", "干活")
        assert runner.calls == [], "拦下了就一轮都不该发出去"

    def test_没有这个把手时报没有(self):
        assert workbench_new_session.status("webui-never-existed") is None
