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
    sync_employee_ledger,
)
from frago.employee.service import (
    DEFAULT_STOCK_EMPLOYEE_SPEC,
    EmployeeOntologyService,
    ensure_builtin_stock_employee,
)
from frago.employee.store import (
    EMPLOYEE_LEDGER_SUFFIX,
    EMPLOYEE_POST_SCHEMA,
    VALID_AGENT_KERNELS,
    EmployeeLedger,
    EmployeePostRecord,
    LedgerCursor,
    create_data_slot_entry,
    delete_post,
    employee_ledger_path,
    employees_dir,
    frago_home,
    get_post,
    ledger_summary,
    list_posts,
    load_ledger,
    merge_ledger_entries,
    save_ledger,
    save_post,
    scan_data_slot_entries,
    validate_post_id,
)

__all__ = [
    "DEFAULT_STOCK_EMPLOYEE_SPEC",
    "EMPLOYEE_LEDGER_SUFFIX",
    "EMPLOYEE_POST_SCHEMA",
    "LEDGER_SYNC_CRON",
    "VALID_AGENT_KERNELS",
    "EmployeeLedger",
    "EmployeeOntologyService",
    "EmployeePostRecord",
    "LedgerCursor",
    "create_data_slot_entry",
    "delete_post",
    "employee_ledger_path",
    "employees_dir",
    "ensure_builtin_stock_employee",
    "ensure_employee_ledger_schedule",
    "extract_scope_keywords",
    "frago_home",
    "get_post",
    "ledger_summary",
    "list_posts",
    "load_ledger",
    "merge_ledger_entries",
    "save_ledger",
    "save_post",
    "scan_data_slot_entries",
    "sync_employee_ledger",
    "validate_post_id",
]
