"""``frago context`` —— 按关键词把一段落盘的上下文加载进当前会话。"""

from __future__ import annotations

import json

import click

from frago.context import ContextError, render, resolve_ref

from .agent_friendly import AgentFriendlyCommand, BusinessError


def _as_json(result) -> str:
    return json.dumps(
        {
            "ref": result.ref,
            "path": str(result.path),
            "matched_by": result.matched_by,
            "total_files": result.total_files,
            "total_bytes": result.total_bytes,
            "omitted_from_listing": result.omitted_from_listing,
            "also_matched": [c.name for c in result.also_matched],
            "files": [
                {
                    "rel": e.rel,
                    "size": e.size,
                    "mtime": e.mtime,
                    "text": e.text,
                    "skip_reason": e.skip_reason,
                }
                for e in result.entries
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


@click.command("context", cls=AgentFriendlyCommand)
@click.argument("ref")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option(
    "--paths-only",
    is_flag=True,
    help="Only the path + file listing, skip inlining any file contents",
)
def context_command(ref: str, json_output: bool, paths_only: bool) -> None:
    """Load a stored context by keyword: ``frago context data:<keyword>``.

    Fuzzy-matches ``<keyword>`` against directory names under ``~/.frago/data``,
    then prints the directory listing plus the full text of small index-type
    files (notebook.md / README.md / spec.md / …). Large files are listed by
    path only — read them on demand.

    \b
    Matching is layered, most certain first:
      exact name > name prefix > substring > all keyword words present >
      character subsequence (abbreviation) > difflib similarity (typos)

    \b
    When several directories match and none is an exact name, the command
    refuses to guess: it lists the candidates and exits 1, so you can come
    back with a sharper keyword.

    \b
    Examples:
      frago context data:cxmt-ipo
      frago context data:session-workbench
      frago context data:etf --paths-only
      frago context data:etf --json
    """
    try:
        result = resolve_ref(ref)
    except ContextError as exc:
        raise BusinessError(exc.message, *exc.fixes) from exc

    if paths_only:
        for entry in result.entries:
            entry.text = None
            entry.skip_reason = entry.skip_reason or "--paths-only"

    click.echo(_as_json(result) if json_output else render(result))
