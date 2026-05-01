# /// script
# requires-python = ">=3.9"
# dependencies = ["lark-oapi"]
# ///
"""Feishu bot message poller for frago ingestion.

Fetches recent messages from chats the bot is in. Messages that @ the bot
are returned as tasks; other messages in the same chat are attached as
context (up to CONTEXT_LIMIT messages before each task).

Whitelist is read from ~/.frago/config.json → task_ingestion.whitelist.feishu:
  - allowed_chats: [{chat_id, name}] — only these chats are polled
  - allowed_senders: [{sender_id, name}] — only these users' messages become tasks
    (empty list = all senders in allowed chats are accepted)

Each poll writes .chat_and_sender_directory.json to the recipe directory,
recording all seen chat names/ids and sender ids for easy whitelist configuration.

Credentials are injected via FRAGO_SECRETS env var by the recipe runner,
configured in ~/.frago/recipes.local.json or Web UI.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

# Feishu API is domestic, bypass any proxy
for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(k, None)

FRAGO_HOME = Path.home() / ".frago"
FRAGO_CONFIG_PATH = FRAGO_HOME / "config.json"
DIRECTORY_PATH = FRAGO_HOME / "feishu_directory.json"
# Directory to store downloaded images and files
IMAGE_CACHE_DIR = Path.home() / ".frago" / "cache" / "feishu_images"
FILE_CACHE_DIR = Path.home() / ".frago" / "cache" / "feishu_files"

# Max context messages to attach before each task
CONTEXT_LIMIT = 10
# Max chars per context message (0 = no limit)
CONTEXT_MSG_LIMIT = 0
# Max seconds between consecutive commands to merge into one task
MERGE_WINDOW_MS = 60_000


def load_credentials():
    """Load app_id and app_secret from FRAGO_SECRETS (injected by recipe runner)."""
    secrets = json.loads(os.environ.get("FRAGO_SECRETS", "{}"))
    app_id = secrets.get("app_id", "")
    app_secret = secrets.get("app_secret", "")
    if app_id and app_secret:
        return {"app_id": app_id, "app_secret": app_secret}

    raise ValueError(
        "飞书凭证未找到。请在 recipes.local.json 或 Web UI 中配置 feishu_check_messages 的 app_id/app_secret"
    )


def load_whitelist():
    """Load feishu whitelist from ~/.frago/config.json → task_ingestion.whitelist.feishu.

    Returns {"allowed_chats": [{chat_id, name}], "allowed_senders": [{sender_id, name}]}.
    """
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
    """Return set of allowed chat_ids. Empty set = no whitelist configured (allow all)."""
    wl = load_whitelist()
    chats = wl["allowed_chats"]
    if not chats:
        return set()  # no whitelist = allow all
    return {c["chat_id"] for c in chats}


def get_allowed_sender_ids():
    """Return set of allowed sender_ids. Empty set = all senders accepted."""
    wl = load_whitelist()
    senders = wl["allowed_senders"]
    if not senders:
        return set()  # empty = all senders accepted
    return {s["sender_id"] for s in senders}


def save_directory(chats_seen, senders_seen):
    """Save .chat_and_sender_directory.json for easy whitelist configuration.

    chats_seen: {chat_id: chat_name}
    senders_seen: {sender_id: {chat_ids: [chat_id, ...], last_seen: create_time}}
    """
    # Merge with existing directory data
    existing = {}
    if DIRECTORY_PATH.exists():
        try:
            existing = json.loads(DIRECTORY_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # Merge chats
    old_chats = {c["chat_id"]: c["name"] for c in existing.get("chats", [])}
    old_chats.update(chats_seen)
    merged_chats = [{"chat_id": cid, "name": name} for cid, name in sorted(old_chats.items(), key=lambda x: x[1])]

    # Merge senders
    old_senders = {s["sender_id"]: s for s in existing.get("senders", [])}
    for sid, info in senders_seen.items():
        if sid in old_senders:
            old_chat_ids = set(old_senders[sid].get("chat_ids", []))
            old_chat_ids.update(info["chat_ids"])
            old_senders[sid]["chat_ids"] = sorted(old_chat_ids)
            old_senders[sid]["last_seen"] = info["last_seen"]
        else:
            old_senders[sid] = {"sender_id": sid, "chat_ids": sorted(info["chat_ids"]), "last_seen": info["last_seen"]}
    merged_senders = sorted(old_senders.values(), key=lambda s: s["sender_id"])

    directory = {"chats": merged_chats, "senders": merged_senders}
    DIRECTORY_PATH.write_text(json.dumps(directory, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[directory] 已更新 {DIRECTORY_PATH.name}: {len(merged_chats)} 群, {len(merged_senders)} 用户", file=sys.stderr)


def get_bot_open_id(app_id, app_secret):
    """Get bot's open_id via Feishu API to identify bot mentions."""
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


def download_image(client, image_key, message_id=None):
    """Download an image from Feishu by image_key, save to cache, return local path.

    Tries GetMessageResource API first (more reliable), falls back to GetImage API.
    """
    from lark_oapi.api.im.v1 import GetImageRequest, GetMessageResourceRequest

    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Check cache first
    cached = IMAGE_CACHE_DIR / f"{image_key}.png"
    if cached.exists():
        return str(cached)

    # Try GetMessageResource first (requires message_id)
    if message_id:
        request = (
            GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(image_key)
            .type("image")
            .build()
        )
        response = client.im.v1.message_resource.get(request)
        if response.success() and response.file:
            cached.write_bytes(response.file.read())
            print(f"[info] Downloaded image {image_key} via resource API -> {cached}", file=sys.stderr)
            return str(cached)
        print(f"[info] Resource API failed for {image_key}: code={response.code}, trying image API", file=sys.stderr)

    # Fallback to GetImage API
    request = GetImageRequest.builder().image_key(image_key).build()
    response = client.im.v1.image.get(request)

    if response.success() and response.file:
        cached.write_bytes(response.file.read())
        print(f"[info] Downloaded image {image_key} via image API -> {cached}", file=sys.stderr)
        return str(cached)

    print(f"[warn] Failed to download image {image_key}: code={response.code}, msg={response.msg}", file=sys.stderr)
    return None


def download_file(client, file_key, file_name, message_id):
    """Download a file from Feishu by file_key via GetMessageResource API, return local path."""
    from lark_oapi.api.im.v1 import GetMessageResourceRequest

    FILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Preserve original extension
    cached = FILE_CACHE_DIR / f"{file_key}_{file_name}"
    if cached.exists():
        return str(cached)

    request = (
        GetMessageResourceRequest.builder()
        .message_id(message_id)
        .file_key(file_key)
        .type("file")
        .build()
    )
    response = client.im.v1.message_resource.get(request)
    if response.success() and response.file:
        cached.write_bytes(response.file.read())
        print(f"[info] Downloaded file {file_name} -> {cached}", file=sys.stderr)
        return str(cached)

    print(f"[warn] Failed to download file {file_name} ({file_key}): code={response.code}, msg={response.msg}", file=sys.stderr)
    return None


def load_state():
    """Load last poll timestamp to avoid duplicates."""
    state_path = FRAGO_HOME / "feishu_poll_state.json"
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_create_time": None, "last_poll_at": None}


def save_state(state):
    """Persist poll state."""
    state_path = FRAGO_HOME / "feishu_poll_state.json"
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


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


def extract_text(msg, client=None):
    """Extract content from a Feishu message object.

    Returns (body_text, placeholder_text, msg_type, attachments):
      body_text       — user-typed text only (used for 'frago' detection)
      placeholder_text — [图片: path] / [文件: path] / [类型] for non-text content
      attachments     — local cache paths for downloaded media
    """
    msg_type = msg.msg_type
    msg_id = msg.message_id
    content_str = msg.body.content if msg.body else "{}"

    try:
        content = json.loads(content_str)
    except (json.JSONDecodeError, TypeError):
        content = {"text": content_str}

    paths = []

    if msg_type == "text":
        return content.get("text", ""), "", msg_type, paths
    elif msg_type == "post":
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
                                elif elem.get("tag") == "img" and elem.get("image_key") and client:
                                    path = download_image(client, elem["image_key"], message_id=msg_id)
                                    if path:
                                        paths.append(path)
                                        ph_parts.append(f"[图片: {path}]")
        return "\n".join(text_parts), "\n".join(ph_parts), msg_type, paths
    elif msg_type == "image":
        image_key = content.get("image_key", "")
        if image_key and client:
            path = download_image(client, image_key, message_id=msg_id)
            if path:
                paths.append(path)
                return "", f"[图片: {path}]", msg_type, paths
        return "", "[图片]", msg_type, paths
    elif msg_type == "file":
        file_name = content.get("file_name", "unknown")
        file_key = content.get("file_key", "")
        if file_key and client and msg_id:
            path = download_file(client, file_key, file_name, message_id=msg_id)
            if path:
                paths.append(path)
                return "", f"[文件: {path}]", msg_type, paths
        return "", f"[文件: {file_name}]", msg_type, paths
    else:
        return "", PLACEHOLDER_MAP.get(msg_type, f"[{msg_type}]"), msg_type, paths


def fetch_message_content(client, message_id):
    """Fetch a single message by ID and extract its text content.

    Used to retrieve the original text of a quoted/replied-to message.
    Returns text string on success, None on failure.
    """
    from lark_oapi.api.im.v1 import GetMessageRequest

    try:
        request = GetMessageRequest.builder().message_id(message_id).build()
        response = client.im.v1.message.get(request)
        if not response.success() or not response.data or not response.data.items:
            print(f"[warn] Failed to fetch quoted message {message_id}: code={response.code}, msg={response.msg}", file=sys.stderr)
            return None
        msg = response.data.items[0]
        body, ph, _, _ = extract_text(msg, client=client)
        combined = "\n".join(p for p in (body, ph) if p).strip()
        return combined or None
    except Exception as e:
        print(f"[warn] Exception fetching quoted message {message_id}: {e}", file=sys.stderr)
        return None


def is_command(body_text, mentions=None, bot_open_id=None):
    """A message triggers PA only if it @-mentions the bot OR contains 'frago' in body.

    body_text MUST be the raw user-typed text WITHOUT attachment placeholders —
    placeholder paths like /home/yammi/.frago/cache/... contain 'frago' and would
    self-trigger every image/file message.
    """
    bot_mentioned = False
    if mentions and bot_open_id:
        bot_mentioned = any(m.id == bot_open_id for m in mentions)
    if bot_mentioned:
        return True
    if body_text and re.search(r"frago", body_text, re.IGNORECASE):
        return True
    return False


def strip_mention(text, mentions=None, bot_open_id=None):
    """Process @ mention placeholders in text.

    - Bot mentions: removed entirely
    - Other user mentions: replaced with @real_name
    """
    if mentions:
        for m in mentions:
            if not m.key:
                continue
            if bot_open_id and m.id == bot_open_id:
                text = text.replace(m.key, "")
            elif m.name:
                text = text.replace(m.key, f"@{m.name}")
    text = re.sub(r"@frago\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def react_to_message(client, message_id, emoji_type="OnIt"):
    """Add an emoji reaction to a message to signal processing."""
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
        request = (
            CreateMessageReactionRequest.builder()
            .message_id(message_id)
            .request_body(body)
            .build()
        )
        response = client.im.v1.message_reaction.create(request)
        if not response.success():
            print(f"[warn] Failed to react to {message_id}: {response.msg}", file=sys.stderr)
    except Exception as e:
        print(f"[warn] React failed: {e}", file=sys.stderr)


def fetch_messages(app_id, app_secret, max_results=5, context_limit=CONTEXT_LIMIT):
    """Fetch messages from all bot chats.

    Returns a list of task messages. Each task has a `context` field containing
    the preceding chat messages (up to context_limit) for situational awareness.
    Command messages get an immediate emoji reaction to signal receipt.
    """
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import ListChatRequest, ListMessageRequest

    # Get bot's open_id for accurate mention detection
    bot_open_id = None
    try:
        bot_open_id = get_bot_open_id(app_id, app_secret)
        print(f"[info] Bot open_id: {bot_open_id}", file=sys.stderr)
    except Exception as e:
        print(f"[warn] Failed to get bot open_id, mention detection degraded: {e}", file=sys.stderr)

    client = (
        lark.Client.builder()
        .app_id(app_id)
        .app_secret(app_secret)
        .domain(lark.FEISHU_DOMAIN)
        .log_level(lark.LogLevel.WARNING)
        .timeout(10)
        .build()
    )

    chat_request = ListChatRequest.builder().page_size(20).build()
    chat_response = client.im.v1.chat.list(chat_request)

    if not chat_response.success():
        print(f"[warn] Failed to list chats: {chat_response.msg}", file=sys.stderr)
        return []

    chats = chat_response.data.items or []
    print(f"[info] Bot is in {len(chats)} chat(s)", file=sys.stderr)

    # Record ALL chats for directory (before whitelist filtering)
    chats_seen = {c.chat_id: (c.name or c.chat_id) for c in chats}
    senders_seen = {}

    # Filter chats by whitelist from config.json
    allowed_chat_ids = get_allowed_chat_ids()
    allowed_sender_ids = get_allowed_sender_ids()
    if allowed_chat_ids:
        before = len(chats)
        chats = [c for c in chats if c.chat_id in allowed_chat_ids]
        skipped = before - len(chats)
        if skipped:
            print(f"[info] Skipping {skipped} chat(s) not in whitelist", file=sys.stderr)
    if allowed_sender_ids:
        print(f"[info] Sender whitelist active: {len(allowed_sender_ids)} allowed sender(s)", file=sys.stderr)

    state = load_state()
    last_create_time = state.get("last_create_time")

    all_tasks = []
    highest_create_time = last_create_time

    for chat in chats:
        chat_id = chat.chat_id
        chat_name = chat.name or chat_id

        # Fetch enough messages to build context
        # We need more than max_results to capture context around task messages
        fetch_size = min(max(max_results * 3, 20), 50)
        msg_request = (
            ListMessageRequest.builder()
            .container_id_type("chat")
            .container_id(chat_id)
            .sort_type("ByCreateTimeDesc")
            .page_size(fetch_size)
            .build()
        )
        msg_response = client.im.v1.message.list(msg_request)

        if not msg_response.success():
            print(f"[warn] Failed to list messages in {chat_name}: {msg_response.msg}", file=sys.stderr)
            continue

        items = msg_response.data.items or []

        # Parse all messages into a chronological list (oldest first)
        # Bot messages are kept for context but marked as non-command
        parsed = []
        for msg in reversed(items):
            msg_id = msg.message_id
            create_time = msg.create_time  # Unix ms timestamp, monotonically increasing
            update_time = getattr(msg, "update_time", None) or create_time
            sender = msg.sender
            is_bot = sender and sender.sender_type == "app"

            parent_id = getattr(msg, "parent_id", None) or None
            body_text, placeholder_text, msg_type, msg_images = extract_text(msg, client=client)
            combined_text = "\n".join(p for p in (body_text, placeholder_text) if p).strip()
            if not combined_text:
                continue

            # Skip system/recalled
            if msg_type == "system":
                continue
            if "This message was recalled" in body_text or "This message was recalled" in placeholder_text:
                continue

            sender_id = sender.id if sender else ""

            # Track sender for directory file
            if sender_id and not is_bot:
                if sender_id not in senders_seen:
                    senders_seen[sender_id] = {"chat_ids": set(), "last_seen": create_time}
                senders_seen[sender_id]["chat_ids"].add(chat_id)
                senders_seen[sender_id]["last_seen"] = max(senders_seen[sender_id]["last_seen"], create_time)

            # Sender whitelist: non-whitelisted senders stay in context but cannot trigger tasks
            sender_allowed = not allowed_sender_ids or is_bot or sender_id in allowed_sender_ids

            # A message is "new" if created after last poll, OR edited after last poll
            msg_is_new = not last_create_time or create_time > last_create_time
            msg_is_edited = (
                not msg_is_new
                and last_create_time
                and update_time > last_create_time
                and update_time != create_time
            )

            parsed.append({
                "msg_id": msg_id,
                "create_time": create_time,
                "update_time": update_time,
                "body_text": body_text,
                "placeholder_text": placeholder_text,
                "text": combined_text,
                "sender_id": sender_id,
                "is_bot": is_bot,
                "is_new": msg_is_new or msg_is_edited,
                "is_command": not is_bot and sender_allowed and is_command(body_text, msg.mentions, bot_open_id),
                "mentions": msg.mentions,
                "chat_id": chat_id,
                "chat_name": chat_name,
                "images": msg_images,
                "parent_id": parent_id,
            })

        # Group consecutive new command messages from same sender within MERGE_WINDOW_MS
        # into a single task, so "分析豆粕ETF" + "对比沪深300" becomes one task.
        new_commands = [(i, p) for i, p in enumerate(parsed) if p["is_new"] and p["is_command"]]

        groups = []  # list of lists of (index, parsed_msg)
        for item in new_commands:
            idx, p = item
            if (
                groups
                and groups[-1][-1][1]["sender_id"] == p["sender_id"]
                and int(p["create_time"]) - int(groups[-1][-1][1]["create_time"]) <= MERGE_WINDOW_MS
            ):
                groups[-1].append(item)
            else:
                groups.append([item])

        for group in groups:
            first_idx, first_msg = group[0]
            last_msg = group[-1][1]

            # Collect context before the first message in this group
            context_msgs = []
            start = max(0, first_idx - context_limit)
            for j in range(start, first_idx):
                ctx = parsed[j]
                ctx_text = ctx["text"][:CONTEXT_MSG_LIMIT] if CONTEXT_MSG_LIMIT else ctx["text"]
                # Replace mention placeholders with real names in context too
                ctx_text = strip_mention(ctx_text, ctx.get("mentions"), bot_open_id)
                prefix = "[bot] " if ctx["is_bot"] else ""
                context_msgs.append(f"{prefix}{ctx_text}")

            # Merge instruction texts from all messages in the group
            # For replies/quotes, fetch the original message content
            instruction_parts = []
            for _, p in group:
                clean_body = strip_mention(p.get("body_text", ""), p.get("mentions"), bot_open_id) if p.get("body_text") else ""
                ph = p.get("placeholder_text", "")
                part_text = "\n".join(s for s in (clean_body, ph) if s).strip()
                if p.get("parent_id"):
                    quoted = fetch_message_content(client, p["parent_id"])
                    if quoted:
                        part_text = f"<quoted_message>{quoted}</quoted_message>\n{part_text}"
                instruction_parts.append(part_text)
            prompt_text = "\n".join(instruction_parts)

            # Collect all attachments from messages in this group AND context
            task_images = []
            for j in range(start, first_idx):
                task_images.extend(parsed[j].get("images", []))
            for _, p in group:
                task_images.extend(p.get("images", []))

            # Use last message's id for reply (reply to the latest message)
            task = {
                "id": last_msg["msg_id"],
                "prompt": prompt_text,
                "reply_context": {
                    "chat_id": chat_id,
                    "chat_name": chat_name,
                    "message_id": last_msg["msg_id"],
                    # parent_message_id: the feishu message this message quotes/replies to.
                    # Used by frago Thread Classifier Layer 1 for native thread attribution
                    # across long time gaps (spec 20260418-thread-organization).
                    "parent_message_id": last_msg.get("parent_id"),
                    "sender_id": first_msg["sender_id"],
                },
            }

            # Add attachment paths to reply_context for downstream access
            if task_images:
                task["reply_context"]["attachments"] = task_images

            if context_msgs:
                task["prompt"] = (
                    f"<instruction>\n{prompt_text}\n</instruction>\n"
                    "<context>\n"
                    + "\n".join(f"- {m}" for m in context_msgs)
                    + "\n</context>"
                )

            all_tasks.append(task)

            # React to all messages in the group
            for _, p in group:
                react_to_message(client, p["msg_id"])
                print(f"[react] ⏳ {p['msg_id'][:16]}", file=sys.stderr)

            # Track highest time (max of create_time, update_time)
            msg_max_time = max(last_msg["create_time"], last_msg["update_time"])
            if not highest_create_time or msg_max_time > highest_create_time:
                highest_create_time = msg_max_time

        # Also track highest time from context-only messages (to advance poll state)
        for p in parsed:
            if p["is_new"]:
                p_max_time = max(p["create_time"], p["update_time"])
                if not highest_create_time or p_max_time > highest_create_time:
                    highest_create_time = p_max_time

    # Sort tasks chronologically and limit
    all_tasks.sort(key=lambda m: m["id"])
    all_tasks = all_tasks[-max_results:]

    # Update state — advance to highest seen create_time (including non-task messages)
    if highest_create_time and highest_create_time != last_create_time:
        state["last_create_time"] = highest_create_time
        state["last_poll_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_state(state)

    # Save directory file (convert sets to lists for JSON)
    dir_senders = {sid: {"chat_ids": list(info["chat_ids"]), "last_seen": info["last_seen"]}
                   for sid, info in senders_seen.items()}
    save_directory(chats_seen, dir_senders)

    return all_tasks


def main():
    if len(sys.argv) < 2:
        params = {}
    else:
        try:
            params = json.loads(sys.argv[1])
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"参数解析失败: {e}"}))
            sys.exit(1)

    # Load credentials
    print("[init] 加载飞书凭证...", file=sys.stderr)
    try:
        creds = load_credentials()
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    max_results = int(params.get("max_results", 5))

    try:
        print("[poll] 拉取飞书消息...", file=sys.stderr)
        messages = fetch_messages(
            creds["app_id"],
            creds["app_secret"],
            max_results=max_results,
        )
        print(f"[done] 获取 {len(messages)} 条任务消息", file=sys.stderr)
        print(json.dumps({
            "status": "success",
            "messages": messages,
            "count": len(messages),
        }, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
