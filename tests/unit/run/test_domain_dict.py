"""Phase 3 tests — domain_dict lookup + create_run dictionary integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from frago.run import domain_dict as dd
from frago.run.manager import RunManager


def _seed_dict(tmp_books: Path, entries: dict[str, list[str]]) -> None:
    """Drop fake domain_dict docs into a temp ~/.frago/books layout."""
    domain_dir = tmp_books / "domain_dict"
    domain_dir.mkdir(parents=True, exist_ok=True)
    for name, aliases in entries.items():
        body = "---\n"
        body += f"name: {name}\n"
        body += "aliases:\n"
        for a in aliases:
            body += f"- {a}\n"
        body += "---\n"
        (domain_dir / f"{name}.md").write_text(body, encoding="utf-8")


@pytest.fixture
def patched_books(tmp_path, monkeypatch):
    books_root = tmp_path / "books"
    monkeypatch.setattr(
        "frago.def_.registry.BOOKS_DIR", books_root, raising=True
    )
    return books_root


# --------------------------------------------------------------------- #
# alias matching
# --------------------------------------------------------------------- #

def test_lookup_chinese_alias_substring(patched_books):
    _seed_dict(patched_books, {"twitter": ["twitter", "推特", "X"]})
    assert dd.lookup_domain("我想看看 推特 上的热点") == "twitter"


def test_lookup_ascii_word_boundary(patched_books):
    _seed_dict(patched_books, {"twitter": ["twi", "twitter"]})
    # "twi" should NOT match the substring inside "twin"
    assert dd.lookup_domain("twin peaks story") is None
    # but should match as a whole word
    assert dd.lookup_domain("the twi shortcut") == "twitter"


def test_lookup_uppercase_alias_case_insensitive(patched_books):
    _seed_dict(patched_books, {"hn": ["hackernews", "HN", "hacker news"]})
    assert dd.lookup_domain("hot on Hacker News today") == "hn"


def test_lookup_no_match_returns_none(patched_books):
    _seed_dict(patched_books, {"twitter": ["推特"]})
    assert dd.lookup_domain("research on llama models") is None


def test_lookup_multi_match_collapses_to_cross(patched_books):
    _seed_dict(
        patched_books,
        {
            "twitter": ["推特", "twitter"],
            "feishu": ["飞书"],
        },
    )
    out = dd.lookup_domain("把 推特 内容同步到 飞书")
    assert out == "CROSS-feishu-twitter"  # sorted alphabetically


def test_lookup_empty_description_returns_none(patched_books):
    _seed_dict(patched_books, {"twitter": ["推特"]})
    assert dd.lookup_domain("") is None
    assert dd.lookup_domain(None) is None  # type: ignore[arg-type]


def test_list_aliases_returns_known(patched_books):
    _seed_dict(patched_books, {"hn": ["hn", "hacker news"]})
    assert sorted(dd.list_aliases("hn")) == ["hacker news", "hn"]
    assert dd.list_aliases("missing") == []


def test_lookup_when_dict_missing(patched_books):
    # No domain_dict folder seeded — lookup must gracefully return None
    assert dd.lookup_domain("anything") is None


# --------------------------------------------------------------------- #
# RunManager.create_run integration
# --------------------------------------------------------------------- #

def test_create_run_uses_dict_canonical(tmp_path, patched_books):
    _seed_dict(patched_books, {"twitter": ["推特", "twitter"]})

    projects_dir = tmp_path / "projects"
    manager = RunManager(projects_dir)

    instance = manager.create_run("我想看看 推特 上的新动态")
    assert instance.run_id == "twitter"
    assert instance.domain == "twitter"
    # alias cache populated from dict
    assert "推特" in instance.aliases


def test_create_run_falls_back_to_slug(tmp_path, patched_books):
    _seed_dict(patched_books, {"twitter": ["推特"]})

    projects_dir = tmp_path / "projects"
    manager = RunManager(projects_dir)

    instance = manager.create_run("explore the rust borrow checker")
    # No alias hit → slug
    assert instance.run_id == "explore-the-rust-borrow-checker"


def test_create_run_explicit_run_id_skips_lookup(tmp_path, patched_books):
    _seed_dict(patched_books, {"twitter": ["推特"]})

    projects_dir = tmp_path / "projects"
    manager = RunManager(projects_dir)

    # description mentions 推特 but caller pinned run_id → use that
    instance = manager.create_run("推特 任务", run_id="custom-domain")
    assert instance.run_id == "custom-domain"


def test_create_run_multi_match_creates_cross(tmp_path, patched_books):
    _seed_dict(
        patched_books,
        {
            "twitter": ["推特"],
            "feishu": ["飞书"],
        },
    )

    projects_dir = tmp_path / "projects"
    manager = RunManager(projects_dir)

    instance = manager.create_run("从 推特 抓内容同步到 飞书")
    assert instance.run_id.startswith("CROSS-")
    assert instance.is_cross_domain is True
    assert sorted(instance.component_domains) == ["feishu", "twitter"]
