"""Tests for Windows Smart App Control detection.

The point of the feature is that a blocked binary reports nothing, so these
tests pin the one thing that makes the failure visible: whether a warning is
produced, and on which state.
"""

from __future__ import annotations

import sys

import pytest

from frago.init import app_control
from frago.init.app_control import (
    SAC_ENFORCING,
    SAC_EVALUATION,
    SAC_OFF,
    smart_app_control_state,
    smart_app_control_warning,
)


class FakeKey:
    def __enter__(self) -> FakeKey:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False


class FakeWinreg:
    """Just enough of the winreg surface for the read path."""

    HKEY_LOCAL_MACHINE = object()

    def __init__(self, value: object) -> None:
        self.value = value
        self.opened: list[str] = []

    def OpenKey(self, _root: object, sub_key: str) -> FakeKey:  # noqa: N802
        self.opened.append(sub_key)
        if isinstance(self.value, OSError):
            raise self.value
        return FakeKey()

    def QueryValueEx(self, _key: FakeKey, _name: str) -> tuple[object, int]:  # noqa: N802
        return self.value, 4


@pytest.fixture
def on_windows(monkeypatch: pytest.MonkeyPatch):
    """Present as Windows and let each test supply the registry value."""

    monkeypatch.setattr(app_control.platform, "system", lambda: "Windows")

    def use(value: object) -> FakeWinreg:
        fake = FakeWinreg(value)
        monkeypatch.setitem(sys.modules, "winreg", fake)
        return fake

    return use


class TestSmartAppControlState:
    def test_non_windows_asks_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The registry does not exist off Windows; no probing, no failing."""
        monkeypatch.setattr(app_control.platform, "system", lambda: "Linux")
        monkeypatch.setitem(sys.modules, "winreg", FakeWinreg(SAC_ENFORCING))

        assert smart_app_control_state() is None

    @pytest.mark.parametrize("state", [SAC_OFF, SAC_ENFORCING, SAC_EVALUATION])
    def test_reads_the_policy_value(self, on_windows, state: int) -> None:
        fake = on_windows(state)

        assert smart_app_control_state() == state
        assert fake.opened == [app_control._CI_POLICY_KEY]

    def test_absent_value_is_not_an_error(self, on_windows) -> None:
        """Windows builds predating the feature simply have no such value."""
        on_windows(FileNotFoundError("no such key"))

        assert smart_app_control_state() is None

    def test_unreadable_key_is_not_an_error(self, on_windows) -> None:
        on_windows(PermissionError("denied"))

        assert smart_app_control_state() is None

    def test_non_integer_value_is_ignored(self, on_windows) -> None:
        on_windows("1")

        assert smart_app_control_state() is None


class TestSmartAppControlWarning:
    def test_warns_when_enforcing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            app_control, "smart_app_control_state", lambda: SAC_ENFORCING
        )

        warning = smart_app_control_warning()

        assert warning is not None
        # the two things the reader cannot work out alone: that failures are
        # silent, and where the switch is
        assert "silently" in warning
        assert "Windows Security" in warning

    @pytest.mark.parametrize("state", [SAC_OFF, SAC_EVALUATION, None])
    def test_silent_otherwise(
        self, monkeypatch: pytest.MonkeyPatch, state: int | None
    ) -> None:
        """Evaluation mode audits without blocking — warning there cries wolf."""
        monkeypatch.setattr(app_control, "smart_app_control_state", lambda: state)

        assert smart_app_control_warning() is None
