"""codex rollout JSONL 读取层的单测。

固定装置用的是 codex-cli 0.147.0 真实写出来的记录形状（字段名、嵌套、``event_msg``
与 ``response_item`` 的分工都照抄自实测文件），NEVER 按文档想象一份。
"""

import json
import os
from datetime import UTC, datetime

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


def _meta(session_id, cwd, ts="2026-08-19T15:07:11.570Z"):
    return {
        "timestamp": ts,
        "type": "session_meta",
        "payload": {
            "session_id": session_id,
            "id": session_id,
            "timestamp": ts,
            "cwd": cwd,
        },
    }


def _epoch_ms(iso_utc: str) -> int:
    return int(datetime.fromisoformat(iso_utc).replace(tzinfo=UTC).timestamp() * 1000)


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


def test_claim_picks_by_session_start_not_by_file_mtime(codex_home, tmp_path):
    """回归：认领 MUST 看这场会话什么时候**开始**，不看它的文件最后被动过是什么时候。

    20261009 现场：两场 codex 会话在同一个目录里隔了 45 秒先后起来，先起的那场还在
    干活、文件一直被写，mtime 比后起的那场新。按 mtime 挑就把先起的那场认成了后起
    这一场——两个 frago 句柄绑到同一个编号，后起那场的对话在页面上认不出来（完成
    探针去读别人的 rollout，永远等不到自己这一轮结束），它真正的那场会话也没人管，
    写锁一直攥在手里，下一次发消息就撞上 codex 的单写者锁。
    """
    first, second = "sid-started-first", "sid-started-second"
    started_first = _write_rollout(
        codex_home / "sessions",
        ("2026", "10", "09"),
        f"rollout-2026-10-09T14-02-15-{first}.jsonl",
        [_meta(first, str(tmp_path), ts="2026-10-09T06:02:15.000Z")],
    )
    started_second = _write_rollout(
        codex_home / "sessions",
        ("2026", "10", "09"),
        f"rollout-2026-10-09T14-03-02-{second}.jsonl",
        [_meta(second, str(tmp_path), ts="2026-10-09T06:03:02.000Z")],
    )
    # 先起的那场还在写：它的文件比后起的那个新。锚点取第二次新建发起的那一刻。
    now = datetime.now(UTC).timestamp()
    os.utime(started_first, (now, now))
    os.utime(started_second, (now - 120, now - 120))

    anchor = _epoch_ms("2026-10-09T06:03:00.000+00:00")
    assert codex_store.claim_session(str(tmp_path), anchor) == second


def test_claim_takes_the_earliest_session_after_the_anchor(codex_home, tmp_path):
    """锚点之后不止一场时取**最早**的那个：刚起的那一场排在别人后面，取最晚会取错。"""
    for sid, ts in (("sid-a", "2026-10-09T06:03:01.000Z"), ("sid-b", "2026-10-09T06:03:09.000Z")):
        _write_rollout(
            codex_home / "sessions",
            ("2026", "10", "09"),
            f"rollout-2026-10-09T14-03-00-{sid}.jsonl",
            [_meta(sid, str(tmp_path), ts=ts)],
        )
    anchor = _epoch_ms("2026-10-09T06:03:00.000+00:00")
    assert codex_store.claim_session(str(tmp_path), anchor) == "sid-a"


def test_claim_skips_a_session_already_bound_to_another_frago_session(codex_home, tmp_path):
    """已经认给别人的编号不再认一次：一个编号只属于一个 frago 会话。

    重复认领会把两场对话的记录接到一起，页面上谁也认不出自己那一场。
    """
    sid = "sid-taken"
    _write_rollout(
        codex_home / "sessions",
        ("2026", "10", "09"),
        f"rollout-2026-10-09T14-03-02-{sid}.jsonl",
        [_meta(sid, str(tmp_path), ts="2026-10-09T06:03:02.000Z")],
    )
    codex_store.put_binding("webui-someone-else", sid, str(tmp_path))

    assert codex_store.claim_session(str(tmp_path), 0) is None


def test_claim_refuses_a_rollout_that_does_not_say_when_it_started(codex_home, tmp_path):
    """首行没写起始时刻就**不认**，不退回文件时间——退回正是要治的那个错。"""
    sid = "sid-no-timestamp"
    record = _meta(sid, str(tmp_path))
    del record["timestamp"]
    del record["payload"]["timestamp"]
    _write_rollout(
        codex_home / "sessions",
        ("2026", "10", "09"),
        f"rollout-2026-10-09T14-03-02-{sid}.jsonl",
        [record],
    )
    assert codex_store.claim_session(str(tmp_path), 0) is None


def test_claim_falls_back_to_the_record_timestamp(codex_home, tmp_path):
    """payload 里没有起始时刻时退回整条记录的时间戳——少一处可比就永远认不回来。"""
    sid = "sid-top-level-ts"
    record = _meta(sid, str(tmp_path))
    del record["payload"]["timestamp"]
    _write_rollout(
        codex_home / "sessions",
        ("2026", "10", "09"),
        f"rollout-2026-10-09T14-03-02-{sid}.jsonl",
        [record],
    )
    anchor = _epoch_ms("2026-08-19T15:07:00.000+00:00")
    assert codex_store.claim_session(str(tmp_path), anchor) == sid


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


def test_drop_bindings_pointing_at_spares_the_others(codex_home, tmp_path):
    """按 codex 编号找 frago 编号：两边不是同一个编号空间，别把键当值删。"""
    codex_store.put_binding("frago-1", "codex-gone", str(tmp_path))
    codex_store.put_binding("frago-2", "codex-kept", str(tmp_path))
    # 键恰好长得和要删的那个一样，也必须留着——它指的是另一场会话。
    codex_store.put_binding("codex-gone", "codex-other", str(tmp_path))

    dropped = codex_store.drop_bindings_pointing_at("codex-gone")

    assert dropped == ["frago-1"]
    assert codex_store.get_binding("frago-1") is None
    assert codex_store.get_binding("frago-2") == "codex-kept"
    assert codex_store.get_binding("codex-gone") == "codex-other"


def test_corrupt_binding_file_reads_as_empty(codex_home):
    codex_store.BINDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    codex_store.BINDINGS_PATH.write_text("{not json", encoding="utf-8")
    assert codex_store.get_binding("frago-1") is None
