"""Tests for workspace resource management."""

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from frago.tools.workspace import (
    CollectResult,
    MIGRATION_FLAG,
    ProjectInfo,
    WorkspaceChangeItem,
    WorkspaceChanges,
    _collect_project_workspace,
    _collect_system_workspace,
    _discover_projects,
    _encode_project_path,
    _encoded_to_readable_name,
    _is_excluded,
    _sync_dir,
    _sync_file,
    canonical_id_to_dirname,
    collect_workspaces,
    detect_workspace_changes,
    get_canonical_id,
    migrate_legacy_claude_dir,
    normalize_git_url,
    summarize_workspace_changes,
)


# =============================================================================
# normalize_git_url
# =============================================================================


class TestNormalizeGitUrl:
    def test_https_with_git_suffix(self):
        assert normalize_git_url("https://github.com/user/repo.git") == "github.com/user/repo"

    def test_https_without_git_suffix(self):
        assert normalize_git_url("https://github.com/user/repo") == "github.com/user/repo"

    def test_ssh_format(self):
        assert normalize_git_url("git@github.com:user/repo.git") == "github.com/user/repo"

    def test_ssh_without_git_suffix(self):
        assert normalize_git_url("git@github.com:user/repo") == "github.com/user/repo"

    def test_whitespace_stripped(self):
        assert normalize_git_url("  https://github.com/u/r.git  ") == "github.com/u/r"

    def test_non_github_https(self):
        assert normalize_git_url("https://gitlab.com/org/project.git") == "gitlab.com/org/project"

    def test_non_github_ssh(self):
        assert normalize_git_url("git@gitlab.com:org/project.git") == "gitlab.com/org/project"

    def test_nested_path(self):
        assert normalize_git_url("https://github.com/org/sub/repo.git") == "github.com/org/sub/repo"


# =============================================================================
# canonical_id_to_dirname
# =============================================================================


class TestCanonicalIdToDirname:
    def test_simple(self):
        assert canonical_id_to_dirname("github.com/user/repo") == "github.com__user__repo"

    def test_nested(self):
        assert canonical_id_to_dirname("gitlab.com/org/sub/proj") == "gitlab.com__org__sub__proj"


# =============================================================================
# _encode_project_path
# =============================================================================


class TestEncodeProjectPath:
    def test_standard_path(self):
        assert _encode_project_path(Path("/Users/frago/Repos/frago")) == "-Users-frago-Repos-frago"

    def test_root_path(self):
        assert _encode_project_path(Path("/tmp")) == "-tmp"


# =============================================================================
# _encoded_to_readable_name
# =============================================================================


class TestEncodedToReadableName:
    def test_home_directory(self):
        home = Path.home()
        encoded = "-" + str(home).lstrip("/").replace("/", "-")
        assert _encoded_to_readable_name(encoded) == "home"

    def test_subdirectory_of_home(self):
        home = Path.home()
        encoded = "-" + str(home / "Repos").lstrip("/").replace("/", "-")
        result = _encoded_to_readable_name(encoded)
        assert "repos" in result.lower()


# =============================================================================
# _is_excluded
# =============================================================================


class TestIsExcluded:
    def test_exact_match(self):
        assert _is_excluded(Path("node_modules"), ["node_modules"])

    def test_dotfile(self):
        assert _is_excluded(Path(".venv"), [".venv"])

    def test_no_match(self):
        assert not _is_excluded(Path("myproject"), ["node_modules", ".venv"])

    def test_empty_patterns(self):
        assert not _is_excluded(Path("anything"), [])


# =============================================================================
# _sync_file
# =============================================================================


class TestSyncFile:
    def test_copy_new_file(self, tmp_path):
        src = tmp_path / "src" / "test.txt"
        src.parent.mkdir()
        src.write_text("hello")
        dst = tmp_path / "dst" / "test.txt"

        assert _sync_file(src, dst)
        assert dst.read_text() == "hello"

    def test_skip_identical(self, tmp_path):
        src = tmp_path / "src" / "test.txt"
        src.parent.mkdir()
        src.write_text("hello")
        dst = tmp_path / "dst" / "test.txt"
        dst.parent.mkdir()
        dst.write_text("hello")

        assert not _sync_file(src, dst)

    def test_update_different(self, tmp_path):
        src = tmp_path / "src" / "test.txt"
        src.parent.mkdir()
        src.write_text("new content")
        dst = tmp_path / "dst" / "test.txt"
        dst.parent.mkdir()
        dst.write_text("old content")

        assert _sync_file(src, dst)
        assert dst.read_text() == "new content"

    def test_nonexistent_source(self, tmp_path):
        src = tmp_path / "nonexistent"
        dst = tmp_path / "dst" / "test.txt"
        assert not _sync_file(src, dst)


# =============================================================================
# _sync_dir
# =============================================================================


class TestSyncDir:
    def test_copy_directory(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("aaa")
        (src / "b.txt").write_text("bbb")

        dst = tmp_path / "dst"
        assert _sync_dir(src, dst)
        assert (dst / "a.txt").read_text() == "aaa"
        assert (dst / "b.txt").read_text() == "bbb"

    def test_delete_removed_files(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "keep.txt").write_text("keep")

        dst = tmp_path / "dst"
        dst.mkdir()
        (dst / "keep.txt").write_text("keep")
        (dst / "remove.txt").write_text("remove me")

        _sync_dir(src, dst)
        assert (dst / "keep.txt").exists()
        assert not (dst / "remove.txt").exists()

    def test_exclude_names(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "include.txt").write_text("yes")
        (src / "settings.local.json").write_text("no")

        dst = tmp_path / "dst"
        _sync_dir(src, dst, exclude_names={"settings.local.json"})

        assert (dst / "include.txt").exists()
        assert not (dst / "settings.local.json").exists()

    def test_nonexistent_source(self, tmp_path):
        assert not _sync_dir(tmp_path / "nonexistent", tmp_path / "dst")

    def test_nested_directories(self, tmp_path):
        src = tmp_path / "src"
        (src / "sub").mkdir(parents=True)
        (src / "sub" / "file.txt").write_text("nested")

        dst = tmp_path / "dst"
        _sync_dir(src, dst)
        assert (dst / "sub" / "file.txt").read_text() == "nested"

    def test_file_symlink_resolved_to_content(self, tmp_path):
        """File symlinks ARE resolved and copied as real content (per
        _sync_dir contract). Directory symlinks are NOT — see next test."""
        real_file = tmp_path / "real.txt"
        real_file.write_text("real content")

        src = tmp_path / "src"
        src.mkdir()
        (src / "linked.txt").symlink_to(real_file)

        dst = tmp_path / "dst"
        _sync_dir(src, dst)

        assert (dst / "linked.txt").read_text() == "real content"
        assert not (dst / "linked.txt").is_symlink()

    def test_dir_symlink_skipped(self, tmp_path):
        """Directory symlinks are intentionally skipped (prevents loops +
        escape out of the source tree). The link must NOT appear in dst."""
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        (real_dir / "data.txt").write_text("real content")

        src = tmp_path / "src"
        src.mkdir()
        (src / "linked").symlink_to(real_dir, target_is_directory=True)

        dst = tmp_path / "dst"
        _sync_dir(src, dst)

        assert not (dst / "linked").exists()


# =============================================================================
# _discover_projects
# =============================================================================


class TestDiscoverProjects:
    def test_finds_git_projects(self, tmp_path):
        project = tmp_path / "myproject"
        project.mkdir()
        (project / ".git").mkdir()

        projects = _discover_projects([str(tmp_path)], [])
        assert len(projects) == 1
        assert projects[0].path == project

    def test_finds_claude_projects(self, tmp_path):
        project = tmp_path / "myproject"
        project.mkdir()
        (project / ".claude").mkdir()

        projects = _discover_projects([str(tmp_path)], [])
        assert len(projects) == 1

    def test_skips_excluded(self, tmp_path):
        project = tmp_path / "node_modules"
        project.mkdir()
        (project / ".git").mkdir()

        projects = _discover_projects([str(tmp_path)], ["node_modules"])
        assert len(projects) == 0

    def test_skips_plain_directories(self, tmp_path):
        (tmp_path / "plain_dir").mkdir()
        projects = _discover_projects([str(tmp_path)], [])
        assert len(projects) == 0

    def test_nonexistent_root(self):
        projects = _discover_projects(["/nonexistent/path"], [])
        assert len(projects) == 0

    def test_multiple_roots(self, tmp_path):
        root1 = tmp_path / "root1"
        root2 = tmp_path / "root2"
        root1.mkdir()
        root2.mkdir()

        p1 = root1 / "proj1"
        p1.mkdir()
        (p1 / ".git").mkdir()

        p2 = root2 / "proj2"
        p2.mkdir()
        (p2 / ".git").mkdir()

        projects = _discover_projects([str(root1), str(root2)], [])
        assert len(projects) == 2

    def test_expanduser(self, tmp_path):
        # Should handle ~ in paths
        projects = _discover_projects(["~/nonexistent_test_dir_xyz"], [])
        assert len(projects) == 0  # Just shouldn't crash


# =============================================================================
# get_canonical_id
# =============================================================================


class TestGetCanonicalId:
    def test_no_git_dir(self, tmp_path):
        assert get_canonical_id(tmp_path) is None

    def test_with_git_remote(self, tmp_path):
        # Create a git repo with a remote
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "remote", "add", "origin",
             "https://github.com/test/repo.git"],
            capture_output=True, check=True
        )
        assert get_canonical_id(tmp_path) == "github.com/test/repo"


# =============================================================================
# _collect_system_workspace
# =============================================================================


class TestCollectSystemWorkspace:
    def test_collects_claude_md(self, tmp_path, monkeypatch):
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (claude_home / "CLAUDE.md").write_text("# My rules")

        system_ws = tmp_path / "workspaces" / "__system__"

        monkeypatch.setattr("frago.tools.workspace.CLAUDE_HOME", claude_home)
        monkeypatch.setattr("frago.tools.workspace.SYSTEM_WORKSPACE", system_ws)

        _collect_system_workspace(set())

        assert (system_ws / "CLAUDE.md").read_text() == "# My rules"

    def test_collects_skills(self, tmp_path, monkeypatch):
        claude_home = tmp_path / ".claude"
        skills = claude_home / "skills" / "my-skill"
        skills.mkdir(parents=True)
        (skills / "skill.md").write_text("skill content")

        system_ws = tmp_path / "workspaces" / "__system__"

        monkeypatch.setattr("frago.tools.workspace.CLAUDE_HOME", claude_home)
        monkeypatch.setattr("frago.tools.workspace.SYSTEM_WORKSPACE", system_ws)

        _collect_system_workspace(set())

        assert (system_ws / "skills" / "my-skill" / "skill.md").read_text() == "skill content"

    def test_collects_commands(self, tmp_path, monkeypatch):
        claude_home = tmp_path / ".claude"
        cmds = claude_home / "commands" / "mygroup"
        cmds.mkdir(parents=True)
        (cmds / "cmd.md").write_text("command")

        system_ws = tmp_path / "workspaces" / "__system__"

        monkeypatch.setattr("frago.tools.workspace.CLAUDE_HOME", claude_home)
        monkeypatch.setattr("frago.tools.workspace.SYSTEM_WORKSPACE", system_ws)

        _collect_system_workspace(set())

        assert (system_ws / "commands" / "mygroup" / "cmd.md").read_text() == "command"


# =============================================================================
# _collect_project_workspace
# =============================================================================


class TestCollectProjectWorkspace:
    def test_collects_project_claude_dir(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        project.mkdir()
        claude_dir = project / ".claude"
        claude_dir.mkdir()
        (claude_dir / "CLAUDE.md").write_text("project rules")
        docs = claude_dir / "docs"
        docs.mkdir()
        (docs / "arch.md").write_text("architecture")

        ws = tmp_path / "workspaces"
        monkeypatch.setattr("frago.tools.workspace.WORKSPACES_DIR", ws)
        monkeypatch.setattr("frago.tools.workspace.CLAUDE_HOME", tmp_path / ".claude")

        _collect_project_workspace(
            ProjectInfo(path=project),
            "github.com/user/project",
        )

        target = ws / "github.com__user__project"
        assert (target / ".claude" / "CLAUDE.md").read_text() == "project rules"
        assert (target / ".claude" / "docs" / "arch.md").read_text() == "architecture"

    def test_excludes_device_specific_files(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        project.mkdir()
        claude_dir = project / ".claude"
        claude_dir.mkdir()
        (claude_dir / "CLAUDE.md").write_text("rules")
        (claude_dir / "settings.local.json").write_text("{}")
        (claude_dir / ".mcp.local.json").write_text("{}")

        ws = tmp_path / "workspaces"
        monkeypatch.setattr("frago.tools.workspace.WORKSPACES_DIR", ws)
        monkeypatch.setattr("frago.tools.workspace.CLAUDE_HOME", tmp_path / ".claude")

        _collect_project_workspace(
            ProjectInfo(path=project),
            "github.com/user/project",
        )

        target = ws / "github.com__user__project" / ".claude"
        assert (target / "CLAUDE.md").exists()
        assert not (target / "settings.local.json").exists()
        assert not (target / ".mcp.local.json").exists()

    def test_collects_project_memory(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        project.mkdir()

        # Create Claude Code memory for this project
        claude_home = tmp_path / ".claude"
        encoded = _encode_project_path(project)
        memory_dir = claude_home / "projects" / encoded / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "MEMORY.md").write_text("project memory")

        ws = tmp_path / "workspaces"
        monkeypatch.setattr("frago.tools.workspace.WORKSPACES_DIR", ws)
        monkeypatch.setattr("frago.tools.workspace.CLAUDE_HOME", claude_home)

        result = _collect_project_workspace(
            ProjectInfo(path=project),
            "github.com/user/project",
        )

        assert result == encoded
        target = ws / "github.com__user__project"
        assert (target / ".project-memory" / "MEMORY.md").read_text() == "project memory"

    def test_collects_hooks_agents_rules(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        project.mkdir()
        claude_dir = project / ".claude"
        claude_dir.mkdir()

        # hooks
        (claude_dir / "hooks").mkdir()
        (claude_dir / "hooks" / "check.sh").write_text("#!/bin/bash")

        # agents
        (claude_dir / "agents").mkdir()
        (claude_dir / "agents" / "reviewer.md").write_text("agent def")

        # rules
        (claude_dir / "rules").mkdir()
        (claude_dir / "rules" / "no-debug.md").write_text("rule")

        ws = tmp_path / "workspaces"
        monkeypatch.setattr("frago.tools.workspace.WORKSPACES_DIR", ws)
        monkeypatch.setattr("frago.tools.workspace.CLAUDE_HOME", tmp_path / ".claude")

        _collect_project_workspace(
            ProjectInfo(path=project),
            "github.com/user/project",
        )

        target = ws / "github.com__user__project" / ".claude"
        assert (target / "hooks" / "check.sh").exists()
        assert (target / "agents" / "reviewer.md").exists()
        assert (target / "rules" / "no-debug.md").exists()


# =============================================================================
# migrate_legacy_claude_dir
# =============================================================================


class TestMigrateLegacyClaudeDir:
    def test_migrates_skills(self, tmp_path, monkeypatch):
        frago_home = tmp_path / ".frago"
        frago_home.mkdir()
        legacy = frago_home / ".claude"
        skills = legacy / "skills" / "frago-test"
        skills.mkdir(parents=True)
        (skills / "skill.md").write_text("test skill")

        monkeypatch.setattr("frago.tools.workspace.FRAGO_HOME", frago_home)
        monkeypatch.setattr("frago.tools.workspace.SYSTEM_WORKSPACE",
                          frago_home / "workspaces" / "__system__")
        monkeypatch.setattr("frago.tools.workspace.MIGRATION_FLAG",
                          frago_home / ".workspace_migrated")

        assert migrate_legacy_claude_dir()

        # Legacy should be gone
        assert not legacy.exists()
        # New location should have the skill
        assert (frago_home / "workspaces" / "__system__" / "skills" / "frago-test" / "skill.md").exists()
        # Flag file should exist
        assert (frago_home / ".workspace_migrated").exists()

    def test_no_migration_if_no_legacy(self, tmp_path, monkeypatch):
        frago_home = tmp_path / ".frago"
        frago_home.mkdir()

        monkeypatch.setattr("frago.tools.workspace.FRAGO_HOME", frago_home)
        monkeypatch.setattr("frago.tools.workspace.SYSTEM_WORKSPACE",
                          frago_home / "workspaces" / "__system__")
        monkeypatch.setattr("frago.tools.workspace.MIGRATION_FLAG",
                          frago_home / ".workspace_migrated")

        assert not migrate_legacy_claude_dir()
        # Flag should still be written (no legacy = nothing to do = mark done)
        assert (frago_home / ".workspace_migrated").exists()

    def test_no_migration_if_already_migrated(self, tmp_path, monkeypatch):
        """Even if legacy dir and target both exist, flag prevents re-migration."""
        frago_home = tmp_path / ".frago"
        frago_home.mkdir()
        legacy = frago_home / ".claude"
        legacy.mkdir()
        flag = frago_home / ".workspace_migrated"
        flag.write_text("migrated")

        monkeypatch.setattr("frago.tools.workspace.FRAGO_HOME", frago_home)
        monkeypatch.setattr("frago.tools.workspace.SYSTEM_WORKSPACE",
                          frago_home / "workspaces" / "__system__")
        monkeypatch.setattr("frago.tools.workspace.MIGRATION_FLAG", flag)

        assert not migrate_legacy_claude_dir()
        # Legacy should NOT be deleted (already migrated)
        assert legacy.exists()

    def test_migrates_even_if_target_exists(self, tmp_path, monkeypatch):
        """If collect ran before migration, migration should still clean up legacy."""
        frago_home = tmp_path / ".frago"
        frago_home.mkdir()
        legacy = frago_home / ".claude"
        skills = legacy / "skills" / "frago-test"
        skills.mkdir(parents=True)
        (skills / "skill.md").write_text("test skill")

        # Simulate: collect already created target with skills
        target = frago_home / "workspaces" / "__system__"
        target_skills = target / "skills" / "frago-test"
        target_skills.mkdir(parents=True)
        (target_skills / "skill.md").write_text("test skill")

        monkeypatch.setattr("frago.tools.workspace.FRAGO_HOME", frago_home)
        monkeypatch.setattr("frago.tools.workspace.SYSTEM_WORKSPACE", target)
        monkeypatch.setattr("frago.tools.workspace.MIGRATION_FLAG",
                          frago_home / ".workspace_migrated")

        assert migrate_legacy_claude_dir()
        # Legacy should be gone
        assert not legacy.exists()
        # Target skills should still be there (not overwritten)
        assert (target_skills / "skill.md").exists()
        # Flag should exist
        assert (frago_home / ".workspace_migrated").exists()

    def test_migrates_metadata(self, tmp_path, monkeypatch):
        frago_home = tmp_path / ".frago"
        frago_home.mkdir()
        legacy = frago_home / ".claude"
        legacy.mkdir()

        metadata = {
            "version": 1,
            "entries": {
                "skills/frago-test": {
                    "content_hash": "abc123",
                    "synced_at": "2026-01-01T00:00:00Z",
                    "synced_by": "dev1",
                }
            },
        }
        (legacy / "sync_metadata.json").write_text(json.dumps(metadata))

        monkeypatch.setattr("frago.tools.workspace.FRAGO_HOME", frago_home)
        monkeypatch.setattr("frago.tools.workspace.SYSTEM_WORKSPACE",
                          frago_home / "workspaces" / "__system__")
        monkeypatch.setattr("frago.tools.workspace.MIGRATION_FLAG",
                          frago_home / ".workspace_migrated")

        migrate_legacy_claude_dir()

        # Check migrated metadata
        new_meta_path = frago_home / "workspaces" / "__system__" / "sync_metadata.json"
        assert new_meta_path.exists()
        new_meta = json.loads(new_meta_path.read_text())
        assert new_meta["version"] == 2
        assert "workspaces/__system__/skills/frago-test" in new_meta["entries"]


# =============================================================================
# collect_workspaces (integration)
# =============================================================================


class TestCollectWorkspaces:
    def test_empty_scan_roots(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.tools.workspace.CLAUDE_HOME", tmp_path / ".claude")
        monkeypatch.setattr("frago.tools.workspace.WORKSPACES_DIR", tmp_path / "workspaces")
        monkeypatch.setattr("frago.tools.workspace.SYSTEM_WORKSPACE",
                          tmp_path / "workspaces" / "__system__")
        # Prevent auto-detection from scanning real ~/Repos etc.
        monkeypatch.setattr("frago.tools.workspace._auto_detect_scan_roots", lambda: [])

        result = collect_workspaces([], [])
        assert result.system_collected
        assert len(result.projects_collected) == 0

    def test_discovers_and_collects(self, tmp_path, monkeypatch):
        import subprocess

        # Set up Claude home
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (claude_home / "CLAUDE.md").write_text("global rules")

        # Set up a project with git
        scan_root = tmp_path / "repos"
        scan_root.mkdir()
        project = scan_root / "myproject"
        project.mkdir()
        subprocess.run(["git", "init", str(project)], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(project), "remote", "add", "origin",
             "https://github.com/test/myproject.git"],
            capture_output=True, check=True
        )
        project_claude = project / ".claude"
        project_claude.mkdir()
        (project_claude / "CLAUDE.md").write_text("project rules")

        ws_dir = tmp_path / "workspaces"

        monkeypatch.setattr("frago.tools.workspace.CLAUDE_HOME", claude_home)
        monkeypatch.setattr("frago.tools.workspace.WORKSPACES_DIR", ws_dir)
        monkeypatch.setattr("frago.tools.workspace.SYSTEM_WORKSPACE", ws_dir / "__system__")

        result = collect_workspaces([str(scan_root)], [])

        assert result.system_collected
        assert "github.com/test/myproject" in result.projects_collected
        assert (ws_dir / "__system__" / "CLAUDE.md").exists()
        assert (ws_dir / "github.com__test__myproject" / ".claude" / "CLAUDE.md").exists()


# =============================================================================
# detect_workspace_changes
# =============================================================================


class TestDetectWorkspaceChanges:
    def test_detects_system_changes(self):
        diffs = [
            ("M", "workspaces/__system__/CLAUDE.md"),
            ("A", "workspaces/__system__/skills/new-skill/skill.md"),
        ]
        changes = detect_workspace_changes(diffs)
        assert changes.has_changes
        assert len(changes.items) == 2
        assert changes.items[0].workspace == "__system__"
        assert changes.items[0].path == "CLAUDE.md"

    def test_detects_project_changes(self):
        diffs = [
            ("M", "workspaces/github.com__user__repo/.claude/CLAUDE.md"),
        ]
        changes = detect_workspace_changes(diffs)
        assert len(changes.items) == 1
        assert changes.items[0].workspace == "github.com__user__repo"
        assert changes.items[0].path == ".claude/CLAUDE.md"

    def test_ignores_non_workspace(self):
        diffs = [
            ("M", "recipes/atomic/test.json"),
            ("A", ".gitignore"),
        ]
        changes = detect_workspace_changes(diffs)
        assert not changes.has_changes

    def test_maps_status_codes(self):
        diffs = [
            ("A", "workspaces/__system__/a.md"),
            ("M", "workspaces/__system__/b.md"),
            ("D", "workspaces/__system__/c.md"),
        ]
        changes = detect_workspace_changes(diffs)
        types = [c.change_type for c in changes.items]
        assert types == ["added", "modified", "deleted"]


# =============================================================================
# summarize_workspace_changes
# =============================================================================


class TestSummarizeWorkspaceChanges:
    def test_groups_files_into_resources(self):
        changes = WorkspaceChanges(items=[
            WorkspaceChangeItem("__system__", "skills/test/a.md", "modified"),
            WorkspaceChangeItem("__system__", "skills/test/b.md", "modified"),
        ])
        summary = summarize_workspace_changes(changes)
        assert len(summary) == 1
        assert summary[0]["resource"] == "skills/test"

    def test_separate_workspaces(self):
        changes = WorkspaceChanges(items=[
            WorkspaceChangeItem("__system__", "CLAUDE.md", "modified"),
            WorkspaceChangeItem("gh__u__r", ".claude/CLAUDE.md", "added"),
        ])
        summary = summarize_workspace_changes(changes)
        assert len(summary) == 2

    def test_single_file_resource(self):
        changes = WorkspaceChanges(items=[
            WorkspaceChangeItem("__system__", "CLAUDE.md", "added"),
        ])
        summary = summarize_workspace_changes(changes)
        assert len(summary) == 1
        assert summary[0]["resource"] == "CLAUDE.md"


# =============================================================================
# Integration: collect → change detection roundtrip
# =============================================================================


class TestCollectAndDetectRoundtrip:
    def test_collect_produces_detectable_paths(self, tmp_path, monkeypatch):
        """Verify that workspace directory structure from collect()
        matches the path format expected by detect_workspace_changes()."""
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (claude_home / "CLAUDE.md").write_text("global rules")
        skills = claude_home / "skills" / "my-skill"
        skills.mkdir(parents=True)
        (skills / "skill.md").write_text("content")

        ws_dir = tmp_path / "workspaces"

        monkeypatch.setattr("frago.tools.workspace.CLAUDE_HOME", claude_home)
        monkeypatch.setattr("frago.tools.workspace.WORKSPACES_DIR", ws_dir)
        monkeypatch.setattr("frago.tools.workspace.SYSTEM_WORKSPACE", ws_dir / "__system__")

        collect_workspaces([], [])

        # Simulate git diff output for the collected files
        diffs = []
        for path in ws_dir.rglob("*"):
            if path.is_file():
                rel = str(path.relative_to(tmp_path))
                diffs.append(("A", rel))

        changes = detect_workspace_changes(diffs)
        assert changes.has_changes

        # Should have at least CLAUDE.md and skill
        resources = {item.path for item in changes.items}
        assert "CLAUDE.md" in resources
        assert any("skills/" in r for r in resources)
