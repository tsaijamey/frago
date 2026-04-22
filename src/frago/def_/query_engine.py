"""Query engine for domain documents.

Handles: find (filter/project/sort/limit/count), save (upsert with schema validation).
Document format: YAML frontmatter + content arrays in body.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .schema_validator import validate

logger = logging.getLogger(__name__)


def find(
    domain_dir: Path,
    schema: dict[str, Any],  # noqa: ARG001  reserved for future schema-aware filtering
    filters: dict[str, str] | None = None,
    fields: list[str] | None = None,
    sort_by: str | None = None,
    desc: bool = False,
    limit: int | None = None,
    count_only: bool = False,
) -> str:
    """Query documents in a domain directory.

    Returns formatted output string (designed for minimal token usage).
    """
    if not domain_dir.exists():
        return "No documents (directory not found)"

    docs = _load_all_docs(domain_dir)

    # Filter
    if filters:
        docs = _apply_filters(docs, filters)

    total = len(docs)

    # Sort
    if sort_by:
        docs = sorted(
            docs,
            key=lambda d: d.get("meta", {}).get(sort_by, ""),
            reverse=desc,
        )

    # Count only
    if count_only:
        return f"{total} documents"

    # Limit
    if limit and limit < len(docs):
        docs = docs[:limit]

    if not docs:
        return "No matching documents"

    # Single document: expand entries
    if len(docs) == 1:
        return _format_single_doc(docs[0])

    # Multiple documents: table
    return _format_docs(docs, fields, shown=len(docs), total=total)


def save(
    domain_dir: Path,
    schema: dict[str, Any],
    name: str,
    data: dict[str, Any] | None = None,
    content: list[str] | None = None,
) -> str:
    """Save (upsert) a document to a domain.

    Returns status message.
    Raises ValueError on validation failure.
    """
    domain_dir.mkdir(parents=True, exist_ok=True)

    # Merge name into data
    if data is None:
        data = {}
    data["name"] = name

    # Validate against schema
    errors = validate(schema, data)
    if errors:
        field_info = _format_schema_fields(schema)
        raise ValueError(
            "Validation failed:\n"
            + "\n".join(f"  - {e}" for e in errors)
            + f"\n\nSchema fields:\n{field_info}"
        )

    # Add updated timestamp
    data["updated"] = datetime.now().strftime("%Y-%m-%d")

    file_path = domain_dir / f"{name}.md"
    is_update = file_path.exists()

    # Build document
    frontmatter = yaml.dump(data, default_flow_style=False, allow_unicode=True).strip()
    body = ""
    if content:
        # Content is stored as a YAML array in the body
        body = "\n" + yaml.dump(
            {"entries": content},
            default_flow_style=False,
            allow_unicode=True,
        ).strip()

    doc_content = f"---\n{frontmatter}\n---\n{body}\n"
    file_path.write_text(doc_content, encoding="utf-8")

    action = "Updated" if is_update else "Saved"
    entry_count = len(content) if content else 0
    suffix = f" ({entry_count} entries)" if entry_count else ""
    return f"{action} {file_path}{suffix}"


def get_schema_display(schema: dict[str, Any]) -> str:
    """Format schema fields for display."""
    return _format_schema_fields(schema)


# --- Internal helpers ---


def _parse_entry(line: str) -> dict[str, str]:
    """Parse a single entry with optional relation type markup.

    Format: [[[type]]][[from]][[to]]
    Untagged entries return type=misc.
    """
    if not isinstance(line, str):
        return {"type": "misc", "content": str(line)}

    if line.startswith("[[[") and "]]]" in line:
        type_end = line.index("]]]")
        rel_type = line[3:type_end]
        rest = line[type_end + 3:]
        # Extract [[...]] fields
        parts = []
        while "[[" in rest and "]]" in rest:
            start = rest.index("[[") + 2
            end = rest.index("]]")
            parts.append(rest[start:end])
            rest = rest[end + 2:]
        return {
            "type": rel_type,
            "from": parts[0] if parts else "",
            "to": parts[1] if len(parts) > 1 else "",
        }
    return {"type": "misc", "content": line}


def _format_single_doc(doc: dict[str, Any]) -> str:
    """Format a single document with full entries expanded.

    Entries with relation type markup are grouped by type.
    """
    meta = doc.get("meta", {})
    content = doc.get("content", [])

    lines = []
    # Document name
    name = meta.get("name", doc.get("path", Path("?")).stem)
    lines.append(name)

    # Metadata fields (exclude name)
    for key, value in sorted(meta.items()):
        if key == "name":
            continue
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        lines.append(f"  {key}: {value}")

    if not content:
        return "\n".join(lines)

    # Parse all entries
    parsed = [_parse_entry(entry) for entry in content]

    # Check if any entries have relation types (non-misc)
    has_relations = any(e["type"] != "misc" for e in parsed)

    if not has_relations:
        # All misc: flat list (backward compatible)
        lines.append("")
        for entry in content:
            lines.append(f"  - {entry}")
    else:
        # Group by relation type
        from collections import OrderedDict

        groups: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
        for entry in parsed:
            t = entry["type"]
            if t not in groups:
                groups[t] = []
            groups[t].append(entry)

        for rel_type, entries in groups.items():
            lines.append("")
            lines.append(f"  [{rel_type}]")
            for e in entries:
                if rel_type == "misc":
                    lines.append(f"  - {e['content']}")
                else:
                    lines.append(f"  - {e['from']} → {e['to']}")

    return "\n".join(lines)


def _load_all_docs(domain_dir: Path) -> list[dict[str, Any]]:
    """Load all .md documents from a domain directory."""
    docs = []
    for md_file in sorted(domain_dir.glob("*.md")):
        try:
            doc = _parse_document(md_file)
            if doc:
                docs.append(doc)
        except Exception as e:
            logger.warning("Failed to parse %s: %s", md_file, e)
    return docs


def _parse_document(path: Path) -> dict[str, Any] | None:
    """Parse a YAML frontmatter document.

    Returns {"meta": {frontmatter fields}, "content": [entries], "path": path}
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None

    # Parse body for content entries
    body = parts[2].strip()
    content = []
    if body:
        try:
            body_data = yaml.safe_load(body)
            if isinstance(body_data, dict) and "entries" in body_data:
                content = body_data["entries"]
            elif isinstance(body_data, list):
                content = body_data
        except yaml.YAMLError:
            pass

    return {"meta": meta, "content": content, "path": path}


def _apply_filters(
    docs: list[dict[str, Any]], filters: dict[str, str]
) -> list[dict[str, Any]]:
    """Filter documents by frontmatter field values."""
    result = []
    for doc in docs:
        meta = doc.get("meta", {})
        match = True
        for key, value in filters.items():
            doc_value = meta.get(key)
            if doc_value is None:
                match = False
                break
            # List field: check if value is in the list
            if isinstance(doc_value, list):
                if value not in doc_value:
                    match = False
                    break
            # Scalar: exact match
            elif str(doc_value) != value:
                match = False
                break
        if match:
            result.append(doc)
    return result


def _format_docs(
    docs: list[dict[str, Any]],
    fields: list[str] | None,
    shown: int,
    total: int,
) -> str:
    """Format documents as a compact table."""
    if not docs:
        return "No documents"

    # Determine columns
    all_meta_keys = set()
    for doc in docs:
        all_meta_keys.update(doc.get("meta", {}).keys())

    if fields:
        columns = [f for f in fields if f in all_meta_keys or f == "entries"]
    else:
        # Default: show all frontmatter fields except internal ones
        columns = sorted(all_meta_keys)

    # Build rows
    rows = []
    for doc in docs:
        meta = doc.get("meta", {})
        row = {}
        for col in columns:
            if col == "entries":
                row[col] = str(len(doc.get("content", [])))
            else:
                val = meta.get(col, "-")
                if isinstance(val, list):
                    val = ", ".join(str(v) for v in val)
                row[col] = str(val)
        rows.append(row)

    # Calculate column widths
    col_widths = {}
    for col in columns:
        col_widths[col] = max(
            len(col.upper()),
            max((len(row.get(col, "")) for row in rows), default=0),
        )

    # Format header
    header = "  ".join(col.upper().ljust(col_widths[col]) for col in columns)
    separator = "  ".join("-" * col_widths[col] for col in columns)

    # Format rows
    lines = [header, separator]
    for row in rows:
        line = "  ".join(row.get(col, "-").ljust(col_widths[col]) for col in columns)
        lines.append(line)

    # Footer
    if shown < total:
        lines.append(f"({shown} of {total})")
    else:
        lines.append(f"({total} documents)")

    return "\n".join(lines)


def _format_schema_fields(schema: dict[str, Any]) -> str:
    """Format schema fields as a table."""
    fields = schema.get("fields", [])
    if not fields:
        return "No fields defined"

    lines = []
    lines.append("  FIELD        TYPE       REQUIRED   DESCRIPTION")
    lines.append("  " + "-" * 60)
    for f in fields:
        name = f.get("name", "?")
        ftype = f.get("type", "?")
        if ftype == "enum" and f.get("values"):
            ftype = " | ".join(f["values"])
        req = "yes" if f.get("required") else "no"
        desc = f.get("description", "")
        lines.append(f"  {name:<12s} {ftype:<10s} {req:<10s} {desc}")

    return "\n".join(lines)
