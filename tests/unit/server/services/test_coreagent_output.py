"""CoreAgent 输出的新老两种形状，读出来得是同一回事。"""

import json

from frago.server.services.coreagent_output import final_from, legacy_events

# 2026-09-24 新版内核 `-p … --output-format stream-json` 的真实输出（删掉了无关字段）。
CC_STREAM = [
    {"type": "system", "subtype": "init", "session_id": "core_1", "tools": ["Bash"], "model": "m"},
    {"type": "system", "subtype": "hook_response", "hook_event": "SessionStart", "outcome": "ok"},
    {"type": "assistant", "message": {"id": "msg_1", "role": "assistant", "content": [{"type": "text", "text": "先跑命令"}]}},
    {"type": "assistant", "message": {"id": "msg_1", "role": "assistant", "content": [
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "frago todo add x"}}]}},
    {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "Created todo 20260924-x", "is_error": False}]}},
    {"type": "assistant", "message": {"id": "msg_2", "role": "assistant", "content": [
        {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "rm -rf ~"}}]}},
    {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t2", "content": "〔rules refused〕不许删家目录", "is_error": True}]}},
    {"type": "result", "subtype": "success", "is_error": False, "result": "建好了", "num_turns": 3,
     "session_id": "core_1", "usage": {"input_tokens": 5}, "model": "m", "role": "coreagent",
     "profile": "p", "wire": "anthropic", "error_kind": None},
]


def _stdout(rows):
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"


def test_claude_code_result_line_reads_as_the_old_final_line():
    final = final_from(_stdout(CC_STREAM))
    assert final["type"] == "final"
    assert final["ok"] is True and final["text"] == "建好了"
    assert final["rounds"] == 3 and final["role"] == "coreagent" and final["usage"] == {"input_tokens": 5}


def test_a_failed_claude_code_result_carries_its_reason():
    row = {"type": "result", "subtype": "error_during_execution", "is_error": True,
           "result": "模型这一轮既没有文字也没有工具调用", "error_kind": "empty_answer", "num_turns": 4}
    final = final_from(_stdout([row]))
    assert final["ok"] is False and final["text"] == ""
    assert final["error_kind"] == "empty_answer" and "既没有文字" in final["error"]


def test_the_old_final_line_passes_through_untouched():
    old = {"type": "final", "ok": True, "text": "x", "rounds": 2}
    assert final_from(_stdout([old])) == old


def test_an_old_tool_result_event_is_not_mistaken_for_the_conclusion():
    old_tool_result = {"type": "result", "tool_call_id": "c1", "output": "boom", "denied": False, "is_error": True}
    assert final_from(_stdout([old_tool_result])) is None
    assert legacy_events(old_tool_result) == [old_tool_result]


def test_claude_code_events_become_the_old_events():
    events = [e for row in CC_STREAM for e in legacy_events(row)]
    kinds = [e["type"] for e in events]
    assert kinds == ["thinking", "tool", "result", "tool", "result", "done"]
    assert events[1]["tool_name"] == "Bash" and events[1]["input"]["command"] == "frago todo add x"
    assert events[2]["output"] == "Created todo 20260924-x" and events[2]["denied"] is False
    assert events[4]["denied"] is True, "a refusal marker makes it a denial"
    assert events[-1]["final_text"] == "建好了"


def test_a_failed_tool_is_an_error_but_not_a_denial():
    row = {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t", "content": "Exit code 1\nno such file", "is_error": True}]}}
    assert legacy_events(row)[0]["denied"] is False
