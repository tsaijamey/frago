"""Skill management commands"""

import json

import click

from frago.skills import SkillRegistry
from .agent_friendly import AgentFriendlyGroup


@click.group(name='skill', cls=AgentFriendlyGroup)
def skill_group():
    """Skill management command group"""
    pass


@skill_group.command(name='list')
@click.option(
    '--format',
    'output_format',
    type=click.Choice(['table', 'json', 'names'], case_sensitive=False),
    default='table',
    help='Output format'
)
def list_skills(output_format: str):
    """List all available Skills"""
    registry = SkillRegistry()
    registry.scan()

    skills = registry.list_all()
    invalid_skills = registry.get_invalid()

    if output_format == 'json':
        output = {
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "path": str(s.path)
                }
                for s in skills
            ],
            "invalid": [
                {
                    "dir_name": inv.dir_name,
                    "path": str(inv.path),
                    "reason": inv.reason
                }
                for inv in invalid_skills
            ]
        }
        click.echo(json.dumps(output, ensure_ascii=False, indent=2))

    elif output_format == 'names':
        for s in skills:
            click.echo(s.name)
        # Also output invalid skill warnings in names format
        if invalid_skills:
            click.echo()
            click.echo("[!] The following Skills do not comply with specifications and were not loaded:", err=True)
            for inv in invalid_skills:
                click.echo(f"  - {inv.dir_name}: {inv.reason}", err=True)

    else:  # table
        if not skills and not invalid_skills:
            click.echo("No Skills found")
            return

        if skills:
            for s in skills:
                click.echo(f"- {s.name}")
                click.echo(f"  {s.description}")
                click.echo()

        # Output invalid skill warnings
        if invalid_skills:
            click.echo()
            click.echo("[!] The following Skills do not comply with specifications and were not loaded:")
            for inv in invalid_skills:
                click.echo(f"  - {inv.dir_name}: {inv.reason}")
