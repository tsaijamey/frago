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

import logging
from collections.abc import Mapping, Sequence
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
    get_default_session_store,
)

logger = logging.getLogger(__name__)

TERMINAL_STATES: frozenset[str] = frozenset({"completed", "error", "cancelled"})

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

        rec = SessionOntologyRecord(
            session_id=clean_sid,
            agent_kernel=clean_kernel,
            origin=normalized_origin,
            lifecycle_state="running",
            is_worker=is_worker,
            parent_session_id=parent_session_id,
            relation_kind=clean_relation,
            cwd=cwd,
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
    # State Machine Transition Guard
    # ──────────────────────────────────────────────────────────────────────────

    def transition_state(
        self,
        session_id: str,
        target_state: str,
        *,
        reason: str | None = None,
        summary: str | None = None,
        allow_resume: bool = False,
    ) -> SessionOntologyRecord:
        """Enforce strict state machine transitions across session lifecycle."""
        clean_sid = str(session_id or "").strip()
        rec = self._store.get(clean_sid)
        if rec is None:
            raise ActionContractError(f"Session '{clean_sid}' not found.")

        current = rec.lifecycle_state
        target = normalize_session_lifecycle_state(target_state)

        # Illegal backward transition: terminal -> active without explicit allow_resume
        if current in TERMINAL_STATES and target not in TERMINAL_STATES and not allow_resume:
            raise ActionContractError(
                f"Illegal state machine transition: session '{clean_sid}' cannot jump backward "
                f"from terminal state '{current}' to '{target}' without explicit resume."
            )

        updated = self._store.update_lifecycle_state(
            clean_sid,
            target,
            waiting_reason=reason,
            summary=summary,
        )
        if updated is None:
            # 同另外两处：`assert` 在 `-O` 下整句被剥掉，契约会静默消失；这里显式抛。
            raise ActionContractError(
                f"Session '{clean_sid}' disappeared from the store while transitioning to '{target}'."
            )
        return updated

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
