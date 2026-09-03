"""WebUI 图像输入落盘 + prompt 拼装。

claude-sessions 页面的 composer 支持发图（粘贴 / 拖拽 / 选文件），但 tmux 注入端
无法真正粘贴剪贴板图像（Ctrl+V / 拖拽都依赖真实剪贴板或鼠标，send-keys 只能送
键盘文本）。可行路径是「路径引用」：浏览器把图片以 base64 传上来，服务端落盘成真实
文件，再把绝对路径拼进注入 claude 的 prompt 文本——claude 的 Read 工具对 PNG/JPG
是按图像视觉解析的，于是等价于「看图」。

本模块只做两件事：把上传的 base64 图像存到磁盘（返回绝对路径），以及把用户文本与这些
路径拼成最终注入 prompt。落盘目录按 sid 分组，位于 ``~/.frago/webui_uploads/<sid>/``。
"""

from __future__ import annotations

import base64
import binascii
import re
from pathlib import Path
from uuid import uuid4

FRAGO_HOME = Path.home() / ".frago"
UPLOAD_ROOT = FRAGO_HOME / "webui_uploads"

# 单张上限 20MB（base64 解码后的字节数），单轮最多 8 张——超限即拒，避免撑爆磁盘/prompt。
_MAX_BYTES = 20 * 1024 * 1024
_MAX_COUNT = 8

# data URL 前缀：``data:image/png;base64,....``。mime 决定落盘扩展名。
_DATA_URL_RE = re.compile(r"^data:(?P<mime>image/[\w.+-]+);base64,(?P<b64>.*)$", re.DOTALL)

# 文档的 data URL：mime 不限（``application/pdf``、``text/markdown``、甚至空）。
# 扩展名不从 mime 猜，而是照抄用户原来的文件名——见 ``save_uploaded_documents``。
_ANY_DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;,]*);base64,(?P<b64>.*)$", re.DOTALL)

# mime 子类型 → 扩展名。未知子类型退回 .png（claude Read 按内容识别，扩展名只作提示）。
_MIME_EXT = {
    "png": "png",
    "jpeg": "jpg",
    "jpg": "jpg",
    "gif": "gif",
    "webp": "webp",
    "bmp": "bmp",
    "svg+xml": "svg",
}

# 只有一个非法输入时抛，路由层转 400 反馈给前端。
class ImageUploadError(ValueError):
    """一张上传图像无法解析 / 超限。"""


def _sanitize_sid(sid: str) -> str:
    """sid 作目录名——只留安全字符，杜绝 ``../`` 之类的路径穿越。"""
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", sid)
    return cleaned or "session"


def _decode_one(item: str) -> tuple[bytes, str]:
    """把一条上传项（data URL 或裸 base64）解码成 (bytes, 扩展名)。"""
    m = _DATA_URL_RE.match(item.strip())
    if m:
        subtype = m.group("mime").split("/", 1)[1].lower()
        ext = _MIME_EXT.get(subtype, "png")
        payload = m.group("b64")
    else:
        # 裸 base64（无 data 前缀）——扩展名无从得知，按 png 存。
        ext = "png"
        payload = item.strip()

    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ImageUploadError(f"invalid base64 image data: {e}") from e

    if not raw:
        raise ImageUploadError("empty image payload")
    if len(raw) > _MAX_BYTES:
        raise ImageUploadError(
            f"image too large: {len(raw)} bytes > {_MAX_BYTES} limit"
        )
    return raw, ext


def save_uploaded_images(images: list[str], sid: str) -> list[Path]:
    """把上传的 base64 图像列表落盘，返回绝对路径列表（顺序与入参一致）。

    每张独立成文件，命名 ``<uuid>.<ext>``，落在 ``~/.frago/webui_uploads/<sid>/``。
    空列表返回空列表；数量或单张体积超限抛 ``ImageUploadError``。落盘不做去重——
    同一张图两次上传就是两个文件，语义简单可预期。
    """
    if not images:
        return []
    if len(images) > _MAX_COUNT:
        raise ImageUploadError(f"too many images: {len(images)} > {_MAX_COUNT} limit")

    target_dir = UPLOAD_ROOT / _sanitize_sid(sid)
    target_dir.mkdir(parents=True, exist_ok=True)

    saved: list[Path] = []
    for item in images:
        raw, ext = _decode_one(item)
        path = target_dir / f"{uuid4().hex}.{ext}"
        path.write_bytes(raw)
        saved.append(path.resolve())
    return saved


def _safe_filename(name: str) -> str:
    """把用户那边的文件名收拾成一个能安全落盘的名字。

    只保留基名（丢掉任何目录部分），把不安全字符换成下划线，并且不许以点开头——
    ``../../etc/passwd`` 与 ``.bashrc`` 这两类都在这里被挡住。名字整个被清空时
    退回 ``file``。扩展名照抄用户的，因为 agent 是靠它判断该怎么读这个文件的：
    ``.md`` 当文本读、``.pdf`` 走解析、``.csv`` 可能直接上表格工具。
    """
    base = Path(name.strip()).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")
    return cleaned or "file"


def save_uploaded_documents(documents: list[dict], sid: str) -> list[Path]:
    """把上传的文档落盘，返回绝对路径列表（顺序与入参一致）。

    与图片同一条路：浏览器读不到本机文件的真实路径（那是浏览器的安全边界，拖拽也拿
    不到），所以内容以 base64 传上来，由服务端落盘成真实文件，再把**服务端这一侧的
    绝对路径**拼进提示词。agent 拿到的是一条它真的打得开的路径，而不是一个它够不着的
    本机路径。

    每条入参形如 ``{"name": "spec.md", "data": "data:text/markdown;base64,..."}``。
    落盘命名 ``<uuid>-<原文件名>``：前缀保证同名文件不互相覆盖，后缀保留原名，
    这样 agent 在提示词里看到的路径仍然是有意义的，而不是一串十六进制。
    """
    if not documents:
        return []
    if len(documents) > _MAX_COUNT:
        raise ImageUploadError(f"too many documents: {len(documents)} > {_MAX_COUNT} limit")

    target_dir = UPLOAD_ROOT / _sanitize_sid(sid)
    target_dir.mkdir(parents=True, exist_ok=True)

    saved: list[Path] = []
    for item in documents:
        raw_data = str(item.get("data", "")).strip()
        m = _ANY_DATA_URL_RE.match(raw_data)
        payload = m.group("b64") if m else raw_data
        try:
            blob = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as e:
            raise ImageUploadError(f"invalid base64 document data: {e}") from e
        if not blob:
            raise ImageUploadError("empty document payload")
        if len(blob) > _MAX_BYTES:
            raise ImageUploadError(
                f"document too large: {len(blob)} bytes > {_MAX_BYTES} limit"
            )
        path = target_dir / f"{uuid4().hex}-{_safe_filename(str(item.get('name', '')))}"
        path.write_bytes(blob)
        saved.append(path.resolve())
    return saved


def build_prompt_with_attachments(
    text: str, image_paths: list[Path], doc_paths: list[Path] | None = None
) -> str:
    """把用户文本、已落盘图片与已落盘文档拼成投给 agent 的最终 prompt。

    图片与文档分两段写，因为要 agent 做的事不一样：图片是"打开看"，文档是"打开读"。
    合成一段的话，agent 常常只处理头一类就往下走了。

    两段都 NEVER 点名某个具体工具——同一条通道现在驱动 Claude Code、opencode 与
    codex，它们的读文件工具各叫各的名字，点名一个别家没有的工具只会让那一家先愣一下。
    """
    docs = doc_paths or []
    if not image_paths and not docs:
        return text

    parts = [text.strip() or "请查看以下附件。"]
    if image_paths:
        lines = "\n".join(str(p) for p in image_paths)
        parts.append(f"[附带图片，请用读文件的工具逐一打开查看]:\n{lines}")
    if docs:
        lines = "\n".join(str(p) for p in docs)
        parts.append(f"[附带文档，请用读文件的工具逐一打开阅读]:\n{lines}")
    return "\n\n".join(parts)


def build_prompt_with_images(text: str, image_paths: list[Path]) -> str:
    """把用户文本与已落盘图像路径拼成投给 agent 的最终 prompt。

    无图时原样返回文本。有图时在文本后附一段明确的中文指引 + 每行一个绝对路径，
    让 agent 主动打开这些图（各家的读文件工具对 PNG/JPG 都按图像解析），而不是把
    路径当普通文字忽略。文本为空（纯发图）时给一句默认指令，避免 prompt 只有裸路径。

    指引里 NEVER 点名某个工具（从前写的是 claude 的 ``Read``）：同一条通道现在还驱动
    opencode 与 codex，它们的读文件工具各叫各的名字，点名一个别家没有的工具只会让
    那一家先愣一下再自己找替代。说清"打开看图"这件事即可，用哪个工具是 agent 的事。
    """
    if not image_paths:
        return text
    lines = "\n".join(str(p) for p in image_paths)
    header = text.strip() if text.strip() else "请查看以下图片。"
    return f"{header}\n\n[附带图片，请用读文件的工具逐一打开查看]:\n{lines}"
