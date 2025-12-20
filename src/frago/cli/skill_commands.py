"""Skill 管理命令"""

import json

import click

from frago.skills import SkillRegistry
from .agent_friendly import AgentFriendlyGroup


@click.group(name='skill', cls=AgentFriendlyGroup)
def skill_group():
    """Skill 管理命令组"""
    pass


@skill_group.command(name='list')
@click.option(
    '--format',
    'output_format',
    type=click.Choice(['table', 'json', 'names'], case_sensitive=False),
    default='table',
    help='输出格式'
)
def list_skills(output_format: str):
    """列出所有可用的 Skill"""
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
        # names 格式下也输出无效 skill 警告
        if invalid_skills:
            click.echo()
            click.echo("⚠ 以下 Skill 不符合规范，未加载:", err=True)
            for inv in invalid_skills:
                click.echo(f"  • {inv.dir_name}: {inv.reason}", err=True)

    else:  # table
        if not skills and not invalid_skills:
            click.echo("未找到 Skill")
            return

        if skills:
            for s in skills:
                click.echo(f"• {s.name}")
                click.echo(f"  {s.description}")
                click.echo()

        # 输出无效 skill 警告
        if invalid_skills:
            click.echo()
            click.echo("⚠ 以下 Skill 不符合规范，未加载:")
            for inv in invalid_skills:
                click.echo(f"  • {inv.dir_name}: {inv.reason}")
