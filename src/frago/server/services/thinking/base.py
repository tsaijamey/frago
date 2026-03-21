"""BaseThinkingEngine — abstract base class with Q1→Q4 template method."""

import logging
import re
from abc import ABC, abstractmethod

from frago.server.services.ingestion.models import (
    ActionType,
    ContextBinding,
    ExecutionPlan,
    IngestedTask,
    SemanticType,
    TaskIndex,
    TaskStatus,
    ThinkingResult,
)
from frago.server.services.thinking.matrix import (
    ACTION_MATRIX,
    post_process_action,
)

logger = logging.getLogger(__name__)

# Shared pattern: heartbeat format detection (used by all paradigms)
META_PATTERN = re.compile(r"^---\s*心跳")


class BaseThinkingEngine(ABC):
    """Abstract base for thinking paradigms.

    Subclasses implement Q1 (classify_semantic), Q2 (classify_context),
    Q4 (plan_execution). Q3 (decide_action) uses shared ACTION_MATRIX.
    """

    def __init__(self) -> None:
        self._task_index: list[TaskIndex] = []

    # -- public API --

    def process(self, text: str, task: IngestedTask | None = None) -> ThinkingResult:
        """Run the full Q1→Q4 decision chain on input text."""
        # Q1
        semantic_type = self.classify_semantic(text)
        logger.debug("Q1 semantic_type=%s for: %s", semantic_type, text[:60])

        # Q2
        context_binding = self.classify_context(text, task)
        logger.debug("Q2 context_binding=%s", context_binding)

        # Q3
        action_type = self.decide_action(semantic_type, context_binding)
        action_type = post_process_action(semantic_type, action_type, self._task_index)
        logger.debug("Q3 action_type=%s", action_type)

        # Q4
        execution_plan = None
        if action_type in (ActionType.EXECUTE, ActionType.RESPOND):
            execution_plan = self.plan_execution(action_type, text, task)
            logger.debug("Q4 strategy=%s target=%s", execution_plan.strategy, execution_plan.target[:60] if execution_plan.target else "")

        result = ThinkingResult(
            input_text=text,
            semantic_type=semantic_type,
            context_binding=context_binding,
            action_type=action_type,
            execution_plan=execution_plan,
        )
        logger.info(
            "ThinkingEngine: %s × %s → %s%s",
            semantic_type.value,
            context_binding.value,
            action_type.value,
            f" ({execution_plan.strategy.value})" if execution_plan else "",
        )
        return result

    def update_task_index(self, index: list[TaskIndex]) -> None:
        """Replace the in-memory task index."""
        self._task_index = index

    # -- Q1: Semantic Classification --

    @abstractmethod
    def classify_semantic(self, text: str) -> SemanticType: ...

    # -- Q2: Context Binding --

    @abstractmethod
    def classify_context(
        self, text: str, task: IngestedTask | None = None
    ) -> ContextBinding: ...

    # -- Q3: Action Decision (shared, not abstract) --

    def decide_action(
        self, semantic_type: SemanticType, context_binding: ContextBinding
    ) -> ActionType:
        """Look up the ACTION_MATRIX. Pure code, exhaustive."""
        key = (semantic_type.value, context_binding.value)
        action = ACTION_MATRIX.get(key)
        if action is None:
            logger.error("ACTION_MATRIX miss for key=%s, defaulting to DELEGATE", key)
            return ActionType.DELEGATE
        return action

    # -- Q4: Execution Strategy --

    @abstractmethod
    def plan_execution(
        self,
        action_type: ActionType,
        text: str,
        task: IngestedTask | None = None,
    ) -> ExecutionPlan: ...

    # -- shared helpers --

    def _find_task_in_index(self, task_id: str) -> TaskIndex | None:
        for idx in self._task_index:
            if idx.task_id == task_id:
                return idx
        return None

    def _try_direct_reply(self, text: str) -> str | None:
        """Try to answer directly from task_index without LLM.

        Phase 1: Only handles explicit task status queries.
        """
        instruction = text
        import re as _re
        instr_match = _re.search(r"<instruction>\s*(.*?)\s*</instruction>", text, _re.DOTALL)
        if instr_match:
            instruction = instr_match.group(1)

        if re.search(r"(?:多少|几个).*(?:任务|task)", instruction, re.IGNORECASE) or \
           re.search(r"(?:任务|task).*(?:多少|几个|状态)", instruction, re.IGNORECASE):
            active = [t for t in self._task_index if t.status in (TaskStatus.PENDING, TaskStatus.EXECUTING)]
            completed = [t for t in self._task_index if t.status == TaskStatus.COMPLETED]
            return (
                f"当前活跃任务: {len(active)} 个, 已完成: {len(completed)} 个"
            )
        return None

    def _recipe_exact_match(self, text: str) -> str | None:
        """Try to match input against recipe registry (name, use_cases, tags)."""
        try:
            from frago.recipes.registry import get_registry

            registry = get_registry()
            return registry.exact_match(text)
        except Exception:
            logger.debug("Recipe exact_match unavailable", exc_info=True)
            return None

    def _format_task_index(self) -> str:
        """Build compact task index summary for LLM context."""
        lines = []
        for idx in self._task_index[:20]:
            lines.append(
                f"- [{idx.task_id[:8]}] ({idx.status.value}) {idx.one_line_summary}"
            )
        return "\n".join(lines)

    def _build_recipe_catalog(self) -> str:
        """Build compact recipe catalog for LLM context."""
        try:
            from frago.recipes.registry import get_registry

            registry = get_registry()
            all_recipes = registry.list_all()
        except Exception:
            return ""

        if not all_recipes:
            return ""

        lines = []
        for r in all_recipes[:30]:
            use_cases_str = ", ".join(r.metadata.use_cases[:3])
            lines.append(f"- {r.metadata.name}: {r.metadata.description} (use cases: {use_cases_str})")
        return "\n".join(lines)
