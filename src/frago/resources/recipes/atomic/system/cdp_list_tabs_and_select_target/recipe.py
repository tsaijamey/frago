#!/usr/bin/env python3
"""
Recipe: cdp_list_tabs_and_select_target
Description: 列出Chrome所有tabs并选择/锁定其中一个作为CDP操作目标
Created: 2025-11-27
Version: 1.0.0
"""

import json
import sys
from pathlib import Path


def list_tabs(host: str = "127.0.0.1", port: int = 9222) -> list[dict]:
    """
    获取Chrome所有可用的tabs

    Returns:
        list: tab信息列表，每个tab包含id, title, url, type等字段
    """
    import requests

    try:
        response = requests.get(
            f"http://{host}:{port}/json/list",
            timeout=5
        )
        response.raise_for_status()
        all_targets = response.json()

        # 只返回page类型的targets（过滤iframe、worker等）
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
            f"无法连接到Chrome DevTools。请确保Chrome以远程调试模式启动:\n"
            f"  google-chrome --remote-debugging-port={port}"
        )
    except Exception as e:
        raise RuntimeError(f"获取tabs失败: {e}")


def select_tab_by_index(tabs: list[dict], index: int) -> dict:
    """通过索引选择tab"""
    if index < 0 or index >= len(tabs):
        raise ValueError(f"索引越界: {index}，有效范围: 0-{len(tabs)-1}")
    return tabs[index]


def select_tab_by_title(tabs: list[dict], title_pattern: str) -> dict:
    """通过标题模糊匹配选择tab"""
    for tab in tabs:
        if title_pattern.lower() in tab["title"].lower():
            return tab
    raise ValueError(f"未找到标题包含 '{title_pattern}' 的tab")


def select_tab_by_url(tabs: list[dict], url_pattern: str) -> dict:
    """通过URL模糊匹配选择tab"""
    for tab in tabs:
        if url_pattern.lower() in tab["url"].lower():
            return tab
    raise ValueError(f"未找到URL包含 '{url_pattern}' 的tab")


def select_tab_by_id(tabs: list[dict], tab_id: str) -> dict:
    """通过精确ID选择tab"""
    for tab in tabs:
        if tab["id"] == tab_id:
            return tab
    raise ValueError(f"未找到ID为 '{tab_id}' 的tab")


def save_target_config(tab: dict, config_path: Path = None) -> Path:
    """
    保存选中的tab为目标配置文件

    后续frago命令可以通过 --target-config 参数使用这个配置
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
    """主函数"""
    # 解析输入参数
    if len(sys.argv) < 2:
        params = {}
    else:
        try:
            params = json.loads(sys.argv[1])
        except json.JSONDecodeError as e:
            print(json.dumps({
                "success": False,
                "error": f"参数JSON解析失败: {e}"
            }, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)

    # 获取配置
    host = params.get("host", "127.0.0.1")
    port = params.get("port", 9222)
    action = params.get("action", "list")  # list | select

    try:
        # 获取所有tabs
        tabs = list_tabs(host, port)

        if not tabs:
            print(json.dumps({
                "success": False,
                "error": "没有找到任何Chrome tab"
            }, ensure_ascii=False))
            sys.exit(1)

        if action == "list":
            # 仅列出所有tabs
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
            # 选择并锁定一个tab
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
                    "error": "select操作需要指定 index、title、url 或 id 参数"
                }, ensure_ascii=False))
                sys.exit(1)

            # 保存配置
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
                "usage_hint": f"后续命令使用: uv run frago --target-id {selected_tab['id']} <command>"
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))

        else:
            print(json.dumps({
                "success": False,
                "error": f"未知action: {action}，有效值: list, select"
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
            "error": f"执行失败: {type(e).__name__}: {e}"
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
