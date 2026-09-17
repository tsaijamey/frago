"""Putting something in this machine's trash.

**Why a move rather than a delete.** This machine's own rule for removing files
is that they go to the trash (the ``userdir-deny-rm-use-trash`` hook rule says so
to every agent that types ``rm``), and the reason is the same one a desktop has:
between "gone from where it was" and "gone for good" there is a room the owner
walks into themselves. A file in the trash can be dragged back out in Finder, or
left alone until the trash is emptied. That decision belongs to whoever owns the
machine, and frago does not make it for them in either direction — it neither
destroys the file nor promises to bring it back.

**The name it lands under is never guessed.** A trash directory already holding a
``report.pdf`` gets the new one under a name that is free, resolved at the moment
of the move and handed back to the caller, because the item already sitting there
is somebody's earlier deletion and may be the only copy of itself left.

**The freedesktop note is written where the layout takes one.** ``.trashinfo`` is
what a Linux file manager's "Restore" reads; writing it is how a file this module
moved stays as recoverable by hand as one the desktop trashed itself.
"""

from __future__ import annotations

import contextlib
import os
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote


def home_trash() -> Path:
    """The trash this machine's desktop opens when somebody clicks the icon."""
    if platform.system() == "Darwin":
        return Path.home() / ".Trash"
    if platform.system() == "Windows":
        # Windows has a Recycle Bin and no way to reach it from the standard
        # library. Said out loud rather than pretended: the fallback below is a
        # real directory, it is simply not the bin Explorer shows. See the
        # delivery note.
        return fallback_trash()
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data_home) / "Trash"


def fallback_trash() -> Path:
    """frago's own holding area, for a machine whose trash cannot be reached."""
    return Path.home() / ".frago" / "trash"


def known_trash_roots() -> list[Path]:
    """Every directory this module might have put something in.

    Used by the guard next door to refuse operating inside the trash, so it has
    to name the volume trashes too — a file deleted from an external disk does
    not land in the home trash.
    """
    roots = [home_trash(), fallback_trash()]
    if platform.system() == "Darwin":
        roots.append(Path.home() / ".Trash")
        for volume in _volumes():
            roots.append(volume / ".Trashes")
    else:
        for volume in _volumes():
            roots.append(volume / f".Trash-{os.getuid()}")
            roots.append(volume / ".Trash")
    seen: list[Path] = []
    for one in roots:
        if one not in seen:
            seen.append(one)
    return seen


def _volumes() -> list[Path]:
    out: list[Path] = []
    for holder in ("/Volumes", "/mnt", "/media"):
        root = Path(holder)
        try:
            if root.is_dir():
                out += [p for p in root.iterdir() if p.is_dir()]
        except OSError:
            continue
    return out


# ── getting something in there ─────────────────────────────────────────────


@dataclass(frozen=True)
class Trashed:
    """One thing that went into the trash, and where it is now."""

    origin: Path
    #: ``None`` when the helper that moved it would not say what it is called
    #: now — reported as the gap it is rather than filled in with a guess.
    trash_path: Path | None
    backend: str
    note: str = ""


def _mount_point(path: Path) -> Path:
    here = path if path.is_dir() else path.parent
    here = Path(os.path.realpath(here))
    while not os.path.ismount(here) and here != here.parent:
        here = here.parent
    return here


def _same_device(a: Path, b: Path) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def _free_name(directory: Path, name: str) -> Path:
    """A name nothing in there is using.

    The suffix is the epoch second, which is the shape this machine already
    uses: the ``userdir-deny-rm-use-trash`` hook rule hands agents exactly this
    algorithm to type by hand, and two spellings of "what a trashed duplicate is
    called" would be one more thing that has to agree with itself.

    **Never overwrites.** The item already sitting there is somebody's earlier
    deletion, and it is the one thing in the system whose only copy is in the
    trash.
    """
    candidate = directory / name
    if not candidate.exists() and not candidate.is_symlink():
        return candidate
    stamp = int(time.time())
    candidate = directory / f"{name}.{stamp}"
    n = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = directory / f"{name}.{stamp}-{n}"
        n += 1
    return candidate


def _write_trashinfo(info_dir: Path, item: Path, origin: Path) -> None:
    """The freedesktop note that lets the desktop's own trash restore it too.

    This is the only thing that remembers where the item came from, and the file
    manager is the only reader: a trashed file that no "Restore" knows the origin
    of is one somebody has to identify by eye.
    """
    info_dir.mkdir(parents=True, exist_ok=True)
    note = (
        "[Trash Info]\n"
        f"Path={quote(str(origin), safe='/')}\n"
        f"DeletionDate={datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n"
    )
    (info_dir / f"{item.name}.trashinfo").write_text(note, encoding="utf-8")


def _freedesktop_trash(path: Path) -> Trashed:
    """The Linux layout: ``files/`` holds the item, ``info/`` says where it was."""
    home = home_trash()
    if _same_device(path.parent, home.parent if home.exists() else Path.home()):
        root, backend = home, "freedesktop-home"
    else:
        volume = _mount_point(path)
        root, backend = volume / f".Trash-{os.getuid()}", "freedesktop-volume"
    files, info = root / "files", root / "info"
    files.mkdir(parents=True, exist_ok=True)
    landed = _free_name(files, path.name)
    shutil.move(str(path), str(landed))
    # The item is already safe at this point: it is in the trash either way, and
    # the note is what lets the desktop offer "Restore" for it. Failing to write
    # it must not undo the move.
    with contextlib.suppress(OSError):
        _write_trashinfo(info, landed, path)
    return Trashed(origin=path, trash_path=landed, backend=backend)


def _macos_trash(path: Path) -> Trashed:
    home = Path.home() / ".Trash"
    home.mkdir(parents=True, exist_ok=True)
    if _same_device(path.parent, home):
        root, backend = home, "macos-home-trash"
    else:
        volume = _mount_point(path)
        root, backend = volume / ".Trashes" / str(os.getuid()), "macos-volume-trash"
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            # An external disk that will not take a trash directory — a FAT
            # stick, a read-only mount. Falling back to the home trash means a
            # cross-device copy, which is slower and still correct.
            root, backend = home, "macos-home-trash"
    landed = _free_name(root, path.name)
    shutil.move(str(path), str(landed))
    return Trashed(origin=path, trash_path=landed, backend=backend)


def _desktop_helper(path: Path) -> Trashed | None:
    """``gio trash`` / ``trash-put``, for a layout this module got wrong.

    Only reached when the freedesktop move failed, because these two hand back
    nothing: the item is gone and neither tells the caller what it is called
    now. The name is recovered by reading the ``.trashinfo`` files afterwards
    and finding the one that names this path — and if that fails, the report says
    it does not know rather than naming a file it did not verify.
    """
    for tool, argv in (("gio", ["gio", "trash", "--"]), ("trash-put", ["trash-put", "--"])):
        if not shutil.which(argv[0]):
            continue
        try:
            done = subprocess.run([*argv, str(path)], capture_output=True, text=True,
                                  timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if done.returncode != 0:
            continue
        landed = _find_trashinfo(path)
        return Trashed(
            origin=path,
            trash_path=landed,
            backend=tool,
            note="" if landed else f"{tool} 没有说它把文件放成了什么名字，得自己去垃圾桶里认",
        )
    return None


def _find_trashinfo(origin: Path) -> Path | None:
    """The newest trash entry claiming to have come from ``origin``."""
    best: tuple[float, Path] | None = None
    for root in known_trash_roots():
        info_dir = root / "info"
        if not info_dir.is_dir():
            continue
        for note in info_dir.glob("*.trashinfo"):
            try:
                text = note.read_text(encoding="utf-8", errors="ignore")
                stamp = note.stat().st_mtime
            except OSError:
                continue
            for line in text.splitlines():
                if line.startswith("Path=") and unquote(line[5:].strip()) == str(origin):
                    item = root / "files" / note.name[: -len(".trashinfo")]
                    if best is None or stamp > best[0]:
                        best = (stamp, item)
    return best[1] if best else None


def send_to_trash(path: Path) -> Trashed:
    """Move one thing into this machine's trash. Raises ``OSError`` if it cannot.

    Never deletes as a fallback. The whole difference between this and an unlink
    is that the file is somewhere its owner can still go and look; a branch that
    quietly destroys it instead would take that away exactly when the trash was
    hardest to reach.
    """
    path = Path(path)
    system = platform.system()
    if system == "Darwin":
        return _macos_trash(path)
    if system == "Windows":
        root = fallback_trash()
        root.mkdir(parents=True, exist_ok=True)
        landed = _free_name(root, path.name)
        shutil.move(str(path), str(landed))
        return Trashed(origin=path, trash_path=landed, backend="frago-trash",
                       note="Windows 上没有能从命令行进的回收站，东西在 ~/.frago/trash")
    try:
        return _freedesktop_trash(path)
    except OSError as err:
        helped = _desktop_helper(path)
        if helped is not None:
            return helped
        root = fallback_trash()
        try:
            root.mkdir(parents=True, exist_ok=True)
            landed = _free_name(root, path.name)
            shutil.move(str(path), str(landed))
        except OSError:
            raise err from None
        return Trashed(origin=path, trash_path=landed, backend="frago-trash",
                       note="系统垃圾桶进不去，东西在 ~/.frago/trash")
