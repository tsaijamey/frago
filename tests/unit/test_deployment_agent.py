"""Tests for deployment agent — change analysis, project matching, deploy execution."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from frago.tools.deployment_agent import (
    DeployAction,
    DeploymentAgent,
    DeploymentPlan,
    ProjectMatch,
    execute_deployment,
    format_deployment_table,
)
from frago.tools.workspace import (
    WorkspaceChangeItem,
    WorkspaceChanges,
    detect_workspace_changes,
    summarize_workspace_changes,
)


# =============================================================================
# detect_workspace_changes
# =============================================================================


class TestDetectWorkspaceChanges:
    def test_filters_workspace_paths(self):
        diffs = [
            ("M", "workspaces/__system__/CLAUDE.md"),
            ("A", "workspaces/__system__/skills/new-skill/skill.md"),
            ("M", "recipes/atomic/test.json"),  # not workspace
        ]
        changes = detect_workspace_changes(diffs)
        assert len(changes.items) == 2
        assert changes.has_changes

    def test_empty_when_no_workspace_changes(self):
        diffs = [
            ("M", "recipes/atomic/test.json"),
            ("A", ".gitignore"),
        ]
        changes = detect_workspace_changes(diffs)
        assert not changes.has_changes

    def test_parses_status_correctly(self):
        diffs = [
            ("A", "workspaces/__system__/CLAUDE.md"),
            ("M", "workspaces/gh__u__r/.claude/docs/arch.md"),
            ("D", "workspaces/__system__/skills/old-skill/skill.md"),
        ]
        changes = detect_workspace_changes(diffs)
        assert changes.items[0].change_type == "added"
        assert changes.items[1].change_type == "modified"
        assert changes.items[2].change_type == "deleted"

    def test_extracts_workspace_and_path(self):
        diffs = [
            ("M", "workspaces/github.com__user__repo/.claude/CLAUDE.md"),
        ]
        changes = detect_workspace_changes(diffs)
        assert changes.items[0].workspace == "github.com__user__repo"
        assert changes.items[0].path == ".claude/CLAUDE.md"

    def test_canonical_id_property(self):
        item = WorkspaceChangeItem(
            workspace="github.com__user__repo",
            path=".claude/CLAUDE.md",
            change_type="modified",
        )
        assert item.canonical_id == "github.com/user/repo"

    def test_canonical_id_none_for_system(self):
        item = WorkspaceChangeItem(
            workspace="__system__",
            path="CLAUDE.md",
            change_type="modified",
        )
        assert item.canonical_id is None

    def test_skips_shallow_paths(self):
        diffs = [
            ("M", "workspaces/__system__"),  # no third component
        ]
        changes = detect_workspace_changes(diffs)
        assert not changes.has_changes


# =============================================================================
# summarize_workspace_changes
# =============================================================================


class TestSummarizeWorkspaceChanges:
    def test_groups_by_resource(self):
        changes = WorkspaceChanges(items=[
            WorkspaceChangeItem("__system__", "skills/git-xxx/a.md", "modified"),
            WorkspaceChangeItem("__system__", "skills/git-xxx/b.md", "modified"),
            WorkspaceChangeItem("__system__", "CLAUDE.md", "modified"),
        ])
        summary = summarize_workspace_changes(changes)
        assert len(summary) == 2
        resources = {s["resource"] for s in summary}
        assert "skills/git-xxx" in resources
        assert "CLAUDE.md" in resources

    def test_mixed_changes_become_modified(self):
        changes = WorkspaceChanges(items=[
            WorkspaceChangeItem("__system__", "skills/test/a.md", "added"),
            WorkspaceChangeItem("__system__", "skills/test/b.md", "deleted"),
        ])
        summary = summarize_workspace_changes(changes)
        assert len(summary) == 1
        assert summary[0]["change_type"] == "modified"


# =============================================================================
# DeploymentAgent.analyze
# =============================================================================


class TestDeploymentAgentAnalyze:
    def test_system_resource_targets_claude_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.tools.deployment_agent.CLAUDE_HOME", tmp_path / ".claude")

        agent = DeploymentAgent(scan_roots=[], exclude_patterns=[])
        changes = WorkspaceChanges(items=[
            WorkspaceChangeItem("__system__", "CLAUDE.md", "modified"),
        ])
        plan = agent.analyze(changes)

        assert len(plan.actions) == 1
        assert plan.actions[0].action == "deploy"
        assert plan.actions[0].confidence == 1.0
        assert ".claude" in plan.actions[0].target

    def test_project_resource_matches_local(self, tmp_path, monkeypatch):
        # Create a project with git remote
        project = tmp_path / "repos" / "myproject"
        project.mkdir(parents=True)
        subprocess.run(["git", "init", str(project)], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(project), "remote", "add", "origin",
             "https://github.com/user/myproject.git"],
            capture_output=True, check=True
        )

        monkeypatch.setattr("frago.tools.deployment_agent.CLAUDE_HOME", tmp_path / ".claude")

        agent = DeploymentAgent(
            scan_roots=[str(tmp_path / "repos")],
            exclude_patterns=[],
        )
        changes = WorkspaceChanges(items=[
            WorkspaceChangeItem("github.com__user__myproject", ".claude/CLAUDE.md", "modified"),
        ])
        plan = agent.analyze(changes)

        assert len(plan.actions) == 1
        assert plan.actions[0].action == "deploy"
        assert plan.actions[0].confidence == 1.0
        assert str(project) == plan.actions[0].target

    def test_unmatched_project_is_pending(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.tools.deployment_agent.CLAUDE_HOME", tmp_path / ".claude")

        agent = DeploymentAgent(scan_roots=[], exclude_patterns=[])
        changes = WorkspaceChanges(items=[
            WorkspaceChangeItem("github.com__other__proj", ".claude/docs/spec.md", "added"),
        ])
        plan = agent.analyze(changes)

        assert len(plan.actions) == 1
        assert plan.actions[0].action == "pending"
        assert plan.actions[0].target == "???"
        assert plan.actions[0].confidence == 0.0

    def test_fuzzy_match_by_name(self, tmp_path, monkeypatch):
        # Project matches by directory name but different org
        project = tmp_path / "repos" / "myrepo"
        project.mkdir(parents=True)
        subprocess.run(["git", "init", str(project)], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(project), "remote", "add", "origin",
             "https://github.com/org-a/myrepo.git"],
            capture_output=True, check=True
        )

        monkeypatch.setattr("frago.tools.deployment_agent.CLAUDE_HOME", tmp_path / ".claude")

        agent = DeploymentAgent(
            scan_roots=[str(tmp_path / "repos")],
            exclude_patterns=[],
        )
        # Different org but same repo name
        changes = WorkspaceChanges(items=[
            WorkspaceChangeItem("github.com__org-b__myrepo", ".claude/CLAUDE.md", "modified"),
        ])
        plan = agent.analyze(changes)

        assert len(plan.actions) == 1
        assert plan.actions[0].action == "deploy"
        assert plan.actions[0].confidence == 0.5

    def test_groups_file_changes_into_resources(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.tools.deployment_agent.CLAUDE_HOME", tmp_path / ".claude")

        agent = DeploymentAgent(scan_roots=[], exclude_patterns=[])
        changes = WorkspaceChanges(items=[
            WorkspaceChangeItem("__system__", "skills/test-skill/a.md", "modified"),
            WorkspaceChangeItem("__system__", "skills/test-skill/b.md", "modified"),
            WorkspaceChangeItem("__system__", "CLAUDE.md", "added"),
        ])
        plan = agent.analyze(changes)

        assert len(plan.actions) == 2  # grouped into 2 resources


# =============================================================================
# DeploymentPlan
# =============================================================================


class TestDeploymentPlan:
    def test_has_actionable(self):
        plan = DeploymentPlan(actions=[
            DeployAction("CLAUDE.md", "modified", "~/.claude", "deploy", 1.0),
        ])
        assert plan.has_actionable

    def test_has_pending(self):
        plan = DeploymentPlan(actions=[
            DeployAction("docs", "added", "???", "pending", 0.0),
        ])
        assert plan.has_pending
        assert not plan.has_actionable

    def test_serialize_deserialize(self, tmp_path):
        plan = DeploymentPlan(actions=[
            DeployAction("CLAUDE.md", "modified", "~/.claude", "deploy", 1.0, "__system__"),
            DeployAction("docs", "added", "???", "pending", 0.0, "gh__u__r"),
        ])
        path = tmp_path / "plan.json"
        plan.save(path)

        loaded = DeploymentPlan.load(path)
        assert loaded is not None
        assert len(loaded.actions) == 2
        assert loaded.actions[0].resource == "CLAUDE.md"
        assert loaded.actions[1].action == "pending"

    def test_load_nonexistent_returns_none(self, tmp_path):
        assert DeploymentPlan.load(tmp_path / "nope.json") is None

    def test_clear_pending(self, tmp_path):
        path = tmp_path / "plan.json"
        path.write_text("{}")
        DeploymentPlan.clear_pending(path)
        assert not path.exists()

    def test_to_table_data(self):
        plan = DeploymentPlan(actions=[
            DeployAction("CLAUDE.md", "modified", "~/.claude", "deploy", 1.0, git_tracked=True),
        ])
        data = plan.to_table_data()
        assert len(data) == 1
        assert data[0]["git_tracked"] is True


# =============================================================================
# execute_deployment
# =============================================================================


class TestExecuteDeployment:
    def test_deploy_system_claude_md(self, tmp_path, monkeypatch):
        # Set up workspace with CLAUDE.md
        ws = tmp_path / "workspaces" / "__system__"
        ws.mkdir(parents=True)
        (ws / "CLAUDE.md").write_text("# Updated rules")

        claude_home = tmp_path / ".claude"
        claude_home.mkdir()

        monkeypatch.setattr("frago.tools.deployment_agent.WORKSPACES_DIR", tmp_path / "workspaces")
        monkeypatch.setattr("frago.tools.deployment_agent.CLAUDE_HOME", claude_home)
        monkeypatch.setattr("frago.tools.deployment_agent.PENDING_DEPLOYMENTS_FILE",
                          tmp_path / ".pending.json")

        plan = DeploymentPlan(actions=[
            DeployAction("CLAUDE.md", "modified", str(claude_home), "deploy", 1.0, "__system__"),
        ])
        msgs = execute_deployment(plan)

        assert (claude_home / "CLAUDE.md").read_text() == "# Updated rules"
        assert any("CLAUDE.md" in m for m in msgs)

    def test_deploy_system_skill(self, tmp_path, monkeypatch):
        ws = tmp_path / "workspaces" / "__system__"
        skill_dir = ws / "skills" / "new-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.md").write_text("new skill content")

        claude_home = tmp_path / ".claude"
        claude_home.mkdir()

        monkeypatch.setattr("frago.tools.deployment_agent.WORKSPACES_DIR", tmp_path / "workspaces")
        monkeypatch.setattr("frago.tools.deployment_agent.CLAUDE_HOME", claude_home)
        monkeypatch.setattr("frago.tools.deployment_agent.PENDING_DEPLOYMENTS_FILE",
                          tmp_path / ".pending.json")

        plan = DeploymentPlan(actions=[
            DeployAction("skills/new-skill", "added", str(claude_home), "deploy", 1.0, "__system__"),
        ])
        msgs = execute_deployment(plan)

        assert (claude_home / "skills" / "new-skill" / "skill.md").read_text() == "new skill content"

    def test_deploy_project_claude_dir(self, tmp_path, monkeypatch):
        # Set up workspace with project .claude/
        ws = tmp_path / "workspaces" / "github.com__user__proj"
        (ws / ".claude" / "docs").mkdir(parents=True)
        (ws / ".claude" / "CLAUDE.md").write_text("project rules")
        (ws / ".claude" / "docs" / "arch.md").write_text("architecture")

        # Set up local project
        project = tmp_path / "repos" / "proj"
        project.mkdir(parents=True)
        (project / ".claude").mkdir()

        monkeypatch.setattr("frago.tools.deployment_agent.WORKSPACES_DIR", tmp_path / "workspaces")
        monkeypatch.setattr("frago.tools.deployment_agent.CLAUDE_HOME", tmp_path / ".claude")
        monkeypatch.setattr("frago.tools.deployment_agent.PENDING_DEPLOYMENTS_FILE",
                          tmp_path / ".pending.json")

        plan = DeploymentPlan(actions=[
            DeployAction(".claude/CLAUDE.md", "modified", str(project), "deploy", 1.0,
                        "github.com__user__proj"),
        ])
        msgs = execute_deployment(plan)

        assert (project / ".claude" / "CLAUDE.md").read_text() == "project rules"

    def test_deploy_project_memory(self, tmp_path, monkeypatch):
        # Set up workspace with project memory
        ws = tmp_path / "workspaces" / "github.com__user__proj"
        (ws / ".project-memory").mkdir(parents=True)
        (ws / ".project-memory" / "MEMORY.md").write_text("project memory content")

        # Set up local project
        project = tmp_path / "repos" / "proj"
        project.mkdir(parents=True)

        claude_home = tmp_path / ".claude"

        monkeypatch.setattr("frago.tools.deployment_agent.WORKSPACES_DIR", tmp_path / "workspaces")
        monkeypatch.setattr("frago.tools.deployment_agent.CLAUDE_HOME", claude_home)
        monkeypatch.setattr("frago.tools.deployment_agent.PENDING_DEPLOYMENTS_FILE",
                          tmp_path / ".pending.json")

        plan = DeploymentPlan(actions=[
            DeployAction(".project-memory", "modified", str(project), "deploy", 1.0,
                        "github.com__user__proj"),
        ])
        msgs = execute_deployment(plan)

        # Should restore to Claude Code's encoded path
        from frago.tools.workspace import _encode_project_path
        encoded = _encode_project_path(project)
        memory_path = claude_home / "projects" / encoded / "memory" / "MEMORY.md"
        assert memory_path.read_text() == "project memory content"

    def test_skips_pending_actions(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.tools.deployment_agent.WORKSPACES_DIR", tmp_path / "workspaces")
        monkeypatch.setattr("frago.tools.deployment_agent.CLAUDE_HOME", tmp_path / ".claude")
        monkeypatch.setattr("frago.tools.deployment_agent.PENDING_DEPLOYMENTS_FILE",
                          tmp_path / ".pending.json")

        plan = DeploymentPlan(actions=[
            DeployAction("docs", "added", "???", "pending", 0.0, "gh__u__r"),
        ])
        msgs = execute_deployment(plan)
        assert len(msgs) == 0

    def test_deploy_nonexistent_project_skips(self, tmp_path, monkeypatch):
        ws = tmp_path / "workspaces" / "gh__u__r"
        (ws / ".claude").mkdir(parents=True)
        (ws / ".claude" / "CLAUDE.md").write_text("rules")

        monkeypatch.setattr("frago.tools.deployment_agent.WORKSPACES_DIR", tmp_path / "workspaces")
        monkeypatch.setattr("frago.tools.deployment_agent.CLAUDE_HOME", tmp_path / ".claude")
        monkeypatch.setattr("frago.tools.deployment_agent.PENDING_DEPLOYMENTS_FILE",
                          tmp_path / ".pending.json")

        plan = DeploymentPlan(actions=[
            DeployAction(".claude/CLAUDE.md", "modified", "/nonexistent/path", "deploy", 1.0, "gh__u__r"),
        ])
        msgs = execute_deployment(plan)
        assert any("not found" in m for m in msgs)


# =============================================================================
# format_deployment_table
# =============================================================================


class TestFormatDeploymentTable:
    def test_empty_plan(self):
        plan = DeploymentPlan(actions=[])
        assert format_deployment_table(plan) == ""

    def test_basic_table(self):
        plan = DeploymentPlan(actions=[
            DeployAction("CLAUDE.md", "modified", "~/.claude", "deploy", 1.0),
        ])
        table = format_deployment_table(plan)
        assert "CLAUDE.md" in table
        assert "deploy" in table

    def test_git_tracked_annotation(self):
        plan = DeploymentPlan(actions=[
            DeployAction(".claude/docs", "modified", "~/repos/proj", "deploy", 1.0, git_tracked=True),
        ])
        table = format_deployment_table(plan)
        assert "git-tracked" in table

    def test_pending_annotation(self):
        plan = DeploymentPlan(actions=[
            DeployAction("docs", "added", "???", "pending", 0.0),
        ])
        table = format_deployment_table(plan)
        assert "pending" in table


# =============================================================================
# DeploymentAgent._is_claude_dir_git_tracked
# =============================================================================


class TestIsClaudeDirGitTracked:
    def test_tracked(self, tmp_path):
        # Set up a git repo with .claude/ tracked
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "CLAUDE.md").write_text("rules")
        subprocess.run(["git", "-C", str(tmp_path), "add", ".claude/"], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-m", "init", "--allow-empty"],
            capture_output=True, check=True
        )

        assert DeploymentAgent._is_claude_dir_git_tracked(tmp_path)

    def test_not_tracked(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "CLAUDE.md").write_text("rules")
        # Not staged/committed

        assert not DeploymentAgent._is_claude_dir_git_tracked(tmp_path)

    def test_no_git(self, tmp_path):
        assert not DeploymentAgent._is_claude_dir_git_tracked(tmp_path)
