"""What this layer refuses to touch, whoever is asking.

Three rules, each with a reason that survives the machine it was written on.
Deliberately **not** a list of names that sound dangerous: the platform already
made that decision once, for the bus door these commands arrive through
(``frago.server.routes.bus.bus_frago``), and rejected sorting commands by how
alarming they read. The same reasoning applies to targets, so what is here had
to earn its place by what its loss costs, not by how it sounds.

**One. "Everything" is not a file.** The root, the home directory itself, and
every directory between them. ``frago rm ~`` is never a thing somebody meant; it
is a path variable that came out empty. The trash would accept it without
complaining, and the machine would come apart around a path nobody typed on
purpose.

**Two. The operating system.** ``/usr``, ``/System``, ``/etc`` and the rest — the
same subtrees ``frago.recipes.isolation`` hands a recipe read-only, for the same
reason: a recipe that writes into ``/usr`` is not a recipe with a bug, it is a
recipe changing the machine for everything else that runs on it. The two lists
are written separately on purpose. They answer different questions — "what may
this run read" and "what may nobody move" — and folding them into one would mean
the next change to either silently moves the other.

**Three. frago's own books, except the work products.** ``~/.frago`` holds every
account's data, this machine's identity, and every recipe's credentials. A
generic move command has no business in there: each of those has its own command
that knows what removing it means. The carve-out is **output** — ``~/.frago/data``
where an agent's work products land, and the ``recipe-data`` trees where a
recipe's own working data lands, both by the platform's own rules
(``frago book must-data-dir``, ``must-recipe-data``). Deleting last month's report,
or a clip out of a recipe's own library, is an ordinary file operation; refusing it
would only teach people to go around this layer. See ``work_products`` for what
separated the two — output speaks for nobody but its owner, the rest speaks for
the whole machine.

**And the trash itself.** Everything in there is what is left of a deletion
somebody has not finished making: they can fish it out or empty the trash, and
until they do, that choice is still theirs. A command that moves things around
inside the trash — or deletes them out of it — makes the choice for them, and
does it where they will not see it happen.

**What is deliberately not here.** ``~/.ssh``, ``~/.aws``, a browser profile: they
hold secrets, and this layer does not read files, it moves them — and everything
it moves goes to the trash rather than away, so ``frago rm ~/.ssh`` leaves the
keys somewhere their owner can still get at them. Refusing them would be
protecting against the wrong verb, and would be the "sounds dangerous" list this
module opens by refusing to be.
"""

from __future__ import annotations

import contextlib
import os
import platform
from pathlib import Path


class Refused(RuntimeError):
    """This target is out of bounds. Carries what to do instead."""

    def __init__(self, message: str, *fixes: str):
        super().__init__(message)
        self.fixes: tuple[str, ...] = tuple(f for f in fixes if f)


#: The directory name the platform files a recipe's own working data under, both
#: inside an account and at machine level. Spelled here rather than imported so a
#: bare CLI process does not have to pull in the recipe machinery to decide
#: whether a path is somebody's output; it must stay in step with
#: ``frago.recipes.app_state.RECIPE_DATA``.
RECIPE_DATA = "recipe-data"


def frago_home() -> Path:
    return Path.home() / ".frago"


def work_products() -> list[Path]:
    """The subtrees of the frago home this layer will operate in.

    Two kinds of the same thing: output. ``data`` is where an agent's work
    products land by the platform's own rule; ``recipe-data`` is where a recipe's
    own working data lands by the platform's other rule — one tree per account,
    plus a machine-level one for what a recipe keeps outside any account.

    ``recipe-data`` was missing here at first, and the cost showed up the same
    day: a recipe that keeps a library of video clips could not delete one of its
    own clips. It cannot move the file to the trash itself — the trash is in the
    home directory and a recipe only sees its own landing spot — so it asks the
    platform, and the platform refused, on the grounds that the file was "in
    ~/.frago, where accounts, identity and credentials live". It was none of
    those. It was that recipe's own footage, in the one directory the platform
    told it to write to.

    The distinction that matters is not "inside the frago home or outside" — it
    is **whose data this is and who else it speaks for**. A recipe's own output
    speaks for nobody else. The machine's identity, an account's credentials and
    the books every command reads do, and each of those has a command of its own
    that knows what removing it means.
    """
    home = frago_home()
    roots = [home / "data", home / RECIPE_DATA]
    # One per account. Globbed rather than resolved through the server's own
    # helper: this module is reached from a bare CLI process that must not have
    # to import the platform's account machinery to answer "is this output".
    accounts = home / "users"
    if accounts.is_dir():
        with contextlib.suppress(OSError):
            roots += [child / RECIPE_DATA for child in accounts.iterdir() if child.is_dir()]
    return roots


def system_roots() -> list[Path]:
    """The parts of the machine that belong to the operating system.

    Neither ``/tmp`` nor ``/var`` is here, and that is the point of writing the
    list rather than reaching for "everything outside the home directory":
    scratch space is where half of this layer's real work happens.
    """
    if platform.system() == "Darwin":
        return [
            Path(p) for p in (
                "/usr", "/bin", "/sbin", "/System", "/Library", "/opt",
                "/private/etc", "/private/var/db", "/private/var/select",
                "/Applications", "/cores",
            )
        ]
    if platform.system() == "Windows":
        windir = os.environ.get("SYSTEMROOT") or r"C:\Windows"
        return [Path(windir), Path(r"C:\Program Files"), Path(r"C:\Program Files (x86)")]
    return [
        Path(p) for p in (
            "/usr", "/bin", "/sbin", "/lib", "/lib64", "/lib32", "/etc", "/opt",
            "/boot", "/proc", "/sys", "/dev", "/run",
        )
    ]


def mount_parents() -> list[Path]:
    """Directories that hold mount points. The directory itself is refused; what
    is under it is somebody's disk and is ordinary."""
    return [Path(p) for p in ("/Volumes", "/mnt", "/media", "/home", "/Users")]


def trash_roots() -> list[Path]:
    """Every place this layer might have put something, and will not go back into."""
    from frago.files.trash import known_trash_roots

    return known_trash_roots()


def settle(target: Path) -> Path:
    """The path to judge, with the symlinks in its parents resolved.

    The last component is left alone on purpose: ``rm link`` removes the link,
    not what it points at, so the thing being judged is the link. Resolving it
    would judge the target instead, and refuse ``rm`` of a harmless symlink that
    happens to point into ``/usr``.
    """
    target = Path(target).expanduser()
    parent = target.parent
    try:
        settled = Path(os.path.realpath(parent))
    except OSError:
        settled = parent
    return settled / target.name if target.name not in ("", ".", "..") else settled


def check(target: Path, *, verb: str) -> Path:
    """Refuse this target, or hand back the settled path to operate on.

    ``verb`` is the word that goes in the refusal — "删除", "覆盖", "移动" — so
    that the message says what was about to happen rather than naming a rule.
    """
    path = settle(target)
    home = Path.home()

    if path == Path(path.anchor) or path == home or home.is_relative_to(path):
        raise Refused(
            f"不能{verb} {path}——这不是一个文件，是「全部」。"
            f"根目录、家目录本身、以及它们之间的每一层，一律不动。",
            "把路径写到具体的那一个文件或目录上",
        )

    for root in mount_parents():
        if path == root:
            raise Refused(
                f"不能{verb} {path}——它是挂载点所在的目录，不是某一份数据。"
                f"它下面的某一块盘、某一个人的家目录是正常目标，它自己不是。",
                f"写到具体的那一项上，比如 {root}/<名字>/<文件>",
            )

    for root in system_roots():
        if path == root or path.is_relative_to(root):
            raise Refused(
                f"不能{verb} {path}——它属于操作系统（{root}）。"
                f"动这里不是改一份数据，是改这台机器上所有程序的运行环境。",
                "系统目录交给包管理器或系统自己的工具",
            )

    for root in trash_roots():
        if path == root or path.is_relative_to(root):
            raise Refused(
                f"不能{verb} {path}——它在垃圾桶里。"
                f"里面每一样都是某次删除之后仅剩的那一份，捞回来还是清掉，"
                f"是它主人自己还没做的决定。",
                "要取回其中一项，去垃圾桶里直接拖出来",
                "要彻底清空垃圾桶，用系统自己的「清倒废纸篓」",
            )

    home_of_frago = frago_home()
    mine = any(path == root or path.is_relative_to(root) for root in work_products())
    if (path == home_of_frago or path.is_relative_to(home_of_frago)) and not mine:
        raise Refused(
            f"不能{verb} {path}——它在 ~/.frago 里。"
            f"那里面装的是每个账号的数据、这台机器的身份、每个配方的凭证。"
            f"这些各有各的命令，它们知道删掉意味着什么。",
            "frago recipe uninstall <名字>   # 卸一个配方",
            "frago todo remove <id>          # 删一条待办",
            "产出不受此限：~/.frago/data 下的，以及各配方自己 recipe-data 落点里的",
        )

    return path
