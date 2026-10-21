"""左栏清单排序的回归：按创建时刻，不因后续更新而移动。

排序键在核心数据层定（见 ``record_reader.sort_key``），界面只照服务端给的次序摆。
这里把五家的取数换成替身，只核一件事：回复时刻再新，也压不过创建时刻。
"""

from frago.session import record_reader
from frago.session.record_reader import SessionCard, sort_key


def _card(
    session_id: str,
    created_at: int,
    *,
    last_active_at: int | None = None,
    last_reply_at: int | None = None,
) -> SessionCard:
    return SessionCard(
        session_id=session_id,
        family="claude-code",
        title=session_id,
        directory="/tmp",
        created_at=created_at,
        last_active_at=created_at if last_active_at is None else last_active_at,
        last_reply_at=last_reply_at,
    )


def _wire(monkeypatch, cards: list[SessionCard]) -> None:
    """五家的取数换成一份给定卡片，避免真去翻盘上的会话。"""
    monkeypatch.setattr(record_reader.session_origin, "load_origin_index", lambda: {})
    monkeypatch.setattr(record_reader, "_claude_cards", lambda _origins: list(cards))
    monkeypatch.setattr(record_reader, "_opencode_cards", lambda _origins: [])
    monkeypatch.setattr(record_reader, "_codex_cards", lambda _origins: [])
    monkeypatch.setattr(record_reader, "_coreagent_cards", lambda _origins: [])
    monkeypatch.setattr(record_reader, "_agy_cards", lambda _origins: [])


def test_sort_key_is_creation_time() -> None:
    card = _card("x", 1_000, last_active_at=9_000, last_reply_at=9_000)

    assert sort_key(card) == 1_000


def test_list_sessions_orders_by_creation_not_last_reply(monkeypatch) -> None:
    older = _card("older", 1_000, last_active_at=9_000, last_reply_at=9_000)
    newer = _card("newer", 2_000, last_active_at=3_000, last_reply_at=3_000)
    _wire(monkeypatch, [older, newer])

    assert [card.session_id for card in record_reader.list_sessions()] == ["newer", "older"]


def test_updating_a_session_does_not_move_it(monkeypatch) -> None:
    older = _card("older", 1_000, last_active_at=2_000, last_reply_at=2_000)
    newer = _card("newer", 3_000, last_active_at=3_500, last_reply_at=3_500)
    _wire(monkeypatch, [older, newer])

    before = [card.session_id for card in record_reader.list_sessions()]
    older.last_active_at = 99_000
    older.last_reply_at = 99_000
    after = [card.session_id for card in record_reader.list_sessions()]

    assert before == after == ["newer", "older"]
