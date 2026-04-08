"""Recipe metadata parsing and validation"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .exceptions import MetadataParseError, RecipeValidationError


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
    warnings: list[dict[str, str]] = field(default_factory=list)  # Security warnings for UI display
    flow: list[dict[str, Any]] = field(default_factory=list)  # Workflow execution flow


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
            warnings=data.get('warnings', []),
            flow=data.get('flow', []),
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


def validate_params(metadata: RecipeMetadata, params: dict[str, Any]) -> None:
    """
    Validate if runtime-provided parameters conform to metadata definition

    Args:
        metadata: Recipe metadata
        params: User-provided parameters

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

    # Check provided parameter types
    for param_name, param_value in params.items():
        if param_name in metadata.inputs:
            param_def = metadata.inputs[param_name]
            expected_type = param_def.get('type')
            if expected_type:
                type_errors = check_param_type(param_name, param_value, expected_type)
                errors.extend(type_errors)

    if errors:
        raise RecipeValidationError(metadata.name, errors)


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
