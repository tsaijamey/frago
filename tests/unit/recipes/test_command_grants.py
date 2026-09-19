"""Outside commands a recipe declares, and what this machine lets each one see.

CoreAgent is never called here. What is tested is everything around it: when it
is asked, what is done with its answer, where the answer is kept, and what a run
gets from it. ``audit`` itself is replaced wherever a question would be asked.
"""

import json

import pytest

from frago.recipes import command_grants, isolation
from frago.recipes.app_state import GRANTS_FILE, grants_path
from frago.recipes.exceptions import RecipeValidationError
from frago.recipes.metadata import RecipeMetadata, validate_metadata


@pytest.fixture
def machine(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    # The interpreter's scratch is writable for every run, and tmp_path lives
    # inside it; point it elsewhere so "not writable" means what it says.
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(isolation, "_interpreter_writable", lambda: [scratch])
    # Confined, whatever this test machine has installed.
    monkeypatch.setattr(command_grants, "_confined", lambda: True)
    return home


@pytest.fixture
def recipe(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "recipe.py").write_text(
        'import subprocess\n'
        'GH = "gh"\n'
        'def fetch():\n'
        '    return subprocess.run([GH, "api", "graphql"])\n'
        '# a ghost is not gh-like\n'
    )
    (code / "test_recipe.py").write_text('run(["gh", "auth", "status"])\n')
    return code


def answer(paths, verdict="allow", reason="只读，只查公开数据"):
    def fake(recipe_name, recipe_dir, command, lines):
        return {
            "fingerprint": command_grants.fingerprint(command, recipe_dir),
            "verdict": verdict,
            "executable": "/opt/homebrew/bin/gh",
            "paths": [{"path": str(p), "why": "配置"} for p in paths],
            "dropped": [],
            "reason": reason,
            "audited_at": "2026-09-18T00:00:00Z",
            "auditor": {"role": "coreagent", "profile": "x", "model": "m"},
            "machine": "Test",
        }
    return fake


def never_asked(*_args, **_kwargs):
    raise AssertionError("CoreAgent was asked when the record should have answered")


class TestWhatTheRecipeSaysAboutTheCommand:
    def test_only_lines_naming_the_command_as_a_word(self, recipe):
        lines = [line for _, _, line in command_grants.mentions(recipe, "gh")]
        assert 'GH = "gh"' in lines
        assert not any("ghost" in line for line in lines)

    def test_the_recipes_own_tests_are_not_what_runs(self, recipe):
        files = {rel for rel, _, _ in command_grants.mentions(recipe, "gh")}
        assert files == {"recipe.py"}

    def test_a_call_that_does_not_spell_the_name_is_still_covered(self, recipe):
        """``github_star_watch`` starts gh as ``[self._gh_path(), "api", …]``.
        Changing what follows must be asked about again."""
        before = command_grants.fingerprint("gh", recipe)
        script = recipe / "recipe.py"
        script.write_text(script.read_text().replace('"api", "graphql"', '"repo", "delete"'))
        assert command_grants.fingerprint("gh", recipe) != before

    def test_editing_its_own_tests_does_not_send_it_back(self, recipe):
        before = command_grants.fingerprint("gh", recipe)
        (recipe / "test_recipe.py").write_text("# rewritten\n")
        assert command_grants.fingerprint("gh", recipe) == before


class TestWhereTheRecordLives:
    def test_beside_the_recipes_machine_level_data(self, machine):
        assert grants_path("demo") == machine / ".frago" / "recipe-data" / "demo" / GRANTS_FILE

    def test_an_empty_record_is_laid_down_where_the_tree_exists(self, machine):
        tree = machine / ".frago" / "recipe-data" / "demo"
        tree.mkdir(parents=True)
        command_grants.seal("demo")
        assert json.loads(grants_path("demo").read_text())["commands"] == {}

    def test_no_tree_is_created_just_to_hold_one(self, machine):
        command_grants.seal("demo")
        assert not (machine / ".frago" / "recipe-data" / "demo").exists()

    def test_an_existing_record_is_not_touched(self, machine):
        path = grants_path("demo")
        path.parent.mkdir(parents=True)
        path.write_text('{"commands": {"gh": {}}}')
        command_grants.seal("demo")
        assert json.loads(path.read_text()) == {"commands": {"gh": {}}}


class TestWhatARunGets:
    def test_nothing_declared_nothing_asked(self, machine, recipe, monkeypatch):
        monkeypatch.setattr(command_grants, "audit", never_asked)
        assert command_grants.for_run("demo", recipe, []) == ({}, "")

    def test_nothing_confined_nothing_asked(self, machine, recipe, monkeypatch):
        """Isolation off, or Windows: a command already sees everything."""
        monkeypatch.setattr(command_grants, "_confined", lambda: False)
        monkeypatch.setattr(command_grants, "audit", never_asked)
        assert command_grants.for_run("demo", recipe, ["gh"]) == ({}, "")

    def test_the_first_run_asks_and_records(self, machine, recipe, monkeypatch):
        config = machine / ".config" / "gh"
        monkeypatch.setattr(command_grants, "audit", answer([config]))
        granted, refusal = command_grants.for_run("demo", recipe, ["gh"])
        assert refusal == ""
        assert granted == {"gh": [config]}
        record = json.loads(grants_path("demo").read_text())
        assert record["commands"]["gh"]["verdict"] == "allow"

    def test_the_next_run_reads_the_record_and_asks_nothing(self, machine, recipe, monkeypatch):
        config = machine / ".config" / "gh"
        monkeypatch.setattr(command_grants, "audit", answer([config]))
        command_grants.for_run("demo", recipe, ["gh"])
        monkeypatch.setattr(command_grants, "audit", never_asked)
        granted, refusal = command_grants.for_run("demo", recipe, ["gh"])
        assert (granted, refusal) == ({"gh": [config]}, "")

    def test_changed_code_is_asked_about_again_and_the_old_answer_kept(
        self, machine, recipe, monkeypatch
    ):
        monkeypatch.setattr(command_grants, "audit", answer([machine / "a"]))
        command_grants.for_run("demo", recipe, ["gh"])
        script = recipe / "recipe.py"
        script.write_text(script.read_text().replace('"api"', '"repo", "delete"'))
        monkeypatch.setattr(command_grants, "audit", answer([machine / "b"]))
        granted, _ = command_grants.for_run("demo", recipe, ["gh"])
        assert granted == {"gh": [machine / "b"]}
        entry = json.loads(grants_path("demo").read_text())["commands"]["gh"]
        assert entry["earlier"][0]["paths"][0]["path"] == str(machine / "a")

    def test_a_command_that_was_not_allowed_refuses_the_run(self, machine, recipe, monkeypatch):
        monkeypatch.setattr(command_grants, "audit",
                            answer([], verdict="deny", reason="它会删仓库"))
        granted, refusal = command_grants.for_run("demo", recipe, ["gh"])
        assert granted == {}
        assert "它会删仓库" in refusal
        assert str(grants_path("demo")) in refusal

    def test_a_failed_audit_refuses_and_records_nothing(self, machine, recipe, monkeypatch):
        def broken(*_args):
            raise command_grants.AuditFailed("没有绑定连接")
        monkeypatch.setattr(command_grants, "audit", broken)
        granted, refusal = command_grants.for_run("demo", recipe, ["gh"])
        assert granted == {}
        assert "没有绑定连接" in refusal
        assert not grants_path("demo").exists()

    def test_the_door_that_must_not_block_does_not_ask(self, machine, recipe, monkeypatch):
        monkeypatch.setattr(command_grants, "audit", never_asked)
        granted, refusal = command_grants.for_run("demo", recipe, ["gh"], may_audit=False)
        assert granted == {}
        assert "frago recipe run demo" in refusal

    def test_deleting_an_entry_revokes_it(self, machine, recipe, monkeypatch):
        monkeypatch.setattr(command_grants, "audit", answer([machine / "a"]))
        command_grants.for_run("demo", recipe, ["gh"])
        path = grants_path("demo")
        record = json.loads(path.read_text())
        del record["commands"]["gh"]
        path.write_text(json.dumps(record))
        asked = []
        monkeypatch.setattr(command_grants, "audit",
                            lambda *a: asked.append(1) or answer([machine / "a"])(*a))
        command_grants.for_run("demo", recipe, ["gh"])
        assert asked == [1]

    @pytest.mark.parametrize("bad", ["/usr/bin/gh", "frago", "gh api"])
    def test_a_name_that_is_not_a_command_is_refused_not_audited(
        self, machine, recipe, monkeypatch, bad
    ):
        monkeypatch.setattr(command_grants, "audit", never_asked)
        granted, refusal = command_grants.for_run("demo", recipe, [bad])
        assert granted == {} and repr(bad) in refusal
        _, notes = command_grants.recorded("demo", recipe, [bad])
        assert notes == []  # validate's own error says it; no "will be audited" beside it

    def test_validate_reads_the_record_and_never_asks(self, machine, recipe, monkeypatch):
        monkeypatch.setattr(command_grants, "audit", never_asked)
        granted, notes = command_grants.recorded("demo", recipe, ["gh"])
        assert granted == {}
        assert notes and "还没审计过" in notes[0]


class TestWhatIsNeverHandedOver:
    """The model is told these rules. This is the half that holds when it did
    not follow them."""

    def test_a_commands_own_directory_is_kept(self, machine):
        config = machine / ".config" / "gh"
        config.mkdir(parents=True)
        kept, dropped = command_grants.screen([{"path": str(config), "why": "x"}], home=machine)
        assert [one["path"] for one in kept] == [str(config)] and not dropped

    @pytest.mark.parametrize("where", ["", ".frago", ".frago/users", ".ssh", ".aws"])
    def test_home_and_the_places_that_are_never_a_commands_own(self, machine, where):
        target = machine / where if where else machine
        target.mkdir(parents=True, exist_ok=True)
        kept, dropped = command_grants.screen([{"path": str(target)}], home=machine)
        assert not kept and dropped

    def test_anything_holding_frago_inside_it(self, machine):
        (machine / ".frago").mkdir()
        kept, _ = command_grants.screen([{"path": str(machine.parent)}], home=machine)
        assert not kept

    def test_a_path_that_is_not_there(self, machine):
        kept, dropped = command_grants.screen([{"path": str(machine / "nope")}], home=machine)
        assert not kept and "不存在" in dropped[0]["why"]

    def test_a_relative_path(self, machine):
        kept, dropped = command_grants.screen([{"path": ".config/gh"}], home=machine)
        assert not kept and dropped


class TestReadingTheAnswer:
    def test_a_fenced_object(self):
        text = '看过了。\n```json\n{"verdict": "allow", "paths": []}\n```'
        assert command_grants._last_json(text)["verdict"] == "allow"

    def test_a_bare_object_after_prose(self):
        text = '结论如下 {"verdict": "deny", "paths": [], "reason": "查不清"}'
        assert command_grants._last_json(text)["reason"] == "查不清"

    def test_no_object(self):
        assert command_grants._last_json("我觉得可以") is None


class TestTheDeclaration:
    def meta(self, commands):
        return RecipeMetadata(
            name="demo", type="atomic", runtime="python", version="1.0.0",
            description="d", use_cases=["u"], output_targets=["stdout"],
            uses_commands=commands,
        )

    def test_command_names_pass(self):
        validate_metadata(self.meta(["gh", "yt-dlp", "ffmpeg"]))

    @pytest.mark.parametrize("bad", ["/opt/homebrew/bin/gh", "gh api", "~/bin/x", ""])
    def test_a_path_or_a_command_line_is_refused(self, bad):
        with pytest.raises(RecipeValidationError):
            validate_metadata(self.meta([bad]))

    def test_frago_itself_points_at_its_own_declaration(self):
        with pytest.raises(RecipeValidationError) as err:
            validate_metadata(self.meta(["frago"]))
        assert "uses_frago_cli" in str(err.value)


class TestTheViewItBecomes:
    def test_granted_directories_are_readable_and_not_writable(self, machine):
        config = machine / ".config" / "gh"
        config.mkdir(parents=True)
        view = isolation.view_for("demo", landing_spot=None, recipe_dir=None,
                                  granted={"gh": [config]})
        assert view.sees(config) and not view.may_write(config)
        assert "gh" in view.because[str(config)]

    def test_the_record_is_readable_and_never_writable_by_the_recipe(self, machine):
        view = isolation.view_for("demo", landing_spot=None, recipe_dir=None)
        record = machine / ".frago" / "recipe-data" / "demo" / GRANTS_FILE
        assert view.sees(record)
        assert not view.may_write(record)
        # The tree around it stays the recipe's own.
        assert view.may_write(record.parent / "cache.json")

    def test_a_refusal_stops_the_run_at_wrap(self):
        with pytest.raises(isolation.NotGranted):
            isolation.wrap(["true"], isolation.View(refusal="不许"))
