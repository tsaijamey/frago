"""Schedule time-spec parsing for recipe scheduling.

Houses the interval / datetime parsing that ``cli/recipe_commands.py`` used to
carry inline. ``click.BadParameter`` is raised verbatim so the CLI's exit code
(2) and usage-error formatting stay identical after the relocation.
"""
import re
from datetime import datetime, timedelta

import click


def parse_interval(value: str) -> int:
    """Parse interval string to seconds.

    Supports: "30s", "10m", "2h", "1h30m", "600" (pure number = seconds).
    Minimum: 10 seconds.
    """
    value = value.strip()

    # Pure number → seconds
    if value.isdigit():
        seconds = int(value)
    else:
        match = re.fullmatch(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?', value)
        if not match or not any(match.groups()):
            raise click.BadParameter(f"Invalid interval format: '{value}'. Use e.g. 30s, 10m, 2h, 1h30m")
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        secs = int(match.group(3) or 0)
        seconds = hours * 3600 + minutes * 60 + secs

    if seconds < 10:
        raise click.BadParameter(f"Interval too short ({seconds}s). Minimum is 10 seconds.")
    return seconds


def parse_datetime(value: str) -> datetime:
    """Parse datetime string. Supports ISO 8601 and HH:MM."""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            t = datetime.strptime(value, fmt).time()
            today = datetime.now().replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)
            if today <= datetime.now():
                today = today + timedelta(days=1)
            return today
        except ValueError:
            continue

    raise click.BadParameter(f"Cannot parse datetime: '{value}'. Use ISO 8601 or HH:MM format.")
