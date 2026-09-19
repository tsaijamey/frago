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
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

from frago.recipes import isolation


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A machine whose home is not inside the scratch space runs are granted.

    A run gets the interpreter's scratch — `$TMPDIR`, `/tmp`, `/var/tmp` —
    because uv writes the environment it builds and python writes its bytecode,
    and that grant is right. It is also where pytest puts `tmp_path`: on macOS
    under `$TMPDIR`, on Linux under `/tmp`. So a fixture that made the whole
    fake home a subdirectory of it described a machine where everything is
    scratch, and every assertion here about what a run must *not* see was
    answered by that one unrelated grant rather than by the rule under test.

    Two directories instead of one, side by side and neither inside the other:
    the machine, and the scratch it hands out.
    """
    home = tmp_path / "home"
    home.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.setattr(isolation, "_interpreter_writable", lambda: [scratch])
    return home


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
    def test_only_files_are_refused(self):
        """A deny-default profile recorded silence from the microphone. Nothing
        but files is refused."""
        profile = isolation.SandboxExec().profile(isolation.View(), cwd=None)
        assert "(allow default)" in profile
        assert "(deny default)" not in profile
        refusals = [line for line in profile.splitlines() if line.startswith("(deny")]
        assert refusals and all(line.startswith("(deny file-") for line in refusals)

    def test_the_root_directory_is_readable(self):
        """Without it every process aborts, /bin/echo included, with no
        diagnostic anywhere."""
        profile = isolation.SandboxExec().profile(isolation.View(), cwd=None)
        assert '(require-not (literal "/"))' in profile

    def test_a_shared_block_ends_in_a_refusal_to_write_it(self, tmp_path):
        block = tmp_path / "feed" / "share" / "common"
        view = isolation.View(writable=(tmp_path,), readable=(block,),
                              shared=(block,))
        profile = isolation.SandboxExec().profile(view, cwd=None)
        outside = profile.index("(deny file-write* (require-all")
        shared = profile.index(f'(deny file-write* (subpath "{block}")')
        # Last matching rule wins, and the writable root covers the block. With
        # the order reversed this test passes as a string check and the block is
        # writable in fact.
        assert shared > outside

    def test_the_platforms_record_ends_in_a_refusal_to_write_it(self, tmp_path):
        """Same shape as a shared block: the recipe's writable tree covers it,
        so the refusal has to come after."""
        record = tmp_path / "grants.json"
        view = isolation.View(writable=(tmp_path,), platform_owned=(record,))
        profile = isolation.SandboxExec().profile(view, cwd=None)
        outside = profile.index("(deny file-write* (require-all")
        held = profile.index(f'(subpath "{record}")')
        assert held > outside

    def test_the_working_directory_is_writable_even_if_nobody_listed_it(self, tmp_path):
        profile = isolation.SandboxExec().profile(isolation.View(), cwd=tmp_path)
        assert str(tmp_path) in profile

    def test_every_refusal_carries_the_runs_marker(self, tmp_path):
        """The system log names processes by pid, and nobody knows the pids a
        recipe's children had. The marker is how a run finds its own refusals."""
        block = tmp_path / "block"
        view = isolation.View(writable=(tmp_path,), readable=(block,), shared=(block,))
        profile = isolation.SandboxExec().profile(view, cwd=None, marker="frago-run-abc")
        refusals = [line for line in profile.splitlines() if line.startswith("(deny")]
        assert len(refusals) == 3
        assert all('(with message "frago-run-abc")' in line for line in refusals)

    def test_no_marker_no_message(self):
        profile = isolation.SandboxExec().profile(isolation.View(), cwd=None)
        assert "with message" not in profile


_LOG_LINES = "\n".join(json.dumps(one) for one in [
    {"eventMessage": "Sandbox: python3.13(81657) deny(1) file-write-create "
                     "/Users/x/Library/Caches/whisper/model.pt\nfrago-run-abc"},
    {"eventMessage": "3 duplicate reports for Sandbox: python3.13(81657) deny(1) "
                     "file-write-create /Users/x/Library/Caches/whisper/model.pt\nfrago-run-abc"},
    {"eventMessage": "Sandbox: uv(81600) deny(1) file-read-data /Users/x/.netrc\nfrago-run-abc"},
    {"finished": 1},
])


class TestSayingSoAfterItHappened:
    """A failed run is told what the kernel refused while it ran."""

    def test_the_marker_is_safe_to_quote_and_search(self):
        assert isolation.marker_for("exec 1/a\"b") == "frago-run-exec-1-a-b"

    @pytest.mark.skipif(platform.system() != "Darwin", reason="reads the macOS log")
    def test_the_log_is_read_into_one_line_per_refusal(self, monkeypatch):
        def fake_run(argv, **_):
            assert 'eventMessage CONTAINS "frago-run-abc"' in argv[-1]
            return subprocess.CompletedProcess(argv, 0, stdout=_LOG_LINES, stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert isolation.refusals("frago-run-abc", since=0) == [
            "python3.13 新建 /Users/x/Library/Caches/whisper/model.pt",
            "uv 读 /Users/x/.netrc",
        ]

    def test_turned_off_says_nothing(self, monkeypatch):
        monkeypatch.setenv("FRAGO_RECIPE_ISOLATION", "off")
        assert isolation.explain_refusals("frago-run-abc", 0) == ""

    def test_linux_says_there_is_nothing_to_read(self, monkeypatch):
        """Not silence: a person on Linux would otherwise conclude nothing was
        refused."""
        monkeypatch.setenv("FRAGO_RECIPE_ISOLATION", "enforce")
        monkeypatch.setattr(isolation, "backend", lambda: isolation.Bubblewrap())
        assert "Linux" in isolation.explain_refusals("frago-run-abc", 0)

    def test_both_notes_point_at_the_command_declaration(self, monkeypatch):
        """The third kind of refusal — a command reading its own config — is
        the one nobody guesses, and neither the landing spot nor an environment
        variable fixes it. Both platforms' notes have to name the declaration."""
        monkeypatch.setenv("FRAGO_RECIPE_ISOLATION", "enforce")
        monkeypatch.setattr(isolation, "backend", lambda: isolation.Bubblewrap())
        assert "uses_commands" in isolation.explain_refusals("frago-run-abc", 0)
        monkeypatch.setattr(isolation, "backend", lambda: isolation.SandboxExec())
        monkeypatch.setattr(isolation, "refusals",
                            lambda marker, since: ["gh 读 /Users/x/.config/gh/config.yml"])
        assert "uses_commands" in isolation.explain_refusals("frago-run-abc", 0)

    def test_macos_lists_them_and_says_what_to_do(self, monkeypatch):
        monkeypatch.setenv("FRAGO_RECIPE_ISOLATION", "enforce")
        monkeypatch.setattr(isolation, "backend", lambda: isolation.SandboxExec())
        monkeypatch.setattr(isolation, "refusals",
                            lambda marker, since: ["python 新建 /Users/x/Library/Caches/y"])
        note = isolation.explain_refusals("frago-run-abc", 0)
        assert "1 处" in note and "Library/Caches/y" in note and "落点" in note

    def test_macos_with_an_unreadable_log_says_so(self, monkeypatch):
        monkeypatch.setenv("FRAGO_RECIPE_ISOLATION", "enforce")
        monkeypatch.setattr(isolation, "backend", lambda: isolation.SandboxExec())
        monkeypatch.setattr(isolation, "refusals", lambda marker, since: None)
        note = isolation.explain_refusals("frago-run-abc", 0)
        assert "读不到系统日志" in note
        # Nothing listed is when a direction matters most.
        assert "uses_commands" in note


class TestTheMountsLinuxIsHeldTo:
    def test_shared_blocks_are_bound_read_only_last(self, tmp_path):
        block = tmp_path / "feed"
        view = isolation.View(writable=(tmp_path,), readable=(block,),
                              shared=(block,))
        argv = isolation.Bubblewrap().wrap(["echo"], view, cwd=None)
        assert argv[-2:] == ["--", "echo"]
        assert argv.index("--ro-bind-try") > argv.index("--bind-try")

    def test_the_platforms_record_is_bound_read_only_after_the_tree_around_it(self, tmp_path):
        record = tmp_path / "grants.json"
        view = isolation.View(writable=(tmp_path,), platform_owned=(record,))
        argv = isolation.Bubblewrap().wrap(["true"], view, cwd=None)
        tree = argv.index(str(tmp_path))
        held = max(i for i, one in enumerate(argv) if one == str(record))
        assert argv[held - 2] == "--ro-bind-try"
        assert held > tree

    def test_the_hosts_dev_keeps_its_devices_and_is_not_bound_over(self, tmp_path):
        """The host's /dev bound the ordinary way is what broke every recipe on
        the demo server on 2026-08-31 — device nodes stop being devices and the
        tool that starts the interpreter gives up before running a line. Bound
        with device access kept it works and hands over the sound card and GPU.
        The view's own /dev and /proc entries must never replace those mounts."""
        view = isolation.View(
            writable=(Path("/dev"), tmp_path),
            readable=(Path("/usr"), Path("/proc")),
        )
        argv = isolation.Bubblewrap().wrap(["echo"], view, cwd=None)
        triples = list(zip(argv, argv[1:], argv[2:], strict=False))
        assert ("--dev-bind", "/dev", "/dev") in triples
        assert "--proc" in argv                               # bwrap 自己铺
        pairs = list(zip(argv, argv[1:], strict=False))
        assert ("--ro-bind-try", "/proc") not in pairs
        assert ("--bind-try", "/dev") not in pairs
        assert ("--ro-bind-try", "/usr") in pairs            # 别的照常

    def test_system_service_sockets_are_bound_through(self, tmp_path):
        """Session bus, PulseAudio, PipeWire and Wayland live under
        /run/user/<uid>; the system bus under /run/dbus. Hiding them refuses
        more than files."""
        argv = isolation.Bubblewrap().wrap(["echo"], isolation.View(), cwd=None)
        pairs = list(zip(argv, argv[1:], strict=False))
        assert ("--bind-try", "/run/dbus") in pairs
        assert ("--bind-try", f"/run/user/{os.getuid()}") in pairs

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
    def run(self, tmp_path, monkeypatch):
        # Everything sits in its own directory, none of them inside another. A
        # first draft of this fixture put the secret inside the recipe's own
        # directory and the test passed by reading it.
        #
        # And none of them inside the interpreter's scratch, which is the same
        # mistake one level up: a run is granted `$TMPDIR`, `/tmp` and
        # `/var/tmp` because uv builds environments there and python writes
        # bytecode there, and `tmp_path` is inside that grant on both platforms.
        # So "nobody shared this with me" was being answered by a grant that has
        # nothing to do with sharing, and the kernel was right to allow it.
        # Pointed at a directory of this test's own instead, so what the kernel
        # refuses here is refused for the reason this class is about.
        monkeypatch.setattr(
            isolation, "_interpreter_writable", lambda: [tmp_path / "scratch"]
        )
        (tmp_path / "scratch").mkdir()
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

    @pytest.mark.parametrize("exists", [True, False])
    def test_it_cannot_write_the_record_of_what_it_was_allowed(
        self, tmp_path, monkeypatch, exists
    ):
        """The record sits in the recipe's own writable tree. A recipe able to
        write it — or to create it before the platform does — could grant
        itself any directory it liked. On Linux the platform lays the file down
        first (``command_grants.seal``); that step is part of what is tested."""
        from frago.recipes import command_grants

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr("pathlib.Path.home", lambda: home)
        monkeypatch.setattr(isolation, "_interpreter_writable",
                            lambda: [tmp_path / "scratch"])
        (tmp_path / "scratch").mkdir()
        tree = home / ".frago" / "recipe-data" / "demo"
        tree.mkdir(parents=True)
        record = tree / "grants.json"
        if exists:
            record.write_text('{"commands": {}}')
        command_grants.seal("demo")
        if platform.system() == "Darwin" and not exists:
            record.unlink()  # macOS holds an absent path too; prove it without the file

        view = isolation.view_for("demo", landing_spot=None, recipe_dir=None)
        script = (
            "import sys, pathlib\n"
            "tree = pathlib.Path(sys.argv[1])\n"
            "out = []\n"
            "for target in (tree / 'grants.json', tree / 'cache.json'):\n"
            "    try:\n"
            "        target.write_text('{\"commands\": {\"gh\": {}}}')\n"
            "        out.append('allowed')\n"
            "    except OSError as e:\n"
            "        out.append('denied')\n"
            "print(' '.join(out))\n"
        )
        cmd, _ = isolation.wrap([sys.executable, "-c", script, str(tree)], view, cwd=None)
        done = subprocess.run(cmd, capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        record_write, own_write = done.stdout.split()
        assert record_write == "denied"
        assert own_write == "allowed"

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

    @pytest.mark.skipif(platform.system() != "Darwin", reason="macOS preferences")
    def test_system_resources_are_not_refused(self, tmp_path):
        """Reading system preferences goes through a system service, not a file
        in the view. The deny-default profile refused it; this one must not —
        the same refusal is what recorded silence from the microphone."""
        land = tmp_path / "land"
        land.mkdir()
        view = isolation.view_for("demo", landing_spot=land, recipe_dir=None)
        cmd, _ = isolation.wrap(
            ["/usr/bin/defaults", "read", "-g", "AppleLocale"], view, cwd=land)
        done = subprocess.run(cmd, cwd=land, capture_output=True, text=True)
        assert done.returncode == 0, done.stderr

    @pytest.mark.skipif(platform.system() != "Darwin", reason="macOS link semantics")
    def test_a_file_outside_the_view_cannot_be_given_a_name_inside_it(
            self, tmp_path, monkeypatch):
        """Allow-by-default leaves every file operation not named open. The ways
        to launder a file into the view — hard link, clone, symlink — must all
        still end in a refusal to read it."""
        # Outside the interpreter's scratch, for the reason the `run` fixture
        # above gives: tmp_path is inside that grant.
        monkeypatch.setattr(
            isolation, "_interpreter_writable", lambda: [tmp_path / "scratch"])
        (tmp_path / "scratch").mkdir()
        secret = tmp_path / "secret"
        secret.mkdir()
        (secret / "key").write_text("private")
        land = tmp_path / "land"
        land.mkdir()
        view = isolation.view_for("demo", landing_spot=land, recipe_dir=None)
        script = (
            f'ln "{secret}/key" hard; cp -c "{secret}/key" clone; '
            f'ln -s "{secret}/key" soft; cat hard clone soft 2>/dev/null; true'
        )
        cmd, _ = isolation.wrap(["/bin/sh", "-c", script], view, cwd=land)
        done = subprocess.run(cmd, cwd=land, capture_output=True, text=True)
        assert "private" not in done.stdout

    @pytest.mark.skipif(platform.system() != "Darwin", reason="reads the macOS log")
    def test_a_refusal_can_be_found_again_by_its_marker(self, tmp_path, monkeypatch):
        """The chain end to end: the kernel refuses, writes the marker into the
        system log, and the run reads its own refusal back. Slow — reading the
        log takes seconds — and the only proof the marker survives the kernel."""
        import time

        monkeypatch.setattr(
            isolation, "_interpreter_writable", lambda: [tmp_path / "scratch"])
        (tmp_path / "scratch").mkdir()
        secret = tmp_path / "secret"
        secret.mkdir()
        (secret / "key").write_text("private")
        land = tmp_path / "land"
        land.mkdir()
        marker = isolation.marker_for(f"test-{time.time_ns()}")
        since = time.time()
        view = isolation.view_for("demo", landing_spot=land, recipe_dir=None)
        cmd, _ = isolation.wrap(["/bin/cat", str(secret / "key")], view,
                                cwd=land, marker=marker)
        subprocess.run(cmd, cwd=land, capture_output=True)
        found: list[str] = []
        for _ in range(3):                                  # 日志落盘有延迟
            found = isolation.refusals(marker, since) or []
            if found:
                break
            time.sleep(1)
        assert any(str(secret.resolve() / "key") in line or "secret/key" in line
                   for line in found), found


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
