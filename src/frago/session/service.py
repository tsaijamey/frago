"""frago session — ontology-backed service with concentric action contract guards.

Provides Ring 3 concentric contract guards (`@ontological_action` and `ActionContractError`)
for the five canonical Session actions registered in `frago.json`:
1. ``launch_agent_session``: prevents nested worker spawning, validates kernels and origins,
   and registers initial `AgentSessionProcess` + states into storage.
2. ``record_session_step``: emits immutable `SessionStepEvent` and advances step counter.
3. ``yield_awaiting_input``: safely transitions running session into awaiting_input state.
4. ``terminate_agent_session``: finalizes session into completed/error/cancelled, rejecting
   illegal backward state transitions.
5. ``adopt_existing_session``: takes an already-running session that frago did not launch
   (pre-existing transcripts, sessions started by an external CLI) into ontology
   management without inventing a parent relation.

每个动作都同时挂两层护栏：`@ontological_action` 执行 `frago.json` 里登记的同心圆契约
（参数 ⊂ 签名 ⊂ 契约），函数体内的显式校验负责业务语义（内核白名单、worker 禁止嵌套、
状态机合法跃迁）。前者管「这个动作按本体说法能不能这么调」，后者管「这次调用在业务上
站不站得住」，两层都过才算数。

Layer: domain service — imports `frago.session.store` and `frago.ontology.*`.
NEVER imports `frago.server` or `frago.cli`.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shlex
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.ontology import (
    DEFAULT_DOMAIN_REGISTRY,
    AgentSessionProcess,
    DomainClassRegistry,
    OntologyGraph,
    SessionProcessProjection,
    project_session_process_dict,
)
from frago.ontology.contracts import ActionContractError, ontological_action
from frago.ontology.introspection import OntologyIntrospector
from frago.ontology.runtime import (
    SESSION_VALID_KERNELS,
    SESSION_VALID_ORIGINS,
    build_adopt_existing_session_contract,
    build_launch_agent_session_contract,
    build_record_session_step_contract,
    build_terminate_agent_session_contract,
    build_yield_awaiting_input_contract,
    normalize_session_lifecycle_state,
    normalize_session_origin,
)
from frago.session.store import (
    LEGACY_RELATION_KINDS,
    SessionOntologyRecord,
    SessionOntologyStore,
    StaleTurnSeqError,
    get_default_session_store,
)

logger = logging.getLogger(__name__)

TERMINAL_STATES: frozenset[str] = frozenset({"completed", "error", "cancelled"})
ZOMBIE_IDLE_TIMEOUT_SECONDS: int = 6 * 60 * 60  # 6 hours


class StaleTurnEventError(ActionContractError):
    """Raised when a late turn completion/cancellation event carries an outdated turn_seq."""

_ALLOWED_STEP_TYPES: frozenset[str] = frozenset(
    {"user", "assistant", "tool_call", "tool_result", "system"}
)

#: 五个动作的同心圆契约在 import 期一次建好（契约内容来自 frago.json 这个唯一真源）。
_SESSION_ACTION_CONTRACTS = OntologyIntrospector()
_LAUNCH_AGENT_SESSION_CONTRACT = build_launch_agent_session_contract(_SESSION_ACTION_CONTRACTS)
_RECORD_SESSION_STEP_CONTRACT = build_record_session_step_contract(_SESSION_ACTION_CONTRACTS)
_YIELD_AWAITING_INPUT_CONTRACT = build_yield_awaiting_input_contract(_SESSION_ACTION_CONTRACTS)
_TERMINATE_AGENT_SESSION_CONTRACT = build_terminate_agent_session_contract(_SESSION_ACTION_CONTRACTS)
_ADOPT_EXISTING_SESSION_CONTRACT = build_adopt_existing_session_contract(_SESSION_ACTION_CONTRACTS)


class SessionOntologyService:
    """Ontology-backed service managing the lifecycle and contracts of `AgentSessionProcess`."""

    def __init__(
        self,
        store: SessionOntologyStore | None = None,
        *,
        registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    ) -> None:
        self._store = store if store is not None else get_default_session_store()
        self._registry = registry

    @property
    def store(self) -> SessionOntologyStore:
        return self._store

    # ──────────────────────────────────────────────────────────────────────────
    # Ring 3 Action 1: launch_agent_session
    # ──────────────────────────────────────────────────────────────────────────

    @ontological_action(_LAUNCH_AGENT_SESSION_CONTRACT)
    def launch_agent_session(
        self,
        *,
        session_id: str,
        agent_kernel_id: str | None = None,
        agent_kernel: str | None = None,
        origin: str = "terminal",
        initial_prompt: str = "",
        is_worker: bool = False,
        parent_session_id: str | None = None,
        caller_role: str | None = None,
        caller_is_worker: bool = False,
        cwd: str = "",
        relation_kind: str | None = None,
        employee_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> SessionProcessProjection:
        """Launch an AgentSessionProcess with strict Ring 3 contract guardrails.

        Preconditions:
        - Caller MUST NOT bear SubtaskWorkerRole (subtask workers are strictly forbidden from spawning child sessions).
        - origin MUST be one of {'terminal', 'web', 'worker', 'schedule', 'channel'}.
        - session_id MUST be non-empty and not currently in 'running' state.
        - agent_kernel_id MUST be one of five supported kernels.
        """
        clean_sid = str(session_id or "").strip()
        if not clean_sid:
            raise ActionContractError("session_id MUST be a non-empty string.")

        # Hard guardrail 1: Worker nesting prohibition
        if caller_is_worker or caller_role in {"worker", "SubtaskWorkerRole"}:
            raise ActionContractError(
                f"Caller bearing SubtaskWorkerRole is strictly prohibited from spawning "
                f"nested agent sessions (attempted launch of '{clean_sid}')."
            )

        # Check if parent session was a worker
        if parent_session_id:
            parent_rec = self._store.get(parent_session_id)
            if parent_rec is not None and parent_rec.is_worker and not is_worker:
                raise ActionContractError(
                    f"Parent session '{parent_session_id}' is a worker and cannot spawn non-worker session '{clean_sid}'."
                )

        target_kernel = agent_kernel_id or agent_kernel or ""
        clean_kernel = str(target_kernel).strip().lower()
        # 只认本体登记在册的内核名：`claude-code` 是同一个内核的旧写法，归一到 `claude`；
        # 其余拼错的名字当场拒掉，NEVER 静默回落成某个默认内核——回落会把别家的会话
        # 记到 Claude 名下，出身与能力切面跟着一起错。
        if clean_kernel == "claude-code":
            clean_kernel = "claude"
        if clean_kernel not in SESSION_VALID_KERNELS:
            raise ActionContractError(
                f"Unknown agent kernel '{clean_kernel}'. Allowed kernels: {sorted(SESSION_VALID_KERNELS)}."
            )

        clean_origin = str(origin or "").strip().lower()
        normalized_origin = normalize_session_origin(clean_origin, is_worker=is_worker)
        if clean_origin not in SESSION_VALID_ORIGINS and clean_origin != normalized_origin:
            raise ActionContractError(
                f"Invalid session origin '{clean_origin}'. Allowed origins: {sorted(SESSION_VALID_ORIGINS)}."
            )

        # 关系要由调用方明说，或者由 worker 身份推出来。人自己开的会话（终端 / 网页 /
        # 定时 / 渠道）没有关系，落库时留空——给它安一个「派活」会让它在出身判定里
        # 变成「认不出谁派的 worker」，从会话树上掉下去。
        clean_relation = str(relation_kind).strip() if relation_kind else None
        if clean_relation not in LEGACY_RELATION_KINDS:
            clean_relation = None
        if clean_relation is None and (is_worker or normalized_origin == "worker"):
            clean_relation = "dispatch"

        existing = self._store.get(clean_sid)
        if existing is not None and existing.lifecycle_state in {"running", "awaiting_input"}:
            raise ActionContractError(
                f"Session '{clean_sid}' already exists and is currently in active state '{existing.lifecycle_state}'."
            )

        clean_employee = str(employee_id).strip() or None if employee_id else None
        if not clean_employee and extra and extra.get("employee_id"):
            clean_employee = str(extra.get("employee_id")).strip() or None

        rec = SessionOntologyRecord(
            session_id=clean_sid,
            agent_kernel=clean_kernel,
            origin=normalized_origin,
            lifecycle_state="running",
            is_worker=is_worker,
            parent_session_id=parent_session_id,
            relation_kind=clean_relation,
            cwd=cwd,
            turn_seq=max(1, (existing.turn_seq + 1) if existing is not None else 1),
            employee_id=clean_employee,
            prompt_head=initial_prompt[:120],
            extra=dict(extra or {}),
        )
        self._store.save(rec)

        return self.project_session(clean_sid)

    # ──────────────────────────────────────────────────────────────────────────
    # Ring 3 Action 2: record_session_step
    # ──────────────────────────────────────────────────────────────────────────

    @ontological_action(_RECORD_SESSION_STEP_CONTRACT)
    def record_session_step(
        self,
        *,
        session_id: str,
        step_type: str,
        payload_dict: Mapping[str, Any] | None = None,
        tool_name: str | None = None,
    ) -> int:
        """Record an immutable SessionStepEvent into the session lifecycle."""
        clean_sid = str(session_id or "").strip()
        rec = self._store.get(clean_sid)
        if rec is None:
            raise ActionContractError(f"Target AgentSessionProcess '{clean_sid}' does not exist.")

        if rec.lifecycle_state in TERMINAL_STATES:
            raise ActionContractError(
                f"Cannot record session step: target session '{clean_sid}' is terminated ('{rec.lifecycle_state}')."
            )

        clean_step_type = str(step_type or "").strip()
        if clean_step_type not in _ALLOWED_STEP_TYPES:
            raise ActionContractError(
                f"Invalid step_type '{clean_step_type}'. Allowed step types: {sorted(_ALLOWED_STEP_TYPES)}."
            )

        new_count = self._store.increment_step(clean_sid)
        if payload_dict or tool_name:
            rec.step_count = new_count
            rec.extra["latest_step"] = {
                "step_type": clean_step_type,
                "tool_name": tool_name,
                "step_count": new_count,
            }
            self._store.save(rec)
        return new_count

    # ──────────────────────────────────────────────────────────────────────────
    # Ring 3 Action 3: yield_awaiting_input
    # ──────────────────────────────────────────────────────────────────────────

    @ontological_action(_YIELD_AWAITING_INPUT_CONTRACT)
    def yield_awaiting_input(
        self,
        *,
        session_id: str,
        waiting_reason: str,
    ) -> SessionOntologyRecord:
        """Transition an active session from 'running' to 'awaiting_input'."""
        clean_sid = str(session_id or "").strip()
        rec = self._store.get(clean_sid)
        if rec is None:
            raise ActionContractError(f"Target AgentSessionProcess '{clean_sid}' does not exist.")

        if rec.lifecycle_state in TERMINAL_STATES:
            raise ActionContractError(
                f"Cannot transition to 'awaiting_input': session '{clean_sid}' is already in terminal state '{rec.lifecycle_state}'."
            )

        updated = self._store.update_lifecycle_state(
            clean_sid,
            "awaiting_input",
            waiting_reason=waiting_reason,
        )
        if updated is None:
            # 走到这里说明记录在「刚读过」与「刚写入」之间消失了（并发的另一路把它删了）。
            # 从前这一格是 `assert`：`-O` 跑起来整句被优化掉，函数就带着 None 往下走，
            # 上层拿到 None 再取值才炸，现场与原因隔了一层。这里直接抛。
            raise ActionContractError(
                f"Session '{clean_sid}' disappeared from the store while transitioning to 'awaiting_input'."
            )
        return updated

    # ──────────────────────────────────────────────────────────────────────────
    # Ring 3 Action 4: terminate_agent_session
    # ──────────────────────────────────────────────────────────────────────────

    @ontological_action(_TERMINATE_AGENT_SESSION_CONTRACT)
    def terminate_agent_session(
        self,
        *,
        session_id: str,
        terminal_status: str = "completed",
        summary: str | None = None,
    ) -> SessionOntologyRecord:
        """Finalize an AgentSessionProcess with terminal status validation."""
        clean_sid = str(session_id or "").strip()
        rec = self._store.get(clean_sid)
        if rec is None:
            raise ActionContractError(f"Target AgentSessionProcess '{clean_sid}' does not exist.")

        clean_status = str(terminal_status or "").strip().lower()
        if clean_status not in TERMINAL_STATES:
            raise ActionContractError(
                f"Invalid terminal_status '{clean_status}'. Allowed terminal states: {sorted(TERMINAL_STATES)}."
            )

        if rec.lifecycle_state in TERMINAL_STATES:
            raise ActionContractError(
                f"Session '{clean_sid}' is already in terminal state '{rec.lifecycle_state}' and cannot be terminated again."
            )

        updated = self._store.update_lifecycle_state(
            clean_sid,
            clean_status,
            summary=summary,
        )
        if updated is None:
            raise ActionContractError(
                f"Session '{clean_sid}' disappeared from the store while terminating as '{clean_status}'."
            )
        return updated

    # ──────────────────────────────────────────────────────────────────────────
    # Ring 3 Action 5: adopt_existing_session
    # ──────────────────────────────────────────────────────────────────────────

    @ontological_action(_ADOPT_EXISTING_SESSION_CONTRACT)
    def adopt_existing_session(
        self,
        *,
        session_id: str,
        agent_kernel_id: str = "claude",
        origin: str = "terminal",
        initial_state: str = "running",
        already_registered: bool = False,
        relation_kind: str | None = None,  # noqa: ARG002 — 契约要求它出现在签名里（补档不得编造关系），
        # 函数体不读它：这个动作一律写 relation_kind=None，传什么都不影响结果，前置条件会先拒掉非空值。
    ) -> SessionOntologyRecord:
        """把一场 frago 没开过、但确实存在的会话纳入本体纳管。

        ``already_registered`` 由调用方明说它是否已经在本体存储里：这条动作只负责
        **补档**（存量历史会话、外部 CLI 直接拉起的会话），已经在册的会话要走读回路径，
        不能借补档之名重写既有记录——那会把内核、出身这些已经认准的事实覆盖掉。
        调用方拿不准时先 ``get_session`` 看一眼，别把猜测当事实传进来。
        """
        clean_sid = str(session_id or "").strip()
        if not clean_sid:
            raise ActionContractError("session_id MUST be a non-empty string.")

        existing = self._store.get(clean_sid)
        if existing is not None:
            if already_registered:
                return existing
            raise ActionContractError(
                f"Session '{clean_sid}' is already registered in the ontology store; "
                f"read it back instead of re-adopting it."
            )
        if already_registered:
            # 调用方声称在册、实际查不到：这是调用方与存储不一致，别替它圆过去。
            raise ActionContractError(
                f"Caller declared session '{clean_sid}' as already registered, but the store has no such record."
            )

        # 内核别名归一 + 非法回落：补档这条路是存量会话的唯一入口，宁可回落成 claude
        # 也不能抛错——抛错会让整场历史会话从本体里彻底消失（上层是宽 except）。
        # 但回落这件事本身要留痕迹，见下面的 warning。
        kernel = "claude" if agent_kernel_id in ("claude-code", "claude") else str(agent_kernel_id or "")
        if kernel not in SESSION_VALID_KERNELS:
            logger.warning(
                "adopt_existing_session: unknown kernel %r for session %s, falling back to 'claude'.",
                agent_kernel_id,
                clean_sid,
            )
            kernel = "claude"

        new_rec = SessionOntologyRecord(
            session_id=clean_sid,
            agent_kernel=kernel,
            origin=normalize_session_origin(origin),
            lifecycle_state=normalize_session_lifecycle_state(initial_state),
            # 走这条路的都是存量或外部直接拉起的会话，没有一条「谁派了谁」的事实可记。
            # 显式留空，NEVER 让它默认成「派活」——那会把人的会话写成 worker。
            relation_kind=None,
        )
        self._store.save(new_rec)
        return new_rec

    # ──────────────────────────────────────────────────────────────────────────
    # State Machine Transition Guard & Monotonic Turn Seq
    # ──────────────────────────────────────────────────────────────────────────

    def start_turn(
        self,
        session_id: str,
        *,
        agent_kernel_id: str = "claude",
        origin: str = "terminal",
        summary: str | None = None,
    ) -> SessionOntologyRecord:
        """Start a new active turn for ``session_id`` and bump monotonic ``turn_seq``."""
        clean_sid = str(session_id or "").strip()
        self.ensure_managed_session(
            clean_sid,
            agent_kernel_id=agent_kernel_id,
            origin=origin,
            initial_state="running",
        )
        updated = self._store.start_turn(clean_sid, summary=summary)
        if updated is None:
            raise ActionContractError(
                f"Session '{clean_sid}' disappeared from the store while starting turn."
            )
        return updated

    def complete_turn_if_current(
        self,
        session_id: str,
        *,
        turn_seq: int,
        target_state: str = "completed",
        waiting_reason: str | None = None,
        summary: str | None = None,
    ) -> tuple[SessionOntologyRecord | None, bool]:
        """Complete/yield a turn ONLY when ``turn_seq`` matches the latest active turn.

        Late completion/cancellation callbacks carrying ``turn_seq < rec.turn_seq``
        are safely dropped (returns ``(rec, False)``) and NEVER downgrade or cancel
        the currently running turn.
        """
        clean_sid = str(session_id or "").strip()
        rec = self._store.get(clean_sid)
        if rec is None:
            return None, False
        if int(turn_seq) < int(rec.turn_seq):
            logger.warning(
                "Late turn event dropped for session %s: event_turn_seq=%s < current_turn_seq=%s (target=%s)",
                clean_sid,
                turn_seq,
                rec.turn_seq,
                target_state,
            )
            return rec, False
        target = normalize_session_lifecycle_state(target_state)
        try:
            updated = self._store.update_lifecycle_state(
                clean_sid,
                target,
                waiting_reason=waiting_reason,
                summary=summary,
                expected_turn_seq=int(turn_seq),
            )
        except StaleTurnSeqError:
            latest = self._store.get(clean_sid)
            logger.warning(
                "Late turn event dropped under store lock for session %s: event_turn_seq=%s (current=%s)",
                clean_sid,
                turn_seq,
                latest.turn_seq if latest else "?",
            )
            return latest, False
        return updated, updated is not None

    def transition_state(
        self,
        session_id: str,
        target_state: str,
        *,
        reason: str | None = None,
        summary: str | None = None,
        allow_resume: bool = False,
        turn_seq: int | None = None,
    ) -> SessionOntologyRecord:
        """Enforce strict state machine transitions across session lifecycle."""
        clean_sid = str(session_id or "").strip()
        rec = self._store.get(clean_sid)
        if rec is None:
            raise ActionContractError(f"Session '{clean_sid}' not found.")

        if turn_seq is not None and int(turn_seq) < int(rec.turn_seq):
            raise StaleTurnEventError(
                f"Late turn event rejected for session '{clean_sid}': "
                f"event turn_seq={turn_seq} < current turn_seq={rec.turn_seq}."
            )

        current = rec.lifecycle_state
        target = normalize_session_lifecycle_state(target_state)

        # Illegal backward transition: terminal -> active without explicit allow_resume
        if current in TERMINAL_STATES and target not in TERMINAL_STATES and not allow_resume:
            raise ActionContractError(
                f"Illegal state machine transition: session '{clean_sid}' cannot jump backward "
                f"from terminal state '{current}' to '{target}' without explicit resume."
            )

        try:
            updated = self._store.update_lifecycle_state(
                clean_sid,
                target,
                waiting_reason=reason,
                summary=summary,
                expected_turn_seq=turn_seq,
            )
        except StaleTurnSeqError as exc:
            raise StaleTurnEventError(str(exc)) from exc
        if updated is None:
            # 同另外两处：`assert` 在 `-O` 下整句被剥掉，契约会静默消失；这里显式抛。
            raise ActionContractError(
                f"Session '{clean_sid}' disappeared from the store while transitioning to '{target}'."
            )
        return updated

    def reconcile_session_lifecycle(
        self,
        session_id: str,
        *,
        agent_kernel_id: str = "claude",
        origin: str = "terminal",
        is_alive: bool | None = None,
        last_activity_ts: float | None = None,
        observed_error: str | None = None,
        observed_terminal_state: str | None = None,
        waiting_reason: str | None = None,
        observed_active: bool = False,
        turn_seq: int | None = None,
        stale_after_seconds: float = ZOMBIE_IDLE_TIMEOUT_SECONDS,
        now_ts: float | None = None,
        persist: bool = True,
    ) -> SessionOntologyRecord | None:
        """Reconcile a session's ontology five-state lifecycle against live liveness & transcript signals.

        Rules enforced:
        1. Late events with ``turn_seq < rec.turn_seq`` NEVER downgrade an active turn.
        2. Authoritative ``observed_error`` NEVER collapses into ``completed``; if a session
           was previously mis-folded as ``completed`` (or stuck ``running``), it heals to ``error``.
        3. Disconnected sessions (``is_alive is False``) stuck in ``running`` or ``queued`` beyond
           ``stale_after_seconds`` (default 6h) converge to ``error`` (if error observed) or
           ``completed`` — eliminating >6h zombie ``running`` sessions. ``awaiting_input`` is NEVER
           auto-completed below ``ZOMBIE_IDLE_TIMEOUT_SECONDS`` (6h).
        """
        clean_sid = str(session_id or "").strip()
        if not clean_sid:
            return None

        rec = self._store.get(clean_sid)
        if rec is None:
            if not persist:
                return None
            rec = self.ensure_managed_session(
                clean_sid,
                agent_kernel_id=agent_kernel_id,
                origin=origin,
                initial_state="running" if is_alive else "completed",
            )

        if turn_seq is not None and int(turn_seq) < int(rec.turn_seq):
            logger.warning(
                "reconcile_session_lifecycle dropped stale event for %s (event_turn_seq=%s < current=%s)",
                clean_sid,
                turn_seq,
                rec.turn_seq,
            )
            return rec

        now = float(now_ts if now_ts is not None else time.time())
        ref_ts = float(last_activity_ts if last_activity_ts is not None else rec.updated_at or rec.created_at)
        age = max(0.0, now - ref_ts)
        current = rec.lifecycle_state
        target = current
        new_summary = rec.summary
        new_waiting_reason = rec.waiting_reason

        clean_error = str(observed_error).strip() if observed_error else ""
        clean_obs_terminal = (
            normalize_session_lifecycle_state(observed_terminal_state)
            if observed_terminal_state
            else None
        )
        # awaiting_input 绝不纳入僵尸自动结案集合：无论等待多久都保持 awaiting_input，
        # 绝不能被 6 小时超时洗白为 completed。
        zombie_states = {"running", "queued"}

        if observed_active and not clean_error:
            # Active turn observed (e.g., new user prompt / tool call / live runner) supersedes
            # any stale error/completed state from a previous turn.
            target = "running"
            new_waiting_reason = None
            if current == "error":
                new_summary = ""
        elif current == "cancelled":
            # 人工取消（cancelled）为受保护终态：非新一轮活跃重启时，旧轮次的报错或终态观测信号
            # 绝不可将其覆写为 error / completed / awaiting_input。
            target = "cancelled"
        elif clean_error:
            # Error MUST remain explicitly exposed and NEVER folded into completed
            if is_alive is not True or current in {"running", "queued", "completed"}:
                target = "error"
                new_summary = clean_error[:500]
                new_waiting_reason = None
        elif clean_obs_terminal in TERMINAL_STATES:
            if current == "error" and clean_obs_terminal == "completed":
                target = "error"
            elif is_alive is not True:
                target = clean_obs_terminal
                new_waiting_reason = None
        elif clean_obs_terminal == "awaiting_input":
            if current == "error":
                target = "error"
            elif is_alive is not True or current in {"running", "queued", "awaiting_input"}:
                target = "awaiting_input"
                if waiting_reason is not None:
                    new_waiting_reason = waiting_reason
        elif current in zombie_states and is_alive is False and age >= float(stale_after_seconds):
            target = "completed"
            new_waiting_reason = None
        elif current in zombie_states and is_alive is None and age >= float(stale_after_seconds):
            # When caller has no live signal and inactivity exceeded stale threshold, converge zombie sessions
            target = "completed"
            new_waiting_reason = None

        if (
            target != current
            or new_summary != rec.summary
            or new_waiting_reason != rec.waiting_reason
        ):
            if not persist:
                rec.lifecycle_state = target
                rec.summary = new_summary
                rec.waiting_reason = new_waiting_reason
                return rec
            try:
                updated = self._store.update_lifecycle_state(
                    clean_sid,
                    target,
                    waiting_reason=new_waiting_reason if new_waiting_reason != rec.waiting_reason else None,
                    summary=new_summary if new_summary != rec.summary else None,
                    expected_turn_seq=turn_seq,
                )
                return updated or rec
            except StaleTurnSeqError:
                return self._store.get(clean_sid) or rec
        return rec

    def list_sessions_by_employee(self, member_post_id: str) -> list[SessionOntologyRecord]:
        """Return sessions explicitly bound to ``member_post_id`` in the ontology store."""
        clean_post = str(member_post_id or "").strip()
        if not clean_post:
            return []
        return [
            rec
            for rec in self._store.list_all()
            if rec.employee_id == clean_post
            or rec.extra.get("employee_id") == clean_post
        ]

    # ──────────────────────────────────────────────────────────────────────────
    # Projection & Graph Discovery & Defensive Admission
    # ──────────────────────────────────────────────────────────────────────────

    def ensure_managed_session(
        self,
        session_id: str,
        *,
        agent_kernel_id: str = "claude",
        origin: str = "terminal",
        initial_state: str = "running",
    ) -> SessionOntologyRecord:
        """保证会话被纳入 SessionOntologyStore 纳管。

        若 session_id 已存在，直接返回其本体记录；
        若尚不存在（存量历史会话或外部 CLI 直接拉起的会话），经本体登记在册的显式动作
        :meth:`adopt_existing_session` 补档，防止流式推进时因找不到实体而抛出未捕获的
        ActionContractError 导致后台线程崩溃。

        这里从前是自己拼一条 ``SessionOntologyRecord`` 直接落库的——绕过了契约，本体里
        于是多出一批来历没经过审计的记录。现在补档这件事本身也是一个本体动作，前置条件
        写在 ``frago.json`` 里（不在册才可补档、不许借补档编造父子关系）。
        """
        clean_sid = str(session_id or "").strip()
        rec = self._store.get(clean_sid)
        if rec is not None:
            return rec

        return self.adopt_existing_session(
            session_id=clean_sid,
            agent_kernel_id=agent_kernel_id,
            origin=origin,
            initial_state=initial_state,
            already_registered=False,
        )

    def get_session(self, session_id: str) -> SessionOntologyRecord | None:
        return self._store.get(session_id)

    def get_session_process(self, session_id: str) -> AgentSessionProcess | None:
        """Return the AgentSessionProcess entity node from the session ontology projection."""
        rec = self.get_session(session_id)
        if rec is None:
            return None
        return self.project_session(session_id).session_process

    def list_sessions(self) -> list[SessionOntologyRecord]:
        return self._store.list_all()

    def project_session(
        self,
        session_id: str,
        *,
        raw_steps: Sequence[Mapping[str, Any]] = (),
        graph: OntologyGraph | None = None,
    ) -> SessionProcessProjection:
        """Project a persisted session record into its complete 5-part ontology graph."""
        rec = self.get_session(session_id)
        if rec is None:
            raise ActionContractError(f"Session '{session_id}' not found in store.")

        raw_dict = {
            "session_id": rec.session_id,
            "agent_type": rec.agent_kernel,
            "status": rec.lifecycle_state,
            "source": rec.origin,
            "source_file": rec.transcript_uri,
        }
        return project_session_process_dict(
            raw_dict,
            raw_steps=raw_steps,
            is_worker=rec.is_worker,
            registry=self._registry,
            graph=graph,
        )

    def build_sessions_graph(self) -> OntologyGraph:
        """Project all stored sessions into an aggregate `OntologyGraph` for cross-session reasoning."""
        g = OntologyGraph()
        for rec in self.list_sessions():
            try:
                self.project_session(rec.session_id, graph=g)
            except Exception:
                logger.debug("Skipping invalid session projection for %s", rec.session_id, exc_info=True)
        return g


_DEFAULT_SESSION_SERVICE = SessionOntologyService()


def get_default_session_service() -> SessionOntologyService:
    return _DEFAULT_SESSION_SERVICE


SHORT_SETTLED_GRACE_SECONDS = 60.0
DISCONNECT_CRASH_GRACE_SECONDS = 300.0
IN_PROGRESS_TRANSCRIPT_KINDS: frozenset[str] = frozenset(
    {"tool.call", "tool.result", "subagent.dispatch", "user.say", "agent.think"}
)


def can_write_ontology_store(svc: SessionOntologyService | None = None) -> bool:
    """Return True when writing to ``svc.store`` is safe (respecting pytest home protection)."""
    from frago.session.store import DEFAULT_SESSION_STORE_PATH

    target = svc if svc is not None else get_default_session_service()
    store_path = getattr(getattr(target, "store", None), "store_path", None)
    return (
        store_path != DEFAULT_SESSION_STORE_PATH
        or not os.environ.get("PYTEST_CURRENT_TEST")
    )


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil

        if not psutil.pid_exists(pid):
            return False
        with contextlib.suppress(psutil.Error, OSError):
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return False
        return True
    except ImportError:
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except OSError:
            return False


def _parse_iso_epoch(value: Any) -> float | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


@dataclass
class LiveRuntimeProbes:
    """Cross-process physical runtime liveness snapshot (drive PIDs, core markers, async_dispatch)."""

    live_drive_pids: set[str] = field(default_factory=set)
    live_drive_tmux: dict[str, str] = field(default_factory=dict)
    live_core_markers: set[str] = field(default_factory=set)
    live_dispatch_targets: set[str] = field(default_factory=set)
    latest_dispatch_by_target: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluatedSessionState:
    """Converged read-side session status + ontology lifecycle + optional heal directive."""

    ui_status: str
    lifecycle_state: str
    physically_alive: bool
    actively_running: bool
    heal_target: str | None = None
    heal_summary: str | None = None
    heal_waiting_reason: str | None = None
    tool_aborted: bool = False


_AGENT_PROCESS_NAMES: frozenset[str] = frozenset(
    {"frago", "frago-core", "coreagent", "claude", "codex", "opencode", "agy", "tmux"}
)


def _probe_pid_process_info(pid: int) -> tuple[str | None, float | None]:
    """Return ``(cmdline, create_time_epoch)`` for a live PID, or ``(None, None)``."""
    if pid <= 0:
        return None, None
    cmdline: str | None = None
    create_time: float | None = None
    with contextlib.suppress(Exception):
        import psutil

        if not psutil.pid_exists(pid):
            return None, None
        proc = psutil.Process(pid)
        if proc.status() == psutil.STATUS_ZOMBIE:
            return None, None
        create_time = float(proc.create_time())
        parts = proc.cmdline()
        joined = " ".join(parts).strip() if parts else ""
        if joined:
            cmdline = joined

    if cmdline is None:
        with contextlib.suppress(Exception):
            res = subprocess.run(
                ["ps", "-o", "command=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                cmdline = res.stdout.strip()

    if cmdline is not None and create_time is None:
        with contextlib.suppress(Exception):
            res = subprocess.run(
                ["ps", "-o", "lstart=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                dt = datetime.strptime(" ".join(res.stdout.split()), "%a %b %d %H:%M:%S %Y")
                create_time = dt.timestamp()

    return cmdline, create_time


def _is_agent_process_cmdline(cmdline: str) -> bool:
    """Return True iff *cmdline* belongs to a frago / agent / tmux runtime process."""
    raw = str(cmdline or "").strip()
    if not raw:
        return False
    head = raw.split(" -", 1)[0].strip()
    head_exe = Path(head).name.lower() if head else ""
    try:
        tokens = shlex.split(raw)
    except ValueError:
        tokens = raw.split()
    if not tokens:
        return False
    tok0_exe = Path(tokens[0]).name.lower()

    if head_exe in _AGENT_PROCESS_NAMES or tok0_exe in _AGENT_PROCESS_NAMES:
        return True

    is_python = head_exe.startswith("python") or tok0_exe.startswith("python")
    is_wrapper = is_python or tok0_exe in {"uv", "node", "env", "bash", "sh", "zsh"}
    if is_wrapper:
        for tok in tokens[1:]:
            tok_name = Path(tok).name.lower()
            if tok_name in _AGENT_PROCESS_NAMES:
                return True
            if is_python and (
                tok.lower() == "frago"
                or tok.lower().startswith("frago.")
                or "/frago/" in tok.lower()
                or "\\frago\\" in tok.lower()
            ):
                return True
        if is_python and "-m frago" in raw.lower():
            return True

    return False


def _is_valid_drive_pid_owner(
    pid: int,
    data: Mapping[str, Any],
    *,
    file_mtime: float | None = None,
) -> bool:
    """Verify *pid* is alive, belongs to an agent/frago process, and is not OS-reused."""
    if not isinstance(pid, int) or pid <= 0 or not _pid_is_alive(pid):
        return False
    cmdline, live_ctime = _probe_pid_process_info(pid)
    if not cmdline or not _is_agent_process_cmdline(cmdline):
        return False

    recorded_ctime = data.get("proc_create_time")
    if isinstance(recorded_ctime, int | float) and float(recorded_ctime) > 0:
        if live_ctime is not None and abs(float(live_ctime) - float(recorded_ctime)) > 5.0:
            return False
    else:
        reg_at = data.get("registered_at")
        ref_ts = (
            float(reg_at)
            if isinstance(reg_at, int | float) and float(reg_at) > 0
            else file_mtime
        )
        if (
            ref_ts is not None
            and ref_ts > 0
            and live_ctime is not None
            and float(live_ctime) > float(ref_ts) + 60.0
        ):
            return False

    return True


def collect_live_runtime_probes(
    *,
    live_tmux_ids: set[str] | None = None,
    core_alive: Mapping[str, bool] | None = None,
    now_s: float | None = None,
) -> LiveRuntimeProbes:
    """Collect cross-process runtime probes across drive registry, coreagent markers, and async_dispatch."""
    probes = LiveRuntimeProbes()
    cur_now = float(now_s if now_s is not None else time.time())

    # 1. Transient drive entries (~/.frago/drive/*.json)
    with contextlib.suppress(Exception):
        from frago.employee.store import frago_home

        drive_dir = frago_home() / "drive"
        if drive_dir.is_dir():
            for path in drive_dir.glob("*.json"):
                with contextlib.suppress(Exception):
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        continue
                    sid = str(data.get("session_id") or data.get("name") or path.stem).strip()
                    if not sid:
                        continue
                    file_mtime: float | None = None
                    with contextlib.suppress(OSError):
                        file_mtime = path.stat().st_mtime
                    pid = data.get("pid")
                    if isinstance(pid, int) and _is_valid_drive_pid_owner(
                        pid, data, file_mtime=file_mtime
                    ):
                        probes.live_drive_pids.add(sid)
                        if path.stem and path.stem != sid:
                            probes.live_drive_pids.add(path.stem)
                    tmux_name = str(data.get("tmux_name") or "").strip()
                    if tmux_name:
                        tmux_sid = (
                            tmux_name[len("frago-agent-") :]
                            if tmux_name.startswith("frago-agent-")
                            else sid
                        )
                        if (
                            live_tmux_ids is None
                            or tmux_sid in live_tmux_ids
                            or sid in live_tmux_ids
                        ):
                            probes.live_drive_tmux[sid] = tmux_name

    # 2. CoreAgent active pane markers (~/.frago/coreagent/panes/*.active_run)
    with contextlib.suppress(Exception):
        from frago.agent_driver.coreagent_pane_host import panes_dir

        pdir = panes_dir()
        if pdir.is_dir():
            for marker in pdir.glob("*.active_run"):
                with contextlib.suppress(Exception):
                    run_str = marker.read_text(encoding="utf-8", errors="replace").strip()
                    if not run_str:
                        continue
                    run_dir = Path(run_str)
                    if (
                        not run_dir.is_dir()
                        or (run_dir / "exit.code").is_file()
                        or (run_dir / "superseded").is_file()
                    ):
                        continue
                    pid_file = run_dir / "core.pid"
                    if not pid_file.is_file():
                        continue
                    pid = int(pid_file.read_text(encoding="utf-8").strip())
                    if not _pid_is_alive(pid):
                        continue
                    probes.live_core_markers.add(marker.stem)
                    launch_file = run_dir / "launch.json"
                    if launch_file.is_file():
                        launch = json.loads(launch_file.read_text(encoding="utf-8"))
                        if isinstance(launch, dict):
                            lsid = str(launch.get("session_id") or "").strip()
                            if lsid:
                                probes.live_core_markers.add(lsid)

    # 3. Async dispatch ledger (~/.frago/sessions/async_dispatches/*.json)
    with contextlib.suppress(Exception):
        from frago.session.async_dispatch import list_dispatch_jobs

        best_key: dict[str, tuple[int, float, float]] = {}
        for job in list_dispatch_jobs(active_only=False):
            tid = str(getattr(job, "target_session_id", "") or "").strip()
            if not tid:
                continue
            rank = (
                int(getattr(job, "turn_seq", 0) or 0),
                _parse_iso_epoch(getattr(job, "updated_at", None)) or 0.0,
                _parse_iso_epoch(getattr(job, "created_at", None)) or 0.0,
            )
            prev = best_key.get(tid)
            if prev is None or rank >= prev:
                best_key[tid] = rank
                probes.latest_dispatch_by_target[tid] = job

            st = str(getattr(job, "status", "") or "").strip().lower()
            if st in ("pending", "running"):
                wpid = getattr(job, "watcher_pid", None)
                created_s = _parse_iso_epoch(getattr(job, "created_at", None))
                watcher_alive = isinstance(wpid, int) and wpid > 0 and _pid_is_alive(wpid)
                within_grace = (
                    created_s is not None
                    and (cur_now - created_s) <= SHORT_SETTLED_GRACE_SECONDS
                )
                target_alive = (
                    (live_tmux_ids is not None and tid in live_tmux_ids)
                    or (core_alive is not None and tid in core_alive)
                    or (tid in probes.live_drive_pids)
                    or (tid in probes.live_core_markers)
                )
                if watcher_alive or within_grace or target_alive:
                    probes.live_dispatch_targets.add(tid)

    return probes


def _normalize_transcript_kind(last_kind: str | None) -> str | None:
    if not last_kind:
        return None
    mapping = {
        "assistant_text": "agent.say",
        "turn_end": "agent.say",
        "assistant_tool": "tool.call",
        "assistant_think": "agent.think",
        "user": "user.say",
    }
    clean = str(last_kind).strip()
    return mapping.get(clean, clean)


def evaluate_session_liveness_and_state(
    *,
    session_id: str,
    onto_rec: SessionOntologyRecord | None,
    card_status: str,
    last_kind: str | None,
    last_active_s: float,
    last_reply_s: float | None = None,
    digest_stuck: str | None = None,
    in_tmux: bool = False,
    liveness_flag: bool | None = None,
    core_alive: Mapping[str, bool] | None = None,
    probes: LiveRuntimeProbes | None = None,
    now_s: float | None = None,
    collapse_unmanaged_dead: bool = True,
) -> EvaluatedSessionState:
    """Shared 6-precondition read-side evaluator (60s settled / 300s mid-turn crash / 21600s zombie).

    Enforces:
    1. Source state for 60s/300s self-heal is ONLY ``running`` or ``queued`` (NEVER ``awaiting_input``).
    2. Full physical offline check (tmux, coreagent resident pool, drive PID, core marker, live dispatch).
    3. 60s race-window floor from ``max(last_active_s, onto_updated_s)``.
    4. Settled evidence (``agent.say``/``done``/``idle``/``error`` or settled dispatch job) vs
       mid-turn crash (``IN_PROGRESS_TRANSCRIPT_KINDS`` waits 300s then heals to ``error``).
    5. Error fidelity (error signals MUST become ``error``, ``needs_input`` -> ``awaiting_input``).
    6. 21600s (6h) ultimate fallback for zombie ``running``/``queued`` (collapsing mid-turn tool aborts
       to ``error``; ``awaiting_input`` NEVER washes out to ``completed``).
    """
    now = float(now_s if now_s is not None else time.time())
    norm_kind = _normalize_transcript_kind(last_kind)
    norm_card_status = str(card_status or "idle").strip().lower()

    is_core_busy = core_alive is not None and core_alive.get(session_id) is True
    is_core_resident = core_alive is not None and session_id in core_alive
    has_drive_pid = probes is not None and session_id in probes.live_drive_pids
    has_drive_tmux = probes is not None and session_id in probes.live_drive_tmux
    has_core_marker = probes is not None and session_id in probes.live_core_markers
    has_live_dispatch = probes is not None and session_id in probes.live_dispatch_targets

    physically_alive = bool(
        in_tmux
        or liveness_flag is True
        or is_core_resident
        or has_drive_pid
        or has_drive_tmux
        or has_core_marker
        or has_live_dispatch
    )
    actively_running = bool(
        in_tmux
        or liveness_flag is True
        or is_core_busy
        or has_drive_pid
        or has_drive_tmux
        or has_core_marker
        or has_live_dispatch
    )

    onto_state = (
        str(getattr(onto_rec, "lifecycle_state", "") or "").strip().lower()
        if onto_rec is not None
        else None
    )
    onto_updated_s = (
        float(getattr(onto_rec, "updated_at", 0) or 0) if onto_rec is not None else 0.0
    )
    onto_turn_seq = (
        int(getattr(onto_rec, "turn_seq", 0) or 0) if onto_rec is not None else 0
    )

    has_fresh_onto_turn = (
        onto_rec is not None
        and onto_state == "running"
        and onto_turn_seq > 0
        and onto_updated_s > last_active_s + 1.0
    )
    fresh_onto_turn = has_fresh_onto_turn and (
        actively_running
        or (
            liveness_flag is None
            and probes is None
            and (now - onto_updated_s) < float(ZOMBIE_IDLE_TIMEOUT_SECONDS)
        )
        or (
            liveness_flag is None
            and (now - onto_updated_s) < SHORT_SETTLED_GRACE_SECONDS
        )
    )
    can_reopen_terminal_onto = is_core_busy or has_live_dispatch
    is_transcript_running = (
        actively_running
        and norm_kind != "error"
        and (
            (onto_state not in {"completed", "cancelled"} or can_reopen_terminal_onto)
            and (
                norm_kind in IN_PROGRESS_TRANSCRIPT_KINDS
                or (
                    onto_state not in {"completed", "cancelled", "awaiting_input"}
                    and norm_kind != "agent.say"
                    and norm_card_status == "running"
                )
            )
        )
    )
    resumed_newer_transcript = (
        onto_rec is not None
        and onto_state == "error"
        and norm_card_status == "running"
        and norm_kind in IN_PROGRESS_TRANSCRIPT_KINDS
        and liveness_flag is not False
        and last_active_s > onto_updated_s + 2.0
        and (now - last_active_s) < DISCONNECT_CRASH_GRACE_SECONDS
    )

    if is_core_busy or fresh_onto_turn or is_transcript_running or resumed_newer_transcript:
        return EvaluatedSessionState(
            ui_status="running",
            lifecycle_state="running",
            physically_alive=physically_alive,
            actively_running=actively_running or resumed_newer_transcript,
            heal_target="running" if onto_state == "error" else None,
            heal_summary="" if onto_state == "error" else None,
        )

    if (
        onto_rec is not None
        and onto_state == "error"
        and norm_card_status != "error"
        and norm_kind == "agent.say"
        and last_reply_s is not None
        and last_reply_s > onto_updated_s + 5.0
    ):
        return EvaluatedSessionState(
            ui_status="done" if norm_card_status == "running" else norm_card_status,
            lifecycle_state="completed",
            physically_alive=physically_alive,
            actively_running=actively_running,
            heal_target="completed",
            heal_summary="",
        )

    # 人工取消（cancelled）为受保护终态：除非前面已由真实活跃轮次重开（is_core_busy / has_live_dispatch），
    # 否则任何旧卡片/转录的 error、tool_abort 或 idle 信号都绝不可将其改判为 error，
    # 更严禁生成 heal_target 覆写持久化本体存储。
    if onto_state == "cancelled":
        ui = (
            "done"
            if norm_kind == "agent.say"
            else (
                norm_card_status
                if norm_card_status in {"done", "idle"}
                else "idle"
            )
        )
        return EvaluatedSessionState(
            ui_status=ui,
            lifecycle_state="cancelled",
            physically_alive=physically_alive,
            actively_running=False,
            heal_target=None,
            tool_aborted=False,
        )

    if (
        norm_kind == "error"
        or (norm_card_status == "error" and onto_state != "awaiting_input")
    ):
        should_heal_error = (
            onto_rec is not None
            and onto_state not in {"error", "cancelled"}
            and not (liveness_flag is None and has_fresh_onto_turn)
        )
        is_mid_turn_abort = norm_kind in IN_PROGRESS_TRANSCRIPT_KINDS or (
            onto_rec is not None
            and str(getattr(onto_rec, "summary", "") or "").strip() == "process_terminated_mid_turn"
        )
        return EvaluatedSessionState(
            ui_status="error",
            lifecycle_state="error",
            physically_alive=physically_alive,
            actively_running=actively_running,
            heal_target="error" if should_heal_error else None,
            heal_summary=(
                ("process_terminated_mid_turn" if is_mid_turn_abort else (digest_stuck or "session_error"))
                if should_heal_error
                else None
            ),
            tool_aborted=is_mid_turn_abort,
        )

    if onto_state == "error":
        onto_summary = str(getattr(onto_rec, "summary", "") or "").strip()
        is_mid_turn_abort = (
            norm_kind in IN_PROGRESS_TRANSCRIPT_KINDS
            or onto_summary == "process_terminated_mid_turn"
        )
        return EvaluatedSessionState(
            ui_status="error",
            lifecycle_state="error",
            physically_alive=physically_alive,
            actively_running=actively_running,
            tool_aborted=is_mid_turn_abort,
        )

    ref_ts = (
        max(last_active_s, onto_updated_s)
        if onto_rec is not None and onto_updated_s > 0
        else last_active_s
    )
    age_s = max(0.0, now - ref_ts)
    activity_age_s = max(0.0, now - last_active_s)

    latest_job = probes.latest_dispatch_by_target.get(session_id) if probes is not None else None
    job_turn = int(getattr(latest_job, "turn_seq", 0) or 0) if latest_job is not None else 0
    job_matches = latest_job is not None and (onto_rec is None or job_turn >= onto_turn_seq)
    job_status = str(getattr(latest_job, "status", "") or "").strip().lower() if job_matches else ""
    job_settled = job_status in {"completed", "failed", "superseded", "cancelled"}
    job_exit_code = int(getattr(latest_job, "exit_code", 0) or 0) if job_matches else 0
    job_error = str(getattr(latest_job, "error", "") or "").strip() if job_matches else ""

    if onto_state in {"completed", "cancelled"}:
        # 存量自愈（仅针对 completed，绝不覆盖人工 cancelled）：
        # 1. 存量工具/中间态中途退场被旧 90s/6h 逻辑误写成 completed：末帧停在未闭合中间态、
        #    进程已离线、其后无更新的 agent.say 结案回复且无已成功派发单，纠偏为 error。
        if (
            onto_state == "completed"
            and not physically_alive
            and norm_kind in IN_PROGRESS_TRANSCRIPT_KINDS
            and not (job_settled and job_status == "completed")
            and (last_reply_s is None or last_active_s > last_reply_s + 1.0)
            and (liveness_flag is False or activity_age_s >= DISCONNECT_CRASH_GRACE_SECONDS)
        ):
            return EvaluatedSessionState(
                ui_status="error",
                lifecycle_state="error",
                physically_alive=False,
                actively_running=False,
                heal_target="error",
                heal_summary="process_terminated_mid_turn",
                tool_aborted=True,
            )
        # 2. 存量 awaiting_input 被旧 6h 逻辑误洗白成 completed：底层仍为 awaiting_input
        #    且其后无更新的完成回复时安全恢复为 awaiting_input（绝不误伤后续已结案会话）。
        if (
            onto_state == "completed"
            and not physically_alive
            and norm_card_status == "awaiting_input"
            and (last_reply_s is None or last_reply_s <= onto_updated_s + 5.0)
        ):
            return EvaluatedSessionState(
                ui_status="idle",
                lifecycle_state="awaiting_input",
                physically_alive=False,
                actively_running=False,
                heal_target="awaiting_input",
            )
        ui = (
            ("done" if norm_kind == "agent.say" else "idle")
            if norm_card_status == "running"
            else norm_card_status
        )
        return EvaluatedSessionState(
            ui_status=ui,
            lifecycle_state=onto_state,
            physically_alive=physically_alive,
            actively_running=False,
        )

    transcript_settled = (norm_kind not in IN_PROGRESS_TRANSCRIPT_KINDS) and (
        norm_kind in ("agent.say", "error")
        or norm_card_status in ("done", "idle", "completed", "error")
    )
    onto_is_worker = bool(
        onto_rec is not None
        and (
            bool(getattr(onto_rec, "is_worker", False))
            or str(getattr(onto_rec, "origin", "") or "").strip().lower() == "worker"
        )
    )
    missing_transcript_crashed = (
        norm_kind is None
        and not transcript_settled
        and not job_settled
        and (liveness_flag is False or (onto_is_worker and probes is not None))
    )
    in_progress_crashed = (
        (norm_kind in IN_PROGRESS_TRANSCRIPT_KINDS) or missing_transcript_crashed
    ) and not job_settled

    # Case A: onto in running/queued (or unmanaged running)
    if onto_state in {"running", "queued"} or (onto_rec is None and norm_card_status == "running"):
        if not physically_alive:
            if age_s >= SHORT_SETTLED_GRACE_SECONDS and (transcript_settled or job_settled):
                if job_status == "failed" or (job_settled and job_exit_code != 0):
                    if "needs_input" in job_error.lower() or job_exit_code == 2:
                        return EvaluatedSessionState(
                            ui_status="done" if norm_kind == "agent.say" else "idle",
                            lifecycle_state="awaiting_input",
                            physically_alive=False,
                            actively_running=False,
                            heal_target="awaiting_input" if onto_rec is not None else None,
                            heal_waiting_reason="needs_input" if onto_rec is not None else None,
                        )
                    return EvaluatedSessionState(
                        ui_status="error",
                        lifecycle_state="error",
                        physically_alive=False,
                        actively_running=False,
                        heal_target="error" if onto_rec is not None else None,
                        heal_summary=(job_error or "dispatch_failed")[:500]
                        if onto_rec is not None
                        else None,
                        tool_aborted=norm_kind in IN_PROGRESS_TRANSCRIPT_KINDS,
                    )
                return EvaluatedSessionState(
                    ui_status="done" if norm_kind == "agent.say" else "idle",
                    lifecycle_state="completed",
                    physically_alive=False,
                    actively_running=False,
                    heal_target="completed" if onto_rec is not None else None,
                    heal_summary="" if onto_rec is not None else None,
                )

            if in_progress_crashed and age_s >= DISCONNECT_CRASH_GRACE_SECONDS:
                return EvaluatedSessionState(
                    ui_status="error",
                    lifecycle_state="error",
                    physically_alive=False,
                    actively_running=False,
                    heal_target="error" if onto_rec is not None else None,
                    heal_summary="process_terminated_mid_turn" if onto_rec is not None else None,
                    tool_aborted=True,
                )

            if activity_age_s >= float(ZOMBIE_IDLE_TIMEOUT_SECONDS):
                if in_progress_crashed or norm_kind in IN_PROGRESS_TRANSCRIPT_KINDS:
                    return EvaluatedSessionState(
                        ui_status="error",
                        lifecycle_state="error",
                        physically_alive=False,
                        actively_running=False,
                        heal_target="error" if onto_rec is not None else None,
                        heal_summary="process_terminated_mid_turn" if onto_rec is not None else None,
                        tool_aborted=True,
                    )
                return EvaluatedSessionState(
                    ui_status="done" if norm_kind == "agent.say" else "idle",
                    lifecycle_state="completed",
                    physically_alive=False,
                    actively_running=False,
                    heal_target="completed" if onto_rec is not None else None,
                )

            # Unmanaged dead running cards in workbench/usage (when collapse_unmanaged_dead is True)
            if onto_rec is None and collapse_unmanaged_dead and norm_card_status == "running":
                if norm_kind in IN_PROGRESS_TRANSCRIPT_KINDS:
                    return EvaluatedSessionState(
                        ui_status="error",
                        lifecycle_state="error",
                        physically_alive=False,
                        actively_running=False,
                        tool_aborted=True,
                    )
                return EvaluatedSessionState(
                    ui_status="done" if norm_kind == "agent.say" else "idle",
                    lifecycle_state="completed",
                    physically_alive=False,
                    actively_running=False,
                )

        if onto_state == "running":
            return EvaluatedSessionState(
                ui_status="running",
                lifecycle_state="running",
                physically_alive=physically_alive,
                actively_running=actively_running,
            )
        if onto_state == "queued":
            return EvaluatedSessionState(
                ui_status=norm_card_status,
                lifecycle_state="queued",
                physically_alive=physically_alive,
                actively_running=actively_running,
            )
        return EvaluatedSessionState(
            ui_status=norm_card_status,
            lifecycle_state="running" if norm_card_status == "running" else "completed",
            physically_alive=physically_alive,
            actively_running=actively_running,
        )

    # Case B: onto in awaiting_input (NEVER self-heal or wash out to completed regardless of age)
    if onto_state == "awaiting_input":
        ui = (
            ("done" if norm_kind == "agent.say" else "idle")
            if norm_card_status == "running"
            else norm_card_status
        )
        return EvaluatedSessionState(
            ui_status=ui,
            lifecycle_state="awaiting_input",
            physically_alive=physically_alive,
            actively_running=actively_running,
        )

    # Case C: unmanaged non-running card
    if not physically_alive and norm_card_status == "running" and collapse_unmanaged_dead:
        if norm_kind in IN_PROGRESS_TRANSCRIPT_KINDS:
            return EvaluatedSessionState(
                ui_status="error",
                lifecycle_state="error",
                physically_alive=False,
                actively_running=False,
                tool_aborted=True,
            )
        return EvaluatedSessionState(
            ui_status="done" if norm_kind == "agent.say" else "idle",
            lifecycle_state="completed",
            physically_alive=False,
            actively_running=False,
        )

    # Unmanaged dead mid-turn abort (e.g., card_status=idle with last_kind=tool.call) MUST NOT
    # fall back to lifecycle_state="completed".
    if (
        onto_rec is None
        and not physically_alive
        and norm_kind in IN_PROGRESS_TRANSCRIPT_KINDS
        and not (job_settled and job_status == "completed")
        and (liveness_flag is False or activity_age_s >= DISCONNECT_CRASH_GRACE_SECONDS)
    ):
        return EvaluatedSessionState(
            ui_status="error",
            lifecycle_state="error",
            physically_alive=False,
            actively_running=False,
            tool_aborted=True,
        )

    if norm_card_status == "awaiting_input":
        return EvaluatedSessionState(
            ui_status="idle",
            lifecycle_state="awaiting_input",
            physically_alive=physically_alive,
            actively_running=actively_running,
        )

    fallback_lifecycle = (
        onto_state
        or (
            norm_card_status
            if norm_card_status in {"running", "queued", "cancelled", "error"}
            else "completed"
        )
    )
    return EvaluatedSessionState(
        ui_status=norm_card_status,
        lifecycle_state=fallback_lifecycle,
        physically_alive=physically_alive,
        actively_running=actively_running,
    )
