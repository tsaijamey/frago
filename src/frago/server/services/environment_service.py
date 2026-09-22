"""环境仪表盘：跑 frago 需要的每样东西，本机装的是哪一版、外面出到哪一版。

**这张清单不是这里定的，是照装机向导抄的。** 装机时那份探测脚本查哪几样——git、uv、
tmux、浏览器、ffmpeg、gh，Linux 再加 bubblewrap，外加四个 agent 命令行——这里就报哪
几样，再加上 frago 自己。两处对不上，用户装完看到的和事后查到的就成了两台机器。

**每一格只并排放两个数字，不替人下结论。** 「外面出到 x」不等于「你该升级」：tmux 和
git 差一个小版本对用户毫无影响，而 agent 命令行几乎天天在发版。谁该动、什么时候动，
看的人自己判断。

**唯一被特殊对待的是 frago 自己：从本地 wheel 装的那份永远不报可更新。** 开发机上的
frago 是自己构建装上去的，版本号通常比线上大；照版本号比大小，会劝人把自己的构建覆盖
成一个更旧的线上版。判据不是版本号，是这份包的安装记录里写的来源——本地文件还是索引。

**两边都缓存。** 问外面要版本号是十来次跨境请求（缓存六小时、落盘），问本机要版本号是
十来次子进程（缓存一分钟、在内存里）。这张表的入口是侧边栏上一颗常驻按钮，不缓存的话，
代价全落在从不点开它的人身上。
"""

import json
import logging
import os
import platform
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

# 外面的版本号缓存多久。跨境请求十来次，六小时一轮足够跟上——没有哪一样东西是发布后
# 几小时之内非升不可的。
LATEST_TTL_SECONDS = 6 * 3600

# 本机版本号缓存多久。子进程十来个，一分钟一轮：人点开浮窗、装完一样东西再点刷新，
# 中间的间隔都比这个长。
LOCAL_TTL_SECONDS = 60

# 单条命令、单个请求各自的上限。谁卡住都不该把整张表拖住。
PROBE_TIMEOUT_SECONDS = 5
FETCH_TIMEOUT_SECONDS = 8

CACHE_FILE = Path.home() / ".frago" / "cache" / "environment-latest.json"

GROUP_FRAGO = "frago"
GROUP_REQUIRED = "required"
GROUP_OPTIONAL = "optional"
GROUP_AGENT = "agent"


@dataclass(frozen=True)
class Item:
    """清单里的一样东西。

    ``latest_source`` 是「外面的版本号去哪儿问」，None 表示没有可查的公开版本源
    （WorkBuddy 只有桌面版，官网不发布可机读的版本号），那一格的最新版留空。
    """

    id: str
    name: str
    group: str
    required: bool
    latest_source: str | None


def catalog() -> list[Item]:
    """本平台该出现在表上的那些。bubblewrap 只在 Linux 上是一件事。"""
    items = [
        Item("frago", "frago", GROUP_FRAGO, True, "pypi:frago-cli"),
        Item("git", "git", GROUP_REQUIRED, True, "github_tags:git/git"),
        Item("uv", "uv", GROUP_REQUIRED, True, "github_release:astral-sh/uv"),
        Item("tmux", "tmux", GROUP_OPTIONAL, False, "github_release:tmux/tmux"),
        Item("browser", "Chrome for Testing", GROUP_OPTIONAL, False, "cft"),
        Item("ffmpeg", "ffmpeg", GROUP_OPTIONAL, False, "endoflife:ffmpeg"),
        Item("gh", "GitHub CLI", GROUP_OPTIONAL, False, "github_release:cli/cli"),
    ]
    if platform.system() == "Linux":
        items.append(
            Item(
                "bwrap",
                "bubblewrap",
                GROUP_OPTIONAL,
                False,
                "github_release:containers/bubblewrap",
            )
        )
    items += [
        Item("claude", "Claude Code", GROUP_AGENT, False, "npm:@anthropic-ai/claude-code"),
        Item("codex", "codex", GROUP_AGENT, False, "npm:@openai/codex"),
        Item("opencode", "opencode", GROUP_AGENT, False, "npm:opencode-ai"),
        Item("codebuddy", "WorkBuddy", GROUP_AGENT, False, None),
    ]
    return items


# 每样东西问版本号的那条命令。不统一是它们自己的事：tmux 只认 -V，ffmpeg 把版本号写在
# 一大段编译参数的第一行里。
_VERSION_COMMANDS: dict[str, list[str]] = {
    "git": ["git", "--version"],
    "uv": ["uv", "--version"],
    "tmux": ["tmux", "-V"],
    "ffmpeg": ["ffmpeg", "-version"],
    "gh": ["gh", "--version"],
    "bwrap": ["bwrap", "--version"],
    "claude": ["claude", "--version"],
    "codex": ["codex", "--version"],
    "opencode": ["opencode", "--version"],
    "codebuddy": ["codebuddy", "--version"],
}

# 版本号长什么样：一个数字、一个点，后面跟数字、点或字母（tmux 是 3.6b）。连字符之后
# 的东西一律不要——发行版会往后面接一长串自己的打包号（n4.4.2-0ubuntu0.22.04.1）。
_VERSION_PATTERN = re.compile(r"(\d+\.[0-9A-Za-z.]*[0-9A-Za-z])")

# WorkBuddy 的命令行藏在桌面应用包里，PATH 上通常没有它。路径与装机探测脚本里的那几条
# 保持一致。应用包内的相对位置三个平台同形（``resources/app.asar.unpacked/cli/bin``），
# 差别只在应用装在哪。
#
# macOS 这条是本机实测的。Windows 与 Linux 那几条按桌面应用的常规落点写，没有实机验证过
# ——探不到时页面报「没装」，跟补这几条之前的行为一样，不会更糟。
def _codebuddy_bundled() -> list[Path]:
    rel = Path("app.asar.unpacked") / "cli" / "bin"
    system = platform.system()
    if system == "Darwin":
        base = Path("/Applications/WorkBuddy.app/Contents/Resources")
        return [base / rel / "codebuddy"]
    if system == "Windows":
        roots = [
            Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Programs",
            Path(os.environ.get("PROGRAMFILES") or "C:/Program Files"),
        ]
        return [
            root / "WorkBuddy" / "resources" / rel / name
            for root in roots
            for name in ("codebuddy.cmd", "codebuddy.exe", "codebuddy")
        ]
    return [
        root / "resources" / rel / "codebuddy"
        for root in (
            Path("/opt/WorkBuddy"),
            Path("/usr/lib/workbuddy"),
            Path("/usr/share/workbuddy"),
            Path.home() / ".local" / "share" / "WorkBuddy",
        )
    ]


def _search_path() -> str:
    """找命令用的 PATH：当前进程的，再补上几个用户级目录。

    服务可能是开机自启拉起来的。那种情况下进程拿到的 PATH 是系统给的最小集，用户自己
    装在 ``~/.local/bin`` 和 Homebrew 里的东西全都不在上面——照那份 PATH 探测，这张表
    会把机器上明明装着的东西一律报成没装。
    """
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    extra = [str(Path.home() / ".local" / "bin")]
    if platform.system() == "Darwin":
        extra += ["/opt/homebrew/bin", "/usr/local/bin"]
    elif platform.system() == "Linux":
        extra += ["/usr/local/bin", "/usr/bin"]
    for p in extra:
        if p not in parts:
            parts.append(p)
    return os.pathsep.join(parts)


def _run_version(argv: list[str]) -> str | None:
    """跑一条命令、从它的第一行里取版本号。取不到就当没装。"""
    path = _search_path()
    exe = shutil.which(argv[0], path=path)
    if not exe:
        return None
    try:
        result = subprocess.run(
            [exe, *argv[1:]],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROBE_TIMEOUT_SECONDS,
            env={**os.environ, "PATH": path},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (result.stdout or result.stderr or "").strip()
    if not text:
        return None
    match = _VERSION_PATTERN.search(text.splitlines()[0])
    return match.group(1) if match else None


def _local_frago() -> str | None:
    """frago 自己的版本号。跑的就是它，直接读，不必再起一个子进程。"""
    try:
        from frago import __version__

        return __version__
    except Exception:
        return None


def frago_install_source() -> str:
    """这份 frago 是从哪儿装的：``local`` 本地构建的 wheel、``index`` 索引、``unknown``。

    安装记录里写着来源，这是可机读的事实，不用拿版本号去猜。开发机上 `uv run frago
    server start` 会打一个 wheel 到临时目录再装，那条记录里留的就是一个 file: 地址。
    """
    try:
        from importlib.metadata import distribution

        raw = distribution("frago-cli").read_text("direct_url.json")
        if not raw:
            return "index"
        url = json.loads(raw).get("url", "")
        return "local" if url.startswith("file:") else "index"
    except Exception:
        return "unknown"


def _local_browser() -> str | None:
    """frago 自己那份 Chrome for Testing。路径解析复用浏览器后端的那一套。"""
    try:
        from frago.browser.backends.extension import cft_binary

        binary = cft_binary()
    except Exception:
        return None
    if not binary:
        return None
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = _VERSION_PATTERN.search((result.stdout or "").strip())
    return match.group(1) if match else None


def _local_codebuddy() -> str | None:
    """WorkBuddy：先按普通命令找，再看桌面应用包里那份。"""
    version = _run_version(_VERSION_COMMANDS["codebuddy"])
    if version:
        return version
    for bundled in _codebuddy_bundled():
        if bundled.exists():
            # 版本号读不出来但东西在的时候报「?」——「装了、版本未知」比「没装」诚实。
            return _run_version([str(bundled), "--version"]) or "?"
    return None


def probe_local(item_id: str) -> str | None:
    """一样东西在本机装的是哪一版。None = 没装。"""
    if item_id == "frago":
        return _local_frago()
    if item_id == "browser":
        return _local_browser()
    if item_id == "codebuddy":
        return _local_codebuddy()
    argv = _VERSION_COMMANDS.get(item_id)
    return _run_version(argv) if argv else None


# ── 外面的版本号 ────────────────────────────────────────────────────────────

def _http_json(url: str) -> Any:
    response = requests.get(
        url,
        timeout=FETCH_TIMEOUT_SECONDS,
        headers={"Accept": "application/json", "User-Agent": "frago-environment-check"},
    )
    response.raise_for_status()
    return response.json()


def _version_key(text: str) -> tuple:
    """把版本号排成可比较的样子。字母后缀（tmux 的 3.6b）当作末尾一段。"""
    parts: list[tuple[int, str]] = []
    for chunk in re.split(r"[.\-]", text):
        match = re.match(r"^(\d+)([A-Za-z]*)$", chunk)
        if match:
            parts.append((int(match.group(1)), match.group(2)))
        elif chunk.isdigit():
            parts.append((int(chunk), ""))
    return tuple(parts)


def _fetch_latest(source: str) -> str | None:
    """按来源类型问一次外面的版本号。问不到返回 None，那一格留空。"""
    kind, _, arg = source.partition(":")

    if kind == "pypi":
        data = _http_json(f"https://pypi.org/pypi/{arg}/json")
        return data.get("info", {}).get("version")

    if kind == "github_release":
        data = _http_json(f"https://api.github.com/repos/{arg}/releases/latest")
        tag = data.get("tag_name") or ""
        return tag.lstrip("vn") or None

    if kind == "github_tags":
        # git 不发 release，只打标签。标签接口不保证按版本排序，自己挑最大的那个，
        # 并且把候选版（-rc）排除掉——那不是让人去装的东西。
        data = _http_json(f"https://api.github.com/repos/{arg}/tags?per_page=50")
        names = [
            t.get("name", "").lstrip("vn")
            for t in data
            if isinstance(t, dict) and "rc" not in t.get("name", "").lower()
        ]
        names = [n for n in names if n and n[0].isdigit()]
        return max(names, key=_version_key) if names else None

    if kind == "endoflife":
        # ffmpeg 的 GitHub 仓库不发 release，标签也不按版本排。这个接口按发布周期列出
        # 每一支的最新小版本，取其中最大的那个。
        data = _http_json(f"https://endoflife.date/api/{arg}.json")
        latest = [c.get("latest") for c in data if isinstance(c, dict) and c.get("latest")]
        return max(latest, key=_version_key) if latest else None

    if kind == "npm":
        data = _http_json(f"https://registry.npmjs.org/{arg}/latest")
        return data.get("version")

    if kind == "cft":
        data = _http_json(
            "https://googlechromelabs.github.io/chrome-for-testing/"
            "last-known-good-versions.json"
        )
        return data.get("channels", {}).get("Stable", {}).get("version")

    return None


class EnvironmentService:
    """这张表的取数与缓存。"""

    _instance: Optional["EnvironmentService"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._latest: dict[str, str | None] = {}
        self._latest_at: float = 0.0
        self._local: dict[str, str | None] = {}
        self._local_at: float = 0.0
        self._guard = threading.Lock()
        self._load_cache()

    @classmethod
    def get_instance(cls) -> "EnvironmentService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── 落盘缓存 ────────────────────────────────────────────────────────

    def _load_cache(self) -> None:
        try:
            raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            self._latest = dict(raw.get("items") or {})
            self._latest_at = float(raw.get("fetched_at") or 0)
        except Exception:
            # 没有缓存、缓存坏了，都只是「这一轮得重新问一次」，不是错误。
            self._latest = {}
            self._latest_at = 0.0

    def _save_cache(self) -> None:
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            payload = {"fetched_at": self._latest_at, "items": self._latest}
            tmp = CACHE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(CACHE_FILE)
        except Exception as e:
            logger.debug(f"Environment cache not written: {e}")

    # ── 取数 ────────────────────────────────────────────────────────────

    def invalidate_local(self) -> None:
        """把本机那份版本号作废。

        升级刚做完的那一刻调它：缓存还留着升级前的号，界面照那份画出来，人会以为升级
        没生效。外面那批不用动——升级不改变外面出到哪一版。
        """
        self._local = {}
        self._local_at = 0.0

    def _collect_local(self, items: list[Item], refresh: bool) -> dict[str, str | None]:
        if not refresh and self._local and time.time() - self._local_at < LOCAL_TTL_SECONDS:
            return self._local
        with ThreadPoolExecutor(max_workers=8) as pool:
            versions = list(pool.map(lambda i: probe_local(i.id), items))
        self._local = {
            item.id: version for item, version in zip(items, versions, strict=True)
        }
        self._local_at = time.time()
        return self._local

    def _collect_latest(self, items: list[Item], refresh: bool) -> dict[str, str | None]:
        fresh = self._latest and time.time() - self._latest_at < LATEST_TTL_SECONDS
        if not refresh and fresh:
            return self._latest

        sources = [(item.id, item.latest_source) for item in items if item.latest_source]

        def one(pair: tuple[str, str]) -> tuple[str, str | None]:
            item_id, source = pair
            try:
                return item_id, _fetch_latest(source)
            except Exception as e:
                logger.debug(f"Latest version for {item_id} unavailable: {e}")
                # 问不到就沿用上一次的答案：一次跨境失败不该让整张表突然空掉。
                return item_id, self._latest.get(item_id)

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = dict(pool.map(one, sources))

        self._latest = results
        self._latest_at = time.time()
        self._save_cache()
        return self._latest

    def snapshot(self, refresh: bool = False) -> dict[str, Any]:
        """整张表。``refresh`` 为真时本机与外面都重新问一遍。"""
        items = catalog()
        with self._guard:
            local = self._collect_local(items, refresh)
            latest = self._collect_latest(items, refresh)

        source = frago_install_source()
        rows: list[dict[str, Any]] = []
        for item in items:
            current = local.get(item.id)
            newest = latest.get(item.id)
            # 「有更新」只在两个数字都拿得到、且外面那个确实更大时才成立。frago 从本地
            # wheel 装的那份不参与比较——见模块说明。
            outdated = bool(
                current
                and newest
                and current != "?"
                and _version_key(newest) > _version_key(current)
            )
            if item.id == "frago" and source == "local":
                outdated = False
            rows.append(
                {
                    "id": item.id,
                    "name": item.name,
                    "group": item.group,
                    "required": item.required,
                    "installed": current is not None,
                    "current": current,
                    "latest": newest,
                    "outdated": outdated,
                }
            )

        return {
            "items": rows,
            "os": platform.system().lower(),
            "frago_source": source,
            "checked_at": self._latest_at or None,
        }
