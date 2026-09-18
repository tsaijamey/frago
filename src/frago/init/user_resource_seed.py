"""Seed package-shipped knowledge into ``~/.frago`` so the user can edit it.

Two kinds of text ship inside the wheel: the book topics and the constitution.
Both are meant to be read *and changed* by the person running frago, and a file
inside site-packages is neither editable in practice nor survives an upgrade.
So the wheel carries the pristine copy and this module lays it down under
``~/.frago``.

The rule that matters, since 2026-09-11: **an upgrade replaces what the package
shipped, and a hand edit is never lost without a copy left behind.** Until then
an existing file was never overwritten. That sounded protective and was not:
the hook prompts the light AI runs on exist only here, so a machine that had
installed any older version kept that version's wording forever. Correcting a
prompt upstream changed nothing for anybody who already had the old file — the
new text simply could not arrive. What protects an edit is the backup, not a
refusal to write.

How the two are told apart. Next to the files it keeps
``~/.frago/.seed-manifest.json``: the version that last seeded this machine, and
the hash of each file as the package placed it. On every call:

* a file that is missing is placed — new files in a later release always arrive;
* the manifest's version is still the installed one: nothing is touched, so what
  the user changed between two upgrades stays;
* the version moved (*an upgrade*): each file is compared. Against the package,
  it is already current and stays. Against what the last seed placed, nobody has
  touched it and it is overwritten. Against neither, it was edited by hand: it is
  copied to ``<name>.bak-<old version>-<timestamp>`` in the same directory, the
  backup path is logged, and only then is it overwritten;
* there is no manifest (*a machine from before this existed*): the same as an
  upgrade, so anything differing from the package is backed up before it goes.

The manifest is written back at the end — the installed version plus the hash of
everything placed this time — so the next start can tell an edit from a stale
copy. A failure on one file is logged and that file skipped: the server start
this runs inside must not die over a text file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from importlib.resources import files as pkg_files
from pathlib import Path

logger = logging.getLogger(__name__)

FRAGO_HOME = Path.home() / ".frago"

#: Records the version that last seeded this machine and the hash of every file
#: as the package placed it. Absent on a machine that seeded before it existed.
MANIFEST_NAME = ".seed-manifest.json"

#: ``(package resource, destination under ~/.frago)``. A directory source seeds
#: every file it holds, one by one.
SEED_MAP: tuple[tuple[str, str], ...] = (
    ("book", "book"),
    ("constitution.md", "constitution.md"),
    ("agent-disciplines.md", "agent-disciplines.md"),
    # The hook engine's rules. They used to be compiled into the engine binary,
    # which meant every wording change cost a four-platform rebuild and put
    # editing them out of reach of anyone who does not write Rust. The engine
    # now reads them from here and carries no copy, so these files are the only
    # place they exist on a machine. Edits here survive an upgrade only as the
    # ``.bak-`` copy the upgrade leaves beside them — that copy is why a rewrite
    # is allowed at all.
    #
    # Directory to directory, same name on both sides: the wheel's layout and
    # the machine's layout are the one thing a reader should not have to hold
    # two versions of in their head.
    ("hook", "hook"),
    # CoreAgent's instructions — what it is told when frago calls it for a job
    # of its own, such as deciding what an outside command a recipe declared
    # may see on this machine. Read by name from ``~/.frago/coreagent/``, so
    # they have to be there on a machine nobody has written them onto.
    ("coreagent", "coreagent"),
)


@dataclass
class SeedReport:
    """What one seeding pass did, file by file."""

    written: list[str] = field(default_factory=list)
    overwritten: list[str] = field(default_factory=list)
    backed_up: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"seeded {len(self.written)} new", f"replaced {len(self.overwritten)}"]
        if self.backed_up:
            parts.append(f"backed up {len(self.backed_up)} edited")
        parts.append(f"kept {len(self.kept)}")
        parts.append(f"{len(self.failed)} failed")
        return ", ".join(parts)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _package_version() -> str:
    """The installed frago version, or ``"unknown"`` when it cannot be read.

    A machine whose version cannot be determined is still seeded; it just
    compares equal to whatever the manifest recorded, so nothing gets touched.
    """
    try:
        from importlib.metadata import version

        return version("frago-cli")
    except Exception:  # pragma: no cover - only a broken install reaches this
        logger.debug("could not read the installed frago version", exc_info=True)
        return "unknown"


def _backup_of(dest: Path, version: str | None) -> Path:
    """``<name>.bak-<old version>-<timestamp>``, beside the file it copies."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    tag = "".join(c if c.isalnum() or c in ".-" else "_" for c in (version or "unknown"))
    return dest.with_name(f"{dest.name}.bak-{tag}-{stamp}")


def _place(
    src,
    dest: Path,
    *,
    recorded_hash: str | None,
    version_changed: bool,
    old_version: str | None,
    report: SeedReport,
) -> str | None:
    """Put one packaged file where it belongs; return the hash to record.

    ``None`` means the file is not on disk in the package's shape, so the caller
    keeps whatever the manifest said about it.
    """
    content = src.read_bytes()
    digest = _sha256(content)

    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        report.written.append(str(dest))
        return digest

    if not version_changed:
        # Nothing shipped since this machine was last seeded — what is on disk is
        # the user's, edits and all.
        report.kept.append(str(dest))
        return recorded_hash

    on_disk = dest.read_bytes()
    if _sha256(on_disk) == digest:
        report.kept.append(str(dest))
        return digest

    if recorded_hash is not None and _sha256(on_disk) == recorded_hash:
        dest.write_bytes(content)
        report.overwritten.append(str(dest))
        return digest

    # Neither the package's copy nor the one we placed: somebody edited this.
    # The backup is the whole reason this branch may write at all.
    backup = _backup_of(dest, old_version)
    shutil.copy2(dest, backup)
    dest.write_bytes(content)
    report.backed_up.append(str(backup))
    report.overwritten.append(str(dest))
    logger.info("replaced hand-edited %s; the previous copy is at %s", dest, backup)
    return digest


def _read_manifest(path: Path) -> dict | None:
    """The manifest, or ``None`` — which reads as "treat this as an upgrade"."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning(
            "seed manifest %s is unreadable (%s); every file will be treated as "
            "hand-edited, so anything the package changed gets backed up first",
            path,
            exc,
        )
        return None
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("version"), str)
        or not isinstance(payload.get("files"), dict)
    ):
        logger.warning("seed manifest %s is not shaped like one; ignoring it", path)
        return None
    files = {k: v for k, v in payload["files"].items() if isinstance(v, str)}
    return {"version": payload["version"], "files": files}


def _write_manifest(path: Path, version: str, files_now: dict[str, str]) -> None:
    payload = {"version": version, "files": files_now}
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        # A manifest that cannot be written only means the next start cannot tell
        # an edit from a stale copy, and will back files up before replacing them.
        logger.warning("failed to write the seed manifest %s: %s", path, exc)


def _pairs(base, rel_src: str, rel_dest: str) -> list[tuple[object, str]]:
    """``(packaged file, destination key)`` for one entry of :data:`SEED_MAP`."""
    src = base / rel_src
    if src.is_dir():
        return [
            (child, f"{rel_dest}/{child.name}")
            for child in sorted(src.iterdir(), key=lambda c: c.name)
            if child.is_file()
        ]
    if src.is_file():
        return [(src, rel_dest)]
    return []


def seed_user_resources(home: Path | None = None) -> SeedReport:
    """Bring the resources under ``~/.frago`` in line with the installed package."""
    root = home or FRAGO_HOME
    report = SeedReport()
    version = _package_version()

    manifest_path = root / MANIFEST_NAME
    manifest = _read_manifest(manifest_path)
    recorded: dict[str, str] = dict(manifest["files"]) if manifest else {}
    old_version = manifest["version"] if manifest else None
    version_changed = old_version != version

    base = pkg_files("frago.resources")
    files_now: dict[str, str] = {}

    for rel_src, rel_dest in SEED_MAP:
        pairs = _pairs(base, rel_src, rel_dest)
        if not pairs:
            logger.warning("packaged resource missing: %s", rel_src)
            report.failed.append(rel_src)
            continue
        for child, key in pairs:
            dest = root / key
            try:
                digest = _place(
                    child,
                    dest,
                    recorded_hash=recorded.get(key),
                    version_changed=version_changed,
                    old_version=old_version,
                    report=report,
                )
            except Exception as exc:
                logger.warning("failed to seed %s: %s", dest, exc)
                report.failed.append(str(dest))
                digest = None
            if digest is None and key in recorded:
                # Nothing of this pass is on disk here, so the last placed copy is
                # still there. Keeping its hash is what lets the next upgrade
                # replace it outright instead of backing up an unedited file.
                digest = recorded[key]
            if digest is not None:
                files_now[key] = digest

    if version != old_version or files_now != recorded:
        _write_manifest(manifest_path, version, files_now)

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
