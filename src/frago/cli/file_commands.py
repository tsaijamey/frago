"""``frago cp`` / ``mv`` / ``rm`` —— 搬文件这一层的命令面。

这一层只做 click 的事：收参数、选输出格式、把退出码和结果对齐。真正的语义在
:mod:`frago.files.ops`，边界在 :mod:`frago.files.guard`，怎么把东西送进垃圾桶在
:mod:`frago.files.trash`，命令层不重复实现任何一条。

两种调用方，同一套回执：人在终端里跑，和配方通过总线请平台代跑
（``self.ask_frago(["rm", path])``）。后者拿到的是退出码加上这里打印的文字，
所以 ``--json`` 给的是一份能直接 ``json.loads`` 的完整交代，而不是给人看的摘要。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from frago.files import ops

from .agent_friendly import AgentFriendlyCommand, BusinessError, echo_business_error

_ARROW = "→"


def _render(report: ops.Report) -> str:
    """一条命令干了什么，逐行说清楚。

    没有「静默成功」这条路：即使一件事都没做成，也会打出一句说明没做成什么，
    因为调用方看到的空输出和「命令根本没跑」长得一模一样。
    """
    lines: list[str] = []
    for one in report.done:
        if one.verb == "trashed":
            lines.append(f"rm      {one.source}  {_ARROW}  垃圾桶 {one.target}")
        elif one.verb == "skipped":
            lines.append(f"skip    {one.target}")
        else:
            verb = "cp" if one.verb == "copied" else "mv"
            lines.append(f"{verb:<8}{one.source}  {_ARROW}  {one.target}")
        if one.replaced:
            lines.append(
                f"        覆盖了原来的 {one.replaced['path']}，"
                f"旧的那份进了垃圾桶 {one.replaced['trash_path']}"
            )
        if one.note:
            lines.append(f"        {one.note}")
    if not report.done:
        lines.append(f"什么也没做成（{report.op}）。")
    return "\n".join(lines)


def _finish(report: ops.Report, as_json: bool) -> None:
    """把结果交出去，并让退出码和它一致。

    一次没做成的操作 MUST 是非零退出码：总线那头读的就是这个数，
    ``ok: false`` 配上 ``exit 0`` 等于没人被告知。
    """
    if as_json:
        click.echo(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        click.echo(_render(report))
        for failure in report.failed:
            echo_business_error(failure.why, *failure.fixes)
    if not report.ok:
        sys.exit(1)


def _split(paths: tuple[str, ...], command: str) -> tuple[list[Path], Path]:
    if len(paths) < 2:
        raise BusinessError(
            f"{command} 要至少两个路径：来源在前，目标在最后。",
            f"frago {command} <来源> <目标>",
        )
    return [Path(p) for p in paths[:-1]], Path(paths[-1])


@click.command("cp", cls=AgentFriendlyCommand)
@click.argument("paths", nargs=-1, required=True, type=click.Path())
@click.option("-r", "-R", "--recursive", "recursive", is_flag=True,
              help="Copy directories, as unix requires for a tree")
@click.option("-n", "--no-clobber", "no_clobber", is_flag=True,
              help="Leave an existing destination alone instead of replacing it")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def cp_command(paths: tuple[str, ...], recursive: bool, no_clobber: bool,
               as_json: bool) -> None:
    """Copy files and directories. Unix cp.

    \b
    Runs in the server's process tree, so a recipe can reach a file its own
    confined view does not contain: self.ask_frago(["cp", src, dst]).

    \b
    Unix semantics, with one difference: replacing an existing destination puts
    the old one in the system trash instead of destroying it.

    \b
    Examples:
      frago cp a.txt b.txt
      frago cp a.txt b.txt ~/notes/          # several sources, existing dir last
      frago cp -r ~/project ~/backup/
      frago cp -n a.txt b.txt                # do not replace b.txt
    """
    sources, destination = _split(paths, "cp")
    _finish(ops.copy(sources, destination, recursive=recursive,
                     no_clobber=no_clobber), as_json)


@click.command("mv", cls=AgentFriendlyCommand)
@click.argument("paths", nargs=-1, required=True, type=click.Path())
@click.option("-n", "--no-clobber", "no_clobber", is_flag=True,
              help="Leave an existing destination alone instead of replacing it")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def mv_command(paths: tuple[str, ...], no_clobber: bool, as_json: bool) -> None:
    """Move or rename files and directories. Unix mv — cut and paste.

    \b
    Unix semantics, with one difference: replacing an existing destination puts
    the old one in the system trash instead of destroying it.

    \b
    Examples:
      frago mv draft.md final.md
      frago mv a.txt b.txt ~/notes/          # several sources, existing dir last
      frago mv ~/project ~/archive/
    """
    sources, destination = _split(paths, "mv")
    _finish(ops.move(sources, destination, no_clobber=no_clobber), as_json)


@click.command("rm", cls=AgentFriendlyCommand)
@click.argument("paths", nargs=-1, required=True, type=click.Path())
@click.option("-r", "-R", "--recursive", "recursive", is_flag=True,
              help="Delete directories, as unix requires for a tree")
@click.option("-f", "--force", "force", is_flag=True,
              help="A path that is not there is not an error")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def rm_command(paths: tuple[str, ...], recursive: bool, force: bool,
               as_json: bool) -> None:
    """Delete into the system trash instead of destroying the file.

    \b
    Unix rm, except that it is a move rather than an unlink: the target goes
    to this machine's trash (~/.Trash on macOS, the freedesktop trash on Linux)
    and stays there until somebody empties it, so a wrong path is still
    something its owner can open the trash and drag back out. frago does not
    put it back for you. There is no flag that makes this an unlink.

    \b
    Examples:
      frago rm notes.txt
      frago rm -r ~/old-project
      frago rm -f maybe-there.txt            # missing is not an error
    """
    _finish(ops.remove([Path(p) for p in paths], recursive=recursive, force=force),
            as_json)
