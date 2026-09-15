"""事务清单（`frago todo`）的读接口。

`frago todo` 的事务不走配方，也不进任何数据库——一件事务就是 `~/.frago/todo/`
下的一个 JSON 文件。所以这里没有服务层可以复用，直接读存储层
:mod:`frago.todo.store`：命令行看到的顺序、字段、跳过坏文件的宽容度，界面上
一模一样。任何一处在这里重排或重算，都会造出「命令行说第一条是 A、页面说是 B」
的分裂。

写入路径仍然只有命令行一条。界面上那个「添一件」不例外：它把用户填的那句话交给
frago 自带的小 agent，由 agent 去敲 `frago todo add`。服务端从头到尾不碰
`~/.frago/todo/` 下的文件——事务是 agent 的工作账本，两条写入路径迟早两边打架，
而且 `todo add` 自带的那些规矩（标题被 slugify 成 id、同一件事不准开第二条）也
只有走命令行才生效。

分类清单是例外，但不违反上面那条：它不是事务文件，是 `~/.frago/config.json` 里
的一段本机偏好（见 :mod:`frago.todo.categories`），跟界面上改会话清点门槛、改默认
内核是同一类写入。那几条规矩（id 不许重复、最多 20 个）也不在命令行里，而在存储
层的同一个校验函数里，两条路径谁写都过同一道。整张清单一次交上来——增删改名换位
在界面上都是对这张表的编辑，存盘时一次替换，不会出现「挪了一半」的中间态。
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from frago.todo import categories as todo_categories
from frago.todo.store import PRIORITIES, STATUSES, category_usage, list_todos
from frago.todo.store import get as get_todo

router = APIRouter()


class TodoItem(BaseModel):
    """一件事务。字段与 `frago todo show` 输出的 JSON 逐字对齐。"""

    id: str
    title: str
    summary: str | None = None
    status: str
    priority: str
    tags: list[str] = []
    # 分类 id；旧事务没有这个字段，读出来是 None。可能引用了已从清单里删掉的 id——
    # 原样给出，界面按未分类显示。
    category: str | None = None
    created: str
    updated: str
    done_at: str | None = None
    context: str | None = None
    steps: list[str] = []
    done_when: list[str] = []
    links: list[str] = []
    # 这件事在哪几场会话里被谈过——顺着它能回到当时的原话。旧的事务文件里没有这个
    # 字段，读出来就是空的，不影响显示。
    sessions: list[str] = []


class TodoCategory(BaseModel):
    id: str
    name: str
    # 从 1 数的名次，与 `frago todo category list` 那一栏同一个数。
    position: int


def _category_rows() -> list[TodoCategory]:
    return [
        TodoCategory(id=c.id, name=c.name, position=i)
        for i, c in enumerate(todo_categories.list_categories(), 1)
    ]


class TodoListResponse(BaseModel):
    """一批事务，外加每一档各有几件。

    ``counts`` 按**状态筛选之前**算：点进「已完成」看到 31 件、退回「全部」
    又变成另一个数，人会以为漏了。所以优先级与标签这两道筛过之后就定下计数，
    状态那一道只影响 ``todos``，不影响 ``counts``。
    """

    todos: list[TodoItem]
    counts: dict[str, int]
    # 分类清单，按排名先后。事务里只存 id，界面要靠它换成显示名、排出筛选条。
    categories: list[TodoCategory]


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
    category: str | None = Query(None, description="只看某个分类；none = 未分类"),
) -> TodoListResponse:
    """事务清单，顺序与 `frago todo list` 完全一致（分类名次 → 高中低 → 早建的在前）。"""
    status = _validate(status, STATUSES, "status")
    priority = _validate(priority, PRIORITIES, "priority")
    rows = _category_rows()
    category = _validate(
        category, (*(c.id for c in rows), todo_categories.UNCATEGORIZED), "category"
    )

    # 计数的底样本：优先级、标签、分类筛过，状态没筛。
    base = list_todos(priority=priority, tag=tag or None, category=category)

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
        categories=rows,
    )


class TodoComposeRequest(BaseModel):
    """界面上只填这一句话。"""

    description: str


class TodoComposeResponse(BaseModel):
    """agent 跑完之后，界面要知道的三件事。

    ``created`` 分开报，是因为 agent 按规矩可能不新建：描述的事情已经有一条时，
    它会往那条上追加。界面照实说「记到已有的那件上了」，别把追加说成新建。
    """

    todo_id: str | None = None
    created: bool = False
    # agent 自己的说法，原样带给人看。
    message: str = ""
    # 它实际敲下去的那条命令。看得见执行了什么，这个按钮才不是黑箱。
    command: list[str] | None = None


@router.post("/todos", response_model=TodoComposeResponse)
async def api_compose_todo(request: TodoComposeRequest) -> TodoComposeResponse:
    """把一句话交给 agent，让它写成一件像样的事务。

    这一路会真的起一个模型跑几轮，十几秒是常态——界面那边得有等待态，别按了没反应。
    """
    from frago.server.services.todo_compose_service import (
        TodoComposeError,
        TodoComposeService,
    )

    try:
        result = await run_in_threadpool(TodoComposeService.compose, request.description)
    except TodoComposeError as exc:
        # 建不成的原因（没配模型、超时、agent 自己失败）都是人能处理的，原话带回去。
        raise HTTPException(status_code=502, detail=exc.detail) from exc

    return TodoComposeResponse(**result)


class TodoCategoryInput(BaseModel):
    id: str
    name: str


class TodoCategoriesUpdate(BaseModel):
    """整张分类清单，顺序即名次。"""

    categories: list[TodoCategoryInput]


class TodoCategoriesResponse(BaseModel):
    categories: list[TodoCategory]
    # 每个分类 id 被几件事务引用。界面删分类前要照实说「会影响几件」。
    usage: dict[str, int]


@router.put("/todos/categories", response_model=TodoCategoriesResponse)
async def api_update_todo_categories(request: TodoCategoriesUpdate) -> TodoCategoriesResponse:
    """整张替换分类清单。被删掉的分类，事务里的字段不动，按未分类排。"""
    try:
        todo_categories.save_categories(
            [todo_categories.Category(c.id, c.name) for c in request.categories]
        )
    except ValueError as exc:
        # 超过 20 个、id 重复或不合规、显示名为空——原话带回去，人改了再存。
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TodoCategoriesResponse(categories=_category_rows(), usage=category_usage())


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
