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
import re
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
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
) -> Path:
    """保证 root 下有一份能跑的本平台 CfT，返回可执行文件路径。

    已经有就原样返回，什么都不下（force=True 时重取最新一版）。
    proxy=True 表示按本机探测；传字符串就用它；传 None/False 直连。
    """
    root = root or _root()
    say = progress or (lambda _msg: None)

    if not force and (found := installed_binary(root)):
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
            return found

        if proxy is True:
            from .proxy_detect import detect_local_proxy

            proxy = detect_local_proxy()
        proxy = proxy or None

        say(f"frago 要用自带的浏览器 Chrome for Testing，本机还没有，现在去取（平台 {key}）")
        version, url = fetch_manifest_entry(key, proxy=proxy)
        say(f"版本 {version}，放到 {root}")

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

    binary = root / rel
    say(f"CfT 已就位：{binary}")
    return binary
