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


# ============================================================
# 1. 配置字段
# ============================================================


class TestConfigAgentCore:
    def test_defaults_to_claude(self):
        assert Config().agent_core == "claude"

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

        assert config_manager.get_agent_core() == "claude"


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

        assert body["agent_core"] == "claude"
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
        assert config_manager.load_config().agent_core == "claude"

    def test_put_rejects_core_that_is_not_installed(
        self, settings_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        _pretend_installed(monkeypatch, claude=True, opencode=False)

        resp = settings_client.put(
            "/api/settings/agent-core", json={"agent_core": "opencode"}
        )

        assert resp.status_code == 400
        assert "not installed" in resp.json()["detail"]
        assert config_manager.load_config().agent_core == "claude"


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

    def test_falls_back_to_claude_without_config(self):
        from frago.server.services.agent_service import resolve_agent_type

        assert resolve_agent_type(None) == "claude"

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
