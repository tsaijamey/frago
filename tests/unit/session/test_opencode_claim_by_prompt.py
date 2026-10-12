"""认领的两道防线各自的用例：按首条用户消息的正文认人、整段认领落盘互斥。

按题分两组：

- 「认人」组盯 ``prompt_tail`` 那道判据。上一轮的故障时序（自己的会话行落库晚、
  认领时库里只看得见别人的行）必须各认各的，不许互换。
- 「不撞号」组盯互斥。两场同时认领都在任一次写绑定之前开始时，最终 MUST NOT 写成
  同一个编号。

**反向验**：本文件自带两个开关，把两道防线各自拆掉之后上面两组 MUST 报红。开关只在
测试里打桩，默认关着，跑法见文件末尾的 ``_reverse_checks``。

库与绑定文件全部落在 ``tmp_path``，NEVER 触碰本机真实的会话库与
``~/.frago/opencode-sessions.json``。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

from frago.session import opencode_store

_SCHEMA = """
CREATE TABLE session_v2 (
    id text PRIMARY KEY,
    directory text NOT NULL,
    title text NOT NULL DEFAULT '',
    time_created integer NOT NULL,
    time_updated integer NOT NULL
);
CREATE TABLE session_message (
    id text PRIMARY KEY,
    session_id text NOT NULL,
    type text NOT NULL,
    seq integer NOT NULL,
    time_created integer NOT NULL,
    time_updated integer NOT NULL,
    data text NOT NULL
);
CREATE TABLE session (
    id text PRIMARY KEY,
    directory text NOT NULL,
    title text NOT NULL DEFAULT '',
    time_created integer NOT NULL
);
CREATE TABLE message (
    id text PRIMARY KEY,
    session_id text NOT NULL,
    time_created integer NOT NULL,
    data text NOT NULL
);
CREATE TABLE part (
    id text PRIMARY KEY,
    message_id text NOT NULL,
    session_id text NOT NULL,
    time_created integer NOT NULL,
    data text NOT NULL
);
"""

# 两条提示词：A 的长（落库晚）、B 的短，尾段在去空白之后仍然各是一个整体。
_PROMPT_A = (
    "# 任务：把这条会话认回来\n\n## 背景\n\n"
    "长提示词的会话行落库要几十秒，认领必须在自己的行还没出现时忍住不认别人。\n\n"
    "甲案：这一段尾段属于 A"
)
_PROMPT_B = "短提示词的 B 会话，尾段：这一段尾段属于 B"


def _tail(prompt: str) -> str:
    """与驱动里 ``_tail_marker`` 同一套取法：去掉全部空白之后的末尾 32 字。"""
    return "".join(prompt.split())[-32:]


def _seed(db: Path, sid: str, directory: str, created: int, prompt: str) -> None:
    """一场会话：会话行 + 首条用户消息（正文就是这次提交的提示词）。"""
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO session_v2 (id, directory, title, time_created, time_updated) "
            "VALUES (?, ?, '', ?, ?)",
            (sid, directory, created, created),
        )
        conn.execute(
            "INSERT INTO session_message "
            "(id, session_id, type, seq, time_created, time_updated, data) "
            "VALUES (?, ?, 'user', 1, ?, ?, ?)",
            (
                f"m_{sid}",
                sid,
                created + 1,
                created + 1,
                json.dumps({"time": {"created": created + 1}, "text": prompt}),
            ),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "opencode.db"
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(path))
    monkeypatch.setattr(
        opencode_store, "BINDINGS_PATH", tmp_path / "opencode-sessions.json"
    )
    return path


# ── 认人：首条用户消息的正文才是判据 ────────────────────────────────
def test_each_session_claims_its_own_row_when_the_other_landed_first(db: Path) -> None:
    """上一轮那条故障时序：A 的提示词长、自己那行落库晚；B 的短、先落库。

    两边各认一次，MUST 各认各的。按"同目录 + 窗口 + 最早创建"挑会互换：A 认领那一刻
    库里只看得见 B 那一行，挑中的必然是 B；B 随后认到自己那行已被认走，退取次早又
    拿到 A 的。两条绑定互换，页面上两场对话互串。
    """
    _seed(db, "ses_B", "/w", 2000, _PROMPT_B)

    # A 第一拍去认：自己的行还没落库（33000 才出现）。此刻 MUST 认不到。
    first = opencode_store.claim_and_bind("frago-A", "/w", 1000, _tail(_PROMPT_A))
    # A 自己的行随后落库。
    _seed(db, "ses_A", "/w", 33000, _PROMPT_A)

    a = opencode_store.claim_and_bind("frago-A", "/w", 1000, _tail(_PROMPT_A))
    b = opencode_store.claim_and_bind("frago-B", "/w", 1500, _tail(_PROMPT_B))

    assert (first, a, b) == (None, "ses_A", "ses_B")
    assert opencode_store.get_binding("frago-A") == "ses_A"
    assert opencode_store.get_binding("frago-B") == "ses_B"


def test_claim_refuses_a_row_whose_first_message_is_not_ours(db: Path) -> None:
    """首条用户消息里没有我们的尾段（提示词被改写 / 首条消息不是我们的）：返回 None。

    认不到只是让完成探针退回读屏那条既有的降级路，本轮照常跑完；认错人是两场对话的
    记录接到一起，代价大得多。
    """
    _seed(db, "ses_theirs", "/w", 2000, _PROMPT_B)
    assert opencode_store.claim_session("/w", 1000, _tail(_PROMPT_A)) is None
    assert opencode_store.claim_and_bind("frago-A", "/w", 1000, _tail(_PROMPT_A)) is None
    assert opencode_store.get_binding("frago-A") is None


def test_claim_refuses_when_the_prompt_is_blank(db: Path) -> None:
    """提示词为空 / 只有空白：没有判别信息就不认，也 NEVER 因此写一条绑定。"""
    _seed(db, "ses_A", "/w", 2000, _PROMPT_A)
    assert opencode_store.claim_and_bind("frago-A", "/w", 1000, "") is None
    assert opencode_store.claim_and_bind("frago-A", "/w", 1000, " \n\t ") is None
    assert opencode_store.get_binding("frago-A") is None


def test_identical_prompts_still_resolve_deterministically(db: Path) -> None:
    """同目录两场提交了**完全相同**的提示词：判据分不出谁是谁，结果仍 MUST 确定。

    次序由"创建时刻、再编号"定：先认的那一场拿创建最早的那条，后认的那一场退取剩下
    的那条。两场都认得到、且不撞号——同一个库状态加同一个认领次序，结果永远一样。
    """
    _seed(db, "ses_A", "/w", 1300, _PROMPT_A)
    _seed(db, "ses_B", "/w", 1800, _PROMPT_A)

    first = opencode_store.claim_and_bind("webui-1", "/w", 1000, _tail(_PROMPT_A))
    second = opencode_store.claim_and_bind("webui-2", "/w", 1000, _tail(_PROMPT_A))

    assert (first, second) == ("ses_A", "ses_B")
    assert opencode_store.bound_session_ids() == {"ses_A", "ses_B"}


# ── 不撞号：认领 + 落盘是一个动作 ──────────────────────────────────
def test_two_simultaneous_claims_never_land_on_the_same_row(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两场同时认领，两次都发生在任一次写绑定之前：MUST NOT 写成同一个编号。

    "同时"用三种方式造出来：两个线程在栅栏上对齐同时起跑、读绑定那一步被放慢，两场
    因此都落在"还没有人认过"那个窗口上。两次读绑定的区间不重叠是这条用例的硬证据：
    不重叠才说明"读绑定 → 挑号 → 写绑定"真的串成了一个动作。

    这条盯的是**互斥**这一道防线，故只断言"两场都认到了、且不是同一场"。同一场会话
    到底该归谁由判据那条防线负责，那条在
    ``test_each_session_claims_its_own_row_when_the_other_landed_first`` 里确定地验
    （这里谁先抢到锁本来就不确定，拿它断言"各认各的"会变成掷硬币）。
    """
    _seed(db, "ses_A", "/w", 1300, _PROMPT_A)
    _seed(db, "ses_B", "/w", 1800, _PROMPT_B)

    spans: list[tuple[float, float]] = []
    real_load = opencode_store._load_bindings
    # 只记录**认领期间**那两次读绑定：断言里读映射是测试自己的动作，不在这条证据里。
    claiming = threading.Event()
    claiming.set()

    def slow_load() -> dict[str, dict[str, Any]]:
        if not claiming.is_set():
            return real_load()
        start = time.monotonic()
        try:
            time.sleep(0.15)
            return real_load()
        finally:
            spans.append((start, time.monotonic()))

    monkeypatch.setattr(opencode_store, "_load_bindings", slow_load)

    barrier = threading.Barrier(2)

    def claim(frago_id: str, prompt: str) -> None:
        barrier.wait()
        opencode_store.claim_and_bind(frago_id, "/w", 0, _tail(prompt))

    threads = [
        threading.Thread(target=claim, args=("frago-A", _PROMPT_A)),
        threading.Thread(target=claim, args=("frago-B", _PROMPT_B)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30.0)
    claiming.clear()
    assert not [thread for thread in threads if thread.is_alive()], "认领卡住了"

    # 用户能看见的那一面：两场都认到了自己那一场，且两条绑定没有指着同一场会话。
    bound = opencode_store.bound_session_ids()
    assert opencode_store.get_binding("frago-A") is not None
    assert opencode_store.get_binding("frago-B") is not None
    assert bound == {"ses_A", "ses_B"}, f"两条绑定撞到同一场会话：{bound}"
    # 机制那一面：两次"读绑定 → 写绑定"没有一点重叠。
    assert len(spans) == 2
    ordered = sorted(spans)
    assert ordered[0][1] <= ordered[1][0], f"两次认领的临界区重叠了：{ordered}"


# ── 边界：库表缺失 / 锁取不到 ──────────────────────────────────────
def test_claim_returns_none_when_the_text_tables_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """老库 / 半残库（没有 message、part、session_message）：返回 None，NEVER 抛。

    读不到"首条用户消息的正文"就没有认人的依据，此时 MUST 认不到——退回读屏，而不是
    退回"按创建时刻猜"。
    """
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE session (id text PRIMARY KEY, directory text NOT NULL,"
        " title text NOT NULL DEFAULT '', time_created integer NOT NULL);"
        "INSERT INTO session VALUES ('ses_a', '/w', '', 300);"
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(path))
    monkeypatch.setattr(
        opencode_store, "BINDINGS_PATH", tmp_path / "opencode-sessions.json"
    )
    assert opencode_store.claim_session("/w", 0, "尾段") is None


def test_claim_gives_up_when_the_lock_cannot_be_taken(
    db: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """锁文件取不到（目录不存在 / 不可写）：这一场不认，且 NEVER 把异常逸出去。

    取舍是"不认"而不是"照旧不互斥地认"：没有互斥的认领正是两场撞号的成因，拿不到锁
    的这一次宁可退回读屏。日志留一条 warning——不静默跳过互斥。
    """
    if os.environ.get(_BINDINGS_LOCK_OFF):
        # 反向验把互斥整段拆掉了，这条路径根本走不到——与它要验的东西无关，跳过。
        pytest.skip("反向验拆掉了互斥，这条用例的路径不可达")
    _seed(db, "ses_A", "/w", 1300, _PROMPT_A)
    # ``/dev/null`` 底下建不了文件，且不依赖当前用户的权限——换台机器一样成立。
    monkeypatch.setattr(
        opencode_store, "_lock_path", lambda: Path("/dev/null/opencode-sessions.json.lock")
    )

    with caplog.at_level(logging.WARNING, logger="frago.session.opencode_store"):
        claimed = opencode_store.claim_and_bind("frago-A", "/w", 1000, _tail(_PROMPT_A))

    assert claimed is None
    # 认不到就没有绑定，也 NEVER 留下半截映射文件。
    assert not opencode_store.BINDINGS_PATH.exists()
    assert any("lock unavailable" in record.message for record in caplog.records)


# ── 反向验开关 ──────────────────────────────────────────────────────
_PROMPT_CRITERION_OFF = "FRAGO_TEST_DISABLE_PROMPT_CRITERION"
_BINDINGS_LOCK_OFF = "FRAGO_TEST_DISABLE_BINDINGS_LOCK"


def _pick_without_the_prompt_criterion(
    conn: sqlite3.Connection,
    directory: str,
    since_ms: int,
    tail: str,
    taken: set[str],
) -> str | None:
    """老判据：同目录 + 窗口 + 未被认走，取创建最早的那条——**不看正文**。"""
    names = opencode_store._table_names(conn) or frozenset()
    for _created, sid in opencode_store._claim_candidate_rows(
        conn, directory, since_ms, names
    ):
        if sid not in taken:
            return sid
    return None


@contextmanager
def _no_lock() -> Iterator[bool]:
    """把互斥拆掉：读绑定与写绑定之间重新露出那个"两边都还没认过"的窗口。"""
    yield True


@pytest.fixture(autouse=True)
def _reverse_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """反向验的两个开关，默认都是关的；打开时本文件的用例 MUST 报红。

    它证明的是"用例盯住了这两道防线"，而不是"代码看起来对"：

    - ``FRAGO_TEST_DISABLE_PROMPT_CRITERION=1``：提示词判据换回按创建时刻挑，
      ``test_each_session_claims_its_own_row_when_the_other_landed_first`` 报红（互换）。
    - ``FRAGO_TEST_DISABLE_BINDINGS_LOCK=1``：互斥拆掉，
      ``test_two_simultaneous_claims_never_land_on_the_same_row`` 报红（撞号）。

    两道防线各自独立成立，故两个开关要分开跑：只拆判据时那条"同时认领"的用例仍会
    通过（互斥自己就挡得住撞号），只拆互斥时那条"交错"的用例也仍会通过（判据自己就
    认得准）。互相顶不上对方那一条，正是要分别验的理由。
    """
    if os.environ.get(_PROMPT_CRITERION_OFF):
        monkeypatch.setattr(opencode_store, "_pick_claim", _pick_without_the_prompt_criterion)
    if os.environ.get(_BINDINGS_LOCK_OFF):
        monkeypatch.setattr(opencode_store, "_bindings_locked", _no_lock)
