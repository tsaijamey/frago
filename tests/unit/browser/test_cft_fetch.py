"""frago 自己取 Chrome for Testing：每一处会装成「文件在、起不来」的地方。"""
from __future__ import annotations

import io
import os
import stat
import sys
import threading
import zipfile
from pathlib import Path

import pytest

from frago.browser import cft_fetch as cf

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="用到符号链接与执行位")


# ── 平台 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("system", "machine", "key"), [
    ("Darwin", "arm64", "mac-arm64"),
    ("Darwin", "x86_64", "mac-x64"),
    ("Linux", "x86_64", "linux64"),
    ("Linux", "aarch64", "linux-arm64"),
    ("Windows", "AMD64", "win64"),
    ("Windows", "x86", "win32"),
])
def test_platform_keys_match_the_manifest(system, machine, key):
    assert cf.platform_key(system, machine) == key


def test_unknown_platform_has_no_key():
    assert cf.platform_key("FreeBSD", "amd64") is None
    assert cf.platform_key("Windows", "ARM64") is None


def test_unknown_platform_says_so_without_touching_the_network(monkeypatch, tmp_path):
    monkeypatch.setattr(cf, "platform_key", lambda: None)
    monkeypatch.setattr(cf, "fetch_manifest_entry",
                        lambda *a, **k: pytest.fail("不该去读版本清单"))
    with pytest.raises(cf.CftFetchError) as exc:
        cf.ensure_cft(root=tmp_path / "cft", proxy=None)
    assert exc.value.kind == "platform"


# ── 解压 ────────────────────────────────────────────────────────────


def _zip_with_link_and_exec(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        exe = zipfile.ZipInfo("pkg/bin/run")
        exe.external_attr = (stat.S_IFREG | 0o755) << 16
        zf.writestr(exe, "#!/bin/sh\necho hi\n")
        link = zipfile.ZipInfo("pkg/Current")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(link, "bin")


def test_python_extract_keeps_exec_bit_and_symlinks(tmp_path):
    archive = tmp_path / "a.zip"
    _zip_with_link_and_exec(archive)
    dest = tmp_path / "out"
    dest.mkdir()
    cf._extract_python(archive, dest)
    assert os.access(dest / "pkg/bin/run", os.X_OK)
    assert (dest / "pkg/Current").is_symlink()
    assert os.readlink(dest / "pkg/Current") == "bin"


def test_plain_zipfile_would_have_lost_both(tmp_path):
    """钉住为什么不能用 extractall：这就是「文件都在、起不来」的来路。"""
    archive = tmp_path / "a.zip"
    _zip_with_link_and_exec(archive)
    dest = tmp_path / "out"
    zipfile.ZipFile(archive).extractall(dest)
    assert not (dest / "pkg/Current").is_symlink()
    assert not os.access(dest / "pkg/bin/run", os.X_OK)


@pytest.mark.skipif(sys.platform != "darwin", reason="ditto 只有 macOS 有")
def test_macos_extract_uses_ditto_and_keeps_both(tmp_path):
    archive = tmp_path / "a.zip"
    _zip_with_link_and_exec(archive)
    dest = tmp_path / "out"
    dest.mkdir()
    cf.extract(archive, dest, system="Darwin")
    assert (dest / "pkg/Current").is_symlink()
    assert os.access(dest / "pkg/bin/run", os.X_OK)


# ── 验证 ────────────────────────────────────────────────────────────


def _script(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "chrome"
    p.write_text(f"#!/bin/sh\n{body}\n")
    p.chmod(0o755)
    return p


def test_verify_returns_version(tmp_path):
    assert cf.verify(_script(tmp_path, "echo 'Google Chrome for Testing 1.2.3'"),
                     system="Linux") == "Google Chrome for Testing 1.2.3"


def test_verify_names_missing_system_library(tmp_path):
    binary = _script(tmp_path, (
        "echo 'chrome: error while loading shared libraries: libnss3.so: "
        "cannot open shared object file' >&2; exit 127"))
    with pytest.raises(cf.CftFetchError) as exc:
        cf.verify(binary, system="Linux")
    assert exc.value.kind == "deps"
    assert "libnss3.so" in str(exc.value)
    assert "sudo apt-get install" in (exc.value.remedy or "")


def test_verify_rejects_a_binary_that_prints_nothing(tmp_path):
    with pytest.raises(cf.CftFetchError) as exc:
        cf.verify(_script(tmp_path, "exit 1"), system="Linux")
    assert exc.value.kind == "verify"


# ── 网络 ────────────────────────────────────────────────────────────


def test_network_error_says_which_route_was_used():
    err = cf._network_error("下载 CfT", "http://127.0.0.1:7890", TimeoutError("timed out"))
    assert err.kind == "network"
    assert "127.0.0.1:7890" in str(err)
    assert "FRAGO_BROWSER_PROXY" in str(err)
    assert "直连" in str(cf._network_error("下载 CfT", None, OSError("x")))


# ── 整条流程 ─────────────────────────────────────────────────────────


@pytest.fixture
def fake_release(monkeypatch, tmp_path):
    """假的版本清单与下载：下载得到一个装着假 CfT 的 zip。"""
    key = cf.platform_key()
    if key is None:
        pytest.skip("本机平台没有 CfT")
    rel = cf._relative_binary(key)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo(rel.replace("\\", "/"))
        info.external_attr = (stat.S_IFREG | 0o755) << 16
        zf.writestr(info, "#!/bin/sh\necho 'Google Chrome for Testing 9.9.9'\n")
    downloads = []

    monkeypatch.setattr(cf, "fetch_manifest_entry",
                        lambda k, proxy: ("9.9.9", f"https://example/{k}.zip"))

    def _download(url, dest, *, proxy, progress):
        downloads.append(url)
        dest.write_bytes(buf.getvalue())

    monkeypatch.setattr(cf, "_download", _download)
    return tmp_path / "chrome-for-testing", rel, downloads


def test_fetches_into_place_and_says_what_it_does(fake_release):
    root, rel, downloads = fake_release
    said = []
    binary = cf.ensure_cft(root=root, proxy=None, progress=said.append)
    assert binary == root / rel
    assert os.access(binary, os.X_OK)
    assert downloads and said[0].startswith("frago 要用自带的浏览器 Chrome for Testing")
    assert any("9.9.9" in s for s in said)
    # 临时目录收干净了，正式目录里只有平台那一层
    assert [p.name for p in root.parent.iterdir() if p.name.startswith(".chrome")] == [
        ".chrome-for-testing.lock"]


def test_existing_copy_is_left_alone(fake_release):
    root, _rel, downloads = fake_release
    cf.ensure_cft(root=root, proxy=None)
    cf.ensure_cft(root=root, proxy=None)
    assert len(downloads) == 1


def test_force_replaces_existing_copy(fake_release):
    root, _rel, downloads = fake_release
    cf.ensure_cft(root=root, proxy=None)
    cf.ensure_cft(root=root, proxy=None, force=True)
    assert len(downloads) == 2


def test_failed_verify_leaves_nothing_behind(fake_release, monkeypatch):
    root, _rel, _downloads = fake_release

    def _broken(_binary, **_kw):
        raise cf.CftFetchError("verify", "起不来")

    monkeypatch.setattr(cf, "verify", _broken)
    with pytest.raises(cf.CftFetchError):
        cf.ensure_cft(root=root, proxy=None)
    assert cf.installed_binary(root) is None
    assert not [p for p in root.parent.iterdir() if p.name.startswith(".chrome-for-testing-")]


def test_two_callers_at_once_download_once(fake_release):
    root, _rel, downloads = fake_release
    results, errors = [], []

    def _go():
        try:
            results.append(cf.ensure_cft(root=root, proxy=None))
        except Exception as e:  # pragma: no cover - 失败时把原因带出来
            errors.append(e)

    threads = [threading.Thread(target=_go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(results) == 2 and results[0] == results[1]
    assert len(downloads) == 1
