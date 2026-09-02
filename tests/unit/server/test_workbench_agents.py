"""新建会话时能挑哪几家 —— 清单的判据与那条创建接口。

盯的是三件人真会撞上的事：

1. **没装的那一家照样列出来**，只是不可挑并写明为什么。藏起来的话，人只会以为
   "frago 不支持 codex"，而真相往往只是没装。
2. **驱动得动、记录却读不进工作台的那一家不可挑**（codebuddy 就是）。放它进去的结果
   是会话真的起来了、真的在干活，而页面上那一行永远不出现——比不给这个选项坏得多。
3. **清单来自 driver 注册表**，不是一张手写名单。注册了新的一家，它自己就出现在这里；
   前端与后端各写一张，接新家的人改完 driver 会发现界面上它根本不出现。

全程用假的 driver 注册表，NEVER 依赖跑用例这台机器上装了什么——那样的用例在 CI 上和在
本机上答案不一样，而两边都说自己是对的。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from frago.agent_driver.driver import AgentDriver, PaneMatcher
from frago.server.services import workbench_agents


def _driver(agent_type: str, *, display_name: str, locate, accepts_session_id: bool) -> AgentDriver:
    """一个只填了本用例关心的那几格的 driver。行为格子全是占位。"""
    matcher = PaneMatcher(name=f"{agent_type}-x", pattern="x")
    return AgentDriver(
        agent_type=agent_type,
        launch_command=lambda ctx: agent_type,
        ready_signal=matcher,
        submit=lambda session, prompt: None,
        done_signal=matcher,
        extract=lambda delta: delta,
        display_name=display_name,
        locate=locate,
        accepts_session_id=accepts_session_id,
    )


@pytest.fixture
def registry(monkeypatch):
    """一张假注册表：装了的 claude、没装的 codex、记录读不回来的 codebuddy。"""
    drivers = {
        "claude": _driver(
            "claude",
            display_name="Claude Code",
            locate=lambda: "/usr/local/bin/claude",
            accepts_session_id=True,
        ),
        "codex": _driver(
            "codex", display_name="Codex CLI", locate=lambda: None, accepts_session_id=False
        ),
        "opencode": _driver(
            "opencode",
            display_name="opencode",
            locate=lambda: "/opt/homebrew/bin/opencode",
            accepts_session_id=False,
        ),
        "codebuddy": _driver(
            "codebuddy",
            display_name="CodeBuddy Code",
            locate=lambda: "/Applications/WorkBuddy.app/cli",
            accepts_session_id=True,
        ),
    }
    monkeypatch.setattr(workbench_agents, "registered_drivers", lambda: drivers)
    return drivers


def _by_type(agents) -> dict:
    return {a.agent_type: a for a in agents}


class TestList:
    def test_装了且读得回来的那几家可挑(self, registry):
        agents = _by_type(workbench_agents.list_agents())
        assert agents["claude"].selectable is True
        assert agents["claude"].installed is True
        assert agents["claude"].path == "/usr/local/bin/claude"
        assert agents["claude"].reason is None
        assert agents["opencode"].selectable is True

    def test_没装的不藏起来只是不可挑(self, registry):
        """藏掉等于告诉人"frago 不支持它"，而装一下就能用。"""
        agents = _by_type(workbench_agents.list_agents())
        assert "codex" in agents, "没装的那一家 MUST 仍然出现在清单里"
        assert agents["codex"].selectable is False
        assert agents["codex"].installed is False
        assert "没找到" in agents["codex"].reason

    def test_记录读不进工作台的那一家不可挑(self, registry):
        """codebuddy 装着、也驱动得动，但它的记录落在工作台读不到的地方。

        放它进去，人会起一场真的在干活、却永远不出现在左栏的会话。
        """
        agents = _by_type(workbench_agents.list_agents())
        assert agents["codebuddy"].installed is True
        assert agents["codebuddy"].selectable is False
        assert agents["codebuddy"].family is None
        assert "读不进工作台" in agents["codebuddy"].reason

    def test_编号谁来定出自driver而不是名字(self, registry):
        """新建时等不等编号是两种交互，判据 MUST 来自 driver。"""
        agents = _by_type(workbench_agents.list_agents())
        assert agents["claude"].id_origin == "caller"
        assert agents["codex"].id_origin == "claimed"
        assert agents["opencode"].id_origin == "claimed"

    def test_能挑的排在前面(self, registry):
        agents = workbench_agents.list_agents()
        selectable = [a.selectable for a in agents]
        assert selectable == sorted(selectable, reverse=True)

    def test_探测抛异常只算判不出不会拖垮整份清单(self, monkeypatch):
        """一家探测失败 NEVER 让别家也列不出来——那是一次读盘失败换一个空对话框。"""

        def boom():
            raise OSError("PATH 读不动")

        drivers = {
            "claude": _driver(
                "claude", display_name="Claude Code", locate=boom, accepts_session_id=True
            ),
            "opencode": _driver(
                "opencode",
                display_name="opencode",
                locate=lambda: "/bin/opencode",
                accepts_session_id=False,
            ),
        }
        monkeypatch.setattr(workbench_agents, "registered_drivers", lambda: drivers)

        agents = _by_type(workbench_agents.list_agents())
        assert agents["claude"].installed is None
        # 判不出**放行**：拦下来的代价是一台装了的机器用不了，放行只是启动那一刻报错。
        assert agents["claude"].selectable is True
        assert "判不出" in agents["claude"].reason
        assert agents["opencode"].selectable is True

    def test_新注册一家就自己出现在清单里(self, registry, monkeypatch):
        """清单从注册表现算，不是手写名单。"""
        registry["opencode"] = registry["opencode"]
        before = {a.agent_type for a in workbench_agents.list_agents()}
        assert "newcomer" not in before

        registry["newcomer"] = _driver(
            "newcomer", display_name="Newcomer", locate=lambda: "/bin/newcomer",
            accepts_session_id=True,
        )
        after = _by_type(workbench_agents.list_agents())
        assert "newcomer" in after
        # 记录还读不进工作台，所以列出来但不可挑——这正是接新家时该看到的下一步。
        assert after["newcomer"].selectable is False


class TestDefault:
    def test_配好的内核优先(self, registry, monkeypatch):
        monkeypatch.setattr(
            "frago.init.config_manager.get_agent_core", lambda: "opencode", raising=False
        )
        assert workbench_agents.default_agent() == "opencode"

    def test_配好的内核挑不了就退到第一个能挑的(self, registry, monkeypatch):
        monkeypatch.setattr(
            "frago.init.config_manager.get_agent_core", lambda: "codex", raising=False
        )
        # codex 没装，退到清单里第一个能挑的（claude）。
        assert workbench_agents.default_agent() == "claude"

    def test_一家都挑不了时不摆一个必错的默认值(self, monkeypatch):
        drivers = {
            "codex": _driver(
                "codex", display_name="Codex CLI", locate=lambda: None, accepts_session_id=False
            )
        }
        monkeypatch.setattr(workbench_agents, "registered_drivers", lambda: drivers)
        assert workbench_agents.default_agent() is None


class TestRequireSelectable:
    def test_挑不了的当场拒绝并说清为什么(self, registry):
        with pytest.raises(workbench_agents.AgentUnavailable) as e:
            workbench_agents.require_selectable("codex")
        assert "没找到" in str(e.value)

    def test_不认识的名字也拒绝(self, registry):
        with pytest.raises(workbench_agents.AgentUnavailable):
            workbench_agents.require_selectable("nonesuch")


class TestRoutes:
    @pytest.fixture
    def client(self, registry):
        from frago.server.app import create_app

        return TestClient(create_app(), client=("127.0.0.1", 50000))

    def test_清单接口把挑不了的也回给界面(self, client):
        body = client.get("/api/workbench/agents").json()
        types = {a["agent_type"] for a in body["agents"]}
        assert types == {"claude", "codex", "opencode", "codebuddy"}
        codex = next(a for a in body["agents"] if a["agent_type"] == "codex")
        assert codex["selectable"] is False and codex["reason"]

    def test_挑一家挑不了的当场回400而不是起了再说(self, client):
        """起了再说的话，人要等上一分钟才看得出这一场根本不会出现在左栏。"""
        res = client.post(
            "/api/workbench/sessions",
            json={"agent": "codebuddy", "cwd": "/tmp", "text": "干活"},
        )
        assert res.status_code == 400
        assert "读不进工作台" in res.json()["detail"]

    def test_第一句话是空的当场回400(self, client):
        res = client.post(
            "/api/workbench/sessions", json={"agent": "claude", "cwd": "/tmp", "text": "   "}
        )
        assert res.status_code == 400

    def test_问一个不存在的把手回404(self, client):
        """无限轮询一个永远不会有答案的把手，比直说"跟丢了"坏得多。"""
        res = client.get("/api/workbench/sessions/pending/webui-nothing")
        assert res.status_code == 404
