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
