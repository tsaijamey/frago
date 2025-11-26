#!/usr/bin/env python3
"""
Recipe: 读取剪贴板内容
运行时: python
输入参数: 无
输出: JSON 格式的剪贴板内容
"""

import json
import sys


def read_clipboard():
    """读取剪贴板内容并返回 JSON 格式"""
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
