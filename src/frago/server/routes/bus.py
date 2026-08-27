"""The hub every recipe talks through.

A recipe is a module. What makes a set of modules a system rather than a pile
of scripts is that there is one place where their interactions happen, and that
place knows what happened.

Before this, a recipe that needed another recipe's data read its files. That
worked and was invisible: the module being read had nothing telling it anybody
depended on its layout, so its author edited their own files and a page they
had never heard of started showing stale numbers. The break landed somewhere
unrelated to the change, and only when a person happened to open that page. One
ledger ended up in four places on one machine this way, holding 48, 45, 45 and
37 trades, with the page showing the three-day-old copy and reporting every
refresh as a success.

So every crossing goes through here, and three things follow that could not
follow from recipes calling each other directly:

**The edge is recorded.** Who asked whom, for what. The dependency graph is
something the system holds, not something somebody would have to reconstruct.

**The rule is enforceable.** A module may only be asked for a mode it exported,
and exported modes are read-only by contract. A child process cannot be told
no; a request through a hub can.

**The dependency is declared on both sides.** The caller declares what it
imports; the hub checks the callee exports it. Neither side can acquire a
dependency the other has not agreed to.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/bus", tags=["bus"])

#: Where the hub writes down who asked whom. Append-only: the question it
#: answers — "did anything depend on this module before I changed it" — gets
#: asked months later, and a file that gets rewritten can lose exactly the
#: entry somebody is looking for.
EDGES_NAME = "bus-edges.jsonl"


def edges_path() -> Path:
    return Path.home() / ".frago" / EDGES_NAME


#: Anything that reads as a place on this machine. Deliberately broad: a false
#: positive costs an author one reworded field, a miss hands the front end a
#: path into the back end's filesystem.
#: A single line that is entirely a path. Anchored at both ends and limited to
#: one line, because the first version matched anything beginning with a slash
#: and flagged a module returning the *contents* of a JavaScript file — the text
#: opened with `/**`. A rule that cannot tell a path from a comment will be
#: switched off by the first person it inconveniences.
_LOOKS_LIKE_A_PATH = re.compile(r"^(/|~/|[A-Za-z]:[\\/])[^\n\r]{0,4096}$")


def strip_paths(value, _where: str = "") -> list[str]:
    """Find filesystem paths in what a module is about to hand out.

    The base class already refuses paths in the render state a module
    publishes. That covered one of the two ways a path reaches a page and not
    the other: an exported mode's **return value** goes to the same front end,
    through a different door, and was unchecked. An audit found two modes
    handing the owner's absolute paths to the page that way.

    Reported rather than stripped. Removing the field silently would leave a
    page rendering a blank where something used to be, with nothing anywhere
    saying why — the same quiet wrongness this whole contract exists to remove.
    """
    found = []
    if isinstance(value, dict):
        for k, v in value.items():
            found += strip_paths(v, f"{_where}.{k}" if _where else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found += strip_paths(v, f"{_where}[{i}]")
    elif isinstance(value, str) and _LOOKS_LIKE_A_PATH.match(value.strip()):
        found.append(f"{_where} = {value!r}")
    return found


class AskRequest(BaseModel):
    recipe: str = Field(..., description="被问的模块")
    mode: str = Field(..., description="要它的哪个导出接口")
    params: dict[str, Any] = Field(default_factory=dict)
    #: What the caller declared it imports. Sent by the caller and checked here
    #: rather than there: a module reaching for something it never declared is
    #: the one event worth seeing, and a check that runs inside the caller is
    #: invisible to everyone else and skippable by anything not built on the
    #: base class.
    caller_imports: dict[str, list[str]] = Field(default_factory=dict)


class PublishRequest(BaseModel):
    recipe: str
    slot: str = "default"
    state: dict[str, Any]


class OpenRequest(BaseModel):
    url: str


def _record_edge(caller: str, callee: str, mode: str, ok: bool, why: str = "") -> None:
    """Write down that this crossing happened, whether or not it was allowed.

    Refusals are recorded too, and are the more useful half: a module reaching
    for something it never declared is a dependency somebody is about to add by
    accident, and this is the only moment anyone can see it.
    """
    from datetime import datetime

    entry = {
        "when": datetime.now().astimezone().isoformat(timespec="seconds"),
        "caller": caller or "(unknown)",
        "callee": callee,
        "mode": mode,
        "allowed": ok,
        "why": why,
    }
    try:
        p = edges_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as err:  # recording must never be why a call fails
        logger.warning("bus: could not record edge: %s", err)


def _exports_of(recipe_name: str, wanted: str | None = None) -> tuple[str, ...] | None:
    """Which modes this module offers other modules, read off its own source.

    None when the module never declared an exported surface — which is not the
    same as declaring an empty one. A module that has said nothing has not
    agreed to anything, and the hub says so rather than assuming either way.

    ``wanted`` is the mode about to be checked. It is passed in for one reason:
    a snapshot can be stale in two ways, and until now only one of them was
    handled. A recipe missing from the snapshot got a second look; a recipe
    **present in the snapshot with an older export list** did not, and was
    refused with "this module does not export that" — a sentence that blames
    the recipe when the stale list is the actual problem. That is the same
    failure the paragraph below was written about, one step further along:
    adding an export and being told it does not exist is indistinguishable
    from never having added it.
    """
    from frago.recipes.exceptions import RecipeNotFoundError
    from frago.recipes.registry import get_registry, invalidate_registry

    def _look() -> tuple[str, ...] | None:
        try:
            recipe = get_registry().find(recipe_name)
        except (RecipeNotFoundError, OSError):
            return None
        declared = getattr(recipe.metadata, "exports", None)
        if declared:
            return tuple(declared)
        script = getattr(recipe, "script_path", None)
        if not script or not Path(script).exists():
            return None
        return _exports_from_source(
            Path(script).read_text(encoding="utf-8", errors="ignore"))

    found = _look()

    # Look again before refusing — but only when the answer would be a refusal.
    # Re-scanning on every call would make the hub walk the recipe tree for each
    # question anybody asks, and the overwhelmingly common answer (yes, it is
    # exported) is already correct from the snapshot.
    if found is None or (wanted is not None and wanted not in found):
        invalidate_registry()
        found = _look()

    return found


def _exports_from_source(source: str) -> tuple[str, ...] | None:
    """Read the `exports` declaration without executing the module.

    Parsed rather than imported: importing a recipe to find out what it offers
    would run whatever sits at its module level, on a machine where no run is
    in progress, every time anybody asked it a question.
    """
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            targets = (
                [stmt.target] if isinstance(stmt, ast.AnnAssign)
                else getattr(stmt, "targets", [])
            )
            for t in targets:
                if isinstance(t, ast.Name) and t.id == "exports":
                    value = getattr(stmt, "value", None)
                    if isinstance(value, (ast.Tuple, ast.List)):
                        names = [
                            e.value for e in value.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)
                        ]
                        return tuple(names)
    return None


@router.post("/ask")
async def bus_ask(req: AskRequest, request: Request):
    """One module asking another for data.

    Refused unless the target exported that mode. The refusal is the point:
    exported modes are read-only by contract, so a caller can never reach past
    the surface into a mode that fetches, recomputes or changes state. A status
    check that fell through to a default once landed inside a state machine and
    went and called a live API.
    """
    caller = request.headers.get("X-Frago-Recipe", "")

    # Did the caller declare this dependency? Refused here rather than in the
    # caller, so the reach shows up in the ledger either way — an undeclared
    # attempt is somebody about to acquire a dependency by accident, and this
    # is the only moment it is visible to anyone but the module doing it.
    wanted = req.caller_imports.get(req.recipe)
    if wanted is None:
        _record_edge(caller, req.recipe, req.mode, False, "caller-did-not-declare")
        raise HTTPException(
            status_code=403,
            detail=(f"{caller or '调用方'} 没有声明依赖 {req.recipe}，不能问它要数据。"
                    f"在类上写 imports = {{'{req.recipe}': ('{req.mode}',)}}——"
                    f"依赖写下来，对方才知道自己正在被谁读。"),
        )
    if req.mode not in wanted:
        _record_edge(caller, req.recipe, req.mode, False, "caller-declared-other-modes")
        raise HTTPException(
            status_code=403,
            detail=(f"{caller or '调用方'} 声明依赖 {req.recipe} 时没有写 {req.mode}，"
                    f"只写了 {'、'.join(wanted) or '（空）'}"),
        )

    exports = _exports_of(req.recipe, req.mode)

    if exports is None:
        _record_edge(caller, req.recipe, req.mode, False, "callee-has-no-exports")
        raise HTTPException(
            status_code=403,
            detail=(f"{req.recipe} 没有声明任何导出接口，别的模块调不了它。"
                    f"要把它变成可被调用的，在它的类上写 exports = ('status', ...)，"
                    f"并且导出的 mode 必须是只读的：不触网、不重算、不改状态、不开浏览器。"),
        )
    if req.mode not in exports:
        _record_edge(caller, req.recipe, req.mode, False, "mode-not-exported")
        raise HTTPException(
            status_code=403,
            detail=(f"{req.recipe} 没有把 {req.mode} 导出，它只导出了 "
                    f"{'、'.join(exports) or '（空）'}。"
                    f"没导出的 mode 一律不对外——那里面的活不是给别人顺手调的。"),
        )

    # The callee runs as whoever the caller was running as.
    #
    # Without this the chain loses the person at the first hop: a signed-in
    # visitor's page asks its own recipe for data, that recipe asks the module
    # that holds the book, and the hub started that second module as the
    # machine. The page then showed the machine's book while the person's own
    # writes went to their own — two books, one page, no error anywhere.
    # Observed on the server 2026-08-26.
    #
    # The identity comes from the execution id the caller carries, looked up in
    # the runs this process started, never from a header the caller could
    # choose. A run this process did not start (the CLI, another machine) has no
    # entry and falls back to the owner, exactly as before.
    # **The identity travels; the directory is recomputed.** Handing the
    # caller's context straight over would point the callee at the *caller's*
    # directory — the ledger opening the history page's folder, finding no book,
    # and reporting an empty one. What carries is who this is for; where that
    # person's data for *this* module lives is this module's own answer.
    from frago.recipes import context as run_context
    from frago.recipes.runner import context_of_execution
    from frago.server.services.recipe_service import RecipeService

    ctx = None
    asked_by = context_of_execution(request.headers.get("X-Frago-Execution", ""))
    if asked_by is not None and asked_by.slot:
        try:
            ctx = (run_context.for_visitor(req.recipe, asked_by.slot)
                   if asked_by.is_visitor else run_context.for_owner(req.recipe))
        except Exception:
            # Could not work out where this module keeps that person's data.
            # Running it as the machine instead would answer out of the wrong
            # directory without saying so — the exact failure this passes
            # identity to prevent — so refuse the hop and name it.
            logger.warning("bus: cannot place %s for slot %s", req.recipe, asked_by.slot,
                           exc_info=True)
            _record_edge(caller, req.recipe, req.mode, True, "no-landing-spot-for-caller")
            return {"ok": False, "error": {"code": "callee-failed", "message":
                    f"定不出 {req.recipe} 给这个人的数据落在哪，这次不问了——"
                    f"换成按本机身份去问，会答出别人的数据而且不报错。"}}

    try:
        # Off the event loop. The callee is a whole recipe run, and modules
        # chain: A asks B, B asks C, and every hop lands back on this server.
        # Called inline, the loop is blocked waiting for a recipe that is
        # waiting for the loop — the server stops answering anything at all.
        result = await asyncio.to_thread(
            RecipeService.run_recipe, req.recipe, req.params | {"mode": req.mode}, 300, ctx
        )
    except Exception as err:
        _record_edge(caller, req.recipe, req.mode, True, f"failed: {err}")
        return {"ok": False, "error": {"code": "callee-failed", "message": str(err)}}

    if isinstance(result, dict) and result.get("status") == "error":
        _record_edge(caller, req.recipe, req.mode, True, "callee-said-no")
        err = result.get("error")
        message = err.get("message") if isinstance(err, dict) else err
        return {"ok": False, "error": {"code": "callee-failed",
                                       "message": str(message or f"{req.recipe} 没有给出结果")}}

    _record_edge(caller, req.recipe, req.mode, True)
    data = result.get("data") if isinstance(result, dict) else result
    out = data if isinstance(data, dict) else {"result": data}
    # Two callers, two rules, because the risk is not the same.
    #
    # A page runs in a browser: it has no filesystem to open a path with, and
    # whoever opened the page gets a description of the server's directory
    # layout for free. That is refused outright, next door in `app_pages`.
    #
    # A module runs on this machine and may legitimately be told where
    # something is — a data feed reporting its cache location is diagnostic,
    # not a leak. Refusing it here broke six recipes at once the moment it was
    # tried. So it is recorded and left alone: visible in the ledger for
    # anybody auditing what crosses the hub, and not a rule that fires on the
    # case it was never aimed at.
    leaked = strip_paths(out)
    if leaked:
        _record_edge(caller, req.recipe, req.mode, True,
                     f"paths-in-return: {'; '.join(leaked[:2])}")
    return {"ok": True, "data": out}


@router.post("/publish")
async def bus_publish(req: PublishRequest):
    """A module telling its page what to render. Render state only, no paths.

    Goes through the same state layer the ``frago recipe publish`` command uses.
    The first version of this called a function that did not exist, and every
    publish came back as a 500 — the page skeleton the template generates was
    dead on arrival and nothing said why, because ``frago recipe validate``
    reads files and cannot know that an endpoint answers with an error.
    """
    from frago.recipes.app_state import InvalidSlotName, page_url, publish

    try:
        publish(req.recipe, req.state, req.slot)
        url = page_url(req.recipe, req.slot)
    except InvalidSlotName as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except Exception as err:
        logger.exception("bus: publish failed for %s", req.recipe)
        raise HTTPException(status_code=500, detail=str(err)) from err
    return {"ok": True, "url": url}


@router.post("/open")
async def bus_open(req: OpenRequest):
    from frago.viewer.browser import open_url

    try:
        return {"ok": bool(open_url(req.url))}
    except Exception as err:
        logger.warning("bus: open failed: %s", err)
        return {"ok": False}
