"""tmux 后端的 env 注入单测。

覆盖 `frago agent` 主干里 tmux_env 的构建（Phase 5 起 tmux 是唯一后端，无需选后端）。
拦截 `_run_tmux_driver` 直接断言它收到的 env，不拉真实 tmux。

背景（spec 20260607 Phase 5 前置）：--endpoint / --api-key / --model 原先只在
旧 headless 路径消费（tmux 分支 return 之后），tmux 路径拿不到，依赖它们的 recipe
无法迁移。本组测试把「三者经 new-session -e 注入」钉死为契约。
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from frago.cli import agent_command
from frago.cli.agent_command import agent


@pytest.fixture
def captured_env(monkeypatch):
    """跑一次 tmux 分支，把 _run_tmux_driver 收到的 env 抓出来。"""
    seen: dict = {}

    def _fake_run_tmux_driver(prompt_text, **kwargs):
        seen["prompt"] = prompt_text
        seen["env"] = kwargs.get("env") or {}
        seen["kwargs"] = kwargs

    monkeypatch.setattr(agent_command, "_run_tmux_driver", _fake_run_tmux_driver)
    # CCR 关掉，隔离出 CLI 覆盖这一层。
    monkeypatch.setattr(agent_command, "should_use_ccr", lambda *_a, **_k: (False, None))
    monkeypatch.setattr(agent_command, "load_frago_config", lambda *_a, **_k: {})

    def _run(*args: str):
        result = CliRunner().invoke(agent, list(args))
        assert result.exit_code == 0, result.output
        return seen

    return _run


@pytest.fixture
def invoke_tmux(monkeypatch):
    """跑 tmux 分支并把完整调用结果交回，供断言 kwargs 或非零退出。"""
    seen: dict = {}

    def _fake_run_tmux_driver(_prompt_text, **kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(agent_command, "_run_tmux_driver", _fake_run_tmux_driver)
    monkeypatch.setattr(agent_command, "should_use_ccr", lambda *_a, **_k: (False, None))
    monkeypatch.setattr(agent_command, "load_frago_config", lambda *_a, **_k: {})

    def _run(*args: str):
        result = CliRunner().invoke(agent, list(args))
        return result, seen

    return _run


def test_resume_marks_native_session_id(invoke_tmux) -> None:
    """--resume <uuid> 必须原样带真实 id 续接，即 native_session_id=True。

    调用方 team_orchestrator 靠 `frago agent --resume <uuid>` 给既有 worker 派指令。
    """
    result, seen = invoke_tmux("--resume", "11111111-2222-3333-4444-555555555555", "go")
    assert result.exit_code == 0, result.output
    assert seen["session_id"] == "11111111-2222-3333-4444-555555555555"
    assert seen["native_session_id"] is True


def test_session_id_stays_non_native(invoke_tmux) -> None:
    # --session-id 是 frago 侧标识，driver 需按 uuid5 派生，不得当真实 id 用。
    result, seen = invoke_tmux("--session-id", "frago-worker-a", "go")
    assert result.exit_code == 0, result.output
    assert seen["session_id"] == "frago-worker-a"
    assert seen["native_session_id"] is False


def test_resume_and_session_id_are_mutually_exclusive(invoke_tmux) -> None:
    # 同时给出即报错退出：一个要 driver 派生、一个要原样续接，无法判定。
    result, _ = invoke_tmux(
        "--resume", "11111111-2222-3333-4444-555555555555",
        "--session-id", "frago-worker-a",
        "go",
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


def test_endpoint_injected_as_base_url(captured_env) -> None:
    env = captured_env("--endpoint", "https://llm.example/v1", "hi")["env"]
    assert env["ANTHROPIC_BASE_URL"] == "https://llm.example/v1"


def test_api_key_injected(captured_env) -> None:
    env = captured_env("--api-key", "sk-test-123", "hi")["env"]
    assert env["ANTHROPIC_API_KEY"] == "sk-test-123"


def test_model_injected_as_anthropic_model(captured_env) -> None:
    # --model 走 ANTHROPIC_MODEL（与 profile 表达模型覆盖的变量同源）。
    env = captured_env("--model", "deepseek-v4-flash", "hi")["env"]
    assert env["ANTHROPIC_MODEL"] == "deepseek-v4-flash"


def test_worker_role_always_marked(captured_env) -> None:
    # 阻断 worker 再拉 worker 的角色递归，与 CLAUDE.md 任务执行模式对齐。
    env = captured_env("hi")["env"]
    assert env["FRAGO_AGENT_ROLE"] == "worker"


def test_no_overrides_leaves_creds_absent(captured_env) -> None:
    """不给覆盖时不得凭空塞凭据键，否则会盖掉 worker 继承的宿主环境。"""
    env = captured_env("hi")["env"]
    for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"):
        assert key not in env


def test_asset_anchor_watch_call_shape(captured_env) -> None:
    """asset_anchor_watch 的真实调用形态（三者同现）必须整体到位。

    该 recipe 是 B 类用途（一次性 LLM 调用）的代表，也是最先撞上这个缺口的调用方。
    """
    env = captured_env(
        "--endpoint", "https://api.deepseek.example/anthropic",
        "--api-key", "sk-anchor",
        "--model", "deepseek-v4-flash",
        "analyze this",
    )["env"]
    assert env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.example/anthropic"
    assert env["ANTHROPIC_API_KEY"] == "sk-anchor"
    assert env["ANTHROPIC_MODEL"] == "deepseek-v4-flash"
