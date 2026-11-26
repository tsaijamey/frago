"""``/api/workbench/decisions`` 统一决策收件箱接口单元测试。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from frago.decision_inbox import get_decision_inbox_service
from frago.server.routes import decisions as decisions_route


@pytest.fixture
def inbox_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "decision-inbox"
    monkeypatch.setenv("FRAGO_DECISION_INBOX_DIR", str(path))
    return path


@pytest.fixture
def client(inbox_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def _empty_rows() -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(decisions_route, "collect_workbench_session_rows", _empty_rows)
    app = FastAPI()
    app.include_router(decisions_route.router, prefix="/api")
    return TestClient(app, client=("127.0.0.1", 50000))


class TestDecisionRoutesEmptyAndDualSource:
    def test_fresh_machine_empty_state(self, client: TestClient) -> None:
        resp = client.get("/api/workbench/decisions")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {
            "items": [],
            "counts": {"pending": 0, "schedule": 0, "session": 0, "snoozed": 0},
        }

    def test_aggregates_schedule_and_waiting_session_sources_consistently(
        self,
        inbox_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        svc = get_decision_inbox_service()
        sch_item = svc.propose(
            question="清理 128 个过期缓存目录？",
            action_type="binary",
            risk="high",
            irreversible=True,
            dedup_key="sch:cache-prune",
            schedule_id="sch_1",
            schedule_name="夜间巡检",
        )

        now_ms = int(time.time() * 1000)

        async def _fake_rows() -> list[dict[str, Any]]:
            return [
                # 1) 真实等待拍板的今日在线会话 -> 应计入 session 源
                {
                    "session_id": "ses-wait-1",
                    "title": "发布前核对",
                    "status": "idle",
                    "lifecycle_state": "idle",
                    "need_decision": True,
                    "has_running_worker": False,
                    "callback_queued": False,
                    "local_ops": False,
                    "last_reply_at": now_ms - 60_000,
                    "created_at": now_ms - 120_000,
                    "last_active_at": now_ms - 60_000,
                    "employee_id": "qa",
                    "employee_title": "QA Auditor",
                    "employee_color": "ocean",
                    "digest_done": "等待确认发布范围",
                },
                # 2) running 中即使带 need_decision 也不算 waiting（与 SessionItem.tsx 一致）
                {
                    "session_id": "ses-running-1",
                    "title": "运行中会话",
                    "status": "running",
                    "lifecycle_state": "running",
                    "need_decision": True,
                    "has_running_worker": False,
                    "callback_queued": False,
                    "local_ops": False,
                    "last_reply_at": now_ms - 10_000,
                    "created_at": now_ms - 20_000,
                },
                # 3) callback_queued 不算 waiting
                {
                    "session_id": "ses-cb-1",
                    "title": "待回传会话",
                    "status": "idle",
                    "lifecycle_state": "idle",
                    "need_decision": True,
                    "has_running_worker": False,
                    "callback_queued": True,
                    "local_ops": False,
                    "last_reply_at": now_ms - 10_000,
                    "created_at": now_ms - 20_000,
                },
                # 4) local_ops 后台会话不计入今日在线流
                {
                    "session_id": "ses-localops-1",
                    "title": "定时任务后台会话",
                    "status": "done",
                    "lifecycle_state": "completed",
                    "need_decision": True,
                    "local_ops": True,
                    "last_reply_at": now_ms - 10_000,
                    "created_at": now_ms - 20_000,
                },
                # 5) 超过 24 小时的隔日旧会话不计入今日在线流
                {
                    "session_id": "ses-old-1",
                    "title": "昨日旧会话",
                    "status": "idle",
                    "lifecycle_state": "idle",
                    "need_decision": True,
                    "local_ops": False,
                    "last_reply_at": now_ms - 36 * 3600 * 1000,
                    "created_at": now_ms - 40 * 3600 * 1000,
                },
            ]

        card_json = json.dumps(
            {
                "frago_ui_component": "decision-card",
                "component_type": "single-choice",
                "data": {
                    "type": "single-choice",
                    "question": "本次发布选择哪套灰度方案？",
                    "why": "方案 B 仅影响 5% 流量",
                    "options": [
                        {
                            "key": "A",
                            "label": "全量发布",
                            "effect": "直接切 100% 流量",
                            "reversible": False,
                            "recommended": False,
                        },
                        {
                            "key": "B",
                            "label": "灰度 5%",
                            "effect": "先观测 2 小时",
                            "reversible": True,
                            "recommended": True,
                        },
                    ],
                },
            },
            ensure_ascii=False,
        )

        monkeypatch.setattr(decisions_route, "collect_workbench_session_rows", _fake_rows)
        monkeypatch.setattr(
            decisions_route,
            "_extract_session_card_sync",
            lambda sid: decisions_route.extract_decision_card_detail(card_json)
            if sid == "ses-wait-1"
            else None,
        )

        app = FastAPI()
        app.include_router(decisions_route.router, prefix="/api")
        client = TestClient(app, client=("127.0.0.1", 50000))

        resp = client.get("/api/workbench/decisions")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["counts"] == {
            "pending": 2,
            "schedule": 1,
            "session": 1,
            "snoozed": 0,
        }
        by_id = {item["proposal_id"]: item for item in payload["items"]}
        assert sch_item["proposal_id"] in by_id
        assert "session:ses-wait-1" in by_id
        ses_item = by_id["session:ses-wait-1"]
        assert ses_item["title"] == "本次发布选择哪套灰度方案？"
        assert ses_item["recommended"] == "B"
        assert ses_item["irreversible"] is True
        assert len(ses_item["options"]) == 2


class TestDecisionRoutesActions:
    def test_schedule_snooze_undo_resolve_reject_and_ws_broadcast(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events: list[dict[str, Any]] = []

        async def _fake_broadcast(counts=None, *, action="refresh", proposal_id=None):
            events.append({"action": action, "proposal_id": proposal_id, "counts": counts})

        monkeypatch.setattr(decisions_route, "broadcast_decision_inbox_update", _fake_broadcast)

        svc = get_decision_inbox_service()
        p1 = svc.propose(
            question="执行数据库清理？",
            action_type="binary",
            risk="high",
            irreversible=True,
            dedup_key="act:1",
        )
        p2 = svc.propose(
            question="合并知识簇？",
            action_type="single-choice",
            options=[
                {"key": "A", "label": "合并", "effect": "归并条目", "recommended": True},
                {"key": "B", "label": "暂缓", "effect": "维持现状"},
            ],
            dedup_key="act:2",
        )

        # 搁置 p1 -> 可撤销
        r_snz = client.post(f"/api/workbench/decisions/{p1['proposal_id']}/snooze", json={})
        assert r_snz.status_code == 200
        assert r_snz.json()["item"]["status"] == "snoozed"
        assert r_snz.json()["counts"] == {"pending": 1, "schedule": 1, "session": 0, "snoozed": 1}

        # 撤销 p1 搁置 -> 回到 pending
        r_undo = client.post(f"/api/workbench/decisions/{p1['proposal_id']}/undo", json={})
        assert r_undo.status_code == 200
        assert r_undo.json()["item"]["status"] == "pending"
        assert r_undo.json()["counts"] == {"pending": 2, "schedule": 2, "session": 0, "snoozed": 0}

        # 批复 p2 -> 终态，禁止伪撤销
        r_res = client.post(
            f"/api/workbench/decisions/{p2['proposal_id']}/resolve",
            json={"choice": "A", "note": "同意合并"},
        )
        assert r_res.status_code == 200
        assert r_res.json()["item"]["status"] == "resolved"
        assert client.post(f"/api/workbench/decisions/{p2['proposal_id']}/undo", json={}).status_code == 409

        # 驳回 p1 -> 终态，禁止伪撤销
        r_rej = client.post(
            f"/api/workbench/decisions/{p1['proposal_id']}/reject",
            json={"note": "危险操作先取消"},
        )
        assert r_rej.status_code == 200
        assert r_rej.json()["item"]["status"] == "rejected"
        assert client.post(f"/api/workbench/decisions/{p1['proposal_id']}/undo", json={}).status_code == 409

        assert [e["action"] for e in events] == ["snooze", "undo", "resolve", "reject"]

    def test_resolve_and_snooze_online_session_dispatches_send_to_session(
        self, inbox_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now_ms = int(time.time() * 1000)
        sent_calls: list[tuple[str, str, bool]] = []

        async def _fake_rows() -> list[dict[str, Any]]:
            return [
                {
                    "session_id": "ses-online-9",
                    "title": "在线发布确认",
                    "status": "idle",
                    "lifecycle_state": "idle",
                    "need_decision": True,
                    "has_running_worker": False,
                    "callback_queued": False,
                    "local_ops": False,
                    "last_reply_at": now_ms - 5_000,
                    "created_at": now_ms - 10_000,
                }
            ]

        async def _fake_send(sid: str, req: Any) -> dict[str, Any]:
            sent_calls.append((sid, req.text, req.wait))
            return {"status": "queued", "session_id": sid}

        monkeypatch.setattr(decisions_route, "collect_workbench_session_rows", _fake_rows)
        monkeypatch.setattr(
            decisions_route,
            "_extract_session_card_sync",
            lambda _sid: {
                "action_type": "single-choice",
                "question": "是否推送上线？",
                "why": "全部检查通过",
                "options": [
                    {"key": "A", "label": "立即推送", "effect": "触发上线", "recommended": True}
                ],
                "recommended": "A",
                "draft": None,
                "suggestions": [],
            },
        )
        monkeypatch.setattr(decisions_route, "send_to_session", _fake_send)

        app = FastAPI()
        app.include_router(decisions_route.router, prefix="/api")
        client = TestClient(app, client=("127.0.0.1", 50000))

        # 搁置在线会话后，pending 降为 0、snoozed 升为 1
        r_snz = client.post("/api/workbench/decisions/session:ses-online-9/snooze", json={})
        assert r_snz.status_code == 200
        assert r_snz.json()["counts"] == {"pending": 0, "schedule": 0, "session": 0, "snoozed": 1}

        # 直接批复在线会话，向原会话投递非阻塞消息
        r_res = client.post(
            "/api/workbench/decisions/session:ses-online-9/resolve",
            json={"choice": "A", "note": "稳妥推送"},
        )
        assert r_res.status_code == 200
        assert len(sent_calls) == 1
        assert sent_calls[0][0] == "ses-online-9"
        assert "A（立即推送）" in sent_calls[0][1]
        assert "稳妥推送" in sent_calls[0][1]
        assert sent_calls[0][2] is False

    def test_create_app_exposes_workbench_decisions_endpoint(
        self, inbox_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from frago.server.app import create_app

        async def _empty_rows() -> list[dict[str, Any]]:
            return []

        monkeypatch.setattr(decisions_route, "collect_workbench_session_rows", _empty_rows)
        client = TestClient(create_app(), client=("127.0.0.1", 50000))
        resp = client.get("/api/workbench/decisions")
        assert resp.status_code == 200
        assert "counts" in resp.json()

    def test_snoozed_online_session_shadow_is_superseded_across_turns(
        self, inbox_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """搁置在线会话 -> 用户直接回复脱离 waiting -> 再次提出新问题时旧影子自动 superseded，新提问正常显示为 pending。"""
        from frago.server.services import workbench_today

        monkeypatch.setattr(workbench_today, "list_picked", lambda: {})
        now_ms = int(time.time() * 1000)
        state: dict[str, Any] = {
            "need_decision": True,
            "last_reply_at": now_ms - 60_000,
            "question": "第 1 轮问题：是否生成月报？",
        }

        async def _fake_rows() -> list[dict[str, Any]]:
            return [
                {
                    "session_id": "ses-cycle-1",
                    "title": "循环对话会话",
                    "status": "idle",
                    "lifecycle_state": "idle",
                    "need_decision": state["need_decision"],
                    "has_running_worker": False,
                    "callback_queued": False,
                    "local_ops": False,
                    "origin": "interactive",
                    "last_reply_at": state["last_reply_at"],
                    "created_at": now_ms - 120_000,
                }
            ]

        monkeypatch.setattr(decisions_route, "collect_workbench_session_rows", _fake_rows)
        monkeypatch.setattr(
            decisions_route,
            "_extract_session_card_sync",
            lambda _sid: {
                "action_type": "text-answer",
                "question": state["question"],
                "why": "等待确认",
                "options": [],
                "recommended": None,
                "draft": None,
                "suggestions": [],
            },
        )

        app = FastAPI()
        app.include_router(decisions_route.router, prefix="/api")
        client = TestClient(app, client=("127.0.0.1", 50000))

        # 1. 搁置第 1 轮提问
        r_snz = client.post("/api/workbench/decisions/session:ses-cycle-1/snooze", json={})
        assert r_snz.status_code == 200
        assert r_snz.json()["counts"] == {"pending": 0, "schedule": 0, "session": 0, "snoozed": 1}

        svc = get_decision_inbox_service()
        shadow_1 = svc.store.find_active_by_dedup_key("session:ses-cycle-1")
        assert shadow_1 is not None
        shadow_1_id = shadow_1["proposal_id"]

        # 2. 用户直接在聊天框回复，会话脱离 waiting
        state["need_decision"] = False
        r_mid = client.get("/api/workbench/decisions")
        assert r_mid.status_code == 200
        assert r_mid.json()["counts"] == {"pending": 0, "schedule": 0, "session": 0, "snoozed": 0}
        assert svc.get(shadow_1_id)["status"] == "superseded"

        # 3. 同一会话再次进入 waiting 提出第 2 轮新问题
        state["need_decision"] = True
        state["last_reply_at"] = int(time.time() * 1000) - 5_000
        state["question"] = "第 2 轮问题：请确认最终发送名单？"
        r_next = client.get("/api/workbench/decisions")
        assert r_next.status_code == 200
        assert r_next.json()["counts"] == {"pending": 1, "schedule": 0, "session": 1, "snoozed": 0}
        assert r_next.json()["items"][0]["status"] == "pending"
        assert r_next.json()["items"][0]["title"] == "第 2 轮问题：请确认最终发送名单？"

        # 4. 再次搁置第 2 轮，但未轮询中间脱离态，直接由更新的 last_reply_at 触发第 3 轮淘汰
        r_snz2 = client.post("/api/workbench/decisions/session:ses-cycle-1/snooze", json={})
        assert r_snz2.status_code == 200
        shadow_2 = svc.store.find_active_by_dedup_key("session:ses-cycle-1")
        assert shadow_2 is not None
        assert shadow_2["proposal_id"] != shadow_1_id

        state["last_reply_at"] = int((float(shadow_2["updated_at"]) + 20.0) * 1000)
        state["question"] = "第 3 轮问题：是否追加抄送？"
        r_jump = client.get("/api/workbench/decisions")
        assert r_jump.status_code == 200
        assert r_jump.json()["counts"] == {"pending": 1, "schedule": 0, "session": 1, "snoozed": 0}
        assert r_jump.json()["items"][0]["status"] == "pending"
        assert r_jump.json()["items"][0]["title"] == "第 3 轮问题：是否追加抄送？"
        assert svc.get(shadow_2["proposal_id"])["status"] == "superseded"

    def test_today_window_excludes_schedule_origin_and_keeps_picked_group(
        self, inbox_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """与前端 withinToday / SessionRail 对齐：保留滚动 24h、保留 picked_today 家族组、排除 origin=schedule。"""
        from frago.server.services import workbench_today

        now_ms = int(time.time() * 1000)
        monkeypatch.setattr(workbench_today, "list_picked", lambda: {"ses-picked-parent": "2026-11-26"})

        async def _fake_rows() -> list[dict[str, Any]]:
            return [
                # 20 小时前（滚动 24h 内，应计入）
                {
                    "session_id": "ses-20h",
                    "title": "20小时前待拍板",
                    "status": "idle",
                    "lifecycle_state": "idle",
                    "need_decision": True,
                    "local_ops": False,
                    "origin": "interactive",
                    "last_reply_at": now_ms - 20 * 3600 * 1000,
                    "created_at": now_ms - 21 * 3600 * 1000,
                },
                # 30 小时前的旧子分支，因父会话在 picked_today 中而整组保留
                {
                    "session_id": "ses-picked-parent",
                    "title": "捡回的主会话",
                    "status": "done",
                    "lifecycle_state": "completed",
                    "need_decision": False,
                    "local_ops": False,
                    "origin": "interactive",
                    "last_reply_at": now_ms - 30 * 3600 * 1000,
                    "created_at": now_ms - 31 * 3600 * 1000,
                },
                {
                    "session_id": "ses-picked-child",
                    "title": "捡回主会话的子分支",
                    "parent_session_id": "ses-picked-parent",
                    "status": "idle",
                    "lifecycle_state": "idle",
                    "need_decision": True,
                    "local_ops": False,
                    "origin": "interactive",
                    "last_reply_at": now_ms - 30 * 3600 * 1000,
                    "created_at": now_ms - 31 * 3600 * 1000,
                },
                # origin=schedule（即使 local_ops=False 也不计入在线会话）
                {
                    "session_id": "ses-cron-origin",
                    "title": "定时任务会话",
                    "status": "idle",
                    "lifecycle_state": "idle",
                    "need_decision": True,
                    "local_ops": False,
                    "origin": "schedule",
                    "last_reply_at": now_ms - 10_000,
                    "created_at": now_ms - 20_000,
                },
                # 30 小时前且未被捡回（应排除）
                {
                    "session_id": "ses-old-unpicked",
                    "title": "旧未捡回会话",
                    "status": "idle",
                    "lifecycle_state": "idle",
                    "need_decision": True,
                    "local_ops": False,
                    "origin": "interactive",
                    "last_reply_at": now_ms - 30 * 3600 * 1000,
                    "created_at": now_ms - 31 * 3600 * 1000,
                },
            ]

        monkeypatch.setattr(decisions_route, "collect_workbench_session_rows", _fake_rows)
        monkeypatch.setattr(decisions_route, "_extract_session_card_sync", lambda _sid: None)

        app = FastAPI()
        app.include_router(decisions_route.router, prefix="/api")
        client = TestClient(app, client=("127.0.0.1", 50000))

        resp = client.get("/api/workbench/decisions")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["counts"] == {"pending": 2, "schedule": 0, "session": 2, "snoozed": 0}
        ids = {item["proposal_id"] for item in payload["items"]}
        assert ids == {"session:ses-20h", "session:ses-picked-child"}
