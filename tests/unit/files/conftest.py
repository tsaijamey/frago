"""A whole home directory per test.

Everything in ``frago.files`` is anchored on ``Path.home()`` — the trash and
every rule in the guard — so a test that does not move the home directory is a
test that deletes the developer's files into the developer's trash. Moving
``HOME`` moves both at once, which is also the point: the modules read it live
rather than caching it at import, and this fixture is what keeps that true.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    place = tmp_path / "home"
    (place / ".frago").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(place))
    monkeypatch.setenv("USERPROFILE", str(place))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("FRAGO_RECIPE_NAME", raising=False)
    return place


@pytest.fixture
def work(home: Path) -> Path:
    """An ordinary directory to operate in, outside every protected tree."""
    place = home / "work"
    place.mkdir()
    return place
