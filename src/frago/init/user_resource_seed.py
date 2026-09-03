"""Seed package-shipped knowledge into ``~/.frago`` so the user can edit it.

Two kinds of text ship inside the wheel: the book topics and the constitution.
Both are meant to be read *and changed* by the person running frago, and a file
inside site-packages is neither editable in practice nor survives an upgrade.
So the wheel carries the pristine copy and this module lays it down under
``~/.frago`` the first time it is missing.

The one rule that matters: **an existing file is never overwritten.** A file
that is already there has, as far as this module can tell, been edited on
purpose; replacing it on every server start would silently undo that. New files
appearing in a later release still arrive, because the check is per file.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from importlib.resources import files as pkg_files
from pathlib import Path

logger = logging.getLogger(__name__)

FRAGO_HOME = Path.home() / ".frago"

#: ``(package resource, destination under ~/.frago)``. A directory source seeds
#: every file it holds, one by one.
SEED_MAP: tuple[tuple[str, str], ...] = (
    ("book", "book"),
    ("constitution.md", "constitution.md"),
    ("agent-disciplines.md", "agent-disciplines.md"),
)


@dataclass
class SeedReport:
    written: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"seeded {len(self.written)} new, kept {len(self.kept)} existing, "
            f"{len(self.failed)} failed"
        )


def _copy_if_absent(src, dest: Path, report: SeedReport) -> None:
    if dest.exists():
        report.kept.append(str(dest))
        return
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as fh:
            fh.write(src.read_bytes())
        report.written.append(str(dest))
    except OSError as exc:
        logger.warning("failed to seed %s: %s", dest, exc)
        report.failed.append(str(dest))


def seed_user_resources(home: Path | None = None) -> SeedReport:
    """Lay down any packaged resource that is not present under ``~/.frago``."""
    root = home or FRAGO_HOME
    report = SeedReport()
    base = pkg_files("frago.resources")

    for rel_src, rel_dest in SEED_MAP:
        src = base / rel_src
        dest = root / rel_dest
        if src.is_dir():
            for child in src.iterdir():
                if child.is_file():
                    _copy_if_absent(child, dest / child.name, report)
        elif src.is_file():
            _copy_if_absent(src, dest, report)
        else:
            logger.warning("packaged resource missing: %s", rel_src)
            report.failed.append(rel_src)

    return report


def ensure_book_dir(home: Path | None = None) -> Path:
    """Return ``~/.frago/book``, seeding it first when it does not exist yet.

    The command-line tools read the book without going through the server, so
    seeding cannot live only in the server's startup path.
    """
    root = home or FRAGO_HOME
    book_dir = root / "book"
    if not book_dir.is_dir():
        seed_user_resources(root)
    return book_dir
