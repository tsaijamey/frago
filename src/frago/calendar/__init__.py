"""frago calendar — 每日完成事务（Completed Affairs）与日历服务。"""

from .store import (
    CompletedAffair,
    add_affair,
    get_calendar_dir,
    list_affairs,
    remove_affair,
    update_affair,
    write_affairs,
)

__all__ = [
    "CompletedAffair",
    "add_affair",
    "get_calendar_dir",
    "list_affairs",
    "remove_affair",
    "update_affair",
    "write_affairs",
]
