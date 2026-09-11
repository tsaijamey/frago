"""Tests for what an upgrade does to the editable text under ~/.frago.

The text the package ships — the book, the constitution, the hook prompts the
light AI runs on — exists on a machine only because this module put it there,
and it is meant to be edited in place. Two things must both hold: a new release's
wording has to reach a machine that already has the old file, and a hand edit
must never vanish without a copy left beside it. Whether it is an upgrade at all
comes from a manifest recording the version and the hash of each placed file, so
these cases are the states that record can be in.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

import pytest

from frago.init import user_resource_seed


@pytest.fixture
def shipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in for the wheel's ``frago/resources``: one directory of hook
    prompts, one book, and a loose file at the top."""
    root = tmp_path / "resources"
    (root / "hook").mkdir(parents=True)
    (root / "book").mkdir()
    (root / "hook" / "prompt.md").write_text("prompt v1\n", encoding="utf-8")
    (root / "book" / "one.md").write_text("book v1\n", encoding="utf-8")
    (root / "constitution.md").write_text("constitution v1\n", encoding="utf-8")
    (root / "agent-disciplines.md").write_text("disciplines v1\n", encoding="utf-8")
    monkeypatch.setattr(user_resource_seed, "pkg_files", lambda package: root)
    return root


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """The machine's ~/.frago. Never the real one."""
    return tmp_path / "home"


def install(shipped: Path, relative: str, text: str) -> None:
    """Change what the package ships, as a new release would."""
    (shipped / relative).write_text(text, encoding="utf-8")


def set_version(monkeypatch: pytest.MonkeyPatch, version: str) -> None:
    monkeypatch.setattr(user_resource_seed, "_package_version", lambda: version)


def read_manifest(home: Path) -> dict:
    return json.loads((home / ".seed-manifest.json").read_text(encoding="utf-8"))


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def backups_of(home: Path, relative: str) -> list[Path]:
    target = home / relative
    return sorted(target.parent.glob(target.name + ".bak-*"))


class TestAFreshMachine:
    def test_every_shipped_file_is_placed(
        self, shipped: Path, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        set_version(monkeypatch, "1.0.0")

        report = user_resource_seed.seed_user_resources(home)

        assert sorted(report.written) == sorted(
            [
                str(home / "hook" / "prompt.md"),
                str(home / "book" / "one.md"),
                str(home / "constitution.md"),
                str(home / "agent-disciplines.md"),
            ]
        )
        assert (home / "hook" / "prompt.md").read_text(encoding="utf-8") == "prompt v1\n"
        assert not report.failed

    def test_the_manifest_records_the_version_and_what_was_placed(
        self, shipped: Path, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        set_version(monkeypatch, "1.0.0")

        user_resource_seed.seed_user_resources(home)

        manifest = read_manifest(home)
        assert manifest["version"] == "1.0.0"
        assert manifest["files"] == {
            "hook/prompt.md": digest("prompt v1\n"),
            "book/one.md": digest("book v1\n"),
            "constitution.md": digest("constitution v1\n"),
            "agent-disciplines.md": digest("disciplines v1\n"),
        }


class TestTheSameVersion:
    """Nothing shipped since the last seed, so the disk is the user's."""

    def test_an_edit_made_between_two_upgrades_stays(
        self, shipped: Path, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        set_version(monkeypatch, "1.0.0")
        user_resource_seed.seed_user_resources(home)
        edited = home / "hook" / "prompt.md"
        edited.write_text("prompt v1\nmy own rule\n", encoding="utf-8")

        report = user_resource_seed.seed_user_resources(home)

        assert edited.read_text(encoding="utf-8") == "prompt v1\nmy own rule\n"
        assert str(edited) in report.kept
        assert not report.overwritten

    def test_a_second_start_rewrites_nothing(
        self, shipped: Path, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        set_version(monkeypatch, "1.0.0")
        user_resource_seed.seed_user_resources(home)
        before = (home / ".seed-manifest.json").read_bytes()

        report = user_resource_seed.seed_user_resources(home)

        assert (home / ".seed-manifest.json").read_bytes() == before
        assert not report.written
        assert not report.overwritten

    def test_the_edited_hash_is_not_recorded_as_the_packages(
        self, shipped: Path, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Recording the edited text would make the next upgrade read it as
        untouched and replace it without a backup."""
        set_version(monkeypatch, "1.0.0")
        user_resource_seed.seed_user_resources(home)
        (home / "hook" / "prompt.md").write_text("mine\n", encoding="utf-8")

        user_resource_seed.seed_user_resources(home)

        assert read_manifest(home)["files"]["hook/prompt.md"] == digest("prompt v1\n")


class TestAnUpgrade:
    def test_an_untouched_file_is_replaced_without_a_backup(
        self, shipped: Path, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        set_version(monkeypatch, "1.0.0")
        user_resource_seed.seed_user_resources(home)
        install(shipped, "hook/prompt.md", "prompt v2\n")
        set_version(monkeypatch, "2.0.0")

        report = user_resource_seed.seed_user_resources(home)

        assert (home / "hook" / "prompt.md").read_text(encoding="utf-8") == "prompt v2\n"
        assert str(home / "hook" / "prompt.md") in report.overwritten
        assert not report.backed_up
        assert backups_of(home, "hook/prompt.md") == []

    def test_an_edited_file_is_backed_up_before_it_is_replaced(
        self, shipped: Path, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        set_version(monkeypatch, "1.0.0")
        user_resource_seed.seed_user_resources(home)
        edited = home / "hook" / "prompt.md"
        edited.write_text("prompt v1\nmy own rule\n", encoding="utf-8")
        install(shipped, "hook/prompt.md", "prompt v2\n")
        set_version(monkeypatch, "2.0.0")

        report = user_resource_seed.seed_user_resources(home)

        assert edited.read_text(encoding="utf-8") == "prompt v2\n"
        [backup] = backups_of(home, "hook/prompt.md")
        assert backup.read_text(encoding="utf-8") == "prompt v1\nmy own rule\n"
        assert str(backup) in report.backed_up
        assert re.fullmatch(r"prompt\.md\.bak-1\.0\.0-\d{8}-\d{6}", backup.name)

    def test_the_log_says_where_the_backup_went(
        self,
        shipped: Path,
        home: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        set_version(monkeypatch, "1.0.0")
        user_resource_seed.seed_user_resources(home)
        (home / "hook" / "prompt.md").write_text("mine\n", encoding="utf-8")
        set_version(monkeypatch, "2.0.0")

        with caplog.at_level(logging.INFO, logger=user_resource_seed.__name__):
            user_resource_seed.seed_user_resources(home)

        [backup] = backups_of(home, "hook/prompt.md")
        assert str(backup) in caplog.text

    def test_a_file_the_package_did_not_change_is_left_alone(
        self, shipped: Path, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        set_version(monkeypatch, "1.0.0")
        user_resource_seed.seed_user_resources(home)
        set_version(monkeypatch, "2.0.0")

        report = user_resource_seed.seed_user_resources(home)

        assert str(home / "hook" / "prompt.md") in report.kept
        assert not report.overwritten
        assert backups_of(home, "hook/prompt.md") == []

    def test_a_file_added_by_the_new_release_arrives(
        self, shipped: Path, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        set_version(monkeypatch, "1.0.0")
        user_resource_seed.seed_user_resources(home)
        (shipped / "hook" / "stop.md").write_text("stop v2\n", encoding="utf-8")
        set_version(monkeypatch, "2.0.0")

        report = user_resource_seed.seed_user_resources(home)

        assert (home / "hook" / "stop.md").read_text(encoding="utf-8") == "stop v2\n"
        assert str(home / "hook" / "stop.md") in report.written

    def test_the_manifest_moves_to_the_new_version(
        self, shipped: Path, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        set_version(monkeypatch, "1.0.0")
        user_resource_seed.seed_user_resources(home)
        install(shipped, "hook/prompt.md", "prompt v2\n")
        set_version(monkeypatch, "2.0.0")

        user_resource_seed.seed_user_resources(home)

        manifest = read_manifest(home)
        assert manifest["version"] == "2.0.0"
        assert manifest["files"]["hook/prompt.md"] == digest("prompt v2\n")


class TestAMachineFromBeforeTheManifest:
    """Seeded by an older frago, so there is no record of what was placed."""

    def test_a_differing_file_is_backed_up_before_it_is_replaced(
        self, shipped: Path, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (home / "hook").mkdir(parents=True)
        (home / "hook" / "prompt.md").write_text("prompt v0\n", encoding="utf-8")
        set_version(monkeypatch, "2.0.0")

        report = user_resource_seed.seed_user_resources(home)

        assert (home / "hook" / "prompt.md").read_text(encoding="utf-8") == "prompt v1\n"
        [backup] = backups_of(home, "hook/prompt.md")
        assert backup.read_text(encoding="utf-8") == "prompt v0\n"
        assert re.fullmatch(r"prompt\.md\.bak-unknown-\d{8}-\d{6}", backup.name)
        assert str(backup) in report.backed_up

    def test_a_file_that_already_matches_the_package_is_not_touched(
        self, shipped: Path, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home.mkdir()
        (home / "constitution.md").write_text("constitution v1\n", encoding="utf-8")
        set_version(monkeypatch, "2.0.0")

        report = user_resource_seed.seed_user_resources(home)

        assert str(home / "constitution.md") in report.kept
        assert not report.backed_up
        assert backups_of(home, "constitution.md") == []

    def test_the_manifest_appears_with_this_run_on_it(
        self, shipped: Path, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home.mkdir()
        (home / "constitution.md").write_text("constitution v1\n", encoding="utf-8")
        set_version(monkeypatch, "2.0.0")

        user_resource_seed.seed_user_resources(home)

        assert read_manifest(home) == {
            "version": "2.0.0",
            "files": {
                "hook/prompt.md": digest("prompt v1\n"),
                "book/one.md": digest("book v1\n"),
                "constitution.md": digest("constitution v1\n"),
                "agent-disciplines.md": digest("disciplines v1\n"),
            },
        }


class TestOneBadFile:
    def test_the_other_files_are_still_seeded(
        self, shipped: Path, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A directory where a file belongs makes one destination unwritable.
        The server start this runs inside must survive it."""
        set_version(monkeypatch, "1.0.0")
        home.mkdir()
        (home / "book").write_text("not a directory\n", encoding="utf-8")

        report = user_resource_seed.seed_user_resources(home)

        assert report.failed == [str(home / "book" / "one.md")]
        assert (home / "hook" / "prompt.md").read_text(encoding="utf-8") == "prompt v1\n"
        assert (home / "constitution.md").read_text(encoding="utf-8") == "constitution v1\n"
        assert read_manifest(home)["files"]["constitution.md"] == digest(
            "constitution v1\n"
        )

    def test_a_corrupt_manifest_reads_as_an_upgrade_rather_than_stopping(
        self, shipped: Path, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (home / "hook").mkdir(parents=True)
        (home / "hook" / "prompt.md").write_text("prompt v0\n", encoding="utf-8")
        (home / ".seed-manifest.json").write_text("{ not json", encoding="utf-8")
        set_version(monkeypatch, "2.0.0")

        report = user_resource_seed.seed_user_resources(home)

        assert (home / "hook" / "prompt.md").read_text(encoding="utf-8") == "prompt v1\n"
        assert len(report.backed_up) == 1
        assert read_manifest(home)["version"] == "2.0.0"
