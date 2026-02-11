"""Recipe usage tracking.

Lightweight module to record recipe execution counts and timestamps.
Used by the dashboard to show "Quick Recipes" sorted by recent usage.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

USAGE_FILE = Path.home() / ".frago" / "recipe_usage.json"


def _load_usage() -> Dict[str, Any]:
    """Load usage data from disk."""
    if not USAGE_FILE.exists():
        return {}
    try:
        content = USAGE_FILE.read_text(encoding="utf-8")
        data = json.loads(content)
        if isinstance(data, dict):
            return data
        return {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load recipe usage data: %s", e)
        return {}


def _save_usage(data: Dict[str, Any]) -> None:
    """Save usage data to disk."""
    try:
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(data, indent=2, ensure_ascii=False)
        USAGE_FILE.write_text(content, encoding="utf-8")
    except OSError as e:
        logger.warning("Failed to save recipe usage data: %s", e)


def record_usage(recipe_name: str) -> None:
    """Record a recipe execution. Call after successful run."""
    data = _load_usage()
    entry = data.get(recipe_name, {"run_count": 0, "last_used": None})
    entry["run_count"] = entry.get("run_count", 0) + 1
    entry["last_used"] = datetime.now(timezone.utc).isoformat()
    data[recipe_name] = entry
    _save_usage(data)


def get_usage(recipe_name: str) -> Dict[str, Any]:
    """Return usage info for a single recipe."""
    data = _load_usage()
    return data.get(recipe_name, {"run_count": 0, "last_used": None})


def get_top_recipes(limit: int = 5) -> List[str]:
    """Return recipe names sorted by last_used descending."""
    data = _load_usage()
    # Sort by last_used, treating None as oldest
    sorted_entries = sorted(
        data.items(),
        key=lambda item: item[1].get("last_used") or "",
        reverse=True,
    )
    return [name for name, _ in sorted_entries[:limit]]
