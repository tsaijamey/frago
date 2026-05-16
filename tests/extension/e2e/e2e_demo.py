"""End-to-end smoke: real Chrome + unpacked extension + native host.

Runs:

    1. launch daemon (asyncio subprocess)
    2. launch Chrome with --load-extension=<bundle> and isolated user-data-dir
    3. install native messaging manifest (points to frago extension native-host)
    4. navigate → get-content → click → screenshot → exec-js
    5. tear everything down (chrome process + daemon + user-data-dir)

MV3 service workers only get a native messaging port after a user or
page trigger. We use Chrome's `--load-extension` plus the `activeTab`
permission's granted-by-installation behavior to allow connectNative on
startup. If the bridge does not come online within `STARTUP_TIMEOUT` we
fail loud with the captured daemon log.

Run with:

    uv run python tests/extension/e2e/e2e_demo.py [--keep-chrome]

Outputs are written under:

    $FRAGO_E2E_OUT  (default: <repo>/outputs/e2e)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from frago.chrome.extension.native_host import SOCK_PATH, STABLE_EXTENSION_ID, install_manifest, chrome_manifest_dir, HOST_NAME
from frago.chrome.backends.extension import (
    ExtensionBackendError, ExtensionChromeBackend, launch_chrome_with_extension,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

from frago.chrome.extension import bundle_path
BUNDLE_DIR = bundle_path()
STARTUP_TIMEOUT = float(os.environ.get("FRAGO_E2E_STARTUP_TIMEOUT", "20"))


def _log(step: str, payload) -> None:
    print(f"[e2e] {step}: {json.dumps(payload, ensure_ascii=False, default=str)[:400]}")


def wait_for_socket(path: Path, timeout: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return
        time.sleep(0.1)
    raise TimeoutError(f"daemon socket {path} not created in {timeout}s")


def wait_for_bridge(timeout: float) -> dict:
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            return ExtensionChromeBackend().start()
        except (ExtensionBackendError, FileNotFoundError, ConnectionError) as e:
            last_err = e
            time.sleep(0.5)
    raise TimeoutError(f"bridge did not come online: {last_err}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-chrome", action="store_true")
    ap.add_argument("--out", default=os.environ.get("FRAGO_E2E_OUT",
                                                    str(REPO_ROOT / "outputs" / "e2e")))
    ap.add_argument("--browser", default=os.environ.get("FRAGO_E2E_BROWSER"),
                    help="Browser binary path (e.g. /usr/bin/microsoft-edge). "
                         "Default: auto-detect chrome/chromium.")
    ap.add_argument("--manifest-dir", type=Path,
                    default=os.environ.get("FRAGO_E2E_MANIFEST_DIR"),
                    help="Where to write the native messaging manifest. "
                         "Edge: ~/.config/microsoft-edge/NativeMessagingHosts")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "e2e_log.json"
    shot_path = out_dir / "e2e_screenshot.png"
    daemon_log = out_dir / "daemon.log"
    udd = Path(tempfile.mkdtemp(prefix="frago-e2e-udd-"))

    # Clean stale daemon socket.
    if SOCK_PATH.exists():
        SOCK_PATH.unlink()

    results: dict = {"extension_id": STABLE_EXTENSION_ID, "steps": {}}
    chrome_proc = None
    daemon_proc = None
    installed_manifest: Path | None = None
    try:
        # Step 0: daemon
        daemon_proc = subprocess.Popen(
            [sys.executable, "-m", "frago.cli.main", "extension", "daemon"],
            stdout=open(daemon_log, "wb"), stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        wait_for_socket(SOCK_PATH, timeout=5.0)
        _log("daemon_up", {"pid": daemon_proc.pid, "sock": str(SOCK_PATH)})

        # Step 0.5: install native manifest so Chrome can spawn the relay
        launcher = Path.home() / ".frago" / "chrome" / "native_host_launcher.sh"
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_text(
            "#!/usr/bin/env bash\n"
            f"exec {sys.executable} -m frago.cli.main extension native-host\n"
        )
        launcher.chmod(0o755)
        # When --user-data-dir is overridden (always, in this test), Chromium
        # resolves DIR_USER_NATIVE_MESSAGING to <udd>/NativeMessagingHosts —
        # NOT ~/.config/<brand>/NativeMessagingHosts. Default to the udd
        # location; honor explicit --manifest-dir if the caller insists.
        manifest_dir = args.manifest_dir or (udd / "NativeMessagingHosts")
        installed_manifest = install_manifest(
            str(launcher), target_dir=manifest_dir)
        _log("manifest_installed", {"path": str(installed_manifest)})

        # Step 1: launch Chrome headed with extension loaded
        chrome_log = out_dir / "chrome.log"
        chrome_proc = launch_chrome_with_extension(
            BUNDLE_DIR, user_data_dir=udd, log_path=chrome_log,
            chrome_binary=args.browser)
        _log("chrome_launched", {"pid": chrome_proc.pid, "udd": str(udd)})

        # Step 2: wait for bridge
        info = wait_for_bridge(STARTUP_TIMEOUT)
        results["steps"]["bridge_up"] = info
        _log("bridge_up", info)

        be = ExtensionChromeBackend()

        # Step 3: navigate
        nav = be.navigate("https://example.com", group="e2e")
        results["steps"]["navigate"] = {"tab_id": nav.tab_id,
                                        "url": nav.url, "title": nav.title}
        _log("navigate", results["steps"]["navigate"])
        assert "example" in (nav.title or "").lower() or "example" in (nav.url or "")

        # Step 4: get-content
        content = be.get_content(group="e2e")
        preview = (content.text or "")[:120]
        results["steps"]["get_content"] = {"title": content.title,
                                           "text_preview": preview,
                                           "text_len": len(content.text or "")}
        _log("get_content", results["steps"]["get_content"])
        assert "Example Domain" in (content.text or ""), \
            f"unexpected content: {preview!r}"

        # Step 5: click
        click = be.click("a", group="e2e")
        results["steps"]["click"] = {"success": click.success}
        _log("click", results["steps"]["click"])
        assert click.success

        # Step 6: screenshot
        shot = be.screenshot(group="e2e", output=str(shot_path))
        results["steps"]["screenshot"] = {"path": shot.path,
                                          "png_bytes": len(
                                              (shot.png_base64 or "")) * 3 // 4}
        _log("screenshot", results["steps"]["screenshot"])
        assert shot_path.exists() and shot_path.stat().st_size > 1024

        # Step 7: exec-js
        js = be.exec_js("1 + 2 * 3", group="e2e")
        results["steps"]["exec_js"] = {"value": js.value}
        _log("exec_js", results["steps"]["exec_js"])
        assert js.value == 7

        # ─── Batch 1 (live): tab management + page ops ────────────────
        # Re-navigate to example.com to ensure stable page state for the
        # remaining ops (post-click landed on iana.org with unknown load
        # state). Stay on a network-light target that's reachable in
        # restricted-egress dev environments.
        nav2 = be.navigate("https://example.com/", group="e2e")
        results["steps"]["navigate_2"] = {"tab_id": nav2.tab_id,
                                          "url": nav2.url, "title": nav2.title}
        _log("navigate_2", results["steps"]["navigate_2"])
        assert "example" in (nav2.url or "").lower()

        # Step 8: scroll. example.com is short; just verify the RPC
        # round-trips successfully and scrollY is a number (could be 0
        # if the page already fits in viewport).
        scr = be.scroll(200, group="e2e")
        sy = be.exec_js("window.scrollY", group="e2e").value
        results["steps"]["scroll"] = {"requested": scr.get("scrolled"),
                                       "scrollY": sy}
        _log("scroll", results["steps"]["scroll"])
        assert scr.get("scrolled") == 200
        assert isinstance(sy, (int, float)), f"scrollY={sy!r}"

        # Step 9: scroll_to (link selector — every page has anchors)
        st = be.scroll_to(group="e2e", selector="a", block="center")
        results["steps"]["scroll_to"] = st
        _log("scroll_to", st)
        assert st.get("success")

        # Step 10: zoom
        z = be.zoom(1.5, group="e2e")
        results["steps"]["zoom"] = z
        _log("zoom", z)
        assert abs(float(z.get("factor", 0)) - 1.5) < 0.01

        # Step 11: get_title
        title = be.get_title(group="e2e")
        results["steps"]["get_title"] = {"title": title}
        _log("get_title", results["steps"]["get_title"])
        assert "Example" in title

        # Step 12: list_tabs (our tab must be in the list)
        tabs = be.list_tabs()
        ids = [t.get("id") for t in tabs]
        results["steps"]["list_tabs"] = {"count": len(tabs),
                                          "our_tab_present": nav2.tab_id in ids}
        _log("list_tabs", results["steps"]["list_tabs"])
        assert nav2.tab_id in ids, f"our tab {nav2.tab_id} missing from {ids}"

        # Step 13: groups.list / groups.info (we registered "e2e" earlier)
        groups = be.list_groups()
        results["steps"]["groups_list"] = {"groups": list(groups.keys())}
        _log("groups_list", results["steps"]["groups_list"])
        assert "e2e" in groups

        ginfo = be.group_info("e2e")
        results["steps"]["group_info"] = {"tab_id": ginfo.get("tab_id"),
                                          "url": ginfo.get("url")}
        _log("group_info", results["steps"]["group_info"])
        assert ginfo.get("tab_id") == nav2.tab_id

        # Step 14: zoom restore (so a kept-Edge isn't left at 1.5x)
        be.zoom(1.0, group="e2e")

        # ─── Batch 1 (live, multi-tab): switch / close / reset / cleanup ─
        # Open a second group → second tab, exercise tab + group lifecycle.
        nav3 = be.navigate("https://example.com/", group="e2e2", timeout=30.0)
        results["steps"]["navigate_group2"] = {"tab_id": nav3.tab_id,
                                                "url": nav3.url}
        _log("navigate_group2", results["steps"]["navigate_group2"])
        assert nav3.tab_id != nav2.tab_id, "second group should have a distinct tab"

        # Step 15: list_tabs sees both
        tabs2 = be.list_tabs()
        ids2 = [t.get("id") for t in tabs2]
        results["steps"]["list_tabs_two_groups"] = {
            "count": len(tabs2),
            "both_present": nav2.tab_id in ids2 and nav3.tab_id in ids2}
        _log("list_tabs_two_groups",
             results["steps"]["list_tabs_two_groups"])
        assert nav2.tab_id in ids2 and nav3.tab_id in ids2

        # Step 16: switch_tab to the e2e group's tab, verify it's active
        # (exec_js runs in the page's main world and can't see chrome.* APIs;
        # use list_tabs to inspect the active flag from the SW context.)
        be.switch_tab(nav2.tab_id)
        time.sleep(0.3)
        post_switch = be.list_tabs()
        active_tabs = [t for t in post_switch if t.get("active")]
        results["steps"]["switch_tab"] = {
            "switched_to": nav2.tab_id,
            "now_active_ids": [t.get("id") for t in active_tabs]}
        _log("switch_tab", results["steps"]["switch_tab"])
        assert any(t.get("id") == nav2.tab_id and t.get("active")
                   for t in post_switch), \
            f"e2e tab not active after switch: {post_switch}"

        # Step 17: close the second group's tab. close_tab is courteous —
        # SW also removes the group binding inline (so group_cleanup later
        # has nothing to do; that's correct behavior).
        be.close_tab(nav3.tab_id)
        time.sleep(0.3)
        after_close = be.list_tabs()
        ids_after = [t.get("id") for t in after_close]
        results["steps"]["close_tab"] = {
            "closed": nav3.tab_id, "still_present": nav3.tab_id in ids_after}
        _log("close_tab", results["steps"]["close_tab"])
        assert nav3.tab_id not in ids_after

        # Step 18: groups_list should already exclude e2e2 (close_tab cleaned it)
        groups_after_close = be.list_groups()
        results["steps"]["groups_after_close_tab"] = {
            "groups": list(groups_after_close.keys())}
        _log("groups_after_close_tab",
             results["steps"]["groups_after_close_tab"])
        assert "e2e" in groups_after_close and "e2e2" not in groups_after_close

        # Step 19: groups.cleanup is a no-op here (no stale bindings); just
        # verify the RPC round-trips and reports 0 removed.
        cleanup = be.group_cleanup()
        results["steps"]["group_cleanup"] = cleanup
        _log("group_cleanup", cleanup)
        assert cleanup.get("removed") == 0, \
            f"unexpected stale bindings: {cleanup}"

        # Step 20: group_close on a fresh group — closes its tab + drops binding
        nav4 = be.navigate("https://example.com/", group="e2e3", timeout=30.0)
        results["steps"]["navigate_group3"] = {"tab_id": nav4.tab_id}
        _log("navigate_group3", results["steps"]["navigate_group3"])
        gclose = be.group_close("e2e3")
        results["steps"]["group_close"] = gclose
        _log("group_close", gclose)
        assert gclose.get("closed") is True
        post_gclose = be.list_tabs()
        assert nav4.tab_id not in [t.get("id") for t in post_gclose]
        assert "e2e3" not in be.list_groups()

        # Step 21: tabs.reset on e2e — closes its tab, clears binding
        reset = be.reset(group="e2e")
        results["steps"]["tabs_reset"] = reset
        _log("tabs_reset", reset)
        assert nav2.tab_id in (reset.get("closed") or [])

        # Step 21: groups.list — empty
        groups_final = be.list_groups()
        results["steps"]["groups_final"] = {"groups": list(groups_final.keys())}
        _log("groups_final", results["steps"]["groups_final"])
        assert "e2e" not in groups_final

        results["ok"] = True
        return 0
    except BaseException as e:
        import traceback as _tb
        tb_str = _tb.format_exc()
        results["ok"] = False
        results["error"] = repr(e)
        results["traceback"] = tb_str
        try:
            log_path.write_text(json.dumps(results, indent=2, default=str))
        except Exception:
            pass
        print(f"[e2e] FAILED: {e!r}\n{tb_str}", file=sys.stderr)
        return 2
    finally:
        log_path.write_text(json.dumps(results, indent=2, default=str))
        print(f"[e2e] log written: {log_path}")
        if chrome_proc and not args.keep_chrome:
            try:
                os.killpg(os.getpgid(chrome_proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
        if daemon_proc:
            try:
                os.killpg(os.getpgid(daemon_proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
        if installed_manifest and installed_manifest.exists():
            installed_manifest.unlink()
        if not args.keep_chrome:
            shutil.rmtree(udd, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
