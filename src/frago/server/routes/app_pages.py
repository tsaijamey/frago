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
    except RecipeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Recipe '{name}' not found")

    owner = getattr(recipe.metadata, "ui_from", None) or name
    if owner != name:
        if "/" in owner or ".." in owner:
            raise HTTPException(status_code=400, detail=f"Invalid ui_from: {owner}")
        try:
            recipe = get_registry().find(owner)
        except RecipeNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"Recipe '{name}' borrows its UI from '{owner}', which is not installed",
            )

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
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    return candidate


def _slot_state(name: str, request: Request) -> tuple[str, dict]:
    """Resolve the requested slot and read its state."""
    key = request.query_params.get("key") or DEFAULT_SLOT
    try:
        return key, read_slot(name, key)
    except InvalidSlotName as e:
        raise HTTPException(status_code=400, detail=str(e))


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
    """
    _assets_dir(name)
    key, state = _slot_state(name, request)

    config = dict(state)
    config["apiBase"] = "/api"
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
        )

    base = Path(data_dir).expanduser()
    if not base.is_dir():
        raise HTTPException(status_code=404, detail=f"dataDir does not exist: {data_dir}")

    full_path = _resolve_within(base, file_path)
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

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
