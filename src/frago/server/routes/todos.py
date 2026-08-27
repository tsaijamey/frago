"""事务清单（`frago todo`）的读接口。

`frago todo` 的事务不走配方，也不进任何数据库——一件事务就是 `~/.frago/todo/`
下的一个 JSON 文件。所以这里没有服务层可以复用，直接读存储层
:mod:`frago.todo.store`：命令行看到的顺序、字段、跳过坏文件的宽容度，界面上
一模一样。任何一处在这里重排或重算，都会造出「命令行说第一条是 A、页面说是 B」
的分裂。

只读。改事务的口子留在命令行——事务是 agent 的工作账本，写入路径只有一条才不
会两边打架。
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from frago.todo.store import PRIORITIES, STATUSES, get as get_todo, list_todos

router = APIRouter()


class TodoItem(BaseModel):
    """一件事务。字段与 `frago todo show` 输出的 JSON 逐字对齐。"""

    id: str
    title: str
    summary: str | None = None
    status: str
    priority: str
    tags: list[str] = []
    created: str
    updated: str
    done_at: str | None = None
    context: str | None = None
    steps: list[str] = []
    done_when: list[str] = []
    links: list[str] = []


class TodoListResponse(BaseModel):
    """一批事务，外加每一档各有几件。

    ``counts`` 按**状态筛选之前**算：点进「已完成」看到 31 件、退回「全部」
    又变成另一个数，人会以为漏了。所以优先级与标签这两道筛过之后就定下计数，
    状态那一道只影响 ``todos``，不影响 ``counts``。
    """

    todos: list[TodoItem]
    counts: dict[str, int]


def _validate(value: str | None, allowed: tuple[str, ...], field: str) -> str | None:
    """挡掉词表外的取值，别让它安静地筛出一个空清单。"""
    if value is None or value == "":
        return None
    if value not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"invalid {field} {value!r}; must be one of {', '.join(allowed)}",
        )
    return value


@router.get("/todos", response_model=TodoListResponse)
async def api_list_todos(
    status: str | None = Query(None, description="只看某一档状态"),
    priority: str | None = Query(None, description="只看某一档优先级"),
    tag: str | None = Query(None, description="只看带某个标签的"),
) -> TodoListResponse:
    """事务清单，顺序与 `frago todo list` 完全一致（优先级高在前，同级早的在前）。"""
    status = _validate(status, STATUSES, "status")
    priority = _validate(priority, PRIORITIES, "priority")

    # 计数的底样本：优先级与标签筛过，状态没筛。
    base = list_todos(priority=priority, tag=tag or None)

    counts: dict[str, int] = {"all": len(base)}
    for name in STATUSES:
        counts[name] = 0
    for todo in base:
        if todo.status in counts:
            counts[todo.status] += 1

    visible = base if status is None else [t for t in base if t.status == status]
    return TodoListResponse(
        todos=[TodoItem(**asdict(t)) for t in visible],
        counts=counts,
    )


@router.get("/todos/{todo_id}", response_model=TodoItem)
async def api_get_todo(todo_id: str) -> TodoItem:
    """单件事务。深链直接刷新时走这条，不必先把整份清单拉回来。"""
    try:
        return TodoItem(**asdict(get_todo(todo_id)))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # 前缀撞了多条。报出候选，别替人挑一条。
        raise HTTPException(status_code=400, detail=str(exc)) from exc
