"""Resource Installation Module.

After spec 20260422-init-flow-modernization, init no longer copies Claude
Code commands, skills, or example recipes from the package into the user's
home directory. Only hook scripts (consumed by frago-hook) still need to be
materialised — that's what `ensure_hooks()` does.

The `install_*` and `install_all_resources` functions remain as stubs so
existing callers (e.g. `server/services/init_service.py` → Web InitWizard)
keep working. They return empty `InstallResult`s so the UI renders "nothing
to install" rather than failing with ImportError or KeyError.

`get_package_resources_path()` is kept for one remaining reader: the recipe
registry (`recipes/registry.py`) adds the package `recipes/` directory as a
search path when present. After the bundled recipes are deleted the path
simply won't exist and the try/except caller handles it.
"""

import shutil
from datetime import datetime
from pathlib import Path

from frago.init.models import InstallResult, ResourceStatus, ResourceType


def get_package_resources_path(resource_type: str) -> Path:
    """Return the package's `frago/resources/<resource_type>` directory.

    Raises FileNotFoundError if the directory no longer exists (which is the
    normal case after spec 20260422 for commands/skills/recipes).
    """
    valid_types = ("commands", "skills", "recipes", "hooks")
    if resource_type not in valid_types:
        raise ValueError(
            f"Invalid resource type: {resource_type}, valid values: {valid_types}"
        )

    try:
        from importlib.resources import files
        package_files = files("frago.resources")
        resource_path = Path(str(package_files.joinpath(resource_type)))
        if not resource_path.exists():
            raise FileNotFoundError(
                f"Resource directory does not exist: {resource_path}"
            )
        return resource_path
    except (ImportError, AttributeError) as err:
        import frago.resources
        base_path = Path(frago.resources.__file__).parent
        resource_path = base_path / resource_type
        if not resource_path.exists():
            raise FileNotFoundError(
                f"Resource directory does not exist: {resource_path}"
            ) from err
        return resource_path


def install_commands() -> InstallResult:
    """Deprecated no-op retained for backward compatibility."""
    return InstallResult(resource_type=ResourceType.COMMAND)


def install_skills() -> InstallResult:
    """Deprecated no-op retained for backward compatibility."""
    return InstallResult(resource_type=ResourceType.SKILL)


def install_recipes() -> InstallResult:
    """Deprecated no-op retained for backward compatibility."""
    return InstallResult(resource_type=ResourceType.RECIPE)


def ensure_hooks() -> list[str]:
    """Copy frago-hook scripts into ~/.claude/hooks/frago/ and register them
    in ~/.claude/settings.json.

    Returns the list of newly installed hook descriptions. Safe to call
    repeatedly — already-registered hooks are skipped.
    """
    import json
    from importlib.resources import files as pkg_files

    CLAUDE_DIR = Path.home() / ".claude"
    CLAUDE_SETTINGS_PATH = CLAUDE_DIR / "settings.json"
    TARGET_HOOKS_DIR = CLAUDE_DIR / "hooks" / "frago"
    SOURCE_HOOKS_DIR = Path(str(pkg_files("frago.resources") / "hooks"))

    if not SOURCE_HOOKS_DIR.exists():
        return []

    manifest_path = SOURCE_HOOKS_DIR / "_manifest.json"
    if not manifest_path.exists():
        return []

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    TARGET_HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    CLAUDE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CLAUDE_SETTINGS_PATH.exists():
        try:
            settings = json.loads(CLAUDE_SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            settings = {}
    else:
        settings = {}

    hooks = settings.setdefault("hooks", {})
    installed = []

    for hook_def in manifest.get("hooks", []):
        event = hook_def["event"]
        script = hook_def["script"]
        description = hook_def.get("description", script)

        src_script = SOURCE_HOOKS_DIR / script
        if not src_script.exists():
            continue
        dst_script = TARGET_HOOKS_DIR / script
        shutil.copy2(src_script, dst_script)
        dst_script.chmod(0o755)

        existing_entries = hooks.get(event, [])
        already_registered = any(
            any(script in h.get("command", "") for h in entry.get("hooks", []))
            for entry in existing_entries
        )
        if already_registered:
            continue

        new_entry = {
            "matcher": hook_def.get("matcher", ""),
            "hooks": [
                {
                    "type": "command",
                    "command": f'bash "{dst_script}"',
                    "timeout": hook_def.get("timeout", 10),
                }
            ],
        }
        existing_entries.append(new_entry)
        hooks[event] = existing_entries
        installed.append(description)

    if installed:
        with open(CLAUDE_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)

    return installed


def install_all_resources(
    skip_recipes: bool = False,  # noqa: ARG001
    force_update: bool = False,  # noqa: ARG001
) -> ResourceStatus:
    """Install resources.

    Post-modernization: only hooks are materialised. Commands/skills/recipes
    are left untouched; the corresponding fields in `ResourceStatus` are
    populated with empty `InstallResult`s so downstream UI code renders a
    clean "nothing was installed" state.

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
    status.hooks_installed = ensure_hooks()
    return status


def format_install_summary(status: ResourceStatus) -> str:
    """Format installation summary output."""
    lines = []
    if status.hooks_installed:
        lines.append("\n[*] Installed hooks:")
        for name in status.hooks_installed:
            lines.append(f"  [OK] {name}")
    elif not any([status.commands, status.skills, status.recipes]):
        lines.append("No resources to install")
    return "\n".join(lines)


def get_resources_status() -> dict:
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
