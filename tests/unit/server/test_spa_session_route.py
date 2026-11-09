"""SPA 路由回退与 /sessions/<session_id> 深层路径静态资源解析测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_spa_session_detail_route_and_nested_assets(tmp_path: Path, monkeypatch) -> None:
    """直接访问 /sessions/<session_id> 返回 index.html，且相对路径产生的 /sessions/assets/* 正确映射。"""
    assets_dir = tmp_path / "assets"
    icons_dir = tmp_path / "icons"
    assets_dir.mkdir(parents=True)
    icons_dir.mkdir(parents=True)

    index_html = tmp_path / "index.html"
    index_html.write_text(
        '<!DOCTYPE html><html><head><title>Frago SPA</title></head>'
        '<body><script src="./assets/index-test.js"></script></body></html>',
        encoding="utf-8",
    )
    js_bundle = assets_dir / "index-test.js"
    js_bundle.write_text("console.log('frago-spa-loaded');", encoding="utf-8")
    icon_file = icons_dir / "logo-32.png"
    icon_file.write_bytes(b"\x89PNG\r\n\x1a\n")

    monkeypatch.setattr("frago.server.app.get_frontend_path", lambda: tmp_path)

    from frago.server.app import create_app

    client = TestClient(create_app(), client=("127.0.0.1", 50000))

    # 1. 直接访问 /sessions/<session_id> 返回 index.html 且带 no-cache 头
    session_id = "ac80fa5f-03dc-407a-b464-7c29ef5f456e"
    res = client.get(f"/sessions/{session_id}")
    assert res.status_code == 200
    assert "Frago SPA" in res.text
    assert res.headers.get("cache-control") == "no-cache"

    # 2. 深层路径下因 ./assets/* 或 ./icons/* 触发的嵌套静态资源请求正确返回真实文件
    res_js = client.get("/sessions/assets/index-test.js")
    assert res_js.status_code == 200
    assert "frago-spa-loaded" in res_js.text
    assert "javascript" in res_js.headers.get("content-type", "")

    res_icon = client.get("/sessions/icons/logo-32.png")
    assert res_icon.status_code == 200
    assert res_icon.content == b"\x89PNG\r\n\x1a\n"

    # 3. 不存在的嵌套静态资源返回 404，绝不把 index.html 当成 JS 返回
    res_missing = client.get("/sessions/assets/nonexistent.js")
    assert res_missing.status_code == 404
