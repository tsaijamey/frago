"""Resource Installation Module.

After spec 20260422-init-flow-modernization, init no longer copies anything
from the package into the user's home directory — not commands, skills or
example recipes, and since 2026-08-22 not hook scripts either. `ensure_hooks()`
outlived the last script it had to install: its manifest had been empty since
April, so all it still did was recreate an empty ~/.claude/hooks/frago/ on
every server start, one moment before the retirement sweep removed it again.
What frago left in ~/.claude/ on machines installed back then is collected by
`frago.init.retired_artifacts`.

The `install_*` and `install_all_resources` functions remain as stubs so
existing callers (e.g. `server/services/init_service.py` → Web InitWizard)
keep working. They return empty `InstallResult`s so the UI renders "nothing
to install" rather than failing with ImportError or KeyError.

`get_package_resources_path()` used to live here for one remaining reader: the
recipe registry scanned the package's own `recipes/` directory as the
`Official` source. That directory is gone — public recipes moved to
tsaijamey/frago-recipe-community and the package ships none — so the function
went with its last caller, and nothing here invites a future reader to put
recipes back into the wheel.
"""

from datetime import datetime
from typing import Any

from frago.init.models import InstallResult, ResourceStatus, ResourceType


def install_commands() -> InstallResult:
    """Deprecated no-op retained for backward compatibility."""
    return InstallResult(resource_type=ResourceType.COMMAND)


def install_skills() -> InstallResult:
    """Deprecated no-op retained for backward compatibility."""
    return InstallResult(resource_type=ResourceType.SKILL)


def install_recipes() -> InstallResult:
    """Deprecated no-op retained for backward compatibility."""
    return InstallResult(resource_type=ResourceType.RECIPE)


def install_all_resources(
    skip_recipes: bool = False,  # noqa: ARG001
    force_update: bool = False,  # noqa: ARG001
) -> ResourceStatus:
    """Install resources — nothing is materialised any more.

    Commands/skills/recipes are left untouched; the corresponding fields in
    `ResourceStatus` are populated with empty `InstallResult`s so downstream UI
    code renders a clean "nothing was installed" state.

    The `skip_recipes` / `force_update` parameters are preserved for callers
    that still pass them by keyword (e.g. server/services/init_service.py);
    both are now no-ops.
    """
    from frago import __version__

    status = ResourceStatus(
        frago_version=__version__,
        install_time=datetime.now(),
    )
    status.commands = install_commands()
    status.skills = install_skills()
    status.recipes = install_recipes()
    return status


def format_install_summary(status: ResourceStatus) -> str:
    """Format installation summary output.

    Nothing is installed any more, so there is nothing to report. The function
    stays because callers still print its result; `ResourceStatus.hooks_installed`
    stays on the model because the init API's response shape is public.
    """
    if any([status.commands, status.skills, status.recipes]):
        return ""
    return "No resources to install"


def get_resources_status() -> dict[str, Any]:
    """Return a minimal resource status snapshot for API consumers.

    The `available` counts for commands/skills/recipes are always 0 because
    init no longer ships those. Callers that still expect the keys (e.g.
    server/services/init_service.py) get a consistent shape.
    """
    return {
        "commands": {
            "installed": [],
            "available": 0,
            "missing": [],
        },
        "skills": {
            "installed": [],
            "available": 0,
            "missing": [],
        },
        "recipes": {
            "installed": [],
            "available": 0,
            "missing": [],
        },
        "hooks": {
            "installed": [],
        },
    }
