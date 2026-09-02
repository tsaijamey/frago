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

**Modules declare their surface.** A mode carries an access level, written on
the method itself — ``@export`` for what other modules may call, ``@action``
for what this module's own page may press, nothing for the modes only the
owner reaches. ``imports`` says whose surface this one depends on. Both sides
are written down, so the recipe being read finally knows it is being read —
the single fact whose absence made every one of these failures silent.

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


# ── access levels ──────────────────────────────────────────────────────────
#
# How far out a mode reaches, written on the method that implements it.
#
# This used to be two lists of names in `recipe.md` — `exports` and
# `page_actions` — that had to agree with a third list of names in the class,
# and the three agreed only as long as somebody kept them agreeing. Two of the
# three mismatches were invisible on the machine where the recipe was written:
# a `page_actions` entry naming a mode that does not exist raised nothing at
# all and showed up as a 403 on the server, and the owner's own path never
# consults either list.
#
# The names being in a different file from the thing they name was the whole
# problem, so they moved onto it. One value per mode, not two flags: "exported
# and also pressable from the page" was never a coherent state — an exported
# mode is read-only by contract and the page reads it through
# `POST /app/<name>/api/<mode>` without needing a button — and the rule that
# used to forbid that combination is now something the shape cannot express.
#
# **Not a C++-style ladder, and it must not be designed as one.** public /
# protected / private is a total order, each level containing the next. These
# do not nest: a mode may be pressable from a page and still not callable by
# another module, because the bus additionally promises read-only and the page
# route explicitly does not. What travels is not "how far", it is "by whom" —
# closer to Rust's `pub(crate)` than to anything in C++.

#: Read-only contract. Other modules may call it over the bus, and this
#: module's own page may read it. MUST be read-only: no network, no
#: recomputation, no state change, no browser.
EXPORT = "export"

#: This module's page may trigger it, and it is allowed to do work. Not
#: callable by other modules — the bus promises read-only, and this does not.
ACTION = "action"

#: The default, and the default is right. A mode nobody marked runs only for
#: the owner: a page is the least trusted thing in the system, because whoever
#: can open it can press it, while the run happens on the owner's machine with
#: the owner's credentials.
OWNER_ONLY = "owner"

#: Where the mark is kept on the function object. The platform reads the
#: *decorator's name* out of the source without importing anything (see
#: ``frago.recipes.contract``); this attribute is what makes the same answer
#: available at run time to the class itself.
ACCESS_ATTR = "__frago_access__"


def export(method):
    """This mode is a read-only contract: the bus and the page may both read it.

    MUST be read-only — no network, no recomputation, no state change, no
    browser. Another module is entitled to ask every five minutes, and a
    read-only probe that fell through into a state machine once went and called
    a live API.
    """
    setattr(method, ACCESS_ATTR, EXPORT)
    return method


def action(method):
    """This module's page may trigger this mode, and it may do work.

    Everything about this is a permission, not a formality: whoever can open
    the page can press it, and pressing it runs this code on the owner's
    machine with the owner's credentials. NEVER mark a mode that spends money
    or acts outwards as the owner.
    """
    setattr(method, ACCESS_ATTR, ACTION)
    return method


class ContractBroken(TypeError):
    """The class does not describe a module this platform can place.

    Raised while the class body is being built, so it fires on import — before
    a run, before a page, before anything reads a surface that is not there.
    """


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

    def frago(self, argv: list[str], timeout: int = 120) -> dict:
        """Have the platform run one of its own commands and hand back the result.

        The words after ``frago``, as a list — the same list this module would
        have passed to a subprocess, which is exactly what it used to do. What
        changed is who runs it: inside this process the command inherits this
        run's confined view of the filesystem and answers out of it, cheerfully
        and with exit 0, having seen none of the platform's own books.
        """
        body = self._call("/api/bus/frago",
                          {"argv": [str(word) for word in argv], "timeout": timeout},
                          timeout=timeout + 10)
        return {"code": int(body.get("code") or 0),
                "stdout": str(body.get("stdout") or ""),
                "stderr": str(body.get("stderr") or "")}

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
            imports = {}                          # 不依赖别人

            @export                               # 别的模块能调，页面也读得到
            def mode_status(self):
                return {"symbols": len(self.store.read_json("index.json", default=[]))}

            def mode_refresh(self):               # 不标：只有主人能跑
                ...

    There is no list of modes to keep in step with the methods: ``modes``,
    ``exports`` and ``page_actions`` are all derived from the ``mode_*``
    methods and their access marks, in the order the methods are written.
    Declaring any of the three by hand is refused rather than quietly
    overwritten — see ``__init_subclass__``.

    ``main()`` does the rest: reads params, checks what is required, picks the
    mode, and turns whatever comes back into one result message with an exit
    code that agrees with it.
    """

    #: Must match the directory name and ``recipe.md``.
    name: str = ""

    #: This module's own version. Bump it when its exported shapes change.
    version: str = "1.0.0"

    #: Every mode this module answers to, in the order the methods appear.
    #: Derived — NEVER write this in a subclass.
    modes: tuple[str, ...] = ()

    #: The modes other modules may call, i.e. every ``@export``. Derived.
    exports: tuple[str, ...] = ()

    #: The modes this module's page may trigger, i.e. every ``@action``.
    #: Derived.
    page_actions: tuple[str, ...] = ()

    #: Which mode a caller gets when they name none. Empty means the first
    #: ``mode_*`` method.
    #:
    #: Written down rather than derived, unlike everything above it, because
    #: this one is a decision and the others are facts. Deriving it would make
    #: "which mode runs by default" a consequence of where somebody happened to
    #: type a method — moving two methods past each other, or renaming one,
    #: would silently change what a bare run does. Eleven installed recipes had
    #: a default that was not their first method when this was introduced.
    default_mode: str = ""

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

    #: Names a subclass may no longer bind. Each was a list of mode names kept
    #: in a different place from the modes it named, which is the whole reason
    #: the marks moved onto the methods.
    _DERIVED = ("modes", "exports", "page_actions")

    def __init_subclass__(cls, **kwargs):
        """Work out this module's surface from its methods, once, at import.

        Refuses rather than overrides when a subclass writes one of the derived
        names itself. Overriding would be the quieter behaviour and the wrong
        one: a class carrying ``exports = ("status",)`` says something specific,
        and silently computing a different answer would leave the file and the
        system disagreeing with nothing to show for it — which is the exact
        failure mode this whole change is here to remove.
        """
        super().__init_subclass__(**kwargs)

        clashing = [one for one in cls._DERIVED if one in cls.__dict__]
        if clashing:
            raise ContractBroken(
                f"{cls.__name__} 自己写了 {'、'.join(clashing)}。"
                f"这几项现在由平台从 mode_* 方法上的访问级别推导，不再手写——"
                f"手写的那份和方法一旦对不上，页面和总线各按各的答案走，而且不报错。"
                f"改法：在方法上标 @export（只读契约，别的模块和页面都读得到）"
                f"或 @action（页面能触发，允许干活），不标就是只有主人能跑。"
                f"默认 mode 用 default_mode = \"<名字>\" 指定。"
            )

        modes: list[str] = []
        exports: list[str] = []
        actions: list[str] = []
        # Reversed MRO so a base's modes come before the ones a subclass adds,
        # and a subclass overriding a mode keeps the position it inherited
        # rather than jumping to the end and becoming the default.
        for base in reversed(cls.__mro__):
            for attr, value in vars(base).items():
                if not attr.startswith("mode_") or not callable(value):
                    continue
                mode = attr[len("mode_"):]
                if mode not in modes:
                    modes.append(mode)
                level = getattr(value, ACCESS_ATTR, OWNER_ONLY)
                for level_name, bucket in ((EXPORT, exports), (ACTION, actions)):
                    if level == level_name and mode not in bucket:
                        bucket.append(mode)

        cls.modes = tuple(modes)
        cls.exports = tuple(exports)
        cls.page_actions = tuple(actions)

        if cls.default_mode and cls.default_mode not in modes:
            raise ContractBroken(
                f"{cls.__name__} 把默认 mode 定成 {cls.default_mode!r}，"
                f"但它没有 mode_{cls.default_mode} 方法。"
                f"本模块有的是：{'、'.join(modes) or '（一个都没有）'}"
            )

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

    def ask_frago(self, argv: list[str], timeout: int = 120) -> dict:
        """Run a frago command through the platform. Returns code/stdout/stderr.

        Write the words you would type::

            out = self.ask_frago(["user", "list", "--format", "json"])
            if out["code"] == 0:
                roster = json.loads(out["stdout"])

        **Use this instead of starting frago yourself.** A subprocess started
        here runs inside this run's view of the filesystem, where the platform's
        own books do not exist. The commands that read them do not fail when
        they cannot see them — they answer "nothing", exit 0, and whatever was
        going to be shown gets shown as empty. Through this door the command
        runs where those books actually are.

        No shell is involved and no line is assembled, so an argument may hold
        quotes, spaces or an apostrophe without anything needing to be escaped.
        """
        return self.bus.frago(argv, timeout=timeout)

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
                raise RecipeFailed("这个模块一个 mode_* 方法都没有")
            return self.default_mode or self.modes[0]
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
        """Entry point. ``MyRecipe.main()`` at the bottom of the file.

        Written bare, without ``if __name__ == "__main__"``, because importing
        a recipe **is** running it: the way to use another module is the hub,
        and a guard there would leave a quiet side door where somebody imports
        a recipe to call one of its functions directly.

        Which is right until the recipe starts subprocesses of its own. Python
        re-imports the main script in every child it spawns — that is what the
        guard normally stops. Without one, a recipe that scans the market
        across eight workers has each worker begin the whole scan again on
        startup; eight copies then trample the same progress file and results,
        and the run dies with a process pool error that says nothing about any
        of this. Seen on 2026-08-26: the stock phase counted to 2100, dropped
        back to 0, climbed again, and collapsed.

        So the two cases are told apart rather than one being sacrificed. A
        child process re-importing its parent leaves a mark: the multiprocessing
        machinery names the process something other than ``MainProcess``.
        Anyone else importing this file leaves no such mark, and still runs it.
        """
        import multiprocessing

        if multiprocessing.current_process().name != "MainProcess":
            # A worker this recipe started, loading its parent. It is here to
            # run one task, not to start the whole run over.
            return

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
