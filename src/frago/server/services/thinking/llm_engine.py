"""LLMThinkingEngine — pure LLM paradigm for every decision layer.

Every layer (Q1, Q2, Q4) uses haiku-level LLM classification.
META code detection is retained (system format, not semantic).
Q3 uses shared ACTION_MATRIX (exhaustive lookup, LLM adds no value).
"""

import logging

from frago.server.services.ingestion.models import (
    ActionType,
    ContextBinding,
    ExecutionPlan,
    ExecutionStrategy,
    IngestedTask,
    SemanticType,
)
from frago.server.services.thinking.base import META_PATTERN, BaseThinkingEngine
from frago.server.services.thinking.llm_caller import llm_classify

logger = logging.getLogger(__name__)

# -- Q1 prompt --
_Q1_PROMPT = (
    "Classify the following message into exactly one category.\n"
    "Respond with ONLY one word: statement, directive, inquiry, or meta.\n\n"
    "- statement: information delivery, reporting facts, status updates\n"
    "- directive: requesting action, giving commands, asking someone to do something\n"
    "- inquiry: asking questions, requesting information\n"
    "- meta: system-level messages, heartbeats, control signals\n\n"
    "Message: {text}\n\n"
    "Category:"
)

# -- Q2 prompt --
_Q2_PROMPT = (
    "Given the following message and existing task list, determine the relationship.\n"
    "Respond with ONLY one of these exact words:\n"
    "- active_supplement (message provides additional info for an active/pending task)\n"
    "- completed_followup (message follows up on a completed/failed task)\n"
    "- new_affair (message is a new, unrelated topic)\n"
    "- non_transactional (casual chat, acknowledgment, not task-related)\n\n"
    "Existing tasks:\n{index}\n\n"
    "Message: {text}\n\n"
    "Relationship:"
)

# -- Q4 prompt --
_Q4_PROMPT = (
    "Given the user's request, action type, available recipes, and task context, "
    "choose the best execution strategy.\n\n"
    "Action type: {action_type}\n\n"
    "Available recipes:\n{catalog}\n\n"
    "Task context:\n{index}\n\n"
    "User request: {text}\n\n"
    "Respond in this exact format (one line):\n"
    "strategy: <recipe_exact|recipe_semantic|reply_direct|agent_delegate>\n"
    "target: <recipe name or reply text or the original request>\n\n"
    "If a recipe matches well, use recipe_exact or recipe_semantic.\n"
    "If the request is a simple question answerable from task context, use reply_direct.\n"
    "Otherwise, use agent_delegate.\n\n"
    "Response:"
)

_SEMANTIC_MAP = {
    "statement": SemanticType.STATEMENT,
    "directive": SemanticType.DIRECTIVE,
    "inquiry": SemanticType.INQUIRY,
    "meta": SemanticType.META,
}

_CONTEXT_MAP = {
    "active_supplement": ContextBinding.ACTIVE_TASK_SUPPLEMENT,
    "completed_followup": ContextBinding.COMPLETED_TASK_FOLLOWUP,
    "new_affair": ContextBinding.NEW_AFFAIR,
    "non_transactional": ContextBinding.NON_TRANSACTIONAL,
}

_STRATEGY_MAP = {
    "recipe_exact": ExecutionStrategy.RECIPE_EXACT,
    "recipe_semantic": ExecutionStrategy.RECIPE_SEMANTIC,
    "reply_direct": ExecutionStrategy.REPLY_DIRECT,
    "agent_delegate": ExecutionStrategy.AGENT_DELEGATE,
}


class LLMThinkingEngine(BaseThinkingEngine):
    """Pure LLM paradigm: every decision layer uses haiku-level model.

    META code detection retained (system format match).
    task=None → NEW_AFFAIR short-circuit retained.
    Q3 uses shared ACTION_MATRIX.
    """

    # -- Q1: Semantic Classification --

    def classify_semantic(self, text: str) -> SemanticType:
        # META: system format — always code
        if META_PATTERN.match(text):
            return SemanticType.META

        # All others: LLM
        raw = llm_classify(_Q1_PROMPT.format(text=text[:500]))
        if raw:
            normalized = raw.lower().strip().rstrip(".")
            result = _SEMANTIC_MAP.get(normalized)
            if result:
                return result
            logger.debug("Q1 LLM returned unparseable: %s", raw[:50])

        # Fallback: STATEMENT
        return SemanticType.STATEMENT

    # -- Q2: Context Binding --

    def classify_context(
        self, text: str, task: IngestedTask | None = None
    ) -> ContextBinding:
        # Short-circuit: no task → new affair
        if task is None:
            return ContextBinding.NEW_AFFAIR

        # META messages: non-transactional
        if META_PATTERN.match(text):
            return ContextBinding.NON_TRANSACTIONAL

        # All others: LLM with task_index context
        index_text = self._format_task_index()
        if not index_text:
            return ContextBinding.NEW_AFFAIR

        raw = llm_classify(_Q2_PROMPT.format(text=text[:500], index=index_text))
        if raw:
            normalized = raw.lower().strip().rstrip(".")
            result = _CONTEXT_MAP.get(normalized)
            if result:
                return result
            logger.debug("Q2 LLM returned unparseable: %s", raw[:50])

        # Fallback: NEW_AFFAIR
        return ContextBinding.NEW_AFFAIR

    # -- Q4: Execution Strategy --

    def plan_execution(
        self,
        action_type: ActionType,
        text: str,
        task: IngestedTask | None = None,
    ) -> ExecutionPlan:
        catalog = self._build_recipe_catalog()
        index_text = self._format_task_index()

        raw = llm_classify(_Q4_PROMPT.format(
            text=text[:500],
            action_type=action_type.value,
            catalog=catalog or "(no recipes available)",
            index=index_text or "(no tasks)",
        ))

        if raw:
            plan = self._parse_q4_response(raw, text, task)
            if plan:
                return plan

        # Fallback: delegate
        return ExecutionPlan(
            strategy=ExecutionStrategy.AGENT_DELEGATE,
            target=text,
            params={"channel": task.channel, "reply_context": task.reply_context}
            if task
            else None,
        )

    def _parse_q4_response(
        self, raw: str, text: str, task: IngestedTask | None
    ) -> ExecutionPlan | None:
        """Parse LLM Q4 response into ExecutionPlan."""
        strategy_str = None
        target_str = None

        for line in raw.strip().split("\n"):
            line = line.strip()
            if line.lower().startswith("strategy:"):
                strategy_str = line.split(":", 1)[1].strip().lower()
            elif line.lower().startswith("target:"):
                target_str = line.split(":", 1)[1].strip()

        if not strategy_str:
            return None

        strategy = _STRATEGY_MAP.get(strategy_str)
        if not strategy:
            return None

        # Validate recipe names against registry for recipe strategies
        if strategy in (ExecutionStrategy.RECIPE_EXACT, ExecutionStrategy.RECIPE_SEMANTIC):
            if target_str:
                validated = self._validate_recipe_name(target_str)
                if validated:
                    return ExecutionPlan(strategy=strategy, target=validated)
            # Recipe not found → fallback to delegate
            return None

        return ExecutionPlan(
            strategy=strategy,
            target=target_str or text,
            params={"channel": task.channel, "reply_context": task.reply_context}
            if task and strategy == ExecutionStrategy.AGENT_DELEGATE
            else None,
        )

    @staticmethod
    def _validate_recipe_name(candidate: str) -> str | None:
        """Check candidate recipe name against registry."""
        try:
            from frago.recipes.registry import get_registry

            registry = get_registry()
            for r in registry.list_all():
                if r.metadata.name.lower() == candidate.lower():
                    return r.metadata.name
        except Exception:
            pass
        return None
