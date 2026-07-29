"""``frago context`` —— 按关键词找出上下文落在哪儿。

这一层只做 click 的事：收参数、把无 scheme 的全盘搜索拦在确认闸后、挑输出格式。
真正的检索与呈现规则在 :mod:`frago.context`，命令层不重复实现任何一条。
"""

from __future__ import annotations

import json
import sys

import click

from frago.context import ContextError, render, resolve_ref, scheme_help, split_ref

from .agent_friendly import AgentFriendlyCommand, BusinessError

# 没给 scheme 前缀时摆在调用方面前的两笔账。
#
# 代价先讲**机制**再给数字：机制换台机器依然成立，数字只是本机的一个取样。
# 这一条是有教训的——文案原先写"实测数秒"，那是只扫名字那一版量的；后来加上了
# 对整棵树的全文检索，行为变了却没回头重量，于是这道确认开始低估四倍
# （本机实测 17.9 / 21.1 / 22.1 秒）。确认闸的全部意义就是让调用方在动手前知道
# 要付多少，报少了比不报还糟。改这段搜索的成本时 MUST 一并重量这里的数字。
_WHOLE_HOME_WARNING = """\
{ref!r} 没有 scheme 前缀。

带前缀是精确查找，只翻一处：
{schemes}

不带前缀的含义是"翻遍整个 ~/.frago"：先扫一遍全部目录名与文件名，再对其中每一个
文本文件做一次全文检索。本机实测二十秒上下（约两万个目录、几十 GB），换台机器按
这个量级估。

脏是另一笔账：那棵树里绝大多数目录本就是机器用的——浏览器 profile、HTTP 缓存、
recipe 的依赖树、日志轮转。它们的名字照样会跟关键词撞上，但没有一个是上下文。\
"""


def _stdin_is_tty() -> bool:
    """当前是否有真人坐在终端前。

    单独成函数是因为它决定确认闸走哪一支，而 ``sys.stdin`` 在测试与各种宿主
    环境下会被整个换掉——判定逻辑要有个稳定的名字才谈得上打桩和验证。
    """
    return sys.stdin.isatty()


def _confirm_whole_home(ref: str, key: str) -> None:
    """全盘搜索前的确认闸。不是交互终端就拒绝，NEVER 挂在那儿等一个不会来的回车。"""
    click.echo(_WHOLE_HOME_WARNING.format(ref=ref, schemes=scheme_help()), err=True)
    if not _stdin_is_tty():
        raise BusinessError(
            "全盘搜索需要确认，而当前不是交互终端。",
            f"frago context data:{key}",
            f"frago context {key} --yes",
        )
    if not click.confirm("要翻整个 ~/.frago 吗？", default=False, err=True):
        raise BusinessError("已取消。", f"frago context data:{key}")


def _as_json(report) -> str:
    return json.dumps(
        {
            "ref": report.ref,
            "root": str(report.root),
            "keyword": report.keyword,
            "duration_ms": report.duration_ms,
            "scanned_dirs": report.scanned_dirs,
            "skipped_dirs": report.skipped_dirs,
            "notes": report.notes,
            "dir_hits": {
                "total": report.dir_total,
                "listed": [
                    {
                        "rel": h.rel,
                        "path": str(h.path),
                        "file_count": h.file_count,
                        "total_bytes": h.total_bytes,
                        "mtime": h.mtime,
                        "reason": h.reason,
                        "score": h.score,
                    }
                    for h in report.dir_hits
                ],
            },
            "file_hits": {
                "total": report.file_total,
                "listed": [
                    {
                        "rel": h.rel,
                        "size": h.size,
                        "mtime": h.mtime,
                        "reason": h.reason,
                        "score": h.score,
                    }
                    for h in report.file_hits
                ],
            },
            "content_hits": {
                "total": report.content_total,
                "machine_format_files": report.machine_total,
                "listed": [
                    {"rel": h.rel, "count": h.count, "snippet": h.snippet}
                    for h in report.content_hits
                ],
            },
        },
        ensure_ascii=False,
        indent=2,
    )


@click.command("context", cls=AgentFriendlyCommand)
@click.argument("ref")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="Skip the confirmation prompt for a scheme-less (whole ~/.frago) search",
)
def context_command(ref: str, json_output: bool, assume_yes: bool) -> None:
    """Find where a keyword lives: ``frago context data:<keyword>``.

    Reports hits in three tiers and prints NO file contents — you decide what
    is worth reading, because you are the one paying for the context.

    \b
      directory hits   directory names matching the keyword
      filename hits    file names matching the keyword
      content hits     readable documents containing it, ranked by hit count

    \b
    Name matching is layered, most certain first:
      exact name > name prefix > substring > all keyword words present >
      character subsequence (abbreviation) > difflib similarity (typos)

    \b
    Content search covers human-authored formats only (md / txt / yaml / csv
    / …). Machine formats (json / jsonl / html) are counted but not listed —
    their hits land on paths and identifiers, not on prose.

    \b
    A bare keyword (no ``<scheme>:`` prefix) is NOT shorthand for ``data:``.
    It means "search the whole ~/.frago" — tens of thousands of directories,
    most of them machinery. That is slow and noisy, so it asks first. Pass
    ``--yes`` to skip the prompt; non-interactive callers must pass it.

    \b
    Examples:
      frago context data:cxmt-ipo
      frago context data:lenovo
      frago context data:etf --json
      frago context kline-blind --yes        # whole ~/.frago, no prompt
    """
    try:
        scheme, key = split_ref(ref)
        if scheme is None and not assume_yes:
            _confirm_whole_home(ref, key)
        report = resolve_ref(ref, allow_whole_home=True)
    except ContextError as exc:
        raise BusinessError(exc.message, *exc.fixes) from exc

    click.echo(_as_json(report) if json_output else render(report))
