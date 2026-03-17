"""ThinkingEngine — deterministic decision framework for Primary Agent.

Implements a 5-layer decision chain (Q1→Q5) that classifies incoming messages
and determines the appropriate action. Deterministic layers (code) run first;
LLM is only invoked when code cannot decide.

Architecture:
    Q1: Semantic classification (META by code, others by rules → LLM fallback)
    Q2: Context binding (reply chain by code → LLM semantic matching)
    Q3: Action decision (ACTION_MATRIX, pure code, 4×4 exhaustive)
    Q4: Execution strategy (layered: exact match → LLM semantic → delegate)
    Q5: State update (pure code, after execution)
"""

import json
import logging
import os
import re
import subprocess

from frago.server.services.ingestion.models import (
    ActionType,
    ContextBinding,
    ExecutionPlan,
    ExecutionStrategy,
    IngestedTask,
    SemanticType,
    TaskIndex,
    TaskStatus,
    ThinkingResult,
)

logger = logging.getLogger(__name__)

# -- Q3: ACTION_MATRIX — exhaustive 4×4 mapping --
# Key: (SemanticType.value, ContextBinding.value) → ActionType
ACTION_MATRIX: dict[tuple[str, str], ActionType] = {
    # STATEMENT
    ("statement", "active_supplement"): ActionType.NO_ACTION,
    ("statement", "completed_followup"): ActionType.RESPOND,
    ("statement", "new_affair"): ActionType.RESPOND,
    ("statement", "non_transactional"): ActionType.NO_ACTION,
    # DIRECTIVE
    ("directive", "active_supplement"): ActionType.EXECUTE,
    ("directive", "completed_followup"): ActionType.EXECUTE,
    ("directive", "new_affair"): ActionType.EXECUTE,
    ("directive", "non_transactional"): ActionType.EXECUTE,
    # INQUIRY
    ("inquiry", "active_supplement"): ActionType.RESPOND,
    ("inquiry", "completed_followup"): ActionType.RESPOND,
    ("inquiry", "new_affair"): ActionType.RESPOND,
    ("inquiry", "non_transactional"): ActionType.RESPOND,
    # META
    ("meta", "active_supplement"): ActionType.NO_ACTION,
    ("meta", "completed_followup"): ActionType.NO_ACTION,
    ("meta", "new_affair"): ActionType.NO_ACTION,
    ("meta", "non_transactional"): ActionType.NO_ACTION,
}

# Q1 rule-based patterns for semantic classification
_META_PATTERN = re.compile(r"^---\s*心跳")
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


def _llm_classify(prompt: str, timeout: int = 30) -> str | None:
    """One-shot Claude CLI call for lightweight classification.

    Uses haiku model with JSON output. Returns the raw result text,
    or None on any failure (timeout, CLI not found, parse error).
    """
    try:
        from frago.compat import find_claude_cli, get_windows_subprocess_kwargs
    except ImportError:
        from frago.compat import get_windows_subprocess_kwargs
        find_claude_cli = None

    # Find claude CLI
    claude_path = None
    if find_claude_cli:
        claude_path = find_claude_cli()
    if not claude_path:
        import shutil
        claude_path = shutil.which("claude")
    if not claude_path:
        logger.debug("LLM classify: claude CLI not found")
        return None

    cmd = [claude_path, "-p", "-", "--model", "haiku", "--output-format", "json"]

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)

    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
            **get_windows_subprocess_kwargs(),
        )
        stdout, stderr = process.communicate(input=prompt, timeout=timeout)

        if process.returncode != 0:
            logger.debug("LLM classify failed (rc=%d): %s", process.returncode, stderr[:200] if stderr else "")
            return None

        result = json.loads(stdout)
        if result.get("type") == "result":
            return result.get("result", "").strip()
        return stdout.strip()

    except subprocess.TimeoutExpired:
        logger.warning("LLM classify timed out (%ds)", timeout)
        import contextlib
        with contextlib.suppress(Exception):
            process.kill()
        return None
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("LLM classify error: %s", e)
        return None


class ThinkingEngine:
    """Decision engine for the Primary Agent.

    Code/rule layers run first. LLM is invoked only when code cannot decide.
    LLM calls can be disabled via enable_llm=False (for testing or cost control).
    """

    def __init__(self, enable_llm: bool = True) -> None:
        self._task_index: list[TaskIndex] = []
        self._enable_llm = enable_llm

    # -- public API --

    def process(self, text: str, task: IngestedTask | None = None) -> ThinkingResult:
        """Run the full Q1→Q4 decision chain on input text.

        Args:
            text: The raw input message text.
            task: Optional IngestedTask providing channel/reply context.

        Returns:
            ThinkingResult with all decisions filled (except Q5 state_delta).
        """
        # Q1
        semantic_type = self.classify_semantic(text)
        logger.debug("Q1 semantic_type=%s for: %s", semantic_type, text[:60])

        # Q2
        context_binding = self.classify_context(text, task)
        logger.debug("Q2 context_binding=%s", context_binding)

        # Q3
        action_type = self.decide_action(semantic_type, context_binding)
        # Post-processing: META with pending task backlog → EXECUTE
        action_type = self._post_process_action(semantic_type, action_type)
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

    def classify_semantic(self, text: str) -> SemanticType:
        """Classify the semantic type of input text.

        Layer 1: Rule-based. META by format; DIRECTIVE/INQUIRY by keyword/pattern.
        Layer 2: LLM fallback when rules return STATEMENT (the uncertain default).
        """
        # META: heartbeat format — always code
        if _META_PATTERN.match(text):
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
        """LLM fallback for Q1 semantic classification.

        Only called when rule-based classification falls through to STATEMENT.
        Returns None if LLM is unavailable or response is unparseable.
        """
        prompt = (
            "Classify the following message into exactly one category.\n"
            "Respond with ONLY one word: statement, directive, or inquiry.\n\n"
            "- statement: information delivery, reporting facts\n"
            "- directive: requesting action, giving commands\n"
            "- inquiry: asking questions, requesting information\n\n"
            f"Message: {text[:500]}\n\n"
            "Category:"
        )
        raw = _llm_classify(prompt)
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
        """Determine how input relates to existing context.

        Round 1: Code — reply_context / reply chain matching.
        Round 2: LLM — semantic similarity against task_index (only when Round 1 indeterminate).
        """
        # META messages are always non-transactional regardless of task presence
        if _META_PATTERN.match(text):
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
            # Referenced task not found (possibly deleted) → treat as new
            return ContextBinding.NEW_AFFAIR

        # Round 1b: match by channel_message_id against reply_context_key in index
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
        """LLM fallback for Q2 context binding.

        Builds a compact task index summary and asks LLM to match.
        Returns None if LLM unavailable, no match, or unparseable.
        """
        # Build compact index for LLM context
        index_lines = []
        for idx in self._task_index[:20]:
            index_lines.append(
                f"- [{idx.task_id[:8]}] ({idx.status.value}) {idx.one_line_summary}"
            )
        if not index_lines:
            return None

        index_text = "\n".join(index_lines)
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
        raw = _llm_classify(prompt)
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

    # -- Q3: Action Decision --

    def decide_action(
        self, semantic_type: SemanticType, context_binding: ContextBinding
    ) -> ActionType:
        """Look up the ACTION_MATRIX. Pure code, exhaustive."""
        key = (semantic_type.value, context_binding.value)
        action = ACTION_MATRIX.get(key)
        if action is None:
            # Should never happen if matrix is complete — defensive fallback
            logger.error("ACTION_MATRIX miss for key=%s, defaulting to DELEGATE", key)
            return ActionType.DELEGATE
        return action

    def _post_process_action(
        self, semantic_type: SemanticType, action_type: ActionType
    ) -> ActionType:
        """Post-processing rules applied after matrix lookup.

        - META with pending task backlog → override to EXECUTE
        """
        if semantic_type == SemanticType.META and action_type == ActionType.NO_ACTION:
            pending_count = sum(
                1 for t in self._task_index if t.status == TaskStatus.PENDING
            )
            if pending_count > 0:
                logger.info(
                    "Post-process: META + %d pending tasks → EXECUTE", pending_count
                )
                return ActionType.EXECUTE
        return action_type

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

        # Layer 1: Direct reply for RESPOND actions that can be answered from index
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

    # -- Q3/Q4 helpers --

    def _find_task_in_index(self, task_id: str) -> TaskIndex | None:
        for idx in self._task_index:
            if idx.task_id == task_id:
                return idx
        return None

    def _recipe_semantic_match(self, text: str) -> str | None:
        """LLM-assisted recipe matching (Layer 2).

        Builds a compact recipe catalog and asks LLM to pick the best match.
        Returns recipe name if matched, None otherwise.
        """
        try:
            from frago.recipes.registry import get_registry

            registry = get_registry()
            all_recipes = registry.list_all()
        except Exception:
            return None

        if not all_recipes:
            return None

        # Build compact catalog for LLM
        catalog_lines = []
        for r in all_recipes[:30]:  # Cap to avoid token explosion
            use_cases_str = ", ".join(r.metadata.use_cases[:3])
            catalog_lines.append(f"- {r.metadata.name}: {r.metadata.description} (use cases: {use_cases_str})")

        catalog_text = "\n".join(catalog_lines)
        prompt = (
            "Given the user's request and available recipes, pick the best matching recipe.\n"
            "If no recipe is a good match, respond with ONLY the word: none\n"
            "If a recipe matches, respond with ONLY its exact name (nothing else).\n\n"
            f"Available recipes:\n{catalog_text}\n\n"
            f"User request: {text[:500]}\n\n"
            "Best match:"
        )
        raw = _llm_classify(prompt)
        if not raw:
            return None

        candidate = raw.strip().lower()
        if candidate == "none" or not candidate:
            return None

        # Validate against actual registry
        for r in all_recipes:
            if r.metadata.name.lower() == candidate:
                logger.info("Q4 LLM semantic match: %s", r.metadata.name)
                return r.metadata.name

        return None

    def _recipe_exact_match(self, text: str) -> str | None:
        """Try to match input against recipe registry (name, use_cases, tags).

        Returns recipe name if matched, None otherwise.
        """
        try:
            from frago.recipes.registry import get_registry

            registry = get_registry()
            return registry.exact_match(text)
        except Exception:
            logger.debug("Recipe exact_match unavailable", exc_info=True)
            return None

    def _try_direct_reply(self, text: str) -> str | None:
        """Try to answer directly from task_index without LLM.

        Phase 1: Only handles explicit task status queries.
        """
        # Simple pattern: asking about task count/status
        if re.search(r"(?:多少|几个).*(?:任务|task)", text, re.IGNORECASE) or \
           re.search(r"(?:任务|task).*(?:多少|几个|状态)", text, re.IGNORECASE):
            active = [t for t in self._task_index if t.status in (TaskStatus.PENDING, TaskStatus.EXECUTING)]
            completed = [t for t in self._task_index if t.status == TaskStatus.COMPLETED]
            return (
                f"当前活跃任务: {len(active)} 个, 已完成: {len(completed)} 个"
            )
        return None

    # -- verification --

    @staticmethod
    def verify_matrix_completeness() -> None:
        """Verify that ACTION_MATRIX covers all 4×4 combinations."""
        missing = []
        for st in SemanticType:
            for cb in ContextBinding:
                key = (st.value, cb.value)
                if key not in ACTION_MATRIX:
                    missing.append(key)
        if missing:
            raise AssertionError(f"ACTION_MATRIX missing keys: {missing}")
        total = len(SemanticType) * len(ContextBinding)
        covered = len(ACTION_MATRIX)
        print(f"{covered}/{total} combinations covered")
