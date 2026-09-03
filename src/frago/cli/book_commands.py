"""frago book — built-in knowledge query command"""

import logging
import click
import yaml

from frago.init.user_resource_seed import ensure_book_dir

from .agent_friendly import AgentFriendlyCommand

logger = logging.getLogger(__name__)


def _book_dir():
    """The book lives under ``~/.frago/book`` so the user can edit it.

    Read straight out of the wheel until 2026-09-03; a topic inside
    site-packages cannot be corrected by the person the topic is wrong for, and
    an upgrade throws the correction away. The packaged copy is now a seed: it
    is laid down once, and never written over.
    """
    return ensure_book_dir()

CATEGORY_ORDER = ["must", "better", "available"]
CATEGORY_HEADERS = {
    "must": "替代（MUST — 不遵守会出错）",
    "better": "偏好（BETTER — 有更好的方式）",
    "available": "效率（AVAILABLE — 你可能不知道有这个）",
}
CATEGORY_TAGS = {"must": "MUST", "better": "BETTER", "available": "AVAILABLE"}


def _load_index() -> list[dict]:
    """Load the book index from _index.yaml."""
    index_path = _book_dir() / "_index.yaml"
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
    scenes_path = _book_dir() / "_scenes.yaml"
    if not scenes_path.is_file():
        return []
    raw = yaml.safe_load(scenes_path.read_text(encoding="utf-8"))
    return raw if raw else []


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split a page into ``(heading, body)`` pairs on its ``##`` headings.

    Whatever precedes the first ``##`` — the page title and its opening
    paragraph — comes back as one pair with an empty heading. It is the page's
    own framing, so a caller asking for a single section can prepend it and
    hand over a fragment that still says what it is about.
    """
    out: list[tuple[str, str]] = []
    heading = ""
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            out.append((heading, "\n".join(buf).strip()))
            heading = line[3:].strip()
            buf = []
        else:
            buf.append(line)
    out.append((heading, "\n".join(buf).strip()))
    return [(h, b) for h, b in out if h or b]


def _section_key(s: str) -> str:
    """Fold a heading down to what a rule author would plausibly type."""
    return "".join(c.lower() for c in s if c.isalnum())


def _find_section(sections: list[tuple[str, str]], wanted: str) -> tuple[str, str] | None:
    """Pick a section by name, tolerating how it is written.

    Headings are written for people — they carry punctuation, parentheses and
    the occasional English word. Demanding an exact string would make every
    rule that points at a section fragile against a copy-edit of the heading,
    so matching narrows in steps: exact, prefix, then substring.
    """
    key = _section_key(wanted)
    if not key:
        return None
    keyed = [(_section_key(h), (h, b)) for h, b in sections if h]
    for pred in (lambda k: k == key, lambda k: k.startswith(key), lambda k: key in k):
        hits = [sec for k, sec in keyed if pred(k)]
        if len(hits) >= 1:
            return hits[0]
    return None


@click.command("book", cls=AgentFriendlyCommand)
@click.argument("topic", required=False)
@click.option("--brief", is_flag=True, help="One-line summary for each topic")
@click.option("--sections", "list_sections", is_flag=True,
              help="List a topic's sections and their sizes instead of its text")
@click.option("--section", "section", default=None,
              help="Print one section of a topic instead of the whole page")
def book_command(topic: str | None, brief: bool, list_sections: bool, section: str | None):
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
        md_path = _book_dir() / f"{topic}.md"
        if md_path.is_file():
            click.echo(md_path.read_text(encoding="utf-8"))
            return
        # Scene not found — suggest available scenes
        scenes = _load_scenes()
        names = [f"scene-{s['name']}" for s in scenes]
        click.echo(f"Scene not found: {topic}", err=True)
        click.echo(f"\nAvailable scenes: {', '.join(names)}", err=True)
        raise SystemExit(1)

    # Find topic — match full name or short name (without category prefix)
    entry = next(
        (e for e in entries if e["name"] == topic or e["name"].split("-", 1)[-1] == topic),
        None,
    )
    if entry is None:
        _print_not_found(topic, entries)
        raise SystemExit(1)

    # Output .md content — always use canonical name from index
    topic_name = entry["name"]
    md_path = _book_dir() / f"{topic_name}.md"
    if not md_path.is_file():
        click.echo(f"{entry['brief']} [{CATEGORY_TAGS[entry['category']]}]", err=True)
        click.echo(f"\nDetail content missing for topic: {topic_name}", err=True)
        raise SystemExit(1)

    text = md_path.read_text(encoding="utf-8")

    if list_sections or section:
        sections = _split_sections(text)
        if list_sections:
            _print_section_list(topic_name, sections)
            return
        found = _find_section(sections, section)
        if found is None:
            click.echo(f"Section not found in '{topic_name}': {section}", err=True)
            _print_section_list(topic_name, sections, err=True)
            raise SystemExit(1)
        # Carry the page's own framing so the fragment still says what it is
        # about; a section injected on its own reads as orphaned otherwise.
        preamble = next((b for h, b in sections if not h), "").splitlines()
        locator = preamble[0] if preamble else f"# {topic_name}"
        click.echo(f"{locator}\n\n## {found[0]}\n\n{found[1]}")
        return

    click.echo(text)


def _print_section_list(topic_name: str, sections: list[tuple[str, str]], err: bool = False):
    click.echo(f"\n{topic_name} — {sum(1 for h, _ in sections if h)} sections\n", err=err)
    for h, b in sections:
        if not h:
            continue
        click.echo(f"  {round(len(b) / 2.2):>5} tok  {h}", err=err)
    click.echo(f"\n取其中一节: frago book {topic_name} --section '<小标题>'", err=err)


def _print_index(entries: list[dict]):
    click.echo("\nfrago Knowledge Book\n")

    # Identity preamble
    identity_path = _book_dir() / "_identity.md"
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
    guidance_path = _book_dir() / "_guidance.md"
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
