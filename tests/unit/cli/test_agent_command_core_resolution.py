"""agent_command 中 worker 绑定连接指向未安装内核时的校验与降级单测。"""

from __future__ import annotations

import inspect

import pytest
from click.testing import CliRunner

from frago.cli import agent_command
from frago.init import agent_core, config_manager
from frago.init.models import Config
from frago.init.profile_manager import KIND_ENDPOINT, KIND_VENDOR_CLI, APIProfile


class TestResolveWorkerAgentCore:
    def test_has_explicit_docstring_for_uninstalled_bound_core_tradeoff(self) -> None:
        doc = inspect.getdoc(agent_command._resolve_worker_agent_core)
        assert doc is not None
        assert "resolve_agent_core" in doc
        assert "core_installed" in doc
        assert "worker_connection" in doc
        assert "降级" in doc

    def test_uses_bound_connection_core_when_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(agent_core, "core_installed", lambda t: t == "agy")
        bound = APIProfile(
            id="agy-cli",
            name="Antigravity",
            kind=KIND_VENDOR_CLI,
            endpoint_type="custom",
            agent_type="agy",
        )
        monkeypatch.setattr(agent_command, "_worker_bound_connection", lambda _a=None: bound)

        core, conn, note = agent_command._resolve_worker_agent_core(None, bound)
        assert core == "agy"
        assert conn == bound
        assert note is None

    def test_falls_back_to_coreagent_and_rebinds_when_bound_core_not_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # agy 未安装，coreagent 已安装；且 coreagent 本身没有绑定的连接
        monkeypatch.setattr(agent_core, "core_installed", lambda t: t == "coreagent")
        bound = APIProfile(
            id="agy-cli",
            name="Antigravity",
            kind=KIND_VENDOR_CLI,
            endpoint_type="custom",
            agent_type="agy",
        )
        rebind_calls: list[str | None] = []

        def fake_bound(agent_type: str | None = None):
            rebind_calls.append(agent_type)
            return bound if agent_type is None else None

        monkeypatch.setattr(agent_command, "_worker_bound_connection", fake_bound)

        core, conn, note = agent_command._resolve_worker_agent_core(None, bound)
        assert core == "coreagent"
        assert conn is None
        assert rebind_calls == ["coreagent"]
        assert note is not None and "agy" in note and "coreagent" in note

    def test_falls_back_and_uses_coreagent_specific_connection_if_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(agent_core, "core_installed", lambda t: t == "coreagent")
        bound = APIProfile(
            id="agy-cli",
            name="Antigravity",
            kind=KIND_VENDOR_CLI,
            endpoint_type="custom",
            agent_type="agy",
        )
        core_conn = APIProfile(
            id="ds-core",
            name="DeepSeek Core",
            kind=KIND_ENDPOINT,
            endpoint_type="deepseek",
            api_key="sk-test",
        )
        monkeypatch.setattr(
            agent_command,
            "_worker_bound_connection",
            lambda agent_type=None: core_conn if agent_type == "coreagent" else bound,
        )

        core, conn, note = agent_command._resolve_worker_agent_core(None, bound)
        assert core == "coreagent"
        assert conn == core_conn
        assert note is not None and "agy" in note

    def test_cli_agent_run_degrades_bound_uninstalled_core_with_warning(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg_path = tmp_path / "frago-home" / "config.json"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(config_manager, "CONFIG_PATH", cfg_path)
        config_manager.save_config(Config(agent_core="coreagent"))

        monkeypatch.setattr(agent_core, "core_installed", lambda t: t == "coreagent")
        bound = APIProfile(
            id="agy-cli",
            name="Antigravity",
            kind=KIND_VENDOR_CLI,
            endpoint_type="custom",
            agent_type="agy",
        )
        monkeypatch.setattr(
            agent_command,
            "_worker_bound_connection",
            lambda agent_type=None: None if agent_type == "coreagent" else bound,
        )

        seen: dict[str, object] = {}

        def _not_tmux(*_args, **_kwargs):
            raise AssertionError("绑定连接内核未装时不该走 tmux 驱动")

        def _kernel(_prompt_text, *, agent_type, kernel_profile_id=None, **_kwargs):
            seen["agent_type"] = agent_type
            seen["kernel_profile_id"] = kernel_profile_id

        monkeypatch.setattr(agent_command, "_run_tmux_driver", _not_tmux)
        monkeypatch.setattr(agent_command, "_run_kernel", _kernel)

        res = CliRunner().invoke(agent_command.agent_run, ["hello"])
        assert seen["agent_type"] == "coreagent"
        assert seen["kernel_profile_id"] is None
        assert "agy" in res.stderr
        assert "改用自带内核" in res.stderr
