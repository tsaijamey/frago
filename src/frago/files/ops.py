"""Copy, move, delete — three verbs, with unix's meanings.

**Why the platform owns these at all.** A recipe runs inside a view of the
filesystem that holds its own landing spot and nothing else
(``frago.recipes.isolation``). That boundary is right and it leaves one thing
impossible: a recipe cannot put a file in the system trash, because the trash
lives in the owner's home directory, outside every recipe's view. Measured on
this machine: asking Finder to trash a file from inside a confined run fails on
the spot with ``-10004``; the same request unconfined succeeds. So the recipe
asks the platform to run a command instead, the command runs in the server's
process tree where the trash actually is, and these three are the commands that
were missing.

**The semantics are unix's, deliberately.** Everybody calling these already
knows what ``cp -r`` does, and a layer that re-decides what "copy" means costs
its callers more than it could possibly buy them. There is one departure and it
has a single shape: nothing here destroys anything. A deleted file and a
replaced one both go to this machine's trash, where they sit until their owner
empties it — the same rule this machine already applies to ``rm`` by hand.

**Nothing succeeds quietly.** Every operation reports what it touched, what it
replaced and where the replaced thing went, and anything that did not happen
comes back as a failure with a non-zero exit. A caller over the bus reads an
exit code and a stream of text, and an empty success is indistinguishable from
a command that did nothing at all.
"""

from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from frago.files import trash as trashlib
from frago.files.guard import Refused, check


def new_operation_id() -> str:
    """One command, one id, stamped on the report it produced.

    Grouped rather than per-item because a report is about the command somebody
    typed: ``frago rm a b c`` is one thing that happened, and a caller reading
    the output over the bus needs one name for it.
    """
    return "op-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]


@dataclass
class Done:
    """One thing that actually happened."""

    verb: str
    source: Path | None
    target: Path | None
    kind: str = "file"
    #: What was sitting at the target, and where it went instead of away.
    replaced: dict | None = None
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "verb": self.verb,
            "source": str(self.source) if self.source else None,
            "target": str(self.target) if self.target else None,
            "kind": self.kind,
            "replaced": self.replaced,
            "note": self.note,
        }


@dataclass
class Failed:
    """One thing that did not happen, and what to do about it."""

    path: Path
    why: str
    fixes: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"path": str(self.path), "why": self.why, "fixes": list(self.fixes)}


@dataclass
class Report:
    """What one command did. Rendered by the CLI layer, read by the bus caller."""

    op: str
    op_id: str
    done: list[Done] = field(default_factory=list)
    failed: list[Failed] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed

    def as_dict(self) -> dict:
        return {
            "op": self.op,
            "op_id": self.op_id,
            "ok": self.ok,
            "done": [d.as_dict() for d in self.done],
            "failed": [f.as_dict() for f in self.failed],
        }


def kind_of(path: Path) -> str:
    if path.is_symlink():
        return "link"
    return "dir" if path.is_dir() else "file"


def _exists(path: Path) -> bool:
    """Whether there is anything at this name — a broken symlink included.

    ``Path.exists`` follows the link and answers "no" for one whose target is
    gone, which would make ``cp`` silently write over a link somebody still had
    a use for.
    """
    return path.exists() or path.is_symlink()


def _is_dir(path: Path) -> bool:
    """A directory, and not a symlink pointing at one. ``mv x linkdir`` moves the
    link out of the way rather than putting ``x`` inside what it points at,
    which is what unix does and what the person reading the line expects."""
    return path.is_dir() and not path.is_symlink()


def _same_thing(a: Path, b: Path) -> bool:
    try:
        return os.path.samestat(os.lstat(a), os.lstat(b))
    except OSError:
        return False


def _landing(source: Path, destination: Path, *, many: bool) -> Path:
    """Where this source ends up, by unix's rules.

    An existing directory as the destination means "inside it, under the same
    name"; anything else means "become this". More than one source therefore
    requires the destination to be a directory that already exists — the
    alternative is three files taking turns overwriting one name.
    """
    if _is_dir(destination):
        return destination / source.name
    if many:
        raise Refused(
            f"给了多个来源，那目标 {destination} 必须是一个已经存在的目录。"
            f"否则就是几个文件轮流覆盖同一个名字。",
            f"mkdir -p {destination}",
        )
    if str(destination).endswith((os.sep, "/")) and not _exists(destination):
        raise Refused(
            f"{destination} 写成了目录的样子，但这个目录不存在。",
            f"mkdir -p {destination}",
        )
    return destination


def _clear(destination: Path) -> dict | None:
    """Put whatever is at the destination into the trash, and say where it went.

    **This is the one place this layer does not do what unix does.** ``cp a b``
    on any unix destroys the old ``b``; here the old ``b`` goes to the system
    trash first, so the command behaves the same — it succeeds, and ``b`` is now
    a copy of ``a`` — while the thing that was there is still sitting somewhere
    its owner can go and look. The cost is trash that fills up faster; the
    alternative is a wrong path variable quietly destroying a file that had no
    other copy, which is the failure this whole layer exists to end.
    """
    if not _exists(destination):
        return None
    check(destination, verb="覆盖")
    landed = trashlib.send_to_trash(destination)
    return {"path": str(destination), "trash_path": str(landed.trash_path or "")}


# ── cp ─────────────────────────────────────────────────────────────────────


def copy(sources: list[Path], destination: Path, *, recursive: bool = False,
         no_clobber: bool = False) -> Report:
    """``frago cp`` — unix ``cp``, with the replaced file kept.

    A directory needs ``-r``, exactly as unix requires it: copying a tree is a
    different-sized decision from copying a file, and the flag is where somebody
    says they meant it.
    """
    report = Report(op="cp", op_id=new_operation_id())
    many = len(sources) > 1
    for raw in sources:
        source = Path(raw).expanduser()
        try:
            if not _exists(source):
                raise Refused(f"{source} 不存在。")
            target = _landing(source, Path(destination).expanduser(), many=many)
            # Only the destination is judged. A guard on the source would be
            # refusing a *read*, and reading is not a boundary this door holds:
            # the same bus already answers `frago session search`, which hands
            # back the contents of every transcript on this machine. Pretending
            # otherwise here would cost real work (`cp /usr/share/... .` is
            # ordinary) and protect nothing.
            check(target, verb="写入")
            if _exists(target) and _same_thing(source, target):
                raise Refused(f"{source} 和 {target} 是同一个文件。")
            if kind_of(source) == "dir" and not recursive:
                raise Refused(
                    f"{source} 是一个目录，复制目录要加 -r。",
                    f"frago cp -r {source} {destination}",
                )
            if no_clobber and _exists(target):
                report.done.append(Done(verb="skipped", source=source, target=target,
                                        kind=kind_of(source),
                                        note="目标已存在，--no-clobber 让它留着"))
                continue
            replaced = _clear(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            if kind_of(source) == "dir":
                shutil.copytree(source, target, symlinks=True)
            else:
                shutil.copy2(source, target, follow_symlinks=False)
            report.done.append(Done(verb="copied", source=source, target=target,
                                    kind=kind_of(source), replaced=replaced))
        except Refused as err:
            report.failed.append(Failed(source, str(err), err.fixes))
        except OSError as err:
            report.failed.append(Failed(source, f"复制失败：{err}"))
    return report


# ── mv ─────────────────────────────────────────────────────────────────────


def move(sources: list[Path], destination: Path, *, no_clobber: bool = False) -> Report:
    """``frago mv`` — unix ``mv``: rename, or move into an existing directory.

    No ``-r``: unix does not ask for one either, because moving a tree is one
    rename when it stays on the same disk and this is the same operation
    whatever is at the end of the path.
    """
    report = Report(op="mv", op_id=new_operation_id())
    many = len(sources) > 1
    for raw in sources:
        source = Path(raw).expanduser()
        try:
            if not _exists(source):
                raise Refused(f"{source} 不存在。")
            target = _landing(source, Path(destination).expanduser(), many=many)
            check(source, verb="移动")
            check(target, verb="写入")
            if _exists(target) and _same_thing(source, target):
                raise Refused(f"{source} 和 {target} 是同一个文件，移动它没有意义。")
            if no_clobber and _exists(target):
                report.done.append(Done(verb="skipped", source=source, target=target,
                                        kind=kind_of(source),
                                        note="目标已存在，--no-clobber 让它留着"))
                continue
            replaced = _clear(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            was = kind_of(source)
            shutil.move(str(source), str(target))
            report.done.append(Done(verb="moved", source=source, target=target, kind=was,
                                    replaced=replaced))
        except Refused as err:
            report.failed.append(Failed(source, str(err), err.fixes))
        except OSError as err:
            report.failed.append(Failed(source, f"移动失败：{err}"))
    return report


# ── rm ─────────────────────────────────────────────────────────────────────


def remove(targets: list[Path], *, recursive: bool = False,
           force: bool = False) -> Report:
    """``frago rm`` — unix ``rm``, except that it is a move, not an unlink.

    The target goes to this machine's trash, which is where deleting things on
    this machine already goes. What that buys is one thing, and only that thing:
    the file sits somewhere its owner can open and drag it back out of, until
    they empty the trash themselves. There is no flag that makes this an unlink
    — destroying the only copy of something is a thing a person should type
    themselves, in their own shell, having read the path twice.
    """
    report = Report(op="rm", op_id=new_operation_id())
    for raw in targets:
        target = Path(raw).expanduser()
        try:
            if not _exists(target):
                if force:
                    continue
                raise Refused(f"{target} 不存在。", f"frago rm -f {target}   # 不存在就当没这回事")
            # 先过守卫，再问要不要 -r。反过来的话，`frago rm ~` 得到的是
            # 「目录要加 -r」外加一句 `[Fix] frago rm -r /Users/frago` ——
            # 一条必然被拒的命令，而 [Fix] 那行的全部价值就是照着敲就能成。
            # 更糟的是它把「删掉整个家目录」写成了建议的样子。
            settled = check(target, verb="删除")
            kind = kind_of(target)
            if kind == "dir" and not recursive:
                raise Refused(
                    f"{target} 是一个目录，删除目录要加 -r。",
                    f"frago rm -r {target}",
                )
            landed = trashlib.send_to_trash(settled)
            report.done.append(Done(verb="trashed", source=target,
                                    target=landed.trash_path, kind=kind,
                                    note=landed.note))
        except Refused as err:
            report.failed.append(Failed(target, str(err), err.fixes))
        except OSError as err:
            report.failed.append(Failed(target, f"进垃圾桶失败：{err}"))
    return report
