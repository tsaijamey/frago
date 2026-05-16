"""Live smoke: drive Upwork browsing through frago-bridge in real Edge profile.

Prereqs:
    - Edge is closed (profile lock)
    - User has logged into upwork.com in the default Edge profile beforehand
    - frago-bridge bundle is auto-resolved via importlib.resources from the installed frago package

Differences from e2e_demo.py (which uses a throwaway temp profile):
    - --user-data-dir points at ~/.config/microsoft-edge/ (REAL default profile)
    - No --disable-extensions-except (user's other extensions stay live)
    - No UDD cleanup (it's the user's real profile)
    - Edge is left running by default (so the user can inspect)

Usage:
    uv run python tests/extension/e2e/upwork_smoke.py
    uv run python tests/extension/e2e/upwork_smoke.py --kill-edge   # tear down at end
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

from frago.chrome.extension import bundle_path
from frago.chrome.extension.native_host import (
    SOCK_PATH, install_manifest,
)
from frago.chrome.backends.extension import (
    ExtensionBackendError, ExtensionChromeBackend,
)

BUNDLE_DIR = bundle_path()


def log(label: str, payload=None) -> None:
    if payload is None:
        print(f"[upwork-e2e] {label}")
    else:
        print(f"[upwork-e2e] {label}: "
              f"{json.dumps(payload, ensure_ascii=False, default=str)[:600]}")


def wait_socket(path: Path, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return
        time.sleep(0.1)
    raise TimeoutError(f"daemon socket {path} not created in {timeout}s")


def wait_bridge(timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            return ExtensionChromeBackend().start()
        except (ExtensionBackendError, FileNotFoundError, ConnectionError) as e:
            last_err = e
            time.sleep(0.5)
    raise TimeoutError(f"bridge timeout: {last_err}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", default="/usr/bin/microsoft-edge")
    ap.add_argument("--profile", type=Path,
                    default=Path.home() / ".config" / "microsoft-edge",
                    help="Edge user-data-dir. Default: real profile root.")
    ap.add_argument("--out", default=str(REPO_ROOT / "outputs" / "upwork_e2e"))
    ap.add_argument("--kill-edge", action="store_true",
                    help="Tear down Edge at end (default: leave running).")
    ap.add_argument("--settle", type=float, default=4.0,
                    help="Seconds to wait after navigation for JS to settle.")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    udd = args.profile
    if not udd.exists():
        sys.exit(f"profile dir does not exist: {udd}")

    # Refuse to run if Edge is already running on this profile.
    pgrep = subprocess.run(
        ["pgrep", "-f", "microsoft-edge"], capture_output=True, text=True)
    if pgrep.stdout.strip():
        sys.exit("Edge is already running. Close it first (the default profile "
                 "is locked while Edge is open).")

    if SOCK_PATH.exists():
        SOCK_PATH.unlink()

    daemon_log = out_dir / "daemon.log"
    edge_log_path = out_dir / "edge.log"
    log_path = out_dir / "upwork_log.json"
    results: dict = {"steps": {}}
    daemon_proc = None
    edge_proc = None
    try:
        # 1. daemon
        daemon_proc = subprocess.Popen(
            [sys.executable, "-m", "frago.cli.main", "extension", "daemon"],
            stdout=open(daemon_log, "wb"), stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        wait_socket(SOCK_PATH, timeout=5.0)
        log("daemon_up", {"pid": daemon_proc.pid})

        # 2. native messaging manifest at <udd>/NativeMessagingHosts/
        launcher = Path.home() / ".frago" / "chrome" / "native_host_launcher.sh"
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_text(
            "#!/usr/bin/env bash\n"
            f"exec {sys.executable} -m frago.cli.main extension native-host\n"
        )
        launcher.chmod(0o755)
        manifest_path = install_manifest(
            str(launcher), target_dir=udd / "NativeMessagingHosts")
        log("manifest_installed", {"path": str(manifest_path)})

        # 3. launch Edge — real profile, keep other extensions, sideload ours.
        edge_log = open(edge_log_path, "wb")
        edge_proc = subprocess.Popen(
            [
                args.browser,
                f"--user-data-dir={udd}",
                f"--load-extension={BUNDLE_DIR}",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ],
            stdout=edge_log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        log("edge_launched", {"pid": edge_proc.pid})

        # 4. bridge handshake
        info = wait_bridge(timeout=30.0)
        log("bridge_up",
            {"extensionId": info.get("bridge", {}).get("extensionId")})
        results["steps"]["bridge_up"] = info

        be = ExtensionChromeBackend(timeout=60.0)

        # 5. navigate to find-work
        log("navigating", {"url": "https://www.upwork.com/nx/find-work/"})
        nav = be.navigate("https://www.upwork.com/nx/find-work/",
                          group="upwork", timeout=30.0)
        results["steps"]["navigate_findwork"] = {
            "tab_id": nav.tab_id, "url": nav.url, "title": nav.title}
        log("navigate_findwork",
            {"url": nav.url, "title": nav.title})
        time.sleep(args.settle)

        # 6. content + login-state heuristic
        content = be.get_content(group="upwork")
        text = content.text or ""
        title = content.title or ""
        results["steps"]["findwork_content"] = {
            "url": content.url, "title": title,
            "text_len": len(text),
            "text_preview": text[:600],
        }
        log("findwork_content",
            {"url": content.url, "title": title, "text_len": len(text)})

        signals = {
            "logged_in_marker": any(s in text.lower() for s in
                                    ["log out", "your jobs", "my jobs",
                                     "saved jobs", "messages"]),
            "login_wall": any(s in title.lower() for s in
                              ["log in", "sign in"]) or
                          any(s in text.lower() for s in
                              ["log in to access", "sign in to upwork"]),
            "blocked": any(s in text.lower() for s in
                           ["access denied", "unusual activity",
                            "we noticed unusual", "request id",
                            "captcha", "verify you are human"]),
        }
        results["steps"]["findwork_signals"] = signals
        log("findwork_signals", signals)

        shot1 = be.screenshot(group="upwork",
                              output=str(out_dir / "findwork.png"))
        log("findwork_screenshot",
            {"path": shot1.path,
             "png_bytes": len(shot1.png_base64 or "") * 3 // 4})

        # 7. extract first job link from the page
        js = be.exec_js(r"""
            (() => {
                const links = Array.from(document.querySelectorAll('a[href*="/jobs/"]'));
                const seen = new Set();
                const jobs = [];
                for (const a of links) {
                    const m = /\/jobs\/[^?#]*~[0-9a-zA-Z]+/.exec(a.href);
                    if (m && !seen.has(a.href)) {
                        seen.add(a.href);
                        jobs.push({href: a.href,
                                   text: (a.innerText || "").slice(0, 120)});
                        if (jobs.length >= 3) break;
                    }
                }
                return jobs;
            })()
        """, group="upwork")
        candidates = js.value or []
        results["steps"]["job_link_candidates"] = candidates
        log("job_link_candidates", candidates)
        if not candidates:
            log("no_job_links_found",
                "find-work page did not yield job detail links — "
                "user likely not logged in, or anti-bot rendered an empty page")
            results["ok"] = False
            results["reason"] = "no job links extractable from find-work page"
            return 1

        # 8. navigate to first job's detail
        job_url = candidates[0]["href"]
        log("navigating_job_detail", {"url": job_url})
        nav2 = be.navigate(job_url, group="upwork", timeout=30.0)
        results["steps"]["navigate_jobdetail"] = {
            "tab_id": nav2.tab_id, "url": nav2.url, "title": nav2.title}
        log("navigate_jobdetail", {"url": nav2.url, "title": nav2.title})
        time.sleep(args.settle)

        # 9. job detail content
        detail = be.get_content(group="upwork")
        detail_text = detail.text or ""
        results["steps"]["jobdetail_content"] = {
            "url": detail.url, "title": detail.title,
            "text_len": len(detail_text),
            "text_preview": detail_text[:1000],
        }
        log("jobdetail_content",
            {"url": detail.url, "title": detail.title,
             "text_len": len(detail_text)})

        detail_signals = {
            "looks_like_real_job": any(s in detail_text.lower() for s in
                                       ["budget", "fixed-price", "hourly",
                                        "proposals", "client's recent",
                                        "skills required", "submit a proposal"]),
            "blocked": any(s in detail_text.lower() for s in
                           ["access denied", "unusual activity",
                            "captcha", "verify you are human"]),
        }
        results["steps"]["jobdetail_signals"] = detail_signals
        log("jobdetail_signals", detail_signals)

        shot2 = be.screenshot(group="upwork",
                              output=str(out_dir / "jobdetail.png"))
        log("jobdetail_screenshot",
            {"path": shot2.path,
             "png_bytes": len(shot2.png_base64 or "") * 3 // 4})

        results["ok"] = (signals["logged_in_marker"]
                        and detail_signals["looks_like_real_job"]
                        and not signals["blocked"]
                        and not detail_signals["blocked"])
        return 0 if results["ok"] else 2
    except BaseException as e:
        import traceback as _tb
        results["ok"] = False
        results["error"] = repr(e)
        results["traceback"] = _tb.format_exc()
        print(f"[upwork-e2e] FAILED: {e!r}", file=sys.stderr)
        return 3
    finally:
        log_path.write_text(json.dumps(results, indent=2, default=str,
                                       ensure_ascii=False))
        print(f"[upwork-e2e] log: {log_path}")
        if args.kill_edge:
            for proc in (edge_proc, daemon_proc):
                if proc is None:
                    continue
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
        else:
            print(f"[upwork-e2e] Edge and daemon left running.")
            if edge_proc:
                print(f"  edge pid:   {edge_proc.pid}")
            if daemon_proc:
                print(f"  daemon pid: {daemon_proc.pid}")


if __name__ == "__main__":
    sys.exit(main())
