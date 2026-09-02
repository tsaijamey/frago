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

**The rule is enforceable.** A module may only be asked for a mode marked
``@export``, and an exported mode is read-only by contract. A child process
cannot be told no; a request through a hub can.

**The dependency is declared on both sides.** The caller declares what it
imports; the hub checks the callee exports it. Neither side can acquire a
dependency the other has not agreed to.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import re
import threading
import time
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


class FragoRequest(BaseModel):
    #: The words that would come after ``frago`` on a terminal, as a list.
    #:
    #: A list rather than a string, and the difference is not stylistic. A
    #: string has to be split by something, and whatever splits it has to make
    #: decisions about quoting — at which point an account named with an
    #: apostrophe, or a page name with a space, becomes a parse question with a
    #: security answer. A list never gets assembled into a line, so there is no
    #: line for anything to break out of.
    argv: list[str] = Field(..., min_length=1, max_length=64)
    timeout: int = Field(default=120, ge=1, le=600)


class PublishRequest(BaseModel):
    recipe: str
    slot: str = "default"
    state: dict[str, Any]


class OpenRequest(BaseModel):
    url: str


#: How long an unremarkable repeat is folded into a count before it is written
#: down again. A page polling a module for progress crosses the hub every two
#: seconds; two days of that produced 49366 records saying the same 56 things,
#: and buried the 52 records that had something to say under 99.89% noise.
_ROLLUP_WINDOW_SECONDS = 3600

#: (caller, callee, mode) -> what has happened since it was last written down.
_rollup: dict[tuple[str, str, str], dict[str, Any]] = {}
_rollup_lock = threading.Lock()


def _append_edge(entry: dict[str, Any]) -> None:
    try:
        p = edges_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as err:  # recording must never be why a call fails
        logger.warning("bus: could not record edge: %s", err)


def _record_edge(caller: str, callee: str, mode: str, ok: bool, why: str = "") -> None:
    """Write down that this crossing happened, whether or not it was allowed.

    Refusals are recorded too, and are the more useful half: a module reaching
    for something it never declared is a dependency somebody is about to add by
    accident, and this is the only moment anyone can see it.

    **What gets a line of its own and what gets counted.** The question this
    ledger answers — did anything depend on this module before I changed it — is
    about which crossings exist, not how many times each one happened. A page
    polling for progress asks the same question every two seconds and every
    answer was written down in full, so the file grew 3.75 MB a day to say 56
    things, and a reader looking for the handful of refusals had to find them in
    it. So: anything carrying a ``why`` — a refusal, a failure, a path handed
    out in a return value — is written in full every time, because none of those
    is a repeat of anything. A crossing that simply worked is written the first
    time it is seen, and after that folded into a count that lands once a window.

    First sighting is written immediately rather than waiting for the window to
    close: a dependency that just appeared is the event worth seeing, and a
    record that only exists in memory is lost if the server stops first.
    """
    from datetime import datetime

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    caller = caller or "(unknown)"
    entry = {"when": now, "caller": caller, "callee": callee,
             "mode": mode, "allowed": ok, "why": why}

    if not ok or why:
        _append_edge(entry)
        return

    key = (caller, callee, mode)
    pending: dict[str, Any] | None = None
    with _rollup_lock:
        state = _rollup.get(key)
        if state is None:
            _rollup[key] = {"opened": time.monotonic(), "opened_at": now,
                            "repeats": 0, "last": now}
            pending = entry | {"times": 1}
        else:
            state["repeats"] += 1
            state["last"] = now
            if time.monotonic() - state["opened"] >= _ROLLUP_WINDOW_SECONDS:
                pending = _close_window(key, state)
    if pending is not None:
        _append_edge(pending)


def _close_window(key: tuple[str, str, str], state: dict[str, Any]) -> dict[str, Any]:
    """Turn what has piled up for one crossing into a single line. Lock held."""
    caller, callee, mode = key
    line = {"when": state["last"], "caller": caller, "callee": callee,
            "mode": mode, "allowed": True, "why": "",
            "times": state["repeats"], "since": state["opened_at"]}
    state["opened"] = time.monotonic()
    state["opened_at"] = state["last"]
    state["repeats"] = 0
    return line


@atexit.register
def _flush_rollups() -> None:
    """Write down what was still being counted when the process went away.

    Without this the last window of every crossing is lost on every restart —
    small, but it is the most recent evidence that a dependency is still live,
    which is exactly what somebody about to change a module wants to know.
    """
    with _rollup_lock:
        lines = [_close_window(k, s) for k, s in _rollup.items() if s["repeats"]]
    for line in lines:
        _append_edge(line)


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

    from frago.recipes.contract import exports_of

    exports = exports_of(req.recipe, req.mode)

    if exports is None:
        _record_edge(caller, req.recipe, req.mode, False, "callee-is-not-a-module")
        raise HTTPException(
            status_code=403,
            detail=(f"{req.recipe} 不是一个建在基类上的模块，别的模块调不了它。"
                    f"先把它改造成配方模块（frago book recipe-creation），"
                    f"再在要开放的 mode 方法上标 @export——"
                    f"导出的 mode 必须只读：不触网、不重算、不改状态、不开浏览器。"),
        )
    if req.mode not in exports:
        _record_edge(caller, req.recipe, req.mode, False, "mode-not-exported")
        raise HTTPException(
            status_code=403,
            detail=(f"{req.recipe} 没有把 {req.mode} 导出，它导出的是 "
                    f"{'、'.join(exports) or '（一个都没有）'}。"
                    f"要开放就在 mode_{req.mode} 上标 @export。"
                    f"没标的 mode 一律不对外——那里面的活不是给别人顺手调的，"
                    f"而 @action 只开给这个配方自己的页面，不开给别的模块。"),
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


#: Environment a recipe's run carries that must not reach the command the hub
#: runs for it. These say "you are this recipe's run, for this person, writing
#: here" — true of the caller, false of the command, and a nested
#: ``frago recipe run`` that inherited them would take the caller's landing spot
#: for its own and write another module's output into it.
_CALLER_ONLY_ENV = ("FRAGO_RECIPE_CALLER", "FRAGO_RECIPE_SLOT", "FRAGO_RECIPE_DATA_DIR",
                    "FRAGO_RECIPE_COMMON_DIR", "FRAGO_BUS_URL", "FRAGO_BUS_TOKEN",
                    "FRAGO_EXECUTION_ID", "FRAGO_CURRENT_RUN")


def _command_path(argv: list[str]) -> str:
    """The command being run, for the ledger: the words before the first flag.

    ``["recipe", "expose", "x", "--allow", "a@b"]`` reads as ``recipe expose``.
    Recorded rather than the whole line because the ledger's question is which
    crossings exist, and the arguments are the part that differs every time —
    keeping them would defeat the roll-up and turn one busy page into megabytes
    of near-identical lines.
    """
    words = []
    for token in argv:
        if token.startswith("-"):
            break
        words.append(token)
        if len(words) == 2:
            break
    return " ".join(words) or "(empty)"


@router.post("/frago")
async def bus_frago(req: FragoRequest, request: Request):
    """A recipe asking the platform to run one of its own commands.

    **Why this exists.** Recipes have always driven frago's commands — it is the
    documented way for one to do anything the platform owns. Confinement did not
    forbid that; it did something worse. The command still ran, still exited 0,
    and answered out of a filesystem view that has none of the platform's own
    books in it. ``frago user list`` inside a recipe returns ``{"users": []}`` on
    a machine with 23 accounts, and the access console drew an empty table under
    a heading that said everything was fine.

    So the command runs here instead, in the server's process tree, which is not
    confined. Nothing is handed to the recipe: no path, no directory, no key. It
    asks for something to be done and gets back what the command printed.

    **The recipe never names the program.** It supplies only the words after
    ``frago``, and this picks the interpreter — the server's own. A recipe cannot
    run ``ls``, cannot run a differently-versioned frago, and cannot reach a
    shell, because no line of shell is ever assembled.

    **What this deliberately does not do is filter the command.** An earlier
    design had tiers — some commands never reachable, some grantable per recipe,
    some open. It was wrong twice over. It sorted commands by how alarming their
    names were rather than by what they actually cross, and it protected a
    machine whose recipes already run as their owner holding a full interpreter:
    a recipe that means harm does not need ``frago def remove``, it has Python.
    The trust decision this rides on is the one that already exists and is
    already asked at the right moment — marking a mode ``@action`` means "this
    source is one I would let other people press".

    The two things that replace a filter are both here: every call is written to
    the ledger with the command it ran, and every call goes through one function,
    so a reviewer sees a recipe's whole reach over the platform in one place
    instead of reading all of its Python.
    """
    import os
    import subprocess
    import sys

    caller = request.headers.get("X-Frago-Recipe", "") or "(unknown)"
    command = _command_path(req.argv)

    # NUL cannot survive the trip into execve, and a caller sending one is
    # either broken or probing. Refused by name so it reads as a rejection
    # rather than a mangled command.
    if any("\0" in word for word in req.argv):
        _record_edge(caller, "frago", command, False, "argv-contains-nul")
        raise HTTPException(status_code=400, detail="参数里不能有 NUL 字节")

    env = {k: v for k, v in os.environ.items() if k not in _CALLER_ONLY_ENV}

    def _run() -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "frago", *req.argv],
            capture_output=True, text=True, timeout=req.timeout, env=env,
            # No terminal, on purpose. `frago user passwd` reads a hidden
            # password; over this door there is nobody to type it. Given a
            # closed stdin it fails at once and says so, where an inherited one
            # would hold a thread until the timeout and report nothing useful.
            stdin=subprocess.DEVNULL,
            # The server's own directory, never the caller's. A relative path in
            # the command would otherwise resolve inside whichever run happened
            # to be asking.
            cwd=str(Path.home()),
        )

    try:
        # Off the event loop: these are whole processes, and one of them may be
        # `frago recipe run`, which comes back through this same server.
        done = await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired:
        _record_edge(caller, "frago", command, True, f"timeout after {req.timeout}s")
        return {"ok": False, "code": 124, "stdout": "",
                "stderr": f"frago {command} 超过 {req.timeout}s 没有返回"}
    except Exception as err:
        logger.exception("bus: frago %s failed for %s", command, caller)
        _record_edge(caller, "frago", command, True, f"failed: {err}")
        return {"ok": False, "code": 127, "stdout": "", "stderr": str(err)}

    # A non-zero exit is the command answering, not the door failing, so it
    # comes back as data. The caller reads the code the same way it would have
    # read it from its own subprocess — which is the whole point: the migration
    # for an existing recipe is one function, not a rewrite.
    _record_edge(caller, "frago", command, True,
                 "" if done.returncode == 0 else f"exit {done.returncode}")
    return {"ok": True, "code": done.returncode,
            "stdout": done.stdout, "stderr": done.stderr}


@router.post("/publish")
async def bus_publish(req: PublishRequest, request: Request):
    """A module telling its page what to render. Render state only, no paths.

    Goes through the same state layer the ``frago recipe publish`` command uses.
    The first version of this called a function that did not exist, and every
    publish came back as a 500 — the page skeleton the template generates was
    dead on arrival and nothing said why, because ``frago recipe validate``
    reads files and cannot know that an endpoint answers with an error.

    **Whose page is being written is decided here, not by the caller.**
    ``app_state.publish`` answers that question by reading the environment of
    the process it is running in — which works perfectly inside a recipe and is
    exactly wrong here, because the process it is running in is the server. A
    recipe started for a signed-in visitor therefore published into the
    *recipe's own* slot: the visitor's page stayed empty however many times they
    pressed the button, and the owner's page was overwritten by a stranger's
    render state without anybody being told. ``bus_ask`` had the same hole on
    the reading side and was closed on 2026-08-26 with the same key — the
    execution id the caller carries, looked up in the runs this process started,
    never a header the caller could choose. This is that fix for the other verb.

    A visitor's slot is their account id and is never named in a URL: the access
    gate decides it, and ``?key=`` is the owner's control alone. So the address
    handed back for a visitor's publish carries no key.
    """
    from frago.recipes.app_state import DEFAULT_SLOT, InvalidSlotName, page_url, publish
    from frago.recipes.runner import context_of_execution

    slot, identity, state = req.slot, False, req.state
    ran_for = context_of_execution(request.headers.get("X-Frago-Execution", ""))
    if ran_for is not None and ran_for.is_visitor and ran_for.slot:
        # The same three substitutions `app_state.publish` makes for a recipe
        # that can see its own environment. `dataDir` in particular is replaced
        # rather than defaulted: a recipe that hard-codes the owner's directory
        # would otherwise publish that path into a visitor's slot, and
        # `/app/<name>/data/…` would serve the owner's files to that visitor,
        # rendering perfectly and silently.
        slot, identity = ran_for.slot, True
        state = {**req.state, "dataDir": str(ran_for.data_dir)}

    try:
        publish(req.recipe, state, slot, identity=identity)
        url = page_url(req.recipe, DEFAULT_SLOT if identity else slot)
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
