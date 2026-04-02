"""Domain registry — CRUD operations for knowledge domain definitions.

Registry file: ~/.frago/books/registry.json
Each domain maps to a directory: ~/.frago/books/<domain>/
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BOOKS_DIR = Path.home() / ".frago" / "books"
REGISTRY_PATH = BOOKS_DIR / "registry.json"


def _ensure_books_dir() -> None:
    """Ensure ~/.frago/books/ exists."""
    BOOKS_DIR.mkdir(parents=True, exist_ok=True)


def load_registry() -> dict[str, dict[str, Any]]:
    """Load the domain registry. Returns empty dict if missing or corrupt."""
    if not REGISTRY_PATH.exists():
        return {}
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            logger.warning("registry.json is not a dict, treating as empty")
            return {}
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load registry.json: %s", e)
        return {}


def save_registry(registry: dict[str, dict[str, Any]]) -> None:
    """Persist the registry to disk."""
    _ensure_books_dir()
    REGISTRY_PATH.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def add_domain(
    name: str,
    purpose: str,
    schema: dict[str, Any],
) -> Path:
    """Register a new domain and create its directory.

    Returns the domain directory path.
    Raises ValueError on conflict or invalid schema.
    """
    registry = load_registry()

    if name in registry:
        raise ValueError(f"Domain '{name}' already exists. Use 'frago def remove' first.")

    # Validate schema basics
    _validate_schema_definition(schema)

    domain_dir = BOOKS_DIR / name
    domain_dir.mkdir(parents=True, exist_ok=True)

    registry[name] = {
        "purpose": purpose,
        "schema": schema,
        "created": datetime.now().strftime("%Y-%m-%d"),
    }
    save_registry(registry)
    return domain_dir


def remove_domain(name: str) -> None:
    """Unregister a domain (does NOT delete files)."""
    registry = load_registry()
    if name not in registry:
        raise ValueError(f"Domain '{name}' not found.")
    del registry[name]
    save_registry(registry)


def list_domains() -> list[dict[str, Any]]:
    """List all registered domains with document counts."""
    registry = load_registry()
    result = []
    for name, definition in sorted(registry.items()):
        domain_dir = BOOKS_DIR / name
        doc_count = len(list(domain_dir.glob("*.md"))) if domain_dir.exists() else 0
        result.append({
            "name": name,
            "purpose": definition.get("purpose", ""),
            "docs": doc_count,
            "created": definition.get("created", ""),
        })
    return result


def get_domain(name: str) -> dict[str, Any] | None:
    """Get a single domain definition, or None."""
    registry = load_registry()
    return registry.get(name)


def get_domain_dir(name: str) -> Path:
    """Get the directory path for a domain."""
    return BOOKS_DIR / name


def _validate_schema_definition(schema: dict[str, Any]) -> None:
    """Validate a schema definition at registration time."""
    if "fields" not in schema:
        raise ValueError("Schema must have 'fields'.")
    fields = schema["fields"]
    if not isinstance(fields, list):
        raise ValueError("Schema 'fields' must be a list.")
    for field in fields:
        if "name" not in field or "type" not in field:
            raise ValueError(f"Each field must have 'name' and 'type'. Got: {field}")
        ftype = field["type"]
        valid_types = {"string", "enum", "list", "date"}
        if ftype not in valid_types:
            raise ValueError(f"Field type must be one of {valid_types}. Got: '{ftype}'")
        if ftype == "enum" and not field.get("values"):
            raise ValueError(f"Enum field '{field['name']}' must define 'values'.")
