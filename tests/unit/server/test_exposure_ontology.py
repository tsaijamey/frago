"""`PublicExposableRecipe` and the anonymous gate must give one answer.

They disagreed about `frago_home`. The ontology read "this recipe marks
`@action`" as "an anonymous reader can write here" and refused it a `--public`
policy, while `~/.frago/published.json` holds `frago_home` as `mode: "public"`.
Both readings were defensible and neither layer was talking to the other.

The correction is not to stop checking. The axiom is about **what an anonymous
reader can reach**, and once `GET`/`HEAD` were confined to `@export`, a
`--public` page's `@action` is unreachable to an anonymous reader unless
somebody registered a door for it by name in `security._ANON_POST`. These tests
pin both halves of that statement, and the production reader that makes the
projection more than a rule only tests evaluate.

They live here rather than under `tests/unit/ontology/` because the second half
of the fact — which anonymous entrances exist — belongs to `server.security`,
and the wiring between the two layers is what was missing.
"""

from __future__ import annotations

import pytest

from frago.ontology import (
    BUILTIN_DEFINED_CLASSES,
    Capability,
    FivePillarShadowProjector,
    ProjectionValidationError,
)
from frago.server import security


def _recipe_graph(modes: dict[str, str]):
    """A projected recipe, as the ontology sees one."""
    projector = FivePillarShadowProjector()
    projector.project_recipe({"name": "candidate", "version": "1.0.0", "modes": modes})
    return projector.graph


class TestTheAxiomReadsReachabilityNotDeclaration:
    def test_an_export_only_recipe_is_exposable(self):
        graph = _recipe_graph({"stats": "export_readonly"})
        recipe = graph.get_entity("recipe:candidate")
        assert BUILTIN_DEFINED_CLASSES["PublicExposableRecipe"].matches(recipe, graph)

    def test_a_reachable_write_makes_it_inexposable(self):
        """`action_triggerable` means "an anonymous reader can reach this write"."""
        graph = _recipe_graph({"refresh": "action_triggerable"})
        recipe = graph.get_entity("recipe:candidate")
        assert not BUILTIN_DEFINED_CLASSES["PublicExposableRecipe"].matches(recipe, graph)

    def test_a_page_calling_its_own_backend_makes_it_inexposable(self):
        """The axiom's second clause: declared in `frago.json`, unread until now.

        A page that fetches `api/<mode>` in a way the anonymous zone refuses
        renders its empty state with nothing anywhere reporting a fault — the
        failure `frago recipe expose --public` refuses up front. An axiom whose
        second half is never evaluated is a clause nobody can rely on.
        """
        graph = _recipe_graph({"stats": "export_readonly"})
        recipe = graph.get_entity("recipe:candidate")
        graph.link(
            recipe,
            "has_capability",
            Capability(
                bearer_id=recipe.ontological_id(),
                context_id="page:candidate",
                dependent_type="app_api_from_public_page",
            ),
        )
        assert not BUILTIN_DEFINED_CLASSES["PublicExposableRecipe"].matches(recipe, graph)


class TestTheProjectionAgreesWithTheAxiom:
    def test_an_export_only_recipe_projects(self):
        projector = FivePillarShadowProjector()
        projector.project_recipe({"name": "candidate", "modes": {"stats": "export_readonly"}})
        policy = projector.project_recipe_exposure(
            {"recipe_name": "candidate", "access": "public"}
        )
        assert policy.ontological_id() == "exposure:candidate:public@1.0.0"

    def test_a_reachable_write_is_refused(self):
        projector = FivePillarShadowProjector()
        projector.project_recipe({"name": "candidate", "modes": {"stats": "export_readonly"}})
        with pytest.raises(ProjectionValidationError, match="PublicExposableRecipe"):
            projector.project_recipe_exposure(
                {
                    "recipe_name": "candidate",
                    "access": "public",
                    "unargued_anon_write": True,
                }
            )

    def test_a_page_that_calls_its_own_backend_is_refused(self):
        projector = FivePillarShadowProjector()
        projector.project_recipe({"name": "candidate", "modes": {"stats": "export_readonly"}})
        with pytest.raises(ProjectionValidationError, match="PublicExposableRecipe"):
            projector.project_recipe_exposure(
                {
                    "recipe_name": "candidate",
                    "access": "public",
                    "page_calls_api_from_public_page": True,
                }
            )

    def test_a_recipe_that_was_never_projected_is_not_judged(self):
        """Not knowing a recipe is not a verdict about it.

        Refusing here would turn "the caller did not project the recipe first"
        into a security finding, and the caller is often a CLI that has no graph.
        """
        projector = FivePillarShadowProjector()
        policy = projector.project_recipe_exposure(
            {"recipe_name": "never_seen", "access": "public"}
        )
        assert policy.ontological_id() == "exposure:never_seen:public@1.0.0"


class TestTheFactsComeFromTheGateNotFromTheDeclaration:
    """The production reader: `security.anon_reachable_writes` / `exposure_facts`.

    This is the half that was missing. The projection could not agree with
    reality while the fact it needs had no reader — and the fact cannot be read
    from inside `frago.ontology`, which may import only the standard library and
    itself. So `security` computes it and the caller hands it in.
    """

    def test_the_registered_entrance_is_read_off_the_gate_table(self):
        # The entrance `frago_home` has: a write, registered by name, with its
        # reason written beside it in `_ANON_POST`.
        assert security.anon_reachable_writes("frago_home") == ("submit_request",)

    def test_a_recipe_with_no_entrance_has_none(self):
        assert security.anon_reachable_writes("frago_login_portal") == ()
        assert security.anon_reachable_writes("github_star_watch") == ()

    def test_marking_an_argued_for_action_is_not_an_unargued_write(self, monkeypatch):
        """The disagreement, resolved.

        `frago_home` marks `@action submit_request` and is published `--public`.
        Both are true: the entrance was argued for by name, and a page action is
        reachable only by the owner now that `GET`/`HEAD` stop at `@export`.
        """
        monkeypatch.setattr(
            "frago.recipes.contract.page_actions_of",
            lambda name, wanted=None: ("submit_request",),
        )
        facts = security.exposure_facts("frago_home")
        assert facts["unargued_anon_write"] is False
        # Its one action is admitted, so its page can load its own data.
        assert facts["page_calls_api_from_public_page"] is False

    def test_an_action_the_gate_refuses_reads_as_a_page_that_calls_its_backend(
            self, monkeypatch):
        """A button the gate refuses means the page cannot load its own data.

        That is the failure `expose --public` exists to catch — seen from the
        declaration rather than from the page's source. `github_star_watch`'s
        `update`/`backfill` are exactly this shape: marked for the page, and no
        anonymous POST entrance admits them.
        """
        monkeypatch.setattr(
            "frago.recipes.contract.page_actions_of",
            lambda name, wanted=None: ("update",),
        )
        assert security.exposure_facts("github_star_watch")[
            "page_calls_api_from_public_page"] is True

    def test_an_unreadable_declaration_does_not_read_as_safe(self, monkeypatch):
        def _explode(name, wanted=None):
            raise OSError("recipe tree unreadable")

        monkeypatch.setattr("frago.recipes.contract.page_actions_of", _explode)
        assert security.exposure_facts("unreadable")[
            "page_calls_api_from_public_page"] is True


class TestTheServingPathConsultsTheOntology:
    def test_the_projection_has_a_production_caller(self):
        """`public_exposure_is_consistent` is that caller, and it has to run.

        It reports rather than refuses — the moment to act on what it finds is
        `frago recipe expose`, where the page can still be fixed — but a
        projection nobody calls is a rule only tests evaluate, which is what it
        was.
        """
        assert security.public_exposure_is_consistent("frago_login_portal") is None

    def test_a_public_page_marking_an_action_is_consistent(self):
        """The exact disagreement this work exists to remove.

        `frago_home` is published `--public` and marks `@action submit_request`.
        Its one action has an argued-for entrance, so the ontology has nothing to
        say against it and its exposure is legitimate.
        """
        assert security.public_exposure_is_consistent("frago_home") is None

    def test_it_names_what_it_would_refuse(self, monkeypatch):
        """A page that cannot load its own data anonymously is reported, not served.

        The reason comes back as a line for the caller to log; it does not raise
        and it does not change what is served.
        """
        monkeypatch.setattr(
            "frago.recipes.contract.page_actions_of",
            lambda name, wanted=None: ("update",),
        )
        reason = security.public_exposure_is_consistent("github_star_watch")
        assert reason is not None
        assert "github_star_watch" in reason
