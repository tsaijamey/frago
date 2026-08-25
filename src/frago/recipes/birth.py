"""The header that says a file is a frago recipe.

A fixed block at the top of every generated recipe. It is a convention, not a
guard: anything that can write a file can write these lines, and a check that
pretended otherwise would only be theatre — an agent with a shell on this
machine can do whatever the platform can do.

What a fixed header is actually for:

**It marks the contract.** ``frago-recipe/1`` says which set of rules this file
was written against. A recipe outlives the contract it was born under, and
"which rules does this one follow" has to be answerable by opening the file.

**It gives the checker somewhere to stand.** ``frago recipe validate`` reads it
and then goes on to check the things that matter — that the file is built on
the base class, that its declared modes exist, that its exported surface is
real. Those are the checks with teeth. The header is how they know to run.

**It tells the next author where the file came from.** Somebody opening a
recipe six months from now sees, in the first three lines, that it was
generated from a template and what to read to understand it. That is worth more
than any amount of machinery.
"""

from __future__ import annotations

import re

MARKER_PREFIX = "frago-recipe"
CONTRACT = 1

#: The header the template lays down. Kept to three lines: long enough to say
#: what this is and where the rules live, short enough that nobody deletes it
#: to get it out of the way.
HEADER = f"""# {MARKER_PREFIX}/{CONTRACT}
# 本文件由 frago recipe create 生成。能力建在基类 Recipe 上，
# 落点、消息、跨模块调用、页面发布都走基类。规范：frago book recipe-creation"""

MARKER_RE = re.compile(rf"{MARKER_PREFIX}/(?P<contract>\d+)")

#: How far into a file the header must appear. Deliberately small: a marker
#: buried three hundred lines down is one nobody opening the file will see, and
#: the whole convention is that it sits at the top.
HEAD_LINES = 12


class Birth:
    MARKED = "marked"
    UNMARKED = "unmarked"
    NEWER = "newer"


def check(name: str, source: str) -> tuple[str, str]:
    """Does this file carry the header, and for which contract."""
    head = "\n".join(source.splitlines()[:HEAD_LINES])
    m = MARKER_RE.search(head)
    if not m:
        return Birth.UNMARKED, (
            f"还没改造：代码头部没有 {MARKER_PREFIX}/{CONTRACT} 描述头，"
            f"也就没建在基类上。配方从模板生成——frago recipe create {name} "
            f"会写好描述头、带上基类和空页面，功能在模板上长。"
        )
    contract = int(m.group("contract"))
    if contract > CONTRACT:
        return Birth.NEWER, (
            f"这个配方写的是契约 v{contract}，本机的 frago 只认到 v{CONTRACT}。"
            f"先升级 frago，别改它的头——改了它只是看起来能跑。"
        )
    return Birth.MARKED, f"契约 v{contract}"
