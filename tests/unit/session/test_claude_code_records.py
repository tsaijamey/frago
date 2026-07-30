"""Claude Code 翻译层的用例（spec 20260729-session-workbench-webui Phase 1）。

三块：23 条判据逐条命中一次、三个实测陷阱的回归用例、兜底不丢记录。样本形状全部照
``research-claude-session-format.md`` 第 2 章的真实样本，字段名与嵌套层次未做简化——
简化过的样本测不出真数据里的坑。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from frago.session.adapters.claude_code_records import (
    ClaudeCodeRecordAdapter,
    to_unified,
    translate_records,
    translate_with_stats,
)

# ── 造样本 ──────────────────────────────────────────────────────────
SESSION = "ssssssss-0000-0000-0000-000000000001"


def _row(uuid: str, rtype: str, ts: str = "2026-07-20T10:00:00.000Z", **extra: Any) -> dict[str, Any]:
    """主干四类共有的信封。"""
    row: dict[str, Any] = {
        "parentUuid": None,
        "isSidechain": False,
        "uuid": uuid,
        "type": rtype,
        "timestamp": ts,
        "userType": "external",
        "entrypoint": "cli",
        "cwd": "/tmp/示意",
        "sessionId": SESSION,
        "version": "2.1.215",
        "gitBranch": "main",
    }
    row.update(extra)
    return row


def _assistant(uuid: str, blocks: list[dict[str, Any]], msg_id: str = "msg_0001", **extra: Any) -> dict[str, Any]:
    return _row(
        uuid,
        "assistant",
        message={
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "content": blocks,
            "model": "claude-opus-5",
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {"input_tokens": 3, "output_tokens": 120},
        },
        **extra,
    )


def _user(uuid: str, content: Any, **extra: Any) -> dict[str, Any]:
    return _row(uuid, "user", message={"role": "user", "content": content}, **extra)


def _kinds(records: list[Any]) -> list[str]:
    return [r.kind for r in records]


def _by_kind(records: list[Any], kind: str) -> list[Any]:
    return [r for r in records if r.kind == kind]


# ── 判据表序 1：十二种旁挂状态 ──────────────────────────────────────
def test_rule01_pointer_standing_types_are_dropped() -> None:
    """纯指针状态不进时间线，但要在账上留下计数。"""
    rows = [
        {"type": "last-prompt", "leafUuid": "u1", "sessionId": SESSION},
        {"type": "queue-operation", "operation": "remove", "sessionId": SESSION},
        {"type": "file-history-snapshot", "messageId": "m1"},
        {"type": "file-history-delta", "messageId": "m2"},
        {"type": "bridge-session", "sessionId": SESSION},
        {"type": "pr-link", "sessionId": SESSION},
        {"type": "frame-link", "sessionId": SESSION},
    ]
    records, stats = translate_with_stats(rows, SESSION)
    assert records == []
    assert stats.dropped_standing == 7


def test_rule01_title_keeps_only_the_last_one() -> None:
    """``ai-title`` 会反复覆写：13282 条只对应 1120 个会话，只留最后一条。"""
    rows = [
        {"type": "ai-title", "aiTitle": "第一版标题", "sessionId": SESSION},
        {"type": "ai-title", "aiTitle": "第二版标题", "sessionId": SESSION},
        {"type": "custom-title", "customTitle": "人改的标题", "sessionId": SESSION},
    ]
    records, stats = translate_with_stats(rows, SESSION)
    assert _kinds(records) == ["session.state"]
    assert records[0].payload["field"] == "title"
    assert records[0].payload["to"] == "人改的标题"
    assert stats.dropped_standing_stale == 2


def test_rule01_mode_dedupes_consecutive_same_value() -> None:
    rows = [
        {"type": "mode", "mode": "normal", "sessionId": SESSION},
        {"type": "mode", "mode": "normal", "sessionId": SESSION},
        {"type": "mode", "mode": "plan", "sessionId": SESSION},
        {"type": "permission-mode", "permissionMode": "bypassPermissions", "sessionId": SESSION},
    ]
    records, stats = translate_with_stats(rows, SESSION)
    assert _kinds(records) == ["session.state"] * 3
    assert [r.payload["to"] for r in records] == ["normal", "plan", "bypassPermissions"]
    assert records[1].payload["from"] == "normal"
    assert stats.dropped_standing_stale == 1


# ── 序 2：上下文压缩边界 ────────────────────────────────────────────
def test_rule02_compact_boundary_takes_summary_from_next_record() -> None:
    """摘要正文在紧随其后的那条记录里，边界的 parentUuid 是 null。"""
    rows = [
        _row(
            "u-boundary",
            "system",
            subtype="compact_boundary",
            content="Conversation compacted",
            level="info",
            logicalParentUuid="u-before",
            compactMetadata={"trigger": "manual", "preTokens": 616523, "postTokens": 9940},
        ),
        _user("u-summary", "这是压缩后的摘要正文", isCompactSummary=True),
    ]
    records = translate_records(rows, SESSION)
    assert _kinds(records) == ["context.compact"]
    payload = records[0].payload
    assert payload["summary_text"] == "这是压缩后的摘要正文"
    assert payload["trigger"] == "manual"
    assert payload["tokens_before"] == 616523
    assert payload["tokens_after"] == 9940
    assert payload["bridge_from"] == "u-before"


# ── 序 3：一次模型调用的边界 ────────────────────────────────────────
def test_rule03_turn_duration_becomes_call_envelope() -> None:
    """边界标记归第十五种形态，不再混进注入内容——本机 5324 条会把那一格淹掉。"""
    rows = [_row("u1", "system", subtype="turn_duration", durationMs=7412, messageCount=66)]
    records = translate_records(rows, SESSION)
    assert _kinds(records) == ["call.envelope"]
    assert records[0].payload["channel"] == "turn-duration"
    assert records[0].payload["duration_ms"] == 7412
    assert records[0].payload["message_count"] == 66


# ── 序 4：引擎侧报错 ────────────────────────────────────────────────
def test_rule04_engine_errors_carry_no_raw_entrance() -> None:
    rows = [
        _row("u1", "system", subtype="model_refusal_fallback", content="模型拒答，已降级重试"),
        _row("u2", "system", subtype="model_consent_fallback", content="授权降级"),
        _row("u3", "system", subtype="informational", level="warning", content="模型不可用"),
    ]
    records = translate_records(rows, SESSION)
    assert _kinds(records) == ["error"] * 3
    assert all(r.payload["scope"] == "engine" for r in records)
    # 报错记录连原文入口都不给挂——响应头里带登录凭据。
    assert all(r.raw_available is False for r in records)
    assert all(r.is_raw_readable() is False for r in records)


def test_rule04_informational_without_warning_is_not_an_error() -> None:
    """``informational`` 只有 level 为 warning 时算报错，否则落序 5。"""
    rows = [_row("u1", "system", subtype="informational", level="info", content="提示")]
    records = translate_records(rows, SESSION)
    assert _kinds(records) == ["context.inject"]


# ── 序 5：其余引擎事件 ──────────────────────────────────────────────
def test_rule05_silent_stop_hook_summary_is_dropped() -> None:
    rows = [
        _row(
            "u1",
            "system",
            subtype="stop_hook_summary",
            hookAdditionalContext=[],
            preventedContinuation=False,
            stopReason="",
        )
    ]
    records, stats = translate_records(rows, SESSION), translate_with_stats(rows, SESSION)[1]
    assert records == []
    assert stats.dropped_stop_hook == 1


def test_rule05_stop_hook_with_context_survives() -> None:
    rows = [
        _row(
            "u1",
            "system",
            subtype="stop_hook_summary",
            hookAdditionalContext=["一条被注入的规则"],
            preventedContinuation=False,
        ),
        _row("u2", "system", subtype="away_summary", content="离开期间的进度"),
    ]
    records = translate_records(rows, SESSION)
    assert _kinds(records) == ["context.inject", "context.inject"]
    assert records[1].payload["channel"] == "away_summary"


# ── 序 6～10：附件 ──────────────────────────────────────────────────
def test_rule06_task_reminder_is_a_todo_snapshot_with_source() -> None:
    rows = [
        _row(
            "u1",
            "attachment",
            attachment={"type": "task_reminder", "content": ["待办一", "待办二"], "itemCount": 2},
        )
    ]
    records = translate_records(rows, SESSION)
    assert _kinds(records) == ["todo.snapshot"]
    assert records[0].payload["item_count"] == 2
    # 引擎被动重发，界面默认折叠，来源标记不能省。
    assert records[0].payload["source"] == "engine-reminder"


def test_rule08_file_attachments_become_media() -> None:
    for atype in ("file", "already_read_file", "nested_memory", "compact_file_reference"):
        rows = [
            _row(
                "u1",
                "attachment",
                attachment={
                    "type": atype,
                    "filename": "/tmp/示意.sh",
                    "displayPath": "../示意.sh",
                    "content": {"type": "text", "file": {"content": "#!/bin/zsh\n"}},
                },
            )
        ]
        records = translate_records(rows, SESSION)
        assert _kinds(records) == ["media.attach"], atype
        assert records[0].payload["display_name"] == "../示意.sh"


def test_rule09_empty_hook_success_is_noise() -> None:
    """本机 52604 条 hook_success 里 46531 条是纯噪音，留着会淹没真正的对话。"""
    rows = [
        _row(
            "u1",
            "attachment",
            attachment={
                "type": "hook_success",
                "hookName": "SessionStart:startup",
                "content": "",
                "stdout": "",
                "stderr": "",
                "exitCode": 0,
                "durationMs": 57,
            },
        )
    ]
    records, stats = translate_with_stats(rows, SESSION)
    assert records == []
    assert stats.dropped_hook_noise == 1


def test_rule09_empty_json_object_stdout_is_also_noise() -> None:
    """hook 的惯例是吐一个空的 JSON 对象表示「我没话说」。

    只认空串等于零命中：本机 52604 条 hook 记录的标准输出没有一条是空串，46531 条
    是 ``{}``。放这些进时间线，中栏会被五万条纯噪音淹掉。
    """
    rows = [
        _row(
            "u1",
            "attachment",
            attachment={
                "type": "hook_success",
                "hookName": "PostToolUse",
                "content": "",
                "stdout": "{}",
                "exitCode": 0,
            },
        ),
        _row(
            "u2",
            "attachment",
            attachment={
                "type": "hook_success",
                "hookName": "PostToolUse",
                "content": "",
                "stdout": "  {}\n",
                "exitCode": 0,
            },
        ),
    ]
    records, stats = translate_with_stats(rows, SESSION)
    assert records == []
    assert stats.dropped_hook_noise == 2


def test_rule09_hook_with_specific_output_is_never_dropped() -> None:
    """带 ``hookSpecificOutput`` 的 6073 条是真有话说的，一条都不许拦。"""
    rows = [
        _row(
            "u1",
            "attachment",
            attachment={
                "type": "hook_success",
                "hookName": "SessionStart",
                "content": "",
                "stdout": '{"hookSpecificOutput":{"additionalContext":"一条规则"}}',
                "exitCode": 0,
            },
        )
    ]
    records, stats = translate_with_stats(rows, SESSION)
    assert _kinds(records) == ["context.inject"]
    assert stats.dropped_hook_noise == 0


def test_rule09_hook_success_with_output_survives() -> None:
    rows = [
        _row(
            "u1",
            "attachment",
            attachment={
                "type": "hook_success",
                "hookName": "PreToolUse",
                "content": "",
                "stdout": '{"decision":"allow"}',
                "stderr": "",
                "exitCode": 0,
            },
        )
    ]
    records = translate_records(rows, SESSION)
    assert _kinds(records) == ["context.inject"]
    assert records[0].payload["stdout"] == '{"decision":"allow"}'


def test_rule10_other_attachments_become_injection() -> None:
    """``hook_additional_context`` 的 content 是字符串数组，不是字符串。"""
    rows = [
        _row(
            "u1",
            "attachment",
            attachment={
                "type": "hook_additional_context",
                "content": ["第一条规则", "第二条规则"],
                "hookName": "SessionStart",
            },
        )
    ]
    records = translate_records(rows, SESSION)
    assert _kinds(records) == ["context.inject"]
    assert records[0].payload["channel"] == "hook_additional_context"
    assert records[0].payload["body"] == "第一条规则\n第二条规则"


# ── 序 11～16：模型回复 ─────────────────────────────────────────────
def test_rule11_api_error_bubble_is_not_a_model_utterance() -> None:
    """报错气泡的 type 也是 assistant、也有 text 块，不看布尔值就会显示成模型自述故障。"""
    rows = [
        _assistant(
            "u1",
            [{"type": "text", "text": "API Error: Unable to connect to API (ECONNRESET)"}],
            msg_id="msg_err",
            error="server_error",
            isApiErrorMessage=True,
        )
    ]
    records = translate_records(rows, SESSION)
    assert _kinds(records) == ["error"]
    assert records[0].payload["scope"] == "api"
    assert records[0].payload["code"] == "server_error"
    assert records[0].raw_available is False


def test_rule12_fallback_block_is_a_model_state_change() -> None:
    rows = [
        _assistant(
            "u1",
            [{"type": "fallback", "from": {"model": "claude-fable-5"}, "to": {"model": "claude-opus-4-8"}}],
        )
    ]
    records = translate_records(rows, SESSION)
    assert _kinds(records) == ["session.state"]
    assert records[0].payload == {
        "field": "model",
        "from": "claude-fable-5",
        "to": "claude-opus-4-8",
    }


def test_rules13_to_16_blocks_split_but_share_one_group() -> None:
    """混合块只有万分之二点七，但那 27 条会让"一行一块"的解析器崩。"""
    rows = [
        _assistant(
            "u1",
            [
                {"type": "thinking", "thinking": "先确认参数读取位置", "signature": "<签名>"},
                {"type": "text", "text": "改好了。"},
                {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "ls"}},
                {
                    "type": "tool_use",
                    "id": "toolu_2",
                    "name": "Agent",
                    "input": {"description": "扫描", "prompt": "统计体积", "subagent_type": "general-purpose"},
                },
            ],
        )
    ]
    records = translate_records(rows, SESSION)
    assert _kinds(records) == ["agent.think", "agent.say", "tool.call", "subagent.dispatch"]
    assert len({r.id for r in records}) == 4, "同一行里的多个块必须各有各的 id"
    assert {r.group_id for r in records} == {"msg_0001"}, "同一次回复共用一个分组键"
    assert "signature" not in records[0].payload
    assert records[2].payload["tool_family"] == "shell"
    assert records[3].payload["agent_type"] == "general-purpose"


def test_rule16_tool_family_covers_names_outside_the_closed_set() -> None:
    """工具名不是封闭集合：MCP 随配置变化，还有 bash / Bash 的大小写变体。"""
    blocks = [
        {"type": "tool_use", "id": "t1", "name": "bash", "input": {"command": "ls"}},
        {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/tmp/a"}},
        {"type": "tool_use", "id": "t3", "name": "Edit", "input": {"file_path": "/tmp/a"}},
        {"type": "tool_use", "id": "t4", "name": "WebFetch", "input": {"url": "https://x"}},
        {"type": "tool_use", "id": "t5", "name": "mcp__claude_ai_Gmail__get_thread", "input": {}},
        {"type": "tool_use", "id": "t6", "name": "从未见过的工具", "input": {}},
        {"type": "tool_use", "id": "t7", "name": "AskUserQuestion", "input": {}},
        {"type": "tool_use", "id": "t8", "name": "CronCreate", "input": {}},
        {"type": "tool_use", "id": "t9", "name": "TaskUpdate", "input": {}},
        {"type": "tool_use", "id": "t10", "name": "ToolSearch", "input": {}},
    ]
    records = translate_records([_assistant("u1", blocks)], SESSION)
    assert [r.payload["tool_family"] for r in records] == [
        "shell",
        "file-read",
        "file-write",
        "web",
        "mcp",
        "other",
        "ask",
        "schedule",
        "todo",
        "search",
    ]


def test_rule16_unparsed_tool_input_is_preserved() -> None:
    """模型吐出的 JSON 没解析成功时参数结构不可信，原样兜底要留住。"""
    rows = [
        _assistant(
            "u1",
            [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"__unparsedToolInput": {"raw": "半截 JSON"}}}],
        )
    ]
    records = translate_records(rows, SESSION)
    assert records[0].payload["args_unparsed"] == {"raw": "半截 JSON"}


# ── 序 17～23：顶着 user 标记的五类 ─────────────────────────────────
def test_rule18_denied_tool_emits_two_records() -> None:
    """被拦截出两条：拦截标记 + 状态为 denied 的结果。"""
    rows = [
        _assistant("u1", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "rm -rf /"}}]),
        _user(
            "u2",
            [{"type": "tool_result", "tool_use_id": "t1", "content": "This command requires approval", "is_error": True}],
            toolUseResult="Error: This command requires approval",
            toolDenialKind="user-rejected",
            permissionMode="default",
        ),
    ]
    records = translate_records(rows, SESSION)
    assert _kinds(records) == ["tool.call", "permission.outcome", "tool.result"]
    assert records[1].payload["decision"] == "denied"
    assert records[1].payload["reason"] == "user-rejected"
    # 被拒排在出错之前，顺序不能换。
    assert records[2].payload["status"] == "denied"


def test_rule19_subagent_result_merges_into_the_dispatch_card() -> None:
    rows = [
        _assistant(
            "u1",
            [{"type": "tool_use", "id": "t1", "name": "Agent", "input": {"description": "扫描", "prompt": "统计", "subagent_type": "general-purpose"}}],
        ),
        _user(
            "u2",
            [{"type": "tool_result", "tool_use_id": "t1", "content": "扫描完成"}],
            toolUseResult={
                "agentId": "a1b2c3d4e5f60718",
                "agentType": "general-purpose",
                "status": "completed",
                "totalDurationMs": 184300,
                "totalTokens": 51820,
                "totalToolUseCount": 14,
                "toolStats": {"Bash": 9, "Read": 5},
                "resolvedModel": "claude-opus-5",
            },
        ),
    ]
    records, stats = translate_with_stats(rows, SESSION)
    assert _kinds(records) == ["subagent.dispatch"], "子 agent 的返回不独立成条"
    payload = records[0].payload
    assert payload["agent_ref"] == "a1b2c3d4e5f60718"
    assert payload["status"] == "completed"
    assert payload["stats"]["total_tokens"] == 51820
    assert payload["stats"]["tool_stats"] == {"Bash": 9, "Read": 5}
    # 93 次派发只有 92 个轨迹文件，"点了展开但没有轨迹"必须容忍。
    assert payload["trace_available"] is False
    assert stats.merged_subagent_result == 1


def test_rule20_status_order_denied_error_interrupted_ok() -> None:
    """被拒 → 出错 → 被打断 → 正常。顺序不能换。"""
    calls = _assistant(
        "u0",
        [
            {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": "ls"}}
            for i in range(4)
        ],
    )
    rows: list[dict[str, Any]] = [calls]
    rows.append(
        _user(
            "u1",
            [{"type": "tool_result", "tool_use_id": "t0", "content": "被拒", "is_error": True}],
            toolDenialKind="automode-blocked",
            toolUseResult={"interrupted": True},
        )
    )
    rows.append(
        _user(
            "u2",
            [{"type": "tool_result", "tool_use_id": "t1", "content": "Exit code 1", "is_error": True}],
            toolUseResult={"interrupted": True},
        )
    )
    rows.append(
        _user(
            "u3",
            [{"type": "tool_result", "tool_use_id": "t2", "content": "半截输出", "is_error": False}],
            toolUseResult={"interrupted": True, "stdout": "半截输出"},
        )
    )
    # 完全没有 is_error 这个键的占 40.5%，也是成功。
    rows.append(_user("u4", [{"type": "tool_result", "tool_use_id": "t3", "content": "正常输出"}]))
    results = _by_kind(translate_records(rows, SESSION), "tool.result")
    assert [r.payload["status"] for r in results] == ["denied", "error", "interrupted", "ok"]


def test_rule20_missing_is_error_key_is_success() -> None:
    """20678 条工具结果完全没有 is_error 键，用 `in` 判断会把它们全判成失败。"""
    rows = [
        _assistant("u0", [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/tmp/a"}}]),
        _user("u1", [{"type": "tool_result", "tool_use_id": "t1", "content": "文件内容"}]),
    ]
    results = _by_kind(translate_records(rows, SESSION), "tool.result")
    assert results[0].payload["status"] == "ok"
    assert results[0].payload["tool_name"] == "Read"


def test_rule20_tool_result_string_shaped_payload_does_not_crash() -> None:
    """``toolUseResult`` 同名不同型：49177 条是 dict，1726 条是纯字符串。"""
    rows = [
        _assistant("u0", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "false"}}]),
        _user(
            "u1",
            [{"type": "tool_result", "tool_use_id": "t1", "content": "Exit code 1", "is_error": True}],
            toolUseResult="Error: Exit code 1",
        ),
    ]
    results = _by_kind(translate_records(rows, SESSION), "tool.result")
    assert results[0].payload["status"] == "error"


def test_rule20_image_result_keeps_shape_not_base64() -> None:
    rows = [
        _assistant("u0", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "screencapture"}}]),
        _user(
            "u1",
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "A" * 262144}}],
                }
            ],
        ),
    ]
    results = _by_kind(translate_records(rows, SESSION), "tool.result")
    assert results[0].payload["body_kind"] == "image"
    assert "A" * 100 not in results[0].payload["body"]


def test_rule21_interrupt_is_not_a_user_utterance() -> None:
    """两种正文都是伪造的 user 消息，这类记录不带 isMeta，只看 isMeta 过滤不掉。"""
    rows = [
        _user("u1", [{"type": "text", "text": "[Request interrupted by user]"}], interruptedMessageId="msg_x"),
        _user(
            "u2",
            [{"type": "text", "text": "[Request interrupted by user for tool use]"}],
            interruptedMessageId="msg_y",
        ),
    ]
    records = translate_records(rows, SESSION)
    assert _kinds(records) == ["interrupt", "interrupt"]
    assert records[0].payload["phase"] == "generating"
    assert records[1].payload["phase"] == "tool"
    assert records[0].payload["target"] == "msg_x"


def test_rule22_meta_pseudo_message_is_injection() -> None:
    rows = [
        _user("u1", [{"type": "text", "text": "Continue from where you left off."}], isMeta=True),
        _user("u2", "Your tool call was malformed and could not be parsed. Please retry.", isMeta=True),
    ]
    records = translate_records(rows, SESSION)
    assert _kinds(records) == ["context.inject", "context.inject"]
    assert all(r.payload["channel"] == "engine" for r in records)


def test_rule23_real_user_input_in_both_content_shapes() -> None:
    """content 可以是字符串（7296 条）也可以是块数组（51877 条）。"""
    rows = [
        _user("u1", "把配置文件里的超时改成 30 秒", promptSource="typed"),
        _user(
            "u2",
            [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "B" * 184320}},
                {"type": "text", "text": "这张截图里的按钮位置不对"},
            ],
            promptSource="queued",
            imagePasteIds=["img_0001"],
        ),
    ]
    records = translate_records(rows, SESSION)
    assert _kinds(records) == ["user.say", "user.say"]
    assert records[0].payload["text"] == "把配置文件里的超时改成 30 秒"
    assert records[0].payload["input_mode"] == "typed"
    assert records[1].payload["input_mode"] == "queued"
    assert records[1].payload["images"][0]["media_type"] == "image/png"
    assert records[1].payload["images"][0]["bytes"] == 184320
    # base64 不进正文。
    assert "B" * 100 not in records[1].payload["text"]


def test_group_id_is_none_for_user_input() -> None:
    records = translate_records([_user("u1", "一句话", promptSource="typed")], SESSION)
    assert records[0].group_id is None


def test_agent_path_marks_subagent_trajectory() -> None:
    """子 agent 记录的 sessionId 仍是父会话的，区分靠 agentId。"""
    rows = [_user("b1", "子轨迹里的一句", agentId="a1b2c3d4e5f60718", isSidechain=True)]
    records = translate_records(rows, SESSION)
    assert records[0].agent_path == ["a1b2c3d4e5f60718"]
    assert translate_records([_user("u1", "主会话")], SESSION)[0].agent_path == []


# ── 回归一：用户标记里 86% 不是人说的话 ─────────────────────────────
def test_regression_user_marked_records_are_mostly_not_user_speech() -> None:
    """59173 条 user 里 51002 条是工具结果、2012 条是伪消息，真正人手打的只有 4360 条。

    照 ``role: "user"`` 直接渲染，界面上会冒出五万条假的「你说」。
    """
    rows: list[dict[str, Any]] = [
        _assistant(
            "u0",
            [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}},
                {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/tmp/a"}},
            ],
        ),
        # 工具结果（51002 条那种）
        _user("u1", [{"type": "tool_result", "tool_use_id": "t1", "content": "输出", "is_error": False}]),
        _user("u2", [{"type": "tool_result", "tool_use_id": "t2", "content": "文件内容"}]),
        # 引擎注入的伪消息（2012 条那种）
        _user("u3", [{"type": "text", "text": "Continue from where you left off."}], isMeta=True),
        _user("u4", "Your tool call was malformed and could not be parsed.", isMeta=True),
        # 打断（191 条那种，不带 isMeta）
        _user("u5", [{"type": "text", "text": "[Request interrupted by user]"}], interruptedMessageId="msg_x"),
        # 压缩摘要（3 条那种）
        _user("u6", "摘要正文", isCompactSummary=True),
        # 真正人手打的
        _user("u7", "这句才是人说的", promptSource="typed"),
    ]
    records = translate_records(rows, SESSION)
    says = _by_kind(records, "user.say")

    assert len(says) == 1, f"只有一条是人说的话，却归出了 {len(says)} 条"
    assert says[0].payload["text"] == "这句才是人说的"
    assert says[0].payload["is_tool_result"] is False
    # 逐类点名，防止将来某一类悄悄漏回 user.say
    assert _kinds(records) == [
        "tool.call",
        "tool.call",
        "tool.result",
        "tool.result",
        "context.inject",
        "context.inject",
        "interrupt",
        "user.say",
    ]
    assert not any(r.kind == "user.say" and r.payload.get("is_tool_result") for r in records)


# ── 回归二：时间戳倒挂 ──────────────────────────────────────────────
def test_regression_seq_follows_physical_order_not_timestamps() -> None:
    """1212 个文件里 850 个（70.1%）时间戳倒挂，共 3973 处，根因是并行工具调用。

    调研第 3.5 节那个真实案例：调用 C 落在结果 B 之前。喂一份乱序的输入，序号仍按
    物理行序递增，NEVER 按时间排序。
    """
    rows = [
        _assistant("call-a", [{"type": "tool_use", "id": "ta", "name": "Read", "input": {}}], msg_id="msg_1", ts="2026-07-20T16:39:20.874Z"),
        _user("res-a", [{"type": "tool_result", "tool_use_id": "ta", "content": "A"}], ts="2026-07-20T16:39:21.302Z"),
        _assistant("call-b", [{"type": "tool_use", "id": "tb", "name": "Read", "input": {}}], msg_id="msg_2", ts="2026-07-20T16:39:21.310Z"),
        _assistant("call-c", [{"type": "tool_use", "id": "tc", "name": "Read", "input": {}}], msg_id="msg_2", ts="2026-07-20T16:39:21.327Z"),
        # 这两条的时间戳早于上面两条：跨请求倒挂，实测存在
        _user("res-b", [{"type": "tool_result", "tool_use_id": "tb", "content": "B"}], ts="2026-07-20T16:39:19.000Z"),
        _user("res-c", [{"type": "tool_result", "tool_use_id": "tc", "content": "C"}], ts="2026-07-20T16:39:18.000Z"),
    ]
    records = translate_records(rows, SESSION)

    assert [r.seq for r in records] == list(range(len(records))), "seq 必须从 0 起连续递增"
    assert [r.id for r in records] == ["call-a", "res-a", "call-b", "call-c", "res-b", "res-c"]
    # 时间戳本身是倒挂的，证明确实没有按时间排过序
    assert records[4].ts < records[3].ts
    assert records[5].ts < records[4].ts
    # 并行调用靠 group_id 才能聚回一次回复，parentUuid 是写盘顺序链不是语义父子
    assert records[2].group_id == records[3].group_id == "msg_2"


# ── 回归三：溢出转存时截断标记写「否」 ──────────────────────────────
def test_regression_offloaded_output_is_not_reported_as_intact() -> None:
    """溢出转存时正文里没有任何截断字样，判成"完整"就等于告诉人这就是全部内容。"""
    rows = [
        _assistant("u0", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "cat 大文件"}}]),
        _user(
            "u1",
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": "Output too large (1.3MB). Full output saved to: /tmp/tool-output/x.txt",
                    "is_error": False,
                }
            ],
            toolUseResult={
                "stdout": "",
                "stderr": "",
                "interrupted": False,
                "isImage": False,
                "persistedOutputPath": "/tmp/tool-output/x.txt",
                "persistedOutputSize": 1363148,
            },
        ),
    ]
    result = _by_kind(translate_records(rows, SESSION), "tool.result")[0]
    assert result.payload["truncation"] == "offloaded", "全文在别处，不是完整"
    assert result.payload["truncation_ref"] == "/tmp/tool-output/x.txt"
    assert result.payload["status"] == "ok"


def test_regression_offloaded_without_persisted_path_still_detected() -> None:
    """只有正文开头那句、``toolUseResult`` 退化成字符串的情形也要判出来。"""
    rows = [
        _assistant("u0", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]),
        _user(
            "u1",
            [{"type": "tool_result", "tool_use_id": "t1", "content": "Output too large (2.1MB). Full output saved to: /tmp/y.txt"}],
            toolUseResult="Output too large",
        ),
    ]
    result = _by_kind(translate_records(rows, SESSION), "tool.result")[0]
    assert result.payload["truncation"] == "offloaded"


def test_truncation_read_pagination_notice_merges_into_result() -> None:
    """Read 分页的提示不在工具结果里，而是一条独立附件，靠 toolUseID 关联。"""
    banner = "[Truncated: PARTIAL view — /tmp/a.py: showing lines 1-1250 of 2198 total]"
    rows = [
        _assistant("u0", [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/tmp/a.py"}}]),
        _user("u1", [{"type": "tool_result", "tool_use_id": "t1", "content": "前 1250 行"}]),
        _row("u2", "attachment", attachment={"type": "read_truncation_notice", "banner": banner, "toolUseID": "t1"}),
    ]
    records, stats = translate_with_stats(rows, SESSION)
    result = _by_kind(records, "tool.result")[0]
    assert result.payload["truncation"] == "offloaded"
    assert result.payload["truncation_ref"] == banner
    assert stats.merged_truncation_notice == 1
    assert "media.attach" not in _kinds(records), "分页通知不独立成条"


def test_truncation_clipped_middle_is_permanent_loss() -> None:
    rows = [
        _assistant("u0", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]),
        _user(
            "u1",
            [{"type": "tool_result", "tool_use_id": "t1", "content": "前 8000 字\n\n... [19339 characters truncated] ...\n\n后 2000 字"}],
        ),
    ]
    result = _by_kind(translate_records(rows, SESSION), "tool.result")[0]
    assert result.payload["truncation"] == "clipped"
    assert result.payload["truncation_ref"] is None


def test_truncation_normal_result_is_none() -> None:
    rows = [
        _assistant("u0", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]),
        _user("u1", [{"type": "tool_result", "tool_use_id": "t1", "content": "12:  timeout: 10"}]),
    ]
    result = _by_kind(translate_records(rows, SESSION), "tool.result")[0]
    assert result.payload["truncation"] == "none"


# ── 兜底：NEVER 静默丢弃 ────────────────────────────────────────────
def test_unknown_top_level_type_is_kept_and_flagged() -> None:
    """将来加的新类型不能凭空消失——人会以为那件事没发生过。"""
    rows = [{"type": "某个还没见过的类型", "uuid": "u1", "timestamp": "2026-07-20T10:00:00.000Z", "payload": 1}]
    records, stats = translate_with_stats(rows, SESSION)
    assert _kinds(records) == ["context.inject"]
    assert records[0].payload["unrecognized"] is True
    assert stats.unrecognized == 1
    assert json.loads(records[0].payload["body"])["type"] == "某个还没见过的类型"


def test_unknown_assistant_block_type_is_kept_and_flagged() -> None:
    rows = [_assistant("u1", [{"type": "还没见过的块", "data": 1}])]
    records, stats = translate_with_stats(rows, SESSION)
    assert _kinds(records) == ["context.inject"]
    assert stats.unrecognized == 1


def test_empty_assistant_content_is_kept_and_flagged() -> None:
    rows = [_assistant("u1", [])]
    records, stats = translate_with_stats(rows, SESSION)
    assert _kinds(records) == ["context.inject"]
    assert stats.unrecognized == 1


def test_orphan_subagent_result_falls_back_to_tool_result() -> None:
    """派发卡不在这一批里（翻的是文件后半截）时，结果也不能凭空消失。"""
    rows = [
        _user(
            "u1",
            [{"type": "tool_result", "tool_use_id": "t-missing", "content": "子任务完成"}],
            toolUseResult={"agentId": "aaa", "status": "completed"},
        )
    ]
    records = translate_records(rows, SESSION)
    assert _kinds(records) == ["tool.result"]


def test_stats_account_for_every_line() -> None:
    """进出账要能对上：每一行的去向都写在账上。"""
    rows: list[dict[str, Any]] = [
        {"type": "last-prompt", "leafUuid": "x", "sessionId": SESSION},
        _row("u1", "attachment", attachment={"type": "hook_success", "content": "", "stdout": "", "exitCode": 0}),
        _assistant("u2", [{"type": "text", "text": "一句"}, {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]),
        _user("u3", [{"type": "tool_result", "tool_use_id": "t1", "content": "输出"}]),
        _user("u4", "人说的话", promptSource="typed"),
    ]
    records, stats = translate_with_stats(rows, SESSION)
    assert stats.lines_in == 5
    # 5 行进：1 行是纯指针状态、1 行是 hook 噪音，各自显式丢弃；剩下 3 行里有一行
    # 含两个块，展成两条。4 条出，差额逐项可解释。
    assert stats.dropped_standing == 1
    assert stats.dropped_hook_noise == 1
    assert stats.records_out == len(records) == 4
    assert _kinds(records) == ["agent.say", "tool.call", "tool.result", "user.say"]
    assert sum(stats.kinds.values()) == stats.records_out


def test_unparsable_line_is_not_silently_swallowed(tmp_path: Path) -> None:
    path = tmp_path / f"{SESSION}.jsonl"
    path.write_text(
        json.dumps(_user("u1", "第一句", promptSource="typed"), ensure_ascii=False)
        + "\n{ 这行不是合法 JSON\n"
        + json.dumps(_user("u2", "第二句", promptSource="typed"), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    records = to_unified(path)
    assert _kinds(records) == ["user.say", "context.inject", "user.say"]
    assert records[1].payload["unrecognized"] is True


# ── 整场：读文件与空壳会话 ──────────────────────────────────────────
def test_to_unified_reads_a_file_and_numbers_from_zero(tmp_path: Path) -> None:
    path = tmp_path / f"{SESSION}.jsonl"
    rows = [
        _user("u1", "改一下超时", promptSource="typed"),
        _assistant("u2", [{"type": "thinking", "thinking": "先看配置", "signature": "s"}]),
        _assistant("u3", [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/tmp/a"}}]),
        _user("u4", [{"type": "tool_result", "tool_use_id": "t1", "content": "timeout: 10"}]),
        _assistant("u5", [{"type": "text", "text": "改好了。"}]),
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    records = to_unified(path)
    assert [r.seq for r in records] == [0, 1, 2, 3, 4]
    assert _kinds(records) == ["user.say", "agent.think", "tool.call", "tool.result", "agent.say"]
    assert all(r.session_id == SESSION for r in records)


def test_empty_shell_session_yields_no_records(tmp_path: Path) -> None:
    """本机 4 个文件只有三四行旁挂状态，一条可渲染记录都没有。这是空壳，不是损坏。"""
    path = tmp_path / f"{SESSION}.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"type": "last-prompt", "leafUuid": "x", "sessionId": SESSION},
                {"type": "mode", "mode": "normal", "sessionId": SESSION},
                {"type": "permission-mode", "permissionMode": "default", "sessionId": SESSION},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    records = to_unified(path)
    assert _kinds(records) == ["session.state", "session.state"]


def test_subagent_trace_presence_is_detected(tmp_path: Path) -> None:
    projects = tmp_path / "示意项目"
    projects.mkdir()
    traces = projects / SESSION / "subagents"
    traces.mkdir(parents=True)
    (traces / "agent-a1b2c3d4e5f60718.jsonl").write_text("{}\n", encoding="utf-8")
    path = projects / f"{SESSION}.jsonl"
    rows = [
        _assistant("u1", [{"type": "tool_use", "id": "t1", "name": "Agent", "input": {"prompt": "p"}}]),
        _user("u2", [{"type": "tool_result", "tool_use_id": "t1", "content": "完成"}], toolUseResult={"agentId": "a1b2c3d4e5f60718", "status": "completed"}),
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    records = to_unified(path)
    assert records[0].payload["trace_available"] is True


# ── 适配器外壳 ──────────────────────────────────────────────────────
def _write_session(root: Path, rows: list[dict[str, Any]]) -> None:
    project = root / "示意项目"
    project.mkdir(parents=True, exist_ok=True)
    (project / f"{SESSION}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )


def test_adapter_pages_from_the_given_cursor(tmp_path: Path) -> None:
    _write_session(tmp_path, [_user(f"u{i}", f"第 {i} 句", promptSource="typed") for i in range(10)])
    adapter = ClaudeCodeRecordAdapter(tmp_path)
    first = adapter.to_unified(SESSION, after=0, limit=4)
    assert [r.seq for r in first] == [0, 1, 2, 3]
    second = adapter.to_unified(SESSION, after=first[-1].seq + 1, limit=4)
    assert [r.seq for r in second] == [4, 5, 6, 7]


def test_adapter_missing_session_returns_empty(tmp_path: Path) -> None:
    adapter = ClaudeCodeRecordAdapter(tmp_path)
    assert adapter.to_unified("00000000-0000-0000-0000-000000000000") == []
    assert adapter.read_raw("00000000-0000-0000-0000-000000000000", "x") is None


def test_adapter_tail_takes_the_last_records(tmp_path: Path) -> None:
    """tail=True 忽略 after，取整场最后 limit 条。中栏打开要直接落在最新内容上。"""
    _write_session(tmp_path, [_user(f"u{i}", f"第 {i} 句", promptSource="typed") for i in range(10)])
    adapter = ClaudeCodeRecordAdapter(tmp_path)
    last = adapter.to_unified(SESSION, after=4, limit=3, tail=True)
    assert [r.seq for r in last] == [7, 8, 9]
    whole = adapter.to_unified(SESSION, after=0, limit=1000, tail=True)
    assert [r.seq for r in whole] == list(range(10))


def test_adapter_read_raw_refuses_error_records(tmp_path: Path) -> None:
    """报错记录的原文入口恒不给挂——响应头里带 Cloudflare 登录凭据。"""
    _write_session(
        tmp_path,
        [
            _user("u1", "一句话", promptSource="typed"),
            _assistant("u2", [{"type": "text", "text": "API Error: overloaded"}], error="server_error", isApiErrorMessage=True),
        ],
    )
    adapter = ClaudeCodeRecordAdapter(tmp_path)
    assert adapter.read_raw(SESSION, "u1") is not None
    assert adapter.read_raw(SESSION, "u2") is None
    assert adapter.read_raw(SESSION, "不存在的记录") is None
