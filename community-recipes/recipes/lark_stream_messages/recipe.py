# /// script
# requires-python = ">=3.9"
# dependencies = ["lark-oapi"]
# ///
"""Lark bot message stream (long-connection / WebSocket) for frago ingestion.

Subscribes to `im.message.receive_v1` via lark-oapi's WS client and emits one
JSON line per accepted message to stdout. The process stays alive — the
IngestionScheduler (stream mode) reads stdout line by line and feeds each
message into its normal dedup / classify / enqueue pipeline.

stdout line format (one JSON object per line):
  {"type": "message", "id": "om_...", "prompt": "...", "reply_context": {...}}

Whitelist / directory / image download behavior mirrors the Feishu counterpart.
Unlike the polling version we do NOT merge consecutive commands within a
window — stream mode delivers each event as it arrives, and thread_id
classification downstream handles continuity.

This is the Lark (overseas, open.larksuite.com) variant; unlike the Feishu
variant we do NOT strip proxy env vars since the endpoint is international
and normally requires the user's HTTP/HTTPS proxy.

Credentials are injected via FRAGO_SECRETS env var by the recipe runner.
"""
import json
import os
import re
import sys
from pathlib import Path

# lark-oapi internals use print() directly on sys.stdout (not the Python
# logging system), which would pollute the JSON stream protocol on stdout.
# Keep the real stdout saved for _flush, and redirect sys.stdout to stderr so
# every print() (from lark, any third-party library, or our own code) goes
# to stderr instead.
_JSON_STDOUT = sys.stdout
sys.stdout = sys.stderr


def _flush(obj):
    """Emit one JSON line to the (saved) real stdout and flush immediately."""
    _JSON_STDOUT.write(json.dumps(obj, ensure_ascii=False) + "\n")
    _JSON_STDOUT.flush()


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


FRAGO_HOME = Path.home() / ".frago"
FRAGO_CONFIG_PATH = FRAGO_HOME / "config.json"
DIRECTORY_PATH = FRAGO_HOME / "lark_directory.json"
IMAGE_CACHE_DIR = FRAGO_HOME / "cache" / "lark_images"
FILE_CACHE_DIR = FRAGO_HOME / "cache" / "lark_files"

LARK_HOST = "https://open.larksuite.com"


def load_credentials():
    secrets = json.loads(os.environ.get("FRAGO_SECRETS", "{}"))
    app_id = secrets.get("app_id", "")
    app_secret = secrets.get("app_secret", "")
    if not (app_id and app_secret):
        raise ValueError(
            "Lark credentials not found. Configure app_id/app_secret for "
            "lark_stream_messages in recipes.local.json or via the Web UI."
        )
    return app_id, app_secret


def load_whitelist():
    try:
        config = json.loads(FRAGO_CONFIG_PATH.read_text(encoding="utf-8"))
        wl = config.get("task_ingestion", {}).get("whitelist", {}).get("lark", {})
        return {
            "allowed_chats": wl.get("allowed_chats", []),
            "allowed_senders": wl.get("allowed_senders", []),
        }
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return {"allowed_chats": [], "allowed_senders": []}


def get_allowed_chat_ids():
    wl = load_whitelist()
    chats = wl["allowed_chats"]
    if not chats:
        return set()
    return {c["chat_id"] for c in chats}


def get_allowed_sender_ids():
    wl = load_whitelist()
    senders = wl["allowed_senders"]
    if not senders:
        return set()
    return {s["sender_id"] for s in senders}


def update_directory(chat_id, chat_name, sender_id, create_time):
    """Merge one observed chat + sender into lark_directory.json."""
    existing = {}
    if DIRECTORY_PATH.exists():
        try:
            existing = json.loads(DIRECTORY_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    old_chats = {c["chat_id"]: c["name"] for c in existing.get("chats", [])}
    if chat_id:
        old_chats[chat_id] = chat_name or old_chats.get(chat_id) or chat_id
    merged_chats = [
        {"chat_id": cid, "name": name}
        for cid, name in sorted(old_chats.items(), key=lambda x: x[1])
    ]

    old_senders = {s["sender_id"]: s for s in existing.get("senders", [])}
    if sender_id:
        if sender_id in old_senders:
            chat_ids = set(old_senders[sender_id].get("chat_ids", []))
            if chat_id:
                chat_ids.add(chat_id)
            old_senders[sender_id]["chat_ids"] = sorted(chat_ids)
            old_senders[sender_id]["last_seen"] = create_time
        else:
            old_senders[sender_id] = {
                "sender_id": sender_id,
                "chat_ids": [chat_id] if chat_id else [],
                "last_seen": create_time,
            }
    merged_senders = sorted(old_senders.values(), key=lambda s: s["sender_id"])

    DIRECTORY_PATH.write_text(
        json.dumps({"chats": merged_chats, "senders": merged_senders},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_bot_open_id(app_id, app_secret):
    import urllib.request
    data = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(
        f"{LARK_HOST}/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        token = json.loads(resp.read())["tenant_access_token"]
    req2 = urllib.request.Request(
        f"{LARK_HOST}/open-apis/bot/v3/info",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req2, timeout=10) as resp2:
        bot_data = json.loads(resp2.read())
    return bot_data["bot"]["open_id"]


def build_api_client(app_id, app_secret):
    import lark_oapi as lark
    return (
        lark.Client.builder()
        .app_id(app_id)
        .app_secret(app_secret)
        .domain(lark.LARK_DOMAIN)
        .log_level(lark.LogLevel.WARNING)
        .timeout(10)
        .build()
    )


def download_image(api_client, image_key, message_id):
    from lark_oapi.api.im.v1 import GetImageRequest, GetMessageResourceRequest
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = IMAGE_CACHE_DIR / f"{image_key}.png"
    if cached.exists():
        return str(cached)

    if message_id:
        req = (
            GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(image_key)
            .type("image")
            .build()
        )
        resp = api_client.im.v1.message_resource.get(req)
        if resp.success() and resp.file:
            cached.write_bytes(resp.file.read())
            return str(cached)

    req = GetImageRequest.builder().image_key(image_key).build()
    resp = api_client.im.v1.image.get(req)
    if resp.success() and resp.file:
        cached.write_bytes(resp.file.read())
        return str(cached)

    _log(f"[warn] download_image failed: {image_key} code={resp.code} msg={resp.msg}")
    return None


def download_file(api_client, file_key, file_name, message_id):
    from lark_oapi.api.im.v1 import GetMessageResourceRequest
    FILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = FILE_CACHE_DIR / f"{file_key}_{file_name}"
    if cached.exists():
        return str(cached)
    req = (
        GetMessageResourceRequest.builder()
        .message_id(message_id)
        .file_key(file_key)
        .type("file")
        .build()
    )
    resp = api_client.im.v1.message_resource.get(req)
    if resp.success() and resp.file:
        cached.write_bytes(resp.file.read())
        return str(cached)
    _log(f"[warn] download_file failed: {file_name} code={resp.code} msg={resp.msg}")
    return None


def extract_text_from_content(msg_type, content_str, message_id, api_client):
    """Parse msg.content JSON → (text, attachments_paths)."""
    try:
        content = json.loads(content_str)
    except (json.JSONDecodeError, TypeError):
        return content_str, []

    images = []
    if msg_type == "text":
        return content.get("text", ""), images
    if msg_type == "post":
        title = content.get("title", "")
        parts = [title] if title else []
        for lang_content in content.values():
            if isinstance(lang_content, list):
                for para in lang_content:
                    if isinstance(para, list):
                        for elem in para:
                            if isinstance(elem, dict):
                                if elem.get("tag") == "text":
                                    parts.append(elem.get("text", ""))
                                elif elem.get("tag") == "img" and elem.get("image_key"):
                                    p = download_image(api_client, elem["image_key"], message_id)
                                    if p:
                                        images.append(p)
                                        parts.append(f"[image: {p}]")
        return "\n".join(parts), images
    if msg_type == "image":
        image_key = content.get("image_key", "")
        if image_key:
            p = download_image(api_client, image_key, message_id)
            if p:
                images.append(p)
                return f"[image: {p}]", images
        return "[image]", images
    if msg_type == "sticker":
        return "[sticker]", images
    if msg_type == "file":
        file_name = content.get("file_name", "unknown")
        file_key = content.get("file_key", "")
        if file_key and message_id:
            p = download_file(api_client, file_key, file_name, message_id)
            if p:
                images.append(p)
                return f"[file: {p}]", images
        return f"[file: {file_name}]", images
    return f"[{msg_type}]", images


def fetch_message_text(api_client, message_id):
    """Fetch the text of a quoted message by id (for parent_id resolution)."""
    from lark_oapi.api.im.v1 import GetMessageRequest
    try:
        req = GetMessageRequest.builder().message_id(message_id).build()
        resp = api_client.im.v1.message.get(req)
        if not resp.success() or not resp.data or not resp.data.items:
            return None
        msg = resp.data.items[0]
        content = msg.body.content if msg.body else "{}"
        text, _ = extract_text_from_content(msg.msg_type, content, message_id, api_client)
        return text.strip() or None
    except Exception as e:
        _log(f"[warn] fetch_message_text {message_id}: {e}")
        return None


def is_command(text, mentions, bot_open_id):
    t = text.strip().lower()
    bot_mentioned = False
    if mentions and bot_open_id:
        for m in mentions:
            # Mentions from WS event payload are dicts, not SDK objects
            mid = m.get("id", {})
            if isinstance(mid, dict):
                if mid.get("open_id") == bot_open_id:
                    bot_mentioned = True
                    break
            elif mid == bot_open_id:
                bot_mentioned = True
                break
    return bot_mentioned or t.startswith("/") or "frago" in t


def strip_mention(text, mentions, bot_open_id):
    """Replace @-mention placeholders. Bot mentions removed; others → @name."""
    if mentions:
        for m in mentions:
            key = m.get("key")
            if not key:
                continue
            mid = m.get("id", {})
            if isinstance(mid, dict):
                open_id = mid.get("open_id")
            else:
                open_id = mid
            if bot_open_id and open_id == bot_open_id:
                text = text.replace(key, "")
            else:
                name = m.get("name", "")
                if name:
                    text = text.replace(key, f"@{name}")
    text = re.sub(r"@frago\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def react_to_message(api_client, message_id, emoji_type="OnIt"):
    from lark_oapi.api.im.v1 import (
        CreateMessageReactionRequest,
        CreateMessageReactionRequestBody,
        Emoji,
    )
    try:
        body = (
            CreateMessageReactionRequestBody.builder()
            .reaction_type(Emoji.builder().emoji_type(emoji_type).build())
            .build()
        )
        req = (
            CreateMessageReactionRequest.builder()
            .message_id(message_id)
            .request_body(body)
            .build()
        )
        resp = api_client.im.v1.message_reaction.create(req)
        if not resp.success():
            _log(f"[warn] react {message_id}: {resp.msg}")
    except Exception as e:
        _log(f"[warn] react exception: {e}")


def get_chat_name(api_client, chat_id):
    """Best-effort lookup of chat name; returns chat_id on failure."""
    try:
        from lark_oapi.api.im.v1 import GetChatRequest
        req = GetChatRequest.builder().chat_id(chat_id).build()
        resp = api_client.im.v1.chat.get(req)
        if resp.success() and resp.data:
            return resp.data.name or chat_id
    except Exception as e:
        _log(f"[warn] get_chat_name {chat_id}: {e}")
    return chat_id


def make_handler(api_client, bot_open_id, allowed_chat_ids, allowed_sender_ids):
    """Build the P2ImMessageReceiveV1 handler closure."""

    def handler(event):
        try:
            _handle_event(event, api_client, bot_open_id, allowed_chat_ids, allowed_sender_ids)
        except Exception as e:
            _log(f"[error] handler exception: {e}")

    return handler


def _handle_event(event, api_client, bot_open_id, allowed_chat_ids, allowed_sender_ids):
    # event.event.message is a SDK object; pull fields and normalize
    ev = event.event
    msg = ev.message
    sender = ev.sender

    msg_id = msg.message_id
    chat_id = msg.chat_id
    create_time = msg.create_time  # unix ms string
    _log(f"[event] received msg_id={msg_id} chat={chat_id} type={msg.message_type}")

    # Sender info: for user messages sender.sender_id.open_id; for bot messages same
    sender_open_id = ""
    if sender and getattr(sender, "sender_id", None):
        sender_open_id = getattr(sender.sender_id, "open_id", "") or ""
    sender_type = getattr(sender, "sender_type", "") if sender else ""
    is_bot = sender_type == "app"

    # mentions: list of {key, id:{open_id,...}, name, tenant_key}
    mentions_raw = []
    if getattr(msg, "mentions", None):
        for m in msg.mentions:
            mid = getattr(m, "id", None)
            mid_dict = {}
            if mid is not None:
                mid_dict = {
                    "open_id": getattr(mid, "open_id", None),
                    "union_id": getattr(mid, "union_id", None),
                    "user_id": getattr(mid, "user_id", None),
                }
            mentions_raw.append({
                "key": getattr(m, "key", None),
                "id": mid_dict,
                "name": getattr(m, "name", None),
            })

    # Whitelist
    if allowed_chat_ids and chat_id not in allowed_chat_ids:
        return
    sender_allowed = not allowed_sender_ids or is_bot or sender_open_id in allowed_sender_ids

    # Update directory regardless
    chat_name = get_chat_name(api_client, chat_id) if chat_id else ""
    if not is_bot:
        update_directory(chat_id, chat_name, sender_open_id, create_time)

    if is_bot:
        return  # never process bot's own messages as tasks

    # Extract text + attachments
    content_str = msg.content or "{}"
    text, images = extract_text_from_content(msg.message_type, content_str, msg_id, api_client)
    if not text.strip():
        return
    if msg.message_type == "system" or text.startswith("[system]"):
        return
    if "This message was recalled" in text:
        return

    # Command gate: only bot-targeted messages become tasks
    if not sender_allowed:
        return
    if not is_command(text, mentions_raw, bot_open_id):
        return

    clean_text = strip_mention(text, mentions_raw, bot_open_id)

    # Handle quote/reply
    parent_id = getattr(msg, "parent_id", None) or None
    prompt_text = clean_text
    if parent_id:
        quoted = fetch_message_text(api_client, parent_id)
        if quoted:
            prompt_text = f"<quoted_message>{quoted}</quoted_message>\n{clean_text}"

    reply_context = {
        "chat_id": chat_id,
        "chat_name": chat_name,
        "message_id": msg_id,
        "parent_message_id": parent_id,
        "sender_id": sender_open_id,
    }
    if images:
        reply_context["attachments"] = images

    _flush({
        "type": "message",
        "id": msg_id,
        "prompt": prompt_text,
        "reply_context": reply_context,
    })

    # Emoji reaction to signal receipt
    react_to_message(api_client, msg_id)


def main():
    _log("[init] loading Lark credentials + bot open_id")
    app_id, app_secret = load_credentials()
    bot_open_id = get_bot_open_id(app_id, app_secret)
    _log(f"[init] bot_open_id={bot_open_id}")

    allowed_chats = get_allowed_chat_ids()
    allowed_senders = get_allowed_sender_ids()
    _log(
        f"[init] whitelist chats={len(allowed_chats) or 'ALL'} "
        f"senders={len(allowed_senders) or 'ALL'}"
    )

    import lark_oapi as lark
    api_client = build_api_client(app_id, app_secret)

    handler = make_handler(api_client, bot_open_id, allowed_chats, allowed_senders)

    dispatcher = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(handler)
        .build()
    )

    ws_client = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=dispatcher,
        domain=lark.LARK_DOMAIN,
        log_level=lark.LogLevel.INFO,
    )

    _log("[ws] opening long-connection; waiting for im.message.receive_v1 events...")
    # Blocks forever; lark-oapi handles ping/pong + auto reconnect internally.
    ws_client.start()


if __name__ == "__main__":
    main()
