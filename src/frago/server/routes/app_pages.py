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

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from frago.recipes.app_state import DEFAULT_SLOT, InvalidSlotName
from frago.recipes.app_state import read as read_slot

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
    from frago.recipes.registry import get_registry

    try:
        recipe = get_registry().find(name)
    except RecipeNotFoundError as err:
        raise HTTPException(status_code=404, detail=f"Recipe '{name}' not found") from err

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
    """
    from frago.server.security import slot_for, zone_of

    zone = zone_of(request)
    visitor = zone in ("public", "identity")
    key = (slot_for(request) or DEFAULT_SLOT) if visitor else (
        request.query_params.get("key") or DEFAULT_SLOT
    )
    try:
        return key, read_slot(name, key, identity=zone == "identity")
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

    from frago.recipes.publish import public_view
    from frago.server.security import is_owner_request

    owner = is_owner_request(request)
    config = dict(state) if owner else public_view(state)
    config["apiBase"] = "/api" if owner else None
    config["readOnly"] = not owner
    config["recipeName"] = name
    config["appBase"] = f"/app/{name}/"
    config["slot"] = key
    return JSONResponse(content=config, headers=_REVALIDATE)


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
    from frago.server.security import zone_of

    if zone_of(request) == "identity":
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
