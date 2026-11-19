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


# ── macOS 透明启动包装器 ───────────────────────────────────────────────


def _make_fake_cft_app(root: Path) -> tuple[Path, Path]:
    """Create a minimal macOS .app bundle layout with a stub executable."""
    import json

    app = root / "chrome-mac-arm64" / "Google Chrome for Testing.app"
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>'
        '<key>CFBundleExecutable</key><string>Google Chrome for Testing</string>'
        '<key>CFBundleIdentifier</key><string>com.google.chrome.for.testing</string>'
        '<key>CFBundlePackageType</key><string>APPL</string>'
        '</dict></plist>\n',
        encoding="utf-8",
    )
    binary = macos / "Google Chrome for Testing"
    # Stub records every argument passed to it on separate lines (or prints version).
    binary.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "${1:-}" = "--version" ]; then\n'
        '  echo "Google Chrome for Testing 153.0.8010.52"\n'
        "  exit 0\n"
        "fi\n"
        'if [ -n "${STUB_ARGS_LOG:-}" ]; then\n'
        '  printf "%s\\n" "$@" > "$STUB_ARGS_LOG"\n'
        "fi\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    assert json.dumps("ok")  # keep imports clean
    return app, binary


def test_wrapper_script_has_no_hardcoded_developer_home():
    assert "/Users/frago" not in cf._MACOS_WRAPPER_SCRIPT
    assert "$HOME/.frago/profiles/cft/extension" in cf._MACOS_WRAPPER_SCRIPT


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS .app wrapper + codesign")
def test_macos_wrapper_installs_idempotently_and_signs(tmp_path):
    import subprocess

    app, binary = _make_fake_cft_app(tmp_path)
    assert cf.ensure_cft_wrapper(binary, system="Darwin") is True
    real_bin = binary.with_name(f"{binary.name}.bin")
    assert real_bin.exists()
    assert cf._is_cft_wrapper(binary)
    assert cf.verify(binary, system="Darwin") == "Google Chrome for Testing 153.0.8010.52"

    # Second call is an idempotent no-op.
    assert cf.ensure_cft_wrapper(binary, system="Darwin") is False

    verify_proc = subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(app)],
        capture_output=True, text=True, check=False,
    )
    assert verify_proc.returncode == 0, verify_proc.stderr


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS .app wrapper")
@pytest.mark.parametrize("argv", [
    ["--version"],
    ["--user-data-dir=/tmp/cdp-9223", "--remote-debugging-port=9223", "--headless=new"],
    ["--user-data-dir", "/tmp/cdp-9222", "--headless"],
    ["--type=renderer", "--lang=zh-CN"],
    ["--load-extension=/tmp/ext", "--user-data-dir=/tmp/ext-prof"],
])
def test_macos_wrapper_passthrough_never_hijacks_explicit_flags(tmp_path, argv):
    import subprocess

    _app, binary = _make_fake_cft_app(tmp_path)
    assert cf.ensure_cft_wrapper(binary, system="Darwin") is True

    args_log = tmp_path / "stub_args.log"
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    # Even if a fake frago existed, passthrough must NOT invoke it.
    fake_bin = fake_home / ".local" / "bin"
    fake_bin.mkdir(parents=True)
    frago_called = tmp_path / "frago_called"
    (fake_bin / "frago").write_text(
        f"#!/bin/sh\ntouch '{frago_called}'\nexit 1\n", encoding="utf-8"
    )
    (fake_bin / "frago").chmod(0o755)

    env = {
        "HOME": str(fake_home),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "STUB_ARGS_LOG": str(args_log),
    }
    proc = subprocess.run([str(binary), *argv], env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert not frago_called.exists()
    if argv == ["--version"]:
        assert proc.stdout.strip() == "Google Chrome for Testing 153.0.8010.52"
    else:
        assert args_log.read_text(encoding="utf-8").splitlines() == argv


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS .app wrapper")
@pytest.mark.parametrize("argv", [
    [],
    ["-psn_0_123456"],
    ["-psn_0_123456", "https://example.com"],
])
def test_macos_wrapper_bare_launch_prepares_extension_and_profile(tmp_path, argv):
    import subprocess

    _app, binary = _make_fake_cft_app(tmp_path)
    assert cf.ensure_cft_wrapper(binary, system="Darwin") is True

    fake_home = tmp_path / "home"
    fake_bin = fake_home / ".local" / "bin"
    fake_bin.mkdir(parents=True)
    fake_bundle = tmp_path / "bundle"
    fake_bundle.mkdir()
    (fake_bundle / "manifest.json").write_text("{}", encoding="utf-8")
    fake_profile = fake_home / ".frago" / "profiles" / "cft" / "extension"

    (fake_bin / "frago").write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "extension" ] && [ "$2" = "prepare-cft" ]; then\n'
        f'  printf "%s\\n%s\\n" "{fake_profile}" "{fake_bundle}"\n'
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    (fake_bin / "frago").chmod(0o755)

    args_log = tmp_path / "stub_args.log"
    # Simulate restricted macOS LaunchServices PATH (no ~/.local/bin in PATH).
    env = {
        "HOME": str(fake_home),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "STUB_ARGS_LOG": str(args_log),
    }
    proc = subprocess.run([str(binary), *argv], env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

    passed = args_log.read_text(encoding="utf-8").splitlines()
    assert f"--user-data-dir={fake_profile}" in passed
    assert f"--load-extension={fake_bundle}" in passed
    assert "--no-first-run" in passed
    assert "--no-default-browser-check" in passed
    assert "--enable-logging=stderr" in passed
    assert "--disable-sync" in passed
    assert not any(a.startswith("--remote-debugging-port") for a in passed)
    for orig in argv:
        assert orig in passed


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS .app wrapper")
def test_ensure_cft_heals_existing_unwrapped_app(tmp_path, monkeypatch):
    root = tmp_path / "chrome-for-testing"
    _app, binary = _make_fake_cft_app(root)
    monkeypatch.setattr(cf, "fetch_manifest_entry",
                        lambda *a, **k: pytest.fail("已有 CfT 时不该重新下载"))
    out = cf.ensure_cft(root=root, force=False)
    assert out == binary
    assert cf._is_cft_wrapper(binary)
    assert binary.with_name(f"{binary.name}.bin").exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS .app wrapper + codesign")
def test_ensure_cft_wrapper_rollback_on_codesign_failure(tmp_path, monkeypatch):
    """If codesign fails midway, restore original binary from .bin and leave no broken wrapper."""
    import subprocess

    app, binary = _make_fake_cft_app(tmp_path)
    original_content = binary.read_bytes()
    real_run = subprocess.run

    monkeypatch.setattr(cf.shutil, "which", lambda name: "/usr/bin/codesign" if name == "codesign" else None)

    def _fail_codesign(cmd, **kw):
        if cmd[0] == "codesign":
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="simulated codesign failure")
        return real_run(cmd, **kw)

    monkeypatch.setattr(cf.subprocess, "run", _fail_codesign)

    with pytest.raises(cf.CftFetchError) as exc:
        cf.ensure_cft_wrapper(binary, system="Darwin")
    assert exc.value.kind == "codesign"

    # Original binary restored in place; .bin and temp files cleaned up.
    assert binary.exists()
    assert binary.read_bytes() == original_content
    assert not cf._is_cft_wrapper(binary)
    assert not binary.with_name(f"{binary.name}.bin").exists()
    assert not binary.with_name(f".{binary.name}.frago-tmp").exists()
    assert cf.verify(binary, system="Darwin") == "Google Chrome for Testing 153.0.8010.52"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS .app wrapper + codesign")
def test_ensure_cft_wrapper_rollback_restores_previous_wrapper_on_update_failure(tmp_path, monkeypatch):
    """If updating an older wrapper fails during codesign, restore previous wrapper bytes."""
    import subprocess

    _app, binary = _make_fake_cft_app(tmp_path)
    assert cf.ensure_cft_wrapper(binary, system="Darwin") is True

    older_wrapper = "#!/usr/bin/env bash\n# frago-cft-wrapper v1\n# old version\nexec \"$0.bin\" \"$@\"\n"
    binary.write_text(older_wrapper, encoding="utf-8")

    monkeypatch.setattr(cf.shutil, "which", lambda name: "/usr/bin/codesign" if name == "codesign" else None)
    monkeypatch.setattr(
        cf.subprocess,
        "run",
        lambda cmd, **_kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="codesign broken"),
    )

    with pytest.raises(cf.CftFetchError) as exc:
        cf.ensure_cft_wrapper(binary, system="Darwin")
    assert exc.value.kind == "codesign"
    assert binary.read_text(encoding="utf-8") == older_wrapper
    assert binary.with_name(f"{binary.name}.bin").exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS .app wrapper")
def test_ensure_cft_default_root_initializes_profile_and_manifest(tmp_path, monkeypatch):
    """Fresh install into default root initializes CfT profile, vertical_tabs, and manifest."""
    import json

    key = cf.platform_key()
    if key is None:
        pytest.skip("本机平台没有 CfT")
    rel = cf._relative_binary(key)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        plist_info = zipfile.ZipInfo(f"chrome-{key}/Google Chrome for Testing.app/Contents/Info.plist")
        zf.writestr(
            plist_info,
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<plist version="1.0"><dict>'
            '<key>CFBundleExecutable</key><string>Google Chrome for Testing</string>'
            '<key>CFBundleIdentifier</key><string>com.google.chrome.for.testing</string>'
            '<key>CFBundlePackageType</key><string>APPL</string>'
            '</dict></plist>',
        )
        bin_info = zipfile.ZipInfo(rel.replace("\\", "/"))
        bin_info.external_attr = (stat.S_IFREG | 0o755) << 16
        zf.writestr(bin_info, "#!/bin/sh\necho 'Google Chrome for Testing 9.9.9'\n")

    fake_home = tmp_path / "fake_home"
    real_default_root = fake_home / ".frago" / "tools" / "chrome-for-testing"

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(cf, "_root", lambda: real_default_root)
    monkeypatch.setattr(cf, "fetch_manifest_entry", lambda k, proxy: ("9.9.9", f"https://example/{k}.zip"))
    monkeypatch.setattr(cf, "_download", lambda _url, dest, **_kw: dest.write_bytes(buf.getvalue()))

    binary = cf.ensure_cft(root=real_default_root, proxy=None)
    assert binary == real_default_root / rel
    assert cf._is_cft_wrapper(binary)

    profile = fake_home / ".frago" / "profiles" / "cft" / "extension"
    prefs = json.loads((profile / "Default" / "Preferences").read_text(encoding="utf-8"))
    assert prefs["vertical_tabs"]["enabled"] is True
    assert prefs["vertical_tabs"]["enabled_first_time"] is True
    assert prefs["extensions"]["ui"]["developer_mode"] is True

    manifest = json.loads(
        (profile / "NativeMessagingHosts" / "com.frago.bridge.json").read_text(encoding="utf-8")
    )
    launcher = fake_home / ".frago" / "chrome" / "native_host_launcher.sh"
    assert launcher.exists()
    assert manifest["path"] == str(launcher)
    assert (fake_home / ".frago" / "chrome" / "python_path").exists()
