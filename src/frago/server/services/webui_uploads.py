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


def build_prompt_with_images(text: str, image_paths: list[Path]) -> str:
    """把用户文本与已落盘图像路径拼成注入 claude 的最终 prompt。

    无图时原样返回文本。有图时在文本后附一段明确的中文指引 + 每行一个绝对路径，
    让 claude 主动用 Read 打开这些图（Read 对图像按视觉解析），而不是把路径当普通
    文字忽略。文本为空（纯发图）时给一句默认指令，避免 prompt 只有裸路径。
    """
    if not image_paths:
        return text
    lines = "\n".join(str(p) for p in image_paths)
    header = text.strip() if text.strip() else "请查看以下图片。"
    return f"{header}\n\n[附带图片，请用 Read 逐一查看]:\n{lines}"
