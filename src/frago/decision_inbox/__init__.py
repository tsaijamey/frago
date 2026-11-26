"""统一决策收件箱（Decision Inbox）领域服务与持久化包。

围绕本体类 ``DecisionInboxItem``（+R 独立资源）、``PendingDecisionProcess``（+R 过程）与
``DecisionInboxState``（~R 状态）构建，提供去重聚合、72h TTL 保守收口、可逆状态撤销与
与在线等待会话的同源查询能力。
"""

from __future__ import annotations

from frago.decision_inbox.card_parser import (
    FENCE,
    _extract_ui_component_dict,
    _first_line,
    card_in,
    extract_decision_card_detail,
)
from frago.decision_inbox.service import (
    DEFAULT_TTL_HOURS,
    DecisionInboxError,
    DecisionInboxService,
    DecisionNotFoundError,
    InvalidDecisionTransitionError,
    UndoNotAllowedError,
    build_dedup_key,
    get_decision_inbox_service,
)
from frago.decision_inbox.store import (
    DecisionInboxStore,
    resolve_decision_inbox_dir,
)

__all__ = [
    "DEFAULT_TTL_HOURS",
    "DecisionInboxError",
    "DecisionInboxService",
    "DecisionInboxStore",
    "DecisionNotFoundError",
    "FENCE",
    "InvalidDecisionTransitionError",
    "UndoNotAllowedError",
    "_extract_ui_component_dict",
    "_first_line",
    "build_dedup_key",
    "card_in",
    "extract_decision_card_detail",
    "get_decision_inbox_service",
    "resolve_decision_inbox_dir",
]
