"""The offline shell's service worker, seen from the server's side.

The SPA catch-all answers every unmatched path with index.html. That is right
for client-side routes and wrong for this one file: a worker whose script
arrives as text/html is refused by the browser ("unsupported MIME type"). The
failure is silent — the page simply has no offline shell, which is a state
nobody notices until the server is down and the shell is the only thing that
could have helped.
"""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from frago.server import app as app_module

LOCAL = ("127.0.0.1", 50000)


def build(frontend: Path) -> TestClient:
    """A real app whose frontend comes from ``frontend``."""
    original = app_module.get_frontend_path
    app_module.get_frontend_path = lambda: frontend
    try:
        application = app_module.create_app()
    finally:
        app_module.get_frontend_path = original
    return TestClient(application, client=LOCAL)


@pytest.fixture
def built_frontend() -> Path:
    """Whatever the last build left in the repo."""
    path = Path(app_module.__file__).parent / "assets"
    if not (path / "index.html").exists():
        pytest.skip("frontend not built")
    return path


def test_worker_is_served_as_a_script(built_frontend):
    resp = build(built_frontend).get("/sw.js")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/javascript")
    assert "addEventListener" in resp.text


def test_client_routes_still_get_the_shell(built_frontend):
    """The route above must not have eaten the catch-all it sits in front of."""
    resp = build(built_frontend).get("/workbench")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")


def test_a_build_without_the_worker_is_a_404_not_the_shell(tmp_path):
    """Answering with index.html here is what silently breaks the offline shell."""
    (tmp_path / "index.html").write_text("<html>")

    resp = build(tmp_path).get("/sw.js")

    assert resp.status_code == 404
