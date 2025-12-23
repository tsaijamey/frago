#!/usr/bin/env python3
"""
Recipe: Read clipboard content
Runtime: python
Input parameters: none
Output: Clipboard content in JSON format
"""

import json
import sys


def read_clipboard():
    """Read clipboard content and return in JSON format"""
    try:
        import pyperclip
        content = pyperclip.paste()
        return {
            "content": content,
            "length": len(content)
        }
    except ImportError:
        print("Error: pyperclip module not found. Install with: pip install pyperclip", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    result = read_clipboard()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0)
