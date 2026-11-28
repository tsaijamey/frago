"""Digital employee DiceBear Micah avatar specification, secure raster upload, and fallback resolution.

Ontological contract:
- Avatar configuration is an anti-rigid (`~R`) visual appearance attribute stored directly on
  `EmployeePostRecord` (`~/.frago/employees/<member_post_id>.json`). Zero sidecar state files.
- Uploaded raster binaries (PNG / JPEG / WebP ONLY) live in `<employees_dir>/_avatars/`
  (automatically honoring `FRAGO_EMPLOYEES_DIR` and `FRAGO_HOME` with zero prior configuration).
  Because post enumeration scans `<employees_dir>/*.json`, `_avatars/` never collides with posts.
- Missing, deleted, unreadable, or corrupted upload files degrade cleanly to the deterministic
  default Micah avatar without raising HTTP 500 or leaving broken image states.

Layer: lower domain store helper — NEVER imports ``frago.server`` or ``frago.cli``.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Canonical 8-color low-saturation architectural neutral backdrop palette (1:1 with WebUI prototype).
AVATAR_BG_PALETTE: tuple[dict[str, str], ...] = (
    {"id": "mist-blue", "label": "雾蓝", "hex": "#e8edf3"},
    {"id": "sage", "label": "鼠尾草", "hex": "#e6efe9"},
    {"id": "oat", "label": "燕麦米", "hex": "#f3ece4"},
    {"id": "lilac", "label": "淡丁香", "hex": "#ece8f5"},
    {"id": "dust-rose", "label": "烟灰粉", "hex": "#f5e8eb"},
    {"id": "glacier", "label": "冰川青", "hex": "#e5eef2"},
    {"id": "warm-sand", "label": "暖砂", "hex": "#efeae1"},
    {"id": "mineral", "label": "矿石灰", "hex": "#e8ebf0"},
)

_PALETTE_BY_ID: dict[str, dict[str, str]] = {p["id"]: p for p in AVATAR_BG_PALETTE}
_PALETTE_BY_HEX: dict[str, dict[str, str]] = {
    p["hex"].lower(): p for p in AVATAR_BG_PALETTE
}

VALID_AVATAR_KINDS: tuple[str, ...] = ("default", "micah", "upload")

ALLOWED_RASTER_MIME_TYPES: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}

ALLOWED_RASTER_EXTENSIONS: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

# Explicit blocklist for scriptable / vector / markup formats.
FORBIDDEN_MIME_SUBSTRINGS: tuple[str, ...] = (
    "svg",
    "html",
    "xml",
    "javascript",
    "ecmascript",
    "script",
)

FORBIDDEN_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".svg",
        ".svgz",
        ".html",
        ".htm",
        ".xhtml",
        ".xml",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".css",
        ".php",
        ".py",
        ".sh",
        ".bat",
        ".exe",
        ".ico",
        ".gif",
    }
)

MAX_AVATAR_UPLOAD_BYTES: int = 2 * 1024 * 1024  # 2 MiB
MAX_AVATAR_SEED_LENGTH: int = 120

_HEX_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
_SAFE_AVATAR_FILENAME_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9_-]{0,62}-[0-9a-f]{8,64}\.(png|jpg|webp)$"
)
_AVATARS_SUBDIR_NAME = "_avatars"


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def stable_avatar_hash(text: str) -> int:
    """Deterministic 32-bit hash identical to the frontend implementation."""
    h = 0
    for ch in text:
        h = ((h * 31) + ord(ch)) & 0xFFFFFFFF
    return h


def default_avatar_palette(member_post_id: str) -> dict[str, str]:
    """Return the deterministic architectural palette entry for ``member_post_id``."""
    seed = str(member_post_id or "").strip() or "frago-employee"
    idx = stable_avatar_hash(seed) % len(AVATAR_BG_PALETTE)
    return dict(AVATAR_BG_PALETTE[idx])


def default_avatar_spec(member_post_id: str) -> dict[str, Any]:
    """Build the default deterministic Micah avatar configuration for a post."""
    seed = str(member_post_id or "").strip() or "frago-employee"
    palette = default_avatar_palette(seed)
    return {
        "kind": "default",
        "seed": seed,
        "bg_color": palette["hex"],
        "palette_id": palette["id"],
        "file_name": None,
        "mime_type": None,
        "updated_at": "",
    }


def _resolve_bg_color_and_palette(
    bg_color: Any,
    palette_id: Any,
    fallback_palette: Mapping[str, str],
) -> tuple[str, str]:
    clean_pid = str(palette_id or "").strip().lower()
    clean_hex = str(bg_color or "").strip().lower()
    if clean_hex and _HEX_COLOR_PATTERN.match(clean_hex):
        matched = _PALETTE_BY_HEX.get(clean_hex)
        if matched is not None:
            return matched["hex"], matched["id"]
        return clean_hex, clean_pid or "custom"
    if clean_pid and clean_pid in _PALETTE_BY_ID:
        pal = _PALETTE_BY_ID[clean_pid]
        return pal["hex"], pal["id"]
    return str(fallback_palette["hex"]), str(fallback_palette["id"])


def is_safe_avatar_filename(file_name: Any) -> bool:
    """Check that ``file_name`` is a single generated raster filename without traversal."""
    if not isinstance(file_name, str):
        return False
    if "/" in file_name or "\\" in file_name or "\x00" in file_name or ".." in file_name:
        return False
    return bool(_SAFE_AVATAR_FILENAME_PATTERN.match(file_name))


def normalize_avatar_spec(
    raw: Any,
    member_post_id: str,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Normalize persisted or incoming avatar metadata into the canonical ontology dict."""
    default_spec = default_avatar_spec(member_post_id)
    if not raw:
        return default_spec
    if not isinstance(raw, Mapping):
        if strict:
            raise ValueError("Avatar specification must be a JSON object.")
        return default_spec

    kind = str(raw.get("kind", "default") or "default").strip().lower()
    if kind not in VALID_AVATAR_KINDS:
        if strict:
            raise ValueError(
                f"Invalid avatar kind '{kind}'; must be one of {VALID_AVATAR_KINDS}."
            )
        return default_spec

    fallback_pal = default_avatar_palette(member_post_id)
    raw_bg = raw.get("bg_color")
    if strict and raw_bg not in (None, "") and not _HEX_COLOR_PATTERN.match(str(raw_bg).strip()):
        raise ValueError(f"Invalid avatar bg_color '{raw_bg}'; expected #RRGGBB.")
    bg_color, palette_id = _resolve_bg_color_and_palette(
        raw_bg,
        raw.get("palette_id"),
        fallback_pal,
    )
    updated_at = str(raw.get("updated_at", "") or "").strip()

    if kind == "default":
        return {
            **default_spec,
            "updated_at": updated_at,
        }

    if kind == "micah":
        raw_seed = str(raw.get("seed", "") or "").strip()
        if not raw_seed:
            if strict:
                raise ValueError("Built-in Micah avatar requires a non-empty 'seed'.")
            raw_seed = default_spec["seed"]
        if len(raw_seed) > MAX_AVATAR_SEED_LENGTH:
            if strict:
                raise ValueError(
                    f"Avatar seed exceeds maximum length ({MAX_AVATAR_SEED_LENGTH})."
                )
            raw_seed = raw_seed[:MAX_AVATAR_SEED_LENGTH]
        if any(ord(ch) < 32 for ch in raw_seed):
            if strict:
                raise ValueError("Avatar seed must not contain control characters.")
            raw_seed = "".join(ch for ch in raw_seed if ord(ch) >= 32).strip() or default_spec["seed"]
        return {
            "kind": "micah",
            "seed": raw_seed,
            "bg_color": bg_color,
            "palette_id": palette_id,
            "file_name": None,
            "mime_type": None,
            "updated_at": updated_at,
        }

    # kind == "upload"
    file_name = raw.get("file_name")
    mime_type = str(raw.get("mime_type", "") or "").strip().lower() or None
    if not is_safe_avatar_filename(file_name):
        if strict:
            raise ValueError(
                "Uploaded avatar requires a safe generated 'file_name' (png/jpg/webp)."
            )
        return default_spec
    if mime_type is not None and mime_type not in ALLOWED_RASTER_MIME_TYPES:
        if strict:
            raise ValueError(
                f"Invalid uploaded avatar mime_type '{mime_type}'; allowed: {sorted(ALLOWED_RASTER_MIME_TYPES)}."
            )
        mime_type = ALLOWED_RASTER_EXTENSIONS.get(Path(str(file_name)).suffix.lower())
    return {
        "kind": "upload",
        "seed": default_spec["seed"],
        "bg_color": bg_color,
        "palette_id": palette_id,
        "file_name": str(file_name),
        "mime_type": mime_type,
        "updated_at": updated_at,
    }


def detect_raster_format(data: bytes) -> tuple[str, str] | None:
    """Inspect magic bytes and return ``(mime_type, ext)`` strictly for PNG / JPEG / WebP."""
    if not data:
        return None
    # Reject markup / script payloads early (including BOM/whitespace-prefixed SVG or HTML).
    head_probe = data[:256].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if head_probe.startswith((b"<svg", b"<?xml", b"<html", b"<!doctype", b"<script")):
        return None

    # PNG: 8-byte signature + minimum IHDR chunk header
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        return ("image/png", "png")
    # JPEG: SOI + marker prefix
    if len(data) >= 12 and data.startswith(b"\xff\xd8\xff"):
        return ("image/jpeg", "jpg")
    # WebP: RIFF....WEBP
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ("image/webp", "webp")
    return None


def validate_avatar_upload(
    data: bytes,
    *,
    content_type: str | None = None,
    filename: str | None = None,
) -> tuple[str, str]:
    """Validate uploaded avatar bytes strictly by size, MIME, extension, and magic bytes.

    Returns ``(detected_mime, canonical_ext)`` or raises ``ValueError``.
    """
    if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
        raise ValueError("上传的头像文件为空，请选择有效的 PNG、JPEG 或 WebP 图片。")
    raw_bytes = bytes(data)
    if len(raw_bytes) > MAX_AVATAR_UPLOAD_BYTES:
        raise ValueError("上传的头像图片超过 2 MB 上限，请压缩后重试。")

    if content_type:
        normalized_ct = content_type.split(";", 1)[0].strip().lower()
        if normalized_ct == "image/jpg":
            normalized_ct = "image/jpeg"
        if any(bad in normalized_ct for bad in FORBIDDEN_MIME_SUBSTRINGS):
            raise ValueError(
                f"禁止上传 '{normalized_ct}' 类型文件，仅支持 PNG、JPEG、WebP 栅格图片。"
            )
        if normalized_ct and normalized_ct != "application/octet-stream" and normalized_ct not in ALLOWED_RASTER_MIME_TYPES:
            raise ValueError(
                f"不支持的图片 MIME 类型 '{normalized_ct}'，仅支持 PNG、JPEG、WebP。"
            )
    else:
        normalized_ct = ""

    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix in FORBIDDEN_EXTENSIONS:
            raise ValueError(
                f"禁止上传 '{suffix}' 格式文件，仅支持 PNG、JPEG、WebP 栅格图片。"
            )
        if suffix and suffix not in ALLOWED_RASTER_EXTENSIONS:
            raise ValueError(
                f"不支持的文件扩展名 '{suffix}'，仅支持 .png、.jpg、.jpeg、.webp。"
            )

    detected = detect_raster_format(raw_bytes)
    if detected is None:
        raise ValueError(
            "文件内容校验失败（非有效 PNG / JPEG / WebP 图片或已损坏），禁止 SVG 与脚本文件。"
        )

    detected_mime, canonical_ext = detected
    if normalized_ct and normalized_ct != "application/octet-stream" and normalized_ct != detected_mime:
        raise ValueError(
            f"声明类型 '{normalized_ct}' 与文件真实格式 '{detected_mime}' 不一致，已拦截。"
        )
    return detected_mime, canonical_ext


def avatars_dir(employees_base_dir: Path) -> Path:
    """Resolve the managed avatar binary directory under ``<employees_dir>/_avatars``."""
    return employees_base_dir / _AVATARS_SUBDIR_NAME


def resolve_avatar_file_path(
    file_name: str | None,
    *,
    employees_base_dir: Path,
) -> Path | None:
    """Resolve ``file_name`` inside ``<employees_dir>/_avatars``, blocking path traversal."""
    if not is_safe_avatar_filename(file_name):
        return None
    base = avatars_dir(employees_base_dir).resolve()
    candidate = (base / str(file_name)).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate


def save_uploaded_avatar_file(
    member_post_id: str,
    data: bytes,
    *,
    employees_base_dir: Path,
    content_type: str | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    """Validate and atomically store an uploaded raster avatar, returning its ontology spec."""
    detected_mime, ext = validate_avatar_upload(
        data,
        content_type=content_type,
        filename=filename,
    )
    safe_post = re.sub(r"[^a-z0-9_-]", "-", str(member_post_id).strip().lower()).strip("-_") or "emp"
    digest = hashlib.sha256(data).hexdigest()[:16]
    generated_name = f"{safe_post}-{digest}.{ext}"

    target_dir = avatars_dir(employees_base_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = resolve_avatar_file_path(generated_name, employees_base_dir=employees_base_dir)
    if target_path is None:
        raise ValueError("Failed to generate safe avatar storage path.")

    fd, tmp_name = tempfile.mkstemp(prefix=".avatar-", suffix=".tmp", dir=str(target_dir))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    default_pal = default_avatar_palette(member_post_id)
    return {
        "kind": "upload",
        "seed": str(member_post_id).strip(),
        "bg_color": default_pal["hex"],
        "palette_id": default_pal["id"],
        "file_name": generated_name,
        "mime_type": detected_mime,
        "updated_at": _now_iso(),
    }


def cleanup_avatar_file(
    file_name: str | None,
    *,
    employees_base_dir: Path,
    referenced_file_names: set[str] | None = None,
) -> bool:
    """Delete an obsolete uploaded avatar file unless another post still references it."""
    if not file_name or not is_safe_avatar_filename(file_name):
        return False
    if referenced_file_names and file_name in referenced_file_names:
        return False
    target_path = resolve_avatar_file_path(file_name, employees_base_dir=employees_base_dir)
    if target_path is None or not target_path.is_file():
        return False
    try:
        target_path.unlink()
        return True
    except OSError:
        return False


def read_valid_avatar_file(
    avatar_spec: Mapping[str, Any] | None,
    *,
    employees_base_dir: Path,
) -> tuple[bytes, str, str] | None:
    """Read and integrity-check the uploaded avatar file; return ``(bytes, mime, etag)`` or ``None``."""
    if not isinstance(avatar_spec, Mapping) or avatar_spec.get("kind") != "upload":
        return None
    file_name = avatar_spec.get("file_name")
    target_path = resolve_avatar_file_path(
        file_name if isinstance(file_name, str) else None,
        employees_base_dir=employees_base_dir,
    )
    if target_path is None or not target_path.is_file():
        return None
    try:
        size = target_path.stat().st_size
        if size <= 0 or size > MAX_AVATAR_UPLOAD_BYTES:
            return None
        data = target_path.read_bytes()
    except OSError:
        return None
    detected = detect_raster_format(data)
    if detected is None:
        return None
    mime_type, _ = detected
    etag = hashlib.sha256(data).hexdigest()[:16]
    return data, mime_type, etag


def resolve_avatar_state(
    member_post_id: str,
    avatar_spec: Mapping[str, Any] | None,
    *,
    employees_base_dir: Path,
) -> dict[str, Any]:
    """Resolve renderable avatar presentation state with automatic fallback for missing/corrupted uploads."""
    normalized = normalize_avatar_spec(avatar_spec, member_post_id)
    default_spec = default_avatar_spec(member_post_id)
    kind = normalized["kind"]

    if kind == "upload":
        file_name = normalized.get("file_name")
        target_path = resolve_avatar_file_path(
            file_name if isinstance(file_name, str) else None,
            employees_base_dir=employees_base_dir,
        )
        fallback_reason: str | None = None
        if target_path is None or not target_path.is_file():
            fallback_reason = "missing"
        else:
            try:
                size = target_path.stat().st_size
                if size <= 0 or size > MAX_AVATAR_UPLOAD_BYTES:
                    fallback_reason = "corrupted"
                else:
                    data = target_path.read_bytes()
                    if detect_raster_format(data) is None:
                        fallback_reason = "corrupted"
            except OSError:
                fallback_reason = "unreadable"

        if fallback_reason is None:
            cache_ver = normalized.get("updated_at") or Path(str(file_name)).stem
            return {
                "kind": "upload",
                "effective_kind": "upload",
                "seed": default_spec["seed"],
                "bg_color": normalized["bg_color"],
                "palette_id": normalized["palette_id"],
                "mime_type": normalized.get("mime_type"),
                "upload_url": f"/api/employees/{member_post_id}/avatar/file?v={cache_ver}",
                "fallback_reason": None,
                "updated_at": normalized.get("updated_at", ""),
            }

        return {
            "kind": "upload",
            "effective_kind": "default",
            "seed": default_spec["seed"],
            "bg_color": default_spec["bg_color"],
            "palette_id": default_spec["palette_id"],
            "mime_type": None,
            "upload_url": None,
            "fallback_reason": fallback_reason,
            "updated_at": normalized.get("updated_at", ""),
        }

    if kind == "micah":
        return {
            "kind": "micah",
            "effective_kind": "micah",
            "seed": normalized["seed"],
            "bg_color": normalized["bg_color"],
            "palette_id": normalized["palette_id"],
            "mime_type": None,
            "upload_url": None,
            "fallback_reason": None,
            "updated_at": normalized.get("updated_at", ""),
        }

    return {
        "kind": "default",
        "effective_kind": "default",
        "seed": default_spec["seed"],
        "bg_color": default_spec["bg_color"],
        "palette_id": default_spec["palette_id"],
        "mime_type": None,
        "upload_url": None,
        "fallback_reason": None,
        "updated_at": normalized.get("updated_at", ""),
    }
