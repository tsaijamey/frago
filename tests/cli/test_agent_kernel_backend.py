"""``frago agent --agent-type coreagent`` 走内核后端：分派、连接翻译、退出码、名册。

内核是"交一件事、跑完就退"的进程，不挂 tmux，所以它不进 driver 注册表，走一条并列后端
（见 frago.agent_driver.kernel_backend）。这一组测试拦掉真实的 frago-core，只验接线：

- ``--agent-type coreagent`` 不落到 SessionLauncher（那是 tmux 那条路）；
- ``--use-profile`` 的名字翻成内核要的 **id**（内核按 id 取连接）；
- 四个停机态各自映射到 _EXIT_CODES 那套退出码；
- 名册里记的是内核进程号、tmux_name 为 None，跑完不留死条目。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

import frago.agent_driver as agent_driver_mod
from frago.agent_driver import kernel_backend
from frago.cli import drive_command
from frago.cli.agent_command import agent

PROFILE_NAME = "火山-GLM5.3"
PROFILE_ID = "0ef6d728"

#: 上一次 run_turn 收到的关键字参数，供断言之用。
CALLS: list[dict] = []


def _turn(status="ok", text="answer", duration_ms=5) -> kernel_backend.KernelTurn:
    return kernel_backend.KernelTurn(text=text, status=status, duration_ms=duration_ms)


@pytest.fixture
def drive_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("FRAGO_DRIVE_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def fake_kernel(monkeypatch):
    """拦掉真实的 frago-core；记录收到的参数，进程号借当前进程顶替。"""
    CALLS.clear()

    def _run_turn(prompt, **kwargs):
        CALLS.append({"prompt": prompt, **kwargs})
        on_spawn = kwargs.get("on_spawn")
        if on_spawn is not None:
            on_spawn(os.getpid())
        return _turn()

    monkeypatch.setattr(kernel_backend, "run_turn", _run_turn)
    return CALLS


@pytest.fixture
def fake_profiles(monkeypatch):
    """把 profiles.json 换成一个只有一条的假 store（名字与 id 不同，便于查翻译）。"""
    store = SimpleNamespace(
        profiles=[SimpleNamespace(name=PROFILE_NAME, id=PROFILE_ID)],
        active_profile_id=PROFILE_ID,
    )
    import frago.init.profile_manager as pm

    monkeypatch.setattr(pm, "load_profiles", lambda: store)
    return store


# ── 分派 ────────────────────────────────────────────────────────────────────


def test_coreagent_does_not_reach_the_tmux_launcher(monkeypatch, fake_kernel):
    """--agent-type coreagent 走内核后端，NEVER 落到 SessionLauncher（注册表里没有它）。"""

    class _BoomLauncher:
        def run(self, *_a, **_k):
            raise AssertionError("coreagent 不该走 tmux 那条路")

    monkeypatch.setattr(agent_driver_mod, "SessionLauncher", _BoomLauncher)
    res = CliRunner().invoke(agent, ["--agent-type", "coreagent", "--quiet", "ping"])
    assert res.exit_code == 0, res.stderr
    assert len(fake_kernel) == 1


def test_runs_on_kernel_is_the_single_judgement():
    from frago.agent_driver.driver import runs_on_kernel

    assert runs_on_kernel("coreagent") is True
    for other in ("claude", "codex", "opencode", "corebuddy"):
        assert runs_on_kernel(other) is False


def test_账在进程起来那一刻就记下_不等整轮跑完(monkeypatch, drive_dir):
    """内核 worker 可能跑很久，账要等这一轮结束才写的话，它在左栏整段时间里都是一张散在
    主干上的卡片——2026-10-16 实测：11:32 起的 worker，11:35:27 才落账，这三分多钟里
    父子关系在界面上就是不成立的。"""
    order: list[str] = []
    import frago.session.session_origin as session_origin

    monkeypatch.setattr(
        session_origin,
        "record_dispatch",
        lambda child, **kwargs: order.append("记账") or True,
    )

    def _run_turn(prompt, **kwargs):
        kwargs["on_spawn"](os.getpid())  # 进程起来了
        order.append("喂任务、等它跑完")
        return _turn()

    monkeypatch.setattr(kernel_backend, "run_turn", _run_turn)
    res = CliRunner().invoke(agent, ["--agent-type", "coreagent", "--quiet", "ping"])

    assert res.exit_code == 0, res.stderr
    assert order == ["记账", "喂任务、等它跑完"]


def test_进程没起来就不记账(monkeypatch, drive_dir):
    """Popen 抛错时 on_spawn 不会被叫，账本里也就不该留下点不开的一行。"""
    recorded: list[str] = []
    import frago.session.session_origin as session_origin

    monkeypatch.setattr(
        session_origin,
        "record_dispatch",
        lambda child, **kwargs: recorded.append(child) or True,
    )

    def _run_turn(prompt, **kwargs):
        raise OSError("内核起不来")

    monkeypatch.setattr(kernel_backend, "run_turn", _run_turn)
    res = CliRunner().invoke(agent, ["--agent-type", "coreagent", "--quiet", "ping"])

    assert res.exit_code != 0
    assert recorded == []


# ── 连接翻译：名字 → id ──────────────────────────────────────────────────────


def test_use_profile_name_is_translated_to_the_kernel_id(fake_kernel, fake_profiles):
    res = CliRunner().invoke(
        agent,
        ["--agent-type", "coreagent", "--use-profile", PROFILE_NAME, "--quiet", "ping"],
    )
    assert res.exit_code == 0, res.stderr
    assert fake_kernel[0]["profile_id"] == PROFILE_ID


def test_use_profile_id_passes_through_unchanged(fake_kernel, fake_profiles):
    res = CliRunner().invoke(
        agent,
        ["--agent-type", "coreagent", "--use-profile", PROFILE_ID, "--quiet", "ping"],
    )
    assert res.exit_code == 0, res.stderr
    assert fake_kernel[0]["profile_id"] == PROFILE_ID


def test_no_profile_means_kernel_default_connection(fake_kernel):
    res = CliRunner().invoke(agent, ["--agent-type", "coreagent", "--quiet", "ping"])
    assert res.exit_code == 0, res.stderr
    assert fake_kernel[0]["profile_id"] is None


def test_profile_env_translation_no_longer_raises_for_driverless_agents(fake_profiles):
    """给一个没有 driver 的 agent_type 翻 profile：说清"没生效"，NEVER 抛 KeyError。"""
    from frago.cli.agent_command import _profile_env_via_driver

    env = _profile_env_via_driver(fake_profiles.profiles[0], "coreagent", label="--use-profile X")
    assert env == {}


# ── 退出码契约 ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "expected"),
    [("ok", 0), ("timeout", 1), ("needs_input", 2), ("error", 3)],
)
def test_status_maps_to_the_exit_code_contract(monkeypatch, status, expected):
    monkeypatch.setattr(
        kernel_backend, "run_turn", lambda prompt, **kw: _turn(status=status, text="m")
    )
    res = CliRunner().invoke(agent, ["--agent-type", "coreagent", "--quiet", "ping"])
    assert res.exit_code == expected, res.stderr


def test_json_payload_carries_no_fake_tmux_name(monkeypatch):
    monkeypatch.setattr(kernel_backend, "run_turn", lambda prompt, **kw: _turn(text="hi"))
    res = CliRunner().invoke(agent, ["--agent-type", "coreagent", "--quiet", "--json", "ping"])
    assert res.exit_code == 0, res.stderr
    payload = json.loads(res.stdout)
    assert payload["text"] == "hi"
    assert payload["status"] == "ok"
    assert payload["tmux_name"] is None  # 内核没有 tmux 会话，NEVER 编一个名字出来


def test_session_id_gets_the_core_prefix_when_not_given(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(
        kernel_backend, "run_turn", lambda prompt, **kw: seen.update(kw) or _turn()
    )
    res = CliRunner().invoke(agent, ["--agent-type", "coreagent", "--quiet", "ping"])
    assert res.exit_code == 0, res.stderr
    assert seen["session_id"].startswith("core_")


def test_given_session_id_is_used_as_is(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(
        kernel_backend, "run_turn", lambda prompt, **kw: seen.update(kw) or _turn()
    )
    res = CliRunner().invoke(
        agent,
        ["--agent-type", "coreagent", "--session-id", "core_abc", "--quiet", "ping"],
    )
    assert res.exit_code == 0, res.stderr
    assert seen["session_id"] == "core_abc"


# ── 名册 ────────────────────────────────────────────────────────────────────


def test_kernel_worker_is_registered_with_its_pid_then_removed(drive_dir, monkeypatch):
    seen: dict = {}

    def _run_turn(prompt, **kwargs):
        kwargs["on_spawn"](4242)
        seen["during"] = drive_command._read_entry(kwargs["session_id"])
        return _turn()

    monkeypatch.setattr(kernel_backend, "run_turn", _run_turn)
    res = CliRunner().invoke(agent, ["--agent-type", "coreagent", "--quiet", "ping"])
    assert res.exit_code == 0, res.stderr
    during = seen["during"]
    assert during is not None
    assert during.tmux_name is None
    assert during.pid == 4242  # 记的是内核那个进程，不是外壳自己
    assert during.agent_type == "coreagent"


def test_kernel_worker_roster_entry_is_removed_after_the_turn(drive_dir, monkeypatch):
    monkeypatch.setattr(kernel_backend, "run_turn", lambda prompt, **kw: _turn())
    res = CliRunner().invoke(
        agent, ["--agent-type", "coreagent", "--session-id", "core_zzz", "--quiet", "ping"]
    )
    assert res.exit_code == 0, res.stderr
    assert drive_command._read_entry("core_zzz") is None


def test_ls_reports_pid_liveness_for_kernel_entries(drive_dir):
    drive_command.register_transient_worker(
        name="core_live", agent_type="coreagent", tmux_name=None, cwd=str(drive_dir), pid=os.getpid()
    )
    res = CliRunner().invoke(agent, ["ls"])
    assert res.exit_code == 0, res.stderr
    assert "core_live\tcoreagent" in res.stdout
    assert "alive" in res.stdout


def test_ls_reports_dead_for_an_exited_kernel_pid(drive_dir):
    proc = subprocess.Popen(["sleep", "30"])  # noqa: S603,S607 — 测试用假 worker
    proc.wait()
    drive_command.register_transient_worker(
        name="core_dead", agent_type="coreagent", tmux_name=None, cwd=str(drive_dir), pid=proc.pid
    )
    res = CliRunner().invoke(agent, ["ls"])
    assert res.exit_code == 0, res.stderr
    assert "core_dead\tcoreagent" in res.stdout
    assert "dead" in res.stdout


def test_stop_kills_a_kernel_worker_by_pid(drive_dir):
    proc = subprocess.Popen(["sleep", "30"])  # noqa: S603,S607 — 测试用假 worker
    try:
        drive_command.register_transient_worker(
            name="core_kill", agent_type="coreagent", tmux_name=None,
            cwd=str(drive_dir), pid=proc.pid,
        )
        res = CliRunner().invoke(agent, ["stop", "core_kill"])
        assert res.exit_code == 0, res.stderr
        deadline = time.monotonic() + 5
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        assert proc.poll() is not None
        assert drive_command._read_entry("core_kill") is None
    finally:
        if proc.poll() is None:
            proc.kill()


def test_send_refuses_a_kernel_worker_instead_of_crashing(drive_dir):
    drive_command.register_transient_worker(
        name="core_nostdin", agent_type="coreagent", tmux_name=None, cwd=str(drive_dir), pid=os.getpid()
    )
    res = CliRunner().invoke(agent, ["send", "core_nostdin", "hello"])
    assert res.exit_code == 1
    assert "内核 worker" in res.stderr
