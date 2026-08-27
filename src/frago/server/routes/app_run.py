"""The one thing a signed-in visitor may make this server do.

Until now the identity zone could only make the server read files off disk. This
route changes that: it starts a process. That is a change of kind rather than of
degree, so it is a route of its own rather than a visitor branch inside
``/api/recipes/<name>/run``.

The reason is not tidiness. That endpoint's contract is "the owner runs anything
with anything", and every check along its path is written on the assumption that
the caller is the owner. A visitor branch inside it would mean every future edit
there has to re-derive whether the visitor case still holds — and it sits in
``/api``, which is the owner's control plane. The previous audit made the same
call about the anonymous POST allowlist, listing it as one exact (method, path)
pair rather than a prefix: entrances get added one at a time, and the person
adding one should be able to see that they are adding it.

What a visitor gets back is ``{"accepted": true}`` and nothing else. The recipe's
return value is an arbitrary dict that routinely carries absolute paths and
internal identifiers, and filtering it would mean inventing a second disclosure
rule beside the one that already exists — the ``public`` block of the slot. A
recipe with something to say to the page says it there, and the page reads the
result out of the visitor's own data directory.
"""

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from frago.server.security import VisitorSafeHTTPException as VisitorSafe

router = APIRouter()
logger = logging.getLogger(__name__)

# The name the platform keeps for itself inside a visitor's data directory.
# A recipe writing its own progress file is welcome to; this one exists so the
# page has a terminal state even when the recipe writes nothing at all, which
# no convention can guarantee.
RUN_STATE_FILE = "run.json"

# One run at a time per (recipe, account). Not global: two people running the
# same recipe is the ordinary case and must stay possible.
_gate_lock = threading.Lock()
_running: dict[tuple[str, str], float] = {}

# At most this many concurrent runs per account, counted across every page.
#
# The per-(recipe, account) key above only stops one account starting the *same*
# page twice. It says nothing about that account starting a run on each distinct
# runnable page it can reach — and a fresh, zero-trust account reaches two here
# (both allow-lists are empty). Two such runs fill the whole visitor pool
# (`MAX_VISITOR_WORKERS`), and from then on every other visitor's run is refused
# with 503. One signed-in account thus locks the run button for everyone.
# Demonstrated end to end on the live server, 2026-08-20: account A holding a
# slot, account B's runs coming back 503.
#
# So the cap is per account, not per page: the pool's slots go to distinct
# people, and no single account can hold more than one at a time. Two different
# accounts still run at once, which is the case the pool exists to serve.
MAX_RUNS_PER_ACCOUNT = 1


def _gate_ttl(timeout: int | None) -> float:
    """How long a claim stays valid before it is treated as abandoned.

    A lock released in a ``finally`` is released almost always — but "almost"
    here means an account that can never run this recipe again, because nothing
    else will ever clear the entry. The process can be killed, the interpreter
    can go down between the two statements. So the claim carries a deadline
    generous enough never to cut a real run short and short enough that a lost
    release costs one wait rather than forever.
    """
    return float(timeout or 300) * 2 + 60


def _account_at_limit(identity: str, now: float, besides: tuple[str, str]) -> bool:
    """Whether this account already holds its share of live run slots.

    Counts only claims that have not passed their deadline: an abandoned claim
    (see `_gate_ttl`) must not lock the account out forever. `besides` is this
    request's own key, excluded so a still-valid claim on the same page reads as
    the "same page again" refusal above rather than the per-account one.
    """
    live = 0
    for other, deadline in _running.items():
        if other != besides and other[1] == identity and now < deadline:
            live += 1
    return live >= MAX_RUNS_PER_ACCOUNT


def _claim(key: tuple[str, str], timeout: int | None) -> bool:
    now = time.time()
    with _gate_lock:
        held = _running.get(key)
        if held is not None and now < held:
            return False
        if _account_at_limit(key[1], now, besides=key):
            return False
        _running[key] = now + _gate_ttl(timeout)
        return True


def _release(key: tuple[str, str]) -> None:
    with _gate_lock:
        _running.pop(key, None)


def _write_run_state(data_dir: Path, **fields: Any) -> None:
    """Record where this run got to, for the page to poll.

    Best effort by design: a run whose state file cannot be written is still a
    run, and failing it here would turn a full disk into a wrong answer rather
    than a slow one.
    """
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        payload = {"updated": datetime.now().astimezone().isoformat(timespec="seconds")}
        payload.update(fields)
        tmp = data_dir / f".{RUN_STATE_FILE}.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(data_dir / RUN_STATE_FILE)
    except OSError:
        logger.exception("could not record run state under %s", data_dir)


def _visitor_error(exc: BaseException) -> str:
    """What a visitor is told when their run fails.

    Never the exception text: recipe failures quote paths, and the paths are the
    server's. The class name says which sort of thing went wrong without saying
    anything about this machine.
    """
    return {
        "TimeoutError": "the run took too long and was stopped",
        "RecipeValidationError": "the recipe refused these parameters",
    }.get(type(exc).__name__, "the run failed")


@router.post("/{name}/run")
async def run_for_visitor(name: str, request: Request):
    """Start a run on behalf of the signed-in visitor who asked for it.

    The order of the checks is the contract, and it is cheapest-and-most-final
    first: whether this page may be run at all, then whether this person may run
    it, then whether the parameters are acceptable, and only then whether they
    already have one going. Nothing here starts a process until all four have
    passed.
    """
    from frago.recipes import app_state, context
    from frago.recipes.exceptions import RecipeNotFoundError, RecipeValidationError
    from frago.recipes.metadata import validate_params
    from frago.recipes.publish import allows, published_entry
    from frago.recipes.registry import get_registry, invalidate_registry
    from frago.server.security import slot_for, zone_of

    if zone_of(request) != "identity":
        # The gate should already have refused, so reaching here means the gate
        # and this route disagree about who may be here. Refuse rather than
        # trust the one that admitted them.
        raise HTTPException(status_code=401, detail="not available")

    identity = slot_for(request)
    entry = published_entry(name)
    if entry is None or not entry.get("runnable") or not allows(entry, identity):
        # One answer for three different failures: not published, published but
        # not runnable, runnable but not for you. Telling them apart would say
        # which pages exist and who is on their lists.
        raise HTTPException(status_code=404, detail="not available")

    # The registry is a process-wide singleton scanned once at startup, so a
    # recipe edited after the server came up is still described here by the
    # metadata it had then. Everywhere else that costs nothing: the owner's
    # validation is loose, so an input declared after the scan passes anyway.
    # Here it is the whole difference between working and refused — strict
    # validation rejects exactly the keys the stale snapshot has not heard of,
    # and the page sending them is the one shipped alongside the edit. The
    # symptom is a visitor told a parameter "is not declared by this recipe"
    # while the recipe on disk plainly declares it, and it lasts until some
    # other route happens to rescan.
    registry = get_registry()
    try:
        if registry.needs_rescan():
            invalidate_registry()
            registry = get_registry()
    except OSError:
        # Only the freshness check failed; the snapshot in hand is still a
        # usable answer, and refusing the run over it would be worse.
        logger.warning("could not check the recipe registry for changes", exc_info=True)
    try:
        recipe = registry.find(name)
    except RecipeNotFoundError:
        raise HTTPException(status_code=404, detail="not available") from None

    body = {}
    if await request.body():
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise VisitorSafe(status_code=400, detail="body must be JSON") from None
    if not isinstance(body, dict):
        raise VisitorSafe(status_code=400, detail="body must be a JSON object")
    params = body.get("params") or {}
    if not isinstance(params, dict):
        raise VisitorSafe(status_code=400, detail="params must be a JSON object")

    try:
        validate_params(recipe.metadata, params, strict=True)
    except RecipeValidationError as exc:
        # The recipe's own complaint about its own declared inputs. It names
        # parameters, not paths, so it is safe to repeat and it is the only
        # thing that lets the visitor fix their request.
        raise VisitorSafe(status_code=400, detail=str(exc)) from None

    # Where this run stands, decided in one place for both doors — the run
    # route here and the exported read-only mode a page calls. See
    # `context.for_visitor` for what having two of these cost.
    ctx = context.for_visitor(name, identity)
    data_dir = ctx.data_dir
    key = (name, identity)
    timeout = getattr(recipe.metadata, "timeout", None)
    if not _claim(key, timeout):
        # Either this page is already running for them, or another one is: a
        # visitor holds one run at a time, whichever page it is on.
        raise VisitorSafe(
            status_code=409, detail="you already have a run going; wait for it to finish"
        )

    # Written before the recipe starts, so the page has something to read on the
    # very first run. Without it `/app/<name>/data/…` answers 404 — the slot
    # declares no dataDir until something publishes one — and the page would poll
    # a directory that does not exist yet.
    #
    # Everything already in the slot is carried forward. Publishing only the
    # directory would replace the slot wholesale, and that is what turned a
    # failed run into a blank page: the run emptied the page on its way in, and
    # a run that fails never writes anything back, so the visitor was left
    # looking at nothing with no indication that anything had been lost.
    # Observed on the live server 2026-08-23: a visitor's run failed at 21:23
    # and the page they had been reading went empty until the state was restored
    # by hand a minute later. A run that succeeds replaces this state anyway, so
    # carrying the old values forward costs the successful case nothing.
    try:
        carried = dict(app_state.read(name, identity, identity=True))
        carried["dataDir"] = str(data_dir)
        app_state.publish(
            name,
            carried,
            slot=identity,
            identity=True,
        )
        _write_run_state(data_dir, state="running", started=_now(), error=None)
    except Exception:
        _release(key)
        logger.exception("could not prepare a visitor run of %s", name)
        raise HTTPException(status_code=500, detail="could not start the run") from None

    _submit(name, params, ctx, key, data_dir, timeout)
    return JSONResponse(status_code=202, content={"accepted": True})


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _submit(
    name: str,
    params: dict,
    ctx: Any,
    key: tuple[str, str],
    data_dir: Path,
    timeout: int | None,
) -> None:
    """Hand the run to a worker, with the lock and the state file in one place.

    Both live here rather than one in the runner and one in the pool, because
    splitting them is how a timeout ends up with each side assuming the other
    released the lock. One ``finally`` owns both, and it runs whether the recipe
    returned, raised, or timed out.
    """
    from frago.recipes.background import submit_visitor_run

    def _work():
        from frago.recipes.runner import RecipeRunner

        try:
            RecipeRunner().run(name, params, timeout=timeout, ctx=ctx)
            _write_run_state(data_dir, state="done", finished=_now(), error=None)
        except BaseException as exc:  # noqa: BLE001 — the terminal state must be recorded for anything
            logger.warning("visitor run of %s failed: %s", name, type(exc).__name__)
            _write_run_state(
                data_dir, state="failed", finished=_now(), error=_visitor_error(exc)
            )
        finally:
            _release(key)

    try:
        submit_visitor_run(_work)
    except Exception:
        # Never submitted, so `_work` will never run and its finally will never
        # fire. Undo the claim here or this account is locked out until the
        # deadline.
        _release(key)
        _write_run_state(
            data_dir, state="failed", finished=_now(), error="the server is too busy"
        )
        raise VisitorSafe(status_code=503, detail="too many runs in progress") from None
