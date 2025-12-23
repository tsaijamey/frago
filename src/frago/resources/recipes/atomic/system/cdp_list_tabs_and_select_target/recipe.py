#!/usr/bin/env python3
"""
Recipe: cdp_list_tabs_and_select_target
Description: List all Chrome tabs and select/lock one as the CDP operation target
Created: 2025-11-27
Version: 1.0.0
"""

import json
import sys
from pathlib import Path


def list_tabs(host: str = "127.0.0.1", port: int = 9222) -> list[dict]:
    """
    Get all available Chrome tabs

    Returns:
        list: List of tab information, each tab contains id, title, url, type fields
    """
    import requests

    try:
        response = requests.get(
            f"http://{host}:{port}/json/list",
            timeout=5
        )
        response.raise_for_status()
        all_targets = response.json()

        # Only return page type targets (filter out iframe, worker, etc.)
        pages = [
            {
                "id": t["id"],
                "title": t.get("title", ""),
                "url": t.get("url", ""),
                "type": t.get("type", ""),
                "faviconUrl": t.get("faviconUrl", ""),
                "webSocketDebuggerUrl": t.get("webSocketDebuggerUrl", "")
            }
            for t in all_targets
            if t.get("type") == "page"
        ]

        return pages

    except requests.exceptions.ConnectionError:
        raise ConnectionError(
            f"Unable to connect to Chrome DevTools. Please ensure Chrome is launched in remote debugging mode:\n"
            f"  google-chrome --remote-debugging-port={port}"
        )
    except Exception as e:
        raise RuntimeError(f"Failed to get tabs: {e}")


def select_tab_by_index(tabs: list[dict], index: int) -> dict:
    """Select tab by index"""
    if index < 0 or index >= len(tabs):
        raise ValueError(f"Index out of bounds: {index}, valid range: 0-{len(tabs)-1}")
    return tabs[index]


def select_tab_by_title(tabs: list[dict], title_pattern: str) -> dict:
    """Select tab by title fuzzy matching"""
    for tab in tabs:
        if title_pattern.lower() in tab["title"].lower():
            return tab
    raise ValueError(f"Tab with title containing '{title_pattern}' not found")


def select_tab_by_url(tabs: list[dict], url_pattern: str) -> dict:
    """Select tab by URL fuzzy matching"""
    for tab in tabs:
        if url_pattern.lower() in tab["url"].lower():
            return tab
    raise ValueError(f"Tab with URL containing '{url_pattern}' not found")


def select_tab_by_id(tabs: list[dict], tab_id: str) -> dict:
    """Select tab by exact ID"""
    for tab in tabs:
        if tab["id"] == tab_id:
            return tab
    raise ValueError(f"Tab with ID '{tab_id}' not found")


def save_target_config(tab: dict, config_path: Path = None) -> Path:
    """
    Save the selected tab as target configuration file

    Subsequent frago commands can use this configuration via --target-config parameter
    """
    if config_path is None:
        config_path = Path.home() / ".frago" / "current_target.json"

    config_path.parent.mkdir(parents=True, exist_ok=True)

    config = {
        "target_id": tab["id"],
        "websocket_url": tab["webSocketDebuggerUrl"],
        "title": tab["title"],
        "url": tab["url"]
    }

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    return config_path


def main():
    """Main function"""
    # Parse input parameters
    if len(sys.argv) < 2:
        params = {}
    else:
        try:
            params = json.loads(sys.argv[1])
        except json.JSONDecodeError as e:
            print(json.dumps({
                "success": False,
                "error": f"Failed to parse JSON parameters: {e}"
            }, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)

    # Get configuration
    host = params.get("host", "127.0.0.1")
    port = params.get("port", 9222)
    action = params.get("action", "list")  # list | select

    try:
        # Get all tabs
        tabs = list_tabs(host, port)

        if not tabs:
            print(json.dumps({
                "success": False,
                "error": "No Chrome tabs found"
            }, ensure_ascii=False))
            sys.exit(1)

        if action == "list":
            # List all tabs only
            output = {
                "success": True,
                "action": "list",
                "tabs_count": len(tabs),
                "tabs": [
                    {
                        "index": i,
                        "id": tab["id"],
                        "title": tab["title"][:60] + ("..." if len(tab["title"]) > 60 else ""),
                        "url": tab["url"][:80] + ("..." if len(tab["url"]) > 80 else ""),
                        "full_title": tab["title"],
                        "full_url": tab["url"]
                    }
                    for i, tab in enumerate(tabs)
                ]
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))

        elif action == "select":
            # Select and lock a tab
            selected_tab = None

            if "index" in params:
                selected_tab = select_tab_by_index(tabs, params["index"])
            elif "title" in params:
                selected_tab = select_tab_by_title(tabs, params["title"])
            elif "url" in params:
                selected_tab = select_tab_by_url(tabs, params["url"])
            elif "id" in params:
                selected_tab = select_tab_by_id(tabs, params["id"])
            else:
                print(json.dumps({
                    "success": False,
                    "error": "select operation requires index, title, url or id parameter"
                }, ensure_ascii=False))
                sys.exit(1)

            # Save configuration
            save_config = params.get("save_config", True)
            config_path = None
            if save_config:
                config_path = save_target_config(selected_tab)

            output = {
                "success": True,
                "action": "select",
                "selected_tab": {
                    "id": selected_tab["id"],
                    "title": selected_tab["title"],
                    "url": selected_tab["url"],
                    "websocket_url": selected_tab["webSocketDebuggerUrl"]
                },
                "config_saved": save_config,
                "config_path": str(config_path) if config_path else None,
                "usage_hint": f"Use in subsequent commands: uv run frago --target-id {selected_tab['id']} <command>"
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))

        else:
            print(json.dumps({
                "success": False,
                "error": f"Unknown action: {action}, valid values: list, select"
            }, ensure_ascii=False))
            sys.exit(1)

    except ConnectionError as e:
        print(json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"Execution failed: {type(e).__name__}: {e}"
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
