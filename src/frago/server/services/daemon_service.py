"""Daemon service — supervises config-declared recipe daemons.

The application-layer middle tier between ``frago autostart`` (OS layer, keeps
the *server process* alive) and ``IngestionScheduler`` stream mode (ingestion
layer, recipe output is interpreted as messages). ``DaemonService`` reads the
top-level ``daemons`` section of ``config.json``, and for each *enabled* item
spawns one :class:`RecipeSupervisor` that keeps the recipe alive as a
subprocess with backoff restart — output goes to the default ``LogSink``, not
the PA queue.

Capability lives in the recipe (``metadata.daemon`` / ``metadata.restart_policy``,
shipped with the recipe), activation lives in config (``daemons.items``, per-host
opt-in + override). A config item whose recipe is missing or not declared
``daemon: true`` is skipped with a warning rather than crashing the server.

Mirrors ``IngestionScheduler`` / ``SchedulerService``: a singleton with
``start()`` / ``stop()`` wired into the server lifespan.
"""

import asyncio
import logging

from frago.server.services.recipe_supervisor import (
    RecipeSupervisor,
    SupervisedRecipe,
)

logger = logging.getLogger(__name__)

_VALID_POLICIES = ("always", "on-failure", "never")


class DaemonService:
    """Supervise the set of recipe daemons declared in config.json."""

    _instance: "DaemonService | None" = None

    def __init__(self, daemons: list[SupervisedRecipe]) -> None:
        self._daemons = daemons
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._supervisors: dict[str, RecipeSupervisor] = {}
        self._stop_event = asyncio.Event()
        # Shared runner — avoids recreating RecipeRegistry per daemon spawn.
        from frago.recipes.runner import RecipeRunner
        self._runner = RecipeRunner()

    @classmethod
    def get_instance(cls) -> "DaemonService | None":
        return cls._instance

    @classmethod
    def from_config(cls, raw_config: dict) -> "DaemonService | None":
        """Build a DaemonService from a parsed config.json dict.

        Returns None when the ``daemons`` section is absent / disabled or
        resolves to zero activatable daemons (recipe missing, not declared
        ``daemon: true``, or item disabled).
        """
        daemons_config = raw_config.get("daemons") or {}
        if not daemons_config.get("enabled", False):
            return None

        from frago.recipes.runner import RecipeRunner
        runner = RecipeRunner()

        specs = cls._resolve_specs(daemons_config.get("items", []), runner)
        if not specs:
            logger.info("No enabled daemons configured, skipping DaemonService")
            return None
        return cls(specs)

    @staticmethod
    def _resolve_specs(items: list[dict], runner: object) -> list[SupervisedRecipe]:
        """Merge metadata defaults with config overrides into SupervisedRecipe.

        Skips (with a warning) items that are disabled, name an unknown recipe,
        or name a recipe whose metadata does not declare ``daemon: true``.
        Deduplicates by recipe name — the first declaration wins.
        """
        specs: list[SupervisedRecipe] = []
        seen: set[str] = set()
        for item in items:
            recipe_name = item.get("recipe")
            if not recipe_name:
                logger.warning("Daemon config item missing 'recipe', skipping: %r", item)
                continue
            if not item.get("enabled", True):
                logger.info("Daemon %s disabled in config, skipping", recipe_name)
                continue
            if recipe_name in seen:
                logger.warning("Daemon %s declared more than once, ignoring duplicate", recipe_name)
                continue

            try:
                recipe = runner.registry.find(recipe_name)
            except Exception as e:
                logger.warning("Daemon %s: recipe not found (%s), skipping", recipe_name, e)
                continue
            if not getattr(recipe.metadata, "daemon", False):
                logger.warning(
                    "Daemon %s: recipe metadata does not declare daemon:true, skipping",
                    recipe_name,
                )
                continue

            # restart_policy: config override > metadata default
            policy = item.get("restart_policy") or getattr(
                recipe.metadata, "restart_policy", "on-failure"
            )
            if policy not in _VALID_POLICIES:
                logger.warning(
                    "Daemon %s: invalid restart_policy %r, falling back to on-failure",
                    recipe_name, policy,
                )
                policy = "on-failure"

            spec = SupervisedRecipe(
                recipe=recipe_name,
                params=item.get("params") or {},
                restart_policy=policy,
                max_backoff=item.get("max_backoff", 60),
                initial_backoff=item.get("initial_backoff", 2),
                startup_delay=item.get("startup_delay", 5.0),
                name=item.get("name") or recipe_name,
            )
            specs.append(spec)
            seen.add(recipe_name)
        return specs

    async def start(self) -> None:
        if self._tasks:
            logger.warning("DaemonService already running")
            return
        self._stop_event.clear()
        for spec in self._daemons:
            supervisor = RecipeSupervisor(
                spec,
                runner=self._runner,
                stop_event=self._stop_event,
            )
            self._supervisors[spec.label] = supervisor
            self._tasks[spec.label] = asyncio.create_task(
                supervisor.run(),
                name=f"daemon-{spec.label}",
            )
        logger.info(
            "DaemonService started (daemons=%s)",
            [s.label for s in self._daemons],
        )

    async def stop(self) -> None:
        if not self._tasks:
            return
        self._stop_event.set()
        tasks = list(self._tasks.values())
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._supervisors.clear()
        logger.info("DaemonService stopped")

    def status(self) -> list[dict]:
        """Return per-daemon runtime state for observability."""
        out: list[dict] = []
        for spec in self._daemons:
            task = self._tasks.get(spec.label)
            supervisor = self._supervisors.get(spec.label)
            proc = getattr(supervisor, "_proc", None) if supervisor else None
            pid = getattr(proc, "pid", None) if proc is not None else None
            alive = proc is not None and proc.returncode is None
            out.append({
                "name": spec.label,
                "recipe": spec.recipe,
                "restart_policy": spec.restart_policy,
                "pid": pid,
                "alive": alive,
                "restarts": getattr(supervisor, "_restarts", 0) if supervisor else 0,
                "running": task is not None and not task.done(),
            })
        return out
