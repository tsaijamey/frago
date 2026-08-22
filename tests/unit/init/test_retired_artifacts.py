"""Tests for collecting what older frago versions left inside ~/.claude/.

The leftovers differ by install date, not by operating system — everything frago
wrote went under the user's home — so the cases here are about the *shapes* a
machine can be in: which generation installed it, which platform wrote the
registration line, and what else of the user's lives in the same directories.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from frago.init import retired_artifacts


@pytest.fixture
def claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A disposable ~/.claude/ with settings.json wired to it."""
    from frago.init import configurator

    root = tmp_path / ".claude"
    (root / "hooks" / "frago").mkdir(parents=True)
    (root / "commands").mkdir()
    (root / "skills").mkdir()
    monkeypatch.setattr(retired_artifacts, "get_claude_dir", lambda: root)
    monkeypatch.setattr(configurator, "CLAUDE_SETTINGS_PATH", root / "settings.json")
    return root


def write_settings(claude: Path, payload: dict) -> None:
    (claude / "settings.json").write_text(json.dumps(payload), encoding="utf-8")


def read_settings(claude: Path) -> dict:
    return json.loads((claude / "settings.json").read_text(encoding="utf-8"))


def hook_entry(command: str, timeout: int = 10) -> dict:
    return {"matcher": "", "hooks": [{"type": "command", "command": command, "timeout": timeout}]}


CURRENT_HOOK = "/home/me/.frago/bin/frago-core --engine"


class TestTheHookScript:
    def test_unregisters_then_deletes(self, claude: Path) -> None:
        script = claude / "hooks" / "frago" / "session-start-book.sh"
        script.write_text("#!/bin/bash\n")
        write_settings(claude, {"hooks": {"SessionStart": [
            hook_entry(f'bash "{script}"'),
            hook_entry(CURRENT_HOOK, timeout=20),
        ]}})

        removed = retired_artifacts.retire_superseded_install_artifacts()

        assert not script.exists()
        assert str(script) in removed
        groups = read_settings(claude)["hooks"]["SessionStart"]
        assert [g["hooks"][0]["command"] for g in groups] == [CURRENT_HOOK]

    def test_the_windows_registration_is_the_same_registration(
        self, claude: Path
    ) -> None:
        """Claude Code on Windows runs hooks through Git Bash.

        The line reads ``bash "C:\\Users\\me\\...\\session-start-book.sh"`` —
        different quoting, different separators, different install prefix from
        every POSIX machine. Matching on the filename is what makes one rule
        cover all three platforms; matching on the path would have covered none
        of them.
        """
        write_settings(claude, {"hooks": {"SessionStart": [
            hook_entry('bash "C:\\Users\\me\\.claude\\hooks\\frago\\session-start-book.sh"'),
        ]}})

        retired_artifacts.retire_superseded_install_artifacts()

        assert read_settings(claude)["hooks"] == {}

    def test_the_oldest_generation_registered_a_path_inside_the_package(
        self, claude: Path
    ) -> None:
        """The first generation (2026-03-30) pointed settings.json into
        site-packages instead of ~/.claude/.

        On those machines the wheel upgrade deleted the script back in April and
        the registration stayed — a hook that has failed on every session start
        since. There is no file left to delete here; unregistering is the whole
        repair, and it must not depend on finding one.
        """
        write_settings(claude, {"hooks": {"SessionStart": [
            hook_entry(
                'bash "/home/me/.local/share/uv/tools/frago-cli/lib/python3.12/'
                'site-packages/frago/resources/hooks/session-start-book.sh"'
            ),
        ]}})

        removed = retired_artifacts.retire_superseded_install_artifacts()

        assert read_settings(claude)["hooks"] == {}
        assert removed  # the repair is reported even with no file to delete

    def test_both_generations_at_once(self, claude: Path) -> None:
        """Upgrading did not unregister the old line before adding the new one."""
        script = claude / "hooks" / "frago" / "session-start-book.sh"
        script.write_text("#!/bin/bash\n")
        write_settings(claude, {"hooks": {"SessionStart": [
            hook_entry('bash "/site-packages/frago/resources/hooks/session-start-book.sh"'),
            hook_entry(f'bash "{script}"'),
            hook_entry(CURRENT_HOOK, timeout=20),
        ]}})

        retired_artifacts.retire_superseded_install_artifacts()

        groups = read_settings(claude)["hooks"]["SessionStart"]
        assert [g["hooks"][0]["command"] for g in groups] == [CURRENT_HOOK]

    def test_the_emptied_legacy_directory_goes_too(self, claude: Path) -> None:
        (claude / "hooks" / "frago" / "session-start-book.sh").write_text("#!/bin/bash\n")

        retired_artifacts.retire_superseded_install_artifacts()

        assert not (claude / "hooks" / "frago").exists()

    def test_a_windows_binary_still_sitting_there_keeps_the_directory(
        self, claude: Path
    ) -> None:
        """~/.claude/hooks/frago/ also held frago-hook.exe on Windows.

        The binary is swept by ``deploy_hook_binary``, which the server runs
        first. If the order ever slips, the directory survives rather than the
        sweep raising — and the next start collects it.
        """
        hooks_dir = claude / "hooks" / "frago"
        (hooks_dir / "session-start-book.sh").write_text("#!/bin/bash\n")
        (hooks_dir / "frago-hook.exe").write_bytes(b"old")

        retired_artifacts.retire_superseded_install_artifacts()

        assert hooks_dir.exists()
        assert (hooks_dir / "frago-hook.exe").exists()

    def test_other_hooks_and_settings_survive(self, claude: Path) -> None:
        """This file is the user's. Retiring ours must not touch anything else."""
        (claude / "hooks" / "frago" / "session-start-book.sh").write_text("#!/bin/bash\n")
        write_settings(claude, {
            "hooks": {
                "SessionStart": [hook_entry('bash "~/.claude/hooks/frago/session-start-book.sh"')],
                "Stop": [hook_entry("~/bell.sh", timeout=5)],
            },
            "model": "opus",
            "permissions": {"allow": ["Bash(ls:*)"]},
        })

        retired_artifacts.retire_superseded_install_artifacts()

        saved = read_settings(claude)
        assert "SessionStart" not in saved["hooks"]
        assert saved["hooks"]["Stop"][0]["hooks"][0]["command"] == "~/bell.sh"
        assert saved["model"] == "opus"
        assert saved["permissions"] == {"allow": ["Bash(ls:*)"]}


class TestTheSlashCommands:
    """Installed into ~/.claude/commands/ on every run until 2026-04-06.

    They are still in the slash menu of every machine installed before that, and
    the rules they carry predate both `frago book` and the hook rule engine.
    """

    def test_removes_the_commands_and_their_support_tree(self, claude: Path) -> None:
        commands = claude / "commands"
        for name in ("frago.agent.md", "frago.recipe.md", "frago.run.md",
                     "frago.skill.md", "frago.test.md", "frago.do.md", "frago.exec.md"):
            (commands / name).write_text("# old\n")
        tree = commands / "frago"
        (tree / "rules").mkdir(parents=True)
        (tree / "COMMON.md").write_text("# old\n")
        (tree / "rules" / "TOOL_PRIORITY.md").write_text("# old\n")

        retired_artifacts.retire_superseded_install_artifacts()

        assert list(commands.iterdir()) == []

    def test_the_users_own_commands_are_not_frago_s_to_remove(
        self, claude: Path
    ) -> None:
        commands = claude / "commands"
        (commands / "frago.recipe.md").write_text("# old\n")
        mine = commands / "sys.chrome.md"
        mine.write_text("# mine\n")
        also_mine = commands / "frago-notes.md"  # frago-ish name, never shipped
        also_mine.write_text("# mine\n")

        retired_artifacts.retire_superseded_install_artifacts()

        assert not (commands / "frago.recipe.md").exists()
        assert mine.exists()
        assert also_mine.exists()

    def test_the_commands_directory_itself_stays(self, claude: Path) -> None:
        """It is Claude Code's, not frago's — empty is fine, missing is not."""
        (claude / "commands" / "frago.run.md").write_text("# old\n")

        retired_artifacts.retire_superseded_install_artifacts()

        assert (claude / "commands").is_dir()


class TestTheSkills:
    """Installed into ~/.claude/skills/ until 2026-04-23, and only when absent."""

    def test_removes_the_shipped_skills(self, claude: Path) -> None:
        skills = claude / "skills"
        for name in ("frago-previewable-content", "frago-x-extract-tweet-with-comments"):
            (skills / name).mkdir()
            (skills / name / "SKILL.md").write_text("# old\n")

        retired_artifacts.retire_superseded_install_artifacts()

        assert list(skills.iterdir()) == []

    def test_a_directory_without_a_skill_file_is_not_the_one_frago_shipped(
        self, claude: Path
    ) -> None:
        """The name alone is not proof. Whatever this is, frago did not write it."""
        squatter = claude / "skills" / "frago-previewable-content"
        squatter.mkdir()
        (squatter / "notes.md").write_text("# mine\n")

        retired_artifacts.retire_superseded_install_artifacts()

        assert squatter.exists()

    def test_skills_frago_never_shipped_are_left_alone(self, claude: Path) -> None:
        mine = claude / "skills" / "frago-my-own-thing"
        mine.mkdir()
        (mine / "SKILL.md").write_text("# mine\n")

        retired_artifacts.retire_superseded_install_artifacts()

        assert mine.exists()


class TestTheWindowsReadOnlyFile:
    """Windows refuses to delete a read-only file.

    The old installer copied these with ``copy2`` — mode and all — so one
    read-only file inside a retired skill would abort the whole directory and
    leave the machine half-swept, with no way to finish on the next run either.
    """

    def test_the_bit_is_cleared_and_the_delete_retried(self, tmp_path: Path) -> None:
        victim = tmp_path / "SKILL.md"
        victim.write_text("# old\n")
        attempts: list[Path] = []

        def remove(path):
            attempts.append(Path(path))
            if len(attempts) == 1:
                raise PermissionError(13, "Access is denied")

        retired_artifacts._clear_read_only(
            remove, str(victim), PermissionError(13, "Access is denied")
        )

        assert len(attempts) == 1  # the retry inside the hook is the second call
        assert victim.exists()  # `remove` is a stub; the point is that it was retried

    def test_any_other_failure_is_not_swallowed(self, tmp_path: Path) -> None:
        """A directory that will not delete for some other reason is a real
        problem, and hiding it would make the sweep silently incomplete."""
        with pytest.raises(FileNotFoundError):
            retired_artifacts._clear_read_only(
                lambda p: None, str(tmp_path / "gone"), FileNotFoundError(2, "nope")
            )


class TestTheSweepAsAWhole:
    def test_a_clean_machine_is_the_steady_state(self, claude: Path) -> None:
        assert retired_artifacts.retire_superseded_install_artifacts() == []
        assert not (claude / "settings.json").exists()  # nothing removed → nothing written

    def test_is_idempotent(self, claude: Path) -> None:
        """It runs on every server start, so the second run has to be silent."""
        (claude / "hooks" / "frago" / "session-start-book.sh").write_text("#!/bin/bash\n")
        (claude / "commands" / "frago.run.md").write_text("# old\n")
        skill = claude / "skills" / "frago-previewable-content"
        skill.mkdir()
        (skill / "SKILL.md").write_text("# old\n")
        write_settings(claude, {"hooks": {"SessionStart": [
            hook_entry('bash "~/.claude/hooks/frago/session-start-book.sh"'),
        ]}})

        assert retired_artifacts.retire_superseded_install_artifacts()
        after_first = read_settings(claude)

        assert retired_artifacts.retire_superseded_install_artifacts() == []
        assert read_settings(claude) == after_first

    def test_an_unreadable_settings_file_does_not_stop_the_file_sweep(
        self, claude: Path
    ) -> None:
        """A corrupt settings.json must not cost the user the rest of the cleanup —
        nor fail the server start it runs inside."""
        (claude / "settings.json").write_text("{ not json", encoding="utf-8")
        (claude / "commands" / "frago.run.md").write_text("# old\n")

        retired_artifacts.retire_superseded_install_artifacts()

        assert not (claude / "commands" / "frago.run.md").exists()
