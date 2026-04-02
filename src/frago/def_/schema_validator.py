"""Schema validator for domain documents.

Validates data against a domain's schema definition before save.
"""

from typing import Any


def validate(schema: dict[str, Any], data: dict[str, Any]) -> list[str]:
    """Validate data against schema fields.

    Returns a list of error messages. Empty list = valid.
    """
    errors = []
    fields = schema.get("fields", [])

    field_defs = {f["name"]: f for f in fields}

    # Check required fields
    for field in fields:
        if field.get("required") and field["name"] not in data:
            errors.append(f"Missing required field: {field['name']}")

    # Check field types
    for key, value in data.items():
        if key not in field_defs:
            continue  # Extra fields are allowed (passthrough)
        field_def = field_defs[key]
        ftype = field_def["type"]

        if ftype == "string" and not isinstance(value, str):
            errors.append(f"Field '{key}' must be a string, got {type(value).__name__}")
        elif ftype == "enum":
            allowed = field_def.get("values", [])
            if value not in allowed:
                errors.append(f"Field '{key}' must be one of {allowed}, got '{value}'")
        elif ftype == "list" and not isinstance(value, list):
            errors.append(f"Field '{key}' must be a list, got {type(value).__name__}")
        elif ftype == "date" and not isinstance(value, str):
            errors.append(f"Field '{key}' must be a date string, got {type(value).__name__}")

    return errors
