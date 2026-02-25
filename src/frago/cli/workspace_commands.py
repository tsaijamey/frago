"""workspace command group - Manage workspace resources"""

import sys

import click

from frago.cli.agent_friendly import AgentFriendlyGroup
from frago.init.config_manager import load_config, save_config


@click.group(name="workspace", cls=AgentFriendlyGroup)
def workspace_group():
    """
    Manage workspace resources

    \b
    Workspace collects agent resources (skills, CLAUDE.md, project memories)
    from your local machine and syncs them across devices via `frago sync`.
    """
    pass


@workspace_group.command("list")
def workspace_list():
    """List discovered projects and workspace status"""
    config = load_config()
    scan_roots = config.workspace_scan_roots
    exclude_patterns = config.workspace_exclude_patterns

    if not scan_roots:
        click.echo("No scan roots configured.")
        click.echo("")
        click.echo("Configure scan roots to discover projects:")
        click.echo('  frago workspace set-scan-roots ~/repos/ ~/work/')
        return

    click.echo(f"Scan roots: {', '.join(scan_roots)}")
    click.echo("")

    from frago.tools.workspace import (
        WORKSPACES_DIR,
        _discover_projects,
        get_canonical_id,
    )

    projects = _discover_projects(scan_roots, exclude_patterns)

    if not projects:
        click.echo("No projects found in scan roots.")
        return

    # Table header
    click.echo(f"{'Canonical ID':<40} {'Local Path'}")
    click.echo(f"{'─' * 40} {'─' * 40}")

    # System workspace
    click.echo(f"{'__system__':<40} {'~/.claude/ (global)'}")

    # Projects
    identified = 0
    unidentified = 0
    for project in sorted(projects, key=lambda p: str(p.path)):
        canonical_id = get_canonical_id(project.path)
        if canonical_id:
            click.echo(f"{canonical_id:<40} {project.path}")
            identified += 1
        else:
            click.echo(f"{'[unidentified]':<40} {project.path}")
            unidentified += 1

    click.echo("")
    click.echo(f"Total: {identified} project(s), {unidentified} unidentified")

    # Check workspace directory
    if WORKSPACES_DIR.exists():
        workspace_count = sum(1 for d in WORKSPACES_DIR.iterdir() if d.is_dir())
        click.echo(f"Workspace storage: {WORKSPACES_DIR} ({workspace_count} workspace(s))")


@workspace_group.command("set-scan-roots")
@click.argument("roots", nargs=-1, required=True)
def workspace_set_scan_roots(roots: tuple[str, ...]):
    """Set directories to scan for projects

    \b
    Examples:
      frago workspace set-scan-roots ~/repos/
      frago workspace set-scan-roots ~/repos/ ~/work/ ~/projects/
    """
    config = load_config()
    config.workspace_scan_roots = list(roots)
    save_config(config)

    click.echo(f"Scan roots set to: {', '.join(roots)}")
    click.echo("")
    click.echo("Run 'frago workspace list' to see discovered projects.")
    click.echo("Run 'frago sync' to collect and sync workspace resources.")


@workspace_group.command("collect")
@click.option("--dry-run", is_flag=True, help="Preview what would be collected")
def workspace_collect(dry_run: bool):
    """Collect workspace resources without syncing"""
    config = load_config()
    scan_roots = config.workspace_scan_roots
    exclude_patterns = config.workspace_exclude_patterns

    if not scan_roots:
        click.echo("No scan roots configured.")
        click.echo("Use 'frago workspace set-scan-roots' first.")
        sys.exit(1)

    if dry_run:
        click.echo("=== Preview Mode ===")
        click.echo("")

    from frago.tools.workspace import collect_workspaces

    result = collect_workspaces(scan_roots, exclude_patterns)

    click.echo(f"System workspace: {'collected' if result.system_collected else 'skipped'}")
    if result.projects_collected:
        click.echo(f"Projects collected ({len(result.projects_collected)}):")
        for cid in sorted(result.projects_collected):
            click.echo(f"  {cid}")
    if result.unidentified:
        click.echo(f"Unidentified projects ({len(result.unidentified)}):")
        for path in result.unidentified:
            click.echo(f"  {path}")
    if result.errors:
        click.echo(f"Errors ({len(result.errors)}):")
        for err in result.errors:
            click.echo(f"  {err}", err=True)


@workspace_group.command("pending")
def workspace_pending():
    """View pending deployment actions from last sync

    \b
    Shows workspace resources that were synced from another device
    but haven't been deployed to their target locations yet.
    """
    from frago.tools.deployment_agent import DeploymentPlan, format_deployment_table

    plan = DeploymentPlan.load()
    if plan is None:
        click.echo("No pending deployments.")
        return

    table = format_deployment_table(plan)
    if table:
        click.echo(table)
    else:
        click.echo("No pending deployments.")

    click.echo("")
    click.echo(f"Created at: {plan.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    click.echo("")
    click.echo("These actions will be executed automatically on next 'frago sync'.")
    click.echo("Or run 'frago workspace deploy' to execute now.")
