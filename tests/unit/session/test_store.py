"""`SessionOntologyStore` 的锁、合并与防冲回行为。

这个文件单独立起来，是因为 `store.py` 从前没有自己的单测：它的锁行为、`close_branch`
与 `_keep_closed_branch` 这几条分支被塞在 `tests/unit/ontology/test_ontology_kernel.py`
里，跟本体内核的测试混在一起。混着的后果是**这两类断言的理由不一样却共用一套夹具**——
内核测的是公理与契约，存储测的是「两边账本合起来之后事实还在不在」。

这里只碰 ``tmp_path`` 下的文件，绝不碰真人会话目录。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from frago.session.store import (
    SessionOntologyRecord,
    SessionOntologyStore,
)


@pytest.fixture
def store(tmp_path: Path) -> SessionOntologyStore:
    """一份隔离的存储：本体存储与老账本都落在 tmp_path 下。"""
    return SessionOntologyStore(
        tmp_path / "session-ontology-store.json",
        legacy_ledger_path=tmp_path / "agent-launches.json",
    )


def _legacy_branch_entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "child": "branch-1",
        "parent": "parent-1",
        "kind": "branch",
        "agent_type": "claude",
        "cwd": "/repo",
        "prompt_head": "分出来改一处",
        "at": 1794548000,
        "anchor": {"file": "b.py", "line": 12},
        "note": "分出来改一处",
        "closed_at": 1794548500,
        "closed_by": "human",
    }
    entry.update(overrides)
    return entry


class TestClosedBranchMerge:
    """两边账本合起来时，收口过的事实不许被冲掉。"""

    def test_keep_closed_branch_preserves_anchor_and_note(self, tmp_path: Path) -> None:
        """老账本那份已收口，本体存储这份还开着：合出来的必须同时有收口与锚点。

        只补 ``closed_at`` / ``closed_by`` 的话，合出来的那条分支有收口时刻却没有锚点——
        页面画这条分支时锚点为空，虚线画不出来，看起来像这条分支从来没存在过。
        """
        legacy_file = tmp_path / "agent-launches.json"
        store_file = tmp_path / "session-ontology-store.json"

        # 老账本：已收口的分支，带锚点与备注（这是老账本的原生格式，几项都在顶层）。
        legacy_file.write_text(
            json.dumps([_legacy_branch_entry()], ensure_ascii=False),
            encoding="utf-8",
        )
        # 本体存储：同一条分支，还开着，且 extra 里**没有** anchor / note。
        store_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "sessions": {
                        "branch-1": {
                            "session_id": "branch-1",
                            "agent_kernel": "claude",
                            "origin": "terminal",
                            "lifecycle_state": "running",
                            "is_worker": False,
                            "parent_session_id": "parent-1",
                            "relation_kind": "branch",
                            "created_at": 1794548000,
                            "updated_at": 1794548000,
                            "extra": {},
                        }
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        store = SessionOntologyStore(store_file, legacy_ledger_path=legacy_file)
        rec = store.get("branch-1")
        assert rec is not None
        # 收口状态保留（这条原有行为）。
        assert rec.extra.get("closed_at") == 1794548500
        assert rec.extra.get("closed_by") == "human"
        # 锚点与备注一并保留——没有它页面画不出这条分支。
        assert rec.extra.get("anchor") == {"file": "b.py", "line": 12}
        assert rec.extra.get("note") == "分出来改一处"

    def test_existing_anchor_is_never_overwritten(self, tmp_path: Path) -> None:
        """本体存储那份自己带着锚点时，以它为准，绝不被老账本那份盖掉。"""
        legacy_file = tmp_path / "agent-launches.json"
        store_file = tmp_path / "session-ontology-store.json"
        legacy_file.write_text(
            json.dumps([_legacy_branch_entry()], ensure_ascii=False),
            encoding="utf-8",
        )
        store_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "sessions": {
                        "branch-1": {
                            "session_id": "branch-1",
                            "agent_kernel": "claude",
                            "origin": "terminal",
                            "lifecycle_state": "running",
                            "is_worker": False,
                            "parent_session_id": "parent-1",
                            "relation_kind": "branch",
                            "created_at": 1794548000,
                            "updated_at": 1794548000,
                            "extra": {"anchor": {"file": "own.py"}, "note": "我自己的备注"},
                        }
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        store = SessionOntologyStore(store_file, legacy_ledger_path=legacy_file)
        rec = store.get("branch-1")
        assert rec is not None
        assert rec.extra.get("anchor") == {"file": "own.py"}
        assert rec.extra.get("note") == "我自己的备注"

    def test_closed_branch_is_not_reverted_by_later_writes(self, store: SessionOntologyStore) -> None:
        """收口之后别的会话落盘，收口信息必须还在，且回写到老账本。"""
        store.save(
            SessionOntologyRecord(
                session_id="branch-1",
                agent_kernel="claude",
                origin="terminal",
                relation_kind="branch",
                parent_session_id="parent-1",
                extra={"anchor": {"file": "a.py"}, "note": "n"},
            )
        )
        closed = store.close_branch("branch-1", closed_at=1794549000, closed_by="human")
        assert closed is not None

        store.save(
            SessionOntologyRecord(
                session_id="human-after-close",
                agent_kernel="claude",
                origin="web",
                is_worker=False,
            )
        )

        again = store.get("branch-1")
        assert again is not None
        assert again.extra["closed_at"] == 1794549000
        assert again.extra["closed_by"] == "human"
        assert again.extra.get("anchor") == {"file": "a.py"}

    def test_repeated_close_keeps_first_click(self, store: SessionOntologyStore) -> None:
        """重复收口不改写第一次的时刻与来路：第一次点击才是事实。"""
        store.save(
            SessionOntologyRecord(
                session_id="branch-2",
                agent_kernel="claude",
                relation_kind="branch",
                parent_session_id="parent-1",
                extra={"anchor": {"file": "c.py"}},
            )
        )
        store.close_branch("branch-2", closed_at=1794549000, closed_by="human")
        repeat = store.close_branch("branch-2", closed_at=1794549999, closed_by="someone-else")
        assert repeat is not None
        assert repeat.extra["closed_at"] == 1794549000
        assert repeat.extra["closed_by"] == "human"


class TestConcurrentWriteVisibility:
    """别的进程刚写进老账本的关系，本进程下一次读就必须看得见。"""

    def test_external_ledger_edit_is_picked_up_by_increment_step(self, tmp_path: Path) -> None:
        """外部直接改 ``agent-launches.json`` 之后调 ``increment_step``，改动不能被吞掉。

        这是双账本最容易出错的一处：本体存储落盘时会**整份覆写**老账本。若它拿的是自己
        手上的旧快照，外部刚写进去的那条关系就会在这一次写入里消失，且不报错。
        这里的判据是：改完之后读回来，外部写的那条还在，且步数是自增过的。
        """
        legacy_file = tmp_path / "agent-launches.json"
        store_file = tmp_path / "session-ontology-store.json"
        store = SessionOntologyStore(store_file, legacy_ledger_path=legacy_file)

        store.save(
            SessionOntologyRecord(
                session_id="sess-step-1",
                agent_kernel="claude",
                origin="terminal",
                lifecycle_state="running",
                is_worker=False,
            )
        )

        # 外部（另一个进程）往老账本里追加一条派活关系。
        legacy = json.loads(legacy_file.read_text(encoding="utf-8"))
        assert isinstance(legacy, list)
        legacy.append(
            {
                "child": "external-worker-1",
                "parent": "sess-step-1",
                "kind": "dispatch",
                "origin": "worker",
                "agent_type": "claude",
                "cwd": "/repo",
                "prompt_head": "外部进程派出去的活",
                "at": 1794550000,
            }
        )
        legacy_file.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

        # 本进程接着自增步数（这一步会读—改—写两份账）。
        new_count = store.increment_step("sess-step-1")
        assert new_count == 1

        # 外部那条关系必须还在。
        after = json.loads(legacy_file.read_text(encoding="utf-8"))
        children = {e["child"] for e in after}
        assert "external-worker-1" in children, (
            "外部刚写进老账本的派活关系被本体存储的整份覆写吞掉了"
        )
        # 自增也确实落盘了。
        rec = store.get("sess-step-1")
        assert rec is not None
        assert rec.step_count == 1

    def test_increment_step_on_unknown_session_is_zero(self, store: SessionOntologyStore) -> None:
        """不存在的会话自增步数返回 0，不建档、不抛错。"""
        assert store.increment_step("no-such-session") == 0
        assert store.get("no-such-session") is None

    def test_save_then_get_roundtrip(self, store: SessionOntologyStore) -> None:
        """落盘再读回来，字段原样。"""
        store.save(
            SessionOntologyRecord(
                session_id="sess-rt-1",
                agent_kernel="agy",
                origin="web",
                lifecycle_state="awaiting_input",
                cwd="/repo/x",
                prompt_head="第一句",
            )
        )
        rec = store.get("sess-rt-1")
        assert rec is not None
        assert rec.agent_kernel == "agy"
        assert rec.origin == "web"
        assert rec.lifecycle_state == "awaiting_input"
        assert rec.cwd == "/repo/x"
        assert rec.prompt_head == "第一句"


class TestLegacyLedgerProjection:
    """老账本只记「关系」：没有关系的普通会话一条都不该进去。"""

    def test_human_session_stays_out_of_legacy_ledger(self, store: SessionOntologyStore, tmp_path: Path) -> None:
        store.save(
            SessionOntologyRecord(
                session_id="human-1",
                agent_kernel="claude",
                origin="terminal",
                is_worker=False,
            )
        )
        legacy = json.loads((tmp_path / "agent-launches.json").read_text(encoding="utf-8"))
        assert legacy == []

    def test_dispatch_without_parent_still_counts_as_worker(self, store: SessionOntologyStore, tmp_path: Path) -> None:
        """认不出父亲也仍然是 worker：派活这件事本身就是 worker 的证据。"""
        store.save(
            SessionOntologyRecord(
                session_id="worker-1",
                agent_kernel="claude",
                origin="worker",
                is_worker=True,
                parent_session_id=None,
                relation_kind="dispatch",
            )
        )
        legacy = json.loads((tmp_path / "agent-launches.json").read_text(encoding="utf-8"))
        assert [e["child"] for e in legacy] == ["worker-1"]
        assert legacy[0]["origin"] == "worker"
        assert legacy[0]["parent"] is None
