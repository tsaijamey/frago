# /// script
# requires-python = ">=3.9"
# dependencies = ["lark-oapi"]
# ///
"""Feishu bot message stream (long-connection / WebSocket) for frago ingestion.

Subscribes to `im.message.receive_v1` via lark-oapi's WS client and emits one
JSON line per accepted message to stdout. The process stays alive — the
IngestionScheduler (stream mode) reads stdout line by line and feeds each
message into its normal dedup / classify / enqueue pipeline.

stdout line format (one JSON object per line):
  {"type": "message", "id": "om_...", "prompt": "...", "reply_context": {...}}

Whitelist / directory / image download behavior mirrors feishu_check_messages.
Unlike the polling version we do NOT merge consecutive commands within a
window — stream mode delivers each event as it arrives, and thread_id
classification downstream handles continuity.

Credentials are injected via FRAGO_SECRETS env var by the recipe runner.
"""
import json
import os
import re
import sys
from pathlib import Path

# lark-oapi 内部用 print() 直接打到 sys.stdout（不是 Python logging 系统），
# 会污染我们用 stdout 做 JSON 流协议的输出。
# 解决方案：保存真实 stdout 供 _flush 使用，把 sys.stdout 指向 stderr，
# 这样所有 print()（包括 lark、第三方库、我们自己的 print）全部去 stderr。
_JSON_STDOUT = sys.stdout
sys.stdout = sys.stderr


def _flush(obj):
    """Emit one JSON line to the (saved) real stdout and flush immediately."""
    _JSON_STDOUT.write(json.dumps(obj, ensure_ascii=False) + "\n")
    _JSON_STDOUT.flush()


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


# Feishu API is domestic, bypass any proxy
for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(k, None)

FRAGO_HOME = Path.home() / ".frago"
FRAGO_CONFIG_PATH = FRAGO_HOME / "config.json"
DIRECTORY_PATH = FRAGO_HOME / "feishu_directory.json"
IMAGE_CACHE_DIR = FRAGO_HOME / "cache" / "feishu_images"
FILE_CACHE_DIR = FRAGO_HOME / "cache" / "feishu_files"


def load_credentials():
    secrets = json.loads(os.environ.get("FRAGO_SECRETS", "{}"))
    app_id = secrets.get("app_id", "")
    app_secret = secrets.get("app_secret", "")
    if not (app_id and app_secret):
        raise ValueError(
            "飞书凭证未找到。请在 recipes.local.json 或 Web UI 中配置 "
            "feishu_stream_messages 的 app_id/app_secret"
        )
    return app_id, app_secret


def load_whitelist():
    try:
        config = json.loads(FRAGO_CONFIG_PATH.read_text(encoding="utf-8"))
        wl = config.get("task_ingestion", {}).get("whitelist", {}).get("feishu", {})
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
    """Merge one observed chat + sender into feishu_directory.json."""
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
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        token = json.loads(resp.read())["tenant_access_token"]
    req2 = urllib.request.Request(
        "https://open.feishu.cn/open-apis/bot/v3/info",
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
        .domain(lark.FEISHU_DOMAIN)
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


PLACEHOLDER_MAP = {
    "sticker": "[表情包]",
    "audio": "[音频]",
    "media": "[视频]",
    "folder": "[文件夹]",
    "share_chat": "[分享群名片]",
    "share_user": "[分享个人名片]",
    "location": "[位置]",
    "video_chat": "[视频会议]",
    "todo": "[待办]",
    "vote": "[投票]",
    "merge_forward": "[合并转发]",
    "hongbao": "[红包]",
}


def extract_text_from_content(msg_type, content_str, message_id, api_client):
    """Parse msg.content JSON.

    Returns (body_text, placeholder_text, attachment_paths):
      body_text       — user-typed text only (used for 'frago' keyword detection;
                        path-like strings like /home/yammi/.frago/... must NOT leak in)
      placeholder_text — [图片: path] / [文件: path] / [类型] block to append to prompt
      attachment_paths — local cache paths for downloaded media
    """
    try:
        content = json.loads(content_str)
    except (json.JSONDecodeError, TypeError):
        return content_str, "", []

    paths = []
    if msg_type == "text":
        return content.get("text", ""), "", paths
    if msg_type == "post":
        title = content.get("title", "")
        text_parts = [title] if title else []
        ph_parts = []
        for lang_content in content.values():
            if isinstance(lang_content, list):
                for para in lang_content:
                    if isinstance(para, list):
                        for elem in para:
                            if isinstance(elem, dict):
                                if elem.get("tag") == "text":
                                    text_parts.append(elem.get("text", ""))
                                elif elem.get("tag") == "img" and elem.get("image_key"):
                                    p = download_image(api_client, elem["image_key"], message_id)
                                    if p:
                                        paths.append(p)
                                        ph_parts.append(f"[图片: {p}]")
        return "\n".join(text_parts), "\n".join(ph_parts), paths
    if msg_type == "image":
        image_key = content.get("image_key", "")
        if image_key:
            p = download_image(api_client, image_key, message_id)
            if p:
                paths.append(p)
                return "", f"[图片: {p}]", paths
        return "", "[图片]", paths
    if msg_type == "file":
        file_name = content.get("file_name", "unknown")
        file_key = content.get("file_key", "")
        if file_key and message_id:
            p = download_file(api_client, file_key, file_name, message_id)
            if p:
                paths.append(p)
                return "", f"[文件: {p}]", paths
        return "", f"[文件: {file_name}]", paths
    return "", PLACEHOLDER_MAP.get(msg_type, f"[{msg_type}]"), paths


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
        body, ph, _ = extract_text_from_content(msg.msg_type, content, message_id, api_client)
        combined = "\n".join(p for p in (body, ph) if p)
        return combined.strip() or None
    except Exception as e:
        _log(f"[warn] fetch_message_text {message_id}: {e}")
        return None


def is_bot_mentioned(mentions, bot_open_id):
    if not (mentions and bot_open_id):
        return False
    for m in mentions:
        # Mentions from WS event payload are dicts, not SDK objects
        mid = m.get("id", {})
        if isinstance(mid, dict):
            if mid.get("open_id") == bot_open_id:
                return True
        elif mid == bot_open_id:
            return True
    return False


def should_trigger_pa(body_text, mentions, bot_open_id):
    """PA trigger requires either an @-mention of the bot or 'frago' in body text.

    body_text MUST be the raw user-typed text without attachment placeholders
    (which contain ~/.frago/cache/... and would self-trigger).
    """
    if is_bot_mentioned(mentions, bot_open_id):
        return True
    if body_text and re.search(r"frago", body_text, re.IGNORECASE):
        return True
    return False


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

    # Extract text + attachments. body_text is user-typed only; placeholder_text
    # holds [图片: path] / [文件: path] / [类型]. Attachments (image/file) are
    # always downloaded so the agent can reference local paths even if this
    # particular message ends up being context-only.
    content_str = msg.content or "{}"
    body_text, placeholder_text, attachments = extract_text_from_content(
        msg.message_type, content_str, msg_id, api_client
    )
    combined = "\n".join(p for p in (body_text, placeholder_text) if p).strip()
    if not combined:
        return
    if msg.message_type == "system":
        return
    if "This message was recalled" in body_text or "This message was recalled" in placeholder_text:
        return

    # PA trigger gate: must be sender-allowed AND (bot mentioned OR 'frago' in body)
    if not sender_allowed:
        return
    if not should_trigger_pa(body_text, mentions_raw, bot_open_id):
        _log(
            f"[skip] not mentioned, msg {msg_id} parsed to context only, no PA trigger"
        )
        return

    clean_body = strip_mention(body_text, mentions_raw, bot_open_id) if body_text else ""
    prompt_text = "\n".join(p for p in (clean_body, placeholder_text) if p).strip()

    # Handle quote/reply
    parent_id = getattr(msg, "parent_id", None) or None
    if parent_id:
        quoted = fetch_message_text(api_client, parent_id)
        if quoted:
            prompt_text = f"<quoted_message>{quoted}</quoted_message>\n{prompt_text}"

    reply_context = {
        "chat_id": chat_id,
        "chat_name": chat_name,
        "message_id": msg_id,
        "parent_message_id": parent_id,
        "sender_id": sender_open_id,
    }
    if attachments:
        reply_context["attachments"] = attachments

    _flush({
        "type": "message",
        "id": msg_id,
        "prompt": prompt_text,
        "reply_context": reply_context,
    })

    # Emoji reaction to signal receipt
    react_to_message(api_client, msg_id)


def main():
    _log("[init] 加载飞书凭证 + bot open_id")
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
        log_level=lark.LogLevel.INFO,
    )

    _log("[ws] 建立长连接，等待 im.message.receive_v1 事件...")
    # Blocks forever; lark-oapi handles ping/pong + auto reconnect internally.
    ws_client.start()


if __name__ == "__main__":
    main()
