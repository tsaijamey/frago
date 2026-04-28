"""Domain dictionary lookup (Phase 3).

Reads ``~/.frago/books/domain_dict/*.md`` (managed by ``frago def`` system)
and resolves a free-form description into a canonical domain name.

Match semantics:
  * Each domain_dict doc has frontmatter with ``name`` (canonical) and
    ``aliases`` (list of strings).
  * An alias matches a description when the (case-insensitive) alias string
    appears as a substring of the (case-insensitive) description, OR matches
    a whole word for short ASCII aliases (avoids ``twitter`` matching ``twi``
    inside ``twin``). For Chinese aliases plain substring is used.
  * Zero alias hit → None (caller falls back to slug).
  * One canonical name hit → that name.
  * Multiple distinct canonical names hit → ``CROSS-<a>-<b>...`` (sorted).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List, Optional


_ASCII_RE = re.compile(r"^[A-Za-z0-9_.\- ]+$")


def _alias_hits(alias: str, description: str) -> bool:
    if not alias or not description:
        return False
    a = alias.strip()
    if not a:
        return False
    desc_l = description.lower()
    a_l = a.lower()
    if _ASCII_RE.match(a):
        # ASCII alias: word-boundary match to avoid ``twi`` matching ``twin``
        pattern = r"(?:^|[^a-z0-9])" + re.escape(a_l) + r"(?:$|[^a-z0-9])"
        return re.search(pattern, desc_l) is not None
    # Non-ASCII (e.g. Chinese): simple substring
    return a_l in desc_l


def _load_dict_docs() -> List[dict[str, Any]]:
    """Load all domain_dict documents via the def query_engine.

    Returns a list of {"name": str, "aliases": list[str]} dicts.
    Empty list when the domain is not registered yet — caller should
    treat as "no match".
    """
    try:
        from frago.def_.query_engine import _load_all_docs
        from frago.def_.registry import get_domain_dir
    except Exception:
        return []

    domain_dir = get_domain_dir("domain_dict")
    if not domain_dir.exists():
        return []

    out: List[dict[str, Any]] = []
    for doc in _load_all_docs(domain_dir):
        meta = doc.get("meta", {}) or {}
        name = meta.get("name")
        aliases = meta.get("aliases") or []
        if not name or not isinstance(aliases, list):
            continue
        out.append({"name": str(name), "aliases": [str(a) for a in aliases]})
    return out


def lookup_domain(description: str) -> Optional[str]:
    """Resolve ``description`` to a canonical domain via the dict.

    Returns:
        * ``None`` when no alias matches (caller should fall back to slug
          new-domain creation).
        * A canonical domain name (e.g. ``"twitter"``) when exactly one
          canonical name has a hit.
        * ``"CROSS-<a>-<b>..."`` (sorted) when multiple canonical names hit.
    """
    if not description:
        return None
    docs = _load_dict_docs()
    if not docs:
        return None
    hits = []
    for doc in docs:
        for alias in doc["aliases"]:
            if _alias_hits(alias, description):
                hits.append(doc["name"])
                break
    hits = sorted(set(hits))
    if not hits:
        return None
    if len(hits) == 1:
        return str(hits[0])
    return "CROSS-" + "-".join(hits)


def list_aliases(canonical: str) -> List[str]:
    """Return the alias list for a canonical domain (empty if not registered)."""
    for doc in _load_dict_docs():
        if doc["name"] == canonical:
            return list(doc["aliases"])
    return []


def all_canonical_names() -> List[str]:
    """Return all canonical domain names from the dict (sorted)."""
    return sorted(doc["name"] for doc in _load_dict_docs())


def list_canonical_domains() -> List[str]:
    """Alias for ``all_canonical_names`` (spec-named entry)."""
    return all_canonical_names()


def projects_dir_default() -> Path:
    """Return the default projects directory (``~/.frago/projects``)."""
    return Path.home() / ".frago" / "projects"
