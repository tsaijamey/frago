"""内核偏好接线的单测（spec 20260725-opencode-core-support Phase 5）。

覆盖：配置字段的缺省与往返、设置接口的合法性与"没装就不许选"、两个启动
接口的缺省解析、AgentSession 按内核选 driver、CLI 缺省值随配置变化。
"""

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from frago.init import config_manager
from frago.init.models import Config, known_agent_cores
from frago.server.routes import settings as settings_routes


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 config.json 指向临时目录。

    `config_manager.CONFIG_PATH` 是模块导入期算出来的常量，`mock_home` 之类
    的 Path.home() 打桩对它无效 —— 不改这里，测试会写进真人的 ~/.frago。
    """
    path = tmp_path / "frago-home" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config_manager, "CONFIG_PATH", path)
    return path


@pytest.fixture(autouse=True)
def cores_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认假设"偏好的那家装了"。

    解析内核时会探本机装没装（`frago.init.agent_core.core_installed`），不桩掉的话这
    几条测试的结果会取决于跑测试的机器上装了什么。要验退回自带内核的那条路，用例自己
    再打一次桩。
    """
    from frago.init import agent_core

    monkeypatch.setattr(agent_core, "core_installed", lambda _agent_type: True)


# ============================================================
# 1. 配置字段
# ============================================================


class TestConfigAgentCore:
    def test_defaults_to_the_built_in_core(self):
        # 缺省是自带内核（CoreAgent），不是某一家 CLI：一条 CLI 都没装的机器上，
        # 不点名内核的 `frago agent` 也该跑得起来（2026-10-09 按产品取向改）。
        assert Config().agent_core == "coreagent"

    def test_accepts_every_known_core(self):
        for core in known_agent_cores():
            assert Config(agent_core=core).agent_core == core

    def test_rejects_unknown_core(self):
        with pytest.raises(ValueError):
            Config(agent_core="not-a-core")

    def test_roundtrip_through_config_file(self):
        cfg = config_manager.load_config()
        cfg.agent_core = "opencode"
        config_manager.save_config(cfg)

        assert config_manager.load_config().agent_core == "opencode"
        assert config_manager.get_agent_core() == "opencode"

    def test_get_agent_core_defaults_when_absent(self):
        # 一份完全没有该字段的旧 config.json —— 老用户的现状。
        config_manager.CONFIG_PATH.write_text(
            json.dumps({"schema_version": "1.0"}), encoding="utf-8"
        )

        assert config_manager.get_agent_core() == "coreagent"


# ============================================================
# 2. 设置接口
# ============================================================


@pytest.fixture
def settings_client() -> TestClient:
    app = FastAPI()
    app.include_router(settings_routes.router, prefix="/api")
    return TestClient(app)


def _pretend_installed(monkeypatch: pytest.MonkeyPatch, **installed: bool) -> None:
    monkeypatch.setattr(
        settings_routes, "_agent_core_availability", lambda: dict(installed)
    )


class TestAgentCoreEndpoint:
    def test_get_reports_preference_and_availability(
        self, settings_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        _pretend_installed(monkeypatch, claude=True, opencode=False)

        body = settings_client.get("/api/settings/agent-core").json()

        # 没存过偏好时读出来的是 schema 缺省（自带内核）。
        assert body["agent_core"] == "coreagent"
        assert body["available"] == {"claude": True, "opencode": False}

    def test_put_persists_valid_core(
        self, settings_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        _pretend_installed(monkeypatch, claude=True, opencode=True)

        resp = settings_client.put(
            "/api/settings/agent-core", json={"agent_core": "opencode"}
        )

        assert resp.status_code == 200
        assert resp.json()["agent_core"] == "opencode"
        assert config_manager.load_config().agent_core == "opencode"

    def test_put_rejects_unknown_core(
        self, settings_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        _pretend_installed(monkeypatch, claude=True, opencode=True)

        resp = settings_client.put(
            "/api/settings/agent-core", json={"agent_core": "gpt-whatever"}
        )

        assert resp.status_code == 400
        assert "Unknown agent core" in resp.json()["detail"]
        assert config_manager.load_config().agent_core == "coreagent"

    def test_put_rejects_core_that_is_not_installed(
        self, settings_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        _pretend_installed(monkeypatch, claude=True, opencode=False)

        resp = settings_client.put(
            "/api/settings/agent-core", json={"agent_core": "opencode"}
        )

        assert resp.status_code == 400
        assert "not installed" in resp.json()["detail"]
        assert config_manager.load_config().agent_core == "coreagent"


# ============================================================
# 3. 启动路径的缺省解析
# ============================================================


class TestResolveAgentType:
    def test_explicit_wins(self):
        from frago.server.services.agent_service import resolve_agent_type

        config_manager.save_config(Config(agent_core="claude"))
        assert resolve_agent_type("opencode") == "opencode"

    def test_falls_back_to_preference(self):
        from frago.server.services.agent_service import resolve_agent_type

        config_manager.save_config(Config(agent_core="opencode"))
        assert resolve_agent_type(None) == "opencode"

    def test_falls_back_to_the_built_in_core_without_config(self):
        from frago.server.services.agent_service import resolve_agent_type

        assert resolve_agent_type(None) == "coreagent"

    def test_agent_session_resolves_at_construction(self):
        from frago.server.services.agent_service import AgentSession

        config_manager.save_config(Config(agent_core="opencode"))

        assert AgentSession("id-1", "/tmp").agent_type == "opencode"
        assert AgentSession("id-2", "/tmp", agent_type="claude").agent_type == "claude"


class TestStartEndpointsPassCore:
    """两个 HTTP 启动接口把内核透到服务层；不传时走缺省解析。"""

    @pytest.fixture
    def agent_client(self) -> TestClient:
        from frago.server.routes import agent as agent_routes

        app = FastAPI()
        app.include_router(agent_routes.router, prefix="/api")
        return TestClient(app)

    def test_detached_uses_explicit_core(
        self, agent_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        from frago.server.services.agent_service import AgentService

        seen = {}

        def fake_start(**kwargs):
            seen.update(kwargs)
            return {"status": "ok", "id": "t1", "agent_type": kwargs["agent_type"]}

        monkeypatch.setattr(AgentService, "start_task", staticmethod(fake_start))

        agent_client.post("/api/agent", json={"prompt": "hi", "agent_type": "opencode"})

        assert seen["agent_type"] == "opencode"

    def test_detached_without_core_uses_preference(
        self, agent_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        from frago.server.services import agent_service

        # 这条路会把 prompt 落盘到 `Path.home()/.frago/logs`（运行期现算的路径，
        # 不是模块常量），不打桩就写进真人的 logs 目录。
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        config_manager.save_config(Config(agent_core="opencode"))
        seen = {}

        def fake_bg(cmd, **_kwargs):
            seen["cmd"] = cmd

            class _P:
                pid = 1

            return _P()

        monkeypatch.setattr(agent_service, "run_subprocess_background", fake_bg)

        agent_client.post("/api/agent", json={"prompt": "hi"})

        assert seen["cmd"][seen["cmd"].index("--agent-type") + 1] == "opencode"

    def test_attached_passes_core_through(
        self, agent_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        from frago.server.services.agent_service import AgentService

        seen = {}

        async def fake_attached(**kwargs):
            seen.update(kwargs)
            return {
                "status": "ok",
                "internal_id": "i1",
                "project_path": "/tmp",
            }

        monkeypatch.setattr(
            AgentService, "start_task_attached", classmethod(lambda _cls, **kw: fake_attached(**kw))
        )

        agent_client.post(
            "/api/agent/attached", json={"prompt": "hi", "agent_type": "opencode"}
        )

        assert seen["agent_type"] == "opencode"


# ============================================================
# 4. 命令行缺省值
# ============================================================


class TestCliDefault:
    def _run(self, monkeypatch: pytest.MonkeyPatch, args: list[str]):
        from click.testing import CliRunner

        from frago.cli import agent_command

        seen = {}

        def fake_run(_prompt_text, *, agent_type, **_kwargs):
            seen["agent_type"] = agent_type

        monkeypatch.setattr(agent_command, "_run_tmux_driver", fake_run)

        CliRunner().invoke(agent_command.agent_run, args)
        return seen

    def test_default_follows_config(self, monkeypatch: pytest.MonkeyPatch):
        config_manager.save_config(Config(agent_core="opencode"))
        assert self._run(monkeypatch, ["hello"])["agent_type"] == "opencode"

        config_manager.save_config(Config(agent_core="claude"))
        assert self._run(monkeypatch, ["hello"])["agent_type"] == "claude"

    def test_explicit_flag_overrides_config(self, monkeypatch: pytest.MonkeyPatch):
        config_manager.save_config(Config(agent_core="opencode"))
        seen = self._run(monkeypatch, ["hello", "--agent-type", "claude"])
        assert seen["agent_type"] == "claude"


# ============================================================
# 5. 偏好没装时退回自带内核
# ============================================================


class TestFallBackToBuiltInCore:
    """偏好只是一份偏好：它指向的内核本机没装时退回自带内核，并把换过这件事说出来。

    从前无界面那条是把配置值原样拿去用——那种机器上每一次不点名内核的会话都在启动时
    失败，报的还是驱动层的错，看不出根因是"偏好了一个不存在的东西"。
    """

    def _stub(self, monkeypatch: pytest.MonkeyPatch, installed: set[str]) -> None:
        from frago.init import agent_core

        monkeypatch.setattr(agent_core, "core_installed", lambda t: t in installed)

    def test_keeps_the_preference_when_it_is_installed(self, monkeypatch: pytest.MonkeyPatch):
        from frago.init.agent_core import resolve_agent_core

        self._stub(monkeypatch, {"claude"})
        assert resolve_agent_core("claude") == ("claude", None)

    def test_falls_back_and_explains_when_missing(self, monkeypatch: pytest.MonkeyPatch):
        from frago.init.agent_core import resolve_agent_core

        self._stub(monkeypatch, set())
        core, note = resolve_agent_core("claude")
        assert core == "coreagent"
        assert note and "claude" in note and "coreagent" in note

    def test_built_in_core_missing_stays_put_for_a_specific_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # 自带内核也没装时不装作有：照原样交给内核后端，让它报那句具体的"跑一次 frago init"。
        from frago.init.agent_core import resolve_agent_core

        self._stub(monkeypatch, set())
        assert resolve_agent_core("coreagent") == ("coreagent", None)

    def test_cli_uses_the_fallback_and_says_so(self, monkeypatch: pytest.MonkeyPatch):
        from click.testing import CliRunner

        from frago.cli import agent_command

        self._stub(monkeypatch, set())
        config_manager.save_config(Config(agent_core="claude"))
        seen: dict[str, str] = {}

        def _not_tmux(*_args, **_kwargs):
            raise AssertionError("偏好没装时不该走 tmux 那条路")

        def _kernel(_prompt_text, *, agent_type, **_kwargs):
            seen["agent_type"] = agent_type

        monkeypatch.setattr(agent_command, "_run_tmux_driver", _not_tmux)
        monkeypatch.setattr(agent_command, "_run_kernel", _kernel)
        res = CliRunner().invoke(agent_command.agent_run, ["hello"])

        assert seen["agent_type"] == "coreagent"
        assert "改用自带内核" in res.stderr

    def test_availability_includes_the_built_in_core(self, monkeypatch: pytest.MonkeyPatch):
        from frago.init import agent_core
        from frago.server.routes import settings as settings_routes

        monkeypatch.setattr(agent_core, "kernel_installed", lambda: True)
        assert settings_routes._agent_core_availability()["coreagent"] is True


# ============================================================
# 6. attached 那条路按内核挑后端（tmux 池 / 内核后端）
# ============================================================


@pytest.fixture
def broadcasts(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """截住 WS 广播。两条后端发出去的事件都从这里过。"""
    from frago.server.services import agent_service

    seen: list[dict] = []

    async def _capture(message: dict) -> None:
        seen.append(message)

    monkeypatch.setattr(agent_service.manager, "broadcast", _capture)
    return seen


@pytest.fixture
def kernel_stub(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    """把内核那一侧拦住：不真起进程、不真等一轮。"""
    from frago.server.services import coreagent_runner

    calls: dict[str, list] = {"send": [], "stop": [], "busy": []}

    def _send(session_id, prompt, *, cwd, title=None, wait_s=0.0):
        calls["send"].append((session_id, prompt, cwd))

    def _stop(session_id, **_kwargs):
        calls["stop"].append(session_id)
        return {"running": True, "stopped": True, "busy": False, "dropped": 0}

    def _busy(session_id):
        calls["busy"].append(session_id)
        return False

    monkeypatch.setattr(coreagent_runner, "send", _send)
    monkeypatch.setattr(coreagent_runner, "stop", _stop)
    monkeypatch.setattr(coreagent_runner, "busy", _busy)
    return calls


def _unified(seq: int, kind: str, payload: dict) -> "object":
    from frago.session.unified_record import UnifiedRecord

    return UnifiedRecord(
        id=f"r{seq}", session_id="core_x", group_id=None, seq=seq, ts=0, kind=kind, payload=payload
    )


class TestAttachedPathPicksABackend:
    """这条路的缺省偏好是自带内核；它得走内核后端，而不是被塞进常驻 tmux 池。

    从前是一个不点名内核的请求直接递进池、池拿它去注册表取驱动、取不到就抛
    （2026-10-11 实测 HTTP 500）。
    """

    def test_registered_core_is_kept(self):
        from frago.server.services.agent_service import resolve_attached_agent_type

        config_manager.save_config(Config(agent_core="opencode"))
        assert resolve_attached_agent_type(None) == "opencode"

    def test_explicit_registered_core_is_kept(self):
        from frago.server.services.agent_service import resolve_attached_agent_type

        assert resolve_attached_agent_type("codex") == "codex"

    def test_the_built_in_core_is_kept_for_its_own_backend(self):
        from frago.server.services.agent_service import resolve_attached_agent_type

        # 没存过偏好 → 自带内核。它不被换掉，换的是后端（见 build_attached_session）。
        assert resolve_attached_agent_type(None) == "coreagent"

    def test_unknown_core_raises_a_readable_error(self):
        from frago.server.services.agent_service import (
            UnknownAgentCore,
            resolve_attached_agent_type,
        )

        with pytest.raises(UnknownAgentCore) as excinfo:
            resolve_attached_agent_type("gpt-whatever")
        assert "gpt-whatever" in str(excinfo.value)

    def test_build_picks_the_kernel_session_for_the_built_in_core(self, kernel_stub):
        from frago.server.services.agent_service import (
            KernelAgentSession,
            build_attached_session,
        )

        session = build_attached_session("i-1", "/tmp")

        assert isinstance(session, KernelAgentSession)
        # 编号当场就有：内核那一侧的编号是发起方现发的，没有"等认领"的空窗。
        assert session.session_id.startswith("core_")
        assert session.claude_session_id == session.session_id

    def test_build_picks_the_tmux_session_for_a_registered_core(self):
        from frago.server.services.agent_service import AgentSession, build_attached_session

        config_manager.save_config(Config(agent_core="claude"))

        assert isinstance(build_attached_session("i-2", "/tmp"), AgentSession)

    @pytest.fixture
    def agent_client(self) -> TestClient:
        from frago.server.routes import agent as agent_routes

        app = FastAPI()
        app.include_router(agent_routes.router, prefix="/api")
        return TestClient(app)

    def test_endpoint_start_succeeds_on_the_default_core(
        self, agent_client: TestClient, kernel_stub: dict[str, list]
    ):
        # 缺省配置下这条入口要起得来。从前回 500，detail 是驱动注册表的原话。
        resp = agent_client.post("/api/agent/attached", json={"prompt": "hi"})

        assert resp.status_code == 200
        assert kernel_stub["send"], "这一轮该交给内核那条后端"


class TestKernelAgentSession:
    """内核那一侧的接入：投喂交给 coreagent_runner，正文与工具从会话记录里读出来。"""

    @pytest.mark.asyncio
    async def test_start_hands_the_turn_to_the_kernel_and_announces_the_id(
        self, broadcasts: list[dict], kernel_stub: dict[str, list]
    ):
        from frago.server.services.agent_service import KernelAgentSession

        session = KernelAgentSession("i-1", "/tmp", agent_type="coreagent")
        await session.start("在吗")

        resolved = [m for m in broadcasts if m["type"] == "agent_session_resolved"]
        assert resolved and resolved[0]["session_id"] == session.session_id
        assert kernel_stub["send"] == [(session.session_id, "在吗", "/tmp")]

    @pytest.mark.asyncio
    async def test_records_become_the_same_ws_events_as_the_other_backend(
        self, broadcasts: list[dict], kernel_stub: dict[str, list], monkeypatch: pytest.MonkeyPatch
    ):
        from frago.server.services import agent_service
        from frago.session import record_reader

        records = [
            _unified(0, "agent.say", {"text": "你好"}),
            _unified(
                1,
                "tool.call",
                {"call_id": "c1", "tool_name": "Bash", "args": {"command": "ls"}},
            ),
            _unified(
                2,
                "tool.result",
                {"call_id": "c1", "tool_name": "Bash", "status": "ok", "body": "a b"},
            ),
            # 这条通道不承载的那一类：不该发任何事件出去。
            _unified(3, "usage.tick", {"input_tokens": 10}),
        ]
        served = {"n": 0}

        def _read(session_id, after=0, limit=200, tail=False):
            served["n"] += 1
            if served["n"] > 1:
                return []
            return [r for r in records if r.seq >= after]

        monkeypatch.setattr(record_reader, "read_records", _read)

        session = agent_service.KernelAgentSession("i-1", "/tmp", agent_type="coreagent")
        await session.start("在吗")

        types = [m["type"] for m in broadcasts]
        assert "agent_tool_executing" in types
        assert "agent_tool_result" in types
        assert "agent_session_status" in types
        assert broadcasts[-1]["status"] == "completed"

        text = [m for m in broadcasts if m["type"] == "agent_text_delta"]
        assert [m["content"] for m in text] == ["你好", ""]
        assert [m["done"] for m in text] == [False, True]

        call = next(m for m in broadcasts if m["type"] == "agent_tool_executing")
        assert (call["tool_call_id"], call["tool_name"]) == ("c1", "Bash")
        assert call["parameters"] == {"command": "ls"}

        result = next(m for m in broadcasts if m["type"] == "agent_tool_result")
        assert (result["tool_call_id"], result["success"], result["content"]) == ("c1", True, "a b")

    @pytest.mark.asyncio
    async def test_a_turn_that_never_started_is_visible_not_silent(
        self, broadcasts: list[dict], monkeypatch: pytest.MonkeyPatch
    ):
        # 内核不在 / 没配连接：记录里一个字都没有，页面得看见这句话。
        from frago.server.services import coreagent_runner
        from frago.server.services.agent_service import KernelAgentSession

        def _boom(*_args, **_kwargs):
            raise coreagent_runner.CoreAgentUnavailable("内核还没配连接")

        monkeypatch.setattr(coreagent_runner, "send", _boom)
        monkeypatch.setattr(coreagent_runner, "busy", lambda _sid: False)

        session = KernelAgentSession("i-1", "/tmp", agent_type="coreagent")
        await session.start("在吗")

        text = [m for m in broadcasts if m["type"] == "agent_text_delta"]
        assert any("内核还没配连接" in (m["content"] or "") for m in text)

    @pytest.mark.asyncio
    async def test_stop_stops_the_kernel_session(
        self, broadcasts: list[dict], kernel_stub: dict[str, list]
    ):
        from frago.server.services.agent_service import KernelAgentSession

        session = KernelAgentSession("i-1", "/tmp", agent_type="coreagent")
        await session.start("在吗")
        await session.stop()

        assert kernel_stub["stop"] == [session.session_id]

    @pytest.mark.asyncio
    async def test_follow_up_goes_into_the_same_kernel_session(
        self, broadcasts: list[dict], kernel_stub: dict[str, list]
    ):
        from frago.server.services.agent_service import KernelAgentSession

        session = KernelAgentSession("i-1", "/tmp", agent_type="coreagent")
        await session.start("第一句")
        await session.send_message("第二句")

        assert [c[1] for c in kernel_stub["send"]] == ["第一句", "第二句"]
        # 两句都进同一场：编号从头到尾只有一个。
        assert {c[0] for c in kernel_stub["send"]} == {session.session_id}


class TestTmuxSessionStillEmitsTheSameEvents:
    """另一条后端的发射写法换成了共用的那三处，发出去的事件必须一字不变。"""

    @pytest.mark.asyncio
    async def test_assistant_and_tool_records_map_to_the_same_ws_events(
        self, broadcasts: list[dict]
    ):
        from datetime import datetime

        from frago.server.services.agent_service import AgentSession
        from frago.session.parser import ParsedRecord

        session = AgentSession("i-1", "/tmp", agent_type="claude")
        await session._emit_record(
            ParsedRecord(
                uuid="u1",
                session_id="s1",
                timestamp=datetime.now(),
                record_type="assistant",
                role="assistant",
                content_text="你好",
                tool_calls=[{"id": "c1", "name": "Bash", "input": {"command": "ls"}}],
            )
        )
        await session._emit_record(
            ParsedRecord(
                uuid="u2",
                session_id="s1",
                timestamp=datetime.now(),
                record_type="user",
                role="user",
                tool_results=[{"tool_use_id": "c1", "content": "a b"}],
            )
        )

        text = [m for m in broadcasts if m["type"] == "agent_text_delta"]
        assert [m["content"] for m in text] == ["你好", ""]
        call = next(m for m in broadcasts if m["type"] == "agent_tool_executing")
        assert (call["tool_call_id"], call["tool_name"]) == ("c1", "Bash")
        assert call["parameters"] == {"command": "ls"}
        result = next(m for m in broadcasts if m["type"] == "agent_tool_result")
        # 这条后端的回执不带工具名，得从本场记着的调用里取回来。
        assert (result["tool_call_id"], result["tool_name"], result["success"]) == (
            "c1",
            "Bash",
            True,
        )
