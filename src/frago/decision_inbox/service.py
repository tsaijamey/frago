"""统一决策收件箱业务服务（受 Gate 3 本体动作契约与影子投影保护）。"""

from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path
from typing import Any

from frago.decision_inbox.store import DecisionInboxStore
from frago.ontology import (
    DECISION_INBOX_ALLOWED_ACTION_TYPES,
    DECISION_INBOX_ALLOWED_RISKS,
    ActionContractError,
    build_propose_decision_contract,
    build_transition_decision_inbox_item_contract,
    is_legal_decision_inbox_transition,
    ontological_action,
    project_decision_inbox_item_dict,
)

DEFAULT_TTL_HOURS = 72.0


class DecisionInboxError(RuntimeError):
    """统一决策收件箱领域异常基类。"""


class DecisionNotFoundError(DecisionInboxError):
    """找不到对应的决策提案。"""


class InvalidDecisionTransitionError(DecisionInboxError):
    """违反 DecisionInboxState 状态机的非法跃迁或参数校验失败。"""


class UndoNotAllowedError(DecisionInboxError):
    """不可撤销的操作（终态/不可逆已落盘动作严禁伪撤销）。"""


def build_dedup_key(
    *,
    dedup_key: str | None = None,
    question: str,
    schedule_id: str | None = None,
    session_id: str | None = None,
    employee_id: str | None = None,
) -> str:
    """生成确定性的 ``dedup_key``。显式传入优先；否则按作用域 + 归一化问句生成稳定键。"""
    explicit = (dedup_key or "").strip()
    if explicit:
        return explicit
    scope = (
        (schedule_id or "").strip()
        or (session_id or "").strip()
        or (employee_id or "").strip()
        or "global"
    )
    normalized_q = " ".join(str(question or "").lower().split())[:120]
    digest = hashlib.sha256(normalized_q.encode("utf-8")).hexdigest()[:16]
    return f"{scope}:{digest}"


def _derive_risk_label(risk: str, irreversible: bool) -> str:
    if irreversible or risk == "high":
        return "高危不可逆"
    if risk == "medium":
        return "外发变更"
    return "常规待决"


def _normalize_options(
    options: list[dict[str, Any]] | None,
    *,
    action_type: str,
    recommended: str | None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for idx, opt in enumerate(options or []):
        if not isinstance(opt, dict):
            continue
        key = str(opt.get("key") or opt.get("id") or chr(65 + idx)).strip()
        label = str(opt.get("label") or key).strip()
        effect = str(opt.get("effect") or "").strip()
        is_rec = bool(opt.get("recommended")) or (
            recommended is not None and key == recommended
        )
        item_dict: dict[str, Any] = {
            "key": key,
            "label": label,
            "effect": effect,
            "recommended": is_rec,
        }
        if "reversible" in opt and isinstance(opt.get("reversible"), bool):
            item_dict["reversible"] = opt["reversible"]
        normalized.append(item_dict)
    if action_type == "binary" and not normalized:
        rec_key = (recommended or "approve").strip()
        normalized = [
            {
                "key": "approve",
                "label": "确认执行",
                "effect": "批准执行该提案描述的操作",
                "recommended": rec_key == "approve",
            },
            {
                "key": "reject",
                "label": "拒绝执行",
                "effect": "取消该提案，维持现状",
                "recommended": rec_key == "reject",
            },
        ]
    return normalized


class DecisionInboxService:
    """统一决策收件箱核心领域服务。"""

    def __init__(self, store: DecisionInboxStore | None = None) -> None:
        self._store = store if store is not None else DecisionInboxStore()
        self._propose_contract = build_propose_decision_contract()
        self._transition_contract = build_transition_decision_inbox_item_contract()

        @ontological_action(self._propose_contract)
        def _exec_propose(
            *,
            proposal_id: str,  # noqa: ARG001
            dedup_key: str,  # noqa: ARG001
            action_type: str,  # noqa: ARG001
            risk: str,  # noqa: ARG001
            irreversible: bool,  # noqa: ARG001
            ttl_hours: float,  # noqa: ARG001
            title: str,  # noqa: ARG001
            recommended: str | None,  # noqa: ARG001
            source: str,  # noqa: ARG001
            payload_builder: Any,
        ) -> dict[str, Any]:
            return payload_builder()

        @ontological_action(self._transition_contract)
        def _exec_transition(
            *,
            proposal_id: str,  # noqa: ARG001
            from_state: str,  # noqa: ARG001
            to_state: str,
            action_verb: str,  # noqa: ARG001
            actor_principal: str,  # noqa: ARG001
            irreversible: bool,  # noqa: ARG001
            prior_inbox_state: str | None,  # noqa: ARG001
        ) -> str:
            return to_state

        self._exec_propose = _exec_propose
        self._exec_transition = _exec_transition

    @property
    def store(self) -> DecisionInboxStore:
        return self._store

    def propose(
        self,
        *,
        question: str,
        action_type: str = "single-choice",
        options: list[dict[str, Any]] | None = None,
        recommended: str | None = None,
        why: str = "",
        skip_reason: str = "",
        impact_scope: str = "",
        evidence: str = "",
        risk: str = "low",
        irreversible: bool = False,
        ttl_hours: float = DEFAULT_TTL_HOURS,
        dedup_key: str | None = None,
        source: str = "schedule",
        session_id: str | None = None,
        schedule_id: str | None = None,
        schedule_name: str | None = None,
        employee_id: str | None = None,
        employee_name: str | None = None,
        employee_color: str | None = None,
        draft: str | None = None,
        suggestion: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        ts = float(now if now is not None else time.time())
        clean_title = str(question or "").strip()
        if not clean_title:
            raise InvalidDecisionTransitionError("question 不能为空。")
        clean_type = str(action_type or "single-choice").strip()
        if clean_type not in DECISION_INBOX_ALLOWED_ACTION_TYPES:
            raise InvalidDecisionTransitionError(
                f"不支持的 action_type '{clean_type}'，允许：{sorted(DECISION_INBOX_ALLOWED_ACTION_TYPES)}"
            )
        clean_risk = str(risk or "low").strip().lower()
        if clean_risk not in DECISION_INBOX_ALLOWED_RISKS:
            raise InvalidDecisionTransitionError(
                f"不支持的 risk '{clean_risk}'，允许：{sorted(DECISION_INBOX_ALLOWED_RISKS)}"
            )
        if ttl_hours <= 0:
            raise InvalidDecisionTransitionError("ttl_hours 必须大于 0。")
        if irreversible and clean_risk == "low":
            clean_risk = "high"

        clean_source = "session" if source == "session" else "schedule"
        source_label = "在线等待" if clean_source == "session" else "定时任务跳过"
        clean_rec = str(recommended).strip() if recommended else None
        norm_options = _normalize_options(
            options, action_type=clean_type, recommended=clean_rec
        )
        if clean_rec is None:
            clean_rec = next(
                (str(o["key"]) for o in norm_options if o.get("recommended")),
                None,
            )

        resolved_dedup_key = build_dedup_key(
            dedup_key=dedup_key,
            question=clean_title,
            schedule_id=schedule_id,
            session_id=session_id,
            employee_id=employee_id,
        )

        # 先做一次超期收口，避免聚合到已经超期的历史条目上
        self.sweep_expired(now=ts)

        existing = self._store.find_active_by_dedup_key(resolved_dedup_key)
        is_dedup = existing is not None
        target_id = existing["proposal_id"] if existing is not None else f"dec_{uuid.uuid4().hex[:12]}"

        def _build_and_save() -> dict[str, Any]:
            if existing is not None:
                selected_opt = existing.get("selected_opt") or clean_rec or (
                    norm_options[0]["key"] if norm_options else None
                )
                candidate = {
                    **existing,
                    "action_type": clean_type,
                    "risk": clean_risk,
                    "risk_label": _derive_risk_label(clean_risk, irreversible),
                    "irreversible": bool(irreversible),
                    "title": clean_title,
                    "summary": str(why or existing.get("summary") or clean_title).strip(),
                    "why": str(why or existing.get("why") or "").strip(),
                    "skip_reason": str(skip_reason or existing.get("skip_reason") or "").strip(),
                    "impact_scope": str(impact_scope or existing.get("impact_scope") or "").strip(),
                    "evidence": str(evidence or existing.get("evidence") or "").strip(),
                    "options": norm_options or existing.get("options") or [],
                    "recommended": clean_rec if clean_rec is not None else existing.get("recommended"),
                    "selected_opt": selected_opt,
                    "draft": draft if draft is not None else existing.get("draft"),
                    "suggestion": suggestion if suggestion is not None else existing.get("suggestion"),
                    "session_id": session_id or existing.get("session_id"),
                    "schedule_id": schedule_id or existing.get("schedule_id"),
                    "schedule_name": schedule_name or existing.get("schedule_name"),
                    "employee_id": employee_id or existing.get("employee_id"),
                    "employee_name": employee_name or existing.get("employee_name"),
                    "employee_color": employee_color or existing.get("employee_color"),
                    # 关键不变量：去重命中时严禁重置 created_at/expires_at，也不把 snoozed 翻回 pending
                    "status": existing["status"],
                    "created_at": existing["created_at"],
                    "expires_at": existing["expires_at"],
                    "updated_at": ts,
                    "last_seen_at": ts,
                    "occurrence_count": int(existing.get("occurrence_count", 1)) + 1,
                }
            else:
                selected_opt = clean_rec or (norm_options[0]["key"] if norm_options else None)
                candidate = {
                    "proposal_id": target_id,
                    "dedup_key": resolved_dedup_key,
                    "source": clean_source,
                    "source_label": source_label,
                    "action_type": clean_type,
                    "risk": clean_risk,
                    "risk_label": _derive_risk_label(clean_risk, irreversible),
                    "irreversible": bool(irreversible),
                    "title": clean_title,
                    "summary": str(why or clean_title).strip(),
                    "why": str(why or "").strip(),
                    "skip_reason": str(skip_reason or "").strip(),
                    "impact_scope": str(impact_scope or "").strip(),
                    "evidence": str(evidence or "").strip(),
                    "options": norm_options,
                    "recommended": clean_rec,
                    "selected_opt": selected_opt,
                    "draft": draft,
                    "suggestion": suggestion,
                    "session_id": (session_id or "").strip() or None,
                    "schedule_id": (schedule_id or "").strip() or None,
                    "schedule_name": (schedule_name or "").strip() or None,
                    "employee_id": (employee_id or "").strip() or None,
                    "employee_name": (employee_name or "").strip() or None,
                    "employee_color": (employee_color or "").strip() or None,
                    "status": "pending",
                    "ttl_hours": float(ttl_hours),
                    "created_at": ts,
                    "updated_at": ts,
                    "last_seen_at": ts,
                    "expires_at": ts + float(ttl_hours) * 3600.0,
                    "occurrence_count": 1,
                    "last_reversible_from_state": None,
                    "resolution": None,
                    "schedule_notified_at": None,
                }

            # Gate 2/3 本体影子投影校验
            project_decision_inbox_item_dict(candidate)
            saved = self._store.upsert(
                candidate,
                event_type="proposal_deduped" if is_dedup else "proposal_created",
                event_detail={"occurrence_count": candidate["occurrence_count"]},
            )
            return {**saved, "deduped": is_dedup}

        try:
            return self._exec_propose(
                proposal_id=target_id,
                dedup_key=resolved_dedup_key,
                action_type=clean_type,
                risk=clean_risk,
                irreversible=bool(irreversible),
                ttl_hours=float(ttl_hours),
                title=clean_title,
                recommended=clean_rec,
                source=clean_source,
                payload_builder=_build_and_save,
            )
        except ActionContractError as exc:
            raise InvalidDecisionTransitionError(str(exc)) from exc

    def sweep_expired(self, *, now: float | None = None) -> list[dict[str, Any]]:
        """对超期活跃提案执行保守收口（不可逆或无推荐项安全中止；可逆且有推荐项按推荐项落盘）。"""
        ts = float(now if now is not None else time.time())
        active = self._store.list_all(statuses=("pending", "snoozed"))
        expired_items: list[dict[str, Any]] = []
        for item in active:
            if float(item["expires_at"]) > ts:
                continue
            from_state = str(item["status"])
            try:
                self._exec_transition(
                    proposal_id=item["proposal_id"],
                    from_state=from_state,
                    to_state="expired",
                    action_verb="expire",
                    actor_principal="PrimarySchedulerRole",
                    irreversible=bool(item.get("irreversible")),
                    prior_inbox_state=from_state,
                )
            except ActionContractError:
                continue
            rec = item.get("recommended")
            if (not item.get("irreversible")) and rec:
                resolution = {
                    "mode": "ttl_recommended_fallback",
                    "choice": rec,
                    "note": f"超过 {float(item.get('ttl_hours', DEFAULT_TTL_HOURS)):g} 小时未拍板，已按推荐项「{rec}」保守收口",
                    "actor": "system_ttl",
                    "decided_at": ts,
                }
            else:
                resolution = {
                    "mode": "ttl_safe_hold",
                    "choice": None,
                    "note": "安全维持原状（超期未拍板，不可逆或无推荐项操作严禁自动执行）",
                    "actor": "system_ttl",
                    "decided_at": ts,
                }
            updated = {
                **item,
                "status": "expired",
                "updated_at": ts,
                "last_reversible_from_state": None,
                "resolution": resolution,
            }
            project_decision_inbox_item_dict(updated)
            saved = self._store.upsert(
                updated,
                event_type="proposal_expired",
                event_detail={"resolution_mode": resolution["mode"]},
            )
            expired_items.append(saved)
        return expired_items

    def get(self, proposal_id: str, *, now: float | None = None) -> dict[str, Any]:
        self.sweep_expired(now=now)
        item = self._store.get(proposal_id)
        if item is None:
            raise DecisionNotFoundError(f"找不到决策提案：{proposal_id}")
        return item

    def list_items(
        self,
        *,
        statuses: tuple[str, ...] | None = None,
        source: str | None = None,
        schedule_id: str | None = None,
        now: float | None = None,
    ) -> list[dict[str, Any]]:
        self.sweep_expired(now=now)
        return self._store.list_all(
            statuses=statuses,
            source=source,
            schedule_id=schedule_id,
        )

    def _apply_transition(
        self,
        proposal_id: str,
        *,
        to_state: str,
        action_verb: str,
        actor: str = "human",
        actor_principal: str = "HumanPrincipal",
        resolution: dict[str, Any] | None = None,
        reversible_from: str | None = None,
        selected_opt: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        ts = float(now if now is not None else time.time())
        self.sweep_expired(now=ts)
        item = self._store.get(proposal_id)
        if item is None:
            raise DecisionNotFoundError(f"找不到决策提案：{proposal_id}")
        from_state = str(item["status"])
        if not is_legal_decision_inbox_transition(from_state, to_state):
            raise InvalidDecisionTransitionError(
                f"提案 {proposal_id} 当前状态为 '{from_state}'，无法执行 '{action_verb}' 跃迁至 '{to_state}'。"
            )
        try:
            self._exec_transition(
                proposal_id=proposal_id,
                from_state=from_state,
                to_state=to_state,
                action_verb=action_verb,
                actor_principal=actor_principal,
                irreversible=bool(item.get("irreversible")),
                prior_inbox_state=from_state,
            )
        except ActionContractError as exc:
            raise InvalidDecisionTransitionError(str(exc)) from exc

        updated = {
            **item,
            "status": to_state,
            "updated_at": ts,
            "last_reversible_from_state": reversible_from,
            "resolution": resolution if resolution is not None else item.get("resolution"),
            "selected_opt": selected_opt if selected_opt is not None else item.get("selected_opt"),
        }
        project_decision_inbox_item_dict(updated)
        return self._store.upsert(
            updated,
            event_type=f"proposal_{action_verb}",
            event_detail={"from_state": from_state, "to_state": to_state, "actor": actor},
        )

    def resolve(
        self,
        proposal_id: str,
        *,
        choice: str | None = None,
        choices: list[str] | None = None,
        answer_text: str | None = None,
        note: str | None = None,
        actor: str = "human",
        now: float | None = None,
    ) -> dict[str, Any]:
        ts = float(now if now is not None else time.time())
        item = self.get(proposal_id, now=ts)
        chosen = choice
        if chosen is None and choices:
            chosen = ",".join(str(c) for c in choices if str(c).strip())
        if chosen is None and answer_text:
            chosen = answer_text.strip()
        if chosen is None:
            chosen = item.get("selected_opt") or item.get("recommended")
        receipt_id = f"receipt_{uuid.uuid4().hex[:12]}"
        resolution = {
            "mode": "human_approve",
            "choice": chosen,
            "choices": list(choices) if choices else ([chosen] if chosen else []),
            "answer_text": (answer_text or "").strip() or None,
            "note": (note or "").strip() or None,
            "actor": actor,
            "decided_at": ts,
            "receipt_id": receipt_id,
        }
        return self._apply_transition(
            proposal_id,
            to_state="resolved",
            action_verb="resolve",
            actor=actor,
            resolution=resolution,
            reversible_from=None,
            selected_opt=chosen,
            now=ts,
        )

    def reject(
        self,
        proposal_id: str,
        *,
        note: str | None = None,
        actor: str = "human",
        now: float | None = None,
    ) -> dict[str, Any]:
        ts = float(now if now is not None else time.time())
        receipt_id = f"receipt_{uuid.uuid4().hex[:12]}"
        resolution = {
            "mode": "human_reject",
            "choice": None,
            "note": (note or "").strip() or "人类驳回执行",
            "actor": actor,
            "decided_at": ts,
            "receipt_id": receipt_id,
        }
        return self._apply_transition(
            proposal_id,
            to_state="rejected",
            action_verb="reject",
            actor=actor,
            resolution=resolution,
            reversible_from=None,
            now=ts,
        )

    def snooze(
        self,
        proposal_id: str,
        *,
        actor: str = "human",
        now: float | None = None,
    ) -> dict[str, Any]:
        return self._apply_transition(
            proposal_id,
            to_state="snoozed",
            action_verb="snooze",
            actor=actor,
            reversible_from="pending",
            now=now,
        )

    def unsnooze(
        self,
        proposal_id: str,
        *,
        actor: str = "human",
        now: float | None = None,
    ) -> dict[str, Any]:
        return self._apply_transition(
            proposal_id,
            to_state="pending",
            action_verb="unsnooze",
            actor=actor,
            reversible_from="snoozed",
            now=now,
        )

    def undo(
        self,
        proposal_id: str,
        *,
        actor: str = "human",
        now: float | None = None,
    ) -> dict[str, Any]:
        """仅支持可逆状态切换（pending ↔ snoozed）；已批复/已驳回/超期终态严格拒绝对外伪撤销。"""
        ts = float(now if now is not None else time.time())
        item = self.get(proposal_id, now=ts)
        status = str(item["status"])
        prev = item.get("last_reversible_from_state")
        if status not in {"pending", "snoozed"} or prev not in {"pending", "snoozed"} or prev == status:
            raise UndoNotAllowedError(
                f"提案 {proposal_id} 当前状态为 '{status}'，仅搁置/恢复待决切换支持撤销，已落盘或不可逆动作严禁伪撤销。"
            )
        verb = "unsnooze" if prev == "pending" else "snooze"
        return self._apply_transition(
            proposal_id,
            to_state=prev,
            action_verb=verb,
            actor=actor,
            reversible_from=None,
            now=ts,
        )

    def supersede(
        self,
        proposal_id: str,
        *,
        reason: str | None = None,
        actor: str = "system",
        now: float | None = None,
    ) -> dict[str, Any]:
        """经由本体契约将活跃提案（pending/snoozed）跃迁为 superseded 终态。"""
        ts = float(now if now is not None else time.time())
        resolution = {
            "mode": "superseded",
            "choice": None,
            "note": (reason or "").strip() or "原待决轮次已被新上下文替代",
            "actor": actor,
            "decided_at": ts,
        }
        principal = "PrimarySchedulerRole" if actor == "system" else "HumanPrincipal"
        return self._apply_transition(
            proposal_id,
            to_state="superseded",
            action_verb="supersede",
            actor=actor,
            actor_principal=principal,
            resolution=resolution,
            reversible_from=None,
            now=ts,
        )

    def note_for_schedule(
        self,
        schedule_id: str,
        *,
        mark_consumed: bool = True,
        now: float | None = None,
    ) -> str | None:
        """为定时任务下一次运行装配「人类近期拍板 / 超期保守收口」前置提示，替代旧文本抓卡。"""
        clean_id = (schedule_id or "").strip()
        if not clean_id:
            return None
        ts = float(now if now is not None else time.time())
        self.sweep_expired(now=ts)
        items = self._store.list_all(
            statuses=("resolved", "rejected", "expired"),
            schedule_id=clean_id,
        )
        fresh = [i for i in items if i.get("schedule_notified_at") is None]
        if not fresh:
            return None

        lines: list[str] = ["【统一决策收件箱最新回执】请优先遵循以下人类拍板或超期策略结论："]
        consumed_ids: list[str] = []
        for item in fresh:
            consumed_ids.append(item["proposal_id"])
            res = item.get("resolution") or {}
            status = item["status"]
            choice = res.get("choice")
            note = res.get("note") or ""
            if status == "resolved":
                lines.append(
                    f"- [已批准] {item['title']} -> 选择：{choice or '默认'}"
                    + (f"（备注：{note}）" if note else "")
                )
            elif status == "rejected":
                lines.append(
                    f"- [已驳回] {item['title']} -> 勿执行该操作"
                    + (f"（原因：{note}）" if note else "")
                )
            else:
                mode = res.get("mode")
                if mode == "ttl_recommended_fallback" and choice:
                    lines.append(
                        f"- [超期按推荐项保守执行] {item['title']} -> 默认采用推荐项：{choice}（请在最终答复注明这是按超时默认推荐项处理的）"
                    )
                else:
                    lines.append(
                        f"- [超期安全中止] {item['title']} -> {note or '安全维持原状，严禁自行执行'}"
                    )

        if mark_consumed and consumed_ids:
            self._store.mark_schedule_notified(consumed_ids, ts)

        return "\n".join(lines)


def get_decision_inbox_service(root_dir: Path | None = None) -> DecisionInboxService:
    return DecisionInboxService(DecisionInboxStore(root_dir=root_dir))
