"""frago def — knowledge domain management commands.

Provides:
  frago def add/list/remove    — manage domains
  frago <domain> find/schema/save — dynamic per-domain commands
"""

import json
import logging

import click

from .agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup

logger = logging.getLogger(__name__)


# ── frago def ── static command group ──────────────────────────────────


@click.group(name="def", cls=AgentFriendlyGroup, invoke_without_command=True)
@click.pass_context
def def_group(ctx):
    """Manage structured knowledge domains."""
    if ctx.invoked_subcommand is not None:
        return

    # Bare invocation: show domain list
    from frago.def_.registry import list_domains

    domains = list_domains()
    if not domains:
        click.echo("No registered domains.\n")
        click.echo("Register one:")
        click.echo('  frago def add <name> --purpose "..." --schema \'{"fields": [...]}\'')
        return

    click.echo(f"\nRegistered domains ({len(domains)}):\n")
    # Table header
    click.echo(f"  {'NAME':<24s} {'DOCS':>4s}   PURPOSE")
    click.echo("  " + "-" * 70)
    for d in domains:
        click.echo(f"  {d['name']:<24s} {d['docs']:>4d}   {d['purpose']}")

    click.echo("\nUsage:")
    first = domains[0]["name"]
    click.echo(f"  frago {first} find                          List all documents")
    click.echo(f"  frago {first} find -- --tags=<value>        Filter by tag")
    click.echo(f"  frago {first} find -- --name=<doc>          Show single doc with entries")
    click.echo(f"  frago {first} save --name=<doc> \\")
    click.echo("    --data='{\"tags\": [\"a\", \"b\"]}' \\")
    click.echo("    --content '[\"knowledge entry 1\", \"entry 2\"]'")
    click.echo(f"  frago {first} schema                        Show queryable fields")
    click.echo("  frago def add <name> --purpose \"...\" --schema '{\"fields\": [...]}'")
    click.echo("  frago def remove <name>                     Unregister (keeps files)")


@def_group.command(name="add", cls=AgentFriendlyCommand)
@click.argument("name")
@click.option("--purpose", required=True, help="Domain purpose (used for convergence decisions)")
@click.option("--schema", "schema_json", required=True, help="Schema JSON: {\"fields\": [...]}")
def def_add(name: str, purpose: str, schema_json: str):
    """Register a new knowledge domain."""
    from frago.def_.registry import add_domain

    # Check name conflicts with built-in commands
    from .main import cli as main_cli

    builtin_names = set()
    try:
        ctx = click.Context(main_cli)
        builtin_names = set(main_cli.list_commands(ctx))
    except Exception:
        pass

    if name in builtin_names:
        raise click.ClickException(
            f"Name conflicts with built-in command: '{name}'. Choose a different name."
        )

    try:
        schema = json.loads(schema_json)
    except json.JSONDecodeError as e:
        raise click.ClickException(f"Invalid schema JSON: {e}") from None

    # Ensure source_format defaults to yaml-frontmatter
    if "source_format" not in schema:
        schema["source_format"] = "yaml-frontmatter"

    try:
        domain_dir = add_domain(name, purpose, schema)
    except ValueError as e:
        raise click.ClickException(str(e)) from None

    click.echo(f"Registered domain '{name}'.")
    click.echo(f"Path: {domain_dir}")
    click.echo("\nNext steps:")
    click.echo(f"  frago {name} schema       View queryable fields")
    click.echo(f"  frago {name} save ...     Save first document")
    click.echo("  frago def list            See all domains")


@def_group.command(name="list", cls=AgentFriendlyCommand)
def def_list():
    """List all registered domains."""
    from frago.def_.registry import list_domains

    domains = list_domains()
    if not domains:
        click.echo("No registered domains.")
        click.echo('  frago def add <name> --purpose "..." --schema \'{"fields": [...]}\'')
        return

    click.echo(f"\n{'NAME':<24s} {'DOCS':>4s}   {'CREATED':<12s} PURPOSE")
    click.echo("-" * 80)
    for d in domains:
        click.echo(
            f"{d['name']:<24s} {d['docs']:>4d}   {d['created']:<12s} {d['purpose']}"
        )


@def_group.command(name="remove", cls=AgentFriendlyCommand)
@click.argument("name")
def def_remove(name: str):
    """Unregister a domain (files are kept)."""
    from frago.def_.registry import remove_domain

    try:
        remove_domain(name)
    except ValueError as e:
        raise click.ClickException(str(e)) from None

    click.echo(f"Unregistered domain '{name}'. Files in ~/.frago/books/{name}/ are kept.")


# ── Dynamic domain command group builder ───────────────────────────────


def build_command_group(domain_name: str, definition: dict) -> click.Group:
    """Build a dynamic Click command group for a registered domain.

    Returns a group with find/schema/save subcommands.
    """
    schema = definition.get("schema", {})
    purpose = definition.get("purpose", "")

    @click.group(
        name=domain_name,
        cls=AgentFriendlyGroup,
        invoke_without_command=True,
    )
    @click.pass_context
    def domain_group(ctx):
        if ctx.invoked_subcommand is not None:
            return

        # Bare invocation: show domain info
        from frago.def_.query_engine import get_schema_display
        from frago.def_.registry import get_domain_dir

        domain_dir = get_domain_dir(domain_name)
        doc_count = len(list(domain_dir.glob("*.md"))) if domain_dir.exists() else 0

        click.echo(f"\nDomain: {domain_name}")
        click.echo(f"Purpose: {purpose}")
        click.echo(f"Documents: {doc_count}")
        click.echo("\nSchema:")
        click.echo(get_schema_display(schema))
        click.echo("\nUsage:")
        click.echo(f"  frago {domain_name} find                          List all documents")
        click.echo(f"  frago {domain_name} find -- --name=<doc>          Show single doc with entries")
        click.echo(f"  frago {domain_name} find -- --tags=<value>        Filter by tag")
        click.echo(f"  frago {domain_name} find --count                  Count only")
        click.echo(f"  frago {domain_name} save --name=<doc> \\")
        click.echo("    --data='{\"tags\": [\"a\", \"b\"]}' \\")
        click.echo("    --content '[\"knowledge entry 1\", \"entry 2\"]'")
        click.echo(f"  frago {domain_name} schema                        Show field definitions")

    domain_group.help = purpose

    # ── find ──

    @domain_group.command(name="find", cls=AgentFriendlyCommand)
    @click.option("--fields", default=None, help="Comma-separated field names to display")
    @click.option("--sort-by", default=None, help="Sort by field name")
    @click.option("--desc", is_flag=True, help="Descending sort order")
    @click.option("--limit", type=int, default=None, help="Max results")
    @click.option("--count", is_flag=True, help="Only show count")
    @click.argument("filters", nargs=-1)
    @click.pass_context
    def find_cmd(ctx, fields, sort_by, desc, limit, count, filters):
        """Query documents in this domain."""
        from frago.def_.query_engine import find
        from frago.def_.registry import get_domain_dir

        domain_dir = get_domain_dir(domain_name)

        # Parse filters from --key=value style args
        filter_dict = _parse_filters(filters, ctx)

        fields_list = [f.strip() for f in fields.split(",")] if fields else None

        result = find(
            domain_dir=domain_dir,
            schema=schema,
            filters=filter_dict if filter_dict else None,
            fields=fields_list,
            sort_by=sort_by,
            desc=desc,
            limit=limit,
            count_only=count,
        )
        click.echo(result)

    # ── schema ──

    @domain_group.command(name="schema", cls=AgentFriendlyCommand)
    def schema_cmd():
        """Show queryable fields for this domain."""
        from frago.def_.query_engine import get_schema_display

        click.echo(f"\nDomain: {domain_name}")
        click.echo(f"Purpose: {purpose}")
        click.echo(f"\n{get_schema_display(schema)}")

    # ── save ──

    @domain_group.command(name="save", cls=AgentFriendlyCommand)
    @click.option("--name", "doc_name", required=True, help="Document name (filename without .md)")
    @click.option("--data", "data_json", default=None, help="Frontmatter fields as JSON")
    @click.option("--content", "content_json", default=None, help="Content entries as JSON array")
    def save_cmd(doc_name, data_json, content_json):
        """Save (upsert) a knowledge document."""
        from frago.def_.query_engine import save
        from frago.def_.registry import get_domain_dir

        domain_dir = get_domain_dir(domain_name)

        data = {}
        if data_json:
            try:
                data = json.loads(data_json)
            except json.JSONDecodeError as e:
                raise click.ClickException(f"Invalid --data JSON: {e}") from None

        content = None
        if content_json:
            try:
                content = json.loads(content_json)
                if not isinstance(content, list):
                    raise click.ClickException("--content must be a JSON array")
            except json.JSONDecodeError as e:
                raise click.ClickException(f"Invalid --content JSON: {e}") from None

        try:
            result = save(
                domain_dir=domain_dir,
                schema=schema,
                name=doc_name,
                data=data,
                content=content,
            )
        except ValueError as e:
            raise click.ClickException(str(e)) from None

        click.echo(result)

    return domain_group


def _parse_filters(args: tuple, _ctx: click.Context) -> dict[str, str]:
    """Parse filter arguments like --key=value from remaining args."""
    filters = {}
    for arg in args:
        if arg.startswith("--") and "=" in arg:
            key, value = arg[2:].split("=", 1)
            filters[key] = value
        else:
            # Try to parse as key=value without --
            if "=" in arg:
                key, value = arg.split("=", 1)
                filters[key] = value
    return filters
