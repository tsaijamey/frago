"""What a recipe can and cannot reach while it runs.

Two kinds of test here, and the split is deliberate.

Most of them are about the *view*: what the platform decides one run may see,
which is a pure function of who the run is for and what the two sides declared.
Those run everywhere.

The last class actually starts a confined process and checks what it can do.
Only that one proves anything — every rule above it is a statement about a
string until a kernel refuses something — so it exists despite being slower and
platform-dependent, and it is skipped rather than weakened where no backend is
installed.
"""

import json
import platform
import subprocess
import sys
from pathlib import Path

import pytest

from frago.recipes import isolation


@pytest.fixture
def machine(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


class TestWhatARunMaySee:
    def test_its_landing_spot_is_writable(self, machine):
        view = isolation.view_for(
            "demo", landing_spot=machine / "land", recipe_dir=None)
        assert view.may_write(machine / "land")

    def test_a_landing_spot_that_does_not_exist_yet_is_still_in_the_view(self, machine):
        """A recipe's very first run is exactly the run whose directory is not
        there yet, and it must not be the one run confined out of it."""
        view = isolation.view_for(
            "demo", landing_spot=machine / "never" / "written", recipe_dir=None)
        assert view.may_write(machine / "never" / "written")

    def test_its_own_machine_level_tree_is_writable(self, machine):
        """Where a producer keeps the block it shares. Its own, so it writes it."""
        view = isolation.view_for("demo", landing_spot=None, recipe_dir=None)
        assert view.may_write(machine / ".frago" / "recipe-data" / "demo")

    def test_another_recipes_tree_is_not_in_the_view_at_all(self, machine):
        view = isolation.view_for("demo", landing_spot=None, recipe_dir=None)
        assert not view.sees(machine / ".frago" / "recipe-data" / "someone_else")

    def test_a_shared_block_is_readable_and_never_writable(self, machine):
        block = machine / ".frago" / "recipe-data" / "feed" / "share" / "common"
        block.mkdir(parents=True)
        view = isolation.view_for(
            "demo", landing_spot=None, recipe_dir=None, shared={"feed": block})
        assert view.sees(block)
        assert not view.may_write(block)
        assert block in view.shared

    def test_the_block_is_named_with_who_opened_it(self, machine):
        """A refusal is only actionable next to what the run could see and who
        asked for it."""
        block = machine / ".frago" / "recipe-data" / "feed" / "share" / "common"
        view = isolation.view_for(
            "demo", landing_spot=None, recipe_dir=None, shared={"feed": block})
        assert "feed" in view.because[str(block)]

    def test_nobodys_home_is_in_the_view(self, machine):
        (machine / ".ssh").mkdir()
        view = isolation.view_for(
            "demo", landing_spot=machine / "land", recipe_dir=None)
        assert not view.sees(machine / ".ssh")
        assert not view.sees(machine / ".frago" / "users")
        assert not view.sees(machine / ".frago" / "recipes.local.json")

    def test_the_recipes_root_is_readable_but_not_writable(self, machine):
        """Recipes import algorithm libraries out of each other's directories.
        Source is code every account on this machine already has; letting a run
        *change* it is a different thing entirely."""
        recipes = machine / ".frago" / "recipes"
        (recipes / "workflows" / "demo").mkdir(parents=True)
        view = isolation.view_for(
            "demo", landing_spot=None, recipe_dir=recipes / "workflows" / "demo")
        assert view.sees(recipes / "workflows" / "other")
        assert not view.may_write(recipes / "workflows" / "demo")

    def test_the_platform_cli_is_out_unless_the_recipe_said_it_calls_it(self, machine):
        (machine / ".frago" / "chrome").mkdir(parents=True)
        without = isolation.view_for("demo", landing_spot=None, recipe_dir=None)
        with_cli = isolation.view_for(
            "demo", landing_spot=None, recipe_dir=None, uses_frago_cli=True)
        assert not without.sees(machine / ".frago" / "chrome")
        assert with_cli.may_write(machine / ".frago" / "chrome")

    def test_even_then_nobodys_data_comes_with_it(self, machine):
        """Handing over ~/.frago to run one browser command would give away more
        than having no isolation costs, while reporting a boundary."""
        (machine / ".frago" / "users").mkdir(parents=True)
        view = isolation.view_for(
            "demo", landing_spot=None, recipe_dir=None, uses_frago_cli=True)
        assert not view.sees(machine / ".frago" / "users")
        assert not view.sees(machine / ".frago" / "identity.json")


class TestTheProfileMacOSIsHeldTo:
    def test_it_denies_everything_it_did_not_name(self):
        profile = isolation.SandboxExec().profile(isolation.View(), cwd=None)
        assert "(deny default)" in profile

    def test_the_root_directory_is_readable(self):
        """Without it a deny-default profile aborts every process, /bin/echo
        included, with no diagnostic anywhere."""
        profile = isolation.SandboxExec().profile(isolation.View(), cwd=None)
        assert '(allow file-read* (literal "/"))' in profile

    def test_a_shared_block_ends_in_a_refusal_to_write_it(self, tmp_path):
        block = tmp_path / "feed" / "share" / "common"
        view = isolation.View(writable=(tmp_path,), readable=(block,),
                              shared=(block,))
        profile = isolation.SandboxExec().profile(view, cwd=None)
        deny = profile.index("(deny file-write*")
        allow = profile.index("(allow file-read* file-write*")
        # Last matching rule wins, so the refusal has to come after every allow
        # that could cover the same path. With the order reversed this test
        # passes as a string check and the block is writable in fact.
        assert deny > allow

    def test_the_working_directory_is_writable_even_if_nobody_listed_it(self, tmp_path):
        profile = isolation.SandboxExec().profile(isolation.View(), cwd=tmp_path)
        assert str(tmp_path) in profile


class TestTheMountsLinuxIsHeldTo:
    def test_shared_blocks_are_bound_read_only_last(self, tmp_path):
        block = tmp_path / "feed"
        view = isolation.View(writable=(tmp_path,), readable=(block,),
                              shared=(block,))
        argv = isolation.Bubblewrap().wrap(["echo"], view, cwd=None)
        assert argv[-2:] == ["--", "echo"]
        assert argv.index("--ro-bind-try") > argv.index("--bind-try")

    def test_it_does_not_bind_the_hosts_proc_and_dev_back_over_its_own(self, tmp_path):
        """bwrap furnishes /proc and /dev itself; binding the host's copies on
        top is what broke every recipe on the demo server on 2026-08-31 — the
        tool that starts the interpreter could no longer tell which C library
        the machine has, and gave up before running a line. Measured: the host's
        /proc alone is harmless, the host's /dev alone breaks it. Both are kept
        out — /dev because of this, /proc because a run in its own pid namespace
        has no business reading the host's process table."""
        view = isolation.View(
            writable=(Path("/dev"), tmp_path),
            readable=(Path("/usr"), Path("/proc")),
        )
        argv = isolation.Bubblewrap().wrap(["echo"], view, cwd=None)
        assert "--proc" in argv and "--dev" in argv          # bwrap 自己铺
        pairs = list(zip(argv, argv[1:]))
        assert ("--ro-bind-try", "/proc") not in pairs
        assert ("--bind-try", "/dev") not in pairs
        assert ("--ro-bind-try", "/usr") in pairs            # 别的照常

    def test_the_command_survives_intact(self, tmp_path):
        argv = isolation.Bubblewrap().wrap(
            ["uv", "run", "x.py", "{}"], isolation.View(), cwd=tmp_path)
        assert argv[argv.index("--") + 1:] == ["uv", "run", "x.py", "{}"]


class TestAMachineThatCannotConfineARecipe:
    def test_it_refuses_rather_than_running_one_unconfined(self, monkeypatch):
        # Pinned, because the answer is per platform and the suite has to give
        # the same one wherever it runs.
        monkeypatch.setattr(isolation.platform, "system", lambda: "Linux")
        monkeypatch.setattr(isolation, "backend", lambda: None)
        monkeypatch.setenv("FRAGO_RECIPE_ISOLATION", "enforce")
        with pytest.raises(isolation.NoBackend):
            isolation.wrap(["echo"], isolation.View())

    def test_the_refusal_says_what_to_install(self, monkeypatch):
        monkeypatch.setattr(isolation.platform, "system", lambda: "Linux")
        monkeypatch.setattr(isolation, "backend", lambda: None)
        monkeypatch.setenv("FRAGO_RECIPE_ISOLATION", "enforce")
        with pytest.raises(isolation.NoBackend) as err:
            isolation.wrap(["echo"], isolation.View())
        assert str(err.value).strip()

    def test_windows_warns_and_runs(self, monkeypatch):
        """Not a softer standard — a different situation. A Windows install is
        one person on their own laptop, where the data a recipe could reach is
        already theirs; refusing there costs a working frago and protects
        nobody. The warning still goes out on every run."""
        monkeypatch.setattr(isolation, "backend", lambda: None)
        monkeypatch.setattr(isolation.platform, "system", lambda: "Windows")
        monkeypatch.setenv("FRAGO_RECIPE_ISOLATION", "enforce")
        cmd, name = isolation.wrap(["echo", "hi"], isolation.View())
        assert cmd == ["echo", "hi"]
        assert name == ""

    def test_linux_without_the_tool_still_refuses(self, monkeypatch):
        """The refusal is worth its cost where several people's data and the
        machine's own credentials sit under one unix account."""
        monkeypatch.setattr(isolation, "backend", lambda: None)
        monkeypatch.setattr(isolation.platform, "system", lambda: "Linux")
        monkeypatch.setenv("FRAGO_RECIPE_ISOLATION", "enforce")
        with pytest.raises(isolation.NoBackend):
            isolation.wrap(["echo"], isolation.View())

    def test_turning_it_off_takes_saying_so(self, monkeypatch):
        """The one path where an unconfined recipe starts. It has a name and a
        place, unlike a silent fallback."""
        monkeypatch.setattr(isolation, "backend", lambda: None)
        monkeypatch.setenv("FRAGO_RECIPE_ISOLATION", "off")
        cmd, name = isolation.wrap(["echo", "hi"], isolation.View())
        assert cmd == ["echo", "hi"]
        assert name == ""

    def test_an_unreadable_config_reads_as_enforce(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FRAGO_RECIPE_ISOLATION", raising=False)
        broken = tmp_path / "config.json"
        broken.write_text("{ not json")
        monkeypatch.setattr(isolation, "CONFIG_PATH", broken)
        assert isolation.configured() == isolation.ENFORCE

    def test_a_machine_with_no_config_at_all_reads_as_enforce(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FRAGO_RECIPE_ISOLATION", raising=False)
        monkeypatch.setattr(isolation, "CONFIG_PATH", tmp_path / "nothing.json")
        assert isolation.configured() == isolation.ENFORCE

    def test_the_owner_can_say_off_in_the_config(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FRAGO_RECIPE_ISOLATION", raising=False)
        written = tmp_path / "config.json"
        written.write_text('{"recipe": {"isolation": "off"}}')
        monkeypatch.setattr(isolation, "CONFIG_PATH", written)
        assert isolation.configured() == isolation.OFF


class TestSayingSoBeforeItHappens:
    """The gate `frago recipe validate` closes, and it has to close on exactly
    what the kernel would refuse. A check that permits what the boundary kills
    produces the failure this work exists to end: installed, scheduled, dying
    every five minutes, behind a page still showing three-day-old numbers.
    """

    @pytest.fixture
    def recipe(self, machine):
        d = machine / ".frago" / "recipes" / "workflows" / "demo"
        d.mkdir(parents=True)
        return d

    def _wrote(self, recipe, body):
        (recipe / "recipe.py").write_text(body)
        return recipe

    def test_reaching_into_someone_elses_tree_is_seen(self, machine, recipe):
        self._wrote(recipe, 'from pathlib import Path\n'
                            'p = Path.home() / ".frago" / "recipe-data" / "other" / "x"\n')
        found = isolation.foresee(recipe, "demo")
        assert len(found) == 1
        assert "recipe-data/other" in found[0].why

    def test_its_own_tree_is_not_a_finding(self, machine, recipe):
        self._wrote(recipe, 'from pathlib import Path\n'
                            'p = Path.home() / ".frago" / "recipe-data" / "demo" / "x"\n')
        assert isolation.foresee(recipe, "demo") == []

    def test_a_block_that_was_shared_is_not_a_finding(self, machine, recipe):
        block = machine / ".frago" / "recipe-data" / "feed" / "share" / "common"
        block.mkdir(parents=True)
        self._wrote(recipe, 'from pathlib import Path\n'
                            'p = Path.home() / ".frago" / "recipe-data" / "feed" '
                            '/ "share" / "common" / "x"\n')
        assert isolation.foresee(recipe, "demo", shared={"feed": block}) == []

    def test_prose_about_a_path_is_not_a_finding(self, machine, recipe):
        """These files explain themselves at length. A check that reports the
        explanation is a check people learn to skim past."""
        self._wrote(recipe, '"""读 ~/.ssh 是不允许的，别写 /Users/someone/secret。"""\n')
        assert isolation.foresee(recipe, "demo") == []

    def test_a_url_path_is_not_a_finding(self, machine, recipe):
        """`/CN_MarketData.getKLineData?symbol={x}` is a URL tail, and reporting
        it names something nobody can fix."""
        self._wrote(recipe, 'u = "/CN_MarketData.getKLineData?symbol=x"\n'
                            'sep = "/".join(["a", "b"])\n')
        assert isolation.foresee(recipe, "demo") == []

    def test_starting_frago_without_declaring_it_is_seen(self, machine, recipe):
        self._wrote(recipe, 'import subprocess\n'
                            'subprocess.run(["frago", "browser", "navigate", "x"])\n')
        found = isolation.foresee(recipe, "demo")
        assert len(found) == 1
        assert "uses_frago_cli" in found[0].why

    def test_writing_about_frago_is_not_starting_it(self, machine, recipe):
        self._wrote(recipe, '"""跑法：frago recipe run demo --params \'{}\'"""\n'
                            'HELP = "见 frago book must-recipe-data"\n')
        assert isolation.foresee(recipe, "demo") == []

    def test_declaring_it_settles_both_the_command_and_its_directories(
            self, machine, recipe):
        (machine / ".frago" / "chrome").mkdir(parents=True)
        self._wrote(recipe, 'import subprocess\n'
                            'from pathlib import Path\n'
                            'p = Path.home() / ".frago" / "chrome"\n'
                            'subprocess.run(["frago", "browser", "status"])\n')
        assert isolation.foresee(recipe, "demo") != []
        assert isolation.foresee(recipe, "demo", uses_frago_cli=True) == []

    def test_a_path_one_declaration_would_fix_says_which_declaration(
            self, machine, recipe):
        """Telling the author to "use self.store" about ~/.frago/config.json
        sends them looking for an answer that does not exist."""
        (machine / ".frago" / "config.json").parent.mkdir(parents=True, exist_ok=True)
        (machine / ".frago" / "config.json").write_text("{}")
        self._wrote(recipe, 'from pathlib import Path\n'
                            'p = Path.home() / ".frago" / "config.json"\n')
        found = isolation.foresee(recipe, "demo")
        assert len(found) == 1
        assert "uses_frago_cli" in found[0].fix


_PROBE = """
import json, sys
from pathlib import Path
secret, block, land = (Path(p) for p in sys.argv[1:4])
out = {}
try:
    out["read_secret"] = (secret / "key").read_text()
except Exception as err:
    out["read_secret"] = f"denied:{type(err).__name__}"
try:
    out["read_block"] = (block / "data.json").read_text()
except Exception as err:
    out["read_block"] = f"denied:{type(err).__name__}"
try:
    (block / "evil").write_text("x")
    out["write_block"] = "allowed"
except Exception as err:
    out["write_block"] = f"denied:{type(err).__name__}"
try:
    (land / "mine").write_text("x")
    out["write_land"] = "allowed"
except Exception as err:
    out["write_land"] = f"denied:{type(err).__name__}"
print(json.dumps(out))
"""


@pytest.mark.skipif(
    isolation.backend() is None,
    reason="this machine has no isolation backend; nothing here can be proved",
)
class TestWhatTheKernelActuallyRefuses:
    """The only tests in this file that prove anything.

    Everything above describes a policy. A policy is a string until something
    enforces it, and "read-only by contract" was a true sentence in a docstring
    for as long as this package has existed.
    """

    @pytest.fixture
    def run(self, tmp_path):
        # Everything sits in its own directory, none of them inside another. A
        # first draft of this fixture put the secret inside the recipe's own
        # directory and the test passed by reading it.
        secret = tmp_path / "secret"
        secret.mkdir()
        (secret / "key").write_text("private")
        block = tmp_path / "block"
        block.mkdir()
        (block / "data.json").write_text('{"n": 1}')
        land = tmp_path / "land"
        land.mkdir()
        code = tmp_path / "code"
        code.mkdir()
        probe = code / "probe.py"
        probe.write_text(_PROBE)

        def go():
            view = isolation.view_for(
                "demo", landing_spot=land, recipe_dir=code,
                shared={"feed": block},
            )
            cmd, _ = isolation.wrap(
                [sys.executable, str(probe), str(secret), str(block), str(land)],
                view, cwd=land,
            )
            done = subprocess.run(cmd, cwd=land, capture_output=True, text=True)
            assert done.returncode == 0, done.stderr
            return json.loads(done.stdout)

        return go

    def test_it_cannot_read_what_nobody_shared_with_it(self, run):
        assert run()["read_secret"].startswith("denied:")

    def test_it_can_read_the_block_that_was_shared(self, run):
        assert json.loads(run()["read_block"]) == {"n": 1}

    def test_it_cannot_write_the_block_that_was_shared(self, run):
        """The whole point. One recipe corrupting shared data corrupts it for
        every page that reads it, and there is exactly one copy to compare
        against."""
        assert run()["write_block"].startswith("denied:")

    def test_it_can_write_its_own_landing_spot(self, run):
        assert run()["write_land"] == "allowed"

    @pytest.mark.skipif(platform.system() == "Windows", reason="no ~/.ssh here")
    def test_it_cannot_read_the_owners_keys(self, tmp_path):
        from pathlib import Path

        ssh = Path.home() / ".ssh"
        if not ssh.is_dir():
            pytest.skip("no ~/.ssh on this machine to be refused")
        land = tmp_path / "land"
        land.mkdir()
        probe = tmp_path / "peek.py"
        probe.write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "try:\n"
            "    list(Path(sys.argv[1]).iterdir())\n"
            "    print('READABLE')\n"
            "except Exception as err:\n"
            "    print('denied', type(err).__name__)\n"
        )
        view = isolation.view_for(
            "demo", landing_spot=land, recipe_dir=tmp_path)
        cmd, _ = isolation.wrap(
            [sys.executable, str(probe), str(ssh)], view, cwd=land)
        done = subprocess.run(cmd, cwd=land, capture_output=True, text=True)
        assert "READABLE" not in done.stdout


class TestTheRecipesOwnTestsAreNotTheRecipe:
    """A recipe's tests run from a developer's shell, unconfined, and are
    entitled to reach a fixture directory or the author's own checkout. The
    platform never starts them. Reporting them is a false alarm about a run
    that will not happen — and on the first pass over a real machine, the only
    two complaints against one recipe were both in its test file."""

    @pytest.fixture
    def recipe(self, machine):
        d = machine / ".frago" / "recipes" / "workflows" / "demo"
        d.mkdir(parents=True)
        return d

    @pytest.mark.parametrize("named", [
        "test_demo.py", "demo_test.py", "conftest.py", "tests/helper.py",
    ])
    def test_a_test_file_is_not_scanned(self, machine, recipe, named):
        target = recipe / named
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('from pathlib import Path\n'
                          'p = Path.home() / "Repos" / "frago" / "src"\n')
        assert isolation.foresee(recipe, "demo") == []

    def test_the_recipe_itself_still_is(self, machine, recipe):
        (recipe / "recipe.py").write_text('from pathlib import Path\n'
                                          'p = Path.home() / "Repos" / "frago" / "src"\n')
        assert len(isolation.foresee(recipe, "demo")) == 1


class TestPathsBuiltOffAName:
    """Nobody writes a whole path in one expression.

    They bind the frago home once and divide off it everywhere after. A check
    that does not follow the name can only report the binding — which is never
    opened — while the paths actually opened go unexamined. Found on a real
    machine: one file drew a single complaint about `~/.frago`, and both places
    it actually reached were inside the view.
    """

    @pytest.fixture
    def recipe(self, machine):
        d = machine / ".frago" / "recipes" / "workflows" / "demo"
        d.mkdir(parents=True)
        return d

    def test_the_binding_alone_is_not_reported(self, machine, recipe):
        (recipe / "recipe.py").write_text(
            'from pathlib import Path\n'
            'HOME = Path.home() / ".frago"\n'
            'src = HOME / "recipes" / "workflows" / "other"\n'      # 视野内
            'out = HOME / "recipe-data" / "demo" / "x.json"\n'      # 视野内
        )
        assert isolation.foresee(recipe, "demo") == []

    def test_what_is_built_off_it_still_is(self, machine, recipe):
        (recipe / "recipe.py").write_text(
            'from pathlib import Path\n'
            'HOME = Path.home() / ".frago"\n'
            'other = HOME / "recipe-data" / "someone_else" / "x.json"\n'
        )
        found = isolation.foresee(recipe, "demo")
        assert len(found) == 1
        assert "someone_else" in found[0].why

    def test_a_name_bound_off_another_name_is_followed_too(self, machine, recipe):
        (recipe / "recipe.py").write_text(
            'from pathlib import Path\n'
            'HOME = Path.home() / ".frago"\n'
            'RESULTS = HOME / "viewer" / "content"\n'
            'out = RESULTS / "x.json"\n'
        )
        found = isolation.foresee(recipe, "demo")
        assert found and "viewer" in found[0].why


class TestTheCommandNameCanBeAName:
    """A check that only recognises the most artless spelling rewards artlessness.

    Nine real recipes had hoisted the word `frago` into a constant — a
    deliberate tidy-up with the reason written in their source — and every one
    of them called the platform's CLI without declaring it while this check
    reported nothing. Nine passed the gate; three were broken at run time.
    """

    @pytest.fixture
    def recipe(self, machine):
        d = machine / ".frago" / "recipes" / "workflows" / "demo"
        d.mkdir(parents=True)
        return d

    def test_a_module_level_constant_is_followed(self, machine, recipe):
        (recipe / "recipe.py").write_text(
            'import subprocess\n'
            'FRAGO = "frago"\n'
            'subprocess.run([FRAGO, "recipe", "run", "other"])\n'
        )
        found = isolation.foresee(recipe, "demo")
        assert len(found) == 1
        assert "uses_frago_cli" in found[0].why

    def test_a_class_attribute_is_followed_too(self, machine, recipe):
        (recipe / "recipe.py").write_text(
            'import subprocess\n'
            'class R:\n'
            '    FRAGO = "frago"\n'
            '    def go(self):\n'
            '        subprocess.run([self.FRAGO, "browser", "status"])\n'
        )
        assert len(isolation.foresee(recipe, "demo")) == 1

    def test_a_name_bound_to_something_else_is_not_frago(self, machine, recipe):
        """Following names must not turn into reporting every subprocess."""
        (recipe / "recipe.py").write_text(
            'import subprocess\n'
            'TOOL = "git"\n'
            'subprocess.run([TOOL, "status"])\n'
        )
        assert isolation.foresee(recipe, "demo") == []

    def test_the_shell_string_form_through_a_name(self, machine, recipe):
        (recipe / "recipe.py").write_text(
            'import subprocess\n'
            'FRAGO = "frago"\n'
            'subprocess.run(f"{FRAGO} browser status", shell=True)\n'
        )
        assert len(isolation.foresee(recipe, "demo")) == 1

    def test_declaring_it_still_settles_the_matter(self, machine, recipe):
        (recipe / "recipe.py").write_text(
            'import subprocess\n'
            'FRAGO = "frago"\n'
            'subprocess.run([FRAGO, "recipe", "run", "other"])\n'
        )
        assert isolation.foresee(recipe, "demo", uses_frago_cli=True) == []

    def test_the_command_assembled_on_an_earlier_line(self, machine, recipe):
        """The second spelling, and the one that survived the first fix: build
        the whole command into a variable, hand the variable over next line.
        Following the name but not the list it sits in leaves exactly the
        recipes that write their calls most carefully still invisible."""
        (recipe / "recipe.py").write_text(
            'import subprocess\n'
            'FRAGO = "frago"\n'
            'def go(name):\n'
            '    argv = [FRAGO, "recipe", "run", name]\n'
            '    subprocess.run(argv, capture_output=True)\n'
        )
        found = isolation.foresee(recipe, "demo")
        assert len(found) == 1
        assert "uses_frago_cli" in found[0].why

    def test_a_variable_holding_someone_elses_command_is_not_frago(self, machine, recipe):
        (recipe / "recipe.py").write_text(
            'import subprocess\n'
            'def go():\n'
            '    argv = ["git", "status"]\n'
            '    subprocess.run(argv)\n'
        )
        assert isolation.foresee(recipe, "demo") == []
