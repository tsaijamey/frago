"""Recipe output handler"""
import json
from pathlib import Path
from typing import Any


class OutputHandler:
    """Static class for unified handling of Recipe output to different targets"""

    @staticmethod
    def handle(data: dict[str, Any], target: str, options: dict[str, Any] | None = None) -> None:
        """
        Handle Recipe output

        Args:
            data: JSON data returned by Recipe
            target: Output target ('stdout' | 'file' | 'clipboard')
            options: Target-specific options (e.g., 'path' required for file)

        Raises:
            ValueError: Invalid target type or missing required options
            RuntimeError: Output handling failed
        """
        options = options or {}

        if target == 'stdout':
            OutputHandler._to_stdout(data)
        elif target == 'file':
            OutputHandler._to_file(data, options)
        elif target == 'clipboard':
            OutputHandler._to_clipboard(data)
        else:
            raise ValueError(f"Invalid output target: '{target}', valid values: stdout, file, clipboard")

    @staticmethod
    def _to_stdout(data: dict[str, Any]) -> None:
        """Output to standard output"""
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        print(json_str)

    @staticmethod
    def _to_file(data: dict[str, Any], options: dict[str, Any]) -> None:
        """Output to file"""
        if 'path' not in options:
            raise ValueError("file output target requires 'path' option")

        file_path = Path(options['path'])

        # Create parent directory (if needed)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to file
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        try:
            file_path.write_text(json_str, encoding='utf-8')
        except Exception as e:
            raise RuntimeError(f"Failed to write file: {file_path} - {e}")

    @staticmethod
    def _to_clipboard(data: dict[str, Any]) -> None:
        """Output to clipboard"""
        try:
            import pyperclip
        except ImportError:
            raise RuntimeError(
                "clipboard output requires optional dependency pyperclip.\n"
                "Installation:\n"
                "  pip install frago-cli[clipboard]     # clipboard feature only\n"
                "  pip install frago-cli[all]           # all optional features\n"
                "  uv tool install 'frago-cli[clipboard]'  # for uv users"
            )

        json_str = json.dumps(data, ensure_ascii=False)
        try:
            pyperclip.copy(json_str)
        except Exception as e:
            raise RuntimeError(f"Failed to copy to clipboard: {e}")
