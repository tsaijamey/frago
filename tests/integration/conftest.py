"""Integration test fixtures.

These fixtures create real file system structures for e2e testing.
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.fixture
def frago_home(tmp_path: Path) -> Path:
    """Create isolated ~/.frago directory structure."""
    frago_dir = tmp_path / ".frago"
    (frago_dir / "sessions" / "claude").mkdir(parents=True)
    # Registry scans atomic/system/, atomic/chrome/, and workflows/
    (frago_dir / "recipes" / "atomic" / "system").mkdir(parents=True)
    (frago_dir / "recipes" / "atomic" / "chrome").mkdir(parents=True)
    (frago_dir / "recipes" / "workflows").mkdir(parents=True)
    (frago_dir / "config.json").write_text("{}")
    return tmp_path


@pytest.fixture
def claude_projects(tmp_path: Path) -> Path:
    """Create isolated ~/.claude/projects directory structure."""
    projects_dir = tmp_path / ".claude" / "projects"
    projects_dir.mkdir(parents=True)
    return projects_dir


@pytest.fixture
def sample_session_file(claude_projects: Path) -> tuple[Path, str]:
    """Create a sample Claude Code session file.
    
    Returns:
        Tuple of (file_path, session_id)
    """
    session_id = str(uuid.uuid4())
    project_dir = claude_projects / "-home-user-project"
    project_dir.mkdir(parents=True)
    
    session_file = project_dir / f"{session_id}.jsonl"
    
    # Create realistic session records
    now = datetime.now(timezone.utc).isoformat()
    records = [
        {
            "type": "user",
            "sessionId": session_id,
            "timestamp": now,
            "message": {"content": "Hello, can you help me?"},
        },
        {
            "type": "assistant",
            "sessionId": session_id,
            "timestamp": now,
            "message": {
                "content": [
                    {"type": "text", "text": "Of course! How can I help you?"}
                ]
            },
        },
        {
            "type": "assistant",
            "sessionId": session_id,
            "timestamp": now,
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Read", "input": {"path": "/tmp/test.py"}}
                ]
            },
        },
    ]
    
    with open(session_file, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    
    return session_file, session_id


@pytest.fixture
def sample_recipe(frago_home: Path) -> Path:
    """Create a sample recipe in the user recipes directory.

    Returns:
        Path to the recipe directory
    """
    # Registry expects recipes in atomic/system/ or atomic/chrome/
    recipe_dir = frago_home / ".frago" / "recipes" / "atomic" / "system" / "test-recipe"
    recipe_dir.mkdir(parents=True)

    # Registry expects recipe.md as metadata file with all required fields
    metadata_content = """---
name: test-recipe
description: A test recipe for integration testing
type: atomic
runtime: python
version: 1.0.0
use_cases:
  - Testing recipe registry
output_targets:
  - stdout
tags:
  - test
  - integration
---
"""
    (recipe_dir / "recipe.md").write_text(metadata_content)

    # Create recipe.py
    recipe_script = '''"""Test recipe script."""

async def run(context):
    """Execute the test recipe."""
    return {"status": "ok", "message": "Test completed"}
'''
    (recipe_dir / "recipe.py").write_text(recipe_script)

    return recipe_dir


@pytest.fixture
def multiple_recipes(frago_home: Path) -> list[Path]:
    """Create multiple recipes for testing registry scanning.

    Returns:
        List of recipe directory paths
    """
    recipes = []
    # Registry expects recipes in atomic/system/
    recipe_base = frago_home / ".frago" / "recipes" / "atomic" / "system"
    recipe_base.mkdir(parents=True, exist_ok=True)

    for i, name in enumerate(["recipe-alpha", "recipe-beta", "recipe-gamma"]):
        recipe_dir = recipe_base / name
        recipe_dir.mkdir(parents=True)

        # Use recipe.md with YAML frontmatter (all required fields)
        metadata = f"""---
name: {name}
description: Recipe {name} for testing
type: atomic
runtime: python
version: 1.0.{i}
use_cases:
  - Testing recipe registry
output_targets:
  - stdout
tags:
  - test
---
"""
        (recipe_dir / "recipe.md").write_text(metadata)
        (recipe_dir / "recipe.py").write_text(f'"""Recipe {name}"""\n')

        recipes.append(recipe_dir)

    return recipes
