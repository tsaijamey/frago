"""Two strictnesses, because the parameters have two origins.

Loose is the owner's own machine, where 270-odd installed recipes were written
against a check that lets undeclared keys through. Strict is a stranger over
HTTP, where an undeclared key is not a harmless extra — eleven installed recipes
read ``params["data_dir"]`` and use it as a filesystem path.

The pair of tests that matters most is the same parameter passing loosely and
failing strictly. Anything that made those two agree would either break the
owner's machine or open the visitor's path.
"""

import logging

import pytest

from frago.recipes.exceptions import RecipeValidationError
from frago.recipes.metadata import RecipeMetadata, validate_params


def _meta(inputs):
    return RecipeMetadata(
        name="demo",
        type="atomic",
        runtime="python",
        version="1.0.0",
        description="d",
        use_cases=["u"],
        output_targets=["stdout"],
        inputs=inputs,
    )


DECLARED = {
    "note": {"type": "string", "required": False, "max_length": 10},
    "kind": {"type": "string", "required": False, "enum": ["in", "out"]},
    "amount": {"type": "number", "required": False, "min": 0, "max": 100},
    "code": {"type": "string", "required": False, "pattern": r"[a-z]{3}"},
}


class TestUndeclaredKeys:
    def test_loose_lets_them_through_exactly_as_before(self):
        validate_params(_meta(DECLARED), {"data_dir": "/etc"})

    def test_strict_refuses_them(self):
        with pytest.raises(RecipeValidationError, match="not declared"):
            validate_params(_meta(DECLARED), {"data_dir": "/etc"}, strict=True)

    def test_loose_says_so_in_the_log_rather_than_silently(self, caplog):
        """This is how an owner finds out that a page they are about to expose
        would refuse its own parameters the moment a visitor sent them."""
        with caplog.at_level(logging.DEBUG, logger="frago.recipes.metadata"):
            validate_params(_meta(DECLARED), {"data_dir": "/etc"})
        assert "data_dir" in caplog.text


class TestConstraintsAreStrictOnly:
    @pytest.mark.parametrize("params", [
        {"note": "x" * 50},
        {"kind": "sideways"},
        {"amount": 999},
        {"amount": -1},
        {"code": "ABCDEF"},
    ])
    def test_strict_enforces_them(self, params):
        with pytest.raises(RecipeValidationError):
            validate_params(_meta(DECLARED), params, strict=True)

    @pytest.mark.parametrize("params", [
        {"note": "x" * 50},
        {"kind": "sideways"},
        {"amount": 999},
    ])
    def test_loose_does_not(self, params):
        validate_params(_meta(DECLARED), params)

    @pytest.mark.parametrize("params", [
        {"note": "short"},
        {"kind": "in"},
        {"amount": 0},
        {"amount": 100},
        {"code": "abc"},
    ])
    def test_values_within_their_limits_pass_strictly(self, params):
        validate_params(_meta(DECLARED), params, strict=True)


class TestTheOldChecksStillApply:
    def test_a_missing_required_parameter_fails_either_way(self):
        meta = _meta({"who": {"type": "string", "required": True}})
        for strict in (False, True):
            with pytest.raises(RecipeValidationError, match="Missing required"):
                validate_params(meta, {}, strict=strict)

    def test_a_wrong_type_fails_either_way(self):
        meta = _meta({"n": {"type": "number", "required": False}})
        for strict in (False, True):
            with pytest.raises(RecipeValidationError, match="type error"):
                validate_params(meta, {"n": "not a number"}, strict=strict)

    def test_a_wrong_type_does_not_also_report_its_constraints(self):
        """One complaint per parameter. "must be one of [...]" about a value
        that is not even the right type is noise on top of the real answer."""
        meta = _meta({"kind": {"type": "string", "required": False, "enum": ["in"]}})
        with pytest.raises(RecipeValidationError) as caught:
            validate_params(meta, {"kind": 7}, strict=True)
        assert "must be one of" not in str(caught.value)


class TestRecipesWithoutConstraintsAreUnaffected:
    def test_a_plain_declaration_accepts_anything_of_the_right_type(self):
        meta = _meta({"note": {"type": "string", "required": False}})
        validate_params(meta, {"note": "x" * 10_000}, strict=True)

    def test_a_recipe_declaring_nothing_accepts_nothing_strictly(self):
        """Declaring no inputs and being runnable means accepting no
        parameters — which is a coherent thing to be, not an error."""
        meta = _meta({})
        validate_params(meta, {}, strict=True)
        with pytest.raises(RecipeValidationError):
            validate_params(meta, {"anything": 1}, strict=True)


class TestABrokenPatternIsTheAuthorsFault:
    def test_it_refuses_rather_than_quietly_not_applying(self):
        """A constraint that silently stops applying is worse than one that was
        never written: the recipe still claims it is there."""
        meta = _meta({"code": {"type": "string", "required": False, "pattern": "([a-z"}})
        with pytest.raises(RecipeValidationError, match="unusable pattern"):
            validate_params(meta, {"code": "abc"}, strict=True)
