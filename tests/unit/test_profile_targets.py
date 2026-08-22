"""激活目标名单：谁能被选、谁不能、为什么。

激活以前只有一个隐含目标（Claude Code），人从界面上看不出自己的另外两个 cli-agent
根本没被碰过。现在目标是显式的，这组测试守住三件事：

1. 不支持的 agent（codex）NEVER 悄悄消失，而是带着原因出现在名单里；
2. 没装的 agent 不能被选中，且拒绝时说的是"没装"而不是"不支持"；
3. 不传目标 == 老行为（只写 Claude Code），且不做"装没装"的检查——那是 frago 一直
   以来的做法，在这里加检查会让 claude 装在非常规位置的人突然切不了 profile。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from frago.init.profile_targets import (
    AGENT_TARGETS,
    DEFAULT_TARGETS,
    list_targets,
    resolve_targets,
    selectable_targets,
    target_status,
)


def _installed(*present: str):
    """只有 present 里的 agent 在本机装了。"""
    return patch(
        "frago.init.profile_targets._installed_path",
        side_effect=lambda agent: f"/usr/local/bin/{agent}" if agent in present else None,
    )


# ── 名单本身 ───────────────────────────────────────────────────────
def test_every_known_agent_is_listed() -> None:
    """三个 cli-agent 都要出现，不因不可选而被藏起来。"""
    assert [s.agent_type for s in list_targets()] == list(AGENT_TARGETS)


def test_codex_is_listed_as_unsupported_with_a_reason() -> None:
    """接不了就说清楚为什么——一个凭空缺席的选项会被当成 bug。"""
    status = target_status("codex")
    assert not status.supported
    assert not status.selectable
    assert status.unsupported_reason
    assert "responses" in status.unsupported_reason


def test_claude_and_opencode_are_supported() -> None:
    assert target_status("claude").supported
    assert target_status("opencode").supported


def test_selectable_needs_both_supported_and_installed() -> None:
    with _installed("claude"):
        assert selectable_targets() == ["claude"]
    with _installed("claude", "opencode", "codex"):
        # codex 装了也不可选：不可选的原因是协议，不是安装。
        assert selectable_targets() == ["claude", "opencode"]


# ── 请求校验 ───────────────────────────────────────────────────────
def test_no_targets_means_the_historical_default() -> None:
    """老调用方（CLI、旧客户端、编辑后重新落盘）行为一个字不变。"""
    with _installed():  # 什么都没装
        assert resolve_targets(None) == list(DEFAULT_TARGETS)


def test_explicit_targets_are_ordered_and_deduplicated() -> None:
    with _installed("claude", "opencode"):
        assert resolve_targets(["opencode", "claude", "opencode"]) == [
            "claude",
            "opencode",
        ]


def test_empty_selection_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one"):
        resolve_targets([])


def test_unknown_agent_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown agent CLI"):
        resolve_targets(["claude", "aider"])


def test_unsupported_agent_is_refused_with_its_reason() -> None:
    with _installed("claude", "codex"):
        with pytest.raises(ValueError, match="cannot use frago profiles"):
            resolve_targets(["codex"])


def test_uninstalled_agent_says_it_is_not_installed() -> None:
    """拒绝的理由必须可行动：'没装'能去装，'不能激活'去不了任何地方。"""
    with _installed("claude"):
        with pytest.raises(ValueError, match="not installed on this machine"):
            resolve_targets(["claude", "opencode"])
