"""What the platform tells a recipe about the run it is starting.

The context is three environment variables, and almost every test here is about
a way of getting them wrong. That emphasis is deliberate: a context that is
merely absent is the ordinary case and behaves like frago always has, while a
context that is *half* present is a visitor's slot paired with an owner's
directory — which fails by writing the wrong person's data rather than by
raising, and so has to be turned into a raise on purpose.
"""

import pytest

from frago.recipes import context


class TestOwnerIsTheAbsenceOfAnything:
    def test_nothing_set_is_the_owner(self):
        ctx = context.current({})
        assert ctx.caller == context.OWNER
        assert ctx.is_visitor is False

    def test_owner_carries_no_slot_and_no_directory(self):
        """The owner's slot is whatever the recipe names and the owner's
        directory is whatever the recipe has always used. Handing the owner
        path a directory would be the platform overruling `must-data-dir`."""
        ctx = context.current({})
        assert ctx.slot is None
        assert ctx.data_dir is None

    def test_saying_owner_out_loud_is_the_same_as_saying_nothing(self):
        assert context.current({context.CALLER_ENV: "owner"}).caller == context.OWNER

    def test_empty_string_is_not_set(self):
        assert context.current({context.CALLER_ENV: "   "}).caller == context.OWNER


class TestVisitor:
    def test_all_three_present_reads_back(self, tmp_path):
        ctx = context.current({
            context.CALLER_ENV: "visitor",
            context.SLOT_ENV: "abc123",
            context.DATA_DIR_ENV: str(tmp_path / "d"),
        })
        assert ctx.is_visitor
        assert ctx.slot == "abc123"
        assert ctx.data_dir == tmp_path / "d"

    def test_caller_is_case_insensitive(self, tmp_path):
        ctx = context.current({
            context.CALLER_ENV: "VISITOR",
            context.SLOT_ENV: "abc123",
            context.DATA_DIR_ENV: str(tmp_path),
        })
        assert ctx.is_visitor


class TestEveryWayOfBeingWrongRaises:
    """None of these may resolve to the owner.

    "Treat what I could not read as the owner" is the one default that looks
    harmless and is not: it turns a misspelled variable into a visitor's run
    writing the owner's data, and the wrong data looks exactly like the right
    data.
    """

    def test_unknown_caller_raises_rather_than_falling_back(self):
        with pytest.raises(context.InvalidInvocationContext):
            context.current({context.CALLER_ENV: "guest"})

    def test_visitor_without_a_slot_raises(self, tmp_path):
        with pytest.raises(context.InvalidInvocationContext):
            context.current({
                context.CALLER_ENV: "visitor",
                context.DATA_DIR_ENV: str(tmp_path),
            })

    def test_visitor_with_a_blank_slot_raises(self, tmp_path):
        """Blank must not become `default` — that slot is the recipe's own,
        i.e. the owner's page."""
        with pytest.raises(context.InvalidInvocationContext):
            context.current({
                context.CALLER_ENV: "visitor",
                context.SLOT_ENV: "  ",
                context.DATA_DIR_ENV: str(tmp_path),
            })

    def test_visitor_without_a_directory_raises(self):
        with pytest.raises(context.InvalidInvocationContext):
            context.current({
                context.CALLER_ENV: "visitor",
                context.SLOT_ENV: "abc123",
            })


class TestApplyToEnv:
    def test_visitor_context_is_stamped_on(self, tmp_path):
        env = {}
        ctx = context.InvocationContext(
            caller=context.VISITOR, slot="abc123", data_dir=tmp_path
        )
        context.apply_to_env(env, ctx)
        assert env[context.CALLER_ENV] == "visitor"
        assert env[context.SLOT_ENV] == "abc123"
        assert env[context.DATA_DIR_ENV] == str(tmp_path)

    def test_visitor_context_overwrites_what_was_already_there(self, tmp_path):
        """Never "set only if absent". The nearby FRAGO_CURRENT_RUN injection
        is written that way on purpose; copying it here would let one line in
        ~/.frago/.env outrank the platform."""
        env = {
            context.CALLER_ENV: "owner",
            context.SLOT_ENV: "default",
            context.DATA_DIR_ENV: "/somewhere/else",
        }
        context.apply_to_env(
            env,
            context.InvocationContext(
                caller=context.VISITOR, slot="abc123", data_dir=tmp_path
            ),
        )
        assert env[context.CALLER_ENV] == "visitor"
        assert env[context.SLOT_ENV] == "abc123"
        assert env[context.DATA_DIR_ENV] == str(tmp_path)

    def test_owner_run_deletes_inherited_keys(self, tmp_path):
        """The environment handed to a recipe starts as dict(os.environ), so
        "we did not write it" is not the same as "it is not there"."""
        env = {
            context.CALLER_ENV: "visitor",
            context.SLOT_ENV: "someone_elses_account",
            context.DATA_DIR_ENV: str(tmp_path),
            "PATH": "/usr/bin",
        }
        context.apply_to_env(env, None)
        for key in context.CONTEXT_ENV_KEYS:
            assert key not in env
        assert env["PATH"] == "/usr/bin", "unrelated variables must survive"

    def test_an_explicit_owner_context_also_deletes(self, tmp_path):
        env = {context.CALLER_ENV: "visitor", context.SLOT_ENV: "x"}
        context.apply_to_env(env, context.OWNER_CONTEXT)
        assert context.CALLER_ENV not in env
        assert context.SLOT_ENV not in env

    def test_half_a_visitor_context_refuses_to_be_stamped(self):
        env = {}
        with pytest.raises(context.InvalidInvocationContext):
            context.apply_to_env(
                env, context.InvocationContext(caller=context.VISITOR, slot="abc")
            )
        assert env == {}, "nothing may be left behind by a refused stamp"


class TestDataDirHelper:
    def test_owner_gets_the_fallback(self, tmp_path):
        assert context.data_dir(tmp_path / "mine", env={}) == tmp_path / "mine"

    def test_visitor_gets_the_platform_directory(self, tmp_path):
        got = context.data_dir(
            tmp_path / "mine",
            env={
                context.CALLER_ENV: "visitor",
                context.SLOT_ENV: "abc123",
                context.DATA_DIR_ENV: str(tmp_path / "theirs"),
            },
        )
        assert got == tmp_path / "theirs"


class TestThisMachineKnowsWhoItIs:
    """A run has to be able to name whose it is, on a personal laptop as much as
    on a server. The laptop has nobody to ask, so the machine records one
    identity the first time anything needs it and reads it forever after.

    The tests below are mostly about the ways of *not* answering, because the
    tempting failure — mint a fresh id and carry on — succeeds loudly while
    orphaning everything filed under the previous one.
    """

    @pytest.fixture
    def here(self, tmp_path, monkeypatch):
        target = tmp_path / "identity.json"
        monkeypatch.setenv("FRAGO_IDENTITY_FILE", str(target))
        return target

    def test_a_fresh_machine_mints_one_without_being_asked(self, here):
        """A person installing frago on their laptop must never meet the word
        "account". The record is written silently and they never see it."""
        who = context.default_identity()
        assert len(who) == 32 and all(c in "0123456789abcdef" for c in who)
        assert here.is_file()

    def test_the_same_machine_answers_the_same_thing_forever(self, here):
        assert context.default_identity() == context.default_identity()

    def test_the_file_is_not_world_readable(self, here):
        context.default_identity()
        assert here.stat().st_mode & 0o077 == 0

    def test_the_login_name_is_recorded_but_never_read_back(self, here, monkeypatch):
        """Recorded as a label for whoever opens the file. Deriving the id from
        it instead would mean a renamed login loses its data."""
        import json

        monkeypatch.setenv("USER", "someone")
        minted = context.default_identity()
        record = json.loads(here.read_text(encoding="utf-8"))
        assert record["label"] == "someone"
        monkeypatch.setenv("USER", "renamed")
        assert context.default_identity() == minted

    def test_an_unreadable_record_raises_rather_than_starting_over(self, here):
        here.write_text("{ this is not json", encoding="utf-8")
        with pytest.raises(context.NoIdentity) as caught:
            context.default_identity()
        assert str(here) in str(caught.value)

    def test_an_id_that_is_not_an_id_raises(self, here):
        import json

        here.write_text(json.dumps({"id": "me"}), encoding="utf-8")
        with pytest.raises(context.NoIdentity):
            context.default_identity()

    def test_a_broken_record_is_never_overwritten(self, here):
        """Repairing it is the operator's job. Replacing it here would look like
        a clean start and would quietly orphan the data filed under the old id."""
        here.write_text("{ broken", encoding="utf-8")
        with pytest.raises(context.NoIdentity):
            context.default_identity()
        assert here.read_text(encoding="utf-8") == "{ broken"

    def test_a_caller_that_refuses_to_create_gets_told_so(self, here):
        with pytest.raises(context.NoIdentity):
            context.default_identity(create=False)
        assert not here.exists()


class TestDataEverybodyReadsAndOneRecipeWrites:
    """Cross-user data reaches a recipe as a directory the platform names, not
    as something linked into that person's own tree.

    A link states where a thing is. What this directory needs stated is who may
    write it — everyone reads the same copy and exactly one recipe updates it —
    and no arrangement of directories can say that. Handing it over as its own
    variable keeps position and permission as two separate claims.
    """

    def test_it_reaches_a_visitor_run(self, tmp_path):
        env = {}
        context.apply_to_env(env, context.InvocationContext(
            caller=context.VISITOR, slot="a" * 32,
            data_dir=tmp_path / "mine", common_dir=tmp_path / "everyones",
        ))
        assert env[context.COMMON_DIR_ENV] == str(tmp_path / "everyones")
        assert context.current(env).common_dir == tmp_path / "everyones"

    def test_a_recipe_with_nothing_to_share_is_told_nothing(self, tmp_path):
        env = {}
        context.apply_to_env(env, context.InvocationContext(
            caller=context.VISITOR, slot="a" * 32, data_dir=tmp_path / "mine",
        ))
        assert context.COMMON_DIR_ENV not in env
        assert context.current(env).common_dir is None

    def test_an_owner_run_clears_it_like_the_rest(self, tmp_path):
        """Inherited from the server process or set in a .env, it would reach
        every recipe that process starts. Not writing it is not the same as it
        not being there."""
        env = {context.COMMON_DIR_ENV: str(tmp_path / "stale")}
        context.apply_to_env(env, context.OWNER_CONTEXT)
        assert context.COMMON_DIR_ENV not in env


class TestAnOwnerRunKnowsWhoseItIs:
    """The owner used to carry nothing, and that emptiness is what forced every
    recipe to invent a directory of its own — the entrance every one of these
    accidents came through.

    It now carries the same answers a visitor's run does, with one condition:
    the directory is handed over only once this recipe's data has actually been
    copied there. Pointing a recipe at an empty directory while its records sit
    under the old path would be a fresh start nobody asked for and nobody is told
    about.
    """

    @pytest.fixture
    def machine(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FRAGO_IDENTITY_FILE", str(tmp_path / "identity.json"))
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.setenv("FRAGO_USER_STATE_DIR", str(tmp_path / ".frago" / "users"))
        return tmp_path

    def _say_it_moved(self, machine, recipe, slot="default"):
        import json

        manifest = machine / ".frago" / "migration-manifest.jsonl"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"recipe": recipe, "slot": slot}) + "\n")

    def test_it_names_the_person_even_before_anything_moved(self, machine):
        ctx = context.for_owner("demo_board")
        assert ctx.slot == context.default_identity()
        assert ctx.is_visitor is False

    def test_no_directory_until_the_data_is_actually_there(self, machine):
        assert context.for_owner("demo_board").data_dir is None

    def test_the_directory_arrives_once_the_move_is_recorded(self, machine):
        from frago.recipes import app_state

        self._say_it_moved(machine, "demo_board")
        ctx = context.for_owner("demo_board")
        assert ctx.data_dir == app_state.recipe_data_dir(ctx.slot, "demo_board")

    def test_a_project_gets_its_own_directory(self, machine):
        from frago.recipes import app_state

        self._say_it_moved(machine, "video_studio", "20260727-demo")
        ctx = context.for_owner("video_studio", "20260727-demo")
        assert ctx.data_dir == app_state.recipe_data_dir(
            ctx.slot, "video_studio", "20260727-demo"
        )

    def test_it_reaches_the_recipe_and_comes_back_unchanged(self, machine):
        self._say_it_moved(machine, "demo_board")
        given = context.for_owner("demo_board")
        env = {}
        context.apply_to_env(env, given)
        read_back = context.current(env)
        assert read_back.caller == context.OWNER
        assert read_back.slot == given.slot
        assert read_back.data_dir == given.data_dir

    def test_a_bare_owner_context_still_clears_everything(self, machine):
        """A run started by hand, with nobody having said whose it is, behaves
        exactly as frago always has. That path must not change underneath the
        recipes that still rely on it."""
        env = {context.CALLER_ENV: "visitor", context.SLOT_ENV: "x", context.DATA_DIR_ENV: "/y"}
        context.apply_to_env(env, context.OWNER_CONTEXT)
        assert env == {}
        assert context.current({}).slot is None
