"""frago book — built-in knowledge query command"""

import logging
from importlib.resources import files as pkg_files

import click
import yaml

from .agent_friendly import AgentFriendlyCommand

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


def _load_scenes() -> list[dict]:
    """Load the scene index from _scenes.yaml."""
    scenes_path = BOOK_DIR / "_scenes.yaml"
    if not scenes_path.is_file():
        return []
    raw = yaml.safe_load(scenes_path.read_text(encoding="utf-8"))
    return raw if raw else []


@click.command("book", cls=AgentFriendlyCommand)
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

    # Handle "scenes" — scene index
    if topic == "scenes":
        _print_scenes()
        return

    # Handle scene-<name> — scene card (also .md file)
    if topic.startswith("scene-"):
        md_path = BOOK_DIR / f"{topic}.md"
        if md_path.is_file():
            click.echo(md_path.read_text(encoding="utf-8"))
            return
        # Scene not found — suggest available scenes
        scenes = _load_scenes()
        names = [f"scene-{s['name']}" for s in scenes]
        click.echo(f"Scene not found: {topic}")
        click.echo(f"\nAvailable scenes: {', '.join(names)}")
        return

    # Find topic — match full name or short name (without category prefix)
    entry = next(
        (e for e in entries if e["name"] == topic or e["name"].split("-", 1)[-1] == topic),
        None,
    )
    if entry is None:
        _print_not_found(topic, entries)
        return

    # Output .md content — always use canonical name from index
    topic_name = entry["name"]
    md_path = BOOK_DIR / f"{topic_name}.md"
    if not md_path.is_file():
        click.echo(f"{entry['brief']} [{CATEGORY_TAGS[entry['category']]}]")
        click.echo(f"\nDetail content missing for topic: {topic_name}")
        return

    click.echo(md_path.read_text(encoding="utf-8"))


def _print_index(entries: list[dict]):
    click.echo("\nfrago Knowledge Book\n")

    # Identity preamble
    identity_path = BOOK_DIR / "_identity.md"
    if identity_path.is_file():
        click.echo(identity_path.read_text(encoding="utf-8"))
        click.echo()

    # Topic index
    for cat in CATEGORY_ORDER:
        group = [e for e in entries if e["category"] == cat]
        if not group:
            continue
        click.echo(f"== {CATEGORY_HEADERS[cat]} ==\n")
        for e in group:
            click.echo(f"  {e['name']:<28s} {e['brief']}")
        click.echo()

    # Guidance footer
    guidance_path = BOOK_DIR / "_guidance.md"
    if guidance_path.is_file():
        click.echo(guidance_path.read_text(encoding="utf-8"))


def _print_scenes():
    scenes = _load_scenes()
    if not scenes:
        click.echo("No scenes available.")
        return

    click.echo("\nfrago 已知场景\n")
    click.echo("你正在面对什么问题？找到匹配的场景，获取推荐路径。\n")

    for s in scenes:
        signals = ", ".join(s.get("signals", [])[:4])
        click.echo(f"  scene-{s['name']:<24s} {s['brief']}")
        click.echo(f"  {'':<28s} 信号词: {signals}")
        click.echo()

    click.echo("查看场景详情: frago book scene-<name>  例: frago book scene-web-research")
    click.echo("返回知识索引: frago book")


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
