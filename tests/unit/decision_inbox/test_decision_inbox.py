"""统一决策收件箱领域服务单元测试（去重、TTL 收口、可逆撤销边界、零配置空态）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from frago.decision_inbox import (
    DecisionInboxService,
    DecisionInboxStore,
    DecisionNotFoundError,
    InvalidDecisionTransitionError,
    UndoNotAllowedError,
    build_dedup_key,
)


def test_zero_config_empty_store_does_not_create_files_or_fail(tmp_path: Path) -> None:
    root = tmp_path / "fresh-machine-inbox"
    svc = DecisionInboxService(DecisionInboxStore(root))
    assert not root.exists()
    assert svc.list_items() == []
    assert svc.note_for_schedule("daily-clean") is None
    assert not root.exists()


def test_dedup_preserves_ttl_and_snoozed_state(tmp_path: Path) -> None:
    svc = DecisionInboxService(DecisionInboxStore(tmp_path / "inbox"))
    t0 = 1_700_000_000.0
    first = svc.propose(
        question="是否清理旧日志？",
        action_type="single-choice",
        options=[
            {"key": "A", "label": "清理 30 天前", "effect": "释放 2GB", "recommended": True},
            {"key": "B", "label": "保留", "effect": "无变化"},
        ],
        recommended="A",
        why="磁盘占用 85%",
        schedule_id="daily-log-gc",
        ttl_hours=72.0,
        now=t0,
    )
    assert first["deduped"] is False
    assert first["occurrence_count"] == 1
    assert first["expires_at"] == pytest.approx(t0 + 72.0 * 3600.0)

    # 人类将其搁置
    snoozed = svc.snooze(first["proposal_id"], now=t0 + 60.0)
    assert snoozed["status"] == "snoozed"

    # 12 小时后同定时任务再次提出同类问题 -> 命中活跃去重
    t1 = t0 + 12 * 3600.0
    second = svc.propose(
        question="是否清理旧日志？",
        action_type="single-choice",
        options=[
            {"key": "A", "label": "清理 30 天前", "effect": "释放 2.4GB", "recommended": True},
            {"key": "B", "label": "保留", "effect": "无变化"},
        ],
        recommended="A",
        why="磁盘占用 89%",
        schedule_id="daily-log-gc",
        ttl_hours=72.0,
        now=t1,
    )
    assert second["deduped"] is True
    assert second["proposal_id"] == first["proposal_id"]
    assert second["occurrence_count"] == 2
    # created_at 和 expires_at 绝不重置；snoozed 绝不翻回 pending
    assert second["created_at"] == pytest.approx(t0)
    assert second["expires_at"] == pytest.approx(t0 + 72.0 * 3600.0)
    assert second["status"] == "snoozed"
    assert second["why"] == "磁盘占用 89%"


def test_ttl_expiry_reversible_recommended_vs_irreversible_safe_hold(tmp_path: Path) -> None:
    svc = DecisionInboxService(DecisionInboxStore(tmp_path / "inbox"))
    t0 = 1_700_000_000.0

    reversible = svc.propose(
        question="是否归档旧草稿？",
        action_type="single-choice",
        options=[
            {"key": "A", "label": "归档", "effect": "移动到 archive/"},
            {"key": "B", "label": "保留", "effect": "原地不动"},
        ],
        recommended="A",
        irreversible=False,
        risk="low",
        ttl_hours=72.0,
        schedule_id="sched-1",
        now=t0,
    )
    high_risk = svc.propose(
        question="是否强制删除生产分支？",
        action_type="binary",
        recommended="approve",
        irreversible=True,
        risk="high",
        ttl_hours=72.0,
        schedule_id="sched-1",
        now=t0,
    )

    expired = svc.sweep_expired(now=t0 + 73.0 * 3600.0)
    assert len(expired) == 2

    rev_after = svc.get(reversible["proposal_id"], now=t0 + 73.0 * 3600.0)
    assert rev_after["status"] == "expired"
    assert rev_after["resolution"]["mode"] == "ttl_recommended_fallback"
    assert rev_after["resolution"]["choice"] == "A"

    high_after = svc.get(high_risk["proposal_id"], now=t0 + 73.0 * 3600.0)
    assert high_after["status"] == "expired"
    assert high_after["resolution"]["mode"] == "ttl_safe_hold"
    assert high_after["resolution"]["choice"] is None

    note = svc.note_for_schedule("sched-1", mark_consumed=True, now=t0 + 73.0 * 3600.0)
    assert note is not None
    assert "超期按推荐项保守执行" in note
    assert "超期安全中止" in note
    # 消费过一次后，再次读取不重复注入
    assert svc.note_for_schedule("sched-1", now=t0 + 73.0 * 3600.0) is None


def test_reversible_undo_only_for_snooze_and_never_for_resolved_or_rejected(
    tmp_path: Path,
) -> None:
    svc = DecisionInboxService(DecisionInboxStore(tmp_path / "inbox"))
    t0 = 1_700_000_000.0

    item = svc.propose(
        question="是否发布版本？",
        action_type="binary",
        irreversible=True,
        risk="high",
        now=t0,
    )
    pid = item["proposal_id"]

    # 1. pending -> snoozed -> undo -> pending
    snoozed = svc.snooze(pid, now=t0 + 10)
    assert snoozed["status"] == "snoozed"
    undone = svc.undo(pid, now=t0 + 20)
    assert undone["status"] == "pending"

    # 再次直接 undo（无最近可逆切换）拒绝
    with pytest.raises(UndoNotAllowedError):
        svc.undo(pid, now=t0 + 30)

    # 2. resolved 终态严禁 undo
    resolved = svc.resolve(pid, choice="approve", note="已核对", now=t0 + 40)
    assert resolved["status"] == "resolved"
    with pytest.raises(UndoNotAllowedError):
        svc.undo(pid, now=t0 + 50)
    with pytest.raises(InvalidDecisionTransitionError):
        svc.reject(pid, now=t0 + 60)

    # 3. 不存在的 ID
    with pytest.raises(DecisionNotFoundError):
        svc.get("dec_nonexistent")


def test_build_dedup_key_is_deterministic() -> None:
    k1 = build_dedup_key(question="  Merge   PR #42? ", schedule_id="repo-patrol")
    k2 = build_dedup_key(question="merge pr #42?", schedule_id="repo-patrol")
    assert k1 == k2
    assert build_dedup_key(dedup_key="custom-key", question="x") == "custom-key"


def test_supersede_transitions_via_ontology_and_preserves_option_reversible() -> None:
    svc = DecisionInboxService()
    t0 = 1_700_000_000.0
    item = svc.propose(
        question="是否直接切换生产路由？",
        action_type="single-choice",
        options=[
            {"key": "A", "label": "灰度", "effect": "10% 切流", "reversible": True},
            {"key": "B", "label": "全切", "effect": "直接替换路由", "reversible": False},
        ],
        dedup_key="session:ses-sup-1",
        source="session",
        session_id="ses-sup-1",
        now=t0,
    )
    assert item["options"][0]["reversible"] is True
    assert item["options"][1]["reversible"] is False

    snoozed = svc.snooze(item["proposal_id"], now=t0 + 5)
    assert snoozed["status"] == "snoozed"

    superseded = svc.supersede(
        item["proposal_id"],
        reason="会话产生新提问，旧搁置影子失效",
        actor="system",
        now=t0 + 15,
    )
    assert superseded["status"] == "superseded"
    assert superseded["resolution"]["mode"] == "superseded"
    assert superseded["last_reversible_from_state"] is None
    assert svc.store.find_active_by_dedup_key("session:ses-sup-1") is None

    with pytest.raises(InvalidDecisionTransitionError):
        svc.unsnooze(item["proposal_id"], now=t0 + 20)
