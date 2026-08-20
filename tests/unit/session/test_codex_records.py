"""codex rollout → 统一记录 的翻译层单测。

守的核心是"同一句话在 rollout 里出现两遍，取哪一遍"：取错会让会话详情里每句话出现
两次，或者让用户消息顶着一段环境说明、真正的提问被淹没。
"""

import json

import pytest

from frago.session import codex_store
from frago.session.adapters import get_adapter
from frago.session.adapters.codex_records import (
    CodexRecordAdapter,
    tool_family_of,
    translate_session,
)


def _meta(session_id, cwd="/repo"):
    return {
        "timestamp": "2026-08-19T15:07:11.570Z",
        "type": "session_meta",
        "payload": {"session_id": session_id, "id": session_id, "cwd": cwd},
    }


def _event(kind, payload, ts="2026-08-19T15:07:20.000Z"):
    return {"timestamp": ts, "type": "event_msg", "payload": {"type": kind, **payload}}


def _item(kind, payload, ts="2026-08-19T15:07:21.000Z"):
    return {
        "timestamp": ts,
        "type": "response_item",
        "payload": {"type": kind, **payload},
    }


@pytest.fixture
def rollout(tmp_path, monkeypatch):
    """写一场会话，返回 (session_id, 写入函数)。"""
    home = tmp_path / "codexhome"
    day = home / "sessions" / "2026" / "08" / "19"
    day.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(home))
    sid = "01a01a8f-df1f-72d2-8074-97a6a8fec9e0"

    def write(records):
        path = day / f"rollout-2026-08-19T23-07-11-{sid}.jsonl"
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
            encoding="utf-8",
        )
        return path

    return sid, write


def _kinds(records):
    return [r.kind for r in records]


# ── 取哪一遍 ────────────────────────────────────────────────────────
def test_user_say_comes_from_the_event_and_the_model_side_copy_becomes_context(
    rollout,
):
    """用户那半轮取 ``event_msg``；模型侧那份裹着环境说明，归注入内容。

    取错会让会话详情里每条用户消息都顶着一段 ``<environment_context>``，真正的提问
    被淹没。
    """
    sid, write = rollout
    write(
        [
            _meta(sid),
            _item(
                "message",
                {
                    "id": "m0",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "<environment_context>…"}],
                },
            ),
            _event("user_message", {"message": "帮我修个 bug"}),
        ]
    )
    records = translate_session(sid)
    kinds = _kinds(records)
    assert kinds == ["session.state", "context.inject", "user.say"]
    assert records[2].payload["text"] == "帮我修个 bug"
    assert records[1].payload["channel"] == "environment"


def test_agent_say_comes_from_the_response_item_not_the_ui_echo(rollout):
    """agent 正文取 ``response_item``——它是模型确实产出过的那条记录。

    取界面回显（``event_msg`` 的 ``agent_message``）的话，某种流程里没有回显时答案
    会整段消失，而丢掉的记录在界面上等于没发生过。
    """
    sid, write = rollout
    write(
        [
            _meta(sid),
            _event("agent_message", {"message": "结论", "phase": "final_answer"}),
            _item(
                "message",
                {
                    "id": "m1",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "结论"}],
                },
            ),
        ]
    )
    records = translate_session(sid)
    says = [r for r in records if r.kind == "agent.say"]
    assert len(says) == 1, "同一句话 NEVER 出现两遍"
    assert says[0].payload["text"] == "结论"


def test_frago_injection_is_shown_as_context_not_dropped(rollout):
    """frago 经钩子注入的上下文是 developer 消息：翻成注入内容，看得见。

    会话工作台的价值之一就是让人看见 agent 当时到底被喂了什么。
    """
    sid, write = rollout
    write(
        [
            _meta(sid),
            _item(
                "message",
                {
                    "id": "m1",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "frago 的行为守则…"}],
                },
            ),
        ]
    )
    (_, injected) = translate_session(sid)
    assert injected.kind == "context.inject"
    assert injected.payload["channel"] == "developer"
    assert "frago" in injected.payload["body"]


# ── 顺序与分组 ──────────────────────────────────────────────────────
def test_seq_takes_physical_order_from_zero(rollout):
    sid, write = rollout
    write(
        [
            _meta(sid),
            _event("task_started", {"turn_id": "t1"}),
            _event("user_message", {"message": "问"}),
            _event("task_complete", {"turn_id": "t1", "last_agent_message": "答"}),
        ]
    )
    records = translate_session(sid)
    assert [r.seq for r in records] == list(range(len(records)))


def test_turn_id_groups_a_round_and_user_input_stays_ungrouped(rollout):
    sid, write = rollout
    write(
        [
            _meta(sid),
            _event("task_started", {"turn_id": "t1"}),
            _event("user_message", {"message": "问"}),
            _item("reasoning", {"id": "r1", "content": [{"type": "reasoning_text",
                                                         "text": "想"}]}),
            _event("task_complete", {"turn_id": "t1", "last_agent_message": "答"}),
        ]
    )
    by_kind = {r.kind: r for r in translate_session(sid)}
    # 用户输入类不设分组键（统一记录的硬约定）。
    assert by_kind["user.say"].group_id is None
    assert by_kind["agent.think"].group_id == "t1"


# ── 报错 ────────────────────────────────────────────────────────────
def test_a_failed_turn_produces_an_error_record_with_no_raw_entry(rollout):
    """报错只留三个字段，且原文入口恒不可用（响应头可能带凭据）。"""
    sid, write = rollout
    write(
        [
            _meta(sid),
            _event("task_started", {"turn_id": "t1"}),
            _event(
                "task_complete",
                {
                    "turn_id": "t1",
                    "last_agent_message": None,
                    "error": {"message": "No tool output found"},
                },
            ),
        ]
    )
    errors = [r for r in translate_session(sid) if r.kind == "error"]
    assert len(errors) == 1
    assert errors[0].payload["message"] == "No tool output found"
    assert errors[0].raw_available is False
    assert errors[0].is_raw_readable() is False


# ── 工具 ────────────────────────────────────────────────────────────
def test_tool_call_and_result_carry_the_shared_payload_shape(rollout):
    sid, write = rollout
    write(
        [
            _meta(sid),
            _item(
                "function_call",
                {
                    "id": "fc1",
                    "call_id": "call_00",
                    "name": "exec_command",
                    "arguments": '{"cmd": "echo hi"}',
                },
            ),
            _item(
                "function_call_output",
                {"id": "fco1", "call_id": "call_00", "output": "hi\n"},
            ),
        ]
    )
    records = translate_session(sid)
    call = next(r for r in records if r.kind == "tool.call")
    result = next(r for r in records if r.kind == "tool.result")
    assert call.payload["tool_name"] == "exec_command"
    assert call.payload["tool_family"] == "shell"
    assert call.payload["args"] == {"cmd": "echo hi"}
    assert result.payload["call_id"] == "call_00"
    assert result.payload["body"] == "hi\n"
    # 同一轮里两条记录的编号必须不同，否则按编号去重会吃掉一条。
    assert call.id != result.id


@pytest.mark.parametrize(
    ("name", "family"),
    [
        ("exec_command", "shell"),
        ("Bash", "shell"),
        ("apply_patch", "file-write"),
        ("update_plan", "todo"),
        ("mcp__filesystem__read_file", "mcp"),
        ("something_new_next_release", "other"),
    ],
)
def test_tool_family_never_raises_on_an_unseen_name(name, family):
    assert tool_family_of(name) == family


# ── 认不出的记录 ────────────────────────────────────────────────────
def test_unrecognised_records_are_surfaced_not_dropped(rollout):
    """丢掉的记录在界面上等于没发生过，人会以为这段时间什么都没发生。"""
    sid, write = rollout
    write([_meta(sid), {"timestamp": "2026-08-19T15:07:22.000Z",
                        "type": "brand_new_kind", "payload": {"type": "whatever"}}])
    unknown = [r for r in translate_session(sid) if r.payload.get("unrecognized")]
    assert len(unknown) == 1
    assert unknown[0].kind == "context.inject"
    assert unknown[0].payload["record_type"] == "brand_new_kind"


def test_pure_bookkeeping_is_dropped_on_purpose(rollout):
    """用量统计与状态快照不是任何人说的话，也不是任何动作，翻进时间线只会挤走内容。"""
    sid, write = rollout
    write(
        [
            _meta(sid),
            _event("token_count", {"info": {}}),
            {"timestamp": "2026-08-19T15:07:22.000Z", "type": "world_state",
             "payload": {}},
            {"timestamp": "2026-08-19T15:07:23.000Z", "type": "turn_context",
             "payload": {"turn_id": "t1"}},
        ]
    )
    assert _kinds(translate_session(sid)) == ["session.state"]


# ── 分页与原文 ──────────────────────────────────────────────────────
def test_pagination_and_tail(rollout):
    sid, write = rollout
    write([_meta(sid)] + [_event("user_message", {"message": f"第 {i} 句"})
                          for i in range(10)])
    adapter = CodexRecordAdapter()
    first = adapter.to_unified(sid, 0, 3)
    assert [r.seq for r in first] == [0, 1, 2]
    nxt = adapter.to_unified(sid, 3, 3)
    assert [r.seq for r in nxt] == [3, 4, 5]
    tail = adapter.to_unified(sid, 0, 2, tail=True)
    assert [r.seq for r in tail] == [9, 10]


def test_read_raw_returns_the_original_line(rollout):
    sid, write = rollout
    write([_meta(sid), _item("message", {"id": "m1", "role": "assistant",
                                         "content": [{"type": "output_text",
                                                      "text": "答"}]})])
    adapter = CodexRecordAdapter()
    say = next(r for r in translate_session(sid) if r.kind == "agent.say")
    raw = adapter.read_raw(sid, say.id)
    assert raw is not None
    assert raw["payload"]["id"] == "m1"
    assert adapter.read_raw(sid, "no-such-record") is None


def test_error_records_never_hand_back_their_raw_line(rollout):
    sid, write = rollout
    write(
        [
            _meta(sid),
            _event("task_started", {"turn_id": "t1"}),
            _event("task_complete", {"turn_id": "t1", "last_agent_message": None,
                                     "error": {"message": "boom"}}),
        ]
    )
    adapter = CodexRecordAdapter()
    err = next(r for r in translate_session(sid) if r.kind == "error")
    assert adapter.read_raw(sid, err.id) is None


def test_absent_session_reads_as_empty_not_as_an_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "absent"))
    assert translate_session("00000000-0000-4000-8000-000000000000") == []


# ── 注册表 ──────────────────────────────────────────────────────────
def test_codex_is_registered_in_the_adapter_registry():
    assert isinstance(get_adapter("codex"), CodexRecordAdapter)


def test_store_and_adapter_read_the_same_file(rollout):
    """两条路（完成探针走 store、界面走 adapter）必须指向同一场会话。"""
    sid, write = rollout
    path = write(
        [
            _meta(sid),
            _event("task_started", {"turn_id": "t1"}),
            _event("task_complete", {"turn_id": "t1", "last_agent_message": "答"}),
        ]
    )
    assert codex_store.find_rollout(sid) == path
    assert codex_store.latest_turn(sid).text == "答"
    assert any(r.kind == "call.envelope" for r in translate_session(sid))
