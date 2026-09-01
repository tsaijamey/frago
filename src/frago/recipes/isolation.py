"""The view of the filesystem a recipe gets while it runs.

Until this module existed, a recipe was a bare process holding the machine: same
uid, same filesystem, no sandbox. Everything else in this package — the landing
spot, the declared imports, the shared-data grants — described what a recipe
*should* touch, and a recipe that wrote a path down touched whatever it liked.
Two consequences, and the second is the expensive one:

**A declaration nobody enforces is not a boundary.** ``reads_common`` bought a
directory the platform staged; hard-coding ``~/.frago/recipe-data/<other>``
bought the same files with no declaration at all. So the declaration was a
courtesy paid by well-behaved recipes.

**"Read-only" was a sentence, not a fact.** Shared data is owned by the unix
account that runs the recipes, so every consumer of a shared ledger could
overwrite it. One recipe corrupting it corrupts it for every page that reads it,
with nothing to compare against — there is exactly one copy, which is the whole
point of sharing it.

This module makes both facts. A run gets:

* its own landing spot — writable,
* the subtrees other modules **declared** they share — readable, never writable,
* the machinery it takes to execute at all — readable,
* nothing else.

**Enforced by the kernel, not by us.** Two backends, one per platform frago
runs recipes on: ``sandbox-exec`` on macOS and ``bwrap`` (bubblewrap) on Linux.
Both wrap the command that was going to be run anyway, so isolation is not a new
door into starting a recipe — it is a property of the only door there is,
``frago recipe run``. A machine with neither backend refuses to start recipes
rather than starting them unprotected: an isolation that silently is not there
is the exact shape of the "read-only by contract" it replaces. The operator can
say otherwise out loud (``recipe.isolation: "off"`` in ``~/.frago/config.json``),
which is a decision with a name and a place, unlike a silent fallback.

**Windows warns and runs.** Windows has confinement mechanisms and none of them
fits: the cheap one blocks writes but barely blocks reads, the precise one works
by rewriting the permissions on the real directories (a side effect outliving
the run), and the thorough one is a lightweight virtual machine that takes
seconds to start for a recipe that often takes half of one. It is also the
platform where the boundary buys least — a Windows install is one person on
their own laptop, where the account whose data a recipe could reach is that same
person's. So a refusal there costs a working frago and protects nobody. The
warning is on every run, because the day such a machine grows a second person is
the day somebody needs to know this was never confined.

**What this does not do.** It bounds *paths*, not authority. A recipe still
holds the bus token it was handed and can therefore ask the hub for anything the
hub will answer; a recipe allowed the platform's own CLI (see
``uses_frago_cli``) can drive frago's commands. Network is open — recipes fetch
market data. Those are separate boundaries with separate answers, and pretending
this module covers them would be the same mistake in a new place.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: How the owner turns this off, and where. Read from ``~/.frago/config.json``
#: under ``recipe.isolation``. Two values only: the default, and a refusal to
#: use it that somebody had to type.
ENFORCE = "enforce"
OFF = "off"


class NoBackend(RuntimeError):
    """This machine has no way to confine a recipe, and was asked to run one.

    Raised rather than resolved into an unconfined run. The tempting default —
    "no sandbox available, carry on" — reproduces the failure this module
    exists to end: a boundary that holds on the machine it was tested on and is
    absent everywhere else, with nothing anywhere saying so.
    """


@dataclass(frozen=True)
class View:
    """Everything one run may reach, and how far.

    Three lists rather than a policy string because the two backends express the
    same three facts in unrelated syntaxes, and the interesting question — "what
    is this run allowed to see" — has to be answerable, printable and testable
    without either of them.

    ``readable`` and ``writable`` are real paths, resolved before they get here:
    the shared subtrees arrive as symlinks staged for this consumer, and a
    kernel that resolves the link before checking would otherwise be handed a
    rule about a path nothing ever opens.
    """

    #: Where this run may write. Its landing spot, its own machine-level tree,
    #: and the scratch space the interpreter needs.
    writable: tuple[Path, ...] = ()

    #: What it may read and must not change: the machinery, its own code, and
    #: every subtree another module declared it shares.
    readable: tuple[Path, ...] = ()

    #: The subtrees that belong to *other* modules. A subset of ``readable``,
    #: kept apart because these are the ones whose read-onlyness is the point
    #: rather than a side effect: every backend below turns them into an
    #: explicit refusal to write, placed after every allow rule, so that no
    #: broad rule about machinery can accidentally hand one back. "Read-only" is
    #: the sentence this whole module exists to turn into a fact, and a fact
    #: that depends on rule ordering is a sentence again.
    shared: tuple[Path, ...] = ()

    #: Why each entry is here, keyed by path. Carried for the sake of the person
    #: reading a refusal — "this run could not see X" is only actionable next to
    #: "and here is what it could see, and who asked for it".
    because: dict[str, str] = field(default_factory=dict)

    def sees(self, path: Path) -> bool:
        """Whether this view reaches ``path`` at all."""
        target = Path(path)
        return any(
            target == root or target.is_relative_to(root)
            for root in (*self.writable, *self.readable)
        )

    def may_write(self, path: Path) -> bool:
        target = Path(path)
        return any(
            target == root or target.is_relative_to(root) for root in self.writable
        )


# ── what a run is allowed to see ───────────────────────────────────────────


def _existing(*candidates: str | Path | None) -> list[Path]:
    """The ones that are actually on this machine.

    Both backends refuse a profile naming a path that does not exist (bwrap
    fails the bind outright; a stale SBPL subpath is merely dead weight), and
    the lists below deliberately name paths that exist on some machines and not
    others — /opt/homebrew, /lib64, the uv cache before uv has ever run.

    **Every entry is kept twice when the name and the place differ**, because
    the kernel resolves symlinks before it consults any rule and the lists below
    are written in the spelling a human uses. On macOS that difference is not an
    edge case, it is ``$TMPDIR``: the environment hands out
    ``/var/folders/…/T/`` and the kernel checks ``/private/var/folders/…/T``, so
    a profile granting the first grants nothing at all. The symptom is a
    scratch directory that every process can see and none can write — uv fails
    to write its lock, and a browser started from the recipe dies creating its
    own temp file, both without a single line in any log of ours. ``/tmp`` and
    ``/var/tmp`` were already listed in both spellings by hand below, which is
    the same fix applied one path at a time; doing it here covers the one that
    is read from the environment and cannot be listed by hand.
    """
    found: list[Path] = []
    for one in candidates:
        if not one:
            continue
        path = Path(one).expanduser()
        try:
            if not path.exists():
                continue
            for spelling in (path, path.resolve()):
                if spelling not in found:
                    found.append(spelling)
        except OSError:
            continue
    return found


def _system_readable() -> list[Path]:
    """The parts of the operating system a process needs to be a process.

    Read-only, all of it. A recipe that writes into /usr is not a recipe with a
    bug, it is a recipe changing the machine for everything else that runs on
    it.
    """
    if platform.system() == "Darwin":
        return _existing(
            "/usr", "/bin", "/sbin", "/System", "/Library", "/opt",
            "/private/etc", "/private/var/db", "/private/var/select",
            "/Applications",
        )
    return _existing(
        "/usr", "/bin", "/sbin", "/lib", "/lib64", "/lib32", "/etc", "/opt",
        "/proc", "/sys", "/run/systemd/resolve",
    )


def _interpreter_readable() -> list[Path]:
    """Whatever it takes to start the interpreter this recipe declared.

    Most recipes carry a PEP 723 block and are started with ``uv run``, so uv's
    own machinery is as load-bearing as the python binary: its cache holds the
    isolated environment it builds, and its python directory holds the
    interpreter it manages. A run that cannot read them fails at "failed to
    discover managed Python installations", which reads like a broken machine
    rather than a policy decision.
    """
    home = Path.home()
    uv_cache = os.environ.get("UV_CACHE_DIR") or (home / ".cache" / "uv")
    return _existing(
        uv_cache,
        home / ".local" / "share" / "uv",
        home / ".local" / "bin",
        shutil.which("uv"),
        # Three answers to "which python", because there are three: the one uv
        # manages, the one a virtualenv points at, and the virtualenv itself.
        # The last is the one that is easy to forget and fails hardest — a venv
        # whose `pyvenv.cfg` cannot be read kills the interpreter during
        # startup, before any code of ours runs, with "Failed to import the site
        # module".
        Path(sys.executable).resolve().parent.parent,
        sys.prefix,
        sys.base_prefix,
        home / ".pyenv",
    )


def _interpreter_writable() -> list[Path]:
    """The scratch space that same interpreter cannot run without.

    uv writes the environment it builds; python writes bytecode and temporary
    files. Nothing anybody's data lives in, and separated from the read-only
    list so the distinction stays visible rather than being folded into one
    permissive blob.
    """
    home = Path.home()
    uv_cache = os.environ.get("UV_CACHE_DIR") or (home / ".cache" / "uv")
    return _existing(
        uv_cache,
        home / ".local" / "share" / "uv",
        os.environ.get("TMPDIR"),
        "/tmp", "/private/tmp", "/var/tmp", "/private/var/tmp",
        "/dev",
    )


def _platform_cli_paths() -> tuple[list[Path], list[Path]]:
    """What frago's own commands need, for a recipe that declared it calls them.

    Returned only for a recipe carrying ``uses_frago_cli`` in its metadata,
    because a recipe shelling out to ``frago browser`` is a dependency like any
    other and the platform's answer to an undeclared dependency is the same
    everywhere in this package: it does not exist.

    **Named subtrees, never the frago home.** ``~/.frago`` holds every account's
    data, every recipe's data, this machine's identity and the credentials of
    every recipe on it. Handing that over to run one browser command would give
    away more than having no isolation costs, because it would do it while
    reporting that a boundary was in place.

    **``profiles`` is the one entry here that is not just machinery, and it is
    said out loud rather than left to be discovered.** A browser profile holds
    the cookies of every site the owner has logged into, so a recipe that writes
    ``uses_frago_cli: true`` can read those. It is here because there is no
    smaller grant that lets ``frago browser`` work at all — the browser's
    user-data-dir is where a browser lives — and because the honest comparison
    is not against a tighter boundary but against the recipe shelling out to a
    browser that dies on startup. The tighter boundary exists and is a separate
    piece of work: a declaration of its own (``uses_browser``) that hands over
    ``profiles`` and nothing else, so that the nine recipes here which only ever
    call ``frago recipe publish`` stop being handed a cookie jar.
    """
    home = Path.home() / ".frago"
    readable = _existing(
        home / "config.json",
        home / "books",
        home / "bin",
        home / "community-recipes",
        home / "certs",
    )
    writable = _existing(
        home / "sessions",
        home / "executions",
        home / "app-state",
        home / "cache",
        home / "chrome",
        home / "logs",
        home / "traces",
        home / "projects",
        # The browser's own profile directories, one per brand and port. Listed
        # next to ``chrome`` because the two are halves of the same thing and
        # only one of them was here: ``chrome`` is the ledger ``frago browser``
        # keeps *about* tabs, ``profiles`` is the user-data-dir the browser it
        # starts actually lives in. Without it the command still returns 0 —
        # it starts the process and sees a port answer — and the browser dies
        # about a second later, unable to create ``SingletonLock`` in a profile
        # directory the view does not contain. Chromium reads that failure as
        # "this profile is already in use" and exits, so the visible symptom is
        # a browser that launched and vanished with nothing in any log of ours.
        # Cost this once: every ``frago desktop up`` on 2026-09-01 failed 90
        # seconds in, and the first three hypotheses were about the port.
        home / "profiles",
    )
    return readable, writable


def view_for(
    recipe_name: str,
    *,
    landing_spot: Path | None,
    recipe_dir: Path | None,
    shared: dict[str, Path] | None = None,
    uses_frago_cli: bool = False,
) -> View:
    """The view one run gets, assembled from what this run actually is.

    ``shared`` is ``{producer: subtree}`` — already resolved to the real
    directories the producers declared, by ``frago.recipes.context``. This
    function does not decide who may read whom; it renders a decision already
    made into something a kernel can hold to. Keeping the two apart is what
    lets ``frago recipe validate`` answer "what will this run be able to see"
    without starting anything.
    """
    from frago.recipes.app_state import RECIPE_DATA

    because: dict[str, str] = {}

    def note(paths: list[Path], why: str) -> list[Path]:
        for one in paths:
            because.setdefault(str(one), why)
        return paths

    writable: list[Path] = []
    readable: list[Path] = []

    # The two directories this run owns are listed whether or not they exist
    # yet. Both backends accept a path that is not there — bwrap skips the bind,
    # sandbox-exec matches a prefix rather than an inode — and the alternative
    # is worse than untidy: a recipe's very first run is exactly the run whose
    # landing spot does not exist yet, and it would be the one run confined out
    # of its own directory.
    if landing_spot is not None:
        writable += note([Path(landing_spot)], "本次运行的落点")
    # The recipe's own machine-level tree: where a producer keeps the data it
    # shares, and where this consumer's staged view of other producers is built.
    # Its own, so writable — the read-only half is the *targets* those staged
    # links point at, which are added below and never appear here.
    own_tree = Path.home() / ".frago" / RECIPE_DATA / recipe_name
    writable += note([own_tree], "本模块自己的机器级目录")

    writable += note(_interpreter_writable(), "解释器要用的暂存")
    readable += note(_system_readable(), "操作系统")
    readable += note(_interpreter_readable(), "解释器")
    # The base class every recipe is built on. The runner puts this directory on
    # PYTHONPATH precisely because a recipe cannot import frago — so a view that
    # leaves it out kills every recipe on the contract at ``import
    # frago_recipe``, which reads like a broken install rather than a policy.
    readable += note([Path(__file__).parent / "runtime"], "配方基类（平台放在 PYTHONPATH 上的）")

    if recipe_dir is not None:
        # The recipe's own directory, and the recipes root around it. The root
        # rather than the directory alone because a recipe's helper modules and
        # the algorithm libraries it imports sit beside it; source is code every
        # account on this machine already has, and cutting the root out would
        # make `import` of a sibling library a runtime failure rather than the
        # design question it actually is.
        readable += note(_existing(recipe_dir), "本模块自己的代码")
        readable += note(_existing(Path.home() / ".frago" / "recipes"), "配方源码")

    shared_roots: list[Path] = []
    for producer, subtree in (shared or {}).items():
        shared_roots += note([Path(subtree)], f"{producer} 声明共享的子树（只读）")
    readable += shared_roots

    if uses_frago_cli:
        cli_readable, cli_writable = _platform_cli_paths()
        readable += note(cli_readable, "frago 命令自己的东西（配方声明了 uses_frago_cli）")
        writable += note(cli_writable, "frago 命令自己的工作目录（配方声明了 uses_frago_cli）")

    # A path already inside a writable root is writable: the narrower statement
    # would be the read-only one, and a run that cannot write its own landing
    # spot because some machinery rule also named it fails in a way nobody could
    # read. Nesting counts, not just equality — the interpreter frago itself
    # runs under lives inside uv's directory, which uv writes.
    readable = [
        one for one in readable
        if not any(one == root or one.is_relative_to(root) for root in writable)
    ]

    return View(
        writable=tuple(dict.fromkeys(writable)),
        readable=tuple(dict.fromkeys(readable)),
        shared=tuple(dict.fromkeys(shared_roots)),
        because=because,
    )


# ── holding a kernel to it ─────────────────────────────────────────────────


class Backend:
    """One platform's way of starting a process that cannot see everything."""

    name = ""

    def available(self) -> bool:
        raise NotImplementedError

    def wrap(self, cmd: list[str], view: View, *, cwd: Path | None) -> list[str]:
        raise NotImplementedError


def _sbpl_quote(path: Path) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


class SandboxExec(Backend):
    """macOS. ``sandbox-exec`` with a profile written for this one run.

    Deprecated by Apple for years and still the only userland confinement macOS
    offers without asking for privileges, which makes "deprecated" a smaller
    problem than "absent". The profile is generated per run and passed on the
    command line rather than written to a file: a file would be one more thing
    to clean up, and one more thing a recipe could read.

    Two details that are not obvious and both cost an afternoon to find:
    ``file-read-metadata`` has to be open everywhere or path resolution fails
    before any rule about the target applies, and the root directory itself
    needs ``file-read*`` — without it a deny-default profile aborts every
    process, including ``/bin/echo``, with no diagnostic at all.
    """

    name = "sandbox-exec"

    def available(self) -> bool:
        return platform.system() == "Darwin" and bool(shutil.which("sandbox-exec"))

    def profile(self, view: View, *, cwd: Path | None) -> str:
        lines = [
            "(version 1)",
            "(deny default)",
            "(allow process*)",
            "(allow sysctl-read)",
            "(allow mach*)",
            "(allow ipc*)",
            "(allow signal (target self))",
            # Recipes fetch market data and call the hub. Confining the network
            # is a different boundary with a different answer; claiming it here
            # would break every feed on the machine and protect nothing that the
            # bus token does not already hand over.
            "(allow network*)",
            # Without this, resolving any path fails before the rule about its
            # target is ever consulted. It leaks the existence of names, not
            # their contents.
            "(allow file-read-metadata)",
            '(allow file-read* (literal "/"))',
        ]
        if view.readable:
            lines.append(
                "(allow file-read* "
                + " ".join(f"(subpath {_sbpl_quote(p)})" for p in view.readable)
                + ")"
            )
        writable = list(view.writable)
        if cwd is not None and cwd not in writable:
            writable.append(cwd)
        if writable:
            lines.append(
                "(allow file-read* file-write* "
                + " ".join(f"(subpath {_sbpl_quote(p)})" for p in writable)
                + ")"
            )
        # Last, because the last matching rule is the one that applies. Another
        # module's data is read-only no matter which broad rule above happens to
        # cover the same path.
        if view.shared:
            lines.append(
                "(deny file-write* "
                + " ".join(f"(subpath {_sbpl_quote(p)})" for p in view.shared)
                + ")"
            )
        return "\n".join(lines) + "\n"

    def wrap(self, cmd: list[str], view: View, *, cwd: Path | None) -> list[str]:
        return ["sandbox-exec", "-p", self.profile(view, cwd=cwd), *cmd]


class Bubblewrap(Backend):
    """Linux. ``bwrap`` with one bind mount per thing this run may see.

    Mounts rather than rules, which makes the "everything else does not exist"
    half literal: the new root holds only what was bound into it, so a path
    nobody granted is not refused, it is absent. That difference matters for
    recipes — code that handles ``FileNotFoundError`` and code that handles
    ``PermissionError`` are rarely the same code, and "absent" is the honest
    description of a directory this run was never given.

    The network namespace is deliberately shared, for the reason
    ``SandboxExec.profile`` gives.
    """

    name = "bwrap"

    def available(self) -> bool:
        return platform.system() == "Linux" and bool(shutil.which("bwrap"))

    #: Places bwrap furnishes itself, and which must not then be bound over with
    #: the host's copy.
    #:
    #: **``/dev`` is the one that bites, and it was not the obvious suspect.**
    #: Binding the host's ``/dev`` on top of the small one bwrap builds leaves
    #: the tool that starts the interpreter unable to work out which C library
    #: this machine has, and it gives up before running anything: every recipe
    #: on the demo server died before its first line on 2026-08-31, minutes
    #: after that machine got its isolation backend installed.
    #:
    #: The measurement is worth recording, because the plausible story was
    #: wrong: bind the host's ``/proc`` alone and everything works; bind the
    #: host's ``/dev`` alone and everything breaks. ``/proc`` is on this list
    #: anyway — a run in its own pid namespace has no business reading the
    #: host's process table — but it is here for isolation, not for this bug.
    FURNISHED = frozenset({Path("/proc"), Path("/dev")})

    def wrap(self, cmd: list[str], view: View, *, cwd: Path | None) -> list[str]:
        argv = ["bwrap", "--die-with-parent", "--unshare-pid", "--proc", "/proc",
                "--dev", "/dev", "--tmpfs", "/tmp"]
        for path in view.readable:
            if path in view.shared or path in self.FURNISHED:
                continue
            argv += ["--ro-bind-try", str(path), str(path)]
        writable = list(view.writable)
        if cwd is not None and cwd not in writable:
            writable.append(cwd)
        for path in writable:
            if path in self.FURNISHED:
                continue
            argv += ["--bind-try", str(path), str(path)]
        # Mounted last, so that a writable bind covering the same place is
        # covered *by* this one rather than the other way round. Same reason the
        # macOS profile puts its refusal at the end.
        for path in view.shared:
            argv += ["--ro-bind-try", str(path), str(path)]
        if cwd is not None:
            argv += ["--chdir", str(cwd)]
        return [*argv, "--", *cmd]


#: Both backends, in the order they are tried. One per platform, so the order
#: settles nothing today; it is a list rather than a branch because the next
#: backend (a Landlock helper, a jail) should be an entry here rather than
#: another branch in a function.
BACKENDS: tuple[Backend, ...] = (SandboxExec(), Bubblewrap())


def backend() -> Backend | None:
    """The one this machine can actually use, or None."""
    for one in BACKENDS:
        if one.available():
            return one
    return None


#: Where the owner's answer lives. Read straight out of the file rather than
#: through ``frago.init.config_manager``, which parses config.json into a typed
#: record and drops what it does not know about — this key among them.
CONFIG_PATH = Path.home() / ".frago" / "config.json"


def configured() -> str:
    """What the owner asked for: ``enforce`` (the default) or ``off``.

    An unreadable or absent config reads as ``enforce``. That is the closed
    direction, and it is the one that matters here: the failure of the open
    direction is a machine that quietly stopped confining anything, which looks
    exactly like a machine that is confining everything.
    """
    override = (os.environ.get("FRAGO_RECIPE_ISOLATION") or "").strip().lower()
    if override in (ENFORCE, OFF):
        return override
    try:
        import json

        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        value = str((data.get("recipe") or {}).get("isolation", ENFORCE)).strip()
    except (OSError, ValueError, AttributeError):
        return ENFORCE
    return OFF if value.lower() == OFF else ENFORCE


def why_unavailable() -> str:
    """What to tell somebody whose machine cannot confine a recipe."""
    system = platform.system()
    if system == "Linux":
        # The package is called bubblewrap on every distribution that carries
        # it, and the command to install it is not. Naming one package manager
        # would be right on the machine this was written for and wrong on the
        # next one — where the reader would be told to run a command that does
        # not exist, and have to work out for themselves that the package name
        # was the part that transferred.
        return (
            "这台机器上没有 bwrap（bubblewrap），配方就没有边界可言——"
            "它能读任何一个账号的数据、能读 ~/.ssh。"
            "装 bubblewrap 这个包：Debian/Ubuntu 用 apt install bubblewrap，"
            "Fedora/RHEL 用 dnf install bubblewrap，Arch 用 pacman -S bubblewrap，"
            "Alpine 用 apk add bubblewrap。"
        )
    if system == "Darwin":
        return (
            "这台机器上找不到 sandbox-exec，macOS 上没有别的用户态办法把配方关起来。"
        )
    if system == "Windows":
        return (
            "Windows 上没有合用的隔离办法：低完整性级别只挡写不挡读；"
            "AppContainer 要逐个目录改真实权限，副作用比这次运行活得久；"
            "Windows 沙盒是台轻量虚拟机，起一次要几秒，而配方常常跑半秒。"
            "本机个人使用照常跑，但它读得到这台机器上的任何东西。"
        )
    return (
        f"{system} 上还没有可用的隔离后端。配方在这里跑就是一个拿着整台机器的裸进程。"
    )


# ── saying so before it happens ────────────────────────────────────────────
#
# A runtime boundary on its own produces a recipe that installs, schedules,
# and dies every five minutes with a page still showing three-day-old numbers.
# The two gates have to say the same thing: whatever the kernel will refuse,
# `frago recipe validate` has to refuse first, and it has to do it by asking the
# same View rather than by keeping a second list of what is allowed.


@dataclass(frozen=True)
class Blocked:
    """One thing this recipe does that its view will not permit."""

    file: Path
    line: int
    excerpt: str
    why: str
    fix: str

    def render(self, root: Path | None = None) -> str:
        where = (
            self.file.relative_to(root)
            if root and self.file.is_relative_to(root)
            else self.file
        )
        return f"{where}:{self.line}  {self.why}\n    {self.excerpt}\n    → {self.fix}"


_CODE_SUFFIXES = {".py", ".sh"}


def _is_a_test(path: Path) -> bool:
    """Whether this file is the recipe's own tests rather than the recipe.

    Skipped, because the platform never starts these — a test runs from a
    developer's shell, unconfined, and is entitled to reach a fixture directory
    or the author's own checkout. Reporting them as things the run cannot see is
    a false alarm about a run that will not happen, and a checker that cries
    about files nobody executes is a checker people learn to skim past. Found on
    the first pass over a real machine: the only two complaints against one
    recipe were both in its test file.
    """
    name = path.name.lower()
    return (
        name.startswith("test_")
        or name.endswith(("_test.py", "_test.sh"))
        or "tests" in path.parts
        or name == "conftest.py"
    )

#: A shell line that runs frago, rather than a line that mentions it. Anchored
#: to the places a command can start, because these files are as full of prose
#: about frago as they are of calls to it — a first version of this check
#: matched the word anywhere and reported the docstring of every recipe that
#: explains how to run itself.
_SHELL_FRAGO = re.compile(r"""(?:^|[;&|(]\s*|\$\(\s*|`\s*)frago\s+[a-z]""")

#: A path in a shell script, in the two shapes that are locations rather than
#: arguments.
_SHELL_PATH = re.compile(r"""(?<![\w?=&])(~/[\w./-]+|/[\w][\w./-]*)""")


def _looks_like_a_local_path(raw: str) -> Path | None:
    """The path this string names, or None if it is not naming one.

    A string starting with a slash is usually not a filesystem path at all —
    it is the tail of a URL, a regex, a format template. The test is whether
    its first component is a directory that exists on this machine, which is
    both cheap and exactly the question: a path the run might open is one whose
    root is real, and ``/CN_MarketData.getKLineData?symbol={x}`` has no such
    root while ``/Users/someone/x`` does.
    """
    text = raw.strip()
    if not text or ("://" in text) or any(ch in text for ch in "{}?&\n "):
        return None
    if text.startswith("~/"):
        return Path(text).expanduser()
    # A bare "/" is a separator — `"/".join(parts)` — not a location. Reporting
    # it names the root directory as something the run cannot reach, which is
    # both untrue and unfixable by whoever reads it.
    if not text.startswith("/") or text.strip("/") == "":
        return None
    head = Path("/" + text.lstrip("/").split("/", 1)[0])
    try:
        return Path(text) if head.is_dir() else None
    except OSError:
        return None


def _fix_for(target: Path, cli_view: View | None) -> str:
    """What to tell the author about this particular path.

    A path that the platform-CLI layer *would* cover gets told so. Without this
    the message says "use self.store" about ``~/.frago/config.json``, which is
    not the answer and sends the reader looking for one that does not exist.
    """
    if cli_view is not None and cli_view.sees(target):
        return (
            "这一条属于 frago 自己的机器件。要用它就在 recipe.md 里写 "
            "uses_frago_cli: true —— 那会把 frago 命令要用的目录交给这次运行，"
            "但不含任何人的数据。能走总线的优先走总线。"
        )
    return _OUT_OF_VIEW_FIX


def _python_findings(
    path: Path, view: View, *, uses_frago_cli: bool, cli_view: View | None = None
) -> list[Blocked]:
    """What this Python file does that the view will refuse.

    Parsed rather than grepped, and the reason is the same one that runs through
    this whole package: these files explain themselves at length, in prose that
    names paths and quotes commands. A text scan reports the explanation and
    misses ``Path.home() / ".frago" / …``, which is the shape that actually
    reaches out of the view — nobody writes the whole path in one string.
    """
    import ast

    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return []

    #: Docstrings are the file explaining itself. They open nothing.
    docstrings = {
        id(node.value) for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    lines = source.splitlines()

    #: The left-hand halves of longer chains. ``home() / "a" / "b" / "c"`` is a
    #: tree of divisions, so walking it yields the whole path *and* every prefix
    #: of it — and the prefixes are exactly the directories a bounded view does
    #: not contain. Reporting them turns one correct path into three complaints,
    #: two of which cannot be acted on.
    prefixes = {
        id(node.left) for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
    }

    #: Names bound to a plain string. The command a recipe starts is often one
    #: of these rather than a literal at the call site.
    strings = _string_names(tree)
    #: Names bound to a whole command line, mapped to the command they start.
    argvs = _argv_names(tree, strings)

    #: Names bound to a place, and the place. Nobody writes a whole path in one
    #: expression — they bind ``FRAGO_HOME = Path.home() / ".frago"`` once and
    #: divide off it everywhere after. Without following the name, the only
    #: thing this check can report is the binding itself, which is never opened:
    #: on a real machine that produced a complaint about ``~/.frago`` against a
    #: file whose two actual uses were both inside the view.
    bound: dict[str, Path] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        where = _chain_target(node.value, bound)
        if where is not None:
            bound[target.id] = where

    #: The names that get extended further. A binding is a place nobody opens —
    #: it is the anchor the real paths are built from — so reporting it names a
    #: directory the run never touches and hides the ones it does.
    anchors = {
        node.left.id for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
        and isinstance(node.left, ast.Name)
    }

    def excerpt(node: ast.AST) -> str:
        line = getattr(node, "lineno", 0)
        return lines[line - 1].strip()[:120] if 0 < line <= len(lines) else ""

    found: list[Blocked] = []

    for node in ast.walk(tree):
        # A path the recipe wrote down.
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            target = _looks_like_a_local_path(node.value)
            if target is not None and not view.sees(target):
                found.append(Blocked(
                    file=path, line=node.lineno, excerpt=excerpt(node),
                    why=f"隔离下这条路径不存在：{target}",
                    fix=_fix_for(target, cli_view),
                ))
        # A path built a segment at a time, off the home directory or off a name
        # already bound to one.
        elif (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
                and id(node) not in prefixes):
            if _is_anchor_binding(node, tree, anchors):
                continue
            target = _chain_target(node, bound)
            if target is not None and not view.sees(target):
                found.append(Blocked(
                    file=path, line=node.lineno, excerpt=excerpt(node),
                    why=f"隔离下这条路径不存在：{target}",
                    fix=_fix_for(target, cli_view),
                ))
        # The platform's own command, actually being run.
        elif (isinstance(node, ast.Call) and not uses_frago_cli
                and _runs_frago(node, strings, argvs)):
            found.append(Blocked(
                file=path, line=node.lineno, excerpt=excerpt(node),
                why="这里起了一个 frago 命令，但 recipe.md 没写 uses_frago_cli",
                fix=_CLI_FIX,
            ))

    return found


_OUT_OF_VIEW_FIX = (
    "配方跑在一个只看得见「自己的落点 + 别人声明共享的那一块」的视图里。"
    "自己的数据用 self.store / self.data_dir；"
    "别人的数据先在 reads_common 里声明、对方也写了 shares 才拿得到；"
    "别人的能力走总线（self.ask），不走文件。"
)

_CLI_FIX = (
    "隔离下 frago 命令看不见自己的工作目录，会当场失败。"
    "在 recipe.md 里写 uses_frago_cli: true —— 这一声明只交出 frago 自己的机器件，"
    "不含任何人的数据；或者改走总线：发布页面用 self.publish()，"
    "要别的模块的数据用 self.ask()。"
)


def _chain_target(node, bound: dict[str, Path]) -> Path | None:
    """The place this ``a / "b" / "c"`` chain names, or None if it names none.

    Two roots count: the home directory, and a name already bound to a place.
    Anything else — a path assembled from a variable this pass never saw, a
    value read at run time — is invisible here, and the module docstring says
    so rather than leaving it to be discovered.
    """
    import ast

    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
        return None
    parts = _chain_segments(node)
    if not parts:
        return None
    if _rooted_at_home(node):
        return Path.home().joinpath(*parts)
    leftmost = node
    while isinstance(leftmost, ast.BinOp):
        leftmost = leftmost.left
    if isinstance(leftmost, ast.Name) and leftmost.id in bound:
        return bound[leftmost.id].joinpath(*parts)
    return None


def _is_anchor_binding(node, tree, anchors: set[str]) -> bool:
    """Whether this chain is only the anchor other paths are built from.

    ``FRAGO_HOME = Path.home() / ".frago"`` opens nothing; the opens are the
    chains divided off that name. Reporting the binding names a directory the
    run never touches, and the person reading it cannot act on it.
    """
    import ast

    for stmt in ast.walk(tree):
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if (isinstance(target, ast.Name) and target.id in anchors
                and stmt.value is node):
            return True
    return False


def _chain_segments(node) -> list[str]:
    import ast

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _chain_segments(node.left) + _chain_segments(node.right)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    return []


def _rooted_at_home(node) -> bool:
    import ast

    return any(
        isinstance(sub, ast.Call)
        and isinstance(sub.func, ast.Attribute)
        and sub.func.attr == "home"
        for sub in ast.walk(node)
    )


def _string_names(tree) -> dict[str, str]:
    """Every name bound to a plain string, wherever in the file it is bound.

    Module level and class body alike, because the shape this exists for appears
    in both: a recipe writes ``FRAGO = "frago"`` once and uses that name at
    every call site. Keyed by the bare name, so ``self.FRAGO`` resolves through
    the same table as ``FRAGO`` — a check that had to know which object an
    attribute hangs off would be a type checker, and would still be wrong about
    a name reassigned halfway down. Being generous here is safe: the answer is
    only ever used to ask "is this string 'frago'".
    """
    import ast

    found: dict[str, str] = {}
    for node in ast.walk(tree):
        value = getattr(node, "value", None)
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = value.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found[node.target.id] = value.value
    return found


def _as_string(node, names: dict[str, str]) -> str | None:
    """The string this expression is, if it plainly is one."""
    import ast

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return names.get(node.id)
    if isinstance(node, ast.Attribute):
        return names.get(node.attr)
    return None


def _argv_names(tree, strings: dict[str, str]) -> dict[str, str]:
    """Names bound to a command line, mapped to the command they start.

    The second way of spelling the same thing, and the one that survived the
    first fix: build the whole command into a variable on one line, hand that
    variable to the subprocess call on the next. Following the command name
    through a constant but not through the list it sits in leaves exactly the
    recipes that write their calls most carefully still invisible.
    """
    import ast

    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        value = node.value
        if not isinstance(target, ast.Name):
            continue
        if not isinstance(value, (ast.List, ast.Tuple)) or not value.elts:
            continue
        first = _as_string(value.elts[0], strings)
        if first is not None:
            found[target.id] = first
    return found


def _runs_frago(call, names: dict[str, str] | None = None,
                argvs: dict[str, str] | None = None) -> bool:
    """Whether this call starts frago's own CLI.

    Looks at what is being started, not at what the line says: the first element
    of an argv list, or the string handed to a shell.

    **The command name is followed through a name.** It did not used to be, and
    the cost was exact: a family of nine recipes had all hoisted the word into a
    constant — a deliberate tidy-up, with the reason written in their source —
    and every one of them called frago's CLI without declaring it while this
    check reported nothing. Nine passed the gate; three were broken at run time.
    A check that only recognises the most artless spelling of a thing is a check
    that rewards artlessness.

    Still shallow, and still said out loud: a command name assembled at run time
    — read from a config file, joined from pieces, picked out of a list — is
    invisible here.
    """
    import ast

    names = names or {}
    argvs = argvs or {}
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if name not in {"run", "Popen", "call", "check_call", "check_output", "system",
                    "create_subprocess_exec", "create_subprocess_shell"}:
        return False
    for arg in call.args[:1]:
        if isinstance(arg, (ast.List, ast.Tuple)) and arg.elts:
            first = _as_string(arg.elts[0], names)
            return first is not None and Path(first).name == "frago"
        # The command was assembled on an earlier line and handed over by name.
        if isinstance(arg, ast.Name) and arg.id in argvs:
            return Path(argvs[arg.id]).name == "frago"
        spelled = _as_string(arg, names)
        if spelled is not None:
            return spelled.strip().startswith("frago ")
        if isinstance(arg, ast.JoinedStr) and arg.values:
            head = arg.values[0]
            if isinstance(head, ast.Constant):
                return str(head.value).strip().startswith("frago ")
            # `f"{FRAGO} recipe run …"` — the command name is the first hole.
            if isinstance(head, ast.FormattedValue):
                first = _as_string(head.value, names)
                return first is not None and Path(first).name == "frago"
    return False


def _shell_findings(
    path: Path, view: View, *, uses_frago_cli: bool, cli_view: View | None = None
) -> list[Blocked]:
    """The same two questions of a shell script, with no parser to help.

    Comment lines are dropped and command starts are anchored; beyond that this
    is a text scan and cannot be more.
    """
    found: list[Blocked] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return found
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for match in _SHELL_PATH.finditer(line):
            target = _looks_like_a_local_path(match.group(1))
            if target is not None and not view.sees(target):
                found.append(Blocked(
                    file=path, line=number, excerpt=line[:120],
                    why=f"隔离下这条路径不存在：{target}",
                    fix=_fix_for(target, cli_view),
                ))
        if not uses_frago_cli and _SHELL_FRAGO.search(line):
            found.append(Blocked(
                file=path, line=number, excerpt=line[:120],
                why="这里起了一个 frago 命令，但 recipe.md 没写 uses_frago_cli",
                fix=_CLI_FIX,
            ))
    return found


def foresee(
    recipe_dir: Path,
    recipe_name: str,
    *,
    uses_frago_cli: bool = False,
    shared: dict[str, Path] | None = None,
    landing_spot: Path | None = None,
) -> list[Blocked]:
    """What this recipe does that its own view will refuse, before it runs.

    Answered by asking the view itself rather than by a second list of allowed
    places, because a second list is a second answer: the whole failure this
    exists to prevent is a check and a boundary that disagree, where one says
    "fine" and the other kills the run.

    Deliberately shallow. It reads paths a recipe writes down, and a path
    assembled at run time from three variables is invisible to it — which is
    said here rather than left for somebody to discover, because a check that
    is mistaken for a guarantee is worse than one nobody trusts.
    """
    view = view_for(
        recipe_name,
        landing_spot=landing_spot,
        recipe_dir=recipe_dir,
        shared=shared,
        uses_frago_cli=uses_frago_cli,
    )
    # The same view with the platform's own machinery added, used only to tell
    # a path that one declaration would fix from one that needs the code changed.
    cli_view = None if uses_frago_cli else view_for(
        recipe_name, landing_spot=landing_spot, recipe_dir=recipe_dir,
        shared=shared, uses_frago_cli=True,
    )

    found: list[Blocked] = []
    for path in sorted(recipe_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _CODE_SUFFIXES:
            continue
        if _is_a_test(path):
            continue
        scan = _python_findings if path.suffix.lower() == ".py" else _shell_findings
        found += scan(path, view, uses_frago_cli=uses_frago_cli, cli_view=cli_view)
    return sorted(found, key=lambda one: (str(one.file), one.line))


def wrap(
    cmd: list[str], view: View, *, cwd: Path | None = None
) -> tuple[list[str], str]:
    """The command to actually start, and the name of what is holding it.

    Returns the command unchanged with an empty name when the owner turned
    isolation off — the one path where an unconfined recipe starts, and it takes
    a line in a config file to reach.

    Raises ``NoBackend`` when isolation is on and this machine has none. The
    caller turns that into a refusal to run; it must not turn it into a run.
    """
    if configured() == OFF:
        logger.warning(
            "配方 %s 不在隔离下运行：recipe.isolation 被设成了 off。"
            "它能读任何一个账号的数据、能写任何一份共读数据。",
            cmd[0] if cmd else "?",
        )
        return cmd, ""
    chosen = backend()
    if chosen is not None:
        return chosen.wrap(cmd, view, cwd=cwd), chosen.name

    # Windows warns and runs; everywhere else refuses.
    #
    # Not a softer standard for one platform — a different situation. What
    # isolation buys is protection *between* the people sharing a machine, and
    # a Windows install is one person on their own laptop: the recipe already
    # runs as them, and the account whose data it might reach is theirs. The
    # refusal is worth its cost on a server, where several people's data and the
    # machine's own credentials sit under one unix account, and it is not worth
    # making frago unusable on a personal machine that has no such neighbours.
    #
    # Said out loud on every run rather than assumed, because the day that
    # machine does grow a second person is the day somebody needs to know this
    # was never confined.
    if platform.system() == "Windows":
        logger.warning("配方 %s 不在隔离下运行：%s", cmd[0] if cmd else "?",
                       why_unavailable())
        return cmd, ""
    raise NoBackend(why_unavailable())
