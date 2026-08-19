"""Every run stands somewhere the platform chose.

The bug these tests exist for looks like this: a recipe writes a file, works
perfectly on its author's machine for months, gets copied to a server, and the
page it serves is empty. Nothing errored on the way — the recipe had named an
absolute path, because a recipe that wants to keep a file has always had to name
one, and the only path its author could name was one on their own disk.

So the platform hands every run a directory and starts the process inside it.
These tests pin the two halves of that: which directory each kind of run gets,
and that a recipe writing a plain relative path really does land there.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from frago.recipes import context
from frago.recipes.context import InvocationContext, OWNER_SLOT


def test_owner_run_gets_its_own_slot_under_the_shared_root(tmp_path, monkeypatch):
    """The owner is an account like any other, so the rule stays one rule."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    target = context.working_dir("astock_trade_history", context.OWNER_CONTEXT)

    assert target == tmp_path / ".frago" / "users" / OWNER_SLOT / "data" / "astock_trade_history"


def test_owner_slot_cannot_collide_with_an_account_id():
    """Account ids are 32 hex characters; a word is not one."""
    assert not all(c in "0123456789abcdef" for c in OWNER_SLOT)


def test_visitor_run_keeps_the_directory_the_platform_already_computed(tmp_path):
    """Visitor isolation is decided upstream; this must not second-guess it."""
    theirs = tmp_path / "users" / "72cae9b96ef939a4f0616199bac89a7e" / "data" / "trial"
    ctx = InvocationContext(caller=context.VISITOR, slot="72cae9b96ef939a4f0616199bac89a7e", data_dir=theirs)

    assert context.working_dir("trial", ctx) == theirs


def test_no_context_is_treated_as_the_owner(tmp_path, monkeypatch):
    """Every run that predates this module passes None, and must still work."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert context.working_dir("whatever", None).parent.name == "data"


def test_prepare_creates_the_directory_so_the_recipe_never_has_to(tmp_path, monkeypatch):
    """A recipe that has to create its directory can create the wrong one."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    target = context.prepare_working_dir("brand_new_recipe", context.OWNER_CONTEXT)

    assert target.is_dir()


def test_owner_run_still_carries_no_data_dir_variable(tmp_path, monkeypatch):
    """Standing somewhere is not the same as being told where to write.

    Recipes that read ``FRAGO_RECIPE_DATA_DIR`` have their own default behind
    it. Setting the variable on an owner run would silently relocate output that
    has been landing in one place for months, which is the exact class of
    accident this work exists to remove — so the variable stays visitor-only.
    """
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    env = {"FRAGO_RECIPE_CALLER": "visitor", "FRAGO_RECIPE_SLOT": "x", "FRAGO_RECIPE_DATA_DIR": "/leaked"}

    context.apply_to_env(env, context.OWNER_CONTEXT)

    assert "FRAGO_RECIPE_DATA_DIR" not in env
    assert context.working_dir("r", context.OWNER_CONTEXT).is_absolute()


def test_a_relative_write_lands_in_the_prepared_directory(tmp_path):
    """The whole point, end to end: no variable read, no path named, still correct."""
    script = tmp_path / "recipe.py"
    script.write_text(
        "import json, pathlib\n"
        "pathlib.Path('ledger.json').write_text('{}')\n"
        "print(json.dumps({'success': True}))\n",
        encoding="utf-8",
    )
    workdir = tmp_path / "prepared"
    workdir.mkdir()

    result = subprocess.run(
        [sys.executable, str(script), "{}"],
        capture_output=True, text=True, cwd=str(workdir), env={**os.environ},
    )

    assert result.returncode == 0, result.stderr
    assert (workdir / "ledger.json").exists()
    assert not (tmp_path / "ledger.json").exists()


def test_runner_passes_the_prepared_directory_to_the_process(tmp_path, monkeypatch):
    """Plumbing check: the directory reaches subprocess, not just the resolver."""
    from frago.recipes import runner as runner_module

    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cwd"] = kwargs.get("cwd")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout='{"success": true}', stderr="")

    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)

    script = tmp_path / "r.py"
    script.write_text("print('{}')", encoding="utf-8")
    instance = runner_module.RecipeRunner.__new__(runner_module.RecipeRunner)

    instance._run_python("r", script, {}, {}, use_system_python=True, cwd=str(tmp_path))

    assert seen["cwd"] == str(tmp_path)
