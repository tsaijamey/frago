"""Architectural contract tests — anchors import-linter results to pytest.

Phase 0: report-only. Tests never fail the suite based on violation count.
The goal is to keep contract evaluation routinely exercised so that:
  1. CI surfaces lint-imports invocation breakage immediately.
  2. The violation trend is observable from pytest output.
  3. tests/arch/ exists as the home for stricter assertions in Phase 7+.

Phase 7 will replace the report-only assertion with a strict pass requirement.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _has_lint_imports() -> bool:
    return shutil.which("lint-imports") is not None


@pytest.mark.skipif(
    not _has_lint_imports(),
    reason="import-linter not installed; install dev deps with `uv sync --extra dev`",
)
def test_import_linter_runs() -> None:
    """import-linter must execute without crashing.

    Phase 0: we accept any exit code (contracts may have violations during
    refactor). We only assert the tool ran and produced output.
    """
    result = subprocess.run(
        ["lint-imports"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # Phase 0: report-only. Both pass (0) and contracts-broken (1) are acceptable.
    # Only crashes (negative or >2) indicate a config/wiring problem.
    assert result.returncode in (0, 1), (
        f"lint-imports crashed with code {result.returncode}\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert result.stdout.strip() or result.stderr.strip(), (
        "lint-imports produced no output — config likely broken"
    )


def test_north_star_doc_exists() -> None:
    """The north-star architecture doc must exist as the contract source-of-truth."""
    doc = REPO_ROOT / ".claude" / "docs" / "architecture-north-star.md"
    assert doc.exists(), f"Missing north-star doc at {doc}"


def test_importlinter_config_exists() -> None:
    """The .importlinter config must exist."""
    cfg = REPO_ROOT / ".importlinter"
    assert cfg.exists(), f"Missing import-linter config at {cfg}"


def test_check_arch_script_exists() -> None:
    """Convenience entrypoint must exist and be executable."""
    script = REPO_ROOT / "scripts" / "check_arch.sh"
    assert script.exists()
    # Executable bit set
    import os
    assert os.access(script, os.X_OK), f"{script} not executable"
