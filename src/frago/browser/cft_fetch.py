"""frago 自己取 Chrome for Testing。

浏览器是 frago 的一部分，不是用户要装的东西：发现 `~/.frago/tools/chrome-for-testing/`
下没有本平台那份，就说明要用 CfT、取哪一版、多大、放哪儿，然后下载、解压、验过再挪进
正式位置。这一步曾经只能靠 agent 照着 how-to-install-frago 的步骤去做，于是舞台和
`frago browser start` 缺 CfT 时只能退回用户自己装的 Edge / Chrome——那是人日常在用的
浏览器，被 agent 占住时人会打不开它（见 `frago book desktop-usage`）。

每一处容易装成「文件都在、就是起不来」的地方都在这里收住：

- **平台**：只认 Google 版本清单里真有的平台（2026-09-15 实查：linux64、linux-arm64、
  mac-arm64、mac-x64、win32、win64）。别的平台直说没有官方 CfT，不重试。
- **解压**：macOS 的应用包里有符号链接，Linux 的可执行文件要执行位。Python 自带的
  zipfile 两样都丢，所以 macOS 用 `ditto`，Linux 优先 `unzip`，没有就自己按 zip 里记的
  权限和链接还原。
- **网络**：下载地址在 Google 的存储上，国内通常要走代理，复用浏览器那套本机代理探测。
  失败时报的是网络，不是「浏览器找不到」。
- **并发**：舞台和 `frago browser start` 可能同时发现缺 CfT。先拿锁，拿到后再看一眼是不是
  已经被别人装好；下载和解压都在同一文件系统的临时目录里做，最后一步整目录改名挪进去。
- **验证**：跑一次 `--version` 能报出版本号才算装好。Linux 上缺系统库时起不来，把缺的库
  和补装命令写进报错——那一步要 sudo，frago 不替人做。
"""
from __future__ import annotations

import contextlib
import json
import os
import platform as _platform
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

MANIFEST_URL = (
    "https://googlechromelabs.github.io/chrome-for-testing/"
    "last-known-good-versions-with-downloads.json"
)

# (系统, 机器架构) → 版本清单里的平台名。架构名按 platform.machine() 在各系统上的实际写法。
_PLATFORM_KEYS: dict[tuple[str, str], str] = {
    ("Darwin", "arm64"): "mac-arm64",
    ("Darwin", "x86_64"): "mac-x64",
    ("Linux", "x86_64"): "linux64",
    ("Linux", "amd64"): "linux64",
    ("Linux", "aarch64"): "linux-arm64",
    ("Linux", "arm64"): "linux-arm64",
    ("Windows", "AMD64"): "win64",
    ("Windows", "x86"): "win32",
}

Progress = Callable[[str], None]


class CftFetchError(RuntimeError):
    """取 CfT 失败。`kind` 说是哪一环，`remedy` 是人能照做的下一步（可能为空）。"""

    def __init__(self, kind: str, message: str, remedy: str | None = None) -> None:
        super().__init__(message if not remedy else f"{message}\n{remedy}")
        self.kind = kind
        self.remedy = remedy


def platform_key(system: str | None = None, machine: str | None = None) -> str | None:
    """本机在版本清单里叫什么；清单里没有本机平台时返回 None。"""
    system = system or _platform.system()
    machine = machine or _platform.machine()
    return _PLATFORM_KEYS.get((system, machine))


def _root() -> Path:
    from .backends.extension import cft_root

    return cft_root()


def installed_binary(root: Path | None = None) -> Path | None:
    """root 下本平台那份 CfT 的可执行文件，没有就 None。"""
    from .backends.extension import _CFT_RELATIVE_BINARIES

    root = root or _root()
    for rel in _CFT_RELATIVE_BINARIES.get(_platform.system(), ()):
        candidate = root / rel
        if candidate.exists():
            return candidate
    return None


def _relative_binary(key: str) -> str:
    """平台名 → 解压后可执行文件相对 root 的路径。"""
    from .backends.extension import _CFT_RELATIVE_BINARIES

    folder = f"chrome-{key}"
    for rel in _CFT_RELATIVE_BINARIES.get(_platform.system(), ()):
        if rel.replace("\\", "/").split("/", 1)[0] == folder:
            return rel
    raise CftFetchError("platform", f"frago 不认识平台 {key} 解压后的目录结构")


# ─────────────────────────────── 网络 ───────────────────────────────


def _opener(proxy: str | None) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    else:
        # 显式直连：不让 urllib 再去读环境变量里另一套代理，结果与报错里说的对不上。
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers)


def _network_error(what: str, proxy: str | None, exc: Exception) -> CftFetchError:
    via = f"经代理 {proxy}" if proxy else "直连（本机没探测到代理）"
    return CftFetchError(
        "network",
        f"{what}失败，{via}：{exc}",
        "Google 的下载地址在国内通常要走代理。开着代理客户端再试，或者设环境变量 "
        "FRAGO_BROWSER_PROXY=http://127.0.0.1:<端口> 指定代理。",
    )


def fetch_manifest_entry(key: str, *, proxy: str | None, timeout: float = 30.0) -> tuple[str, str]:
    """版本清单里 Stable 这一版本平台的 (版本号, 下载地址)。"""
    try:
        with _opener(proxy).open(MANIFEST_URL, timeout=timeout) as resp:
            data = json.load(resp)
    except Exception as e:
        raise _network_error("读 CfT 版本清单", proxy, e) from e
    stable = data["channels"]["Stable"]
    for item in stable["downloads"]["chrome"]:
        if item["platform"] == key:
            return stable["version"], item["url"]
    raise CftFetchError("platform", f"CfT 版本清单里没有平台 {key}")


def _download(url: str, dest: Path, *, proxy: str | None, progress: Progress) -> None:
    try:
        with _opener(proxy).open(url, timeout=60) as resp, open(dest, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            if total:
                progress(f"大小 {total / 1_000_000:.0f} MB")
            done, next_mark = 0, 10
            while chunk := resp.read(1 << 20):
                out.write(chunk)
                done += len(chunk)
                if total and done * 100 // total >= next_mark:
                    progress(f"已下载 {done * 100 // total}%")
                    next_mark += 10
    except Exception as e:
        raise _network_error("下载 CfT", proxy, e) from e
    if total and done != total:
        raise CftFetchError(
            "network", f"下载不完整：收到 {done} 字节，应为 {total} 字节",
            "网络中途断了，重试一次。",
        )


# ─────────────────────────────── 解压 ───────────────────────────────


def _extract_python(archive: Path, dest: Path) -> None:
    """按 zip 里记下的权限与符号链接还原。zipfile.extractall 两样都丢。"""
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            target = dest / info.filename
            mode = info.external_attr >> 16
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if stat.S_ISLNK(mode):
                os.symlink(zf.read(info).decode("utf-8"), target)
                continue
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            if mode & 0o777:
                os.chmod(target, mode & 0o777)


def extract(archive: Path, dest: Path, *, system: str | None = None) -> None:
    system = system or _platform.system()
    if system == "Darwin":
        cmd = ["ditto", "-x", "-k", str(archive), str(dest)]
    elif system == "Linux" and shutil.which("unzip"):
        cmd = ["unzip", "-q", str(archive), "-d", str(dest)]
    else:
        # Windows 的 zip 里没有符号链接也不看执行位；Linux 没有 unzip 时同样走这里。
        try:
            _extract_python(archive, dest)
        except (OSError, zipfile.BadZipFile) as e:
            raise CftFetchError("extract", f"解压 CfT 失败：{e}") from e
        return
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise CftFetchError("extract", f"解压 CfT 失败（{cmd[0]}）：{proc.stderr.strip()}")


# ─────────────────────────────── 验证 ───────────────────────────────

_MISSING_LIB = re.compile(r"error while loading shared libraries: (\S+?):")


def verify(binary: Path, *, system: str | None = None) -> str:
    """跑一次 --version，返回它报的版本串。起不来就抛带原因的错。"""
    system = system or _platform.system()
    if system == "Windows":
        # Windows 版 chrome.exe 不往控制台打版本号，只能确认文件在。
        if not binary.exists():
            raise CftFetchError("verify", f"解压后没找到 {binary}")
        return binary.name
    try:
        proc = subprocess.run(
            [str(binary), "--version"], capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise CftFetchError("verify", f"CfT 装好了但起不来：{e}") from e
    out = (proc.stdout or "").strip()
    if proc.returncode == 0 and out:
        return out
    err = (proc.stderr or proc.stdout or "").strip()
    lib = _MISSING_LIB.search(err)
    if lib:
        raise CftFetchError(
            "deps",
            f"CfT 已下载，但本机缺系统库 {lib.group(1)}，起不来",
            "补装要管理员权限，frago 不替你做。Debian/Ubuntu 上可以跑："
            "sudo apt-get install -y libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 "
            "libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 "
            "libasound2",
        )
    raise CftFetchError("verify", f"CfT 装好了但 --version 没报出版本号：{err[-400:]}")


# ─────────────────────────────── 包装器（macOS）───────────────────────────────

_WRAPPER_MARKER = "# frago-cft-wrapper v1"

_MACOS_WRAPPER_SCRIPT = f"""#!/usr/bin/env bash
{_WRAPPER_MARKER}
# Transparent launcher for Google Chrome for Testing.app on macOS.
# - Explicit automation/probe flags (--user-data-dir, --headless, --version, --type, etc.)
#   are passed straight through to the real binary (`Google Chrome for Testing.bin`).
# - Bare launches (Dock / Finder / Spotlight / `open -a`) ensure the frago extension daemon,
#   NativeMessagingHosts manifest, and profile preferences are ready, then exec the real
#   binary against `$HOME/.frago/profiles/cft/extension` with the current `extension_bundle`.
set -euo pipefail

SOURCE="${{BASH_SOURCE[0]}}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
  TARGET="$(readlink "$SOURCE")"
  if [[ "$TARGET" != /* ]]; then
    SOURCE="$DIR/$TARGET"
  else
    SOURCE="$TARGET"
  fi
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
REAL_BIN="$SCRIPT_DIR/Google Chrome for Testing.bin"

if [ ! -x "$REAL_BIN" ]; then
  echo "frago-cft-wrapper: missing real binary at $REAL_BIN" >&2
  exit 127
fi

for arg in "$@"; do
  case "$arg" in
    --user-data-dir=*|--user-data-dir|--headless=*|--headless|--version|--type=*|--load-extension=*|--load-extension|--remote-debugging-port=*|--dump-dom|-h|--help)
      exec "$REAL_BIN" "$@"
      ;;
  esac
done

_find_frago_cmd() {{
  local candidate
  local saved_path="${{PATH:-/usr/bin:/bin:/usr/sbin:/sbin}}"
  local search_path="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$HOME/.cargo/bin:$saved_path"
  local on_path=""
  on_path="$(PATH="$search_path" command -v frago 2>/dev/null || true)"
  for candidate in \
    "$on_path" \
    "$HOME/.local/bin/frago" \
    "/opt/homebrew/bin/frago" \
    "/usr/local/bin/frago" \
    "$HOME/.cargo/bin/frago"
  do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
      FRAGO_CMD=("$candidate")
      return 0
    fi
  done

  local py_hint="$HOME/.frago/chrome/python_path"
  if [ -r "$py_hint" ]; then
    local py_bin=""
    IFS= read -r py_bin < "$py_hint" || true
    if [ -n "$py_bin" ] && [ -x "$py_bin" ]; then
      FRAGO_CMD=("$py_bin" "-m" "frago.cli.main")
      return 0
    fi
  fi

  local uv_py="$HOME/.local/share/uv/tools/frago-cli/bin/python"
  if [ -x "$uv_py" ]; then
    FRAGO_CMD=("$uv_py" "-m" "frago.cli.main")
    return 0
  fi

  local py_user_bin
  for py_user_bin in "$HOME"/Library/Python/*/bin/frago; do
    if [ -x "$py_user_bin" ]; then
      FRAGO_CMD=("$py_user_bin")
      return 0
    fi
  done

  return 1
}}

PROFILE_DIR="$HOME/.frago/profiles/cft/extension"
BUNDLE_DIR=""
FRAGO_CMD=()

if _find_frago_cmd; then
  PREP_OUT="$("${{FRAGO_CMD[@]}}" extension prepare-cft --paths-only 2>/dev/null || true)"
  if [ -n "$PREP_OUT" ]; then
    {{
      IFS= read -r _prep_profile || true
      IFS= read -r _prep_bundle || true
    }} <<< "$PREP_OUT"
    if [ -n "${{_prep_profile:-}}" ]; then
      PROFILE_DIR="$_prep_profile"
    fi
    if [ -n "${{_prep_bundle:-}}" ] && [ -f "$_prep_bundle/manifest.json" ]; then
      BUNDLE_DIR="$_prep_bundle"
    fi
  fi
fi

mkdir -p "$PROFILE_DIR"

if [ -n "$BUNDLE_DIR" ]; then
  exec "$REAL_BIN" \
    "--user-data-dir=$PROFILE_DIR" \
    "--load-extension=$BUNDLE_DIR" \
    --no-first-run \
    --no-default-browser-check \
    --enable-logging=stderr \
    --disable-sync \
    "$@"
fi

echo "frago-cft-wrapper: warning: extension bundle not resolved, launching profile without --load-extension" >&2
exec "$REAL_BIN" \
  "--user-data-dir=$PROFILE_DIR" \
  --no-first-run \
  --no-default-browser-check \
  --enable-logging=stderr \
  --disable-sync \
  "$@"
"""


def _is_cft_wrapper(path: Path) -> bool:
    """Return True if ``path`` is already our transparent launcher wrapper."""
    if not path.is_file() or path.is_symlink():
        return False
    try:
        with path.open("rb") as f:
            head = f.read(256)
    except OSError:
        return False
    return _WRAPPER_MARKER.encode("utf-8") in head


def _app_bundle_for_binary(binary: Path) -> Path | None:
    """Return the enclosing ``.app`` bundle if ``binary`` lives in ``Contents/MacOS/``."""
    try:
        macos_dir = binary.parent
        contents_dir = macos_dir.parent
        app_bundle = contents_dir.parent
    except IndexError:
        return None
    if (
        macos_dir.name == "MacOS"
        and contents_dir.name == "Contents"
        and app_bundle.suffix == ".app"
        and (contents_dir / "Info.plist").is_file()
    ):
        return app_bundle
    return None


def record_runtime_python_hint() -> None:
    """Persist ``sys.executable`` so LaunchServices bare launches can locate frago."""
    chrome_dir = Path.home() / ".frago" / "chrome"
    with contextlib.suppress(OSError):
        chrome_dir.mkdir(parents=True, exist_ok=True)
        hint_file = chrome_dir / "python_path"
        current = hint_file.read_text(encoding="utf-8").strip() if hint_file.exists() else ""
        if current != sys.executable:
            tmp = hint_file.with_name(".python_path.frago-tmp")
            tmp.write_text(f"{sys.executable}\n", encoding="utf-8")
            tmp.replace(hint_file)


def _initialize_default_cft_environment(say: Progress) -> None:
    """Initialize default CfT extension profile, launcher, and NativeMessagingHosts."""
    from .extension.lifecycle import initialize_cft_environment

    info = initialize_cft_environment(ensure_daemon=False)
    if info.get("prefs_initialized"):
        say(f"已初始化 CfT 默认 Profile：{info['profile_dir']}")


_COOKIE_GUARD_BACKUP_DIR_NAME = ".cookie-guard-backups"
_MAX_COOKIE_GUARD_BACKUPS = 5
_PROFILE_AUTH_FILES: tuple[str, ...] = (
    "Local State",
    "Default/Network/Cookies",
    "Default/Network/Cookies-journal",
    "Default/Network/Cookies-wal",
    "Default/Network/Cookies-shm",
    "Default/Cookies",
    "Default/Cookies-journal",
    "Default/Preferences",
    "Default/Secure Preferences",
)
_COOKIE_DB_FILES: tuple[str, ...] = (
    "Default/Network/Cookies",
    "Default/Cookies",
)
_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+\.\d+|\d+\.\d+)")


@dataclass(frozen=True)
class CftProfileGuardReport:
    """Non-secret metadata summary for one managed CfT profile directory."""

    profile_dir: Path
    locked: bool
    lock_pid: int | None
    has_cookie_assets: bool
    cookie_files: tuple[str, ...]
    asset_files: tuple[str, ...]
    cookie_bytes: dict[str, int]
    total_bytes: int


@dataclass(frozen=True)
class CftCookieGuardResult:
    """Pre-check outcome before CfT upgrade, replacement, or bundle re-sign."""

    profiles_root: Path
    reports: tuple[CftProfileGuardReport, ...]
    locked_profiles: tuple[Path, ...]
    cookie_profiles: tuple[Path, ...]
    old_version: str | None
    new_version: str | None
    major_upgrade: bool
    backup_dir: Path | None


def cft_profiles_root(profiles_root: Path | None = None) -> Path:
    """Return the managed CfT profiles root (``~/.frago/profiles/cft``)."""
    return profiles_root or (Path.home() / ".frago" / "profiles" / "cft")


def _is_under_default_root(binary: Path) -> bool:
    try:
        binary.resolve().relative_to(_root().resolve())
        return True
    except (OSError, ValueError):
        return False


def _app_bundle_info(binary: Path) -> tuple[str | None, str | None]:
    """Read ``(CFBundleIdentifier, version)`` from enclosing ``Info.plist`` without secrets."""
    app_bundle = _app_bundle_for_binary(binary)
    if app_bundle is None:
        return (None, None)
    plist_path = app_bundle / "Contents" / "Info.plist"
    try:
        with plist_path.open("rb") as f:
            data = plistlib.load(f)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return (None, None)
    if not isinstance(data, dict):
        return (None, None)
    bundle_id = data.get("CFBundleIdentifier")
    if not isinstance(bundle_id, str) or not bundle_id.strip():
        bundle_id = None
    else:
        bundle_id = bundle_id.strip()
    version: str | None = None
    for key in ("CFBundleShortVersionString", "CFBundleVersion"):
        raw = data.get(key)
        if isinstance(raw, str) and _VERSION_RE.search(raw):
            version = _VERSION_RE.search(raw).group(1)  # type: ignore[union-attr]
            break
    return (bundle_id, version)


def installed_cft_version(binary: Path | None) -> str | None:
    """Best-effort version string of an existing CfT installation."""
    if binary is None or not binary.exists():
        return None
    _bundle_id, plist_ver = _app_bundle_info(binary)
    if plist_ver:
        return plist_ver
    if _platform.system() != "Windows":
        try:
            proc = subprocess.run(
                [str(binary), "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            out = (proc.stdout or "").strip()
            if proc.returncode == 0 and out and (match := _VERSION_RE.search(out)):
                return match.group(1)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


def _major_version(version: str | None) -> int | None:
    if not version:
        return None
    match = re.match(r"^(\d+)", version.strip())
    return int(match.group(1)) if match else None


def _iter_cft_profile_dirs(profiles_root: Path) -> list[Path]:
    if not profiles_root.is_dir():
        return []
    return sorted(
        (
            p
            for p in profiles_root.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        ),
        key=lambda p: p.name,
    )


def _read_profile_lock_pid(profile_dir: Path) -> int | None:
    lock = profile_dir / "SingletonLock"
    if not lock.is_symlink() and not lock.exists():
        return None
    try:
        target = os.readlink(lock) if lock.is_symlink() else lock.resolve(strict=False).name
        target_name = Path(target).name
        return int(target_name.rsplit("-", 1)[-1])
    except (OSError, ValueError):
        return None


def _is_profile_locked(profile_dir: Path) -> tuple[bool, int | None]:
    lock = profile_dir / "SingletonLock"
    if not lock.exists() and not lock.is_symlink():
        return (False, None)
    pid = _read_profile_lock_pid(profile_dir)
    if pid is None:
        return (True, None)
    if os.name == "nt":
        return (True, pid)
    try:
        os.kill(pid, 0)
        return (True, pid)
    except ProcessLookupError:
        return (False, pid)
    except PermissionError:
        return (True, pid)
    except OSError:
        return (False, pid)


def inspect_cft_profiles(profiles_root: Path | None = None) -> tuple[CftProfileGuardReport, ...]:
    """Inspect managed CfT profiles using filesystem metadata only (never reads secrets)."""
    root_dir = cft_profiles_root(profiles_root)
    reports: list[CftProfileGuardReport] = []
    for pdir in _iter_cft_profile_dirs(root_dir):
        locked, lock_pid = _is_profile_locked(pdir)
        asset_files: list[str] = []
        cookie_files: list[str] = []
        cookie_bytes: dict[str, int] = {}
        total_bytes = 0
        for rel in _PROFILE_AUTH_FILES:
            fpath = pdir / rel
            try:
                if not fpath.is_file():
                    continue
                size = fpath.stat().st_size
            except OSError:
                continue
            asset_files.append(rel)
            total_bytes += size
            if rel in _COOKIE_DB_FILES and size > 0:
                cookie_files.append(rel)
                cookie_bytes[rel] = size
        reports.append(
            CftProfileGuardReport(
                profile_dir=pdir,
                locked=locked,
                lock_pid=lock_pid,
                has_cookie_assets=bool(cookie_files),
                cookie_files=tuple(cookie_files),
                asset_files=tuple(asset_files),
                cookie_bytes=cookie_bytes,
                total_bytes=total_bytes,
            )
        )
    return tuple(reports)


def _prune_old_cookie_backups(backups_root: Path, keep: int = _MAX_COOKIE_GUARD_BACKUPS) -> None:
    if not backups_root.is_dir():
        return
    dirs = sorted(
        (d for d in backups_root.iterdir() if d.is_dir() and not d.name.startswith(".")),
        key=lambda d: d.name,
    )
    for stale in dirs[: max(0, len(dirs) - keep)]:
        shutil.rmtree(stale, ignore_errors=True)


def snapshot_cft_profiles(
    profiles_root: Path,
    reports: tuple[CftProfileGuardReport, ...],
    *,
    reason: str,
    old_version: str | None = None,
    new_version: str | None = None,
) -> Path:
    """Create a 0700 atomic snapshot of Cookies/Local State/Preferences metadata files."""
    backups_root = profiles_root / _COOKIE_GUARD_BACKUP_DIR_NAME
    backups_root.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        backups_root.chmod(0o700)

    safe_reason = re.sub(r"[^a-zA-Z0-9_-]+", "-", reason).strip("-") or "guard"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    staging = Path(tempfile.mkdtemp(prefix=f".tmp-{safe_reason}-", dir=backups_root))
    try:
        with contextlib.suppress(OSError):
            staging.chmod(0o700)

        manifest_profiles: dict[str, dict[str, int]] = {}
        for rep in reports:
            if not rep.asset_files:
                continue
            prof_dest = staging / rep.profile_dir.name
            prof_meta: dict[str, int] = {}
            for rel in rep.asset_files:
                src = rep.profile_dir / rel
                if not src.is_file():
                    continue
                dst = prof_dest / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                prof_meta[rel] = dst.stat().st_size
            if prof_meta:
                manifest_profiles[rep.profile_dir.name] = prof_meta

        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "reason": safe_reason,
            "old_version": old_version,
            "new_version": new_version,
            "profiles": manifest_profiles,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        final_dir = backups_root / f"{stamp}-{safe_reason}"
        suffix = 1
        while final_dir.exists():
            final_dir = backups_root / f"{stamp}-{safe_reason}-{suffix}"
            suffix += 1
        staging.rename(final_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    _prune_old_cookie_backups(backups_root)
    return final_dir


def restore_cft_profile_snapshot(
    snapshot_dir: Path,
    profiles_root: Path | None = None,
) -> list[Path]:
    """Restore backed-up Cookies/Local State/Preferences files from ``snapshot_dir``."""
    root_dir = cft_profiles_root(profiles_root)
    if not snapshot_dir.is_dir():
        raise CftFetchError("backup", f"快照目录不存在：{snapshot_dir}")

    restored: list[Path] = []
    for prof_backup in sorted(p for p in snapshot_dir.iterdir() if p.is_dir()):
        target_profile = root_dir / prof_backup.name
        locked, pid = _is_profile_locked(target_profile)
        if locked:
            raise CftFetchError(
                "locked",
                f"恢复快照前发现 Profile 仍在运行中（{target_profile}，PID={pid}）",
                "请先执行 `frago browser stop` 关闭浏览器后再恢复快照。",
            )
        for rel in _PROFILE_AUTH_FILES:
            src = prof_backup / rel
            if not src.is_file():
                continue
            dst = target_profile / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(f".{dst.name}.frago-restore")
            shutil.copy2(src, tmp)
            os.replace(tmp, dst)
            restored.append(dst)
    return restored


def precheck_cft_cookie_guard(
    *,
    existing_binary: Path | None,
    new_version: str | None = None,
    reason: str = "upgrade",
    profiles_root: Path | None = None,
    allow_cookie_risk: bool = False,
    system: str | None = None,
    progress: Progress | None = None,
) -> CftCookieGuardResult:
    """Pre-check managed CfT profiles for live locks and Cookie/Keychain wipe risk.

    1. Blocks immediately if any managed CfT profile holds an active ``SingletonLock``.
    2. Creates a 0700 atomic snapshot of Cookies/Local State/Preferences whenever
       auth assets exist before upgrading or re-signing.
    3. On cross-major-version replacement or macOS ad-hoc binary replacement when
       Cookie assets exist, intercepts unless explicitly opted in via
       ``allow_cookie_risk=True`` or ``FRAGO_CFT_ALLOW_COOKIE_RISK=1``.
    """
    say = progress or (lambda _msg: None)
    system = system or _platform.system()
    resolved_profiles = cft_profiles_root(profiles_root)
    reports = inspect_cft_profiles(resolved_profiles)
    locked_profiles = tuple(r.profile_dir for r in reports if r.locked)
    cookie_profiles = tuple(r.profile_dir for r in reports if r.has_cookie_assets)

    if locked_profiles:
        names = ", ".join(p.name for p in locked_profiles)
        raise CftFetchError(
            "locked",
            f"受管 CfT Profile（{names}）正在运行中，禁止在占锁状态下执行升级或重签",
            "请先执行 `frago browser stop`（如有 CDP 实例则同时停止）后再重试。",
        )

    old_version = installed_cft_version(existing_binary)
    old_major = _major_version(old_version)
    new_major = _major_version(new_version)
    major_upgrade = bool(
        old_major is not None and new_major is not None and old_major != new_major
    )

    backup_dir: Path | None = None
    if any(r.asset_files for r in reports):
        try:
            backup_dir = snapshot_cft_profiles(
                resolved_profiles,
                reports,
                reason=reason,
                old_version=old_version,
                new_version=new_version,
            )
        except OSError as e:
            raise CftFetchError(
                "backup",
                f"升级或重签前创建受管 Profile 登录态快照失败：{e}",
                "请先手动备份 ~/.frago/profiles/cft 后再重试。",
            ) from e
        say(f"已创建受管 CfT 登录态安全快照：{backup_dir}")

    if reason == "force-upgrade" and existing_binary is not None and cookie_profiles:
        high_risk = major_upgrade or (system == "Darwin")
        effective_allow = allow_cookie_risk or (
            os.environ.get("FRAGO_CFT_ALLOW_COOKIE_RISK") == "1"
        )
        if high_risk and not effective_allow:
            ver_desc = (
                f"{old_version} -> {new_version}"
                if old_version and new_version
                else (new_version or old_version or "跨版本/重签替换")
            )
            prof_names = ", ".join(p.name for p in cookie_profiles)
            raise CftFetchError(
                "cookie_guard",
                f"拦截高危 CfT 升级（{ver_desc}）：受管 Profile（{prof_names}）存在已登录 Cookie，"
                "跨主版本替换或 macOS ad-hoc 重签可能导致 Keychain Safe Storage 解密失败并清空登录态",
                f"已预先备份关键凭据快照至：{backup_dir}\n"
                "若确认需要继续强制升级并承担重新登录风险，请以 "
                "FRAGO_CFT_ALLOW_COOKIE_RISK=1 重试。",
            )

    return CftCookieGuardResult(
        profiles_root=resolved_profiles,
        reports=reports,
        locked_profiles=locked_profiles,
        cookie_profiles=cookie_profiles,
        old_version=old_version,
        new_version=new_version,
        major_upgrade=major_upgrade,
        backup_dir=backup_dir,
    )


def _verify_protected_cookie_assets(
    reports: tuple[CftProfileGuardReport, ...],
    backup_dir: Path | None,
) -> None:
    """Verify protected Cookie DB files did not vanish or truncate during mutation."""
    corrupted: list[str] = []
    for rep in reports:
        for rel, before_size in rep.cookie_bytes.items():
            if before_size <= 0:
                continue
            target = rep.profile_dir / rel
            try:
                now_size = target.stat().st_size if target.is_file() else 0
            except OSError:
                now_size = 0
            if now_size == 0:
                corrupted.append(f"{rep.profile_dir.name}/{rel}")

    if corrupted:
        restored_note = ""
        if backup_dir is not None:
            with contextlib.suppress(Exception):
                restore_cft_profile_snapshot(
                    backup_dir, profiles_root=reports[0].profile_dir.parent
                )
                restored_note = f"（已自动从快照 {backup_dir} 回滚恢复）"
        raise CftFetchError(
            "cookie_guard",
            f"检测到受管 Cookie 文件在操作后丢失或归零：{', '.join(corrupted)}{restored_note}",
        )


def ensure_cft_wrapper(
    binary: Path,
    *,
    system: str | None = None,
    profiles_root: Path | None = None,
    check_profiles: bool = True,
    progress: Progress | None = None,
) -> bool:
    """Install or idempotently update the macOS CfT transparent launcher wrapper.

    Moves the real Mach-O binary to ``<binary>.bin`` if needed, writes the
    transparent launcher script at ``binary``, and re-signs the ``.app``
    bundle preserving ``CFBundleIdentifier``.

    Before mutating an existing installed bundle, checks managed CfT profile
    locks and creates a 0700 snapshot backup of Cookies / Local State /
    Preferences when applicable.

    If writing the wrapper or re-signing fails midway, automatically rolls back
    so the original ``.bin`` binary (or previous wrapper) is restored in place
    and the ``.app`` bundle is never left broken.

    Returns True when changes were applied, False when already up-to-date or
    not applicable (non-Darwin / non-.app test fixture).
    """
    system = system or _platform.system()
    if system != "Darwin":
        return False
    if not binary.exists():
        return False
    app_bundle = _app_bundle_for_binary(binary)
    if app_bundle is None:
        return False

    real_bin = binary.with_name(f"{binary.name}.bin")
    is_wrapper = _is_cft_wrapper(binary)
    old_wrapper_bytes: bytes | None = None
    moved_real_bin = False

    if is_wrapper and real_bin.exists():
        try:
            if binary.read_text(encoding="utf-8") == _MACOS_WRAPPER_SCRIPT:
                return False
            old_wrapper_bytes = binary.read_bytes()
        except OSError:
            pass
    elif is_wrapper and not real_bin.exists():
        raise CftFetchError(
            "verify",
            f"CfT 包装器存在但缺少真实二进制：{real_bin}",
            "请执行 `frago browser install --force` 重新获取 Chrome for Testing。",
        )

    effective_profiles_root: Path | None = None
    if check_profiles:
        if profiles_root is not None:
            effective_profiles_root = profiles_root
        elif _is_under_default_root(binary):
            effective_profiles_root = cft_profiles_root()

    guard_result: CftCookieGuardResult | None = None
    if effective_profiles_root is not None:
        guard_result = precheck_cft_cookie_guard(
            existing_binary=binary,
            new_version=None,
            reason="wrapper-resign",
            profiles_root=effective_profiles_root,
            allow_cookie_risk=True,
            system=system,
            progress=progress,
        )

    if not is_wrapper:
        # Fresh download or overwritten .app: preserve the real binary as .bin.
        os.replace(binary, real_bin)
        real_bin.chmod(real_bin.stat().st_mode | 0o755)
        moved_real_bin = True

    bundle_id, _ = _app_bundle_info(binary)
    tmp_wrapper = binary.with_name(f".{binary.name}.frago-tmp")
    try:
        tmp_wrapper.write_text(_MACOS_WRAPPER_SCRIPT, encoding="utf-8")
        tmp_wrapper.chmod(0o755)
        os.replace(tmp_wrapper, binary)

        if shutil.which("codesign"):
            id_args = ["--identifier", bundle_id] if bundle_id else []
            # Only sign .bin when freshly moved so wrapper-template updates do
            # not churn .bin's CDHash unnecessarily; sign .app without --deep to
            # keep CFBundleIdentifier consistent without disturbing nested helpers.
            if moved_real_bin:
                bin_proc = subprocess.run(
                    ["codesign", "--force", "-s", "-", *id_args, str(real_bin)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if bin_proc.returncode != 0:
                    raise CftFetchError(
                        "codesign",
                        f"CfT 主二进制重签名失败：{(bin_proc.stderr or bin_proc.stdout).strip()}",
                    )
            proc = subprocess.run(
                ["codesign", "--force", "-s", "-", *id_args, str(app_bundle)],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                raise CftFetchError(
                    "codesign",
                    f"CfT 应用包重签名失败：{(proc.stderr or proc.stdout).strip()}",
                )
    except BaseException:
        with contextlib.suppress(OSError):
            tmp_wrapper.unlink()
        if moved_real_bin and real_bin.exists():
            with contextlib.suppress(OSError):
                os.replace(real_bin, binary)
        elif old_wrapper_bytes is not None:
            tmp_restore = binary.with_name(f".{binary.name}.frago-restore")
            with contextlib.suppress(OSError):
                tmp_restore.write_bytes(old_wrapper_bytes)
                tmp_restore.chmod(0o755)
                os.replace(tmp_restore, binary)
        raise

    if guard_result is not None and guard_result.cookie_profiles:
        _verify_protected_cookie_assets(guard_result.reports, guard_result.backup_dir)
    return True


# ─────────────────────────────── 并发 ───────────────────────────────


@contextlib.contextmanager
def _locked(lock_path: Path, timeout: float = 900.0) -> Iterator[None]:
    """同一台机器上只让一个进程在装。等不到就报错，不和别人抢着写同一个目录。"""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+")  # noqa: SIM115 — 锁要跨 yield 持有
    deadline = time.time() + timeout
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as e:
                if time.time() > deadline:
                    raise CftFetchError(
                        "busy", f"另一个进程正在装 CfT，等了 {int(timeout)} 秒还没装完"
                    ) from e
                time.sleep(1.0)
        yield
    finally:
        with contextlib.suppress(OSError):
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()


# ─────────────────────────────── 入口 ───────────────────────────────


def ensure_cft(
    *,
    root: Path | None = None,
    force: bool = False,
    progress: Progress | None = None,
    proxy: str | None | bool = True,
    allow_cookie_risk: bool = False,
    profiles_root: Path | None = None,
) -> Path:
    """保证 root 下有一份能跑的本平台 CfT，返回可执行文件路径。

    已经有就原样返回，什么都不下（force=True 时重取最新一版）。
    proxy=True 表示按本机探测；传字符串就用它；传 None/False 直连。
    """
    default_root = _root()
    use_default_root = root is None or root == default_root
    root = root or default_root
    say = progress or (lambda _msg: None)
    effective_profiles_root = (
        profiles_root
        if profiles_root is not None
        else (cft_profiles_root() if use_default_root else None)
    )

    if not force and (found := installed_binary(root)):
        if ensure_cft_wrapper(
            found,
            profiles_root=effective_profiles_root,
            check_profiles=effective_profiles_root is not None,
            progress=say,
        ):
            say(f"已更新 CfT 透明启动包装器：{found}")
        if use_default_root:
            record_runtime_python_hint()
            _initialize_default_cft_environment(say)
        return found

    key = platform_key()
    if key is None:
        raise CftFetchError(
            "platform",
            f"Google 没有为 {_platform.system()} {_platform.machine()} 发布 Chrome for Testing，"
            "frago 取不到自带浏览器",
        )

    with _locked(root.parent / f".{root.name}.lock"):
        # 等锁期间别的进程可能已经装好了。
        if not force and (found := installed_binary(root)):
            if ensure_cft_wrapper(
                found,
                profiles_root=effective_profiles_root,
                check_profiles=effective_profiles_root is not None,
                progress=say,
            ):
                say(f"已更新 CfT 透明启动包装器：{found}")
            if use_default_root:
                record_runtime_python_hint()
                _initialize_default_cft_environment(say)
            return found

        if proxy is True:
            from .proxy_detect import detect_local_proxy

            proxy = detect_local_proxy()
        proxy = proxy or None

        existing = installed_binary(root)
        say(f"frago 要用自带的浏览器 Chrome for Testing，本机还没有，现在去取（平台 {key}）")
        version, url = fetch_manifest_entry(key, proxy=proxy)
        say(f"版本 {version}，放到 {root}")

        guard_result: CftCookieGuardResult | None = None
        if force and existing is not None and effective_profiles_root is not None:
            guard_result = precheck_cft_cookie_guard(
                existing_binary=existing,
                new_version=version,
                reason="force-upgrade",
                profiles_root=effective_profiles_root,
                allow_cookie_risk=allow_cookie_risk,
                progress=say,
            )

        root.parent.mkdir(parents=True, exist_ok=True)
        # 临时目录和正式位置在同一个文件系统上，最后那一下改名才是原子的。
        staging = Path(tempfile.mkdtemp(prefix=f".{root.name}-", dir=root.parent))
        try:
            archive = staging / f"chrome-{key}.zip"
            _download(url, archive, proxy=proxy, progress=say)
            say("解压中")
            unpacked = staging / "unpacked"
            unpacked.mkdir()
            extract(archive, unpacked)
            archive.unlink()

            rel = _relative_binary(key)
            if ensure_cft_wrapper(unpacked / rel, check_profiles=False):
                say("已注入透明启动包装器并完成本地重签名")
            say(f"验证：{verify(unpacked / rel)}")

            folder = rel.replace("\\", "/").split("/", 1)[0]
            root.mkdir(parents=True, exist_ok=True)
            target = root / folder
            if target.exists():
                # force 重取：旧的先挪进临时目录，新的就位后随临时目录一起删。
                target.rename(staging / "previous")
            (unpacked / folder).rename(target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    if guard_result is not None and guard_result.cookie_profiles:
        _verify_protected_cookie_assets(guard_result.reports, guard_result.backup_dir)

    binary = root / rel
    if use_default_root:
        record_runtime_python_hint()
        _initialize_default_cft_environment(say)
    say(f"CfT 已就位：{binary}")
    return binary
