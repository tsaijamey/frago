"""frago employee — ontology-backed service connecting `store.py` with `frago.ontology`.

Provides the three standard domain ontology operations:
1. **知道 (Discovery)**: Project all persisted employee posts into an `OntologyGraph`
   and query via `SparqlQuery` / `DomainEmployeeRuntime` which employee governs a
   given `KnowledgeDomain`, `RecipeModule`, `DataSlot`, or `ScheduleRuleSpec`.
2. **对接 (Binding & Reassignment)**: Establish (`hire`) or update (`bind_territory`,
   `reassign_kernel`) an `EmployeePostResource` (+R) and its `DomainEmployeeRole` (~R),
   validating through `project_employee_post_dict` (Gate 2) before persisting (Gate 4).
3. **调用 (Contract-Guarded Invocation & Governance)**: Execute `invoke` (guarded by
   `invoke_domain_employee` kinetic contract) and `govern` (guarded by
   `govern_employee_domain_assets` kinetic contract).

Layer: domain service — imports `frago.employee.store` and `frago.ontology`,
NEVER imports `frago.server` or `frago.cli`.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from frago.employee.avatar import (
    cleanup_avatar_file,
    default_avatar_spec,
    normalize_avatar_spec,
    read_valid_avatar_file,
    resolve_avatar_state,
    save_uploaded_avatar_file,
)
from frago.employee.store import (
    VALID_AGENT_KERNELS,
    EmployeeLedger,
    EmployeePostRecord,
    apply_resource_exclusions,
    create_data_slot_entry,
    employees_dir,
    frago_home,
    get_post,
    lift_resource_exclusions,
    list_posts,
    load_ledger,
    save_ledger,
    save_post,
    scan_data_slot_entries,
    validate_post_id,
)
from frago.ontology import (
    DEFAULT_DOMAIN_REGISTRY,
    DomainClassRegistry,
    DomainEmployeeRuntime,
    EmployeePostProjection,
    InformationEntity,
    OntologyEntity,
    OntologyGraph,
    OntologyIntrospector,
    OntologyReasoner,
    Role,
    SparqlQuery,
    TriplePattern,
    project_employee_post_dict,
)


class EmployeeOntologyService:
    """End-to-end ontology service for `EmployeePostResource` and `DomainEmployeeRole`."""

    def __init__(
        self,
        *,
        base_dir: Path | None = None,
        registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
        introspector: OntologyIntrospector | None = None,
    ) -> None:
        self._base_dir = base_dir
        self._registry = registry
        self._introspector = (
            introspector if introspector is not None else OntologyIntrospector()
        )

    def build_runtime_graph(
        self,
    ) -> tuple[DomainEmployeeRuntime, dict[str, EmployeePostProjection]]:
        """Load all persisted posts from disk and project them into a live `DomainEmployeeRuntime`."""
        graph = OntologyGraph()
        projections: dict[str, EmployeePostProjection] = {}
        for record in list_posts(base_dir=self._base_dir):
            proj = project_employee_post_dict(
                record.to_projection_dict(),
                registry=self._registry,
                graph=graph,
            )
            projections[record.member_post_id] = proj
        runtime = DomainEmployeeRuntime(
            graph=graph,
            registry=self._registry,
            introspector=self._introspector,
        )
        return runtime, projections

    def hire(
        self,
        member_post_id: str,
        *,
        title: str,
        agent_kernel: str = "claude",
        description: str = "",
        work_scope: str | None = None,
        cwd: str | None = None,
        knowledge_domains: Sequence[str] = (),
        recipes: Sequence[str] = (),
        data_slots: Sequence[str] = (),
        schedule_ids: Sequence[str] = (),
        allowed_commands: Sequence[str] | None = None,
        skills: Sequence[str] | None = None,
        color: str | None = None,
        avatar: dict[str, Any] | None = None,
    ) -> tuple[EmployeePostRecord, EmployeePostProjection]:
        """Create or update an employee post after validating its ontology shadow projection.

        ``work_scope``、``cwd``、``allowed_commands``、``skills``、``color`` 与 ``avatar`` 给 ``None`` 表示「这一栏不动」，
        沿用磁盘上已有的值：改一条领地绑定不该顺手把岗位的工作范畴、默认技能或自定义头像抹掉。
        """
        existing = get_post(member_post_id, base_dir=self._base_dir)
        record = EmployeePostRecord(
            member_post_id=member_post_id,
            title=title,
            agent_kernel=agent_kernel,
            description=description,
            work_scope=(
                work_scope
                if work_scope is not None
                else (existing.work_scope if existing else "")
            ),
            cwd=cwd if cwd is not None else (existing.cwd if existing else ""),
            knowledge_domains=list(knowledge_domains),
            recipes=list(recipes),
            data_slots=list(data_slots),
            schedule_ids=list(schedule_ids),
            active_session_ids=list(existing.active_session_ids) if existing else [],
            allowed_commands=(
                list(allowed_commands)
                if allowed_commands is not None
                else (list(existing.allowed_commands) if existing else [])
            ),
            skills=(
                list(skills)
                if skills is not None
                else (list(existing.skills) if existing else [])
            ),
            color=(
                color
                if color is not None and str(color).strip()
                else (existing.color if existing else "")
            ),
            avatar=(
                normalize_avatar_spec(avatar, member_post_id, strict=True)
                if avatar is not None
                else (dict(existing.avatar) if existing else {})
            ),
            created_at=existing.created_at if existing else "",
        )
        # Gate 2 validation before Gate 4 persistence
        proj = project_employee_post_dict(
            record.to_projection_dict(),
            registry=self._registry,
        )
        save_post(record, base_dir=self._base_dir)
        self._prune_ledger_to_post(record, previous=existing)
        self._restore_ledger_exclusions(record, previous=existing)
        # 诞生即巡检：一个新岗位刚立起来时除了「我负责什么」一无所有，这时主动把
        # ``~/.frago`` 下与职责相关的资源认领一遍，账本才有内容可注入第一场会话。
        # 失败不阻断创建：岗位本身已经落盘可用，巡检是可以补跑的一步。
        self._sync_ledger_quietly(record.member_post_id)
        # 巡检会把新认领的槽位/配方/知识域反哺回编制，返回磁盘上那一份：把创建前的快照
        # 交回去，调用方看到的是一个比磁盘旧的对象，接着拿它做判断就会漏掉刚认领的东西。
        refreshed = get_post(record.member_post_id, base_dir=self._base_dir)
        return (refreshed or record), proj

    def bind_territory(
        self,
        member_post_id: str,
        *,
        agent_kernel: str | None = None,
        work_scope: str | None = None,
        cwd: str | None = None,
        knowledge_domains: Sequence[str] = (),
        recipes: Sequence[str] = (),
        data_slots: Sequence[str] = (),
        schedule_ids: Sequence[str] = (),
        allowed_commands: Sequence[str] = (),
        skills: Sequence[str] = (),
        color: str | None = None,
    ) -> tuple[EmployeePostRecord, EmployeePostProjection]:
        """Bind additional territory assets or switch the `AgentKernel` (~R) on an existing post (+R).

        ``work_scope`` 与 ``cwd`` 只有显式给了值才覆盖：其余几栏都是「追加」，这两栏是
        「整体替换」，``None`` 与空串的区别在这里必须保住。
        """
        post_id = validate_post_id(member_post_id)
        record = get_post(post_id, base_dir=self._base_dir)
        if record is None:
            raise KeyError(f"Employee post '{post_id}' does not exist.")
        if agent_kernel is not None:
            record.agent_kernel = agent_kernel
        if work_scope is not None:
            record.work_scope = work_scope
        if cwd is not None:
            record.cwd = cwd
        if color is not None and str(color).strip():
            record.color = color
        record.knowledge_domains.extend(knowledge_domains)
        record.recipes.extend(recipes)
        record.data_slots.extend(data_slots)
        record.schedule_ids.extend(schedule_ids)
        record.allowed_commands.extend(allowed_commands)
        record.skills.extend(skills)
        record.__post_init__()
        proj = project_employee_post_dict(
            record.to_projection_dict(),
            registry=self._registry,
        )
        save_post(record, base_dir=self._base_dir)
        return record, proj

    def _referenced_avatar_files(self, *, exclude_post_id: str | None = None) -> set[str]:
        referenced: set[str] = set()
        for post in list_posts(base_dir=self._base_dir):
            if exclude_post_id and post.member_post_id == exclude_post_id:
                continue
            fname = post.avatar.get("file_name")
            if isinstance(fname, str) and fname:
                referenced.add(fname)
        return referenced

    def _cleanup_replaced_avatar(
        self,
        old_file_name: str | None,
        new_file_name: str | None,
    ) -> None:
        if not old_file_name or old_file_name == new_file_name:
            return
        referenced = self._referenced_avatar_files()
        cleanup_avatar_file(
            old_file_name,
            employees_base_dir=employees_dir(self._base_dir),
            referenced_file_names=referenced,
        )

    def resolve_avatar(self, record: EmployeePostRecord) -> dict[str, Any]:
        """Resolve renderable avatar presentation state (with fallback if upload is missing/corrupted)."""
        return resolve_avatar_state(
            record.member_post_id,
            record.avatar,
            employees_base_dir=employees_dir(self._base_dir),
        )

    def set_avatar_micah(
        self,
        member_post_id: str,
        *,
        seed: str,
        bg_color: str | None = None,
        palette_id: str | None = None,
    ) -> tuple[EmployeePostRecord, dict[str, Any]]:
        """Persist a built-in DiceBear Micah selection on ``EmployeePostRecord`` and clean up any old upload."""
        post_id = validate_post_id(member_post_id)
        record = get_post(post_id, base_dir=self._base_dir)
        if record is None:
            raise KeyError(f"Employee post '{post_id}' does not exist.")
        old_file = record.avatar.get("file_name") if isinstance(record.avatar, dict) else None
        from frago.employee.avatar import _now_iso

        record.avatar = normalize_avatar_spec(
            {
                "kind": "micah",
                "seed": seed,
                "bg_color": bg_color,
                "palette_id": palette_id,
                "updated_at": _now_iso(),
            },
            post_id,
            strict=True,
        )
        project_employee_post_dict(record.to_projection_dict(), registry=self._registry)
        save_post(record, base_dir=self._base_dir)
        self._cleanup_replaced_avatar(
            old_file if isinstance(old_file, str) else None,
            None,
        )
        return record, self.resolve_avatar(record)

    def upload_avatar(
        self,
        member_post_id: str,
        *,
        data: bytes,
        content_type: str | None = None,
        filename: str | None = None,
    ) -> tuple[EmployeePostRecord, dict[str, Any]]:
        """Validate, store, and attach a safe local raster image (PNG/JPEG/WebP) to ``EmployeePostRecord``."""
        post_id = validate_post_id(member_post_id)
        record = get_post(post_id, base_dir=self._base_dir)
        if record is None:
            raise KeyError(f"Employee post '{post_id}' does not exist.")
        old_file = record.avatar.get("file_name") if isinstance(record.avatar, dict) else None
        base = employees_dir(self._base_dir)
        new_spec = save_uploaded_avatar_file(
            post_id,
            data,
            employees_base_dir=base,
            content_type=content_type,
            filename=filename,
        )
        new_file = new_spec.get("file_name")
        record.avatar = normalize_avatar_spec(new_spec, post_id, strict=True)
        try:
            project_employee_post_dict(record.to_projection_dict(), registry=self._registry)
            save_post(record, base_dir=self._base_dir)
        except Exception:
            if isinstance(new_file, str) and new_file != old_file:
                cleanup_avatar_file(
                    new_file,
                    employees_base_dir=base,
                    referenced_file_names=self._referenced_avatar_files(),
                )
            raise
        self._cleanup_replaced_avatar(
            old_file if isinstance(old_file, str) else None,
            new_file if isinstance(new_file, str) else None,
        )
        return record, self.resolve_avatar(record)

    def reset_avatar(
        self,
        member_post_id: str,
    ) -> tuple[EmployeePostRecord, dict[str, Any]]:
        """Reset an employee's avatar back to deterministic default Micah and delete any unused upload."""
        post_id = validate_post_id(member_post_id)
        record = get_post(post_id, base_dir=self._base_dir)
        if record is None:
            raise KeyError(f"Employee post '{post_id}' does not exist.")
        old_file = record.avatar.get("file_name") if isinstance(record.avatar, dict) else None
        from frago.employee.avatar import _now_iso

        default_spec = default_avatar_spec(post_id)
        default_spec["updated_at"] = _now_iso()
        record.avatar = default_spec
        project_employee_post_dict(record.to_projection_dict(), registry=self._registry)
        save_post(record, base_dir=self._base_dir)
        self._cleanup_replaced_avatar(
            old_file if isinstance(old_file, str) else None,
            None,
        )
        return record, self.resolve_avatar(record)

    def get_avatar_file(self, member_post_id: str) -> tuple[bytes, str, str] | None:
        """Read and verify the uploaded avatar binary for ``member_post_id``, or return ``None``."""
        post_id = validate_post_id(member_post_id)
        record = get_post(post_id, base_dir=self._base_dir)
        if record is None:
            return None
        return read_valid_avatar_file(
            record.avatar,
            employees_base_dir=employees_dir(self._base_dir),
        )

    def discover(
        self,
        *,
        domain: str | None = None,
        recipe: str | None = None,
        data_slot: str | None = None,
        schedule_id: str | None = None,
    ) -> list[EmployeePostRecord]:
        """Discover employee posts governing the specified territory asset via `OntologyReasoner` & `SparqlQuery`."""
        all_records = {
            r.member_post_id: r for r in list_posts(base_dir=self._base_dir)
        }
        if not all_records:
            return []
        if (
            domain is None
            and recipe is None
            and data_slot is None
            and schedule_id is None
        ):
            return list(all_records.values())

        runtime, _ = self.build_runtime_graph()
        reasoner = OntologyReasoner(runtime.graph)
        matched_post_ids: set[str] | None = None

        asset_targets: list[tuple[str, str]] = []
        if domain is not None:
            dom_id = domain if domain.startswith("domain:") else f"domain:{domain}"
            asset_targets.append(("depends_on_module", dom_id))
        if recipe is not None:
            rec_id = recipe if recipe.startswith("recipe:") else f"recipe:{recipe}"
            asset_targets.append(("depends_on_module", rec_id))
        if data_slot is not None:
            slot_id = (
                data_slot if data_slot.startswith("slot:") else f"slot:{data_slot}"
            )
            asset_targets.append(("depends_on_module", slot_id))

        for predicate, target_id in asset_targets:
            rows = reasoner.query(
                SparqlQuery(
                    where=(TriplePattern("?post", predicate, target_id),),
                    select=("?post",),
                    type_constraints={"?post": "EmployeePostResource"},
                )
            )
            ids_for_filter = {
                r["?post"].ontological_id().removeprefix("post:") for r in rows
            }
            matched_post_ids = (
                ids_for_filter
                if matched_post_ids is None
                else (matched_post_ids & ids_for_filter)
            )

        if schedule_id is not None:
            sched_candidates = (
                (schedule_id, f"{schedule_id}@1.0.0")
                if ":" in schedule_id
                else (
                    f"agent_prompt:{schedule_id}@1.0.0",
                    f"recipe:{schedule_id}@1.0.0",
                    f"command:{schedule_id}@1.0.0",
                    f"schedule:{schedule_id}@1.0.0",
                )
            )
            sched_post_ids: set[str] = set()
            for sched_uid in sched_candidates:
                sched_rows = reasoner.query(
                    SparqlQuery(
                        where=(TriplePattern("?role", "governed_by", sched_uid),),
                        select=("?role",),
                        type_constraints={"?role": "DomainEmployeeRole"},
                    )
                )
                for r in sched_rows:
                    role_entity = r["?role"]
                    ctx_id = getattr(role_entity, "context_id", "")
                    if str(ctx_id).startswith("post:"):
                        sched_post_ids.add(str(ctx_id).removeprefix("post:"))
            matched_post_ids = (
                sched_post_ids
                if matched_post_ids is None
                else (matched_post_ids & sched_post_ids)
            )

        if matched_post_ids is None:
            return []
        return [
            all_records[pid]
            for pid in sorted(matched_post_ids)
            if pid in all_records
        ]

    def list_available_resources(self) -> dict[str, Any]:
        """本机此刻有哪些资源可以绑给员工：数据目录、知识域、配方。

        与巡检不同，这里**不做任何职责词筛选**：它回答的是「这台机器上有什么」，由人在
        详情弹窗里挑。巡检给的是「按职责猜它该管什么」，猜错了由人在这里补；两件事分开，
        页面才能同时摆出「他认领到的」与「本机还有的」。

        实现在 :func:`frago.employee.ledger.list_available_resources`：清单的取法与巡检
        写回编制用的是同一套路径归一化与目录约定，两份实现并存迟早会在「哪些目录算一层」
        这种细节上分岔，而分岔的后果是页面上能选的与巡检认得的不一致。
        """
        from frago.employee.ledger import list_available_resources as _list

        return _list()

    def inspect_managed_data(
        self,
        member_post_id: str,
        *,
        limit_per_slot: int = 12,
    ) -> dict[str, Any]:
        """Report what this post owns: every `data_slots` listing, plus its domains and recipes.

        Each slot is scanned one level deep by :func:`scan_data_slot_entries` — the point is an
        index of what exists, not the contents of what exists.
        """
        post_id = validate_post_id(member_post_id)
        record = get_post(post_id, base_dir=self._base_dir)
        if record is None:
            raise KeyError(f"Employee post '{post_id}' does not exist.")
        return {
            "member_post_id": post_id,
            "data_slots": [
                scan_data_slot_entries(slot, limit=limit_per_slot)
                for slot in record.data_slots
            ],
            "knowledge_domains": list(record.knowledge_domains),
            "recipes": list(record.recipes),
        }

    def register_data_entry(
        self,
        member_post_id: str,
        folder_name: str,
        *,
        summary: str = "",
        slot_path: str | None = None,
    ) -> dict[str, Any]:
        """Create one archive folder inside a slot this post owns, under the governance contract.

        ``slot_path`` MUST already be one of the post's `data_slots`. Registering a folder is a
        write into the employee's territory, so it goes through `govern`
        (``asset_kind="data_slot"``, ``governance_op="refresh_data"``) instead of touching the
        filesystem behind the contract's back: the territory check that stops an employee
        writing outside its own scope is exactly what is being relied on here.
        """
        post_id = validate_post_id(member_post_id)
        record = get_post(post_id, base_dir=self._base_dir)
        if record is None:
            raise KeyError(f"Employee post '{post_id}' does not exist.")
        if not record.data_slots:
            raise ValueError(
                f"Employee post '{post_id}' has no data_slots bound; bind one before registering entries."
            )

        target_slot = (slot_path or record.data_slots[0]).strip()
        if target_slot not in record.data_slots:
            raise ValueError(
                f"DataSlot '{target_slot}' is not governed by employee post '{post_id}'. "
                f"Owned slots: {list(record.data_slots)}."
            )

        receipt = self.govern(
            post_id,
            asset_kind="data_slot",
            target_asset_id=target_slot,
            governance_op="refresh_data",
        )
        entry = create_data_slot_entry(target_slot, folder_name, summary=summary)
        return {**entry, "governance": receipt}

    def _prune_ledger_to_post(
        self,
        record: EmployeePostRecord,
        *,
        previous: EmployeePostRecord | None,
    ) -> None:
        """岗位编制上被删掉的那几项，同步从账本里拿掉并记进排除名单。

        人删掉一项，意图是「这东西不归我管」，而不是「这一轮先别看它」。只在编制里删、
        账本不动，下一轮巡检按职责词又把它认领回来，页面上的「删」等于白点。所以这里
        把差集写进账本的排除名单：账本与编制两条路都会跳过它。

        判据是**差集**（老编制有、新编制没有），不是「新编制里没有的都不算」：账本里认领
        到而编制里还没写回去的条目（巡检刚发现、人还没保存）不能因为一次保存就被判成
        「人不想要」。只有人明确从编制上划掉的才算。
        """
        if previous is None:
            return
        ledger = load_ledger(record.member_post_id, base_dir=self._base_dir)
        if ledger is None:
            return

        def _removed(old: Sequence[str], new: Sequence[str]) -> list[str]:
            kept = {str(x).strip() for x in new}
            return [str(x).strip() for x in old if str(x).strip() and str(x).strip() not in kept]

        removed_slots = _removed(previous.data_slots, record.data_slots)
        removed_recipes = _removed(previous.recipes, record.recipes)
        removed_domains = _removed(previous.knowledge_domains, record.knowledge_domains)
        if not (removed_slots or removed_recipes or removed_domains):
            return

        apply_resource_exclusions(
            ledger,
            data_slots=removed_slots,
            recipes=removed_recipes,
            knowledge_domains=removed_domains,
        )
        save_ledger(ledger, base_dir=self._base_dir)

    def _restore_ledger_exclusions(
        self,
        record: EmployeePostRecord,
        *,
        previous: EmployeePostRecord | None,
    ) -> None:
        """编制上重新绑回来的那几项，从账本的排除名单上撤掉。

        与 :meth:`_prune_ledger_to_post` 是一件事的两个方向，缺了这一半，人的调整只能
        单向走：他删掉一项、过后又改主意重新勾上，账本里那条「人否决过」的记忆还在，
        下一次巡检仍旧把它挡在外面——页面上刚勾上的东西过一天自己又没了，而人根本没
        再动过它。

        判据是**新增的差集**（老编制没有、新编制有），不是「新编制里有的都撤」：账本认领
        到、编制里也有的那些常态条目本就不在名单上，逐个去撤是多写一遍；真正要撤的是
        人这一次明确补上的那几项。
        """
        if previous is None:
            return
        ledger = load_ledger(record.member_post_id, base_dir=self._base_dir)
        if ledger is None:
            return

        def _added(old: Sequence[str], new: Sequence[str]) -> list[str]:
            had = {str(x).strip() for x in old}
            return [str(x).strip() for x in new if str(x).strip() and str(x).strip() not in had]

        added_slots = _added(previous.data_slots, record.data_slots)
        added_recipes = _added(previous.recipes, record.recipes)
        added_domains = _added(previous.knowledge_domains, record.knowledge_domains)
        if not (added_slots or added_recipes or added_domains):
            return

        lift_resource_exclusions(
            ledger,
            data_slots=added_slots,
            recipes=added_recipes,
            knowledge_domains=added_domains,
        )
        save_ledger(ledger, base_dir=self._base_dir)

    def _sync_ledger_quietly(self, member_post_id: str) -> dict[str, Any] | None:
        """跑一次巡检并把异常吞掉。

        巡检读的是整个 ``~/.frago``，任何一个子目录权限不对、某个 ``metadata.json`` 半截
        写着，都不该让「建岗位」这件正事失败。失败时返回 None，调用方照常往下走；
        要追原因用 `frago employee sync-ledger`，那条路上异常是照实报出来的。
        """
        from frago.employee.ledger import sync_employee_ledger

        try:
            return sync_employee_ledger(
                member_post_id, base_dir=self._base_dir
            )
        except (OSError, ValueError, KeyError):
            return None

    def sync_ledger(
        self,
        member_post_id: str,
        *,
        full_rescan: bool = False,
        session_limit: int = 200,
    ) -> dict[str, Any]:
        """对该员工执行一次主动资源巡检并增量入账，返回本次增改了什么。"""
        from frago.employee.ledger import sync_employee_ledger

        return sync_employee_ledger(
            member_post_id,
            base_dir=self._base_dir,
            full_rescan=full_rescan,
            session_limit=session_limit,
        )

    def load_ledger(self, member_post_id: str) -> EmployeeLedger | None:
        """读该员工的账本；从未巡检过时为 None。"""
        return load_ledger(member_post_id, base_dir=self._base_dir)

    def ensure_ledger_schedule(
        self,
        member_post_id: str,
        *,
        add_schedule: Any = None,
        list_schedules: Any = None,
    ) -> dict[str, Any]:
        """确保该员工有一条每天执行的账本巡检排程。"""
        from frago.employee.ledger import ensure_employee_ledger_schedule

        return ensure_employee_ledger_schedule(
            member_post_id,
            base_dir=self._base_dir,
            add_schedule=add_schedule,
            list_schedules=list_schedules,
        )

    def remove_ledger_schedule(
        self,
        member_post_id: str,
        *,
        schedule_ids: Sequence[str] = (),
        remove_schedule: Any = None,
        list_schedules: Any = None,
    ) -> list[str]:
        """移除该员工关联的每日账本巡检排程。"""
        from frago.employee.ledger import remove_employee_ledger_schedule

        return remove_employee_ledger_schedule(
            member_post_id,
            schedule_ids=schedule_ids,
            remove_schedule=remove_schedule,
            list_schedules=list_schedules,
        )

    def build_business_context_block(
        self,
        member_post_id: str,
        *,
        limit_per_slot: int = 10,
        auto_sync: bool = True,
    ) -> str:
        """Render the block prepended to the first message of a new conversation for this post.

        The point is that the first turn already knows who it is talking to and what material
        is on this machine: the post's identity and generalized scope, an index of its data
        slots, and the names of its knowledge domains and recipes. Domains and recipes are
        listed by NAME only — the agent looks them up when a task actually needs them, instead
        of every conversation paying for the full text up front.

        账本存在时，这一段还会带上账本里的四栏精华：用户自己的词指什么、某句话通常要
        干什么、上次停在哪、手上有哪些东西。没有账本时（且 ``auto_sync``）先跑一次巡检
        补上——第一场会话最需要它，而那一刻恰恰是最可能还没有账本的时候。

        A section with nothing to say is omitted whole; an empty heading would just be noise in
        every conversation. An unbound post still gets its identity block.
        """
        post_id = validate_post_id(member_post_id)
        record = get_post(post_id, base_dir=self._base_dir)
        if record is None:
            raise KeyError(f"Employee post '{post_id}' does not exist.")

        ledger = load_ledger(post_id, base_dir=self._base_dir)
        if ledger is None and auto_sync:
            self._sync_ledger_quietly(post_id)
            ledger = load_ledger(post_id, base_dir=self._base_dir)

        lines: list[str] = [
            f'<frago-employee id="{record.member_post_id}" title="{record.title}" '
            f'kernel="{record.agent_kernel}">'
        ]

        lines.append("【员工身份与工作范畴】")
        lines.append(f"岗位：{record.title}（id: {record.member_post_id}）")
        if record.description:
            lines.append(f"职责：{record.description}")
        if record.work_scope:
            lines.append(f"工作范畴与方法论：{record.work_scope}")
        lines.append(
            "职责边界与泛化原则：凡属本岗位核心职责领域内的新问题（包括上面未逐一枚举的同类事项），"
            "均按本岗位的执行准则、数据底账与配方工具链统筹推进；但必须死守**职责围栏**——"
            "「非我职责绝对不由我来处理：因为我缺少目标领域的上下文、执行准则与专属 Worker 会话池，"
            "强行越界处理需要耗费大量额外时间预备上下文，且执行路径不确定、风险极高」。"
        )
        lines.append("")
        if record.member_post_id == "desktop-operator":
            lines.append("【桌面主操作员核心范式：像人类使用操作系统一样使用 Agent OS（最捷径原则与两层硬边界）】")
            lines.append(
                "你是虚拟桌面（`agent_os` / `frago desktop`）的专职操作员，用户正在屏幕前直接观看 `agent_os` 的桌面画面，并与你用第一人称（「我」）实时交流："
            )
            lines.append(
                "  1. **第一层硬边界（仅允许调用 `agent_os` 操作工具）**：你唯一允许调用的工具是 `agent_os` 提供的操作工具（即 `Bash(frago desktop:*)` 子命令族：`frago desktop play`、`frago desktop term run/read/scroll/fontsize`、`frago desktop browser open/click/scroll/read/mode`、`frago desktop window/focus/mouse/click/type/key/wait/pause/elements`、`frago desktop image/video/slide/camera/strap/rec/status`；其中 `elements --in browser` 返回元素属性与表单当前值，同名元素用 `--index <N>` 区分，`play` 用于一次性连贯批处理执行；遇不熟的子命令或参数跑 `frago desktop <subcommand> --help` 查看）。**绝对禁止**在自身后台会话里直接跑普通 Shell 命令或调用 `Read`/`Write`/`Edit`/`Glob`/`Grep`/`Skill`/`TodoWrite`；"
            )
            lines.append(
                "  2. **核心行动哲学（像人类使用操作系统一样使用 Agent OS · 最捷径原则与「先探明、后连贯执行」方法论）**："
                "人类使用操作系统时，绝不会打开终端用 `rg`/`sed`/`cat` 盲翻几千行源码来猜网页长什么样，也绝不会手写命令去硬改大型软件工程源码，而是走最直观高效的捷径——"
            )
            lines.append(
                "     - **单步观测与精确寻址（消除不确定性）**：看界面、查设置、看网页或盯会话进度时，直接打开并操作虚拟浏览器（`win:browser`）。对未知界面先用 `frago desktop browser read` 或 `frago desktop elements --in browser`（直接返回元素的 `id`/`name`/`aria_label`/`value`/`selected_text`，同名元素用 `--index <N>` 或 `page:nth:<N>:...` 精确定位）探明页面结构与目标引用，不靠盲猜选择器试错；"
            )
            lines.append(
                "     - **查代码、定位 Bug、改代码、跑复杂研发任务 → 在虚拟终端（`win:term`）或浏览器工作台里拉起并操控 CLI Agent / 领域员工**：通过 `frago desktop term run` 启动或调用专业 CLI Agent 与领域员工（例如 `frago employee invoke <post_id> \"<需求目标>\"`、`frago employee ask <post_id> \"<问题>\"`、`frago agent ...` 或交互式 CLI Agent），把**需求目标与验收标准**清晰交代给它，由它去翻代码与改代码；"
            )
            lines.append(
                "     - **像人类一样帮 CLI Agent 排除临时故障与推进多轮交互**：当终端里的 CLI Agent 遇到临时环境或连接问题（例如某内核未绑定连接报错、卡在交互确认、需要补充上下文）时，你要像真人在电脑前一样看懂屏幕报错（通过 `term read` / `browser read`），主动帮它切换可用内核/员工、去浏览器设置页核对连接，或向该会话继续发消息推进，直到问题真正闭环；"
            )
            lines.append(
                "     - **深度用足原生工具与「先探明、后连贯执行」方法论**：除 `term` 与 `browser` 外，主动组合使用 `slide`（全屏 HTML 幻灯）、`image`（图片查看器）、`video`（视频播放器）、`camera`（镜头推拉聚焦 `focus/pan/reset`）、`mouse`（真实轨迹移动点击）、`strap`（底部字幕条）与 `play`（批量连贯执行）。当多步操作路径尚未摸清时，先用单步指令探路消除不确定性；一旦路径确认无误且需要连贯执行（如录制演示视频、向观众连续展示操作流或成批完成界面交互），重置回干净起点后用 `frago desktop play '<JSON步骤数组>'`（录制时可带 `--name <片名>`）一次性成批下发，消除多轮思考带来的画面停顿；"
            )
            lines.append(
                "  3. **第二层硬边界（严禁主操作员亲自改代码或下场深度翻源码）**："
                "**绝对禁止**在 `win:term` 中通过 `sed -i`、`perl -pi`、`awk`、`cat <<EOF >`、`python -c`、`patch` 或编辑器直接修改任何项目源码文件（改代码必须 100% 交由 CLI Agent 或研发员工完成）；"
                "**严禁**把 `win:term` 当成个人源码搜索器（禁止在 `win:term` 里连续执行超过 2 次针对源码文件的 `rg`/`grep`/`sed -n`/`cat` 来替下游员工找行号）；"
            )
            lines.append(
                "  4. **双层语音体系（日常伴随播音 `ambient` vs. 显式解说旁白 `narration`）**："
            )
            lines.append(
                "     - **第一层（日常非录制交互 · 旁路伴随播音 `ambient`）**：平时在桌面上推进日常任务、未开启录制时，你只需输出准确的第一人称文本回复，无需手动调用 `say --speak`，由系统旁路 `SpeechSummarizerDaemon` 自动以 `ambient` 通道向屏幕前的人类用户播报进展；"
            )
            lines.append(
                "     - **第二层（录制视频或剧本演示 · 显式解说旁白 `narration`）**：当执行视频录制（`rec start` 或 `play --name <片名>`）时，系统会自动静默旁路 `ambient` 播音；此时你**应当**在 `frago desktop play` 剧本中通过 `say \"<解说词>\" --speak`（默认 `narration` 通道）主动发出面向成片观众的明确解说旁白（Narration），与操作步骤节拍同步收录进视频音轨。解说词必须直接讲解业务操作内容本身，严禁出现「现在开始录制」「我已经把录制停下来了」等跳戏的元状态话术。"
            )
        else:
            lines.append("【岗位角色定位：领域主理人与统筹指挥者】——管理者与人类决策参谋（严禁充当具体执行者）")
            lines.append(
                "你是本领域的常驻主理人与统筹指挥者（Orchestrator），是**管理者与基于已知进度向人类给出决策建议的角色，绝对不是具体的执行者**。"
                "你管理的核心内容只有四项：① **领域知识**（本岗知识域、数据底账、业务词汇表）；"
                "② **执行准则**（本岗方法论、验收标准、归档规范）；"
                "③ **事务围栏**（本岗职责边界 vs 同侪边界、安全禁令、需人类拍板的分叉点）；"
                "④ **Worker 会话池与任务路由**（哪些会话在执行哪些任务、现有任务可以塞到哪些已有 Worker 会话里继续执行）。"
                "你必须严格贯彻以下四条管理铁律："
            )
            lines.append(
                "  1. **非我职责绝对不由我来处理（非本岗任务强制移交同侪）**：收到人类诉求的第一步是判定职责归属。"
                "对于不属于本岗核心职责的任务，绝对不能由你自行处理或派你名下的普通 Worker 硬做——"
                "因为你缺少目标岗位的领域上下文、执行准则与在管会话池，强行越界需要花大量额外时间预备上下文且执行路径会不确定。"
                "遇到非本岗或跨领域任务时，MUST 立即执行 "
                '`frago employee invoke <同侪员工id> "<完整转交人类诉求与已知关联背景>"`'
                '（或 `frago employee ask <同侪员工id> "<问题与背景>"`）正式移交给下方花名册中的对口同侪员工处理；'
            )
            lines.append(
                "  2. **先锚定终态、判清「直答 vs 派 Worker」，严禁把主会话变成执行现场或交半成品**："
                "属本岗职责时，先做**意图反推**——只反推并锚定「人类最终要在真实环境里看到/拿到什么才算彻底办完」"
                "（不在主会话替执行员细拆代码级排查步骤，也不得擅自加塞未授权需求），"
                "严禁把中间动作当交付或缩水（如解 MR 冲突指远端冲突解除且可合并，不是本地 merge 完就收工）。"
                "**免确认直推与动前确认边界**：只读核查、本地可逆试算、用户原话已明确做到哪一步或既定常规步骤，"
                "**禁止再问、直接推进**；仅当同时满足「涉不可逆外部副作用（如远端推送、合并、改线上状态、对外发布/群发）"
                "**且**用户原话未明说做到哪一步」时，才先动前确认（补事实用一句话问清；"
                "需在互斥方案间拍板时，交互式主会话 MUST 调 `frago app ask` 出决策卡，定时/子任务禁发卡，严禁裸写纯文本选项）。"
                "接着自问：**「凭当前对话、本岗位首屏语境、近期活跃事项、业务词汇表或刚交付的摘要，能否准确、无猜地直接回答？」**"
                "**能直答的场景当场直接回答（不派 Worker）**："
                "① 上下文已有明确答案（当前对话、`<frago-employee>` 语境、近期活跃事项、业务词汇表或刚交付摘要已覆盖）；"
                "② 纯思考、判断与参谋（原理讨论、方案权衡、利弊分析、优先级排序、方向建议）；"
                "③ 轻量追问与意图澄清（解释刚给过的结论、说明设计理由、上述边界对齐与动前确认）。"
                "**必须派 Worker 的场景**（一旦缺一手证据不查会猜、或涉真实执行与改动，Employee **绝对不要自己去理解问题细节**——"
                "严禁在主会话里亲自翻读业务源码、探查网页/视频/接口、下载切片、直接改文件或跑重度检索）："
                "① 缺一手证据（需翻读源码、查日志、跨目录或历史会话取证、联网调研）；"
                "② 涉及真实执行与改动（写代码、改配置与账本、跑配方或脚本、批量处理文件、长耗时多步流程）；"
                "③ 需要独立视角验证（重要改动后的交叉代审与实测验收）；"
                "④ 保护主会话上下文（中间过程会产生大量工具输出、会撑爆管理者工作记忆）。"
                "进入派 Worker 分支时，结合已挂载的背景知识目录，把**可能与问题相关的所有参考信息的「方向」**"
                "（候选知识域名 `frago <domain> find`、候选配方名 `frago recipe info/run <name> --params '<JSON>'`、"
                "数据槽位路径、关联历史会话 `frago session ask <session_id>`，以及本岗执行准则、事务围栏与归档路径 "
                "`~/.frago/data/<主体>/<YYYYMMDD>-<语义-slug>/`）写成任务书（`.md`），"
                "**并在任务书中写清人类验收的终态定义与终态回读核验步骤**（两句实话写清终点标准与到哪儿回读确认），"
                "交给 Worker 去探查、做事，并**让 Worker 帮 Employee 自身进行审核**；"
            )
            lines.append(
                "  3. **Worker 会话池与 Context 水位调度决策（决定塞进已存在的 Worker 会话继续执行 vs. 新开 Worker 会话执行）**："
                "对会话的管理除了知道**它在干什么**，还必须盯紧**它的 Context 水位已经多长了**，绝不能无限地往同一个 Worker 会话里塞相关的新 prompt！"
                "派活前先查阅下方「本岗在管 Worker 会话池与在办任务台账」（仅分两档：`充裕 = 小于 500k`、`不充裕 = 大于等于 500k`）："
                "仅当当前 prompt 属于某个已存在 Worker 会话正在推进的同一事务（后续追问、返工修正或补充核查）**且该会话的 Context 充裕（`< 500k tokens`）**时，"
                "才执行 `frago agent --resume <已有worker_session_id> --prompt-file <任务书.md>`"
                "（常驻会话亦可用 `frago agent send <name> --prompt-file <任务书.md>`）把任务塞进该已有会话继续执行；"
                "若该已有会话的 **Context 不充裕（`>= 500k tokens`）**，或者当前是全新独立事务、多路并行子任务、独立交叉代审，"
                "则**严禁继续往旧会话里硬塞**，必须执行 `frago agent --prompt-file <任务书.md>` 新开一个 Worker 会话执行"
                "（并在新任务书中写明让新 Worker 执行 `frago session ask <旧worker_session_id> \"<需继承的前序结论与文件路径>\"` 交接上下文）；"
            )
            lines.append(
                "  4. **默认非阻塞派发、终态回读核验与会话流自动回投闭环（必须在自身会话里给人类结果与决策建议，严禁让人类自查后台会话）**："
                "人类只看着当前与你对话的这个会话窗口，**人类可能根本不知道任务发生在哪个 Worker 会话或同侪会话里**！"
                "`frago employee invoke/ask` 与 `frago agent` 在员工会话中**默认秒级非阻塞返回 `[dispatched]` 回执**（无需任何 CLI 后台参数，亦无需加 `--wait`），"
                "由 Frago 后台守护进程盯梢执行并在完成后将产出封装为 `<frago-async-callback>` 报文**自动投递回你当前会话的消息流**唤醒你；"
                "收到 `[dispatched]` 后请先向人类简要同步派发状态并结束当前回合，待 `<frago-async-callback>` 回传到达后，你 MUST 基于已知进度完成管理审核与 `notebook.md` 沉淀，"
                "**由后台 Worker 在人类最终看到的位置（如远端 MR 状态、8093 实际服务页面或真实落地文件）亲眼执行终态回读并将回读实证带回 `<frago-async-callback>` 报文；"
                "主会话只基于回传证据做管理审阅把关——若发现缺少真实位置回读或仅交中间态，主会话严禁亲自调工具补查，必须续接原 Worker 或新开独立 Worker 补做终态回读，拿到实证后**再在**当前你自己的会话里**直接向 Human（人类）给出完整结果与下一步决策建议"
                "（需人类拍板时调 `frago app ask`，定时/子任务禁发卡），绝不允许误以为人类会自己去看对应的后台会话！"
            )

        peer_posts = [
            p
            for p in list_posts(base_dir=self._base_dir)
            if p.member_post_id != record.member_post_id
        ]
        if peer_posts:
            lines.append("")
            lines.append("【本机同侪员工花名册与跨域协查协议】——非本岗任务强制移交")
            lines.append(
                "本机当前在岗的其他领域员工如下（坚守「非我职责绝对不由我来处理」：凡属对方管辖领域的任务，立即移交对方处理，切勿自行预备上下文或越界硬做）："
            )
            for peer in peer_posts:
                peer_desc = peer.description or peer.work_scope[:80] or "领域专员"
                lines.append(f"  - `{peer.member_post_id}`（{peer.title}）：{peer_desc}")
                assets_parts: list[str] = []
                if peer.knowledge_domains:
                    assets_parts.append(f"知识域={','.join(peer.knowledge_domains[:5])}")
                if peer.recipes:
                    assets_parts.append(f"配方={','.join(peer.recipes[:5])}")
                if peer.data_slots:
                    assets_parts.append(f"数据槽位={','.join(peer.data_slots[:4])}")
                if assets_parts:
                    lines.append(f"      管辖资产：{'；'.join(assets_parts)}")
            lines.append(
                "  跨域移交与协查命令：当人类诉求落入上述同侪员工的职责范畴时，MUST 执行 "
                '`frago employee invoke <同侪员工id> "<完整转交人类诉求与已知关联背景>"` '
                '（或 `frago employee ask <同侪员工id> "<附带必要背景的精准协查问题或任务>"`）'
                "发起非阻塞移交（命令秒级返回 `[dispatched]`，后台完成后自动将 `<frago-async-callback>` 回传报文注入你当前会话流），"
                "并在收到回传后在**当前你自己的会话里**向人类汇总交付结果与决策建议。"
            )

        slot_sections: list[str] = []
        for slot in record.data_slots:
            scan = scan_data_slot_entries(slot, limit=limit_per_slot)
            if not scan["exists"]:
                slot_sections.append(f"  - {slot}（目录不存在）")
                continue
            slot_sections.append(f"  - {slot}（共 {scan['total_count']} 项）")
            for entry in scan["entries"]:
                summary = entry["summary"] or "（无摘要）"
                slot_sections.append(
                    f"      {entry['name']} — {summary} ({entry['file_count']} files)"
                )
        if slot_sections:
            lines.append("")
            lines.append("【自动挂载的 ~/.frago/data 业务数据底账】")
            lines.append(
                "以下是本岗位纳管的本地数据目录现状，已直接列出，无需再逐层搜索："
            )
            lines.extend(slot_sections)
            lines.append(
                "  新产出按 ~/.frago/data/<主体>/<YYYYMMDD>-<语义-slug>/ 归档到上述槽位内。"
            )

        is_recipe_author_post = (
            record.member_post_id == "recipe-builder"
            or "frago-recipe-ops" in record.knowledge_domains
        )
        is_frago_dev_post = (
            record.member_post_id == "frago-developer"
            or "frago-dev" in record.knowledge_domains
        )
        if (
            record.knowledge_domains
            or record.recipes
            or record.skills
            or is_recipe_author_post
            or is_frago_dev_post
        ):
            lines.append("")
            lines.append("【管辖的知识域与配方工具链】——供写入任务书指派给 Worker 的参考方向目录")
            if record.knowledge_domains:
                lines.append(
                    f"知识域：{', '.join(record.knowledge_domains)}"
                    "（已有结论已在上下文或摘要中时可直接引用；需取证核验时把域名与终态核验写入任务书交 Worker 执行 `frago <domain> find`，主会话勿自行盲搜）"
                )
            if record.recipes:
                lines.append(
                    f"配方：{', '.join(record.recipes)}"
                    "（把相关配方名作为参考方向写进任务书，交由 Worker 执行 `frago recipe info <name>` / `frago recipe run <name> --params '<JSON>'`，切勿用 `-p`）"
                )
            if record.skills:
                lines.append(
                    f"默认技能：{', '.join(record.skills)}"
                    "（新会话自动挂载技能正文；含舞台技能时自动触发三角色协同编排）"
                )
            if is_recipe_author_post:
                lines.append(
                    "配方构建权威章节与边界铁律：派发配方规格与实现任务书时，MUST 指示 Worker 阅读 "
                    "`frago book recipe-spec-writing`、`frago book recipe-creation`、"
                    "`frago book interactive-recipe`、`frago book must-recipe-data`；"
                    "**本机配方落盘即自动生效（直通 `local` 区主人权限，无需重启服务，更无需设置权限）**——"
                    "带页面的配方只需将 `default_mode` 设为打开页面的 mode（内部调用 `self.publish` + `self.open_page`）"
                    "或执行 `frago recipe open <名>` 即可在本机 WebUI 直接使用；"
                    "**严禁**把用户业务需求中的「用户输入自己的大模型 key / 独立项目配置」混淆为服务器多租户隔离，"
                    "**严禁**在本机配方开发或交付阶段执行 `frago recipe expose` 或弹窗询问页面开放权限"
                    "（`expose` 仅用于多账号服务器端向外部人员开放访问，除非用户当轮明确要求部署/开放给外部账号，否则绝不触碰）。"
                )
            if is_frago_dev_post:
                lines.append(
                    "【frago 本机服务重启与代码生效铁律】改完 `frago` 源码后要在本机 `8093` 端口生效，"
                    "唯一标准动作是在 `/Users/frago/Repos/frago` 仓库目录执行 `uv run frago server restart`"
                    "（若改了前端 `src/frago/client` 则先 `npm run build`）；"
                    "该命令内部已自动完成本地版本打包与切换，"
                    "**严禁**在任务书、方案文档或 `frago app ask` 决策卡片中手写或推荐 `uv tool install` / `uv tool install --reinstall`！"
                    "派发涉及服务重启的任务书时，MUST 指示 Worker 阅读 `frago book must-system-frago` 与 `frago book better-server-restart`。"
                )

        canonical_prototype = _resolve_canonical_webui_prototype(record)
        if record.member_post_id in {"frago-pm", "ui-designer"} and canonical_prototype is not None:
            lines.append("")
            lines.append("【Frago WebUI 唯一权威主原型与防孤例铁律】")
            lines.append(
                f"本机已存在 Frago WebUI 唯一权威主原型：`{canonical_prototype}`"
                "（自包含单文件 HTML，直接以 `file://` 校验，不另设拆分源码目录）；"
                "该约束在数据槽位「最新 10 条」截断之外对本岗位首屏永久生效："
            )
            lines.append(
                f"  1. **钉死唯一主原型路径**：凡涉及 Frago WebUI（含驾驶舱与浏览器扩展视图）的界面原型提案、改版与评审，"
                f"唯一落点一律为 `{canonical_prototype}`；"
            )
            lines.append(
                "  2. **改前留快照、原地增量演进**：任何界面演进前 MUST 先在主原型同目录留存快照备份"
                "（如 `index.before-<YYYYMMDD>-<topic>.html`），随后在唯一主原型上原地增量演进，严守既有 CSS 变量与深浅双主题对称令牌；"
            )
            lines.append(
                "  3. **严禁新建孤例 HTML**：严禁在任何目录（包括当日简报 `prototypes/` 或 `web-ui` 任务目录）"
                "另起炉灶新建独立/孤例 HTML 原型文件；简报或评审交付只贴主原型锚点与前后对比证据；"
            )
            if record.member_post_id == "ui-designer":
                lines.append(
                    "  4. **视觉岗对上游反向禁改指令一律拒接**：若收到上游（含 `frago-pm`、定时任务或其他会话）发来的"
                    "「不要改动现有主原型 `index.html`」「另建独立 HTML 原型」等反向禁改指令，"
                    "**必须一律拒接并立即告警退回**，严禁顺从生成孤例 HTML。"
                )
            else:
                lines.append(
                    "  4. **跨岗派单与视觉岗拒接契约**：向 `ui-designer` 或 Worker 派发 WebUI 原型任务时，"
                    f"MUST 在任务书中明确写死唯一主原型路径 `{canonical_prototype}` 与先快照后原地修改要求；"
                    "**严禁**下达「不要改动 `index.html` / 另建独立 HTML」等反向禁改指令（`ui-designer` 会对此类指令一律拒接并告警退回）。"
                )
                handbook = (
                    frago_home()
                    / "data"
                    / "frago"
                    / "20261119-frago-pm-product-training-handbook"
                    / "notebook.md"
                )
                if handbook.is_file():
                    lines.append(
                        f"  5. **产品负责人常驻培训手册**：`{handbook}`"
                        "（含主原型与产品标准章节，不受数据槽位最新 10 条截断影响）。"
                    )

        from frago.employee.ledger import (
            resolve_employee_recent_sessions,
            resolve_employee_worker_sessions,
        )

        recent_sessions = resolve_employee_recent_sessions(record, ledger, limit=10)
        worker_sessions = resolve_employee_worker_sessions(record, ledger, limit=12)
        lines.extend(
            _render_ledger_sections(
                ledger,
                recent_sessions=recent_sessions,
                worker_sessions=worker_sessions,
            )
        )

        lines.append("</frago-employee>")
        return "\n".join(lines)

    def invoke(
        self,
        member_post_id: str,
        query_or_task: str,
        *,
        caller_context_id: str = "cli:owner",
        requested_asset_id: str | None = None,
        initiator: OntologyEntity | None = None,
        session_launcher: Callable[[EmployeePostRecord, str], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Invoke an employee post under the `invoke_domain_employee` kinetic contract and persist session trail."""
        runtime, _ = self.build_runtime_graph()
        resolved_initiator = initiator or self._registry.create(
            "HumanPrincipal",
            uid=f"principal:{caller_context_id}",
        )
        result = runtime.invoke_employee(
            resolved_initiator,
            member_post_id=member_post_id,
            query_or_task=query_or_task,
            caller_context_id=caller_context_id,
            requested_asset_id=requested_asset_id,
        )
        record = get_post(member_post_id, base_dir=self._base_dir)
        if record is not None and session_launcher is not None:
            launch_info = session_launcher(record, query_or_task)
            if isinstance(launch_info, dict):
                result.update(launch_info)
                answer_text = str(
                    launch_info.get("answer_summary")
                    or launch_info.get("text")
                    or ""
                ).strip()
                if answer_text:
                    result["answer_summary"] = answer_text
                    result["text"] = answer_text
                if (
                    launch_info.get("is_completed") is False
                    or launch_info.get("completion_state") == "running_in_background"
                ):
                    result["completion_state"] = str(
                        launch_info.get("completion_state") or "running_in_background"
                    )
                    result["is_completed"] = False
                    result["notice"] = str(
                        launch_info.get("notice")
                        or "【未完成信号】子会话刚刚启动并在后台运行中，当前尚未产出最终结果，严禁将此启动回执当作任务已完成"
                    )
                real_sid = str(launch_info.get("session_id") or "").strip()
                if real_sid:
                    self.register_session(member_post_id, real_sid)
        return result

    def register_session(
        self,
        member_post_id: str,
        session_id: str,
    ) -> EmployeePostRecord | None:
        """将指定会话登记到员工岗位的 `active_session_ids` 末尾（作为最近活跃会话）并落盘。"""
        clean_sid = str(session_id or "").strip()
        if not clean_sid:
            return None
        post_id = validate_post_id(member_post_id)
        record = get_post(post_id, base_dir=self._base_dir)
        if record is None:
            return None
        updated = [s for s in record.active_session_ids if s and s != clean_sid]
        updated.append(clean_sid)
        if updated != record.active_session_ids:
            record.active_session_ids = updated
            save_post(record, base_dir=self._base_dir)
        with contextlib.suppress(Exception):
            from frago.session.service import get_default_session_service

            onto_svc = get_default_session_service()
            rec = onto_svc.get_session(clean_sid)
            if rec is not None and not rec.employee_id and not rec.is_worker:
                rec.employee_id = post_id
                onto_svc.store.save(rec)
        return record

    def unregister_session(
        self,
        member_post_id: str,
        session_ids: str | Sequence[str],
    ) -> EmployeePostRecord | None:
        """从员工岗位的 `active_session_ids` 中移除指定会话（如虚拟桌面舞台重置后清理旧会话）。"""
        post_id = validate_post_id(member_post_id)
        record = get_post(post_id, base_dir=self._base_dir)
        if record is None:
            return None
        if isinstance(session_ids, str):
            to_remove = {session_ids.strip()} if session_ids.strip() else set()
        else:
            to_remove = {str(s).strip() for s in session_ids if str(s).strip()}
        if not to_remove:
            return record
        updated = [s for s in record.active_session_ids if s and s not in to_remove]
        if updated != record.active_session_ids:
            record.active_session_ids = updated
            save_post(record, base_dir=self._base_dir)
        return record

    def govern(
        self,
        member_post_id: str,
        *,
        asset_kind: str,
        target_asset_id: str,
        governance_op: str,
        human_decision_receipt_text: str | None = None,
    ) -> dict[str, Any]:
        """Govern a territory asset under the `govern_employee_domain_assets` kinetic contract."""
        runtime, _ = self.build_runtime_graph()
        found_role = runtime.find_employee_role(member_post_id)
        if found_role is not None:
            role: Role = found_role
        else:
            # Create an unbound role entity so Ring 3 precondition reports exact contract violation
            created_role = self._registry.create(
                "DomainEmployeeRole",
                bearer_id="kernel:claude",
                context_id=f"unbound:{member_post_id}",
            )
            assert isinstance(created_role, Role)
            role = created_role

        target_entity = self._resolve_or_materialize_asset(
            runtime.graph,
            asset_kind=asset_kind,
            target_asset_id=target_asset_id,
        )
        auth_source: InformationEntity | None = None
        if human_decision_receipt_text is not None:
            if not human_decision_receipt_text.strip().startswith("【answer】"):
                raise ValueError(
                    "Invalid HumanDecisionReceipt text: must start with '【answer】'."
                )
            receipt_entity = self._registry.create(
                "HumanDecisionReceipt",
                artifact_uri=f"answer://employee/{member_post_id}",
                content=human_decision_receipt_text,
            )
            assert isinstance(receipt_entity, InformationEntity)
            auth_source = receipt_entity

        return runtime.govern_asset(
            role,
            target_entity,
            member_post_id=member_post_id,
            asset_kind=asset_kind,
            target_asset_id=target_asset_id,
            governance_op=governance_op,
            authorization_source=auth_source,
        )

    def _resolve_or_materialize_asset(
        self,
        graph: OntologyGraph,
        *,
        asset_kind: str,
        target_asset_id: str,
    ) -> OntologyEntity:
        kind_map = {
            "knowledge_domain": ("KnowledgeDomain", f"domain:{target_asset_id.removeprefix('domain:')}"),
            "recipe": ("RecipeModule", f"recipe:{target_asset_id.removeprefix('recipe:')}"),
            "data_slot": ("DataSlot", f"slot:{target_asset_id.removeprefix('slot:')}"),
            "schedule": (
                "ScheduleRuleSpec",
                target_asset_id
                if target_asset_id.startswith("schedule:")
                else f"schedule:{target_asset_id}",
            ),
        }
        if asset_kind not in kind_map:
            raise ValueError(
                f"Unknown asset_kind '{asset_kind}'; expected one of {tuple(kind_map.keys())}."
            )
        class_id, uid_or_norm = kind_map[asset_kind]
        existing = graph.get_entity(uid_or_norm) or graph.get_entity(
            f"{uid_or_norm}@1.0.0"
        )
        if existing is not None:
            return existing
        if class_id == "ScheduleRuleSpec":
            return self._registry.create(class_id, norm_id=uid_or_norm)
        return self._registry.create(class_id, uid=uid_or_norm)


def _resolve_canonical_webui_prototype(record: EmployeePostRecord) -> Path | None:
    """Resolve the local canonical WebUI prototype `index.html` if present on disk.

    Uses ``frago_home()`` (honoring ``FRAGO_HOME`` in isolated tests) and avoids
    hardcoding developer-specific absolute paths so a clean user machine without
    the prototype file incurs zero side effects and zero false triggers.
    """
    home = frago_home()
    rel = Path("20260924-page-polish") / "prototype" / "index.html"
    candidates: list[Path] = [home / "data" / "frago-webui" / rel]
    for raw_slot in record.data_slots:
        slot_str = str(raw_slot).strip()
        if not slot_str:
            continue
        if slot_str == "~/.frago":
            slot_path = home
        elif slot_str.startswith("~/.frago/"):
            slot_path = home / slot_str.removeprefix("~/.frago/")
        elif slot_str.startswith("~"):
            slot_path = Path(slot_str).expanduser()
        else:
            slot_path = Path(slot_str)
        if slot_path.name == "frago-webui":
            candidates.append(slot_path / rel)

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _render_ledger_sections(
    ledger: EmployeeLedger | None,
    *,
    recent_sessions: Sequence[dict[str, Any]] | None = None,
    worker_sessions: Sequence[dict[str, Any]] | None = None,
) -> list[str]:
    """账本的四栏精华、本岗在管 Worker 会话池与近期会话脉络，拼进新会话第一句话前面。

    这四栏是「账本为什么值得存在」的全部理由：用户第一个 prompt 里说的词、省掉的主语、
    指代的那件事，答案都在这里，员工不必多轮反问、也不必去搜与己无关的内容。

    每一栏空了就整段不写：一个空标题在每场会话里都占一行，读的人还得判断它是不是
    「还没填」——那是噪声，不是信息。
    """
    if ledger is None and not recent_sessions and not worker_sessions:
        return []
    lines: list[str] = []

    if ledger is not None and ledger.glossary:
        lines.append("")
        lines.append("【本岗位业务词汇与隐含语义速查】")
        lines.append(
            "用户嘴里的词、缩写、代号对应本机哪个东西，直接照这张表理解，不要另猜："
        )
        for entry in ledger.glossary[:40]:
            term = str(entry.get("term", "")).strip()
            if not term:
                continue
            meaning = str(entry.get("meaning", "")).strip() or "（未写说明）"
            targets = entry.get("mapped_targets") or []
            target_text = f" → {', '.join(str(t) for t in targets)}" if targets else ""
            lines.append(f"  - 「{term}」：{meaning}{target_text}")

    if ledger is not None and ledger.intent_playbooks:
        lines.append("")
        lines.append("【高频意图与默认动作】")
        lines.append(
            "用户说下面这类话时，按「上下文可无猜直答则直答；需取证或执行按默认动作派 Worker 写清终态与回读；仅涉未明说边界的不可逆外部副作用才动前确认」处理："
        )
        for entry in ledger.intent_playbooks[:20]:
            intent = str(entry.get("intent", "")).strip()
            if not intent:
                continue
            triggers = entry.get("trigger_phrases") or []
            action = str(entry.get("default_action", "")).strip()
            trigger_text = f"（常见说法：{'、'.join(str(t) for t in triggers)}）" if triggers else ""
            lines.append(f"  - {intent}{trigger_text}")
            if action:
                lines.append(f"      默认动作：{action}")

    if ledger is not None and ledger.active_topics:
        lines.append("")
        lines.append("【近期活跃事项与最新结论】")
        lines.append(
            "以下是本岗位最近在跟的事，每件事只保留当前状态——需要接着往下做时从这里起。"
        )
        for entry in ledger.active_topics[:30]:
            title = str(entry.get("title", "")).strip()
            if not title:
                continue
            status = str(entry.get("status", "")).strip() or "进行中"
            conclusion = str(entry.get("latest_conclusion", "")).strip()
            lines.append(f"  - [{status}] {title}")
            if conclusion:
                lines.append(f"      {conclusion}")

    lines.append("")
    lines.append("【本岗在管 Worker 会话池与在办任务台账（结合「在办内容」与「Context 水位」决定塞入已有会话 vs 新开会话）】")
    lines.append(
        "作为管理者，对会话的管理除了清楚**它在干什么**，还必须盯紧**它的 Context 水位已经多长了**（仅分两档：`充裕 = 小于 500k`、`不充裕 = 大于等于 500k`），绝不能无限往同一个会话里塞新 prompt："
    )
    lines.append(
        "  - **塞进已存在的 Worker 会话继续执行**（同事务追问/返工修改，且该会话 `Context < 500k` 充裕）："
        "`frago agent --resume <worker_session_id> --prompt-file <续接任务书.md>`"
    )
    lines.append(
        "  - **新开一个 Worker 会话执行**（旧会话 `Context >= 500k` 不充裕、全新独立事务、多路并行子任务或独立视角交叉审核）："
        "`frago agent --prompt-file <新任务书.md>`（若为 `>= 500k` 换仓，在新任务书中写明让新 Worker 执行 `frago session ask <旧worker_session_id> \"<需继承的前序结论与文件路径>\"`）"
    )
    if worker_sessions:
        for w in worker_sessions[:12]:
            w_sid = str(w.get("session_id", "")).strip()
            if not w_sid:
                continue
            w_status = "运行中" if w.get("status") == "running" else "可续接"
            w_agent = str(w.get("agent_type", "") or "worker").strip()
            w_title = str(w.get("title", "") or w_sid).strip()
            w_when = str(w.get("last_activity", "")).strip()
            w_watermark = str(w.get("context_watermark", "") or "未知（< 500k · 充裕）").strip()
            w_state = str(w.get("context_state", "") or "low").strip()
            when_part = f"（{w_when}）" if w_when else ""
            lines.append(
                f"  - [Worker:{w_status}] worker_session_id=`{w_sid}` | 内核={w_agent} | 上下文水位={w_watermark} | 任务：{w_title}{when_part}"
            )
            w_conc = str(w.get("latest_conclusion", "")).strip()
            if w_conc and w_conc != w_title:
                lines.append(f"      最新进展/结论：{w_conc}")
            if w_state == "high":
                lines.append(
                    f"      ⚠️ 上下文不充裕（>= 500k），严禁继续 --resume 塞入新 prompt！若需推进该事务，请执行 `frago agent --prompt-file <新任务书.md>` 新开 Worker，并在任务书中指示新 Worker 执行 `frago session ask {w_sid} \"<需提取的前序结论与文件路径>\"`"
                )
            else:
                lines.append(
                    f"      塞入该会话继续执行：`frago agent --resume {w_sid} --prompt-file <新任务书.md>`"
                )
    else:
        lines.append(
            "  - （当前暂无已记录的本岗专属 Worker 会话；首次派活请执行 `frago agent --prompt-file <任务书.md>` 新开 Worker，"
            "系统会自动记录其 `worker_session_id` 供后续回合使用 `--resume` 塞入同一会话继续执行。）"
        )

    matched_sessions = (
        list(recent_sessions)
        if recent_sessions is not None
        else list((ledger.claimed_resources.get("matched_sessions") or []) if ledger else [])
    )
    if matched_sessions:
        lines.append("")
        lines.append("【本岗位生命延续：近期会话脉络与按需续接（供写入任务书的参考方向目录）】")
        lines.append(
            "新开员工会话从 0 历史消息 Token 轻装启动，但你的岗位生命周期连续不断代："
            "当人类继续前序话题、提及「上次 / 之前 / 刚才 / 继续 / 那个报告」，"
            "或当前任务与下列近期会话相关时，优先对照下方已列出的阶段结论——已够回答时当场直答；"
            "若需调取前序会话里的深层细节，可将 `frago session ask <session_id> \"<要提取的前序结论、参数或文件路径>\"` "
            "写入任务书交由 Worker 调取核实（或单轮轻量提取），切勿要求人类重述："
        )
        for entry in matched_sessions[:10]:
            sid = str(entry.get("session_id", "")).strip()
            title = str(entry.get("title", "")).strip() or sid
            if not title and not sid:
                continue
            when = str(entry.get("last_activity", "") or entry.get("started_at", "")).strip()
            tag = "[本岗会话]" if entry.get("bound_to_post") else "[领域相关]"
            sid_part = f"session_id=`{sid}` | " if sid else ""
            when_part = f"（{when}）" if when else ""
            lines.append(f"  - {tag} {sid_part}{title}{when_part}")
            conclusion = str(entry.get("latest_conclusion", "")).strip()
            if conclusion and conclusion != title and conclusion != "（无首条消息摘要）":
                lines.append(f"      阶段结论：{conclusion}")

    if lines and ledger is not None:
        synced = ledger.cursor.sessions_through or "（尚未记录）"
        lines.append("")
        lines.append(
            f"（以上来自本岗位账本 {ledger.member_post_id}.ledger.yaml，"
            f"游标同步至 {synced}；账本由 `frago employee sync-ledger` 维护。）"
        )
    return lines


def resolve_session_employee_id(
    session_id: str,
    *,
    base_dir: Path | None = None,
) -> str | None:
    """解析任意会话 `session_id` 所属的员工岗位编号（含直接创建的员工会话及从员工会话分出的分支/交接会话）。

    按四级确定性证据链依次判定：
    1. 岗位编制 `active_session_ids` 直接命中；
    2. 正在启动中的 `workbench_new_session` 把手或会话绑定命中；
    3. 会话自身的转录/记录中带有 `<frago-employee id="...">` 标签（覆盖 agy / claude / codex / opencode / coreagent）；
    4. 若该会话是从另一场非 Worker 会话分出的 `branch` 或 `handoff`，沿 `session_origin` 父链向上追溯（最多 8 跳）。
    """
    import contextlib

    clean_sid = str(session_id or "").strip()
    if not clean_sid:
        return None

    posts = list_posts(base_dir=base_dir)
    valid_post_ids = {p.member_post_id for p in posts}
    active_by_sid: dict[str, str] = {
        s: p.member_post_id
        for p in posts
        for s in p.active_session_ids
        if s
    }

    def _direct_employee_of(sid: str) -> str | None:
        if sid in active_by_sid:
            return active_by_sid[sid]
        with contextlib.suppress(Exception):
            from frago.session.service import get_default_session_service

            rec = get_default_session_service().get_session(sid)
            if rec is not None and not rec.is_worker:
                emp = str(rec.employee_id or rec.extra.get("employee_id") or "").strip()
                if emp and (not valid_post_ids or emp in valid_post_ids):
                    return emp
        with contextlib.suppress(Exception):
            from frago.employee.store import load_ledger

            for p in posts:
                led = load_ledger(p.member_post_id, base_dir=base_dir)
                if led is None:
                    continue
                for item in led.claimed_resources.get("matched_sessions") or []:
                    if (
                        isinstance(item, dict)
                        and item.get("bound_to_post")
                        and str(item.get("session_id") or "").strip() == sid
                    ):
                        return p.member_post_id
        with contextlib.suppress(Exception):
            from frago.session.adapters.agy_records import detect_employee_id

            detected = detect_employee_id(sid)
            if detected and (not valid_post_ids or detected in valid_post_ids):
                return detected
        with contextlib.suppress(Exception):
            from frago.employee.ledger import (
                _inspect_session_dir,
                _locate_session_dir_by_id,
                strip_injected_session_blocks,
            )
            from frago.employee.store import frago_home

            sdir = _locate_session_dir_by_id(frago_home() / "sessions", sid)
            if sdir is not None:
                info = _inspect_session_dir(sdir, sid)
                emp = str(info.get("employee_id") or "").strip()
                if emp and (not valid_post_ids or emp in valid_post_ids):
                    return emp
        with contextlib.suppress(Exception):
            from frago.employee.ledger import strip_injected_session_blocks
            from frago.session import record_reader

            for rec in record_reader.read_records(sid, limit=8):
                if rec.kind == "user.say":
                    text = str(rec.payload.get("text") or "")
                    emp, _ = strip_injected_session_blocks(text)
                    if emp and (not valid_post_ids or emp in valid_post_ids):
                        return emp
        return None

    direct = _direct_employee_of(clean_sid)
    if direct:
        return direct

    with contextlib.suppress(Exception):
        from frago.session import session_origin

        idx = session_origin.load_origin_index()
        if idx.origin_of(clean_sid) == "worker":
            return None
        cur = idx.parent_of(clean_sid)
        visited: set[str] = {clean_sid}
        for _ in range(8):
            if not cur or cur in visited:
                break
            visited.add(cur)
            found = _direct_employee_of(cur)
            if found:
                return found
            if idx.origin_of(cur) == "worker":
                break
            cur = idx.parent_of(cur)
    return None


# --- The built-in `stock` post: the reference example of a fully specified employee ---
_STOCK_WORK_SCOPE = (
    "负责股票与 ETF 的证券投研全场景，覆盖以下六类工作，并泛化处理同领域一切新任务："
    "① 交互式投研对答与盘面拆解：随时回答行情、标的、板块与持仓问题，把盘面现象拆到可核验的"
    "数据与信号层面，结论必须能指回本地数据或配方输出；"
    "② 标的、行业与市场微观结构调研：单只股票与 ETF 的基本面、结构、流动性与交易机制调研，"
    "行业横向对比与轮动观察，结论落成可复用的调研笔记；"
    "③ 量化与交易策略研究：新策略构思与验证，含 DMA 类信号、趋势网格、波动率与量价因子等，"
    "先写清信号定义与可证伪的预期，再进数据验证；"
    "④ 策略分析与回测归因：收益与回撤拆解、信号前瞻对比、参数稳健性检验，区分「信号有效」"
    "与「参数恰好拟合历史」，把归因结论与失效边界一起写下；"
    "⑤ 特定股票与 ETF 的日常分析：日线与分钟线形态、买卖信号核验、异动复盘，"
    "每日给出可直接执行的观察与信号结论；"
    "⑥ 泛化处理一切与证券投研、行情数据、组合管理相关的新型任务——上面没列举过的同类问题"
    "照样按本岗位的职责方法、数据底账与配方工具链自行推进，不因「不在清单里」而推诿或另起炉灶。"
    "任务完成后，把关键产物（报告、信号表、回测结果、调研笔记）按 "
    "~/.frago/data/stock/<YYYYMMDD>-<语义-slug>/ 归档，方法与纪律写进该目录的 notebook.md，"
    "让下一次同类问题有据可依。"
)

DEFAULT_STOCK_EMPLOYEE_SPEC: dict[str, Any] = {
    "member_post_id": "stock",
    "title": "Stock 投研与策略专员",
    "agent_kernel": "claude",
    "description": (
        "专门负责股票与 ETF 全场景投研工作：涵盖日常对答、标的与行业调研、策略研究、"
        "策略回测与归因分析、特定股票与 ETF 的日常分析，以及 ~/.frago/data/stock "
        "投研数据资产的持续沉淀。"
    ),
    "work_scope": _STOCK_WORK_SCOPE,
    # 四类资源一律留空，靠巡检按职责词自己认领。预填一份清单等于把「这台机器上此刻
    # 有什么」冻在代码里：新装的配方认不进来，卸掉的还挂在编制上，而岗位描述才是唯一
    # 不会过期的依据。清空之后 stock 与任何新建岗位走的是同一条路——建岗位即巡检一次，
    # 认领结果反哺回编制。
    "knowledge_domains": [],
    "recipes": [],
    "data_slots": [],
    "schedule_ids": [],
}


def ensure_builtin_stock_employee(
    base_dir: Path | None = None,
) -> EmployeePostRecord:
    """Create the built-in `stock` post if it is not on disk yet, and return it either way.

    Idempotent on purpose: this runs on every listing of employees, so an existing post is
    returned untouched. Someone editing `~/.frago/employees/stock.json` by hand — narrowing
    its slots, adding a recipe — MUST keep that edit; re-writing the defaults over it on each
    call would silently undo their work.
    """
    existing = get_post(DEFAULT_STOCK_EMPLOYEE_SPEC["member_post_id"], base_dir=base_dir)
    if existing is not None:
        # 岗位在、账本不在：说明它是在账本这套机制上线之前建的，或者账本被删了。
        # 补跑一次巡检，让老岗位也拿到账本；已经有了就什么都不做。
        if load_ledger(existing.member_post_id, base_dir=base_dir) is None:
            EmployeeOntologyService(base_dir=base_dir)._sync_ledger_quietly(
                existing.member_post_id
            )
        return existing

    service = EmployeeOntologyService(base_dir=base_dir)
    record, _ = service.hire(
        DEFAULT_STOCK_EMPLOYEE_SPEC["member_post_id"],
        title=DEFAULT_STOCK_EMPLOYEE_SPEC["title"],
        agent_kernel=DEFAULT_STOCK_EMPLOYEE_SPEC["agent_kernel"],
        description=DEFAULT_STOCK_EMPLOYEE_SPEC["description"],
        work_scope=DEFAULT_STOCK_EMPLOYEE_SPEC["work_scope"],
        knowledge_domains=DEFAULT_STOCK_EMPLOYEE_SPEC["knowledge_domains"],
        recipes=DEFAULT_STOCK_EMPLOYEE_SPEC["recipes"],
        data_slots=DEFAULT_STOCK_EMPLOYEE_SPEC["data_slots"],
        schedule_ids=DEFAULT_STOCK_EMPLOYEE_SPEC["schedule_ids"],
    )
    return record


# --- The built-in `desktop-operator` post: dedicated operator for `frago desktop` / `agent_os` ---
_DESKTOP_OPERATOR_WORK_SCOPE = (
    "作为虚拟桌面（frago desktop / agent_os）的主操作员，像人类使用操作系统一样操作 Agent OS（最捷径原则）："
    "① 只允许调用 agent_os 提供的 `frago desktop` 操作工具（深度使用 `browser` 虚拟浏览器、`term` 虚拟终端、`slide` 全屏幻灯、`image`/`video` 媒体窗口、`camera` 镜头推拉、`mouse`/`strap` 指针与字条、`say` 解说旁白、`elements --in browser` 精确寻址与表单值读取、`play` 批量连贯执行，遇不熟的子命令跑 `frago desktop <subcommand> --help`；严禁在自身后台会话直接执行普通命令或调用 Read/Write/Edit/Glob/Grep 等非 agent_os 工具）；"
    "② 遵循最捷径原则与「先探明、后连贯执行」方法论：看界面、查设置、看网页或盯会话进度时直接打开虚拟浏览器（`frago desktop browser`），未知界面先用 `browser read` 或 `elements --in browser`（返回 `id`/`name`/`aria_label`/`value`/`selected_text`，同名元素用 `--index <N>` 区分）探明结构与引用，不靠盲猜选择器试错；一旦路径确认无误且需要连贯执行（如录屏、连续演示或成批交互），重置回干净起点后用 `frago desktop play '<JSON步骤数组>'`（录制时可带 `--name <片名>`）一次性成批下发，消除多轮思考导致的停顿；查代码、定位 Bug 或修改代码时在虚拟终端（`win:term`）或浏览器工作台里拉起并操控 CLI Agent / 领域员工（如 `frago employee invoke/ask`、`frago agent`）去完成，并像人类一样根据屏幕报错帮 CLI Agent 排除临时故障（如切换可用内核、检查连接或继续对话推进）；"
    "③ 严禁亲自改代码或深度翻源码：绝对禁止在 `win:term` 中直接修改项目源码文件，禁止连续执行超过 2 次 `rg`/`grep`/`sed`/`cat` 替下游员工翻源码行号；"
    "④ 遵循「双层语音体系（日常伴随播音 `ambient` vs. 显式解说旁白 `narration`）」：日常非录制交互时只需输出第一人称文本回答，无需手动调用 `say --speak`（由系统旁路 `SpeechSummarizerDaemon` 以 `ambient` 通道自动播报）；当执行视频录制（`rec start` 或 `play --name <片名>`）时，系统自动静默旁路 `ambient` 播音，此时应当在 `frago desktop play` 剧本中通过 `say \"<解说词>\" --speak`（默认 `narration` 通道）主动发出面向成片观众的明确解说旁白，直接讲解业务操作内容本身，严禁出现「现在开始录制」「我已经把录制停下来了」等元状态话术。"
)

DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC: dict[str, Any] = {
    "member_post_id": "desktop-operator",
    "title": "桌面主操作员",
    "agent_kernel": "coreagent",
    "description": (
        "虚拟桌面（frago desktop / agent_os）主操作员，像人类使用操作系统一样通过浏览器、CLI Agent 与桌面视觉工具高效完成任务；"
        "仅调用 agent_os 工具，严禁亲自直接修改项目源码；采用双层语音体系（日常交互由旁路 ambient 播报，录制视频时通过 say --speak 发出显式 narration 解说旁白）。"
    ),
    "work_scope": _DESKTOP_OPERATOR_WORK_SCOPE,
    # 仅配置创建员工时必须的字段，四类资源留空由岗位通过 sync-ledger 自行整理认领
    "knowledge_domains": [],
    "recipes": [],
    "data_slots": [],
    "schedule_ids": [],
}


def ensure_builtin_desktop_operator_employee(
    base_dir: Path | None = None,
) -> EmployeePostRecord:
    """Create the built-in `desktop-operator` post if it is not on disk yet, and return it either way."""
    existing = get_post(DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["member_post_id"], base_dir=base_dir)
    if existing is not None:
        if load_ledger(existing.member_post_id, base_dir=base_dir) is None:
            EmployeeOntologyService(base_dir=base_dir)._sync_ledger_quietly(
                existing.member_post_id
            )
        return existing

    resolved_kernel = DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["agent_kernel"]
    try:
        from frago.agent_driver.driver import registered_drivers

        drivers = registered_drivers()
        for candidate in ("coreagent", "claude", "codex", "agy", "opencode"):
            drv = drivers.get(candidate)
            if (
                drv is not None
                and drv.locate is not None
                and drv.locate()
                and candidate in VALID_AGENT_KERNELS
            ):
                resolved_kernel = candidate
                break
    except Exception:
        pass

    service = EmployeeOntologyService(base_dir=base_dir)
    record, _ = service.hire(
        DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["member_post_id"],
        title=DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["title"],
        agent_kernel=resolved_kernel,
        description=DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["description"],
        work_scope=DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["work_scope"],
        knowledge_domains=DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["knowledge_domains"],
        recipes=DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["recipes"],
        data_slots=DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["data_slots"],
        schedule_ids=DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["schedule_ids"],
    )
    return record

