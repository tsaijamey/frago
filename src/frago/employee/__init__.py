"""frago employee — domain ontology package for `EmployeePostResource` (+R) & `DomainEmployeeRole` (~R).

Standard 3-file domain ontology package layout:
- ``store.py``: persistent JSON store under ``~/.frago/employees/<member_post_id>.json``
  plus the post's own ledger at ``~/.frago/employees/<member_post_id>.ledger.yaml``
- ``service.py``: ontology-backed discovery (`SparqlQuery`), binding (`project_employee_post_dict`),
  and contract-guarded execution (`DomainEmployeeRuntime`)
- ``ledger.py``: the post's proactive sweep over ``~/.frago`` (data / recipes / books / sessions)
  and the incremental merge that keeps its four-column ledger current
- ``__init__.py``: public domain exports
"""

from __future__ import annotations

from frago.employee.ledger import (
    LEDGER_SYNC_CRON,
    ensure_employee_ledger_schedule,
    extract_scope_keywords,
    list_available_resources,
    remove_employee_ledger_schedule,
    resolve_employee_recent_sessions,
    resolve_employee_worker_sessions,
    strip_injected_session_blocks,
    sync_employee_ledger,
)
from frago.employee.service import (
    DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC,
    DEFAULT_STOCK_EMPLOYEE_SPEC,
    EmployeeOntologyService,
    ensure_builtin_desktop_operator_employee,
    ensure_builtin_stock_employee,
    resolve_session_employee_id,
)
from frago.employee.store import (
    EMPLOYEE_LEDGER_SUFFIX,
    EMPLOYEE_POST_SCHEMA,
    VALID_AGENT_KERNELS,
    VALID_EMPLOYEE_COLORS,
    EmployeeLedger,
    EmployeePostRecord,
    LedgerCursor,
    apply_resource_exclusions,
    create_data_slot_entry,
    default_employee_color,
    delete_post,
    employee_ledger_path,
    employees_dir,
    frago_home,
    get_post,
    is_resource_excluded,
    ledger_summary,
    lift_resource_exclusions,
    list_posts,
    load_ledger,
    merge_ledger_entries,
    save_ledger,
    save_post,
    scan_data_slot_entries,
    validate_post_id,
)

__all__ = [
    "DEFAULT_DESKTOP_OPERATOR_EMPLOYEE_SPEC",
    "DEFAULT_STOCK_EMPLOYEE_SPEC",
    "EMPLOYEE_LEDGER_SUFFIX",
    "EMPLOYEE_POST_SCHEMA",
    "LEDGER_SYNC_CRON",
    "VALID_AGENT_KERNELS",
    "VALID_EMPLOYEE_COLORS",
    "EmployeeLedger",
    "EmployeeOntologyService",
    "EmployeePostRecord",
    "LedgerCursor",
    "apply_resource_exclusions",
    "create_data_slot_entry",
    "default_employee_color",
    "delete_post",
    "employee_ledger_path",
    "employees_dir",
    "ensure_builtin_desktop_operator_employee",
    "ensure_builtin_stock_employee",
    "ensure_employee_ledger_schedule",
    "extract_scope_keywords",
    "frago_home",
    "get_post",
    "is_resource_excluded",
    "ledger_summary",
    "lift_resource_exclusions",
    "list_available_resources",
    "list_posts",
    "load_ledger",
    "merge_ledger_entries",
    "remove_employee_ledger_schedule",
    "resolve_employee_recent_sessions",
    "resolve_employee_worker_sessions",
    "resolve_session_employee_id",
    "save_ledger",
    "save_post",
    "scan_data_slot_entries",
    "strip_injected_session_blocks",
    "sync_employee_ledger",
    "validate_post_id",
]
