#!/usr/bin/env python3
"""Validate community recipe format for CI"""
import re
import sys
from pathlib import Path
from typing import Optional

import yaml


# Required fields in recipe metadata
REQUIRED_FIELDS = [
    'name',
    'type',
    'runtime',
    'version',
    'description',
    'use_cases',
    'output_targets',
]

# Valid values for certain fields
VALID_TYPES = ['atomic', 'workflow']
VALID_RUNTIMES = ['chrome-js', 'python', 'shell']
VALID_OUTPUT_TARGETS = ['stdout', 'file', 'clipboard']

# Script file extensions by runtime
SCRIPT_EXTENSIONS = {
    'chrome-js': '.js',
    'python': '.py',
    'shell': '.sh',
}


def parse_yaml_frontmatter(content: str) -> tuple[Optional[dict], str]:
    """Parse YAML frontmatter from markdown content"""
    if not content.startswith('---'):
        return None, "File must start with YAML frontmatter (---)"

    parts = content.split('---', 2)
    if len(parts) < 3:
        return None, "Invalid YAML frontmatter format (missing closing ---)"

    try:
        metadata = yaml.safe_load(parts[1])
        if not isinstance(metadata, dict):
            return None, "YAML frontmatter must be a dictionary"
        return metadata, ""
    except yaml.YAMLError as e:
        return None, f"YAML parse error: {e}"


def validate_recipe(recipe_dir: Path) -> list[str]:
    """
    Validate a single recipe directory

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    # Check recipe.md exists
    metadata_path = recipe_dir / 'recipe.md'
    if not metadata_path.exists():
        errors.append(f"Missing recipe.md in {recipe_dir.name}")
        return errors

    # Read and parse recipe.md
    try:
        content = metadata_path.read_text(encoding='utf-8')
    except Exception as e:
        errors.append(f"Failed to read recipe.md: {e}")
        return errors

    # Parse YAML frontmatter
    metadata, parse_error = parse_yaml_frontmatter(content)
    if parse_error:
        errors.append(parse_error)
        return errors

    # Validate required fields
    for field in REQUIRED_FIELDS:
        if field not in metadata:
            errors.append(f"Missing required field: {field}")

    # Validate name matches directory
    if metadata.get('name') != recipe_dir.name:
        errors.append(
            f"Recipe name '{metadata.get('name')}' "
            f"does not match directory name '{recipe_dir.name}'"
        )

    # Validate name format
    name = metadata.get('name', '')
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        errors.append(
            f"Invalid name format: '{name}' "
            "(must be alphanumeric with - and _)"
        )

    # Validate type
    recipe_type = metadata.get('type')
    if recipe_type not in VALID_TYPES:
        errors.append(
            f"Invalid type: '{recipe_type}' "
            f"(must be one of: {', '.join(VALID_TYPES)})"
        )

    # Validate runtime
    runtime = metadata.get('runtime')
    if runtime not in VALID_RUNTIMES:
        errors.append(
            f"Invalid runtime: '{runtime}' "
            f"(must be one of: {', '.join(VALID_RUNTIMES)})"
        )

    # Validate version format
    version = metadata.get('version', '')
    if not re.match(r'^\d+\.\d+(\.\d+)?$', str(version)):
        errors.append(
            f"Invalid version format: '{version}' "
            "(must be X.Y or X.Y.Z)"
        )

    # Validate description length
    description = metadata.get('description', '')
    if len(description) > 200:
        errors.append(
            f"Description too long: {len(description)} chars "
            "(max 200)"
        )

    # Validate use_cases is a non-empty list
    use_cases = metadata.get('use_cases', [])
    if not isinstance(use_cases, list) or len(use_cases) == 0:
        errors.append("use_cases must be a non-empty list")

    # Validate output_targets
    output_targets = metadata.get('output_targets', [])
    if not isinstance(output_targets, list) or len(output_targets) == 0:
        errors.append("output_targets must be a non-empty list")
    else:
        for target in output_targets:
            if target not in VALID_OUTPUT_TARGETS:
                errors.append(
                    f"Invalid output_target: '{target}' "
                    f"(must be one of: {', '.join(VALID_OUTPUT_TARGETS)})"
                )

    # Check script file exists
    if runtime in SCRIPT_EXTENSIONS:
        ext = SCRIPT_EXTENSIONS[runtime]
        script_path = recipe_dir / f"recipe{ext}"
        if not script_path.exists():
            errors.append(f"Missing script file: recipe{ext}")
        else:
            # Check script is not empty
            try:
                script_content = script_path.read_text(encoding='utf-8').strip()
                if not script_content:
                    errors.append(f"Script file is empty: recipe{ext}")

                # Basic syntax check for Python
                if runtime == 'python':
                    try:
                        compile(script_content, str(script_path), 'exec')
                    except SyntaxError as e:
                        errors.append(
                            f"Python syntax error: {e.msg} "
                            f"(line {e.lineno})"
                        )
            except Exception as e:
                errors.append(f"Failed to read script file: {e}")

    # Validate inputs format (if present)
    inputs = metadata.get('inputs', {})
    if inputs and isinstance(inputs, dict):
        for param_name, param_def in inputs.items():
            if not isinstance(param_def, dict):
                errors.append(f"Input '{param_name}' must be a dictionary")
            elif 'type' not in param_def:
                errors.append(f"Input '{param_name}' missing 'type' field")
            elif 'required' not in param_def:
                errors.append(f"Input '{param_name}' missing 'required' field")

    return errors


def main():
    """Main entry point"""
    recipes_base = Path('community-recipes/recipes')

    if not recipes_base.exists():
        print("Error: community-recipes/recipes directory not found")
        sys.exit(1)

    recipe_names = sys.argv[1:]
    if not recipe_names:
        print("No recipes specified for validation")
        sys.exit(0)

    all_errors: dict[str, list[str]] = {}
    validated_count = 0

    for recipe_name in recipe_names:
        recipe_name = recipe_name.strip()
        if not recipe_name:
            continue

        recipe_dir = recipes_base / recipe_name
        if not recipe_dir.exists():
            print(f"Warning: Recipe directory not found: {recipe_name}")
            continue

        print(f"Validating: {recipe_name}")
        errors = validate_recipe(recipe_dir)
        validated_count += 1

        if errors:
            all_errors[recipe_name] = errors

    # Report results
    print()
    if all_errors:
        print("=" * 60)
        print("VALIDATION FAILED")
        print("=" * 60)
        for name, errors in all_errors.items():
            print(f"\n{name}:")
            for error in errors:
                print(f"  - {error}")
        print()
        sys.exit(1)
    else:
        print("=" * 60)
        print(f"VALIDATION PASSED ({validated_count} recipe(s))")
        print("=" * 60)
        sys.exit(0)


if __name__ == '__main__':
    main()
