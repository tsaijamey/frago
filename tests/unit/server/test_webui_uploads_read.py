"""会话页取回附图：只放行上传目录里的图片，其余一律当不存在。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from frago.server.services import webui_uploads


@pytest.fixture
def root(tmp_path, monkeypatch):
    root = tmp_path / "uploads"
    monkeypatch.setattr(webui_uploads, "UPLOAD_ROOT", root)
    (root / "sid-1").mkdir(parents=True)
    (root / "sid-1" / "abc.png").write_bytes(b"\x89PNG fake")
    (root / "sid-1" / "abc-spec.md").write_text("doc")
    (tmp_path / "secret.png").write_bytes(b"outside")
    return root


def test_resolves_uploaded_image(root):
    assert webui_uploads.resolve_uploaded_image("sid-1", "abc.png") == (root / "sid-1" / "abc.png").resolve()


@pytest.mark.parametrize(
    ("folder", "name"),
    [
        ("sid-1", "missing.png"),  # 文件不在
        ("sid-1", "abc-spec.md"),  # 文档不经这条路
        ("..", "secret.png"),  # 目录名穿越
        ("sid-1", "../../secret.png"),  # 文件名穿越
        ("sid-1", ".hidden.png"),  # 点开头
    ],
)
def test_rejects_everything_else(root, folder, name):
    assert webui_uploads.resolve_uploaded_image(folder, name) is None


def test_route_serves_image_and_404s_missing(root):
    from frago.server.routes.workbench import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)

    ok = client.get("/api/workbench/uploads/sid-1/abc.png")
    assert ok.status_code == 200
    assert ok.content == b"\x89PNG fake"
    assert ok.headers["content-type"] == "image/png"

    assert client.get("/api/workbench/uploads/sid-1/gone.png").status_code == 404
    assert client.get("/api/workbench/uploads/sid-1/abc-spec.md").status_code == 404
