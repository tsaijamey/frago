"""Tests for Execution model and state machine."""

import pytest
from datetime import datetime, timezone

from frago.recipes.execution import (
    Execution,
    ExecutionStatus,
    InvalidTransitionError,
    VALID_TRANSITIONS,
)


class TestExecutionStatus:
    def test_all_statuses_have_transitions(self):
        for status in ExecutionStatus:
            assert status in VALID_TRANSITIONS

    def test_terminal_states_have_no_transitions(self):
        for status in [ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED,
                       ExecutionStatus.TIMEOUT, ExecutionStatus.CANCELLED]:
            assert VALID_TRANSITIONS[status] == set()

    def test_pending_can_transition_to_running_or_cancelled(self):
        assert VALID_TRANSITIONS[ExecutionStatus.PENDING] == {
            ExecutionStatus.RUNNING, ExecutionStatus.CANCELLED
        }

    def test_running_can_transition_to_terminal_states(self):
        assert VALID_TRANSITIONS[ExecutionStatus.RUNNING] == {
            ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED,
            ExecutionStatus.TIMEOUT, ExecutionStatus.CANCELLED,
        }


class TestExecution:
    def test_create_factory(self):
        ex = Execution.create(
            recipe_name="test_recipe",
            params={"key": "value"},
            source="cli",
            timeout_seconds=60,
        )
        assert ex.id.startswith("exec_")
        assert ex.recipe_name == "test_recipe"
        assert ex.status == ExecutionStatus.PENDING
        assert ex.params == {"key": "value"}
        assert ex.source == "cli"
        assert ex.timeout_seconds == 60
        assert ex.created_at is not None

    def test_transition_pending_to_running(self):
        ex = Execution.create(recipe_name="r", params={})
        ex.transition_to(ExecutionStatus.RUNNING)
        assert ex.status == ExecutionStatus.RUNNING
        assert ex.started_at is not None

    def test_transition_running_to_succeeded(self):
        ex = Execution.create(recipe_name="r", params={})
        ex.transition_to(ExecutionStatus.RUNNING)
        ex.transition_to(ExecutionStatus.SUCCEEDED)
        assert ex.status == ExecutionStatus.SUCCEEDED

    def test_invalid_transition_raises(self):
        ex = Execution.create(recipe_name="r", params={})
        with pytest.raises(InvalidTransitionError):
            ex.transition_to(ExecutionStatus.SUCCEEDED)  # PENDING -> SUCCEEDED is invalid

    def test_terminal_state_cannot_transition(self):
        ex = Execution.create(recipe_name="r", params={})
        ex.transition_to(ExecutionStatus.RUNNING)
        ex.transition_to(ExecutionStatus.FAILED)
        with pytest.raises(InvalidTransitionError):
            ex.transition_to(ExecutionStatus.RUNNING)

    def test_is_terminal(self):
        ex = Execution.create(recipe_name="r", params={})
        assert not ex.is_terminal()
        ex.transition_to(ExecutionStatus.RUNNING)
        assert not ex.is_terminal()
        ex.transition_to(ExecutionStatus.SUCCEEDED)
        assert ex.is_terminal()

    def test_to_dict_and_from_dict_roundtrip(self):
        ex = Execution.create(
            recipe_name="test",
            params={"a": 1},
            source="cli",
            timeout_seconds=30,
        )
        ex.transition_to(ExecutionStatus.RUNNING)

        d = ex.to_dict()
        assert d["id"] == ex.id
        assert d["status"] == "running"
        assert d["recipe_name"] == "test"

        restored = Execution.from_dict(d)
        assert restored.id == ex.id
        assert restored.status == ExecutionStatus.RUNNING
        assert restored.params == {"a": 1}
        assert restored.started_at is not None

    def test_cancel_from_pending(self):
        ex = Execution.create(recipe_name="r", params={})
        ex.transition_to(ExecutionStatus.CANCELLED)
        assert ex.status == ExecutionStatus.CANCELLED

    def test_cancel_from_running(self):
        ex = Execution.create(recipe_name="r", params={})
        ex.transition_to(ExecutionStatus.RUNNING)
        ex.transition_to(ExecutionStatus.CANCELLED)
        assert ex.status == ExecutionStatus.CANCELLED

    def test_timeout_from_running(self):
        ex = Execution.create(recipe_name="r", params={})
        ex.transition_to(ExecutionStatus.RUNNING)
        ex.transition_to(ExecutionStatus.TIMEOUT)
        assert ex.status == ExecutionStatus.TIMEOUT
