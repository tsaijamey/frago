"""RuleThinkingEngine — rule-first paradigm with LLM fallback.

This is the original ThinkingEngine logic: deterministic rules run first,
LLM is invoked only when rules fall through to uncertain defaults.
"""

import logging
import re

from frago.server.services.ingestion.models import (
    ActionType,
    ContextBinding,
    ExecutionPlan,
    ExecutionStrategy,
    IngestedTask,
    SemanticType,
    TaskStatus,
)
from frago.server.services.thinking.base import META_PATTERN, BaseThinkingEngine
from frago.server.services.thinking.llm_caller import llm_classify

logger = logging.getLogger(__name__)

# Q1 rule-based patterns for semantic classification
_DIRECTIVE_PATTERNS = [
    re.compile(r"帮我|请.*(?:查|找|搜|做|发|处理|执行|运行|启动|停止|重启|删除|创建|修改|更新)"),
    re.compile(r"(?:^|\s)(?:run|start|stop|execute|send|delete|create|update|fix|deploy)\b", re.IGNORECASE),
    re.compile(r"把.*(?:发给|转给|发到|转到|复制到|移到)"),
]
_INQUIRY_PATTERNS = [
    re.compile(r"[？?]\s*$"),
    re.compile(r"(?:吗|呢|什么|多少|几个|哪|怎么|如何|是否|能否|可以吗)"),
    re.compile(r"(?:^|\s)(?:what|how|when|where|why|who|which|is there|are there|can you|could you)\b", re.IGNORECASE),
    re.compile(r"(?:状态|进度|结果|完成了?|做完了?)\s*[？?]?\s*$"),
]


class RuleThinkingEngine(BaseThinkingEngine):
    """Rule-first paradigm: deterministic rules → LLM fallback.

    Q1: META by format, DIRECTIVE/INQUIRY by regex, LLM fallback for STATEMENT.
    Q2: reply_context exact match → channel_message_id match → LLM fallback.
    Q4: recipe exact → direct_reply → recipe semantic (LLM) → delegate.
    """

    def __init__(self, enable_llm: bool = True) -> None:
        super().__init__()
        self._enable_llm = enable_llm

    # -- Q1: Semantic Classification --

    def classify_semantic(self, text: str) -> SemanticType:
        # META: heartbeat format — always code
        if META_PATTERN.match(text):
            return SemanticType.META

        # Check DIRECTIVE patterns
        has_directive = any(p.search(text) for p in _DIRECTIVE_PATTERNS)
        # Check INQUIRY patterns
        has_inquiry = any(p.search(text) for p in _INQUIRY_PATTERNS)

        # Priority: DIRECTIVE > INQUIRY > STATEMENT
        if has_directive and has_inquiry:
            return SemanticType.DIRECTIVE
        if has_directive:
            return SemanticType.DIRECTIVE
        if has_inquiry:
            return SemanticType.INQUIRY

        # Rules returned STATEMENT (default) — LLM may reclassify
        if self._enable_llm:
            llm_result = self._llm_classify_semantic(text)
            if llm_result:
                return llm_result

        return SemanticType.STATEMENT

    def _llm_classify_semantic(self, text: str) -> SemanticType | None:
        """LLM fallback for Q1 semantic classification."""
        prompt = (
            "Classify the following message into exactly one category.\n"
            "Respond with ONLY one word: statement, directive, or inquiry.\n\n"
            "- statement: information delivery, reporting facts\n"
            "- directive: requesting action, giving commands\n"
            "- inquiry: asking questions, requesting information\n\n"
            f"Message: {text[:500]}\n\n"
            "Category:"
        )
        raw = llm_classify(prompt)
        if not raw:
            return None

        normalized = raw.lower().strip().rstrip(".")
        mapping = {
            "statement": SemanticType.STATEMENT,
            "directive": SemanticType.DIRECTIVE,
            "inquiry": SemanticType.INQUIRY,
        }
        result = mapping.get(normalized)
        if result and result != SemanticType.STATEMENT:
            logger.info("Q1 LLM reclassified: STATEMENT → %s", result.value)
            return result
        return None

    # -- Q2: Context Binding --

    def classify_context(
        self, text: str, task: IngestedTask | None = None
    ) -> ContextBinding:
        # META messages are always non-transactional
        if META_PATTERN.match(text):
            return ContextBinding.NON_TRANSACTIONAL

        if task is None:
            return ContextBinding.NEW_AFFAIR

        # Round 1: deterministic — reply_context contains task_id
        reply_ctx = task.reply_context or {}
        ref_task_id = reply_ctx.get("task_id") or reply_ctx.get("in_reply_to_task_id")
        if ref_task_id:
            matched = self._find_task_in_index(ref_task_id)
            if matched:
                if matched.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT):
                    return ContextBinding.COMPLETED_TASK_FOLLOWUP
                return ContextBinding.ACTIVE_TASK_SUPPLEMENT
            return ContextBinding.NEW_AFFAIR

        # Round 1b: match by channel_message_id
        if task.channel_message_id:
            for idx in self._task_index:
                if idx.reply_context_key and idx.reply_context_key == task.channel_message_id:
                    if idx.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT):
                        return ContextBinding.COMPLETED_TASK_FOLLOWUP
                    return ContextBinding.ACTIVE_TASK_SUPPLEMENT

        # Round 2: LLM semantic matching against task_index
        if self._enable_llm and self._task_index:
            llm_result = self._llm_classify_context(text)
            if llm_result:
                return llm_result

        return ContextBinding.NEW_AFFAIR

    def _llm_classify_context(self, text: str) -> ContextBinding | None:
        """LLM fallback for Q2 context binding."""
        index_text = self._format_task_index()
        if not index_text:
            return None

        prompt = (
            "Given the following message and task list, determine the relationship.\n"
            "Respond with ONLY one of these exact words:\n"
            "- active_supplement (message is about an active/pending task)\n"
            "- completed_followup (message follows up on a completed task)\n"
            "- new_affair (message is a new, unrelated topic)\n"
            "- non_transactional (casual chat, acknowledgment, not task-related)\n\n"
            f"Existing tasks:\n{index_text}\n\n"
            f"Message: {text[:500]}\n\n"
            "Relationship:"
        )
        raw = llm_classify(prompt)
        if not raw:
            return None

        normalized = raw.lower().strip().rstrip(".")
        mapping = {
            "active_supplement": ContextBinding.ACTIVE_TASK_SUPPLEMENT,
            "completed_followup": ContextBinding.COMPLETED_TASK_FOLLOWUP,
            "new_affair": ContextBinding.NEW_AFFAIR,
            "non_transactional": ContextBinding.NON_TRANSACTIONAL,
        }
        result = mapping.get(normalized)
        if result and result != ContextBinding.NEW_AFFAIR:
            logger.info("Q2 LLM reclassified: NEW_AFFAIR → %s", result.value)
            return result
        return None

    # -- Q4: Execution Strategy --

    def plan_execution(
        self,
        action_type: ActionType,
        text: str,
        task: IngestedTask | None = None,
    ) -> ExecutionPlan:
        """Select execution strategy. Layered: exact → semantic → delegate."""
        # Layer 1: Recipe exact match (code)
        match = self._recipe_exact_match(text)
        if match:
            return ExecutionPlan(
                strategy=ExecutionStrategy.RECIPE_EXACT,
                target=match,
            )

        # Layer 1: Direct reply for RESPOND actions
        if action_type == ActionType.RESPOND:
            direct = self._try_direct_reply(text)
            if direct:
                return ExecutionPlan(
                    strategy=ExecutionStrategy.REPLY_DIRECT,
                    target=direct,
                )

        # Layer 2: Recipe semantic match (LLM)
        if self._enable_llm and action_type == ActionType.EXECUTE:
            semantic_match = self._recipe_semantic_match(text)
            if semantic_match:
                return ExecutionPlan(
                    strategy=ExecutionStrategy.RECIPE_SEMANTIC,
                    target=semantic_match,
                )

        # Layer 3: delegate to agent (fallback)
        return ExecutionPlan(
            strategy=ExecutionStrategy.AGENT_DELEGATE,
            target=text,
            params={"channel": task.channel, "reply_context": task.reply_context}
            if task
            else None,
        )

    def _recipe_semantic_match(self, text: str) -> str | None:
        """LLM-assisted recipe matching (Layer 2)."""
        catalog_text = self._build_recipe_catalog()
        if not catalog_text:
            return None

        prompt = (
            "Given the user's request and available recipes, pick the best matching recipe.\n"
            "If no recipe is a good match, respond with ONLY the word: none\n"
            "If a recipe matches, respond with ONLY its exact name (nothing else).\n\n"
            f"Available recipes:\n{catalog_text}\n\n"
            f"User request: {text[:500]}\n\n"
            "Best match:"
        )
        raw = llm_classify(prompt)
        if not raw:
            return None

        candidate = raw.strip().lower()
        if candidate == "none" or not candidate:
            return None

        # Validate against actual registry
        try:
            from frago.recipes.registry import get_registry

            registry = get_registry()
            for r in registry.list_all():
                if r.metadata.name.lower() == candidate:
                    logger.info("Q4 LLM semantic match: %s", r.metadata.name)
                    return r.metadata.name
        except Exception:
            pass

        return None
