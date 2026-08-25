"""Recipe metadata parsing and validation"""
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .exceptions import MetadataParseError, RecipeValidationError

logger = logging.getLogger(__name__)


@dataclass
class RecipeMetadata:
    """Recipe metadata"""
    name: str
    type: str  # atomic | workflow
    runtime: str  # chrome-js | python | shell
    version: str
    description: str  # AI-understandable field
    use_cases: list[str]  # AI-understandable field
    output_targets: list[str]  # AI-understandable field: stdout | file | clipboard
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)  # AI-understandable field
    secrets: dict[str, dict[str, Any]] = field(default_factory=dict)  # Secrets schema (keys align with recipes.local.json)
    system_packages: bool = False  # Use system Python (for scripts depending on system packages like dbus)
    no_proxy: bool = False  # Strip proxy env vars from subprocess (for domestic APIs like Feishu)
    daemon: bool = False  # Capability declaration: this recipe may run as a supervised daemon
    restart_policy: str = "on-failure"  # Default daemon restart policy (config.json daemons may override)
    warnings: list[dict[str, str]] = field(default_factory=list)  # Security warnings for UI display
    flow: list[dict[str, Any]] = field(default_factory=list)  # Workflow execution flow
    # Name of another recipe whose assets/ holds this recipe's web page. Set it
    # only when one front end genuinely serves several recipes — otherwise a
    # recipe's page belongs in its own assets/, where it ships and versions
    # together with the script that answers its requests.
    ui_from: str | None = None
    # Which other recipes' shared data this one reads. Declared rather than
    # reached for: the recipe holding the data has no way of knowing somebody
    # depends on its directory layout, so it changes its own files and breaks a
    # page it has never heard of. A declaration is the only thing that puts the
    # dependency somewhere both sides can see it — and it is what lets the
    # platform hand over the directory instead of the recipe naming a path.
    reads_common: list[str] = field(default_factory=list)

    #: The modes other modules may call — this module's exported surface.
    #: Exported modes are read-only by contract: no network, no recomputation,
    #: no state change, no browser. The hub refuses anything not listed here,
    #: so a caller can never reach past the surface into a mode that does work.
    exports: list[str] = field(default_factory=list)

    #: Whose surface this module depends on, as ``{recipe: [mode, ...]}``.
    #: Written down so the dependency exists on both sides. Until now the
    #: module being read had no way of knowing anyone depended on it, which is
    #: why editing its own files broke pages it had never heard of.
    imports: dict[str, list[str]] = field(default_factory=dict)
    # When the recipe first appeared and when it last changed, ISO-8601 strings.
    # Backfilled from the ~/.frago git history (first / last commit touching the
    # recipe directory); a recipe not yet committed falls back to file mtime.
    # Optional so a hand-written recipe stays valid before the dates are stamped.
    created_at: str | None = None
    updated_at: str | None = None


def _iso_or_none(value: Any) -> str | None:
    """Normalize a frontmatter date to an ISO-8601 string.

    YAML turns an unquoted `2026-02-12` into a date object, so accept both that
    and a plain string rather than letting the type depend on how it was quoted.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def parse_metadata_file(path: Path) -> RecipeMetadata:
    """
    Parse metadata from YAML frontmatter in Markdown file

    Args:
        path: Metadata file path (.md file)

    Returns:
        RecipeMetadata object

    Raises:
        MetadataParseError: Raised when parsing fails
    """
    try:
        content = path.read_text(encoding='utf-8')
    except Exception as e:
        raise MetadataParseError(str(path), f"Cannot read file: {e}") from e

    # Extract YAML frontmatter
    if not content.startswith('---'):
        raise MetadataParseError(str(path), "File does not start with '---', missing YAML frontmatter")

    parts = content.split('---', 2)
    if len(parts) < 3:
        raise MetadataParseError(str(path), "YAML frontmatter format error, missing closing '---'")

    yaml_content = parts[1].strip()

    # Parse YAML
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        raise MetadataParseError(str(path), f"YAML parsing failed: {e}") from e

    if not isinstance(data, dict):
        raise MetadataParseError(str(path), "YAML frontmatter must be in dictionary format")

    # Build RecipeMetadata object
    try:
        metadata = RecipeMetadata(
            name=data['name'],
            type=data['type'],
            runtime=data['runtime'],
            version=data['version'],
            description=data['description'],
            use_cases=data['use_cases'],
            output_targets=data['output_targets'],
            inputs=data.get('inputs', {}),
            outputs=data.get('outputs', {}),
            dependencies=data.get('dependencies', []),
            tags=data.get('tags', []),
            secrets=data.get('secrets', {}),
            system_packages=data.get('system_packages', False),
            no_proxy=data.get('no_proxy', False),
            daemon=data.get('daemon', False),
            restart_policy=data.get('restart_policy', 'on-failure'),
            warnings=data.get('warnings', []),
            flow=data.get('flow', []),
            ui_from=data.get('ui_from'),
            reads_common=data.get('reads_common') or [],
            exports=data.get('exports') or [],
            imports=data.get('imports') or {},
            created_at=_iso_or_none(data.get('created_at')),
            updated_at=_iso_or_none(data.get('updated_at')),
        )
    except KeyError as e:
        raise MetadataParseError(str(path), f"Missing required field: {e}") from e
    except Exception as e:
        raise MetadataParseError(str(path), f"Metadata construction failed: {e}") from e

    return metadata


def validate_metadata(metadata: RecipeMetadata) -> None:
    """
    Validate metadata validity

    Args:
        metadata: Metadata object to validate

    Raises:
        RecipeValidationError: Raised when validation fails
    """
    errors = []

    # Validate name
    if not metadata.name or not re.match(r'^[a-zA-Z0-9_-]+$', metadata.name):
        errors.append("name must only contain letters, numbers, underscores, and hyphens")

    # Validate type
    if metadata.type not in ['atomic', 'workflow']:
        errors.append(f"type must be 'atomic' or 'workflow', current value: '{metadata.type}'")

    # Validate runtime
    if metadata.runtime not in ['chrome-js', 'python', 'shell']:
        errors.append(f"runtime must be 'chrome-js', 'python' or 'shell', current value: '{metadata.runtime}'")

    # Validate version
    if not re.match(r'^\d+\.\d+(\.\d+)?$', metadata.version):
        errors.append(f"version format invalid: '{metadata.version}', expected format: '1.0' or '1.0.0'")

    # AI field validation
    if not metadata.description or len(metadata.description) > 200:
        errors.append("description must exist and length <= 200 characters")

    if not metadata.use_cases or len(metadata.use_cases) == 0:
        errors.append("use_cases must contain at least one use case")

    if not metadata.output_targets or len(metadata.output_targets) == 0:
        errors.append("output_targets must contain at least one output target")

    for target in metadata.output_targets:
        if target not in ['stdout', 'file', 'clipboard']:
            errors.append(f"output_targets contains invalid value: '{target}', valid values: stdout, file, clipboard")

    # Validate daemon restart_policy
    if metadata.restart_policy not in ('always', 'on-failure', 'never'):
        errors.append(
            f"restart_policy must be 'always', 'on-failure' or 'never', current value: '{metadata.restart_policy}'"
        )

    # Validate inputs
    for param_name, param_def in metadata.inputs.items():
        if 'type' not in param_def or 'required' not in param_def:
            errors.append(f"Input parameter '{param_name}' is missing 'type' or 'required' field")

    # Validate secrets
    for secret_name, secret_def in metadata.secrets.items():
        # Secret name must be a valid identifier
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', secret_name):
            errors.append(f"Secret '{secret_name}' name invalid, must start with letter or underscore")
        # secret_def should be a dictionary
        if not isinstance(secret_def, dict):
            errors.append(f"Secret '{secret_name}' definition must be in dictionary format")
        else:
            # type field is required
            if 'type' not in secret_def:
                errors.append(f"Secret '{secret_name}' is missing 'type' field")
            elif secret_def['type'] not in ('string', 'number', 'boolean', 'object', 'array'):
                errors.append(f"Secret '{secret_name}' has invalid type: '{secret_def['type']}'")
            # required field must be boolean if present
            if 'required' in secret_def and not isinstance(secret_def['required'], bool):
                errors.append(f"Secret '{secret_name}' 'required' field must be boolean")

    if errors:
        raise RecipeValidationError(metadata.name, errors)


def validate_params(
    metadata: RecipeMetadata, params: dict[str, Any], *, strict: bool = False
) -> None:
    """
    Validate if runtime-provided parameters conform to metadata definition

    Two strictnesses, because the parameters have two very different origins.

    On the owner's own machine they come from the owner, and the loose reading
    has been in place long enough that 270-odd installed recipes were written
    against it: undeclared keys pass through, and a declared `string` may be any
    string at all. Tightening that for everybody would turn a security
    improvement into a day of broken recipes, so ``strict=False`` keeps the old
    behaviour exactly and merely logs what strict would have rejected — the
    drift becomes visible without anything breaking.

    ``strict=True`` is for parameters that arrived from a stranger over HTTP.
    There, an undeclared key is not a harmless extra: a recipe reading
    ``params.get('data_dir')`` — eleven installed ones do — turns an undeclared
    key into a filesystem path chosen by the caller. So strict rejects anything
    the recipe did not declare, and enforces the value constraints alongside.

    Args:
        metadata: Recipe metadata
        params: User-provided parameters
        strict: Reject undeclared keys and enforce value constraints

    Raises:
        RecipeValidationError: Raised when parameter validation fails
    """
    errors = []

    # Check if required parameters are provided
    for param_name, param_def in metadata.inputs.items():
        if param_def.get('required', False) and param_name not in params:
            param_desc = param_def.get('description', '')
            error_msg = f"Missing required parameter: '{param_name}'"
            if param_desc:
                error_msg += f" ({param_desc})"
            errors.append(error_msg)

    strict_only = []

    # Check provided parameter types
    for param_name, param_value in params.items():
        if param_name not in metadata.inputs:
            # Undeclared. Loosely this is how it has always worked; strictly it
            # is the whole point of the check, because the recipe may well read
            # it and the caller is a stranger.
            strict_only.append(
                f"Parameter '{param_name}' is not declared by this recipe"
            )
            continue
        param_def = metadata.inputs[param_name]
        expected_type = param_def.get('type')
        if expected_type:
            type_errors = check_param_type(param_name, param_value, expected_type)
            errors.extend(type_errors)
            if type_errors:
                continue
        strict_only.extend(check_param_constraints(param_name, param_value, param_def))

    if strict:
        errors.extend(strict_only)
    elif strict_only:
        # Not an error here, but not silence either: this is how an owner finds
        # out that a recipe they are about to expose would refuse its own
        # parameters the moment a visitor sent them.
        logger.debug(
            "recipe %s: parameters a strict caller would have been refused: %s",
            metadata.name, "; ".join(strict_only),
        )

    if errors:
        raise RecipeValidationError(metadata.name, errors)


def check_param_constraints(
    param_name: str, value: Any, param_def: dict[str, Any]
) -> list[str]:
    """Value constraints, all optional. An absent constraint is not checked.

    Optional so that every existing ``recipe.md`` stays valid unchanged: a
    recipe declares a constraint when it wants one. They exist because a
    declared type is a weak statement about a value from a stranger — `string`
    admits a ten-megabyte string, and `number` admits one that will be used as
    a count.
    """
    errors: list[str] = []

    allowed = param_def.get('enum')
    if isinstance(allowed, list) and allowed and value not in allowed:
        errors.append(
            f"Parameter '{param_name}' must be one of {allowed}, got {value!r}"
        )

    max_length = param_def.get('max_length')
    if isinstance(max_length, int) and hasattr(value, '__len__') and len(value) > max_length:
        errors.append(
            f"Parameter '{param_name}' is longer than {max_length} ({len(value)})"
        )

    pattern = param_def.get('pattern')
    if isinstance(pattern, str) and pattern and isinstance(value, str):
        try:
            if not re.fullmatch(pattern, value):
                errors.append(f"Parameter '{param_name}' does not match {pattern!r}")
        except re.error:
            # A broken pattern is the recipe author's mistake, not the caller's.
            # Refuse rather than skip: a constraint that silently stops applying
            # is worse than one that never existed, because the page still says
            # it is there.
            errors.append(f"Parameter '{param_name}' has an unusable pattern {pattern!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        low = param_def.get('min')
        high = param_def.get('max')
        if isinstance(low, (int, float)) and value < low:
            errors.append(f"Parameter '{param_name}' is below the minimum {low}")
        if isinstance(high, (int, float)) and value > high:
            errors.append(f"Parameter '{param_name}' is above the maximum {high}")

    return errors


def check_param_type(param_name: str, value: Any, expected_type: str) -> list[str]:
    """
    Check if parameter value type matches expected type

    Args:
        param_name: Parameter name
        value: Parameter value
        expected_type: Expected type (string, number, boolean, array, object)

    Returns:
        Error message list (empty means validation passed)
    """
    errors = []

    # Type mapping
    type_checks = {
        'string': lambda v: isinstance(v, str),
        'number': lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        'boolean': lambda v: isinstance(v, bool),
        'array': lambda v: isinstance(v, list),
        'object': lambda v: isinstance(v, dict),
    }

    # `array|string` — a parameter that genuinely accepts either shape. Real
    # recipes want this: a list of tags, or the same tags as one comma-separated
    # string. Without it an author has two choices and both are wrong. Declare
    # one type and the other shape is rejected out here, before the recipe runs,
    # with a message from the platform — the recipe never gets to explain what
    # it would have accepted. Declare something the platform does not recognise
    # and the check is skipped entirely, which reads like "either is fine" and
    # actually means "nothing is checked at all". One recipe was already relying
    # on that second accident.
    if '|' in expected_type:
        options = [t.strip() for t in expected_type.split('|') if t.strip()]
        unknown = [t for t in options if t not in type_checks]
        if unknown:
            return [f"Parameter '{param_name}' declares unknown type(s): "
                    f"{', '.join(unknown)}"]
        if any(type_checks[t](value) for t in options):
            return []
        return [f"Parameter '{param_name}' type mismatch: expected one of "
                f"{' or '.join(options)}, got {type(value).__name__}"]

    if expected_type not in type_checks:
        # Unknown type, skip check
        return errors

    check_func = type_checks[expected_type]
    if not check_func(value):
        # Type mismatch
        actual_type = type(value).__name__
        if isinstance(value, bool):
            actual_type = 'boolean'
        elif isinstance(value, (int, float)):
            actual_type = 'number'
        elif isinstance(value, str):
            actual_type = 'string'
        elif isinstance(value, list):
            actual_type = 'array'
        elif isinstance(value, dict):
            actual_type = 'object'

        errors.append(
            f"Parameter '{param_name}' type error: expected {expected_type}, actual {actual_type}"
        )

    return errors
