"""Tests for the session observer — the side panel's five slots.

Nothing here touches a real frago-core, a real session or the real settings: the
observer takes its reader, its asker and its binding check as arguments.
"""

import json
import os
import stat
import threading

import pytest

from frago.server.services import session_observer as so
from frago.session.session_index import FRAGO_WAKE_MARKERS
from frago.session.unified_record import UnifiedRecord

SID = "11111111-2222-3333-4444-555555555555"


def rec(seq, kind, **payload):
    return UnifiedRecord(
        id=f"r{seq}", session_id=SID, group_id=None, seq=seq, ts=seq, kind=kind, payload=payload
    )


def raw(seq, kind, **payload):
    """监听线上那批的样子：统一的记录还没造出来，传过来的是字典。"""
    return {"id": f"r{seq}", "session_id": SID, "seq": seq, "ts": seq, "kind": kind, "payload": payload}


def human(seq, text):
    return rec(seq, "user.say", text=text, is_tool_result=False)


class FakeSession:
    """Serves records the way record_reader.read_records does."""

    def __init__(self, records):
        self.records = list(records)

    def __call__(self, session_id, after=0, limit=200, tail=False):
        if tail:
            return self.records[-limit:]
        return [r for r in self.records if r.seq >= after][:limit]


def answer(**fields):
    body = {"now": "", "decision": "", "output": "", "happened_add": [], "anchor_seq": None}
    body.update(fields)
    return {"ok": True, "text": json.dumps(body, ensure_ascii=False), "model": "deepseek-v4-flash"}


def observer(tmp_path, session, ask, bound=True):
    return so.SessionObserver(
        ask=ask,
        read_records=session,
        bound=lambda: bound,
        base_dir=lambda sid, family: tmp_path / family / sid,
        detect_family=lambda sid: "claude-code",
        max_workers=2,
    )


def slots_of(tmp_path):
    return json.loads((tmp_path / "claude-code" / SID / so.SLOTS_FILENAME).read_text())


def runs_of(tmp_path):
    path = tmp_path / "claude-code" / SID / so.RUNS_FILENAME
    return [json.loads(line) for line in path.read_text().splitlines()]


class TestWhatCountsAsSomethingThePersonSaid:
    def test_typed_words_count(self):
        assert so.human_text(human(0, "把会话记录归一")) == "把会话记录归一"

    def test_tool_results_do_not(self):
        assert so.human_text(rec(0, "user.say", text="ok", is_tool_result=True)) is None

    def test_frago_waking_the_pa_does_not(self):
        wake = human(0, FRAGO_WAKE_MARKERS[0] + " 醒醒")
        assert so.human_text(wake) is None

    def test_the_same_rule_reads_the_dicts_the_watcher_hands_over(self):
        """监听线上那批还没变成记录，判据必须跟记录那一侧是同一条。"""
        assert so.spoken_text({"text": "把会话记录归一"}) == "把会话记录归一"
        assert so.spoken_text({"text": "ok", "is_tool_result": True}) is None
        assert so.spoken_text({"text": FRAGO_WAKE_MARKERS[0] + " 醒醒"}) is None
        assert so.spoken_text(None) is None
        assert so.human_text(rec(0, "agent.say", text="在")) is None, "kind is judged outside"


class TestWhenTheObserverIsWoken:
    """人刚发话就该叫一次，不等 agent 把话交还——两格说的都是眼下。"""

    def test_a_person_speaking_wakes_it(self):
        assert so.person_spoke([raw(1, "user.say", text="把这件事改了", is_tool_result=False)])

    def test_a_tool_result_written_as_a_user_line_does_not(self):
        assert not so.person_spoke([raw(1, "user.say", text="ok", is_tool_result=True)])

    def test_nothing_but_the_agents_own_words_does_not(self):
        assert not so.person_spoke([raw(1, "agent.say", text="改好了"), raw(2, "tool.call", tool_name="Read")])

    def test_an_empty_batch_does_not(self):
        assert not so.person_spoke([])


class TestHeartbeat:
    def test_a_wake_word_and_an_empty_reply_is_skipped(self):
        batch = [human(0, FRAGO_WAKE_MARKERS[0]), rec(1, "agent.say", text="No response requested.")]
        assert so.is_heartbeat_batch(batch)

    def test_a_wake_word_followed_by_real_work_is_not(self):
        batch = [
            human(0, FRAGO_WAKE_MARKERS[0]),
            rec(1, "tool.call", tool_name="Bash", args={"command": "ls"}),
            rec(2, "agent.say", text="看了"),
        ]
        assert not so.is_heartbeat_batch(batch)


class TestWhatTheModelIsShown:
    def test_thinking_and_tool_output_are_left_out(self):
        assert so.record_line(rec(0, "agent.think", text="")) is None
        assert so.record_line(rec(1, "tool.result", body="x" * 9000)) is None

    def test_a_tool_call_is_named_with_its_target(self):
        line = so.record_line(rec(0, "tool.call", tool_name="Read", args={"file_path": "/a/b.py"}))
        assert line == "[工具] Read /a/b.py"

    def test_only_finished_or_running_todos_are_shown(self):
        line = so.record_line(
            rec(
                0,
                "todo.snapshot",
                items=[
                    {"content": "改 llm.rs", "status": "completed"},
                    {"content": "写测试", "status": "in_progress"},
                    {"content": "部署", "status": "pending"},
                ],
            )
        )
        assert "改 llm.rs" in line and "写测试" in line
        assert "部署" not in line, "a step that has not happened must not reach the model"

    def test_the_passive_todo_resend_is_skipped(self):
        assert so.record_line(rec(0, "todo.snapshot", items=[], source="engine-reminder")) is None


class TestTheRules:
    def test_percentages_counts_and_estimates_are_refused(self):
        for bad in ("测试过了 80%", "5 个里做完 3/5", "预计十分钟"):
            ans = so.parse_answer(json.dumps({"now": bad}))
            assert so.violation(ans), bad

    def test_future_steps_are_refused_outside_the_decision_slot(self):
        assert so.violation(so.parse_answer(json.dumps({"now": "下一步改前端"})))
        ok = so.parse_answer(json.dumps({"decision": "下一步先改前端还是先部署？"}))
        assert so.violation(ok) is None

    def test_dates_and_paths_are_not_counts(self):
        ans = so.parse_answer(json.dumps({"output": "2026/09/11 写好了 src/v1/messages.rs"}))
        assert so.violation(ans) is None

    def test_code_fences_around_the_answer_are_tolerated(self):
        ans = so.parse_answer('```json\n{"now": "在跑测试"}\n```')
        assert ans["now"] == "在跑测试"

    def test_the_empty_marks_it_was_shown_are_not_taken_as_content(self):
        """The prompt writes （还没有） for an empty slot; a model copying it back is not saying anything."""
        ans = so.parse_answer(
            json.dumps(
                {"now": "（还没有）", "output": " （无） ", "happened_add": ["（还没有）", "真的一件事"]},
                ensure_ascii=False,
            )
        )
        assert ans["now"] == ""
        assert ans["output"] == ""
        assert ans["happened_add"] == ["真的一件事"]

    def test_no_json_is_a_format_error(self):
        with pytest.raises(ValueError):
            so.parse_answer("我觉得挺好")


class TestMerging:
    def test_each_slot_follows_its_own_rule(self):
        slots = so.empty_slots(SID, "claude-code")
        slots.update(output="旧产出", decision="要不要部署", happened=["a"])
        changed = so.apply_answer(
            slots,
            so.parse_answer(json.dumps({"now": "在改前端", "happened_add": ["a", "b"]})),
            {7: "部署吧"},
        )
        assert changed
        assert slots["now"] == "在改前端"
        assert slots["output"] == "旧产出", "no new output keeps the last one"
        assert slots["decision"] == "", "an answered question clears the slot"
        assert slots["happened"] == ["a", "b"], "only appended, never repeated"

    def test_a_pending_question_survives_a_stretch_where_nobody_answered_it(self):
        """「需要你决策」是常驻状态，不是「这一段里新出现的待决」。

        模型每次只看得见新增的那一段，而问题是上一段提的，这一段里不会再出现一遍。人没
        开口就把空回答当成「已经答了」，等于 agent 一问完、下一批记录一到就把问题擦掉。
        实测正是这么丢的：agent 摆出三条改法让人挑，两秒后一条轮次边界落盘，这一格就空了。
        """
        slots = so.empty_slots(SID, "claude-code")
        slots["decision"] = "三条改法要人挑一条"

        so.apply_answer(slots, so.parse_answer('{"now": "还在跑测试"}'), {})
        assert slots["decision"] == "三条改法要人挑一条", "人没开口，问题就还挂着"

        so.apply_answer(slots, so.parse_answer('{"now": "在改前端"}'), {9: "选 C"})
        assert slots["decision"] == "", "人开了口又没有新的待决，这一格才算清掉"

    def test_each_slot_carries_the_moment_it_last_changed(self):
        """右栏按时间线读，每一格要分得出是刚刚变的还是半小时前就停在那儿了。

        记的是「上次**变样**」不是「上次被写过」：旁路每轮都跑，值没变也照写一遍，跟着
        写时刻的话，一格几小时没动的内容会一直显示成「刚刚」。
        """
        slots = so.empty_slots(SID, "claude-code")
        so.apply_answer(slots, so.parse_answer('{"now": "在改前端", "happened_add": ["读了 a.py"]}'), {}, 1000)
        assert slots["now_at"] == 1000
        assert slots["happened_at"] == [1000]
        assert slots["output_at"] is None, "没填过的格子没有时刻"

        so.apply_answer(slots, so.parse_answer('{"now": "在改前端"}'), {}, 9000)
        assert slots["now_at"] == 1000, "值没变，时刻不许动"

        so.apply_answer(slots, so.parse_answer('{"now": "在跑测试"}'), {}, 9000)
        assert slots["now_at"] == 9000

    def test_an_old_slots_file_without_times_lines_up_instead_of_skewing(self):
        """老槽位文件只有正文没有时刻。新加的那条不能错位标到老内容头上。"""
        slots = so.empty_slots(SID, "claude-code")
        slots["happened"] = ["很久以前的 a", "很久以前的 b"]
        slots.pop("happened_at")
        so.apply_answer(slots, so.parse_answer('{"happened_add": ["刚发生的 c"]}'), {}, 7000)
        assert slots["happened"] == ["很久以前的 a", "很久以前的 b", "刚发生的 c"]
        assert slots["happened_at"] == [None, None, 7000]

        view = so.public_state(slots, bound=True)
        assert view["happened"] == ["刚发生的 c", "很久以前的 b", "很久以前的 a"]
        assert view["happened_at"] == [7000, None, None], "正文倒过来，时刻要跟着倒"

    def test_the_anchor_moves_only_to_something_the_person_said_in_this_stretch(self):
        slots = so.empty_slots(SID, "claude-code")
        slots["anchor"] = {"seq": 0, "text": "原目标"}
        so.apply_answer(slots, so.parse_answer('{"anchor_seq": 99}'), {7: "新目标"})
        assert slots["anchor"]["seq"] == 0, "a number not offered is ignored"
        so.apply_answer(slots, so.parse_answer('{"anchor_seq": 7}'), {7: "新目标"})
        assert slots["anchor"] == {"seq": 7, "text": "新目标"}


class TestOneRun:
    def test_first_run_fills_the_slots_and_moves_the_cursor(self, tmp_path):
        session = FakeSession(
            [
                human(0, "把会话记录归一成同一种形状"),
                rec(1, "tool.call", tool_name="Read", args={"file_path": "unified_record.py"}),
                rec(2, "agent.say", text="十五种形态已经对齐"),
            ]
        )
        seen = {}

        def ask(prompt):
            seen["prompt"] = prompt
            return answer(now="十五种形态已经对齐", happened_add=["读了 unified_record.py"])

        entry = observer(tmp_path, session, ask).run_once(SID, "turn")
        slots = slots_of(tmp_path)

        assert entry["changed"] is True
        assert slots["cursor"] == 3
        assert slots["anchor"] == {"seq": 0, "text": "把会话记录归一成同一种形状"}
        assert slots["now"] == "十五种形态已经对齐"
        assert "[工具] Read unified_record.py" in seen["prompt"]
        assert runs_of(tmp_path)[-1]["trigger"] == "turn"

    def test_nothing_new_asks_nothing(self, tmp_path):
        session = FakeSession([human(0, "你好"), rec(1, "agent.say", text="在")])
        calls = []
        obs = observer(tmp_path, session, lambda p: calls.append(p) or answer(now="在"))
        obs.run_once(SID, "turn")
        entry = obs.run_once(SID, "open")
        assert entry["skipped"] == "nothing-new"
        assert len(calls) == 1

    def test_a_failed_ask_keeps_the_cursor_so_nothing_is_lost(self, tmp_path):
        session = FakeSession([human(0, "你好"), rec(1, "agent.say", text="在")])
        obs = observer(
            tmp_path, session, lambda p: {"ok": False, "kind": "credential", "error": "WorkBuddy 没登录"}
        )
        obs.run_once(SID, "turn")
        slots = slots_of(tmp_path)
        assert slots["cursor"] == 0
        assert slots["status"] == "failed"
        assert "WorkBuddy" in slots["status_detail"]

    def test_a_rule_breaking_answer_changes_nothing_but_is_not_asked_again(self, tmp_path):
        session = FakeSession([human(0, "你好"), rec(1, "agent.say", text="在")])
        entry = observer(tmp_path, session, lambda p: answer(now="做完了 90%")).run_once(SID, "turn")
        slots = slots_of(tmp_path)
        assert entry["rejected"]
        assert slots["now"] == ""
        assert slots["cursor"] == 2

    def test_a_batch_with_nothing_to_read_never_reaches_the_model(self, tmp_path):
        """一批全是看不见的东西（思考、工具结果、注入、轮次边界）时，不许去问模型。

        问了也是白问：模型看到一份空记录，只会如实答「这一段什么都没有」，而那份空回答
        会盖掉右栏里本来有内容的格子。实测踩到过：agent 刚摆出三条改法等人挑，两秒后一条
        轮次边界落盘，「需要你决策」当场被清空，人什么都没看到。
        """
        session = FakeSession([human(0, "你好"), rec(1, "agent.say", text="三条改法你挑一条")])
        calls = []
        obs = observer(
            tmp_path, session, lambda p: calls.append(p) or answer(decision="三条改法要人挑")
        )
        obs.run_once(SID, "turn")
        assert slots_of(tmp_path)["decision"] == "三条改法要人挑"

        # 轮次边界落盘：一条记录，正文一行都露不出来。
        session.records.append(rec(2, "call.envelope"))
        entry = obs.run_once(SID, "turn")

        assert entry["skipped"] == "nothing-to-read"
        assert len(calls) == 1, "白问一次既花钱又会把右栏擦掉"
        assert slots_of(tmp_path)["decision"] == "三条改法要人挑", "等人挑的那件事还挂着"
        assert slots_of(tmp_path)["cursor"] == 3, "游标照样往前，免得这一批反复重读"

    def test_an_unbound_observer_writes_nothing(self, tmp_path):
        session = FakeSession([human(0, "你好")])
        entry = observer(tmp_path, session, lambda p: answer(), bound=False).run_once(SID, "turn")
        assert entry["skipped"] == "unbound"
        assert not (tmp_path / "claude-code").exists()

    def test_a_session_gone_by_the_time_the_answer_lands_is_dropped(self, tmp_path):
        session = FakeSession([human(0, "你好"), rec(1, "agent.say", text="在")])

        def ask(prompt):
            session.records.clear()
            return answer(now="在")

        entry = observer(tmp_path, session, ask).run_once(SID, "turn")
        assert entry["skipped"] == "session-gone"
        assert not (tmp_path / "claude-code" / SID / so.SLOTS_FILENAME).exists()

    def test_a_long_backlog_is_cut_to_the_most_recent_stretch(self, tmp_path):
        records = [human(0, "开头")] + [
            rec(i, "agent.say", text=f"第{i}句") for i in range(1, so.BACKLOG_CAP + 50)
        ]
        seen = {}

        def ask(prompt):
            seen["prompt"] = prompt
            return answer(now="在说话")

        observer(tmp_path, FakeSession(records), ask).run_once(SID, "open")
        assert "更早的 50 条太多" in seen["prompt"]
        assert slots_of(tmp_path)["anchor"]["text"] == "开头", "the anchor is found even when cut"


class TestWhenTheNumberingShifts:
    """位置会动，身份不会——游标记的是「上次读到哪条」，不是「读到第几号」。

    整场会话每次都是重新编号的：引擎重写一条记录（每轮的花费账本只留最后一条），它后面
    所有记录的编号整体往前挪一格。人刚说的那句话于是可能排在游标**之前**，按位置读就永远
    读不到它。（2026-09-12 实测踩到：那句话再没进过右栏，执行记录里连一笔都没有。）
    """

    def one(self, seq, rid, kind, **payload):
        return UnifiedRecord(
            id=rid, session_id=SID, group_id=None, seq=seq, ts=seq, kind=kind, payload=payload
        )

    def test_a_line_that_moved_behind_the_cursor_is_still_fed(self, tmp_path):
        session = FakeSession(
            [
                self.one(0, "h1", "user.say", text="开头", is_tool_result=False),
                self.one(1, "r1", "agent.say", text="第一轮"),
            ]
        )
        seen: dict[str, str] = {}

        def ask(prompt):
            seen["prompt"] = prompt
            return answer(now="第一轮说完")

        obs = observer(tmp_path, session, ask)
        obs.run_once(SID, "turn")
        assert slots_of(tmp_path)["cursor"] == 2
        assert slots_of(tmp_path)["cursor_id"] == "r1"

        # 砍掉最前面那条：身份没变的那条挪到 0 号，人刚说的话落在 1 号——游标之前。
        session.records = [
            self.one(0, "r1", "agent.say", text="第一轮"),
            self.one(1, "h2", "user.say", text="接着说这个", is_tool_result=False),
        ]
        entry = obs.run_once(SID, "prompt")

        assert entry.get("skipped") != "nothing-new", "读空了不能就当作没有新的"
        assert "接着说这个" in seen["prompt"], "人刚说的那句必须喂到模型面前"
        assert slots_of(tmp_path)["cursor_id"] == "h2"

    def test_an_old_slots_file_without_an_identity_re_reads_once(self, tmp_path):
        """老槽位文件里没有「上次读到哪条」这一格，位置对不对无从判断，就退回去重读一段。

        只遇到一次：这一跑把身份补上，此后按身份判。老槽位是这次改动之前写下的，里面
        的游标可能已经在挪位中跳过了一句话，重喂一遍正好把那一句捞回来。
        """
        directory = tmp_path / "claude-code" / SID
        directory.mkdir(parents=True)
        old = so.empty_slots(SID, "claude-code")
        old.update(cursor=99)
        old.pop("cursor_id")
        (directory / so.SLOTS_FILENAME).write_text(json.dumps(old))

        session = FakeSession([self.one(0, "h1", "user.say", text="你好", is_tool_result=False)])
        seen: dict[str, str] = {}

        def ask(prompt):
            seen["prompt"] = prompt
            return answer(now="在")

        obs = observer(tmp_path, session, ask)
        entry = obs.run_once(SID, "open")
        assert entry.get("skipped") != "nothing-new"
        assert "你好" in seen["prompt"]
        assert slots_of(tmp_path)["cursor_id"] == "h1", "跑完就把身份补上"

        # 补上之后按身份判：真的没有新的才允许读空。
        entry = obs.run_once(SID, "prompt")
        assert entry["skipped"] == "nothing-new"

    def test_a_prompt_that_reads_nothing_leaves_a_trace(self, tmp_path):
        """人说了话，监听那边是看见了才叫我们的，这里却一条都没读到——要留一笔。

        坏掉时的症状：右栏毫无变化，而且事后查不出来——执行记录也干净得像什么都没发生。
        页面补读时读空是常态，那种不记。
        """
        session = FakeSession(
            [
                self.one(0, "h1", "user.say", text="你好", is_tool_result=False),
                self.one(1, "r1", "agent.say", text="在"),
            ]
        )
        obs = observer(tmp_path, session, lambda p: answer(now="在"))
        obs.run_once(SID, "turn")
        before = len(runs_of(tmp_path))

        entry = obs.run_once(SID, "prompt")
        assert entry["skipped"] == "nothing-new"
        assert len(runs_of(tmp_path)) == before + 1, "叫了却读空，执行记录里要留一笔"

        obs.run_once(SID, "open")
        assert len(runs_of(tmp_path)) == before + 1, "平时读空不记，免得把执行记录泡满"


class TestLanes:
    def test_a_trigger_during_a_run_is_owed_not_lost_and_not_run_in_parallel(self, tmp_path):
        session = FakeSession([human(0, "你好"), rec(1, "agent.say", text="在")])
        release = threading.Event()
        started = threading.Event()
        calls = []
        in_flight = []

        def ask(prompt):
            in_flight.append(1)
            assert len(in_flight) == 1, "one session never runs twice at once"
            calls.append(prompt)
            started.set()
            release.wait(5)
            in_flight.pop()
            return answer(now=f"第{len(calls)}次")

        obs = observer(tmp_path, session, ask)
        obs.notify(SID, "turn")
        assert started.wait(5)
        session.records.append(rec(2, "agent.say", text="又说了一句"))
        obs.notify(SID, "turn")
        obs.notify(SID, "interrupt")
        release.set()
        obs._pool.shutdown(wait=True)

        assert len(calls) == 2, "two triggers during one run fold into one more run"
        assert slots_of(tmp_path)["cursor"] == 3


class TestTheExtraWakePoints:
    """监听线上新来一批记录时，除了「一轮结束」还有两处要当场叫一次。"""

    @pytest.fixture
    def woken(self, monkeypatch):
        from frago.server.services.workbench_stream_bridge import WorkbenchStreamBridge

        seen: list[str] = []

        class FakeObserver:
            def notify(self, session_id, trigger):
                seen.append(trigger)

        monkeypatch.setattr(so, "get_observer", lambda *a, **k: FakeObserver())
        return WorkbenchStreamBridge(loop=None), seen

    def test_a_person_speaking_wakes_it_before_the_turn_ends(self, woken):
        bridge, seen = woken
        bridge._trigger_the_observer(SID, [raw(1, "user.say", text="把这件事改了")])
        assert seen == ["prompt"]

    def test_the_agent_talking_alone_does_not(self, woken):
        bridge, seen = woken
        bridge._trigger_the_observer(SID, [raw(1, "agent.say", text="改好了")])
        assert seen == []

    def test_an_interrupt_is_named_and_does_not_wake_it_twice(self, woken):
        bridge, seen = woken
        records = [raw(1, "interrupt"), raw(2, "user.say", text="别改了")]
        bridge._trigger_the_observer(SID, records)
        assert seen == ["interrupt"]

    def test_the_broadcast_path_hands_new_records_to_it(self, monkeypatch, woken):
        bridge, _ = woken
        seen: list[tuple[str, list]] = []
        monkeypatch.setattr(
            bridge, "_trigger_the_observer", lambda sid, records: seen.append((sid, records))
        )
        monkeypatch.setattr(so.asyncio, "run_coroutine_threadsafe", lambda *a, **k: None)

        records = [raw(1, "user.say", text="你好")]
        bridge._on_new_records(SID, records)
        assert seen == [(SID, records)]
        assert bridge._on_new_records(SID, []) is None and seen == [(SID, records)]


class TestOldBinaryGuard:
    def test_a_binary_without_ask_is_never_handed_a_question(self, tmp_path):
        """An old frago-core runs its full agent loop on an unknown first argument."""
        fake = tmp_path / "frago-core"
        fake.write_text("#!/bin/sh\necho 'frago-core — models list / add / remove'\n")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        obs = so.SessionObserver()
        try:
            assert obs._supports_ask(str(fake)) is False
            fake.write_text("#!/bin/sh\necho '  frago-core ask --role <lightagent|observer>'\n")
            os.utime(fake, (1, 1))
            assert obs._supports_ask(str(fake)) is True, "a changed binary is looked at again"
        finally:
            obs.shutdown()
