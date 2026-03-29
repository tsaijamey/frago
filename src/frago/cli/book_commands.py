"""frago book — built-in knowledge query command"""

import logging
from importlib.resources import files as pkg_files

import click
import yaml

logger = logging.getLogger(__name__)

BOOK_DIR = pkg_files("frago.resources") / "book"

CATEGORY_ORDER = ["must", "better", "available"]
CATEGORY_HEADERS = {
    "must": "替代（MUST — 不遵守会出错）",
    "better": "偏好（BETTER — 有更好的方式）",
    "available": "效率（AVAILABLE — 你可能不知道有这个）",
}
CATEGORY_TAGS = {"must": "MUST", "better": "BETTER", "available": "AVAILABLE"}


def _load_index() -> list[dict]:
    """Load the book index from _index.yaml."""
    index_path = BOOK_DIR / "_index.yaml"
    if not index_path.is_file():
        raise click.ClickException(
            "Book index not found. frago installation may be incomplete."
        )
    raw = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    entries = []
    for item in raw:
        cat = item.get("category", "")
        if cat not in CATEGORY_ORDER:
            logger.warning("Invalid category '%s' for topic '%s', skipping", cat, item.get("name"))
            continue
        entries.append(item)
    return entries


@click.command("book")
@click.argument("topic", required=False)
@click.option("--brief", is_flag=True, help="One-line summary for each topic")
def book_command(topic: str | None, brief: bool):
    """frago built-in knowledge book."""
    entries = _load_index()

    if brief:
        _print_brief(entries)
        return

    if topic is None:
        _print_index(entries)
        return

    # Find topic
    entry = next((e for e in entries if e["name"] == topic), None)
    if entry is None:
        _print_not_found(topic, entries)
        return

    # Output .md content
    md_path = BOOK_DIR / f"{topic}.md"
    if not md_path.is_file():
        click.echo(f"{entry['brief']} [{CATEGORY_TAGS[entry['category']]}]")
        click.echo(f"\nDetail content missing for topic: {topic}")
        return

    click.echo(md_path.read_text(encoding="utf-8"))


def _print_index(entries: list[dict]):
    click.echo("\nfrago Knowledge Book\n")
    for cat in CATEGORY_ORDER:
        group = [e for e in entries if e["category"] == cat]
        if not group:
            continue
        click.echo(f"== {CATEGORY_HEADERS[cat]} ==\n")
        for e in group:
            click.echo(f"  {e['name']:<20s} {e['brief']}")
        click.echo()
    click.echo("查看详情: frago book <topic>")


def _print_brief(entries: list[dict]):
    for e in entries:
        click.echo(f"{e['name']}: {e['brief']} [{CATEGORY_TAGS[e['category']]}]")


def _print_not_found(topic: str, entries: list[dict]):
    names = [e["name"] for e in entries]
    # Simple prefix matching
    prefix = topic.split("-")[0]
    suggestions = [n for n in names if n.startswith(prefix)]
    click.echo(f"Topic not found: {topic}")
    if suggestions:
        click.echo(f"Did you mean: {', '.join(suggestions)}?")
    click.echo(f"\nAvailable topics: {', '.join(names)}")
