"""ACTION_MATRIX and post-processing rules — shared across all thinking paradigms."""

import logging

from frago.server.services.ingestion.models import (
    ActionType,
    ContextBinding,
    SemanticType,
    TaskIndex,
    TaskStatus,
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


def post_process_action(
    semantic_type: SemanticType,
    action_type: ActionType,
    task_index: list[TaskIndex],
) -> ActionType:
    """Post-processing rules applied after matrix lookup.

    - META with pending task backlog → override to EXECUTE
    """
    if semantic_type == SemanticType.META and action_type == ActionType.NO_ACTION:
        pending_count = sum(
            1 for t in task_index if t.status == TaskStatus.PENDING
        )
        if pending_count > 0:
            logger.info(
                "Post-process: META + %d pending tasks → EXECUTE", pending_count
            )
            return ActionType.EXECUTE
    return action_type


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
