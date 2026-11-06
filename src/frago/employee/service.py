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

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from frago.employee.store import (
    EmployeeLedger,
    EmployeePostRecord,
    apply_resource_exclusions,
    create_data_slot_entry,
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
    ) -> tuple[EmployeePostRecord, EmployeePostProjection]:
        """Create or update an employee post after validating its ontology shadow projection.

        ``work_scope``、``cwd``、``allowed_commands``、``skills`` 与 ``color`` 给 ``None`` 表示「这一栏不动」，
        沿用磁盘上已有的值：改一条领地绑定不该顺手把岗位的工作范畴或默认技能抹掉。
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
            "这一栏列举的是常见任务，不是边界：凡属同一领域的新问题——包括上面没有枚举过的"
            "——都按本岗位的职责方法、数据底账与配方工具链统筹推进。"
        )
        lines.append("")
        if record.member_post_id == "desktop-operator":
            lines.append("【桌面主操作员工具与执行铁律：仅允许调用 agent_os 操作工具】")
            lines.append(
                "你是虚拟桌面（`agent_os` / `frago desktop`）的专职操作员，用户正在屏幕前直接观看 `agent_os` 的桌面画面，而不是在后台会话里看你敲命令："
            )
            lines.append(
                "  1. **只允许操作 `agent_os`**：你唯一允许调用的工具是 `agent_os` 提供的操作工具（即 `Bash(frago desktop:*)` 子命令族：`frago desktop term run/key/clear/scroll/fontsize`、`frago desktop browser open/goto/click/type/scroll`、`frago desktop window/focus/mouse/click/type/key/wait/elements`、`frago desktop image/video/slide/spot/mark/strap/clear/status`）；"
            )
            lines.append(
                "  2. **严禁在自己的后台会话里直接执行业务操作**：**绝对禁止**在自身后台会话里直接跑 `ls`、`cd`、`cat`、`git`、`python` 等普通 Shell 命令，也**绝对禁止**调用 `Read`、`Write`、`Edit`、`Glob`、`Grep`、`Skill`、`TodoWrite` 或 `frago agent`！凡需查看目录、运行命令、操作仓库或浏览网页，MUST 全部通过 `frago desktop term run \"<命令>\"` 或 `frago desktop browser ...` 在 `agent_os` 屏幕上的虚拟终端（`win:term`）或虚拟浏览器（`win:browser`）内可视化执行；"
            )
            lines.append(
                "  3. **严禁直接语音播报**：**绝对禁止**调用 `frago desktop say --speak`，面向用户的语音播报统一由系统旁路播音大模型实时读取你的会话与 `agent_os` 屏幕画面后自动完成。"
            )
        else:
            lines.append("【指挥官角色契约：作为代理者构建上下文并调度普通 Worker】")
            lines.append(
                "你在本岗位中的核心角色不是亲自埋头写长脚本、硬翻全量文件的底层执行者，"
                "而是掌握完整领域账本的「指挥者与代理者」（Orchestrator）："
            )
            lines.append(
                "  1. 轻量直答：若人类提问可直接由下方账本（业务词汇、近期活跃事项结论、槽位摘要）"
                "或一次单点检索（如 `frago <domain> find`）回答，直接给出准确结论；"
            )
            lines.append(
                "  2. 编撰上下文任务书并派发普通 Worker：凡涉及拉取与清洗数据、执行重型配方"
                "（注意参数语法为 `frago recipe run <name> --params '<JSON>'`，严禁误用 `-p`）、"
                "编写分析脚本、多步浏览器调研或生成交付报告，你 MUST 先将本岗位的领域上下文"
                "（数据槽位精确路径、配方名称与参数说明、知识域规范、前序会话结论及目标归档路径 "
                "`~/.frago/data/<主体>/<YYYYMMDD>-<语义-slug>/`）汇编成一份详尽自洽的任务书文件，"
                "再调用 `frago agent --prompt-file <任务书路径>`（可并发调度 1 个或多个普通 worker）"
                "代为执行重活；你自身聚焦于上下文供给、产物验收、归档登记（`notebook.md`）与最终业务结论提炼。"
            )

        peer_posts = [
            p
            for p in list_posts(base_dir=self._base_dir)
            if p.member_post_id != record.member_post_id
        ]
        if peer_posts:
            lines.append("")
            lines.append("【本机同侪员工花名册与跨域协查协议】")
            lines.append(
                "本机当前在岗的其他领域员工如下（遇到跨域需求时直接向对方发起协查，切勿自行全盘盲搜）："
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
                "  跨域协查命令：当人类诉求涉及或落入上述同侪员工的管辖领域时，MUST 执行 "
                '`frago employee ask <同侪员工id> "<附带必要背景的精准协查问题或任务>"` '
                '（或 `frago employee invoke <同侪员工id> "<问题>"`）同步获取对方员工的真实结论后再综合回复。'
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

        if record.knowledge_domains or record.recipes or record.skills:
            lines.append("")
            lines.append("【管辖的知识域与配方工具链】")
            if record.knowledge_domains:
                lines.append(
                    f"知识域：{', '.join(record.knowledge_domains)}"
                    "（按需 `frago <domain> find` 取用，不要凭空作答）"
                )
            if record.recipes:
                lines.append(
                    f"配方：{', '.join(record.recipes)}"
                    "（按需 `frago recipe info <name>` / `frago recipe run <name> --params '<JSON>'`，切勿用 `-p`）"
                )
            if record.skills:
                lines.append(
                    f"默认技能：{', '.join(record.skills)}"
                    "（新会话自动挂载技能正文；含舞台技能时自动触发三角色协同编排）"
                )

        from frago.employee.ledger import resolve_employee_recent_sessions

        recent_sessions = resolve_employee_recent_sessions(record, ledger, limit=10)
        lines.extend(_render_ledger_sections(ledger, recent_sessions=recent_sessions))

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
                real_sid = str(launch_info.get("session_id") or "").strip()
                if real_sid:
                    refreshed = get_post(member_post_id, base_dir=self._base_dir) or record
                    if real_sid not in refreshed.active_session_ids:
                        refreshed.active_session_ids.append(real_sid)
                        save_post(refreshed, base_dir=self._base_dir)
        return result

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


def _render_ledger_sections(
    ledger: EmployeeLedger | None,
    *,
    recent_sessions: Sequence[dict[str, Any]] | None = None,
) -> list[str]:
    """账本的四栏精华与岗位生命延续近期会话脉络，拼进新会话第一句话前面。

    这四栏是「账本为什么值得存在」的全部理由：用户第一个 prompt 里说的词、省掉的主语、
    指代的那件事，答案都在这里，员工不必多轮反问、也不必去搜与己无关的内容。

    每一栏空了就整段不写：一个空标题在每场会话里都占一行，读的人还得判断它是不是
    「还没填」——那是噪声，不是信息。
    """
    if ledger is None and not recent_sessions:
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
            "用户说下面这类话时，默认要做的事已经定好，直接动手，不要先反问再找："
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

    matched_sessions = (
        list(recent_sessions)
        if recent_sessions is not None
        else list((ledger.claimed_resources.get("matched_sessions") or []) if ledger else [])
    )
    if matched_sessions:
        lines.append("")
        lines.append("【本岗位生命延续：近期会话脉络与按需续接（本岗位相关的近期会话）】")
        lines.append(
            "新开员工会话从 0 历史消息 Token 轻装启动，但你的岗位生命周期连续不断代："
            "当人类在当前会话中继续前序话题、提及「上次 / 之前 / 刚才 / 继续 / 那个报告」，"
            "或当前任务与下列近期会话相关时，你 MUST 主动执行："
        )
        lines.append(
            '  `frago session ask <session_id> "<具体要提取的前序结论、参数、文件路径或上下文>"`'
        )
        lines.append(
            "按需单轮捡起最近会话的精确内容（可加 `--tail 20` 或 `--grep \"关键词\"`），"
            "切勿假装失忆或要求人类重述。"
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
    "作为虚拟桌面（frago desktop / agent_os）的主操作员，只负责两件事："
    "① 识别用户语音转写或输入中的命令请求并仅操作 agent_os（只允许调用 agent_os 提供的 `frago desktop` 操作工具："
    "含 `term` 虚拟终端、`browser` 虚拟浏览器、`image`/`video` 媒体窗口、`slide` 全屏幻灯、`mouse`/`spot`/`mark`/`strap` 指针与字条；"
    "严禁在自身后台会话里直接执行普通命令或调用 Read/Write/Edit/Glob/Grep/Skill/TodoWrite 等非 agent_os 工具，一切终端与文件操作必须通过 `frago desktop term run` 在虚拟桌面终端内完成）；"
    "② 生成准确的文本回答。"
    "严格边界：不负责直接语音回答（禁止自行调用 `frago desktop say --speak`），"
    "语音回答统一由内部旁路语音提炼系统（LightAgent 结合会话与 agent_os 实时屏幕信息增量总结 + Edge TTS）完成。"
)

DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC: dict[str, Any] = {
    "member_post_id": "desktop-operator",
    "title": "桌面主操作员",
    "agent_kernel": "claude",
    "description": (
        "虚拟桌面（frago desktop / agent_os）主操作员，只允许调用 agent_os 提供的操作工具（frago desktop），"
        "严禁在自身后台会话直接执行其他工具或命令；只负责操作 agent_os 与生成文本回答，不负责直接语音回答。"
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

    service = EmployeeOntologyService(base_dir=base_dir)
    record, _ = service.hire(
        DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["member_post_id"],
        title=DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["title"],
        agent_kernel=DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["agent_kernel"],
        description=DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["description"],
        work_scope=DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["work_scope"],
        knowledge_domains=DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["knowledge_domains"],
        recipes=DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["recipes"],
        data_slots=DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["data_slots"],
        schedule_ids=DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC["schedule_ids"],
    )
    return record

