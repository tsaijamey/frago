"""Recipe application pages, served under a stable human-readable address.

A recipe that has a UI is a small web application: its `assets/` directory is
the front end, and its state lives on the server side. This module serves that
application directly from the recipe's own directory at

    /app/<recipe-name>[/<file>]

Nothing is copied. The old scheme published a page by hashing something into a
`content_id`, copying `assets/` into `~/.frago/viewer/content/<hash>/`, dropping
a `config.json` next to it and handing out an unreadable URL. That coupled the
address to a single run, left the copies behind forever, and made "the page for
this recipe" impossible for a person to type from memory.

Three routes make up the contract:

    /app/<name>/              the recipe's index.html
    /app/<name>/config.json   synthesized per request, never a file on disk
    /app/<name>/data/<path>   proxied from the recipe's declared data directory
    /app/<name>/<file>        any other asset, straight from assets/

Front ends keep using relative paths (`fetch('config.json')`, `fetch('data/x.json')`),
so the page does not know it moved.

Running the same recipe twice does not mint a new address. A recipe that needs
to distinguish projects or sessions passes a key in the query string
(`/app/<name>?key=<id>`); without one, the default slot is served. State for
each slot lives in ~/.frago/app-state/<name>/<key>.json, written by the recipe
and read back here.

`?key=` is the owner's control and only the owner's. A visitor — anonymous or
signed in — is served the slot the access gate decided on, never one they named.
For a signed-in visitor that slot is their own account id, read from the
separate identity root; see `_slot_state`.
"""

import asyncio
import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from frago.recipes.app_state import DEFAULT_SLOT, InvalidSlotName
from frago.recipes.app_state import read as read_slot

logger = logging.getLogger(__name__)

router = APIRouter()


def _mime_type(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(str(path))
    return mime_type or "application/octet-stream"


# Let the browser keep its copy but check with us before using it. Editing a
# recipe's front end and seeing the previous version is a nasty class of bug:
# it looks exactly like "my change had no effect". The old scheme fought this
# by rewriting index.html to append a timestamp to every script tag, which each
# recipe had to reimplement. A validator on every response fixes it once, for
# everyone, and costs a 304 rather than a full transfer when nothing changed.
_REVALIDATE = {"Cache-Control": "no-cache"}

# Failures must never stick. A 404 is heuristically cacheable, so a page opened
# once before its data existed can keep failing on that device long after the
# data arrives — while the same account on a phone, fetching for the first time,
# works. That is exactly what happened: same page, same account, one device
# broken and the other fine, with nothing wrong on the server.
_NO_STORE = {"Cache-Control": "no-store"}


def _assets_dir(name: str) -> Path:
    """Locate a recipe's assets directory, or explain why the page can't load.

    The failure modes are worth telling apart: a recipe that does not exist at
    all, one that exists but has no front end, and one that points at a shared
    front end that isn't there. All three used to surface as a blank page.

    A recipe may borrow another recipe's assets via `ui_from` in its metadata,
    for the cases where one front end genuinely serves several recipes.
    """
    if "/" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid recipe name")

    from frago.recipes.exceptions import RecipeNotFoundError
    from frago.recipes.registry import get_registry, invalidate_registry

    try:
        recipe = get_registry().find(name)
    except RecipeNotFoundError:
        # Not in the list the server took when it started. Every recipe created
        # after that is in this position, so its page 404s the first time
        # anybody opens it — and says the recipe does not exist, which sends
        # the reader looking for a recipe that is sitting right there on disk.
        # Look again before answering.
        try:
            invalidate_registry()
            recipe = get_registry().find(name)
        except RecipeNotFoundError as err:
            raise HTTPException(
                status_code=404, detail=f"Recipe '{name}' not found"
            ) from err

    owner = getattr(recipe.metadata, "ui_from", None) or name
    if owner != name:
        if "/" in owner or ".." in owner:
            raise HTTPException(status_code=400, detail=f"Invalid ui_from: {owner}")
        try:
            recipe = get_registry().find(owner)
        except RecipeNotFoundError as err:
            raise HTTPException(
                status_code=404,
                detail=f"Recipe '{name}' borrows its UI from '{owner}', which is not installed",
            ) from err

    base_dir = recipe.base_dir or Path(recipe.script_path).parent
    assets = base_dir / "assets"
    if not assets.is_dir():
        where = f"'{owner}'" if owner != name else f"'{name}'"
        raise HTTPException(
            status_code=404,
            detail=f"Recipe '{name}' has no assets/ directory to serve (looked in {where})",
        )
    return assets


def _resolve_within(base: Path, relative: str) -> Path:
    """Resolve `relative` under `base`, refusing anything that escapes it."""
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError as err:
        raise HTTPException(status_code=403, detail="Access denied") from err
    return candidate


def _slot_state(name: str, request: Request) -> tuple[str, dict]:
    """Resolve the requested slot and read its state.

    A visitor does not get to name their own slot — neither anonymous nor
    signed-in. The access gate already worked out which slot this request is
    for and put it on the scope; reading `?key=` again here is what let
    `?key=public&key=private` be authorised against one slot and served from
    another.

    `?key=` stays exactly as it was for the owner (the local and token zones).
    It is how `app_state.page_url()` addresses a slot and what
    `frago recipe publish --slot` is built on; removing it there would break the
    owner switching between their own data, which was never the bug.

    A signed-in visitor's slot is their account id, and it lives under the
    separate identity root — the same string under `app-state/` would be one of
    the recipe's own slots, which is not theirs to read.

    Unless the page was exposed as one shared reading, in which case the gate
    authorised the recipe's own slot, which lives under the recipe's own root
    with no account in its path. Which root to look in is the gate's answer too
    (`serves_recipe_slot`), never something worked out here from the slot's name.
    """
    from frago.server.security import serves_recipe_slot, slot_for, zone_of

    zone = zone_of(request)
    visitor = zone in ("public", "identity")
    key = (slot_for(request) or DEFAULT_SLOT) if visitor else (
        request.query_params.get("key") or DEFAULT_SLOT
    )
    own_root = zone == "identity" and not serves_recipe_slot(request)
    try:
        return key, read_slot(name, key, identity=own_root)
    except InvalidSlotName as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{name}")
async def serve_app_root(name: str, request: Request):
    """Redirect to the trailing-slash form so relative paths resolve correctly.

    Without the slash the browser treats the recipe name as a file and resolves
    `fetch('config.json')` against /app/, one level too high.
    """
    _assets_dir(name)  # 404 early rather than redirecting into a dead end
    query = request.url.query
    target = f"/app/{name}/" + (f"?{query}" if query else "")
    return RedirectResponse(url=target, status_code=307)


@router.get("/{name}/config.json")
async def serve_app_config(name: str, request: Request):
    """Synthesize the page's configuration for the requested slot.

    `apiBase` is relative on purpose: a hard-coded 127.0.0.1 breaks the page for
    anyone opening it from another device on the network.

    A visitor to a published page gets a different document: only the keys the
    recipe declared public, and `apiBase: null`. The API this page would
    otherwise call can run recipes and read any file on the machine, so a
    published page is a read-only rendering of what is already in `data/`. Front
    ends check `readOnly` and hide whatever would have posted.

    The question asked here is "is this the owner", not "is this anonymous". A
    signed-in visitor is neither: they are not anonymous, and they are not the
    owner. Asking the anonymous question would drop them into the else branch
    and hand them the unfiltered slot — the absolute paths of this server's
    disk, and whatever key the recipe parked in its state. Signing in changes
    *whose* data is served, never how much of it.
    """
    _assets_dir(name)
    key, state = _slot_state(name, request)

    from frago.recipes.contract import page_actions_of
    from frago.recipes.publish import public_view
    from frago.server.security import is_owner_request, serves_recipe_slot, zone_of

    owner = is_owner_request(request)
    config = dict(state) if owner else public_view(state)
    config["apiBase"] = "/api" if owner else None
    config["readOnly"] = not owner
    config["recipeName"] = name
    config["appBase"] = f"/app/{name}/"
    config["slot"] = key

    # Which buttons this page may show. It has to come from here rather than be
    # guessed by the front end: `readOnly` says nothing about whether the server
    # would accept a run, only whether this requester is the owner.
    #
    # The answer is now the recipe's own declaration rather than a flag on the
    # exposure entry, so a page and its run route agree by construction — both
    # read the `@action` marks off the same methods. What the exposure still
    # decides is *who is looking*, and that only subtracts: a shared reading has
    # no per-person directory for a run to write, so its readers get no actions
    # at all.
    if zone_of(request) == "identity":
        actions = () if serves_recipe_slot(request) else page_actions_of(name)
    elif owner:
        # The owner may run anything they can open, declared or not: this is
        # their machine and `/api` is already theirs. The declaration narrows a
        # page for everyone else, never for them.
        actions = page_actions_of(name)
        config["runnable"] = True
    else:
        # Anonymous visitors get neither key. What a page can be made to do is
        # not theirs to know — readOnly:true plus apiBase:null is the whole of
        # what they may infer.
        return JSONResponse(content=config, headers=_REVALIDATE)

    config["actions"] = list(actions)
    # Kept beside `actions` for the front ends written against it. It says the
    # same thing the list does, one bit shorter.
    config.setdefault("runnable", bool(actions))
    return JSONResponse(content=config, headers=_REVALIDATE)


@router.post("/{name}/api/{mode}")
async def serve_app_api(name: str, mode: str, request: Request):
    """A page asking its own recipe for data.

    This is the other half of front-end/back-end separation. The page renders;
    when it needs numbers it calls a mode, the same way another module would —
    it never receives a path and never reads a file. A page handed an absolute
    path is the front end reaching into the back end's filesystem: the visitor
    has no such file, an endpoint able to serve it could serve any file on the
    machine, and the day the recipe's landing spot moves the page keeps reading
    the old one while every refresh reports success.

    Only ``@export`` modes are reachable here, and an exported mode is
    read-only by contract. So a page — which is the least trusted thing in the
    system, since anyone who can open it can call this — can never reach a mode
    that fetches, recomputes, or changes state through this door. The door for
    modes that do work is ``/app/<name>/run``, and it opens only for
    ``@action``.
    """
    from frago.recipes.contract import exports_of

    # Pass the mode: a snapshot can be stale in two ways, and being refused for
    # an export that was added after the server started is indistinguishable
    # from never having added it. See ``contract.surface_of``.
    exports = exports_of(name, mode) or ()
    if mode not in exports:
        raise HTTPException(
            status_code=403,
            detail=(f"{name} 没有把 {mode} 开给页面读。"
                    f"它标了 @export 的是 {'、'.join(exports) or '（一个都没有）'}。"
                    f"页面这个口只收 @export 的只读 mode——"
                    f"要让页面按一下去干活，那个 mode 标 @action，"
                    f"走 POST /app/{name}/run 那扇门。"),
        )

    try:
        params = await request.json()
    except Exception:
        params = {}
    if not isinstance(params, dict):
        params = {}

    from frago.server.services.recipe_service import RecipeService

    # Whose data this read is about.
    #
    # A signed-in visitor's page must be answered out of their own directory,
    # the same one their runs write. Until this was passed, it was not: the run
    # route built a visitor context and this one built none, so a page wrote to
    # the account's book and read back the machine's. Both said fine. Observed
    # on the server 2026-08-26 — the account's ledger sat at 46 entries while
    # every page rendered a different one of 48.
    #
    # The owner keeps `None` (their own run, their own directory), and so does
    # an anonymous visitor to a published page: they have no directory of their
    # own, and what they are meant to see is exactly what the publisher put up.
    #
    # A page exposed as one shared reading keeps `None` as well, and for the
    # same reason an anonymous reader does: everybody on its list is looking at
    # the one copy the recipe itself maintains, so the read has to be answered
    # out of that directory or it answers out of an empty one.
    ctx = None
    from frago.server.security import serves_recipe_slot, slot_for, zone_of

    if zone_of(request) == "identity" and not serves_recipe_slot(request):
        from frago.recipes import context as run_context

        identity = slot_for(request)
        if identity:
            ctx = run_context.for_visitor(name, identity)

    try:
        # Off the event loop. `run_recipe` blocks for as long as the recipe runs,
        # and an exported mode is allowed to ask another module for data — which
        # comes back to this same server on `/api/bus/ask`. Called inline, the
        # loop is blocked waiting for a recipe that is waiting for the loop, and
        # the whole server stops answering anything, health checks included.
        result = await asyncio.to_thread(
            RecipeService.run_recipe, name, params | {"mode": mode}, 300, ctx
        )
    except Exception as err:
        logger.warning("app api: %s/%s failed: %s", name, mode, err)
        return {"ok": False, "error": {"code": "recipe-failed", "message": str(err)}}

    if isinstance(result, dict) and result.get("status") == "error":
        # The recipe ran and said no. Passing that through as a success with an
        # empty payload is how a page ends up rendering nothing while every
        # refresh reports fine — the exact silence this contract exists to
        # remove, reintroduced one layer up.
        err = result.get("error")
        message = err.get("message") if isinstance(err, dict) else err
        return {"ok": False, "error": {"code": "recipe-failed",
                                       "message": str(message or "配方没有给出结果")}}

    data = result.get("data") if isinstance(result, dict) else result
    out = data if isinstance(data, dict) else {"result": data}

    # The same rule the base class applies to published render state, applied
    # to the other door. A page is a front end; a path in what it receives is
    # the front end reaching into the back end's filesystem — useless there,
    # and a description of the server's directory layout handed to whoever
    # opened the page.
    from frago.server.routes.bus import strip_paths

    leaked = strip_paths(out)
    if leaked:
        logger.warning("app api: %s/%s returned paths: %s", name, mode, leaked[:3])
        return {"ok": False, "error": {"code": "paths-in-export", "message":
            f"{name}/{mode} 的返回值里带了本机路径：{'；'.join(leaked[:3])}。"
            f"页面是前端，那边没有这台机器的文件系统。改成返回内容本身，"
            f"或者一个不含路径的标识。"}}
    return {"ok": True, "data": out}


@router.get("/{name}/data/{file_path:path}")
async def serve_app_data(name: str, file_path: str, request: Request):
    """Serve a file from the recipe's declared data directory, without copying it.

    The recipe publishes `dataDir` in its slot state; everything under it is
    readable through this route and nothing outside it is.
    """
    _assets_dir(name)
    key, state = _slot_state(name, request)

    data_dir = state.get("dataDir")
    if not data_dir:
        raise HTTPException(
            status_code=404,
            detail=f"Recipe '{name}' (slot '{key}') declares no dataDir",
            headers=_NO_STORE,
        )

    base = Path(data_dir).expanduser()

    # One account's tree is never served to another account.
    #
    # A visitor's own run has its `dataDir` forced into `users/<their id>/data/`,
    # and that forcing rests on every publish path having been covered — the
    # recipe calling directly, the recipe shelling out to `frago recipe publish`,
    # a sub-recipe adding another layer. Missing one would raise nothing: the
    # page would render, out of somebody else's directory.
    #
    # The rule is deliberately about the accounts' own root and not "must be
    # under this account's directory". An identity page whose data the owner
    # curated — computed ahead of time and published per person, which is what
    # identity mode was built for — points at a directory under the owner's own
    # `~/.frago/data/…`, and that is correct and must keep working. What can
    # never be right is one account's page reading out of another account's
    # subtree.
    #
    # A shared reading is the one deliberate exception, and it has to be spelled
    # out here rather than fall out of the rule: the recipe's own slot points at
    # a directory this machine's own runs wrote, filed under `users/<this
    # machine's id>/recipe-data/…` — inside the accounts root and outside this
    # reader's subtree, so the check below would refuse exactly the case that
    # exposure exists to serve. Everything else is unchanged: one account's page
    # still never reads another account's tree, and the entry saying
    # `reads: recipe` is the only thing that opens this door.
    from frago.server.security import serves_recipe_slot, zone_of

    if zone_of(request) == "identity" and not serves_recipe_slot(request):
        from frago.recipes.app_state import user_root, user_state_dir

        try:
            resolved = base.resolve()
            accounts_root = user_state_dir().resolve()
            if resolved.is_relative_to(accounts_root) and not resolved.is_relative_to(
                user_root(key).resolve()
            ):
                raise HTTPException(status_code=404, detail="File not found", headers=_NO_STORE)
        except (InvalidSlotName, OSError) as err:
            raise HTTPException(status_code=404, detail="File not found", headers=_NO_STORE) from err

    if not base.is_dir():
        raise HTTPException(status_code=404, detail=f"dataDir does not exist: {data_dir}", headers=_NO_STORE)

    full_path = _resolve_within(base, file_path)
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found", headers=_NO_STORE)

    return FileResponse(path=full_path, media_type=_mime_type(full_path), headers=_REVALIDATE)


@router.get("/{name}/")
@router.get("/{name}/{file_path:path}")
async def serve_app_asset(name: str, file_path: str = ""):
    """Serve the recipe's own front-end files straight from its assets/ directory."""
    assets = _assets_dir(name)
    full_path = _resolve_within(assets, file_path or "index.html")

    if full_path.is_dir():
        full_path = full_path / "index.html"

    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(path=full_path, media_type=_mime_type(full_path), headers=_REVALIDATE)
