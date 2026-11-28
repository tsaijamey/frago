"""Unit tests for Digital Employee DiceBear Micah avatar ontology, storage security, API, and fallback."""

from __future__ import annotations

import base64
import json
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from frago.employee import (
    AVATAR_BG_PALETTE,
    MAX_AVATAR_UPLOAD_BYTES,
    EmployeeOntologyService,
    EmployeePostRecord,
    avatars_dir,
    default_avatar_spec,
    get_post,
    is_safe_avatar_filename,
    resolve_avatar_file_path,
    save_post,
)
from frago.ontology import OntologyIntrospector, load_ontology_schema
from frago.server.routes import workbench as workbench_routes
from frago.server.services import coreagent_runner, tmux_sessions_service, workbench_titles
from frago.session import record_reader
from frago.session.record_reader import SessionCard


def _make_minimal_png(width: int = 2, height: int = 2, color: tuple[int, int, int] = (46, 134, 222)) -> bytes:
    """Create a valid minimal RGB PNG payload."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes(color) * width
    raw = row * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _make_minimal_jpeg() -> bytes:
    """Create minimal bytes matching JPEG magic header (SOI + APP0)."""
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"


def _make_minimal_webp() -> bytes:
    """Create minimal bytes matching RIFF....WEBP magic header."""
    return b"RIFF\x1a\x00\x00\x00WEBPVP8 \x0e\x00\x00\x00\x30\x01\x00\x9d\x01\x2a\x01\x00\x01\x00\x00\x00"


@dataclass
class _FakeOntoRec:
    session_id: str
    employee_id: str | None = None
    lifecycle_state: str | None = None
    turn_seq: int = 0
    updated_at: float = 0.0


class _FakeOntoService:
    def __init__(self, records: list[_FakeOntoRec] | None = None) -> None:
        self._records = records or []
        self.store = self

    def list_sessions(self) -> list[_FakeOntoRec]:
        return list(self._records)

    def batch_reconcile_states(self, _heals: list[tuple[str, str, str | None]]) -> None:
        return None


@pytest.fixture
def env_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    emp_dir = tmp_path / "employees"
    emp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(emp_dir))
    monkeypatch.setenv("FRAGO_HOME", str(tmp_path / "frago_home"))
    return emp_dir


@pytest.fixture
def client(env_dirs: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(tmux_sessions_service, "open_session_names", lambda: set())
    monkeypatch.setattr(coreagent_runner, "live_states", lambda: {})
    monkeypatch.setattr(workbench_titles, "load", lambda: {})
    monkeypatch.setattr(workbench_routes, "_observer_slots_state", lambda _sid, _fam: (False, False))
    monkeypatch.setattr(workbench_routes, "_keep_watching_only", lambda _alive: None)
    monkeypatch.setattr("frago.server.routes.workbench.workbench_groups.local_ops_session_ids", lambda: set())

    from frago.server.app import create_app

    return TestClient(create_app(), client=("127.0.0.1", 50000))


def test_ontology_schema_includes_avatar_and_stores_without_sidecar(env_dirs: Path) -> None:
    introspector = OntologyIntrospector()
    assert introspector.validate_schema_integrity() == []
    schema = load_ontology_schema()
    resources = schema["domain_classes"]["Continuant.IndependentContinuant.Resource"]
    emp_schema = next(item for item in resources if item["class_id"] == "EmployeePostResource")
    assert "src/frago/employee/avatar.py" in emp_schema["current_code_locations"]

    svc = EmployeeOntologyService(base_dir=env_dirs)
    rec, projection = svc.hire("frago-pm", title="产品经理", agent_kernel="claude", description="统筹产品演进")
    assert projection.post.ontological_id()
    assert rec.avatar["kind"] == "default"
    assert rec.avatar["seed"] == "frago-pm"

    # Ontology projector rejects invalid avatar payload (bad kind / traversal filename).
    from frago.ontology import ProjectionValidationError, project_employee_post_dict

    with pytest.raises(ProjectionValidationError):
        project_employee_post_dict(
            {
                "member_post_id": "frago-pm",
                "title": "产品经理",
                "agent_kernel": "claude",
                "avatar": {"kind": "upload", "file_name": "../../etc/passwd", "mime_type": "image/png"},
            }
        )

    # Single source of truth: only `<member_post_id>.json` exists under employees dir, no sidecar files.
    json_files = sorted(p.name for p in env_dirs.glob("*.json"))
    assert json_files == ["frago-pm.json"]

    raw_doc = json.loads((env_dirs / "frago-pm.json").read_text(encoding="utf-8"))
    assert raw_doc["member_post_id"] == "frago-pm"
    assert raw_doc["avatar"]["kind"] == "default"
    assert raw_doc["avatar"]["seed"] == "frago-pm"
    assert raw_doc["avatar"]["bg_color"] in {p["hex"] for p in AVATAR_BG_PALETTE}

    # Legacy record missing `avatar` key still loads cleanly with deterministic default.
    raw_doc.pop("avatar", None)
    (env_dirs / "frago-pm.json").write_text(json.dumps(raw_doc, ensure_ascii=False), encoding="utf-8")
    loaded = get_post("frago-pm", base_dir=env_dirs)
    assert loaded is not None
    assert loaded.avatar["kind"] == "default"
    assert loaded.avatar["seed"] == "frago-pm"


def test_deterministic_default_avatar_and_palette() -> None:
    a1 = default_avatar_spec("frago-dev")
    a2 = default_avatar_spec("frago-dev")
    assert a1 == a2
    assert a1["kind"] == "default"
    assert a1["seed"] == "frago-dev"
    assert len(AVATAR_BG_PALETTE) == 8
    assert a1["bg_color"] in {p["hex"] for p in AVATAR_BG_PALETTE}


def test_put_builtin_micah_persists_and_cleans_old_upload(client: TestClient, env_dirs: Path) -> None:
    save_post(EmployeePostRecord(member_post_id="ui-designer", title="UI 设计师"))

    # First upload a valid PNG so we can verify switching to built-in Micah deletes the old file.
    png_bytes = _make_minimal_png()
    up_res = client.post(
        "/api/employees/ui-designer/avatar/upload",
        json={
            "data_url": f"data:image/png;base64,{base64.b64encode(png_bytes).decode('ascii')}",
            "filename": "portrait.png",
        },
    )
    assert up_res.status_code == 200
    old_file_name = up_res.json()["avatar"]["file_name"]
    assert old_file_name
    old_file_path = avatars_dir(env_dirs) / old_file_name
    assert old_file_path.is_file()

    # Now choose a built-in Micah variant.
    put_res = client.put(
        "/api/employees/ui-designer/avatar",
        json={"seed": "micah-studio-42", "bg_color": "#e6efe9", "palette_id": "sage"},
    )
    assert put_res.status_code == 200
    body = put_res.json()
    assert body["avatar"]["kind"] == "micah"
    assert body["avatar"]["seed"] == "micah-studio-42"
    assert body["avatar"]["bg_color"] == "#e6efe9"
    assert body["avatar"]["palette_id"] == "sage"
    assert body["avatar"]["file_name"] is None
    assert body["avatar_resolved"]["effective_kind"] == "micah"
    assert body["avatar_resolved"]["seed"] == "micah-studio-42"
    assert not old_file_path.exists()

    # Invalid hex / empty seed rejected with 400.
    bad_seed = client.put("/api/employees/ui-designer/avatar", json={"seed": "   "})
    assert bad_seed.status_code == 400
    bad_hex = client.put(
        "/api/employees/ui-designer/avatar",
        json={"seed": "ok", "bg_color": "javascript:alert(1)"},
    )
    assert bad_hex.status_code == 400


def test_upload_accepts_png_jpeg_webp_and_replaces_old_binary(client: TestClient, env_dirs: Path) -> None:
    save_post(EmployeePostRecord(member_post_id="frago-dev", title="全栈研发"))

    # 1. Upload PNG via JSON data_url
    png_bytes = _make_minimal_png(color=(10, 20, 30))
    r1 = client.post(
        "/api/employees/frago-dev/avatar/upload",
        json={
            "data_url": f"data:image/png;base64,{base64.b64encode(png_bytes).decode('ascii')}",
            "filename": "headshot.png",
        },
    )
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["avatar"]["kind"] == "upload"
    assert d1["avatar"]["mime_type"] == "image/png"
    assert d1["avatar_resolved"]["effective_kind"] == "upload"
    assert d1["avatar_resolved"]["upload_url"].startswith("/api/employees/frago-dev/avatar/file?v=")
    f1 = avatars_dir(env_dirs) / d1["avatar"]["file_name"]
    assert f1.is_file()

    # Serve endpoint returns PNG with security headers.
    file_res = client.get("/api/employees/frago-dev/avatar/file")
    assert file_res.status_code == 200
    assert file_res.content == png_bytes
    assert file_res.headers["content-type"].startswith("image/png")
    assert file_res.headers["x-content-type-options"] == "nosniff"
    assert "private" in file_res.headers["cache-control"]
    assert file_res.headers["etag"]

    # 2. Replace with JPEG via raw binary upload -> old PNG removed.
    jpeg_bytes = _make_minimal_jpeg()
    r2 = client.post(
        "/api/employees/frago-dev/avatar/upload",
        content=jpeg_bytes,
        headers={"Content-Type": "image/jpeg", "X-Avatar-Filename": "photo.jpg"},
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["avatar"]["mime_type"] == "image/jpeg"
    f2 = avatars_dir(env_dirs) / d2["avatar"]["file_name"]
    assert f2.is_file()
    assert not f1.exists()

    # 3. Replace with WebP -> old JPEG removed.
    webp_bytes = _make_minimal_webp()
    r3 = client.post(
        "/api/employees/frago-dev/avatar/upload",
        content=webp_bytes,
        headers={"Content-Type": "image/webp", "X-Avatar-Filename": "pic.webp"},
    )
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["avatar"]["mime_type"] == "image/webp"
    f3 = avatars_dir(env_dirs) / d3["avatar"]["file_name"]
    assert f3.is_file()
    assert not f2.exists()

    # Uploaded binaries live inside `_avatars/` and never pollute employee JSON listing.
    assert sorted(p.name for p in env_dirs.glob("*.json")) == ["frago-dev.json"]


def test_upload_blocks_svg_html_oversized_mismatch_and_traversal(client: TestClient, env_dirs: Path) -> None:
    save_post(EmployeePostRecord(member_post_id="sec-guard", title="安全审计"))

    # 1. Explicit SVG
    svg_payload = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    res_svg = client.post(
        "/api/employees/sec-guard/avatar/upload",
        json={
            "data_url": f"data:image/svg+xml;base64,{base64.b64encode(svg_payload).decode('ascii')}",
            "filename": "evil.svg",
        },
    )
    assert res_svg.status_code == 400

    # 2. Disguised SVG claiming image/png + .png filename
    res_disguised = client.post(
        "/api/employees/sec-guard/avatar/upload",
        json={
            "data_url": f"data:image/png;base64,{base64.b64encode(svg_payload).decode('ascii')}",
            "filename": "fake.png",
        },
    )
    assert res_disguised.status_code == 400

    # 3. HTML payload
    html_payload = b"<!DOCTYPE html><html><script>alert(1)</script></html>"
    res_html = client.post(
        "/api/employees/sec-guard/avatar/upload",
        content=html_payload,
        headers={"Content-Type": "text/html", "X-Avatar-Filename": "x.html"},
    )
    assert res_html.status_code == 400

    # 4. MIME mismatch (JPEG bytes declared as image/png)
    res_mismatch = client.post(
        "/api/employees/sec-guard/avatar/upload",
        content=_make_minimal_jpeg(),
        headers={"Content-Type": "image/png", "X-Avatar-Filename": "a.png"},
    )
    assert res_mismatch.status_code == 400

    # 5. Oversized file (> 2 MiB)
    oversized = _make_minimal_png() + (b"\x00" * (MAX_AVATAR_UPLOAD_BYTES + 16))
    res_big = client.post(
        "/api/employees/sec-guard/avatar/upload",
        content=oversized,
        headers={"Content-Type": "image/png"},
    )
    assert res_big.status_code == 413

    # 6. Path traversal filename in upload header is sanitized into generated hash name
    assert not is_safe_avatar_filename("../../etc/passwd")
    assert not is_safe_avatar_filename("../evil.png")
    assert resolve_avatar_file_path("../../etc/passwd", employees_base_dir=env_dirs) is None

    res_trav = client.post(
        "/api/employees/sec-guard/avatar/upload",
        content=_make_minimal_png(),
        headers={"Content-Type": "image/png", "X-Avatar-Filename": "../../../escape.png"},
    )
    assert res_trav.status_code == 200
    stored_name = res_trav.json()["avatar"]["file_name"]
    assert is_safe_avatar_filename(stored_name)
    assert "/" not in stored_name and ".." not in stored_name
    assert (avatars_dir(env_dirs) / stored_name).is_file()


def test_delete_resets_to_default_and_cleans_file(client: TestClient, env_dirs: Path) -> None:
    save_post(EmployeePostRecord(member_post_id="reset-bot", title="重置验证员"))

    up_res = client.post(
        "/api/employees/reset-bot/avatar/upload",
        content=_make_minimal_png(),
        headers={"Content-Type": "image/png", "X-Avatar-Filename": "avatar.png"},
    )
    assert up_res.status_code == 200
    file_path = avatars_dir(env_dirs) / up_res.json()["avatar"]["file_name"]
    assert file_path.is_file()

    del_res = client.delete("/api/employees/reset-bot/avatar")
    assert del_res.status_code == 200
    body = del_res.json()
    assert body["avatar"]["kind"] == "default"
    assert body["avatar"]["file_name"] is None
    assert body["avatar_resolved"]["effective_kind"] == "default"
    assert body["avatar_resolved"]["seed"] == "reset-bot"
    assert body["avatar_resolved"]["upload_url"] is None
    assert not file_path.exists()

    # File endpoint returns clean 404 after reset.
    assert client.get("/api/employees/reset-bot/avatar/file").status_code == 404


def test_missing_and_corrupted_upload_falls_back_gracefully(client: TestClient, env_dirs: Path) -> None:
    save_post(EmployeePostRecord(member_post_id="fallback-bot", title="容错验证员"))

    up_res = client.post(
        "/api/employees/fallback-bot/avatar/upload",
        content=_make_minimal_png(),
        headers={"Content-Type": "image/png", "X-Avatar-Filename": "ok.png"},
    )
    assert up_res.status_code == 200
    file_path = avatars_dir(env_dirs) / up_res.json()["avatar"]["file_name"]
    assert file_path.is_file()

    # Case A: Corrupted binary content on disk -> no 500, degrades to default Micah + 404 on /file.
    file_path.write_bytes(b"NOT_A_VALID_IMAGE_BYTES_CORRUPTED")
    get_corrupted = client.get("/api/employees/fallback-bot")
    assert get_corrupted.status_code == 200
    resolved_corrupted = get_corrupted.json()["employee"]["avatar_resolved"]
    assert resolved_corrupted["kind"] == "upload"
    assert resolved_corrupted["effective_kind"] == "default"
    assert resolved_corrupted["fallback_reason"] == "corrupted"
    assert resolved_corrupted["upload_url"] is None
    assert resolved_corrupted["seed"] == "fallback-bot"
    assert client.get("/api/employees/fallback-bot/avatar/file").status_code == 404

    # Case B: Deleted file on disk -> no 500, degrades to default Micah with fallback_reason="missing".
    file_path.unlink()
    get_missing = client.get("/api/employees/fallback-bot")
    assert get_missing.status_code == 200
    resolved_missing = get_missing.json()["employee"]["avatar_resolved"]
    assert resolved_missing["kind"] == "upload"
    assert resolved_missing["effective_kind"] == "default"
    assert resolved_missing["fallback_reason"] == "missing"
    assert resolved_missing["upload_url"] is None
    assert resolved_missing["seed"] == "fallback-bot"

    list_res = client.get("/api/employees")
    assert list_res.status_code == 200
    matched = [item for item in list_res.json()["employees"] if item["member_post_id"] == "fallback-bot"]
    assert len(matched) == 1
    assert matched[0]["avatar_resolved"]["effective_kind"] == "default"
    assert matched[0]["avatar_resolved"]["fallback_reason"] == "missing"
    assert client.get("/api/employees/fallback-bot/avatar/file").status_code == 404


def test_workbench_sessions_include_employee_avatar_resolved(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_post(EmployeePostRecord(member_post_id="frago-pm", title="产品负责人"))
    put_res = client.put(
        "/api/employees/frago-pm/avatar",
        json={"seed": "pm-avatar-seed", "bg_color": "#ece8f5", "palette_id": "lilac"},
    )
    assert put_res.status_code == 200

    card = SessionCard(
        session_id="sess-pm-avatar-1",
        family="claude-code",
        title="Avatar workbench check",
        directory="/tmp",
        created_at=1_700_000_100_000,
        last_active_at=1_700_000_150_000,
        last_reply_at=1_700_000_160_000,
        status="running",
        last_kind="tool.use",
        employee_id="frago-pm",
    )
    monkeypatch.setattr(record_reader, "list_sessions", lambda: [card])
    monkeypatch.setattr(
        "frago.session.service.get_default_session_service",
        lambda: _FakeOntoService([_FakeOntoRec(session_id="sess-pm-avatar-1", employee_id="frago-pm")]),
    )

    wb_res = client.get("/api/workbench/sessions")
    assert wb_res.status_code == 200
    payload = wb_res.json()
    sessions = payload if isinstance(payload, list) else payload["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["employee_id"] == "frago-pm"
    assert sessions[0]["employee_avatar"]["effective_kind"] == "micah"
    assert sessions[0]["employee_avatar"]["seed"] == "pm-avatar-seed"
    assert sessions[0]["employee_avatar"]["bg_color"] == "#ece8f5"
