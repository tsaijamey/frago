"""Phase 1 单测：resolve_backend() 的解析优先级。

config.json primary_agent.agent_backend > env FRAGO_AGENT_DRIVER=tmux > 默认 tmux。
"""

from __future__ import annotations

import json

import frago.server.services.primary_agent_service as pa_mod
from frago.server.services.agent_service import resolve_backend


def test_default_is_tmux(monkeypatch, tmp_path):
    monkeypatch.delenv("FRAGO_AGENT_DRIVER", raising=False)
    monkeypatch.setattr(pa_mod, "CONFIG_FILE", tmp_path / "config.json")
    assert resolve_backend() == "tmux"


def test_config_overrides_to_claude_p(monkeypatch, tmp_path):
    monkeypatch.delenv("FRAGO_AGENT_DRIVER", raising=False)
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({"primary_agent": {"agent_backend": "claude-p"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(pa_mod, "CONFIG_FILE", cfg)
    assert resolve_backend() == "claude-p"


def test_env_tmux_takes_effect(monkeypatch, tmp_path):
    monkeypatch.setenv("FRAGO_AGENT_DRIVER", "tmux")
    monkeypatch.setattr(pa_mod, "CONFIG_FILE", tmp_path / "config.json")
    assert resolve_backend() == "tmux"
