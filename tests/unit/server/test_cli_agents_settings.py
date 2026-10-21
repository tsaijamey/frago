"""设置页「CLI 客户端」分区接口与 OpenCode 后台服务开关测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from frago.agent_driver.driver import AgentDriver, PaneMatcher
from frago.server.routes import settings as settings_route
from frago.session import engine_cli, opencode_store

_DUMMY = PaneMatcher(name="x", pattern="x")


def _fake_driver(agent_type: str, display_name: str, path: str | None) -> AgentDriver:
    return AgentDriver(
        agent_type=agent_type,
        display_name=display_name,
        locate=lambda: path,
        launch_command=lambda _ctx: agent_type,
        ready_signal=_DUMMY,
        submit=lambda _s, _p: None,
        done_signal=_DUMMY,
        extract=lambda _p: "",
    )


def test_cli_agents_status_orders_detected_first_and_reads_opencode_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg_dir = tmp_path / "opencode"
    cfg_dir.mkdir()
    # 包含敏感字段 password，验证接口只读布尔 disabled、绝不泄露口令
    (cfg_dir / "service.json").write_text(
        json.dumps({"password": "secret-do-not-expose", "disabled": True}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(opencode_store, "_standalone_flag", lambda: "--standalone")
    monkeypatch.setattr(
        "frago.agent_driver.driver.registered_drivers",
        lambda: {
            "codex": _fake_driver("codex", "Codex CLI", None),
            "opencode": _fake_driver("opencode", "opencode", "/opt/homebrew/bin/opencode"),
            "claude": _fake_driver("claude", "Claude Code", "/usr/local/bin/claude"),
        },
    )

    resp = settings_route._cli_agents_status()

    assert [a.agent_type for a in resp.agents] == ["claude", "opencode", "codex"]
    assert [a.installed for a in resp.agents] == [True, True, False]
    oc = resp.agents[1]
    assert oc.opencode_service is not None
    assert oc.opencode_service.supported is True
    assert oc.opencode_service.disabled is True
    assert "secret-do-not-expose" not in resp.model_dump_json()


@pytest.mark.asyncio
async def test_put_opencode_service_setting_runs_set_and_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg_dir = tmp_path / "opencode"
    cfg_dir.mkdir()
    service_file = cfg_dir / "service.json"
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(opencode_store, "_standalone_flag", lambda: "--standalone")
    monkeypatch.setattr(
        "frago.agent_driver.driver.registered_drivers",
        lambda: {
            "opencode": _fake_driver("opencode", "opencode", "/opt/homebrew/bin/opencode"),
        },
    )

    calls: list[tuple[str, list[str]]] = []

    def fake_run(agent: str, argv: list[str], **_kwargs):
        calls.append((agent, list(argv)))
        if argv == ["service", "set", "disabled", "true"]:
            service_file.write_text(json.dumps({"disabled": True}), encoding="utf-8")
        elif argv == ["service", "unset", "disabled"]:
            service_file.write_text(json.dumps({}), encoding="utf-8")
        return engine_cli.EngineCommandResult(argv=argv, output="")

    monkeypatch.setattr(engine_cli, "run_engine_command", fake_run)

    res_on = await settings_route.put_opencode_service_setting(
        settings_route.OpencodeServiceUpdateRequest(disabled=True)
    )
    assert calls[-1] == ("opencode", ["service", "set", "disabled", "true"])
    assert res_on.agents[0].opencode_service is not None
    assert res_on.agents[0].opencode_service.disabled is True

    res_off = await settings_route.put_opencode_service_setting(
        settings_route.OpencodeServiceUpdateRequest(disabled=False)
    )
    assert calls[-1] == ("opencode", ["service", "unset", "disabled"])
    assert res_off.agents[0].opencode_service is not None
    assert res_off.agents[0].opencode_service.disabled is False
