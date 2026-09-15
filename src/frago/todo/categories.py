"""frago todo — 事务分类清单。

分类是一张**有序清单**：清单里的位置就是排名，`frago todo list` 先按它排，同一
分类里才轮到高中低。它不映射到优先级——「家庭」排在「工作」前面，说的是这台机器
的主人先看哪一摊，不是说家里的事都比工作急。

事务文件只记分类的 ``id``，显示名另存。改显示名不必回头改几十个事务文件，也不会
让事务和分类失联；删掉一个分类，引用它的事务按「未分类」排，字段原样留着——哪天
把分类加回来，那些事务自动归位。

清单存在 ``~/.frago/config.json`` 顶层的 ``todo_categories`` 段，而不是事务目录
里：事务目录下每个 ``*.json`` 都被当成一件事务读，塞一份配置进去会被当成坏文件跳
过、还会撞前缀解析。这份清单是本机偏好，跟 ``daemons`` 那段是同一类东西，所以沿用
``cli/daemon_commands.py`` 的写法——原样读写 JSON，只动自己这一段，其余键一个不碰。
不走 ``load_config()``：它读的时候会顺手迁移、回写，分类清单只是读一眼，不该触发
那些副作用。

段不存在就用默认四个；一旦有人改过，整张清单落盘，之后以落盘的为准。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass

MAX_CATEGORIES = 20
CONFIG_KEY = "todo_categories"

# 「未分类」的保留字。命令行里 `--category none` 表示清空 / 只看未分类，所以它不能
# 同时是某个分类的 id。
UNCATEGORIZED = "none"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


@dataclass
class Category:
    id: str
    name: str


DEFAULT_CATEGORIES: tuple[Category, ...] = (
    Category("family", "家庭"),
    Category("work", "工作"),
    Category("hobby", "个人喜好"),
    Category("other", "其他"),
)


def _config_path():
    # 调用时再取模块属性：测试夹具会把 CONFIG_PATH 改指到临时目录。
    import frago.init.config_manager as cm

    return cm.CONFIG_PATH


def _load_raw() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def list_categories() -> list[Category]:
    """当前的分类清单，按排名先后。

    读不出来（配置文件坏了、段的形状不对）就退回默认四个并在 stderr 说一声：分类
    只影响排序，NEVER 因为它读失败让 `frago todo list` 整个起不来。
    """
    try:
        section = _load_raw().get(CONFIG_KEY)
    except (json.JSONDecodeError, OSError) as e:
        print(f"warning: config.json unreadable, using default todo categories: {e}",
              file=sys.stderr)
        return list(_defaults())
    if section is None:
        return list(_defaults())
    try:
        return validate(_parse(section))
    except ValueError as e:
        print(f"warning: config.json -> {CONFIG_KEY} invalid ({e}), using defaults",
              file=sys.stderr)
        return list(_defaults())


def _defaults() -> list[Category]:
    return [Category(c.id, c.name) for c in DEFAULT_CATEGORIES]


def _parse(section) -> list[Category]:
    if not isinstance(section, list):
        raise ValueError("expected a list of {id, name}")
    out: list[Category] = []
    for item in section:
        if not isinstance(item, dict):
            raise ValueError("expected a list of {id, name}")
        out.append(Category(str(item.get("id", "")), str(item.get("name", ""))))
    return out


def validate(categories: list[Category]) -> list[Category]:
    """校验一整张清单，返回规整过（去掉首尾空白）的副本。"""
    if len(categories) > MAX_CATEGORIES:
        raise ValueError(
            f"too many categories: {len(categories)} (at most {MAX_CATEGORIES})"
        )
    seen: set[str] = set()
    out: list[Category] = []
    for c in categories:
        cid = c.id.strip()
        name = c.name.strip()
        if cid == UNCATEGORIZED:
            raise ValueError(f"category id {UNCATEGORIZED!r} is reserved for 'uncategorized'")
        if not _ID_RE.match(cid):
            raise ValueError(
                f"invalid category id {cid!r}: lowercase letters, digits, '-' or '_', "
                "starting with a letter or digit, at most 32 chars"
            )
        if cid in seen:
            raise ValueError(f"duplicate category id {cid!r}")
        if not name:
            raise ValueError(f"category {cid!r} needs a display name")
        seen.add(cid)
        out.append(Category(cid, name))
    return out


def save_categories(categories: list[Category]) -> list[Category]:
    """整张清单校验后落盘，只改 ``todo_categories`` 这一段。

    配置文件已经坏了就拒绝写：拿一份空字典覆盖回去，别人那几段就全没了。
    """
    cleaned = validate(categories)
    path = _config_path()
    try:
        data = _load_raw()
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"config.json unreadable, refusing to overwrite it: {e}") from e
    data[CONFIG_KEY] = [asdict(c) for c in cleaned]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return cleaned


def describe(categories: list[Category]) -> str:
    """报错时列出可选项：``family(家庭), work(工作), ...``。"""
    if not categories:
        return "(no categories configured)"
    return ", ".join(f"{c.id}({c.name})" for c in categories)


def require(category_id: str, categories: list[Category] | None = None) -> str:
    """确认 id 在清单里，不在就报错并列出可选项。"""
    categories = list_categories() if categories is None else categories
    if category_id not in {c.id for c in categories}:
        raise ValueError(
            f"unknown category {category_id!r}; choose one of: {describe(categories)}"
        )
    return category_id


# ── 清单的增删改移 ──────────────────────────────────────────────────────


def _index(categories: list[Category], category_id: str) -> int:
    for i, c in enumerate(categories):
        if c.id == category_id:
            return i
    raise KeyError(
        f"no category {category_id!r}; current categories: {describe(categories)}"
    )


def add_category(category_id: str, name: str, *, position: int | None = None) -> list[Category]:
    """新增一个分类。``position`` 从 1 数，缺省排到最后。"""
    categories = list_categories()
    if any(c.id == category_id for c in categories):
        raise ValueError(f"category {category_id!r} already exists")
    if len(categories) >= MAX_CATEGORIES:
        raise ValueError(
            f"already {len(categories)} categories (at most {MAX_CATEGORIES}); "
            "remove one before adding another"
        )
    index = len(categories) if position is None else _clamp(position, len(categories) + 1)
    categories.insert(index, Category(category_id, name))
    return save_categories(categories)


def rename_category(category_id: str, name: str) -> list[Category]:
    categories = list_categories()
    categories[_index(categories, category_id)].name = name
    return save_categories(categories)


def move_category(category_id: str, position: int) -> list[Category]:
    """挪到第 ``position`` 位（从 1 数；超出范围就贴到头或尾）。"""
    categories = list_categories()
    item = categories.pop(_index(categories, category_id))
    categories.insert(_clamp(position, len(categories) + 1), item)
    return save_categories(categories)


def remove_category(category_id: str) -> list[Category]:
    """从清单里拿掉。引用它的事务不动——它们按未分类排，字段值保留。"""
    categories = list_categories()
    categories.pop(_index(categories, category_id))
    return save_categories(categories)


def _clamp(position: int, size: int) -> int:
    """1 起数的位置换成下标，越界贴边。"""
    return max(0, min(position - 1, size - 1))
