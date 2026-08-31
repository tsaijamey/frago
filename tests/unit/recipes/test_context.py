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

    It now carries the same answers a visitor's run does. The directory is
    withheld in one case and one only: this recipe's records are still under an
    old path that nothing has copied, where pointing it at an empty directory
    would be a fresh start nobody asked for and nobody is told about. A recipe
    that never had data anywhere is not that case and gets its directory.
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

    def _say_it_has_records_elsewhere(self, machine, recipe, where, slot="default"):
        import json

        where.mkdir(parents=True, exist_ok=True)
        (where / "ledger.json").write_text("[]", encoding="utf-8")
        note = machine / ".frago" / "app-state" / recipe / f"{slot}.json"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(json.dumps({"dataDir": str(where)}), encoding="utf-8")

    def test_no_directory_while_its_records_are_somewhere_else(self, machine):
        """The one case that withholds it: there is real data under an old path
        and nothing has copied it. Pointing the recipe at an empty directory
        here is a fresh start nobody asked for."""
        self._say_it_has_records_elsewhere(
            machine, "demo_board", machine / ".frago" / "data" / "board"
        )
        assert context.for_owner("demo_board").data_dir is None

    def test_a_recipe_that_never_had_any_data_still_gets_its_directory(self, machine):
        """It can never appear in the migration manifest, having nothing to
        migrate. Reading the manifest as the test meant such a recipe was told
        forever that the platform had not said where to write — harmless while
        every recipe carried a default of its own, fatal once they stopped.

        Found by running `etf_dma_signal_push`, whose state lives inside its own
        package: the migration refuses to move that on purpose, so it could not
        start at all."""
        from frago.recipes import app_state

        ctx = context.for_owner("demo_board")
        assert ctx.data_dir == app_state.recipe_data_dir(ctx.slot, "demo_board")

    def test_a_slot_that_recorded_no_directory_has_nothing_to_lose(self, machine):
        import json

        note = machine / ".frago" / "app-state" / "demo_board" / "default.json"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(json.dumps({"defaults": {"top_n": 5}}), encoding="utf-8")
        assert context.for_owner("demo_board").data_dir is not None

    def test_an_old_directory_that_no_longer_exists_holds_nothing_back(self, machine):
        """Nothing is under it, so there is nothing to start fresh away from."""
        self._say_it_has_records_elsewhere(
            machine, "demo_board", machine / ".frago" / "data" / "board"
        )
        import shutil

        shutil.rmtree(machine / ".frago" / "data" / "board")
        assert context.for_owner("demo_board").data_dir is not None

    def test_the_directory_arrives_once_that_data_is_copied(self, machine):
        from frago.recipes import app_state

        self._say_it_has_records_elsewhere(
            machine, "demo_board", machine / ".frago" / "data" / "board"
        )
        self._say_it_moved(machine, "demo_board")
        ctx = context.for_owner("demo_board")
        assert ctx.data_dir == app_state.recipe_data_dir(ctx.slot, "demo_board")

    def test_one_project_waiting_does_not_hold_back_the_others(self, machine):
        """A multi-project recipe migrates a project at a time. Judging the
        recipe as a whole would refuse six projects because a seventh has not
        moved yet."""
        self._say_it_has_records_elsewhere(
            machine, "video_studio", machine / ".frago" / "data" / "old-demo", "20260727-demo"
        )
        assert context.for_owner("video_studio", "20260727-demo").data_dir is None
        assert context.for_owner("video_studio", "20260820-other").data_dir is not None

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


class TestSharedDataNeedsBothSidesToHaveSaidSomething:
    """Two declarations, said by the two different sides, and neither is enough.

    The consumer's ``reads_common`` says whose data it reads — the recipe
    holding the data has no other way of knowing somebody depends on its layout,
    and edits its own files to break a page it has never heard of.

    The producer's ``shares`` says which block of its own data is open. That is
    the half that used to be missing, and its absence is why the arrangement
    needed an owner's signature: what a declaration bought was a writable handle
    on the producer's *whole* directory, and no amount of signing makes an
    unbounded handle safe. A bounded, read-only block is something a machine can
    hand over — which is exactly why `frago recipe grant` is gone rather than
    merely automated.
    """

    @pytest.fixture
    def machine(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FRAGO_IDENTITY_FILE", str(tmp_path / "identity.json"))
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.setenv("FRAGO_USER_STATE_DIR", str(tmp_path / ".frago" / "users"))
        return tmp_path

    def _registry(self, monkeypatch, *, reads=(), shares=None):
        """A machine holding one consumer and whatever producers ``shares`` names."""
        shares = shares or {}

        class _Meta:
            def __init__(self, reads_common, shared):
                self.reads_common = list(reads_common)
                self.shares = shared

        class _Recipe:
            def __init__(self, meta):
                self.metadata = meta

        class _Registry:
            def find(self, name, source=None):
                from frago.recipes.exceptions import RecipeNotFoundError

                if name == "demo_board":
                    return _Recipe(_Meta(reads, ""))
                if name in shares:
                    return _Recipe(_Meta([], shares[name]))
                raise RecipeNotFoundError(name, [])

        monkeypatch.setattr("frago.recipes.registry.get_registry", lambda: _Registry())

    def test_a_recipe_that_declared_nothing_is_handed_nothing(self, machine, monkeypatch):
        self._registry(monkeypatch, reads=[])
        assert context.common_dirs_for("demo_board") is None
        assert context.for_owner("demo_board").common_dir is None

    def test_reading_something_nobody_shared_is_handed_nothing(self, machine, monkeypatch):
        """Declaring is asking. The answer comes from the other side."""
        self._registry(monkeypatch, reads=["cn_stock_data_feed"],
                       shares={"cn_stock_data_feed": ""})
        root, subtrees, problems = context.shared_with("demo_board")
        assert root is None and subtrees == {}
        assert any("shares" in one for one in problems)

    def test_a_shared_block_becomes_one_entry_in_this_recipe_s_own_door(
            self, machine, monkeypatch):
        self._registry(monkeypatch, reads=["cn_stock_data_feed"],
                       shares={"cn_stock_data_feed": "share/common"})

        root = context.common_dirs_for("demo_board")
        assert root == machine / ".frago" / "recipe-data" / "demo_board" / "reads"
        # The shape recipes already join onto — <root>/<producer>/share/common —
        # comes out at the producer's block and nowhere above it.
        assert (root / "cn_stock_data_feed" / "share" / "common").resolve() == (
            machine / ".frago" / "recipe-data" / "cn_stock_data_feed"
            / "share" / "common"
        )

    def test_nothing_above_the_shared_block_is_reachable_through_the_door(
            self, machine, monkeypatch):
        """The bound is the point: a link at the producer's root would have
        handed over its whole directory, which is what a grant used to sign
        for."""
        self._registry(monkeypatch, reads=["cn_stock_data_feed"],
                       shares={"cn_stock_data_feed": "share/common"})
        root = context.common_dirs_for("demo_board")
        assert not (root / "cn_stock_data_feed").is_symlink()
        assert (root / "cn_stock_data_feed" / "share" / "common").is_symlink()

    def test_a_producer_that_shares_nothing_is_simply_not_there(
            self, machine, monkeypatch):
        self._registry(monkeypatch, reads=["cn_stock_data_feed", "someone_else"],
                       shares={"cn_stock_data_feed": "share/common",
                               "someone_else": ""})
        root = context.common_dirs_for("demo_board")
        # A link, not a copy — and a link whose target may not exist yet, because
        # the producer is entitled not to have run.
        assert (root / "cn_stock_data_feed" / "share" / "common").is_symlink()
        assert not (root / "someone_else").exists()

    def test_withdrawing_takes_the_entry_away_again(self, machine, monkeypatch):
        """A door rebuilt by adding only is a withdrawal that never happens."""
        self._registry(monkeypatch, reads=["cn_stock_data_feed"],
                       shares={"cn_stock_data_feed": "share/common"})
        root = context.common_dirs_for("demo_board")
        assert (root / "cn_stock_data_feed" / "share" / "common").is_symlink()

        self._registry(monkeypatch, reads=["cn_stock_data_feed"],
                       shares={"cn_stock_data_feed": ""})
        assert context.common_dirs_for("demo_board") is None
        assert not (root / "cn_stock_data_feed").exists()

    def test_the_real_block_comes_back_beside_the_door(self, machine, monkeypatch):
        """What the recipe is told about and what the kernel is held to have to
        be the same directory, so both come out of one call."""
        self._registry(monkeypatch, reads=["cn_stock_data_feed"],
                       shares={"cn_stock_data_feed": "share/common"})
        _, subtrees, problems = context.shared_with("demo_board")
        assert problems == []
        assert subtrees == {
            "cn_stock_data_feed": machine / ".frago" / "recipe-data"
            / "cn_stock_data_feed" / "share" / "common"
        }
        assert context.for_owner("demo_board").shared == subtrees

    def test_it_reaches_the_recipe_as_a_variable(self, machine, monkeypatch):
        self._registry(monkeypatch, reads=["cn_stock_data_feed"],
                       shares={"cn_stock_data_feed": "share/common"})
        env = {}
        context.apply_to_env(env, context.for_owner("demo_board"))
        assert env[context.COMMON_DIR_ENV] == str(
            machine / ".frago" / "recipe-data" / "demo_board" / "reads")

    def test_a_producer_nobody_can_find_is_said_out_loud(self, machine, monkeypatch):
        """Silence here is the failure this whole area keeps producing: the run
        starts, reads an empty directory, and reports that there is no data."""
        self._registry(monkeypatch, reads=["gone_away"])
        root, subtrees, problems = context.shared_with("demo_board")
        assert root is None and subtrees == {}
        assert any("gone_away" in one for one in problems)

    def test_a_recipe_nobody_can_find_is_handed_nothing(self, machine, monkeypatch):
        """A registry that cannot answer must not become a reason to open the
        door anyway."""
        from frago.recipes.exceptions import RecipeNotFoundError

        class _Registry:
            def find(self, name, source=None):
                raise RecipeNotFoundError(name, [])

        monkeypatch.setattr("frago.recipes.registry.get_registry", lambda: _Registry())
        assert context.common_dirs_for("nope") is None


class TestAMultiProjectRecipeIsRecognisedAsMigrated:
    """Its projects move one at a time and it never has a `default` slot.

    Reading the manifest for this exact slot withheld the directory from every
    such recipe: the platform had already moved their data and then told them it
    had not said where to write. Found by running one — the manifest held seven
    of its projects and it still refused to start.
    """

    @pytest.fixture
    def machine(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FRAGO_IDENTITY_FILE", str(tmp_path / "identity.json"))
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.setenv("FRAGO_USER_STATE_DIR", str(tmp_path / ".frago" / "users"))
        manifest = tmp_path / ".frago" / "migration-manifest.jsonl"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        import json

        with open(manifest, "w", encoding="utf-8") as fh:
            for slot in ("20260727-demo", "20260820-other"):
                fh.write(json.dumps({"recipe": "video_studio", "slot": slot}) + "\n")
        return tmp_path

    def test_the_base_directory_is_handed_over(self, machine):
        from frago.recipes import app_state

        ctx = context.for_owner("video_studio")
        assert ctx.data_dir == app_state.recipe_data_dir(ctx.slot, "video_studio")

    def test_a_recipe_with_nothing_migrated_is_not_thereby_refused(self, machine):
        """Nothing of its own is left behind anywhere, so there is nothing for
        the platform to be quiet about."""
        assert context.for_owner("never_moved").data_dir is not None
