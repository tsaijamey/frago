"""会话自有消息队列与 [end, end-5] 轮交互卡门控测试。"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from frago.server.services import session_observer, workbench_queue
from frago.session import record_reader
from frago.session.unified_record import UnifiedRecord

CC_SID = "00a02979-7eb4-5c70-94ae-867c8281e3f6"

DECISION_FENCE = (
    "请确认发布方案：\n\n"
    "```answer-needed-by-human\n"
    "question: 是否立即发布？\n"
    "options:\n"
    "  - key: A\n"
    "    label: 立即发布\n"
    "    will: 推送并打标签\n"
    "  - key: B\n"
    "    label: 暂缓\n"
    "    will: 保持当前分支\n"
    "```"
)

FRAGO_ASK_TOOL_OUTPUT = json.dumps(
    {
        "frago_ui_component": "decision-card",
        "kind": "single-choice",
        "question": "选择部署目标环境？",
        "options": [
            {"key": "A", "label": "生产环境", "will": "部署至线上"},
            {"key": "B", "label": "预发环境", "will": "部署至预发"},
        ],
    },
    ensure_ascii=False,
)


def _rec(
    seq: int,
    kind: str,
    payload: dict[str, Any],
    *,
    group_id: str | None = None,
    agent_path: list[str] | None = None,
) -> UnifiedRecord:
    return UnifiedRecord(
        id=f"rec-{seq}",
        session_id=CC_SID,
        group_id=group_id,
        seq=seq,
        ts=1_700_000_000_000 + seq * 1000,
        kind=kind,  # type: ignore[arg-type]
        agent_path=agent_path or [],
        payload=payload,
    )


def _normal_turn(turn_idx: int, base_seq: int) -> list[UnifiedRecord]:
    return [
        _rec(base_seq, "user.say", {"text": f"用户提问 {turn_idx}"}),
        _rec(
            base_seq + 1,
            "agent.say",
            {"text": f"普通回复 {turn_idx}"},
            group_id=f"grp-{turn_idx}",
        ),
    ]


def _hook_supplement_turn(turn_idx: int, base_seq: int) -> list[UnifiedRecord]:
    return [
        _rec(
            base_seq,
            "context.inject",
            {"source": "hook", "body": f"Stop hook 补充要求 {turn_idx}"},
        ),
        _rec(
            base_seq + 1,
            "agent.say",
            {"text": f"根据 hook 补充的说明 {turn_idx}"},
            group_id=f"grp-hook-{turn_idx}",
        ),
    ]


@pytest.fixture(autouse=True)
def isolated_queue_env(tmp_path, monkeypatch):
    workbench_queue.reset_runtime_state()
    monkeypatch.setattr(workbench_queue, "_sender_override", None)
    monkeypatch.setattr(
        session_observer,
        "session_dir",
        lambda sid, family: tmp_path / "sessions" / family / sid,
    )
    monkeypatch.setattr(record_reader, "detect_family", lambda _sid: "claude-code")
    yield tmp_path
    workbench_queue.reset_runtime_state()


@pytest.fixture
def client():
    from frago.server.app import create_app

    return TestClient(create_app(), client=("127.0.0.1", 50000))


class TestTailTurnsInteractiveCardCheck:
    """验证 [end, end-5]（最近 6 轮）交互卡门控逻辑。"""

    def test_no_card_in_tail_turns_allows_injection(self):
        records: list[UnifiedRecord] = []
        for i in range(6):
            records.extend(_normal_turn(i, i * 10))
        assert workbench_queue.has_interactive_card_in_tail_turns(records) is False
        assert workbench_queue.detect_stop_turn_id(records) == "rec-51"

    @pytest.mark.parametrize("hook_turns_after_card", [0, 1, 2, 3, 4, 5])
    def test_card_within_end_to_end_minus_5_blocks_injection(self, hook_turns_after_card: int):
        """当交互卡出现在 end（0 轮补充）到 end-5（5 轮补充）之间时，一律阻断自动注入。"""
        records: list[UnifiedRecord] = [
            _rec(1, "user.say", {"text": "帮我准备发布"}),
            _rec(2, "agent.say", {"text": DECISION_FENCE}, group_id="grp-card"),
        ]
        for h in range(hook_turns_after_card):
            records.extend(_hook_supplement_turn(h + 1, 10 + h * 10))

        turns = workbench_queue.segment_main_turns(records)
        assert len(turns) == 1 + hook_turns_after_card
        assert workbench_queue.has_interactive_card_in_tail_turns(records) is True

    def test_frago_ask_tool_result_occluded_by_5_hook_turns_still_blocks(self):
        """`frago ask` 产出的 tool.result 交互卡即使被 5 轮 hook 补充回复遮挡（位于 end-5），仍阻断注入。"""
        records: list[UnifiedRecord] = [
            _rec(1, "user.say", {"text": "部署到哪里？"}),
            _rec(2, "tool.call", {"tool": "ask"}, group_id="grp-ask"),
            _rec(
                3,
                "tool.result",
                {"status": "ok", "body": FRAGO_ASK_TOOL_OUTPUT},
                group_id="grp-ask",
            ),
            _rec(4, "agent.say", {"text": "请在上方卡片选择环境"}, group_id="grp-ask"),
        ]
        for h in range(5):
            records.extend(_hook_supplement_turn(h + 1, 20 + h * 10))

        turns = workbench_queue.segment_main_turns(records)
        assert len(turns) == 6  # [end-5 .. end]
        assert workbench_queue.has_interactive_card_in_tail_turns(records) is True

    def test_card_at_end_minus_6_no_longer_blocks(self):
        """当交互卡已经在 end-6（后面已有 6 轮无卡轮次）时，不再阻断。"""
        records: list[UnifiedRecord] = [
            _rec(1, "user.say", {"text": "帮我准备发布"}),
            _rec(2, "agent.say", {"text": DECISION_FENCE}, group_id="grp-card"),
        ]
        for h in range(6):
            records.extend(_hook_supplement_turn(h + 1, 10 + h * 10))

        turns = workbench_queue.segment_main_turns(records)
        assert len(turns) == 7
        assert workbench_queue.has_interactive_card_in_tail_turns(records) is False

    def test_card_answered_by_human_no_longer_blocks(self):
        """若交互卡已被人类通过【answer】回复确认，后续 stop 轮次不再被该旧卡阻断。"""
        records: list[UnifiedRecord] = [
            _rec(1, "user.say", {"text": "帮我准备发布"}),
            _rec(2, "agent.say", {"text": DECISION_FENCE}, group_id="grp-card"),
            _rec(3, "user.say", {"text": "【answer】A · 立即发布 —— 推送并打标签"}),
            _rec(4, "agent.say", {"text": "好的，已完成发布。"}, group_id="grp-done"),
        ]
        assert workbench_queue.has_interactive_card_in_tail_turns(records) is False


class TestQueueAutoInjectionAndRoutes:
    """验证队列持久化、FIFO 弹出、忙时不注入、stop 且无卡时自动注入最早一条。"""

    def test_fifo_pop_and_auto_inject_one_per_stop_turn(self, monkeypatch):
        injected: list[tuple[str, str]] = []
        monkeypatch.setattr(
            workbench_queue,
            "_sender_override",
            lambda sid, prompt, _cwd: injected.append((sid, prompt)),
        )
        busy_state = {"busy": True}
        monkeypatch.setattr(workbench_queue, "is_session_busy", lambda _sid: busy_state["busy"])

        records: list[UnifiedRecord] = _normal_turn(1, 10)
        monkeypatch.setattr(
            record_reader, "read_records", lambda *_a, **_k: list(records)
        )

        # 1. 会话执行中入队两条消息：只堆积，不注入
        workbench_queue.enqueue(CC_SID, text="第一条排队消息", prompt="第一条排队消息")
        workbench_queue.enqueue(CC_SID, text="第二条排队消息", prompt="第二条排队消息")
        assert len(workbench_queue.list_queue(CC_SID)) == 2

        res_busy = workbench_queue.try_auto_inject(CC_SID, sync=True)
        assert res_busy["injected"] is False
        assert res_busy["reason"] == "not_stopped"
        assert injected == []
        assert len(workbench_queue.list_queue(CC_SID)) == 2

        # 2. 会话 stop 且 [end, end-5] 无交互卡：自动注入最早的第一条，并从队列删除
        busy_state["busy"] = False
        res_stop_1 = workbench_queue.try_auto_inject(CC_SID, sync=True)
        assert res_stop_1["injected"] is True
        assert res_stop_1["item"]["text"] == "第一条排队消息"
        assert injected == [(CC_SID, "第一条排队消息")]
        remaining = workbench_queue.list_queue(CC_SID)
        assert [it["text"] for it in remaining] == ["第二条排队消息"]

        # 3. 同一轮 stop 不会把第二条也连着弹出去（必须等第一条执行完产生新的 stop 轮次）
        res_same_turn = workbench_queue.try_auto_inject(CC_SID, sync=True)
        assert res_same_turn["injected"] is False
        assert res_same_turn["reason"] == "already_injected_for_turn"
        assert len(workbench_queue.list_queue(CC_SID)) == 1

        # 4. 第一条消息跑完并出现新的 stop 轮次（无交互卡）：自动注入第二条，队列清空
        records.extend(_normal_turn(2, 20))
        res_stop_2 = workbench_queue.try_auto_inject(CC_SID, sync=True)
        assert res_stop_2["injected"] is True
        assert res_stop_2["item"]["text"] == "第二条排队消息"
        assert [p for _, p in injected] == ["第一条排队消息", "第二条排队消息"]
        assert workbench_queue.list_queue(CC_SID) == []

    def test_queue_rest_endpoints_enqueue_delete_reorder_and_drain(
        self, client, monkeypatch
    ):
        injected: list[str] = []
        monkeypatch.setattr(
            workbench_queue,
            "_sender_override",
            lambda _sid, prompt, _cwd: injected.append(prompt),
        )
        monkeypatch.setattr(workbench_queue, "is_session_busy", lambda _sid: False)

        # 先构造存在交互卡被 hook 遮挡在 end-2 的记录：此时 drain 不应注入
        records_with_card: list[UnifiedRecord] = [
            _rec(1, "user.say", {"text": "请处理"}),
            _rec(2, "agent.say", {"text": DECISION_FENCE}, group_id="g1"),
            *_hook_supplement_turn(1, 10),
            *_hook_supplement_turn(2, 20),
        ]
        current_records = {"data": records_with_card}
        monkeypatch.setattr(
            record_reader, "read_records", lambda *_a, **_k: list(current_records["data"])
        )

        r1 = client.post(
            f"/api/workbench/sessions/{CC_SID}/queue",
            json={"text": "消息甲"},
        )
        assert r1.status_code == 200
        r2 = client.post(
            f"/api/workbench/sessions/{CC_SID}/queue",
            json={"text": "消息乙"},
        )
        assert r2.status_code == 200
        r3 = client.post(
            f"/api/workbench/sessions/{CC_SID}/queue",
            json={"text": "消息丙"},
        )
        assert r3.status_code == 200

        q_get = client.get(f"/api/workbench/sessions/{CC_SID}/queue").json()
        assert [it["text"] for it in q_get["items"]] == ["消息甲", "消息乙", "消息丙"]
        assert q_get["blocked_by_card"] is True
        assert q_get["can_inject"] is False

        # 删除中间那条「消息乙」
        second_id = q_get["items"][1]["id"]
        q_del = client.delete(
            f"/api/workbench/sessions/{CC_SID}/queue/{second_id}"
        ).json()
        assert [it["text"] for it in q_del["items"]] == ["消息甲", "消息丙"]

        # 重排：把「消息丙」移到最前
        ids = [it["id"] for it in q_del["items"]]
        q_reorder = client.put(
            f"/api/workbench/sessions/{CC_SID}/queue",
            json={"item_ids": [ids[1], ids[0]]},
        ).json()
        assert [it["text"] for it in q_reorder["items"]] == ["消息丙", "消息甲"]

        # 此时 [end, end-5] 有交互卡，drain 不会注入
        drain_blocked = client.post(
            f"/api/workbench/sessions/{CC_SID}/queue/drain"
        ).json()
        assert drain_blocked["injected"] is False
        assert drain_blocked["reason"] == "blocked_by_card"
        assert len(drain_blocked["items"]) == 2
        assert injected == []

        # 当记录变为无交互卡的 stop 轮次后，drain 自动注入队首「消息丙」并从队列移除
        current_records["data"] = _normal_turn(1, 100)
        drain_ok = client.post(
            f"/api/workbench/sessions/{CC_SID}/queue/drain"
        ).json()
        assert drain_ok["injected"] is True
        assert drain_ok["item"]["text"] == "消息丙"
        assert [it["text"] for it in drain_ok["items"]] == ["消息甲"]

    def test_schedule_auto_inject_retries_across_stop_hook_window(self, monkeypatch):
        """复现并回归：_on_turn_complete 触发时 Stop hook 尚在运行（not_stopped），
        后台退避重试应在 Stop hook 结束后自动完成注入，无需用户切回会话。
        """
        import time

        injected: list[tuple[str, str]] = []
        monkeypatch.setattr(
            workbench_queue,
            "_sender_override",
            lambda sid, prompt, _cwd: injected.append((sid, prompt)),
        )
        # 前两次检查模拟 Stop hook 仍在忙碌，第三次检查起变为空闲
        checks = {"count": 0}

        def fake_busy(_sid: str) -> bool:
            checks["count"] += 1
            return checks["count"] <= 2

        monkeypatch.setattr(workbench_queue, "is_session_busy", fake_busy)
        monkeypatch.setattr(
            record_reader, "read_records", lambda *_a, **_k: _normal_turn(1, 10)
        )

        workbench_queue.enqueue(CC_SID, text="后台自动触发的下一项任务", prompt="后台自动触发的下一项任务")
        workbench_queue.schedule_auto_inject_after_settle(
            CC_SID, delay_s=0.01, retry_delay_s=0.02, max_retries=5
        )

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not injected:
            time.sleep(0.01)

        assert checks["count"] >= 3
        assert injected == [(CC_SID, "后台自动触发的下一项任务")]
        assert workbench_queue.list_queue(CC_SID) == []

    def test_patrol_active_queues_discovers_and_injects_background_session(
        self, monkeypatch
    ):
        """未打开详情页或服务重启前已入队的后台会话，patrol_active_queues 应自动发现并注入。"""
        injected: list[tuple[str, str]] = []
        monkeypatch.setattr(
            workbench_queue,
            "_sender_override",
            lambda sid, prompt, _cwd: injected.append((sid, prompt)),
        )
        monkeypatch.setattr(workbench_queue, "is_session_busy", lambda _sid: False)
        monkeypatch.setattr(
            record_reader, "read_records", lambda *_a, **_k: _normal_turn(1, 10)
        )

        workbench_queue.enqueue(CC_SID, text="后台巡检任务", prompt="后台巡检任务")
        # 模拟服务刚重启、内存态尚未登记但落盘文件存在
        with workbench_queue._locks_guard:
            workbench_queue._queued_sessions.clear()
            workbench_queue._seeded_from_disk = False

        injected_sids = workbench_queue.patrol_active_queues(sync=True)
        assert injected_sids == [CC_SID]
        assert injected == [(CC_SID, "后台巡检任务")]
        assert workbench_queue.list_queue(CC_SID) == []

