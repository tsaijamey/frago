#!/usr/bin/env python3
"""
Claude Code Session Format Checker

Validates Claude Code JSONL session files against known schema.
Detects new fields, missing fields, type changes, and unknown record types.

Usage:
    uv run python scripts/check_claude_session_format.py <path>

    path: Single .jsonl file or directory containing .jsonl files

Exit codes:
    0: No issues found
    1: Warnings found (new/unknown fields)
    2: Errors found (missing required fields, type mismatches)
"""

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# =============================================================================
# Known Schema Definition (based on Claude Code 2.0.76)
# =============================================================================

# Known record types
KNOWN_TYPES = {"queue-operation", "user", "assistant", "summary", "file-history-snapshot", "system"}

# Metadata types (skipped by frago, but known)
METADATA_TYPES = {"queue-operation", "summary", "file-history-snapshot", "system"}

# Required top-level fields by record type
REQUIRED_FIELDS: Dict[str, Set[str]] = {
    "queue-operation": {"type", "operation", "timestamp", "sessionId"},
    "user": {"type", "uuid", "sessionId", "timestamp", "message", "isSidechain", "userType", "cwd", "version"},
    "assistant": {"type", "uuid", "sessionId", "timestamp", "message", "isSidechain"},
    "system": {"type"},  # Minimal required - other fields are optional
    "summary": {"type"},  # sessionId may be absent in some versions
    "file-history-snapshot": {"type"},  # sessionId may be absent in some versions
}

# Optional top-level fields by record type
OPTIONAL_FIELDS: Dict[str, Set[str]] = {
    "queue-operation": {"content"},
    "user": {"parentUuid", "gitBranch", "slug", "toolUseResult", "isMeta", "sourceToolUseID",
             "agentId", "imagePasteIds", "isCompactSummary", "isVisibleInTranscriptOnly",
             "thinkingMetadata", "todos"},
    "assistant": {"parentUuid", "gitBranch", "slug", "userType", "cwd", "version", "requestId",
                  "agentId", "error", "isApiErrorMessage"},
    "system": {"uuid", "sessionId", "timestamp", "parentUuid", "message", "cwd", "version",
               "gitBranch", "slug", "userType", "isSidechain", "isMeta", "subtype", "level",
               "content", "error", "cause", "compactMetadata", "logicalParentUuid",
               "maxRetries", "retryAttempt", "retryInMs"},
    "summary": {"sessionId", "leafUuid", "summary", "uuid", "timestamp"},
    "file-history-snapshot": {"sessionId", "snapshot", "messageId", "isSnapshotUpdate", "uuid", "timestamp"},
}

# Expected field types (Python type names)
FIELD_TYPES: Dict[str, str] = {
    "type": "str",
    "uuid": "str",
    "sessionId": "str",
    "timestamp": "str",
    "parentUuid": "str|None",
    "isSidechain": "bool",
    "userType": "str",
    "cwd": "str",
    "version": "str",
    "gitBranch": "str",
    "slug": "str",
    "message": "dict",
    "requestId": "str",
    "operation": "str",
    "toolUseResult": "dict|str",
    "isMeta": "bool",
    "sourceToolUseID": "str",
}

# message.content block types
KNOWN_CONTENT_BLOCK_TYPES = {"text", "tool_use", "tool_result", "image", "thinking"}

# tool_use input field patterns (known tool names -> expected input fields)
KNOWN_TOOLS: Dict[str, Set[str]] = {
    "Bash": {"command", "description", "timeout", "run_in_background", "dangerouslyDisableSandbox"},
    "Read": {"file_path", "offset", "limit"},
    "Write": {"file_path", "content"},
    "Edit": {"file_path", "old_string", "new_string", "replace_all"},
    "Glob": {"pattern", "path"},
    "Grep": {"pattern", "path", "glob", "type", "output_mode", "-A", "-B", "-C", "-i", "-n", "head_limit", "offset", "multiline"},
    "Task": {"prompt", "description", "subagent_type", "model", "resume", "run_in_background"},
    "TaskOutput": {"task_id", "block", "timeout"},
    "Skill": {"skill", "args"},
    "WebFetch": {"url", "prompt"},
    "WebSearch": {"query", "allowed_domains", "blocked_domains"},
    "TodoWrite": {"todos"},
    "AskUserQuestion": {"questions", "answers"},
    "LSP": {"operation", "filePath", "line", "character"},
    "ExitPlanMode": set(),
    "EnterPlanMode": set(),
    "KillShell": {"shell_id"},
    "NotebookEdit": {"notebook_path", "new_source", "cell_id", "cell_type", "edit_mode"},
    # Added in 2.0.55+
    "BashOutput": {"bash_id"},  # Get output from background bash command
    "SlashCommand": {"command"},  # Execute slash command (deprecated, use Skill)
}


# =============================================================================
# Checker Implementation
# =============================================================================

class SchemaChecker:
    """Check JSONL records against known schema."""

    def __init__(self):
        self.warnings: List[str] = []
        self.errors: List[str] = []
        self.stats = Counter()
        self.new_fields: Dict[str, Set[str]] = defaultdict(set)
        self.new_types: Set[str] = set()
        self.new_content_types: Set[str] = set()
        self.new_tools: Set[str] = set()
        self.type_mismatches: List[str] = []

    def check_file(self, path: Path) -> None:
        """Check a single JSONL file."""
        if not path.exists():
            self.errors.append(f"File not found: {path}")
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                line_num = 0
                for line in f:
                    line_num += 1
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        record = json.loads(line)
                        self.check_record(record, f"{path.name}:{line_num}")
                    except json.JSONDecodeError as e:
                        self.errors.append(f"{path.name}:{line_num}: JSON parse error: {e}")
        except Exception as e:
            self.errors.append(f"Failed to read {path}: {e}")

    def check_record(self, record: Dict[str, Any], location: str) -> None:
        """Check a single record against schema."""
        record_type = record.get("type")

        if not record_type:
            self.errors.append(f"{location}: Missing 'type' field")
            self.stats["missing_type"] += 1
            return

        self.stats[f"type:{record_type}"] += 1

        # Check for unknown record type
        if record_type not in KNOWN_TYPES:
            self.new_types.add(record_type)
            self.warnings.append(f"{location}: Unknown record type: {record_type}")
            return

        # Check required fields
        required = REQUIRED_FIELDS.get(record_type, set())
        for field in required:
            if field not in record:
                self.errors.append(f"{location}: Missing required field '{field}' for type '{record_type}'")
                self.stats["missing_required"] += 1

        # Check for new fields
        known = required | OPTIONAL_FIELDS.get(record_type, set())
        for field in record.keys():
            if field not in known:
                self.new_fields[record_type].add(field)

        # Check field types
        for field, value in record.items():
            expected_type = FIELD_TYPES.get(field)
            if expected_type:
                if not self._check_type(value, expected_type):
                    actual_type = type(value).__name__
                    self.type_mismatches.append(
                        f"{location}: Field '{field}' expected {expected_type}, got {actual_type}"
                    )

        # Deep check message content
        if "message" in record and isinstance(record["message"], dict):
            self._check_message(record["message"], location, record_type)

    def _check_type(self, value: Any, expected: str) -> bool:
        """Check if value matches expected type."""
        type_map = {
            "str": str,
            "bool": bool,
            "int": int,
            "float": (int, float),
            "dict": dict,
            "list": list,
            "None": type(None),
        }

        # Handle union types like "dict|str" or "str|None"
        if "|" in expected:
            allowed_types = expected.split("|")
            for t in allowed_types:
                t = t.strip()
                if t == "None" and value is None:
                    return True
                expected_class = type_map.get(t)
                if expected_class and isinstance(value, expected_class):
                    return True
            return False

        expected_class = type_map.get(expected)
        if expected_class:
            return isinstance(value, expected_class)
        return True

    def _check_message(self, message: Dict[str, Any], location: str, record_type: str) -> None:
        """Check message structure."""
        content = message.get("content")

        if content is None:
            return

        # String content (simple user message)
        if isinstance(content, str):
            return

        # Array content
        if isinstance(content, list):
            for i, block in enumerate(content):
                if isinstance(block, dict):
                    block_type = block.get("type")
                    if block_type and block_type not in KNOWN_CONTENT_BLOCK_TYPES:
                        self.new_content_types.add(block_type)

                    # Check tool_use blocks
                    if block_type == "tool_use":
                        tool_name = block.get("name")
                        if tool_name and tool_name not in KNOWN_TOOLS:
                            self.new_tools.add(tool_name)

    def print_report(self) -> int:
        """Print report and return exit code."""
        print("\n" + "=" * 60)
        print("Claude Code Session Format Check Report")
        print("=" * 60)

        # Statistics
        print("\n📊 Statistics:")
        for key, count in sorted(self.stats.items()):
            print(f"   {key}: {count}")

        # New types
        if self.new_types:
            print(f"\n⚠️  NEW RECORD TYPES ({len(self.new_types)}):")
            for t in sorted(self.new_types):
                print(f"   - {t}")

        # New fields
        if self.new_fields:
            print(f"\n⚠️  NEW FIELDS:")
            for record_type, fields in sorted(self.new_fields.items()):
                print(f"   [{record_type}]: {', '.join(sorted(fields))}")

        # New content block types
        if self.new_content_types:
            print(f"\n⚠️  NEW CONTENT BLOCK TYPES ({len(self.new_content_types)}):")
            for t in sorted(self.new_content_types):
                print(f"   - {t}")

        # New tools
        if self.new_tools:
            print(f"\n⚠️  NEW TOOLS ({len(self.new_tools)}):")
            for t in sorted(self.new_tools):
                print(f"   - {t}")

        # Type mismatches
        if self.type_mismatches:
            print(f"\n❌ TYPE MISMATCHES ({len(self.type_mismatches)}):")
            for m in self.type_mismatches[:10]:  # Limit output
                print(f"   {m}")
            if len(self.type_mismatches) > 10:
                print(f"   ... and {len(self.type_mismatches) - 10} more")

        # Errors
        if self.errors:
            print(f"\n❌ ERRORS ({len(self.errors)}):")
            for e in self.errors[:20]:  # Limit output
                print(f"   {e}")
            if len(self.errors) > 20:
                print(f"   ... and {len(self.errors) - 20} more")

        # Warnings
        if self.warnings:
            print(f"\n⚠️  WARNINGS ({len(self.warnings)}):")
            for w in self.warnings[:20]:
                print(f"   {w}")
            if len(self.warnings) > 20:
                print(f"   ... and {len(self.warnings) - 20} more")

        # Summary
        print("\n" + "-" * 60)
        has_new = bool(self.new_types or self.new_fields or self.new_content_types or self.new_tools)
        has_errors = bool(self.errors or self.type_mismatches)

        if not has_new and not has_errors:
            print("✅ All records match known schema.")
            return 0
        elif has_errors:
            print("❌ Schema errors detected. Review and update frago implementation.")
            return 2
        else:
            print("⚠️  New schema elements detected. Review and update documentation.")
            return 1


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    path = Path(sys.argv[1])
    checker = SchemaChecker()

    if path.is_file():
        print(f"Checking file: {path}")
        checker.check_file(path)
    elif path.is_dir():
        jsonl_files = list(path.glob("*.jsonl"))
        print(f"Checking directory: {path} ({len(jsonl_files)} .jsonl files)")
        for f in jsonl_files:
            checker.check_file(f)
    else:
        print(f"Error: Path not found: {path}")
        sys.exit(1)

    exit_code = checker.print_report()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
