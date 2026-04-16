# /// script
# requires-python = ">=3.9"
# dependencies = ["lark-oapi"]
# ///
"""Feishu broadcast message — sync chat list, manage allowed chats, broadcast.

Config file (.broadcast_config.json) stores all bot chats with numeric indexes.
Only chats whose index appears in allowed_indexes receive broadcasts.
"""
import json
import os
import sys
import time
from pathlib import Path

# Feishu API is domestic, bypass any proxy
for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(k, None)

CONFIG_PATH = Path(__file__).parent / ".broadcast_config.json"
SEND_DELAY = 0.3  # seconds between sends to avoid rate limiting


def load_credentials():
    """Load app_id and app_secret from FRAGO_SECRETS (injected by recipe runner)."""
    secrets = json.loads(os.environ.get("FRAGO_SECRETS", "{}"))
    app_id = secrets.get("app_id", "")
    app_secret = secrets.get("app_secret", "")
    if app_id and app_secret:
        return app_id, app_secret

    raise ValueError(
        "飞书凭证未找到。请在 recipes.local.json 或 Web UI 中配置 feishu_broadcast_message 的 app_id/app_secret"
    )


def build_client(app_id, app_secret):
    import lark_oapi as lark
    return (
        lark.Client.builder()
        .app_id(app_id)
        .app_secret(app_secret)
        .domain(lark.FEISHU_DOMAIN)
        .log_level(lark.LogLevel.WARNING)
        .timeout(10)
        .build()
    )


def fetch_all_chats(client):
    """Fetch all chats the bot belongs to, with pagination."""
    from lark_oapi.api.im.v1 import ListChatRequest

    all_chats = []
    page_token = None

    while True:
        builder = ListChatRequest.builder().page_size(50)
        if page_token:
            builder = builder.page_token(page_token)
        request = builder.build()

        response = client.im.v1.chat.list(request)
        if not response.success():
            raise RuntimeError(f"Failed to list chats: code={response.code}, msg={response.msg}")

        items = response.data.items or []
        for chat in items:
            all_chats.append({
                "chat_id": chat.chat_id,
                "name": chat.name or chat.chat_id,
            })

        if not response.data.has_more:
            break
        page_token = response.data.page_token

    return all_chats


def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"chats": [], "allowed_indexes": []}


def save_config(config):
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def action_sync(client):
    """Sync bot chat list to config. Preserves existing allowed_indexes where possible."""
    print("[sync] 获取机器人所在群列表...", file=sys.stderr)
    chats = fetch_all_chats(client)
    print(f"[sync] 发现 {len(chats)} 个群", file=sys.stderr)

    old_config = load_config()
    # Build lookup from old config: chat_id → index
    old_index_map = {c["chat_id"]: c["index"] for c in old_config.get("chats", [])}
    old_allowed = set(old_config.get("allowed_indexes", []))

    # Assign indexes: preserve old index if chat existed, else assign new
    used_indexes = set(old_index_map.values())
    next_index = max(used_indexes, default=0) + 1

    indexed_chats = []
    new_allowed = []
    for chat in chats:
        if chat["chat_id"] in old_index_map:
            idx = old_index_map[chat["chat_id"]]
        else:
            idx = next_index
            next_index += 1
        indexed_chats.append({
            "index": idx,
            "chat_id": chat["chat_id"],
            "name": chat["name"],
        })
        # Preserve allowed status for existing chats
        if idx in old_allowed:
            new_allowed.append(idx)

    indexed_chats.sort(key=lambda c: c["index"])

    config = {
        "chats": indexed_chats,
        "allowed_indexes": sorted(new_allowed),
    }
    save_config(config)

    for c in indexed_chats:
        marker = "✓" if c["index"] in new_allowed else " "
        print(f"  [{marker}] #{c['index']} {c['name']}", file=sys.stderr)

    print(f"[sync] 配置已保存到 {CONFIG_PATH}", file=sys.stderr)
    print(f"[sync] 允许广播的群: {new_allowed or '无（请编辑 allowed_indexes）'}", file=sys.stderr)

    return config


def action_list():
    """Show current config."""
    config = load_config()
    if not config["chats"]:
        print("[list] 配置为空，请先运行 sync", file=sys.stderr)
        return config

    allowed = set(config.get("allowed_indexes", []))
    print("[list] 当前群配置:", file=sys.stderr)
    for c in config["chats"]:
        marker = "✓" if c["index"] in allowed else " "
        print(f"  [{marker}] #{c['index']} {c['name']} ({c['chat_id'][:16]}...)", file=sys.stderr)
    print(f"[list] 允许广播: {sorted(allowed) or '无'}", file=sys.stderr)

    return config


def action_broadcast(client, text):
    """Send message to all allowed chats."""
    config = load_config()
    if not config["chats"]:
        raise ValueError("配置为空，请先运行 sync")

    allowed = set(config.get("allowed_indexes", []))
    if not allowed:
        raise ValueError("没有允许的群，请编辑 .broadcast_config.json 的 allowed_indexes")

    targets = [c for c in config["chats"] if c["index"] in allowed]
    print(f"[broadcast] 目标群: {len(targets)} 个", file=sys.stderr)

    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

    results = []
    content = json.dumps({"text": text})

    for i, chat in enumerate(targets):
        try:
            body = (
                CreateMessageRequestBody.builder()
                .receive_id(chat["chat_id"])
                .msg_type("text")
                .content(content)
                .build()
            )
            request = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(body)
                .build()
            )
            response = client.im.v1.message.create(request)

            if response.success():
                msg_id = response.data.message_id if response.data else None
                print(f"  [✓] #{chat['index']} {chat['name']}", file=sys.stderr)
                results.append({"index": chat["index"], "name": chat["name"], "status": "ok", "message_id": msg_id})
            else:
                print(f"  [✗] #{chat['index']} {chat['name']}: {response.msg}", file=sys.stderr)
                results.append({"index": chat["index"], "name": chat["name"], "status": "error", "error": response.msg})
        except Exception as e:
            print(f"  [✗] #{chat['index']} {chat['name']}: {e}", file=sys.stderr)
            results.append({"index": chat["index"], "name": chat["name"], "status": "error", "error": str(e)})

        # Rate limiting delay (skip after last)
        if i < len(targets) - 1:
            time.sleep(SEND_DELAY)

    ok_count = sum(1 for r in results if r["status"] == "ok")
    print(f"[broadcast] 完成: {ok_count}/{len(targets)} 成功", file=sys.stderr)

    return results


def main():
    if len(sys.argv) < 2:
        params = {}
    else:
        try:
            params = json.loads(sys.argv[1])
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"参数解析失败: {e}"}))
            sys.exit(1)

    action = params.get("action", "").strip().lower()
    if action not in ("sync", "broadcast", "list"):
        print(json.dumps({"error": "action 必须为 sync / broadcast / list"}))
        sys.exit(1)

    # list doesn't need credentials
    if action == "list":
        config = action_list()
        print(json.dumps({"status": "success", "action": "list", "chats": config["chats"],
                           "allowed_indexes": config.get("allowed_indexes", [])}, ensure_ascii=False))
        return

    # sync and broadcast need credentials + client
    try:
        app_id, app_secret = load_credentials()
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    client = build_client(app_id, app_secret)

    try:
        if action == "sync":
            config = action_sync(client)
            print(json.dumps({"status": "success", "action": "sync", "chats": config["chats"],
                               "allowed_indexes": config.get("allowed_indexes", [])}, ensure_ascii=False))

        elif action == "broadcast":
            text = params.get("text", "").strip()
            if not text:
                print(json.dumps({"error": "broadcast 需要 text 参数"}))
                sys.exit(1)
            results = action_broadcast(client, text)
            ok_count = sum(1 for r in results if r["status"] == "ok")
            print(json.dumps({"status": "success", "action": "broadcast",
                               "sent": ok_count, "total": len(results), "results": results}, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
