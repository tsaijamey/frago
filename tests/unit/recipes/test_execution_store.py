"""Tests for ExecutionStore persistence."""

import json
import pytest
from pathlib import Path

from frago.recipes.execution import Execution, ExecutionStatus
from frago.recipes.execution_store import ExecutionStore, MAX_STORED_DATA_SIZE, AUTO_CLEANUP_INTERVAL, AUTO_CLEANUP_MAX_COUNT


@pytest.fixture
def store(tmp_path):
    return ExecutionStore(store_dir=tmp_path / "executions")


class TestExecutionStore:
    def test_create_and_get(self, store):
        ex = store.create(recipe_name="test", params={"k": "v"}, source="cli")
        assert ex.status == ExecutionStatus.PENDING
        assert ex.id.startswith("exec_")

        loaded = store.get(ex.id)
        assert loaded is not None
        assert loaded.id == ex.id
        assert loaded.recipe_name == "test"
        assert loaded.params == {"k": "v"}

    def test_transition(self, store):
        ex = store.create(recipe_name="test", params={})
        store.transition(ex.id, ExecutionStatus.RUNNING)

        loaded = store.get(ex.id)
        assert loaded.status == ExecutionStatus.RUNNING
        assert loaded.started_at is not None

    def test_complete_succeeded(self, store):
        ex = store.create(recipe_name="test", params={})
        store.transition(ex.id, ExecutionStatus.RUNNING)
        store.complete(
            ex.id,
            status=ExecutionStatus.SUCCEEDED,
            data={"result": "ok"},
            exit_code=0,
            duration_ms=1234,
            runtime="python",
        )

        loaded = store.get(ex.id)
        assert loaded.status == ExecutionStatus.SUCCEEDED
        assert loaded.data == {"result": "ok"}
        assert loaded.exit_code == 0
        assert loaded.duration_ms == 1234
        assert loaded.completed_at is not None

    def test_complete_failed(self, store):
        ex = store.create(recipe_name="test", params={})
        store.transition(ex.id, ExecutionStatus.RUNNING)
        store.complete(
            ex.id,
            status=ExecutionStatus.FAILED,
            error={"code": "ERR", "message": "boom"},
            exit_code=1,
            duration_ms=500,
        )

        loaded = store.get(ex.id)
        assert loaded.status == ExecutionStatus.FAILED
        assert loaded.error["message"] == "boom"

    def test_get_nonexistent_returns_none(self, store):
        assert store.get("exec_nonexistent") is None

    def test_transition_nonexistent_raises(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.transition("exec_nonexistent", ExecutionStatus.RUNNING)

    def test_list_recent(self, store):
        for i in range(5):
            ex = store.create(recipe_name=f"recipe_{i}", params={})
            store.transition(ex.id, ExecutionStatus.RUNNING)
            store.complete(ex.id, status=ExecutionStatus.SUCCEEDED, exit_code=0, duration_ms=100)

        results = store.list_recent(limit=3)
        assert len(results) == 3

    def test_list_recent_filter_by_recipe(self, store):
        store.create(recipe_name="a", params={})
        store.create(recipe_name="b", params={})
        store.create(recipe_name="a", params={})

        results = store.list_recent(recipe_name="a")
        assert len(results) == 2
        assert all(e.recipe_name == "a" for e in results)

    def test_list_recent_filter_by_status(self, store):
        ex1 = store.create(recipe_name="test", params={})
        store.transition(ex1.id, ExecutionStatus.RUNNING)
        store.complete(ex1.id, status=ExecutionStatus.SUCCEEDED, exit_code=0, duration_ms=100)

        ex2 = store.create(recipe_name="test", params={})
        store.transition(ex2.id, ExecutionStatus.RUNNING)
        store.complete(ex2.id, status=ExecutionStatus.FAILED, exit_code=1, duration_ms=100)

        succeeded = store.list_recent(status=ExecutionStatus.SUCCEEDED)
        assert len(succeeded) == 1
        assert succeeded[0].status == ExecutionStatus.SUCCEEDED

    def test_truncate_large_data(self, store):
        ex = store.create(recipe_name="test", params={})
        store.transition(ex.id, ExecutionStatus.RUNNING)

        large_data = {"big": "x" * (MAX_STORED_DATA_SIZE + 1000)}
        store.complete(ex.id, status=ExecutionStatus.SUCCEEDED, data=large_data, exit_code=0, duration_ms=100)

        loaded = store.get(ex.id)
        assert loaded.data.get("_truncated") is True

    def test_index_file_created(self, store):
        store.create(recipe_name="test", params={})
        assert store.index_file.exists()
        index = json.loads(store.index_file.read_text())
        assert len(index) == 1

    def test_cleanup(self, store):
        for i in range(10):
            store.create(recipe_name=f"recipe_{i}", params={})

        removed = store.cleanup(max_count=5)
        assert removed == 5

        index = json.loads(store.index_file.read_text())
        assert len(index) == 5

    def test_auto_cleanup_triggers_periodically(self, store):
        # Verify _maybe_cleanup is called from create() by checking counter
        assert store._create_count == 0
        store.create(recipe_name="a", params={})
        assert store._create_count == 1
        store.create(recipe_name="b", params={})
        assert store._create_count == 2

        # Verify cleanup fires at interval boundary without error
        store._create_count = AUTO_CLEANUP_INTERVAL - 1
        store.create(recipe_name="trigger", params={})
        assert store._create_count == AUTO_CLEANUP_INTERVAL

    def test_file_stored_in_month_directory(self, store):
        ex = store.create(recipe_name="test", params={})
        year = ex.created_at.year
        month = f"{ex.created_at.month:02d}"
        expected_dir = store.store_dir / str(year) / month
        expected_file = expected_dir / f"{ex.id}.json"
        assert expected_file.exists()

    def test_index_includes_workflow_id(self, store):
        store.create(recipe_name="step1", params={}, workflow_id="exec_wf001")
        index = json.loads(store.index_file.read_text())
        assert index[0]["workflow_id"] == "exec_wf001"

    def test_index_workflow_id_null_when_not_set(self, store):
        store.create(recipe_name="standalone", params={})
        index = json.loads(store.index_file.read_text())
        assert index[0]["workflow_id"] is None

    def test_list_by_workflow(self, store):
        wf_id = "exec_wf123"
        # Create 3 steps in a workflow + 1 standalone
        for i in range(3):
            store.create(recipe_name=f"step_{i}", params={}, workflow_id=wf_id, step_index=i)
        store.create(recipe_name="standalone", params={})

        results = store.list_by_workflow(wf_id)
        assert len(results) == 3
        assert all(e.workflow_id == wf_id for e in results)
        # Verify sorted by step_index
        assert [e.step_index for e in results] == [0, 1, 2]

    def test_list_by_workflow_empty(self, store):
        store.create(recipe_name="standalone", params={})
        results = store.list_by_workflow("exec_nonexistent")
        assert results == []

    def test_list_by_workflow_sorts_nulls_last(self, store):
        wf_id = "exec_wf_mixed"
        store.create(recipe_name="with_idx", params={}, workflow_id=wf_id, step_index=1)
        store.create(recipe_name="no_idx", params={}, workflow_id=wf_id)
        store.create(recipe_name="with_idx_0", params={}, workflow_id=wf_id, step_index=0)

        results = store.list_by_workflow(wf_id)
        assert len(results) == 3
        assert results[0].step_index == 0
        assert results[1].step_index == 1
        assert results[2].step_index is None
