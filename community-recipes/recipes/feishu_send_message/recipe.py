# /// script
# requires-python = ">=3.9"
# dependencies = ["lark-oapi"]
# ///
"""Feishu bot message sender for frago ingestion.

Sends messages to Feishu chats via Open API.
Credentials are injected via FRAGO_SECRETS env var by the recipe runner,
configured in ~/.frago/recipes.local.json or Web UI.
"""
import json
import os
import sys
from pathlib import Path

# Feishu API is domestic, bypass any proxy
for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(k, None)


def load_credentials():
    """Load app_id and app_secret from FRAGO_SECRETS (injected by recipe runner)."""
    secrets = json.loads(os.environ.get("FRAGO_SECRETS", "{}"))
    app_id = secrets.get("app_id", "")
    app_secret = secrets.get("app_secret", "")
    if app_id and app_secret:
        return {"app_id": app_id, "app_secret": app_secret}

    raise ValueError(
        "飞书凭证未找到。请在 recipes.local.json 或 Web UI 中配置 feishu_send_message 的 app_id/app_secret"
    )


def _build_client(app_id, app_secret):
    """Build a Feishu API client."""
    import lark_oapi as lark

    return (
        lark.Client.builder()
        .app_id(app_id)
        .app_secret(app_secret)
        .domain(lark.FEISHU_DOMAIN)
        .log_level(lark.LogLevel.WARNING)
        .build()
    )


def upload_image(app_id, app_secret, image_path):
    """Upload an image to Feishu and return the image_key."""
    from lark_oapi.api.im.v1 import (
        CreateImageRequest,
        CreateImageRequestBody,
    )

    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"图片文件不存在: {image_path}")

    client = _build_client(app_id, app_secret)

    with open(path, "rb") as f:
        body = (
            CreateImageRequestBody.builder()
            .image_type("message")
            .image(f)
            .build()
        )

        request = (
            CreateImageRequest.builder()
            .request_body(body)
            .build()
        )

        response = client.im.v1.image.create(request)

    if not response.success():
        raise RuntimeError(
            f"Failed to upload image: code={response.code}, msg={response.msg}"
        )

    return response.data.image_key


def send_message(app_id, app_secret, chat_id, text, reply_message_id=None):
    """Send a text message to a Feishu chat."""
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
    )

    client = _build_client(app_id, app_secret)

    content = json.dumps({"text": text})

    body = (
        CreateMessageRequestBody.builder()
        .receive_id(chat_id)
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

    if not response.success():
        raise RuntimeError(
            f"Failed to send message: code={response.code}, msg={response.msg}"
        )

    return response.data.message_id if response.data else None


def recall_message(app_id, app_secret, message_id):
    """Recall (delete) a message by message_id."""
    from lark_oapi.api.im.v1 import DeleteMessageRequest

    client = _build_client(app_id, app_secret)

    request = (
        DeleteMessageRequest.builder()
        .message_id(message_id)
        .build()
    )

    response = client.im.v1.message.delete(request)

    if not response.success():
        raise RuntimeError(
            f"Failed to recall message: code={response.code}, msg={response.msg}"
        )

    return True


def upload_file(app_id, app_secret, file_path):
    """Upload a file to Feishu and return the file_key."""
    from lark_oapi.api.im.v1 import (
        CreateFileRequest,
        CreateFileRequestBody,
    )

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    suffix = path.suffix.lower()
    type_map = {
        ".opus": "opus", ".mp4": "mp4", ".pdf": "pdf",
        ".doc": "doc", ".xls": "xls", ".ppt": "ppt",
        ".docx": "doc", ".xlsx": "xls", ".pptx": "ppt",
    }
    file_type = type_map.get(suffix, "stream")

    client = _build_client(app_id, app_secret)

    with open(path, "rb") as f:
        body = (
            CreateFileRequestBody.builder()
            .file_type(file_type)
            .file_name(path.name)
            .file(f)
            .build()
        )

        request = (
            CreateFileRequest.builder()
            .request_body(body)
            .build()
        )

        response = client.im.v1.file.create(request)

    if not response.success():
        raise RuntimeError(
            f"Failed to upload file: code={response.code}, msg={response.msg}"
        )

    return response.data.file_key


def send_file_message(app_id, app_secret, chat_id, file_key):
    """Send a file message to a Feishu chat."""
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
    )

    client = _build_client(app_id, app_secret)

    content = json.dumps({"file_key": file_key})

    body = (
        CreateMessageRequestBody.builder()
        .receive_id(chat_id)
        .msg_type("file")
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

    if not response.success():
        raise RuntimeError(
            f"Failed to send file message: code={response.code}, msg={response.msg}"
        )

    return response.data.message_id if response.data else None


def send_image_message(app_id, app_secret, chat_id, image_key):
    """Send an image message to a Feishu chat."""
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
    )

    client = _build_client(app_id, app_secret)

    content = json.dumps({"image_key": image_key})

    body = (
        CreateMessageRequestBody.builder()
        .receive_id(chat_id)
        .msg_type("image")
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

    if not response.success():
        raise RuntimeError(
            f"Failed to send image message: code={response.code}, msg={response.msg}"
        )

    return response.data.message_id if response.data else None


def main():
    if len(sys.argv) < 2:
        params = {}
    else:
        try:
            params = json.loads(sys.argv[1])
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"参数解析失败: {e}"}))
            sys.exit(1)

    # Action: recall (delete) a message
    action = params.get("action", "send")
    if action == "recall":
        message_id = params.get("message_id")
        if not message_id:
            print(json.dumps({"error": "缺少必需参数: message_id"}))
            sys.exit(1)

        print("[init] 加载飞书凭证...", file=sys.stderr)
        try:
            creds = load_credentials()
        except (FileNotFoundError, ValueError) as e:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)

        try:
            print(f"[recall] 撤回消息 {message_id}...", file=sys.stderr)
            recall_message(creds["app_id"], creds["app_secret"], message_id)
            print(f"[done] ✓ 消息已撤回", file=sys.stderr)
            print(json.dumps({
                "status": "success",
                "action": "recall",
                "message_id": message_id,
            }, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)
        return

    # Support both direct params and ingestion notify contract
    reply_context = params.get("reply_context", {})
    chat_id = params.get("chat_id") or reply_context.get("chat_id")
    image_path = params.get("image_path")
    file_path = params.get("file_path")

    # Determine message mode: file > image > text
    if file_path:
        mode = "file"
    elif image_path:
        mode = "image"
    else:
        mode = "text"

    if mode == "text":
        # Build message text from ingestion contract or direct param
        # Priority: text (natural reply) > status+result_summary (template fallback)
        if params.get("text"):
            text = params["text"]
        elif "status" in params and "reply_context" in params:
            result_summary = params.get("result_summary")
            error = params.get("error")
            if result_summary:
                text = result_summary
            elif error:
                text = f"执行失败：{error}"
            else:
                text = f"任务已{params.get('status', '完成')}"
        else:
            text = params.get("text")

        if not chat_id or not text:
            print(json.dumps({"error": "缺少必需参数: chat_id, text（或使用 image_path/file_path 发送附件）"}))
            sys.exit(1)
    else:
        if not chat_id:
            print(json.dumps({"error": "缺少必需参数: chat_id"}))
            sys.exit(1)

    reply_message_id = reply_context.get("message_id")

    print("[init] 加载飞书凭证...", file=sys.stderr)
    try:
        creds = load_credentials()
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    try:
        if mode == "file":
            print(f"[upload] 上传文件 {file_path}...", file=sys.stderr)
            file_key = upload_file(creds["app_id"], creds["app_secret"], file_path)
            print(f"[upload] ✓ file_key={file_key}", file=sys.stderr)

            print(f"[send] 发送文件消息到 {chat_id}...", file=sys.stderr)
            message_id = send_file_message(
                creds["app_id"], creds["app_secret"], chat_id, file_key
            )
            print(f"[done] ✓ 文件消息已发送", file=sys.stderr)
            print(json.dumps({
                "status": "success",
                "chat_id": chat_id,
                "message_id": message_id,
                "file_key": file_key,
            }, ensure_ascii=False))
        elif mode == "image":
            print(f"[upload] 上传图片 {image_path}...", file=sys.stderr)
            image_key = upload_image(creds["app_id"], creds["app_secret"], image_path)
            print(f"[upload] ✓ image_key={image_key}", file=sys.stderr)

            print(f"[send] 发送图片消息到 {chat_id}...", file=sys.stderr)
            message_id = send_image_message(
                creds["app_id"], creds["app_secret"], chat_id, image_key
            )
            print(f"[done] ✓ 图片消息已发送", file=sys.stderr)
            print(json.dumps({
                "status": "success",
                "chat_id": chat_id,
                "message_id": message_id,
                "image_key": image_key,
            }, ensure_ascii=False))
        else:
            print(f"[send] 发送消息到 {chat_id}...", file=sys.stderr)
            message_id = send_message(
                creds["app_id"],
                creds["app_secret"],
                chat_id,
                text,
                reply_message_id=reply_message_id,
            )
            print(f"[done] ✓ 消息已发送", file=sys.stderr)
            print(json.dumps({
                "status": "success",
                "chat_id": chat_id,
                "message_id": message_id,
            }, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
