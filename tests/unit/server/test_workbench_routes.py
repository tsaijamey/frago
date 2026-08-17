"""会话工作台的三个只读接口（spec 20260729-session-workbench-webui Phase 2）。

这些用例盯的是接口这一层自己的承诺，不复验翻译层：两家的会话在同一份清单里、
一次拉不走整场、报错类的原文一律拿不到。翻译层怎么归类由 ``tests/unit/session/``
那三份用例把关，这里全部走打桩的翻译层，不碰真实档案。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from frago.session import adapters, record_reader
from frago.session.record_reader import MAX_LIMIT, SessionCard
from frago.session.unified_record import UnifiedRecord

# 两家的会话编号形状——``detect_family()`` 只认这两种形状，用例照真实形状写。
CC_SID = "00a02979-7eb4-5c70-94ae-867c8281e3f6"
OC_SID = "ses_058288655ffeYMxYC1AZKCcv56"


def _card(sid: str, family: str, last_active: int) -> SessionCard:
    return SessionCard(
        session_id=sid,
        family=family,  # type: ignore[arg-type]
        title=f"{family} 的一场会话",
        directory="/tmp/somewhere",
        created_at=last_active - 1000,
        last_active_at=last_active,
    )


class _FakeAdapter:
    """一家翻译层的替身。记下自己被要了多少条，好验证上限确实卡在核心数据层。"""

    def __init__(self, total: int = 10_000, raw: dict | None = None) -> None:
        self.total = total
        self.raw = raw
        self.asked_limit: int | None = None
        self.asked_after: int | None = None

    def to_unified(
        self, session_id: str, after: int, limit: int, tail: bool = False
    ) -> list[UnifiedRecord]:
        self.asked_after = after
        self.asked_limit = limit
        if tail:
            start, end = max(self.total - limit, 0), self.total
        else:
            start, end = after, min(after + limit, self.total)
        return [
            UnifiedRecord(
                id=f"rec-{seq}",
                session_id=session_id,
                group_id=None,
                seq=seq,
                ts=1_700_000_000_000 + seq,
                kind="user.say",
                payload={"text": f"第 {seq} 条"},
            )
            for seq in range(start, end)
        ]

    def read_raw(self, session_id: str, record_id: str) -> dict | None:
        # 报错类在翻译层就已经返回空，这里照搬那个行为：编号带 error 标记的一律不给。
        if "error" in record_id:
            return None
        return self.raw


@pytest.fixture
def client():
    from frago.server.app import create_app

    # Loopback seat: the workbench is the owner's own UI. Non-local callers hit
    # the access-zone middleware first (see test_security.py).
    return TestClient(create_app(), client=("127.0.0.1", 50000))


@pytest.fixture
def adapter(monkeypatch):
    """两家都换成同一个替身，接口测试不碰真实档案。"""
    fake = _FakeAdapter(raw={"uuid": "rec-3", "type": "user", "message": "原文在此"})
    monkeypatch.setattr(adapters, "get_adapter", lambda _family: fake)
    return fake


class TestSessionList:
    def test_two_families_share_one_list(self, client, monkeypatch):
        """左栏一份清单要同时装下两家，只列一家等于另一家的会话不存在。"""
        monkeypatch.setattr(
            record_reader,
            "list_sessions",
            lambda: [_card(OC_SID, "opencode", 3000), _card(CC_SID, "claude-code", 2000)],
        )
        body = client.get("/api/workbench/sessions").json()
        assert [row["family"] for row in body] == ["opencode", "claude-code"]

    def test_every_row_carries_the_family(self, client, monkeypatch):
        """界面要按家族分样式，缺了这个字段就只能靠编号形状去猜。"""
        monkeypatch.setattr(
            record_reader, "list_sessions", lambda: [_card(CC_SID, "claude-code", 2000)]
        )
        row = client.get("/api/workbench/sessions").json()[0]
        assert set(row) == {
            "session_id",
            "family",
            "title",
            "directory",
            "created_at",
            "last_active_at",
            "last_reply_at",
            "agent_paths",
            "status",
            "digest_done",
            "digest_stuck",
        }

    def test_每行都带状态与摘要(self, client, monkeypatch):
        """左栏最值钱的是"一眼看出每场什么情况"。这三样不出接口，左栏就只能按来源分组。"""
        card = _card(CC_SID, "claude-code", 2000)
        card.status = "error"
        card.digest_done = "把镜头判断追加进了 verdict.jsonl"
        card.digest_stuck = "API Error: Connection closed mid-response."
        monkeypatch.setattr(record_reader, "list_sessions", lambda: [card])

        row = client.get("/api/workbench/sessions").json()[0]

        assert row["status"] == "error"
        assert row["digest_done"] == "把镜头判断追加进了 verdict.jsonl"
        assert row["digest_stuck"] == "API Error: Connection closed mid-response."

    def test_没有摘要时是空值而不是编一句(self, client, monkeypatch):
        """取不到就该露出取不到。塞一句占位的话，人会当成真的发生过。"""
        monkeypatch.setattr(
            record_reader, "list_sessions", lambda: [_card(CC_SID, "claude-code", 2000)]
        )
        row = client.get("/api/workbench/sessions").json()[0]
        assert row["digest_done"] is None
        assert row["digest_stuck"] is None

    def test_order_comes_from_the_data_layer_untouched(self, client, monkeypatch):
        """排序在核心数据层做完了，接口不许再排一次——两处各排一遍迟早各排各的。"""
        given = [_card("ses_a", "opencode", 9), _card("ses_b", "opencode", 5)]
        monkeypatch.setattr(record_reader, "list_sessions", lambda: given)
        body = client.get("/api/workbench/sessions").json()
        assert [row["session_id"] for row in body] == ["ses_a", "ses_b"]

    def test_empty_install_is_an_empty_list_not_an_error(self, client, monkeypatch):
        monkeypatch.setattr(record_reader, "list_sessions", list)
        response = client.get("/api/workbench/sessions")
        assert response.status_code == 200
        assert response.json() == []


class TestRecords:
    def test_first_page_starts_at_zero(self, client, adapter):
        body = client.get(f"/api/workbench/sessions/{CC_SID}/records?after=0&limit=5").json()
        assert [row["seq"] for row in body] == [0, 1, 2, 3, 4]

    def test_cursor_is_the_first_seq_of_this_batch(self, client, adapter):
        """``after`` 是闭区间起点。做成排他游标的话默认值 0 会把开口第一句吃掉。"""
        body = client.get(f"/api/workbench/sessions/{CC_SID}/records?after=7&limit=3").json()
        assert [row["seq"] for row in body] == [7, 8, 9]

    def test_a_record_arrives_whole(self, client, adapter):
        row = client.get(f"/api/workbench/sessions/{CC_SID}/records?limit=1").json()[0]
        assert set(row) == {
            "id",
            "session_id",
            "group_id",
            "seq",
            "ts",
            "kind",
            "agent_path",
            "payload",
            "raw_available",
        }

    def test_default_page_is_two_hundred(self, client, adapter):
        body = client.get(f"/api/workbench/sessions/{CC_SID}/records").json()
        assert len(body) == 200

    def test_asking_for_the_whole_session_still_gets_one_page(self, client, adapter):
        """单条工具结果见过 7.2 万字符。一次拉整场会把浏览器打死，上限硬卡。"""
        body = client.get(f"/api/workbench/sessions/{CC_SID}/records?limit=99999").json()
        assert len(body) == MAX_LIMIT
        assert adapter.asked_limit == MAX_LIMIT

    def test_the_cap_is_not_an_error(self, client, adapter):
        """越界截断，不是 422——界面传大了不该让这一屏内容整个被扣下。"""
        assert client.get(f"/api/workbench/sessions/{CC_SID}/records?limit=99999").status_code == 200

    def test_opencode_session_reads_the_same_way(self, client, adapter):
        body = client.get(f"/api/workbench/sessions/{OC_SID}/records?limit=2").json()
        assert [row["session_id"] for row in body] == [OC_SID, OC_SID]

    def test_unknown_id_shape_is_not_found(self, client, adapter):
        """两家的形状都不像时回 404，NEVER 猜一家试试翻出个空的当「没记录」。"""
        assert client.get("/api/workbench/sessions/不像任何一家/records").status_code == 404

    def test_tail_returns_the_last_page(self, client, adapter):
        """中栏打开会话要直接落在最新内容上，而不是从头一页页翻到尾。"""
        body = client.get(f"/api/workbench/sessions/{CC_SID}/records?tail=true&limit=5").json()
        assert [row["seq"] for row in body] == [9995, 9996, 9997, 9998, 9999]

    def test_tail_ignores_the_cursor(self, client, adapter):
        """tail 模式下 after 没有意义，给了也当被给。"""
        body = client.get(f"/api/workbench/sessions/{CC_SID}/records?tail=true&after=7&limit=3").json()
        assert [row["seq"] for row in body] == [9997, 9998, 9999]

    def test_tail_still_caps_the_page(self, client, adapter):
        """尾部读取同样受上限硬卡，分页纪律对两个方向一视同仁。"""
        body = client.get(f"/api/workbench/sessions/{CC_SID}/records?tail=true&limit=99999").json()
        assert len(body) == MAX_LIMIT
        assert adapter.asked_limit == MAX_LIMIT


class TestRawIsWithheld:
    """报错类取原文必须在服务端拦。那条原文的响应头里带着登录凭据。"""

    def test_error_record_is_forbidden(self, client, adapter):
        response = client.get(
            f"/api/workbench/records/rec-9:error/raw?session_id={CC_SID}"
        )
        assert response.status_code == 403

    def test_error_record_leaks_nothing_in_the_body(self, client, adapter):
        body = client.get(f"/api/workbench/records/rec-9:error/raw?session_id={CC_SID}").text
        assert "原文在此" not in body

    def test_ordinary_record_comes_through(self, client, adapter):
        response = client.get(f"/api/workbench/records/rec-3/raw?session_id={CC_SID}")
        assert response.status_code == 200
        assert response.json()["message"] == "原文在此"

    def test_missing_record_is_withheld_too(self, client, monkeypatch):
        """只有真拿到原文才放行，其余一律不放行。"""
        fake = _FakeAdapter(raw=None)
        monkeypatch.setattr(adapters, "get_adapter", lambda _family: fake)
        assert (
            client.get(f"/api/workbench/records/rec-3/raw?session_id={CC_SID}").status_code == 403
        )

    def test_which_session_must_be_stated(self, client, adapter):
        """记录编号自己定位不到档案：Claude Code 要先找到会话文件，opencode 要先定位会话行。"""
        assert client.get("/api/workbench/records/rec-3/raw").status_code == 422

    def test_unknown_session_shape_is_not_found(self, client, adapter):
        response = client.get("/api/workbench/records/rec-3/raw?session_id=不像任何一家")
        assert response.status_code == 404


class TestContentSearch:
    """内容检索这一层只做取用与序列化，怎么搜由 ``record_search`` 那份用例把关。"""

    def _stub(self, monkeypatch, outcome):
        from frago.session import record_search

        monkeypatch.setattr(record_search, "search_sessions", lambda *_a, **_k: outcome)

    def test_命中的会话与摘要原样交出来(self, client, monkeypatch):
        from frago.session.record_search import ContentHit, SearchOutcome, SessionMatch

        self._stub(
            monkeypatch,
            SearchOutcome(
                query="飞书",
                matches=[
                    SessionMatch(
                        session_id=CC_SID,
                        family="claude-code",
                        hit_count=3,
                        hits=[
                            ContentHit(
                                record_id="rec-1",
                                kind="user.say",
                                ts=1_700_000_000_000,
                                snippet="…把飞书那条推送修一下…",
                            )
                        ],
                    )
                ],
                scanned_files=7,
            ),
        )
        body = client.get("/api/workbench/search?q=飞书").json()
        assert body["terms"] == ["飞书"]
        assert body["scanned_files"] == 7
        (row,) = body["sessions"]
        assert row["session_id"] == CC_SID
        assert row["hit_count"] == 3
        assert row["hits"][0]["snippet"] == "…把飞书那条推送修一下…"

    def test_没做全的地方必须报出来(self, client, monkeypatch):
        """做不全却不说，等于谎报覆盖面。"""
        from frago.session.record_search import SearchOutcome

        self._stub(monkeypatch, SearchOutcome(query="x", warnings=["ripgrep 不在 PATH 上"]))
        assert client.get("/api/workbench/search?q=x").json()["warnings"] == [
            "ripgrep 不在 PATH 上"
        ]

    def test_不给要搜什么就不受理(self, client):
        assert client.get("/api/workbench/search").status_code == 422


class TestExistingRoutesUntouched:
    def test_claude_sessions_prefix_still_answers(self, client):
        """``/api/claude-sessions`` 背后有正在跑的 React 页面，新接口不许挡它的路。"""
        assert client.get("/api/claude-sessions?days=1").status_code == 200
