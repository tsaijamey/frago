"""五内核统一会话适配器物理承载空闲切面（HarnessIdleVerdict）单元测试。

验证：
1. Claude Code 适配器：后台 shell 运行保护（shells still running）、输入框空闲与生成忙碌识别；
2. Antigravity (agy) 适配器：业务轮次完成时，即使停留在评分卡或待输入态，脱敏判定为空闲；生成态判定为忙碌；
3. CoreAgent 适配器：轮次交卷完成空闲裁决；
4. Codex 与 Opencode 适配器：空闲与生成态裁决；
5. 借住与自有模式安全终止命令映射。
"""

from __future__ import annotations

from unittest.mock import patch

from frago.session.adapters.kernel_adapters import (
    AgySessionAdapter,
    CodexSessionAdapter,
    CoreAgentSessionAdapter,
    HarnessIdleVerdict,
    OpencodeSessionAdapter,
    TurnCompletionVerdict,
    get_kernel_session_adapter,
)


def test_claude_adapter_detects_running_subshells() -> None:
    """Claude Code: 窗格显示 shells still running 时必须判定为忙碌且有后台外壳。"""
    adapter = get_kernel_session_adapter("claude-code")
    pane_text = "Task in progress...\n(2 shells still running)\n❯ "
    verdict = adapter.probe_harness_idle("test-sid", pane_text=pane_text)

    assert isinstance(verdict, HarnessIdleVerdict)
    assert verdict.is_busy is True
    assert verdict.is_terminal_idle is False
    assert verdict.has_running_subshells is True
    assert "still running" in verdict.detail


def test_claude_adapter_idle_and_busy() -> None:
    """Claude Code: 正常空输入框裁决为空闲，生成转轮裁决为忙碌。"""
    adapter = get_kernel_session_adapter("claude")

    # 空闲输入框
    idle_pane = "Some finished assistant response\n────────────────\n❯ "
    verdict_idle = adapter.probe_harness_idle("test-sid", pane_text=idle_pane)
    assert verdict_idle.is_busy is False
    assert verdict_idle.is_terminal_idle is True
    assert verdict_idle.has_running_subshells is False

    # 忙碌转轮态
    busy_pane = "Processing request...\n✻ Propagating…\nesc to interrupt"
    verdict_busy = adapter.probe_harness_idle("test-sid", pane_text=busy_pane)
    assert verdict_busy.is_busy is True
    assert verdict_busy.is_terminal_idle is False


def test_agy_adapter_rating_card_desensitization() -> None:
    """Antigravity: 轮次已终结时，即使窗格停留在满意度评分选择卡，必须脱敏判定为空闲。"""
    adapter = get_kernel_session_adapter("agy")
    assert isinstance(adapter, AgySessionAdapter)

    # Mock probe_turn_completion 为 done
    with patch.object(
        adapter,
        "probe_turn_completion",
        return_value=TurnCompletionVerdict(done=True, stop_reason="end_turn"),
    ):
        # 模拟停留在评分卡或待输入态的窗格尾部
        rating_pane = (
            "Here is the final response.\n"
            "How satisfied are you with this response? (1-5)\n"
            "? for shortcuts\n"
            "> "
        )
        verdict = adapter.probe_harness_idle("test-agy-sid", pane_text=rating_pane)
        assert verdict.is_busy is False
        assert verdict.is_terminal_idle is True
        assert verdict.awaiting_input is True


def test_agy_adapter_detects_busy_generating() -> None:
    """Antigravity: 当轮次未终结且底部出现 Generating... 或 esc to cancel 时判定为忙碌。"""
    adapter = get_kernel_session_adapter("agy")

    with patch.object(
        adapter,
        "probe_turn_completion",
        return_value=TurnCompletionVerdict(done=False, stop_reason=None),
    ):
        busy_pane = (
            "Thinking about the code...\n"
            "Generating response...\n"
            "esc to cancel\n"
        )
        verdict = adapter.probe_harness_idle("test-agy-sid", pane_text=busy_pane)
        assert verdict.is_busy is True
        assert verdict.is_terminal_idle is False


def test_coreagent_adapter_idle_when_done() -> None:
    """CoreAgent: 轮次已交卷且无生成特征时，判定为空闲可回收。"""
    adapter = get_kernel_session_adapter("coreagent")
    assert isinstance(adapter, CoreAgentSessionAdapter)

    with patch.object(
        adapter,
        "probe_turn_completion",
        return_value=TurnCompletionVerdict(done=True, stop_reason="end_turn"),
    ):
        pane = "Done! Process finished with exit code 0."
        verdict = adapter.probe_harness_idle("core_1234567890abcdef", pane_text=pane)
        assert verdict.is_busy is False
        assert verdict.is_terminal_idle is True


def test_coreagent_adapter_busy_on_unclosed_tool_use_transcript(tmp_path) -> None:
    """CoreAgent (P2): 真实转录文件末条为未闭合 tool_use 时，即使窗格静态无转轮也必须判忙。"""
    import json

    adapter = get_kernel_session_adapter("coreagent")
    assert isinstance(adapter, CoreAgentSessionAdapter)

    sid = "core_unclosed_tool_7767"
    transcript = tmp_path / f"{sid}.jsonl"
    records = [
        {
            "type": "user",
            "timestamp": "2026-11-11T10:00:00Z",
            "message": {"role": "user", "content": "渲染一段 10 分钟演示视频"},
        },
        {
            "type": "assistant",
            "timestamp": "2026-11-11T10:00:02Z",
            "message": {
                "role": "assistant",
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_01",
                        "name": "Bash",
                        "input": {"command": "python render_video.py"},
                    }
                ],
            },
        },
    ]
    transcript.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )

    static_pane = (
        "━━━ CoreAgent (oneshot) · core_unclosed_tool_7767 ━━━\n"
        "cwd: /repo\n\n"
        "❯ 渲染一段 10 分钟演示视频\n"
        "[init] session=core_unclosed_tool_7767 model=default cwd=/repo\n"
        "⚙ Bash(python render_video.py)\n"
    )
    with patch.object(adapter, "locate_transcript", return_value=transcript):
        verdict = adapter.probe_harness_idle(sid, pane_text=static_pane)
        assert verdict.is_busy is True
        assert verdict.is_terminal_idle is False
        assert verdict.awaiting_input is False

        # 若窗格已退回裸交互式 shell 提示符（宿主已死），不得因残留半截记录永远卡死忙碌
        shell_pane = static_pane + "\nfrago@macbook:~/repo$ \n"
        verdict_shell = adapter.probe_harness_idle(sid, pane_text=shell_pane)
        assert verdict_shell.is_busy is False
        assert verdict_shell.is_terminal_idle is True


def test_coreagent_adapter_idle_on_closed_end_turn_transcript_with_tool_history(
    tmp_path,
) -> None:
    """CoreAgent (P2): 转录末条为闭合 end_turn 且窗格已打印 Turn complete 时，历史工具行不误报忙。"""
    import json

    adapter = get_kernel_session_adapter("coreagent")
    sid = "core_closed_turn_7767"
    transcript = tmp_path / f"{sid}.jsonl"
    records = [
        {
            "type": "user",
            "timestamp": "2026-11-11T10:00:00Z",
            "message": {"role": "user", "content": "ls"},
        },
        {
            "type": "assistant",
            "timestamp": "2026-11-11T10:00:01Z",
            "message": {
                "role": "assistant",
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_01",
                        "name": "Bash",
                        "input": {"command": "ls"},
                    }
                ],
            },
        },
        {
            "type": "user",
            "timestamp": "2026-11-11T10:00:02Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_01",
                        "content": "README.md",
                    }
                ],
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-11-11T10:00:03Z",
            "message": {
                "role": "assistant",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "目录检查完毕。"}],
            },
        },
    ]
    transcript.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )

    completed_pane = (
        "━━━ CoreAgent (resident) · core_closed_turn_7767 ━━━\n"
        "cwd: /repo\n\n"
        "❯ ls\n"
        "⚙ Bash(ls)\n"
        "  ↳ README.md\n"
        "⏺ 目录检查完毕。\n"
        "✓ Turn complete (1 turns, 320ms)\n"
    )
    with patch.object(adapter, "locate_transcript", return_value=transcript):
        verdict = adapter.probe_harness_idle(sid, pane_text=completed_pane)
        assert verdict.is_busy is False
        assert verdict.is_terminal_idle is True
        assert verdict.awaiting_input is True


def test_coreagent_adapter_virtual_check_busy_never_false_positives() -> None:
    """CoreAgent (P2 防坑): 传入虚拟 '__check_busy__' 无转录文件时，静态空闲窗格绝不误判为忙。"""
    adapter = get_kernel_session_adapter("coreagent")

    verdict_plain = adapter.probe_harness_idle(
        "__check_busy__", pane_text="Static output without spinner\n"
    )
    assert verdict_plain.is_busy is False
    assert verdict_plain.is_terminal_idle is True

    finished_host_pane = (
        "━━━ CoreAgent (oneshot) · core_1 ━━━\n"
        "cwd: /repo\n\n"
        "❯ hello\n"
        "⚙ Bash(echo hi)\n"
        "✓ Turn complete (1 turns, 100ms)\n"
    )
    verdict_finished = adapter.probe_harness_idle(
        "__check_busy__", pane_text=finished_host_pane
    )
    assert verdict_finished.is_busy is False

    active_host_pane = (
        "━━━ CoreAgent (oneshot) · core_1 ━━━\n"
        "cwd: /repo\n\n"
        "❯ long task\n"
        "⚙ Bash(sleep 300)\n"
    )
    verdict_active = adapter.probe_harness_idle(
        "__check_busy__", pane_text=active_host_pane
    )
    assert verdict_active.is_busy is True


def test_codex_and_opencode_adapters() -> None:
    """Codex 与 Opencode: 空闲与中断特征裁决。"""
    codex_adapter = get_kernel_session_adapter("codex")
    assert isinstance(codex_adapter, CodexSessionAdapter)

    with patch.object(
        codex_adapter,
        "probe_turn_completion",
        return_value=TurnCompletionVerdict(done=True, stop_reason="end_turn"),
    ):
        verdict = codex_adapter.probe_harness_idle("codex-sid", pane_text="Finished.\n> ")
        assert verdict.is_busy is False
        assert verdict.is_terminal_idle is True

    opencode_adapter = get_kernel_session_adapter("opencode")
    assert isinstance(opencode_adapter, OpencodeSessionAdapter)

    busy_pane = "Working...\nesc to interrupt"
    verdict_opencode = opencode_adapter.probe_harness_idle("ses_123", pane_text=busy_pane)
    assert verdict_opencode.is_busy is True
    assert verdict_opencode.is_terminal_idle is False


def test_safe_terminate_command_borrowed_vs_owned() -> None:
    """安全终止指令映射：借住模式返回退出序列，自有模式返回 None 由底座销毁。"""
    claude_adapter = get_kernel_session_adapter("claude-code")
    assert claude_adapter.safe_terminate_command("sid", is_borrowed=True) == ["/exit", "C-c", "C-d"]
    assert claude_adapter.safe_terminate_command("sid", is_borrowed=False) is None

    agy_adapter = get_kernel_session_adapter("agy")
    assert agy_adapter.safe_terminate_command("sid", is_borrowed=True) == ["C-c", "C-c", "exit", "C-d"]
