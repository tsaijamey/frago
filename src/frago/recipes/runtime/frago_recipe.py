"""The contract every recipe is built on: frago's module ABI.

A recipe is a module in an operating system, not a script that happens to live
in a directory. That framing decides everything below it:

**The server is the hub.** Every interaction that leaves a recipe — asking
another recipe for data, telling a page what to render, saying how far along
this run is — goes through it. Not because a hub is tidier, but because the
failure this whole contract exists to prevent is *an interaction nobody
recorded*. One ledger existed in four places on one machine because four
callers each worked out their own path to it; the page showed the three-day-old
copy and reported every refresh as a success. Nothing was broken. Nothing was
logged. There was simply no place where "who reads whom" was written down.

**Modules declare their surface.** ``exports`` says what other modules may
call; ``imports`` says whose surface this one depends on. Both sides are
written down, so the recipe being read finally knows it is being read — the
single fact whose absence made every one of these failures silent.

**The page is a front end.** It renders state and calls this module's exported
modes. It never receives a path and never reads a file.

This module is stdlib-only and is not installed. The runner puts it on
``PYTHONPATH``, so a recipe imports it without declaring a dependency — which
matters because most recipes carry a PEP 723 block, and ``uv run`` then builds
an isolated environment holding only what that recipe declared. The moment this
file needs a third-party import, every recipe has to declare it and the one
property that makes it workable is gone.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

#: Stamped into the head of every generated recipe, with the contract version it
#: was born against. Presence alone is not the test — see ``frago.recipes.birth``
#: for why, and for what the platform actually checks.
MARKER = "frago-recipe/1"
CONTRACT = 1

CALLER_ENV = "FRAGO_RECIPE_CALLER"
SLOT_ENV = "FRAGO_RECIPE_SLOT"
DATA_DIR_ENV = "FRAGO_RECIPE_DATA_DIR"
COMMON_DIR_ENV = "FRAGO_RECIPE_COMMON_DIR"
BUS_ENV = "FRAGO_BUS_URL"
EXECUTION_ENV = "FRAGO_EXECUTION_ID"

#: What proves this call came from a recipe the platform started, rather than
#: from the internet. A deployed server sets ``FRAGO_BEHIND_PROXY=1`` and then
#: — correctly — grants nothing on the basis of the peer address: a reverse
#: proxy connects from loopback too, and a proxy that sets none of the headers
#: anybody thought to list would hand every visitor the owner's seat. So the
#: hub is reachable only with the token, and the platform hands it over the
#: same way it hands over the landing spot. Empty on a personal machine, where
#: loopback is trusted and no token exists.
BUS_TOKEN_ENV = "FRAGO_BUS_TOKEN"


class NoLandingSpot(RuntimeError):
    """The platform did not say where this run writes.

    Raised rather than resolved to a default. "The platform did not say, so I
    will use my own path" is the one line that put a ledger in four places: it
    never fails, it just files today's work where yesterday's reader will not
    look.
    """


class BusUnavailable(RuntimeError):
    """The hub could not be reached.

    Raised, never worked around. A fallback here — start the other recipe as a
    child process, read its files directly — would restore exactly the
    unrecorded coupling the hub exists to replace, and would do it at the worst
    possible moment: while something is already wrong.
    """


class RecipeFailed(RuntimeError):
    """A handled failure with something useful to say."""

    def __init__(self, message: str, **detail: Any):
        super().__init__(message)
        self.detail = detail


class NotExported(RecipeFailed):
    """Asking for a mode the other module does not offer, or did not declare."""


# ── messages ───────────────────────────────────────────────────────────────
#
# stdout is a stream of messages, one JSON object per line, and the last one is
# the result. Before this, stdout held a single blob printed at the end: a
# caller learned nothing until the process exited, so a mode that takes half an
# hour was indistinguishable from one that had hung. Recipes worked around it by
# inventing progress files that only the page knowing the filename could read.

MSG_PROGRESS = "progress"
MSG_WARN = "warn"
MSG_RESULT = "result"


def _emit(kind: str, **fields: Any) -> None:
    """Put one message on the wire. stdout, one line, never buffered.

    Line-buffered on purpose: a progress message that arrives after the run
    finishes is not progress.
    """
    payload = {"t": kind, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **fields}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


class Bus:
    """The one door out of a recipe.

    Everything that crosses the module boundary goes through the hub: asking
    another module, publishing render state, reporting progress. One door means
    one place that knows what crossed it, which is the whole point — the graph
    of who depends on whom becomes a thing the system holds rather than a thing
    somebody would have to go and reconstruct.
    """

    def __init__(self, recipe: Recipe):
        self.recipe = recipe

    @property
    def url(self) -> str:
        raw = (os.environ.get(BUS_ENV) or "").strip()
        if not raw:
            raise BusUnavailable(
                f"平台没有交代总线地址（{BUS_ENV} 未设置）。"
                f"跨模块调用、发布页面、上报进度都走总线，"
                f"请通过 frago recipe run 启动，别手工起进程。"
            )
        return raw.rstrip("/")

    def _call(self, path: str, payload: dict, timeout: int = 120) -> dict:
        req = urllib.request.Request(
            f"{self.url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                # Who is calling. The hub records the edge under this name, so
                # the dependency shows up on the other module's side too.
                "X-Frago-Recipe": self.recipe.name or "",
                "X-Frago-Execution": (os.environ.get(EXECUTION_ENV) or "").strip(),
                **({"Authorization": f"Bearer {_token}"}
                   if (_token := (os.environ.get(BUS_TOKEN_ENV) or "").strip()) else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            detail = ""
            with contextlib.suppress(Exception):
                detail = json.loads(err.read().decode("utf-8")).get("detail", "")
            if err.code == 403:
                raise NotExported(str(detail) or "总线拒绝了这次调用") from err
            raise RecipeFailed(f"总线返回 {err.code}：{detail or err.reason}") from err
        except (urllib.error.URLError, OSError, TimeoutError) as err:
            raise BusUnavailable(f"连不上总线（{self.url}）：{err}") from err
        if not isinstance(body, dict):
            raise RecipeFailed(f"总线返回的不是一个对象：{type(body).__name__}")
        return body

    def ask(self, recipe: str, mode: str, params: dict | None = None,
            timeout: int = 120) -> dict:
        """Ask another module for data.

        **The check is not done here.** Refusing locally would be faster and
        would give a friendlier message, and it would also make the single most
        interesting event in this system invisible: a module reaching for
        something it never declared is a dependency somebody is about to
        acquire by accident, and the hub is the only place that can see it. A
        check that runs inside the caller is also a check the caller can simply
        not run — anything not built on this class would bypass it entirely.

        So the request goes out with what this module declared attached, and
        the hub decides. Enforcement and recording happen in the same place,
        which is the only arrangement where "what was refused" is knowable.
        """
        declared = {k: list(v) for k, v in (self.recipe.imports or {}).items()}
        body = self._call(
            "/api/bus/ask",
            {"recipe": recipe, "mode": mode, "params": params or {},
             "caller_imports": declared},
            timeout=timeout,
        )
        if not body.get("ok"):
            err = body.get("error") or {}
            raise RecipeFailed(
                err.get("message") or f"{recipe}/{mode} 没有给出结果",
                **{k: v for k, v in err.items() if k != "message"},
            )
        return body.get("data") or {}

    def publish(self, state: dict, slot: str = "default") -> str:
        body = self._call("/api/bus/publish",
                          {"recipe": self.recipe.name, "slot": slot, "state": state})
        return str(body.get("url") or "")

    def open_page(self, url: str) -> bool:
        with contextlib.suppress(RecipeFailed, BusUnavailable):
            return bool(self._call("/api/bus/open", {"url": url}).get("ok"))
        return False


class Store:
    """This module's own data. The only files it may touch.

    Every method writes through a temporary file and renames, because the
    alternative — open, truncate, write, and be interrupted — leaves a file
    that is neither the old contents nor the new, and the reader of a
    half-written ledger has no way to tell.
    """

    def __init__(self, root: Path):
        self.root = root

    def path(self, *parts: str) -> Path:
        p = self.root.joinpath(*parts)
        if not p.resolve().is_relative_to(self.root.resolve()):
            raise RecipeFailed(f"这个路径跑到了本模块的落点之外：{p}")
        return p

    def read_json(self, *parts: str, default: Any = None) -> Any:
        p = self.path(*parts)
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default
        except (OSError, json.JSONDecodeError) as err:
            raise RecipeFailed(f"{p.name} 读不动：{err}") from err

    def write_json(self, value: Any, *parts: str, indent: int = 2) -> Path:
        p = self.path(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".writing")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=indent, default=str),
                       encoding="utf-8")
        tmp.replace(p)
        return p

    def append_jsonl(self, value: Any, *parts: str) -> Path:
        p = self.path(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return p

    def read_jsonl(self, *parts: str) -> list[Any]:
        p = self.path(*parts)
        if not p.exists():
            return []
        out = []
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                with contextlib.suppress(json.JSONDecodeError):
                    out.append(json.loads(line))
        return out


class Recipe:
    """The base every recipe is built on.

    A subclass declares what it is, what it offers, and what it depends on::

        class EtfFeed(Recipe):
            name = "cn_etf_data_feed"
            modes = ("refresh", "status", "read")
            exports = ("status", "read")          # 别的模块能调这两个
            imports = {}                          # 不依赖别人

            def mode_status(self):
                return {"symbols": len(self.store.read_json("index.json", default=[]))}

    ``main()`` does the rest: reads params, checks what is required, picks the
    mode, and turns whatever comes back into one result message with an exit
    code that agrees with it.
    """

    #: Must match the directory name and ``recipe.md``.
    name: str = ""

    #: This module's own version. Bump it when its exported shapes change.
    version: str = "1.0.0"

    #: Every mode this module answers to. The first is the default.
    modes: tuple[str, ...] = ()

    #: The modes other modules may call — this module's exported surface.
    #: **Exported modes must be read-only**: no network, no recomputation, no
    #: state change, no browser. The hub refuses anything not listed here, so a
    #: caller can never reach into a mode that does work.
    exports: tuple[str, ...] = ()

    #: Whose surface this module depends on, as ``{recipe: (mode, ...)}``.
    #: Declared so the dependency exists on both sides: the module being read
    #: has, until now, had no way of knowing anyone depended on it, which is
    #: why editing its own files broke pages it had never heard of.
    imports: dict[str, tuple[str, ...]] = {}

    #: Other modules whose shared, read-only data this one may read.
    reads_common: tuple[str, ...] = ()

    #: Params without which a mode cannot run, as ``{"mode": ("a", "b")}``.
    #: ``"*"`` applies to every mode.
    requires: dict[str, tuple[str, ...]] = {}

    def __init__(self, params: dict | None = None):
        self.params: dict = params or {}
        #: Things that went wrong without making the answer worthless.
        self.warnings: list[str] = []

    # ── where this run writes ──────────────────────────────────────────────

    @property
    def data_dir(self) -> Path:
        """Where this run writes. Decided by the platform, never by the module.

        A property rather than something resolved in ``__init__`` so that
        importing a recipe module never fails: a checker, a test or a metadata
        probe has to be able to load the file on a machine where no run is in
        progress. Three recipes resolved this at module level and became
        impossible to import at all.
        """
        raw = (os.environ.get(DATA_DIR_ENV) or "").strip()
        if not raw:
            raise NoLandingSpot(
                f"平台没有交代落点（{DATA_DIR_ENV} 未设置）。"
                f"本模块只写平台指定的目录，请通过 frago recipe run 启动。"
            )
        d = Path(raw).expanduser()
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def store(self) -> Store:
        """This module's own data. Reading another module's files is not a
        slower version of asking it — it is a dependency nobody recorded."""
        return Store(self.data_dir)

    @property
    def common_dir(self) -> Path | None:
        """The root under which other modules' shared data may be read.

        Read-only by contract: everyone reads one copy and exactly one module
        updates it. That is a rule about permission, which no directory layout
        can express — which is why it is a contract and not a symlink.
        """
        raw = (os.environ.get(COMMON_DIR_ENV) or "").strip()
        return Path(raw).expanduser() if raw else None

    @property
    def seed_dir(self) -> Path | None:
        """Starting data: copied once, then owned by whoever copied it.

        The opposite of ``common_dir`` in the way that matters — this is meant
        to be copied and then forgotten, that one must never be copied. Two
        directories, so the two behaviours cannot be confused.
        """
        root = self.common_dir
        return None if root is None or not self.name else root / self.name / "share" / "seed"

    @property
    def caller(self) -> str:
        return (os.environ.get(CALLER_ENV) or "owner").strip() or "owner"

    @property
    def slot(self) -> str:
        return (os.environ.get(SLOT_ENV) or "").strip()

    @property
    def is_visitor(self) -> bool:
        return self.caller == "visitor"

    @property
    def bus(self) -> Bus:
        return Bus(self)

    # ── talking to the rest of the system ──────────────────────────────────

    def ask(self, recipe: str, mode: str, params: dict | None = None,
            timeout: int = 120) -> dict:
        """Ask another module for data. The only sanctioned way to get it."""
        return self.bus.ask(recipe, mode, params, timeout=timeout)

    def publish(self, state: dict, slot: str = "default") -> str:
        """Publish what this module's page should render; returns its address.

        **The page is a front end and this module is its back end.** What goes
        through here is render state and nothing else — it must not carry a
        path.

        A path in page state is the front end reaching into the back end's
        filesystem. It looks harmless on the author's machine and fails three
        ways elsewhere: a visitor has no such file; a page that reads files
        needs an endpoint able to read *any* file; and when the module's
        landing spot moves the page keeps reading the old one and reports every
        refresh as a success. Eleven pages were doing exactly that.

        Data comes from the other channel: the page calls this module's
        exported modes through the hub, the same way another module would.
        """
        _refuse_paths(state)
        return self.bus.publish(state, slot=slot)

    def open_page(self, url: str) -> bool:
        return self.bus.open_page(url)

    # ── saying what is happening ───────────────────────────────────────────

    def progress(self, note: str, step: int | None = None, of: int | None = None) -> None:
        """Say how far along this run is, while it is still running."""
        _emit(MSG_PROGRESS, recipe=self.name, note=note, step=step, of=of)

    def warn(self, message: str) -> None:
        """Something went wrong that does not make the answer worthless.

        One unreadable file among twenty-six must not make the other
        twenty-five vanish from the page. Merge this with failure and a module
        loses the ability to be partly broken, which is the state most real
        ones are in.
        """
        self.warnings.append(message)
        _emit(MSG_WARN, recipe=self.name, note=message)

    def log(self, *args: Any) -> None:
        """For a person watching. stderr, because stdout carries messages."""
        print(f"[{self.name or 'recipe'}]", *args, file=sys.stderr, flush=True)

    def fail(self, message: str, **detail: Any) -> RecipeFailed:
        """A failure that makes the answer worthless. ``raise self.fail(...)``.

        Produces ``ok: false`` **and** a non-zero exit code. The two always move
        together: callers overwhelmingly read the exit code alone, so a false
        paired with a zero exit is a failure nobody is told about.
        """
        return RecipeFailed(message, **detail)

    def require(self, *names: str) -> None:
        """Refuse to start without these params, naming every one that is missing.

        All of them at once: a caller told about one, who fixes it and is then
        told about the next, makes the round trip once per missing param.
        """
        missing = [n for n in names if self.params.get(n) in (None, "", [], {})]
        if missing:
            raise RecipeFailed(f"缺少必填参数：{'、'.join(missing)}")

    # ── not running twice at once ──────────────────────────────────────────

    @contextlib.contextmanager
    def lock(self, name: str = "run", stale_after: int = 600):
        """Hold a lock for the length of a block, so two runs cannot overlap.

        Every scheduled module needs this and several had hand-rolled it, each
        with its own idea of when a lock goes stale. Expiry is the part people
        get wrong: without it, a machine that lost power once never runs that
        module again and nothing says why.
        """
        lock_file = self.data_dir / f".{name}.lock"
        if lock_file.exists():
            try:
                age = time.time() - lock_file.stat().st_mtime
            except OSError:
                age = stale_after + 1
            if age < stale_after:
                raise RecipeFailed(
                    f"上一轮还在跑（锁 {age:.0f} 秒前建的，{stale_after} 秒才算过期），本轮跳过"
                )
            self.log(f"锁已过期（{age:.0f} 秒），清掉重拿")
            lock_file.unlink(missing_ok=True)
        try:
            with open(lock_file, "x", encoding="utf-8") as fh:
                fh.write(str(os.getpid()))
        except FileExistsError:
            raise RecipeFailed("另一个进程刚拿到锁，本轮跳过") from None
        try:
            yield lock_file
        finally:
            lock_file.unlink(missing_ok=True)

    # ── running ────────────────────────────────────────────────────────────

    def resolve_mode(self) -> str:
        asked = str(self.params.get("mode") or "").strip()
        if not asked:
            if not self.modes:
                raise RecipeFailed("这个模块没有声明任何 mode")
            return self.modes[0]
        if asked not in self.modes:
            raise RecipeFailed(
                f"未知 mode: {asked}（本模块支持 {' | '.join(self.modes)}）。"
                f"NEVER 让不认识的 mode 落到默认那条路上——一次只读的探问"
                f"就是这样掉进状态机、真的去调了外部接口。"
            )
        return asked

    def dispatch(self) -> dict:
        mode = self.resolve_mode()
        self.require(*self.requires.get("*", ()))
        self.require(*self.requires.get(mode, ()))
        handler = getattr(self, f"mode_{mode}", None)
        if handler is None:
            raise RecipeFailed(f"声明了 mode={mode}，但没有对应的 mode_{mode} 方法")
        data = handler()
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise RecipeFailed(
                f"mode_{mode} 返回的是 {type(data).__name__}，模块的返回值必须是一个对象"
            )
        return data

    @classmethod
    def main(cls, argv: list[str] | None = None) -> None:
        """Entry point. ``MyRecipe.main()`` at the bottom of the file."""
        argv = sys.argv[1:] if argv is None else argv
        me = cls()
        params: dict = {}
        if argv and argv[0].strip().startswith("{"):
            try:
                params = json.loads(argv[0])
            except json.JSONDecodeError as err:
                _result(cls, None, error={"code": "bad-params",
                                          "message": f"参数解析失败：{err}"})
                sys.exit(1)

        me = cls(params)
        # Resolved once, before anything can fail, so the envelope names the
        # mode on the failure path too. Without it a failed run reports
        # ``mode: null`` and whoever is reading the log cannot tell which of a
        # module's five modes died.
        try:
            mode = me.resolve_mode()
        except RecipeFailed as err:
            _result(cls, None, error={"code": "bad-mode", "message": str(err)})
            sys.exit(1)

        started = time.monotonic()
        try:
            data = me.dispatch()
        except (RecipeFailed, NoLandingSpot, BusUnavailable) as err:
            _result(cls, None, mode=mode, warnings=me.warnings, error={
                "code": type(err).__name__, "message": str(err),
                **getattr(err, "detail", {}),
            }, ms=int((time.monotonic() - started) * 1000))
            sys.exit(1)

        _result(cls, data, mode=mode, warnings=me.warnings,
                ms=int((time.monotonic() - started) * 1000))
        sys.exit(0)


def _result(cls: type, data: dict | None, *, warnings: list[str] | None = None,
            error: dict | None = None, ms: int | None = None,
            mode: str | None = None) -> None:
    """The last message on the wire: the envelope every caller can read.

    The envelope is fixed and the payload is not. ``data`` is whatever this
    module means; everything around it — did it work, what went wrong, how long
    it took — has one shape across every module, so a caller can handle any of
    them without knowing which it called.
    """
    _emit(MSG_RESULT, **{
        "recipe": getattr(cls, "name", "") or "",
        "version": getattr(cls, "version", ""),
        "contract": CONTRACT,
        "mode": mode,
        "ok": error is None,
        "data": data if data is not None else {},
        "warnings": warnings or [],
        "error": error,
        "ms": ms,
    })


#: Anything that looks like somewhere on this machine. Deliberately broad: a
#: false positive costs an author one reworded string, a miss costs a page that
#: reads a file right up until the day the file moves.
_LOOKS_LIKE_A_PATH = re.compile(r"^(/|~/|\.{1,2}/|[A-Za-z]:[\\/])")


def _refuse_paths(state: Any, _where: str = "") -> None:
    """Refuse page state carrying a filesystem path, naming exactly where."""
    if isinstance(state, dict):
        for k, v in state.items():
            _refuse_paths(v, f"{_where}.{k}" if _where else str(k))
    elif isinstance(state, list):
        for i, v in enumerate(state):
            _refuse_paths(v, f"{_where}[{i}]")
    elif isinstance(state, str) and _LOOKS_LIKE_A_PATH.match(state.strip()):
        raise RecipeFailed(
            f"页面状态里带了一条路径：{_where} = {state!r}。"
            f"页面是前端、模块是后端，前端不碰后端的文件系统——"
            f"数据走接口（页面调本模块导出的只读 mode），不走路径。"
        )
