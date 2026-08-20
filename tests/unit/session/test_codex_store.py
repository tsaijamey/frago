"""codex rollout JSONL 读取层的单测。

固定装置用的是 codex-cli 0.147.0 真实写出来的记录形状（字段名、嵌套、``event_msg``
与 ``response_item`` 的分工都照抄自实测文件），NEVER 按文档想象一份。
"""

import json

import pytest

from frago.session import codex_store


def _write_rollout(root, day_parts, name, records):
    directory = root.joinpath(*day_parts)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    return path


def _meta(session_id, cwd):
    return {
        "timestamp": "2026-08-19T15:07:11.570Z",
        "type": "session_meta",
        "payload": {
            "session_id": session_id,
            "id": session_id,
            "timestamp": "2026-08-19T15:07:11.570Z",
            "cwd": cwd,
        },
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
def codex_home(tmp_path, monkeypatch):
    home = tmp_path / "codexhome"
    (home / "sessions").mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setattr(
        codex_store, "BINDINGS_PATH", tmp_path / "frago" / "codex-sessions.json"
    )
    return home


# ── 定位与认领 ──────────────────────────────────────────────────────
def test_find_rollout_and_meta(codex_home, tmp_path):
    sid = "01a01a8f-df1f-72d2-8074-97a6a8fec9e0"
    path = _write_rollout(
        codex_home / "sessions",
        ("2026", "08", "19"),
        f"rollout-2026-08-19T23-07-11-{sid}.jsonl",
        [_meta(sid, str(tmp_path))],
    )
    assert codex_store.find_rollout(sid) == path
    assert codex_store.session_exists(sid) is True

    sessions = codex_store.list_sessions()
    assert [s.session_id for s in sessions] == [sid]
    assert sessions[0].cwd == str(tmp_path)


def test_session_exists_is_true_when_nothing_is_readable(codex_home, monkeypatch):
    """读不到不等于会话没了——NEVER 因为一次读不到就把一条好绑定清掉。"""
    monkeypatch.setenv("CODEX_HOME", str(codex_home / "does-not-exist"))
    assert codex_store.session_exists("whatever") is True


def test_claim_matches_symlinked_directory(codex_home, tmp_path):
    """认领要按真实路径比：macOS 上 /tmp 是 /private/tmp 的软链接。

    不归一化就精确匹配，认领永远落空，而且是**静默**落空：没有绑定 → 完成探针
    全程弃权 → 本轮悄悄退回读屏。
    """
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    sid = "sid-symlink"
    _write_rollout(
        codex_home / "sessions",
        ("2026", "08", "19"),
        f"rollout-2026-08-19T23-07-11-{sid}.jsonl",
        [_meta(sid, str(real))],
    )
    assert codex_store.claim_session(str(link), 0) == sid


def test_claim_ignores_sessions_older_than_the_anchor(codex_home, tmp_path):
    sid = "sid-old"
    _write_rollout(
        codex_home / "sessions",
        ("2026", "08", "19"),
        f"rollout-2026-08-19T23-07-11-{sid}.jsonl",
        [_meta(sid, str(tmp_path))],
    )
    future_ms = 4102444800_000  # 2100-01-01
    assert codex_store.claim_session(str(tmp_path), future_ms) is None


def test_claim_ignores_other_directories(codex_home, tmp_path):
    sid = "sid-elsewhere"
    _write_rollout(
        codex_home / "sessions",
        ("2026", "08", "19"),
        f"rollout-2026-08-19T23-07-11-{sid}.jsonl",
        [_meta(sid, "/somewhere/else")],
    )
    assert codex_store.claim_session(str(tmp_path), 0) is None


# ── 轮次判定 ────────────────────────────────────────────────────────
def _session_with(codex_home, tmp_path, sid, tail):
    return _write_rollout(
        codex_home / "sessions",
        ("2026", "08", "19"),
        f"rollout-2026-08-19T23-07-11-{sid}.jsonl",
        [_meta(sid, str(tmp_path)), *tail],
    )


def test_latest_turn_reports_done_with_final_text(codex_home, tmp_path):
    sid = "sid-done"
    _session_with(
        codex_home,
        tmp_path,
        sid,
        [
            _event("task_started", {"turn_id": "t1"}),
            _item("message", {"id": "m1", "role": "assistant",
                              "content": [{"type": "output_text", "text": "答完了"}]}),
            _event("task_complete", {"turn_id": "t1", "last_agent_message": "答完了"}),
        ],
    )
    turn = codex_store.latest_turn(sid)
    assert turn.done is True
    assert turn.text == "答完了"
    assert turn.turn_id == "t1"
    assert turn.error is None


def test_latest_turn_reports_running_while_a_turn_is_open(codex_home, tmp_path):
    sid = "sid-running"
    _session_with(
        codex_home,
        tmp_path,
        sid,
        [
            _event("task_started", {"turn_id": "t1"}),
            _event("task_complete", {"turn_id": "t1", "last_agent_message": "上一轮"}),
            _event("task_started", {"turn_id": "t2"}),
        ],
    )
    turn = codex_store.latest_turn(sid)
    assert turn.done is False
    assert turn.turn_id == "t2"


def test_latest_turn_surfaces_a_turn_codex_marked_failed(codex_home, tmp_path):
    """轮次终结了但 codex 标了错误：MUST 把原文带出来。

    这一档正是"鉴权失败 / provider 拒绝"的现场：轮次确实结束了，答案却是空的。
    静默返回空字符串会让调用方以为一切正常。
    """
    sid = "sid-error"
    _session_with(
        codex_home,
        tmp_path,
        sid,
        [
            _event("task_started", {"turn_id": "t1"}),
            _event(
                "task_complete",
                {
                    "turn_id": "t1",
                    "last_agent_message": None,
                    "error": {"message": "No tool output found"},
                },
            ),
        ],
    )
    turn = codex_store.latest_turn(sid)
    assert turn.done is True
    assert turn.text == ""
    assert turn.error == "No tool output found"


def test_latest_turn_falls_back_to_the_assistant_message(codex_home, tmp_path):
    sid = "sid-fallback"
    _session_with(
        codex_home,
        tmp_path,
        sid,
        [
            _event("task_started", {"turn_id": "t1"}),
            _item("message", {"id": "m1", "role": "assistant",
                              "content": [{"type": "output_text", "text": "正文在这"}]}),
            _event("task_complete", {"turn_id": "t1", "last_agent_message": None}),
        ],
    )
    assert codex_store.latest_turn(sid).text == "正文在这"


def test_latest_turn_is_done_even_when_task_started_fell_out_of_the_tail(
    codex_home, tmp_path, monkeypatch
):
    """回读窗口罩不住 ``task_started`` 时，结论仍然是"答完了"。

    按"配对 turn_id"判就会在这里永远判不出答完，本轮空等到超时——所以判据只看
    末段里最后出现的是开始还是结束。
    """
    monkeypatch.setattr(codex_store, "_TAIL_BYTES", 200)
    sid = "sid-tail"
    filler = [
        _item("message", {"id": f"f{i}", "role": "developer",
                          "content": [{"type": "input_text", "text": "x" * 200}]})
        for i in range(10)
    ]
    _session_with(
        codex_home,
        tmp_path,
        sid,
        [
            _event("task_started", {"turn_id": "t1"}),
            *filler,
            _event("task_complete", {"turn_id": "t1", "last_agent_message": "ok"}),
        ],
    )
    turn = codex_store.latest_turn(sid)
    assert turn.done is True
    assert turn.text == "ok"


# ── 记录归一化 ──────────────────────────────────────────────────────
def test_user_text_comes_from_the_event_not_the_model_side_copy():
    """用户那半轮取 ``event_msg``，不取混着环境说明的 ``response_item``。"""
    clean = _event("user_message", {"message": "帮我看看这个 bug"})
    noisy = _item(
        "message",
        {"id": "m0", "role": "user",
         "content": [{"type": "input_text", "text": "<environment_context>…"}]},
    )
    kinds = [k for k, _ in codex_store.record_payloads(clean, "s", include_user=True)]
    assert kinds == [codex_store.RECORD_USER_TEXT]
    assert codex_store.record_payloads(noisy, "s", include_user=True) == []


def test_injected_developer_context_never_reaches_the_archive():
    """frago 经钩子注入的上下文在 rollout 里是 developer 消息，一条都不取。"""
    injected = _item(
        "message",
        {"id": "m1", "role": "developer",
         "content": [{"type": "input_text", "text": "frago 的行为守则…"}]},
    )
    assert codex_store.record_payloads(injected, "s", include_user=True) == []


def test_user_text_is_withheld_from_the_streaming_path():
    """实时流里用户消息由主路径自己投递，来源再投一次会在前端出现两遍。"""
    clean = _event("user_message", {"message": "问题"})
    assert codex_store.record_payloads(clean, "s") == []


def test_assistant_text_only_takes_the_final_answer_phase():
    final = _event("agent_message", {"message": "结论", "phase": "final_answer"})
    interim = _event("agent_message", {"message": "中途", "phase": "progress"})
    kinds = [k for k, _ in codex_store.record_payloads(final, "s")]
    assert kinds == [codex_store.RECORD_TEXT]
    assert codex_store.record_payloads(interim, "s") == []


def test_tool_call_and_result_normalize_into_the_shared_shape():
    call = _item(
        "function_call",
        {"id": "fc1", "call_id": "call_00", "name": "exec_command",
         "arguments": '{"cmd": "echo hi"}'},
    )
    result = _item(
        "function_call_output",
        {"id": "fco1", "call_id": "call_00", "output": "hi\n"},
    )
    (kind, payload), = codex_store.record_payloads(call, "s")
    assert kind == codex_store.RECORD_TOOL_CALL
    assert payload["tool_calls"] == [
        {"id": "call_00", "name": "exec_command", "input": {"cmd": "echo hi"}}
    ]
    (kind, payload), = codex_store.record_payloads(result, "s")
    assert kind == codex_store.RECORD_TOOL_RESULT
    assert payload["tool_results"] == [
        {"tool_use_id": "call_00", "content": "hi\n", "is_error": False}
    ]


def test_reasoning_and_bookkeeping_records_are_dropped():
    for record in (
        _item("reasoning", {"id": "r1", "content": [{"type": "reasoning_text",
                                                     "text": "想…"}]}),
        _event("token_count", {"info": {}}),
        {"timestamp": "2026-08-19T15:07:11.570Z", "type": "world_state", "payload": {}},
    ):
        assert codex_store.record_payloads(record, "s", include_user=True) == []


# ── 身份映射 ────────────────────────────────────────────────────────
def test_binding_roundtrip(codex_home, tmp_path):
    assert codex_store.get_binding("frago-1") is None
    codex_store.put_binding("frago-1", "codex-1", str(tmp_path))
    assert codex_store.get_binding("frago-1") == "codex-1"
    codex_store.drop_binding("frago-1")
    assert codex_store.get_binding("frago-1") is None


def test_corrupt_binding_file_reads_as_empty(codex_home):
    codex_store.BINDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    codex_store.BINDINGS_PATH.write_text("{not json", encoding="utf-8")
    assert codex_store.get_binding("frago-1") is None
