"""会话可调用的前端图片网格组件生成工具（``frago app image``）。

参考 ``frago app ask`` 交互组件的确定性调用方式，让 agent 将本机图片路径或互联网图片 URL
作为参数填入，经 CLI 严格校验后输出带 ``frago_ui_component: "image-grid"`` 标识的结构化
JSON 数据包，由会话工作台渲染出自适应屏幕宽度的图片网格（Image Grid），并支持点击任意
图片弹出放大预览浮窗（Lightbox）。

核心特性：
1. **同时支持本机与互联网图片**：
   - 本机图片（绝对路径、``~/...``、相对路径、``file://...``）当场校验文件存在性，并自动转为
     同源内联地址 ``/api/file?disposition=inline&path=<编码后绝对路径>``；
   - 互联网图片（``http://...`` / ``https://...``）当场校验 URL 合法性并保留原地址。
2. **参数错当场拦下并给 ``[Fix]`` 正确示例**：
   - 未传图片、本机文件不存在、目录误传为文件、URL 格式残缺、或传了未知选项时，直接返回
     非零退出码并输出正确调用示例，杜绝坏链接流入前端。
3. **灵活传参**：支持位置参数直接罗列、``-i / --image "PATH_OR_URL|CAPTION"`` 管道简写、
   或 JSON 对象字符串。
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path
from typing import Any

import click
from click import Context

from .agent_friendly import BusinessError

UI_IMAGE_GRID_MARKER = "image-grid"

IMAGE_GRID_EXAMPLES: list[str] = [
    (
        "frago app image "
        "--title \"宣传海报定稿（2 张）\" "
        "-i \"/Users/frago/.frago/data/promo/poster-1.png|图 1：主视觉海报\" "
        "-i \"https://example.com/assets/poster-2.png|图 2：线上横幅参考\""
    ),
    (
        "frago app image "
        "/Users/frago/.frago/data/promo/shot-1.png "
        "/Users/frago/.frago/data/promo/shot-2.png "
        "https://example.com/demo.png"
    ),
]


def _raise_image_error(message: str) -> None:
    """抛出附带 ``frago app image`` 标准调用示例的 BusinessError。"""
    raise BusinessError(message, *IMAGE_GRID_EXAMPLES)


class ImageCommand(click.Command):
    """会话图片网格命令：将所有 Click 解析期异常转为只含 ``frago app image`` 用例的 Friendly Feedback。"""

    def make_context(
        self,
        info_name: str | None,
        args: list[str],
        parent: Context | None = None,
        **extra: Any,
    ) -> Context:
        try:
            return super().make_context(info_name, args, parent, **extra)
        except click.NoSuchOption as e:
            _raise_image_error(
                f"image 组件不存在参数 '{e.option_name}'。"
                f"请用位置参数或 -i / --image \"地址|说明\" 传入图片，标题用 -t / --title，列数用 --columns。"
            )
        except (click.MissingParameter, click.BadParameter, click.UsageError) as e:
            _raise_image_error(f"image 组件参数错误：{e.format_message()}")
        raise AssertionError("unreachable")


def _extract_remote_name(parsed: urllib.parse.SplitResult) -> str:
    """从远程 URL 提取可读文件名。"""
    tail = urllib.parse.unquote(parsed.path.rstrip("/").split("/")[-1]).strip()
    if tail:
        return tail
    return parsed.netloc or "remote-image"


def _resolve_image_source(raw_target: str, index: int) -> dict[str, str]:
    """校验单张图片地址（本机路径或互联网 URL）并生成前端可直接渲染的数据结构。"""
    target = (raw_target or "").strip()
    if not target:
        _raise_image_error(
            f"第 {index} 张图片地址为空。请传入本机图片绝对路径或 http(s):// 互联网图片地址。"
        )

    # 1. 互联网图片 URL（http:// 或 https://）
    if target.startswith(("http://", "https://")):
        parsed = urllib.parse.urlsplit(target)
        if not parsed.netloc or any(ch.isspace() for ch in target):
            _raise_image_error(
                f"第 {index} 张图片的互联网地址格式无效（收到 {raw_target!r}）。"
                f"必须为完整的 http:// 或 https:// URL。"
            )
        return {
            "src": target,
            "raw": target,
            "name": _extract_remote_name(parsed),
            "source": "remote",
        }

    # 2. 已是服务端内联接口或上传附件地址
    if target.startswith("/api/workbench/uploads/"):
        name = urllib.parse.unquote(target.rstrip("/").split("/")[-1]) or "upload-image"
        return {
            "src": target,
            "raw": target,
            "name": name,
            "source": "local",
        }

    if target.startswith("/api/file"):
        parsed = urllib.parse.urlsplit(target)
        qs = urllib.parse.parse_qs(parsed.query)
        path_vals = qs.get("path") or []
        if not path_vals or not path_vals[0].strip():
            _raise_image_error(
                f"第 {index} 张图片的 /api/file 地址缺少 path 参数（收到 {raw_target!r}）。"
                f"请直接传入本机绝对路径，工具会自动生成内联地址。"
            )
        target = path_vals[0].strip()

    # 3. file:// 协议地址转本机路径
    if target.startswith("file://"):
        parsed = urllib.parse.urlsplit(target)
        local_raw = urllib.parse.unquote(parsed.path or "")
        if parsed.netloc and parsed.netloc != "localhost":
            local_raw = f"//{parsed.netloc}{local_raw}"
        if not local_raw:
            _raise_image_error(
                f"第 {index} 张图片的 file:// 地址无效（收到 {raw_target!r}）。"
                f"请直接传入本机绝对路径（如 /Users/.../image.png）。"
            )
        target = local_raw

    # 4. 其它未知协议（如 ftp://、data: 等）拦截提示
    if "://" in target and not target.startswith("/"):
        _raise_image_error(
            f"第 {index} 张图片使用了不支持的协议（收到 {raw_target!r}）。"
            f"仅支持本机文件路径与 http:// 或 https:// 互联网图片地址。"
        )

    # 5. 本机文件路径校验
    expanded = Path(target).expanduser()
    resolved_candidate = expanded if expanded.is_absolute() else (Path.cwd() / expanded)
    try:
        resolved = resolved_candidate.resolve(strict=True)
    except (FileNotFoundError, OSError):
        _raise_image_error(
            f"第 {index} 张本机图片不存在：{raw_target!r}（解析路径：{resolved_candidate}）。"
            f"请确认图片文件已生成且路径无误。"
        )

    if not resolved.is_file():
        _raise_image_error(
            f"第 {index} 张图片路径不是文件（而是目录或特殊设备）：{resolved}。"
        )

    encoded_path = urllib.parse.quote(str(resolved), safe="")
    return {
        "src": f"/api/file?disposition=inline&path={encoded_path}",
        "raw": str(resolved),
        "name": resolved.name,
        "source": "local",
    }


def _parse_single_image(
    raw_item: str,
    index: int,
    fallback_caption: str | None = None,
) -> dict[str, Any]:
    """解析单条图片输入（支持 JSON 对象、``地址|说明`` 管道简写、或纯地址）。"""
    text = (raw_item or "").strip()
    if not text:
        _raise_image_error(
            f"第 {index} 张图片参数为空。请传入本机路径、互联网 URL，或 \"地址|说明\"。"
        )

    caption: str | None = (
        fallback_caption.strip()
        if isinstance(fallback_caption, str) and fallback_caption.strip()
        else None
    )

    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            _raise_image_error(
                f"第 {index} 张图片的 JSON 解析失败（{e.msg}）。推荐直接使用 \"地址|说明\" 格式。"
            )
        if not isinstance(obj, dict):
            _raise_image_error(
                f"第 {index} 张图片的 JSON 必须是对象（包含 src/path/url 与可选 caption）。"
            )
        raw_target = str(
            obj.get("src") or obj.get("path") or obj.get("url") or ""
        ).strip()
        if not raw_target:
            _raise_image_error(
                f"第 {index} 张图片 JSON 缺少地址字段（需提供 'src'、'path' 或 'url'）。"
            )
        raw_cap = (
            obj.get("caption")
            if obj.get("caption") is not None
            else obj.get("label")
            if obj.get("label") is not None
            else obj.get("title")
            if obj.get("title") is not None
            else obj.get("alt")
        )
        if raw_cap is not None and str(raw_cap).strip():
            caption = str(raw_cap).strip()
        resolved_info = _resolve_image_source(raw_target, index)
        if caption:
            resolved_info["caption"] = caption
        return resolved_info

    # 若包含竖线且整体不是一个已存在的本机路径，则按第一根竖线拆分为「地址|说明」
    raw_target = text
    if "|" in text and not Path(text).expanduser().exists():
        left, right = text.split("|", 1)
        raw_target = left.strip()
        if right.strip():
            caption = right.strip()

    resolved_info = _resolve_image_source(raw_target, index)
    if caption:
        resolved_info["caption"] = caption
    return resolved_info


def _normalize_columns(columns: str | None) -> int | None:
    """校验并规范化列数配置（支持 auto 或 1~4）。"""
    if columns is None:
        return None
    raw = str(columns).strip().lower()
    if not raw or raw == "auto":
        return None
    try:
        val = int(raw)
    except ValueError:
        _raise_image_error(
            f"--columns 参数值无效（收到 {columns!r}）。仅支持 auto 或 1 到 4 之间的整数。"
        )
    if val < 1 or val > 4:
        _raise_image_error(
            f"--columns 超出范围（收到 {val}）。网格列数仅支持 1 到 4（或不传以自适应屏幕）。"
        )
    return val


def validate_and_build_image_grid(
    *,
    items_positional: tuple[str, ...],
    items_option: tuple[str, ...],
    captions: tuple[str, ...],
    title: str | None,
    columns: str | None,
) -> dict[str, Any]:
    """校验所有图片参数并生成前端 ``image-grid`` 组件的数据包。"""
    combined_raw: list[str] = [*items_positional, *items_option]
    if not combined_raw:
        _raise_image_error(
            "image 组件缺少图片参数（请通过位置参数或 -i / --image 传入至少 1 个本机图片路径或互联网图片 URL）。"
        )

    norm_cols = _normalize_columns(columns)

    parsed_images: list[dict[str, Any]] = []
    for idx, raw_item in enumerate(combined_raw, start=1):
        fallback_cap = captions[idx - 1] if idx - 1 < len(captions) else None
        parsed_images.append(_parse_single_image(raw_item, idx, fallback_cap))

    clean_title = title.strip() if isinstance(title, str) and title.strip() else None

    data: dict[str, Any] = {
        "type": UI_IMAGE_GRID_MARKER,
        "images": parsed_images,
    }
    if clean_title is not None:
        data["title"] = clean_title
    if norm_cols is not None:
        data["columns"] = norm_cols

    return {
        "frago_ui_component": UI_IMAGE_GRID_MARKER,
        "component_type": UI_IMAGE_GRID_MARKER,
        "data": data,
        "next_action": (
            "前端图片网格组件数据已生成，WebUI 会将该自适应图片网格自动挂载到本轮最终收尾回复（Stop 消息）中渲染，"
            "用户可点击任意图片放大浮窗查看；无需在回复正文中重复手写 Markdown 图片链接。"
        ),
    }


@click.command(
    name="image",
    cls=ImageCommand,
    short_help="Render local or web images as an adaptive grid card in the session",
    help=(
        "将本机图片路径或互联网图片 URL 渲染为会话内的自适应屏幕网格卡片（支持点击放大浮窗预览）。\n\n"
        "正确调用示例:\n" + "\n".join(f"  {ex}" for ex in IMAGE_GRID_EXAMPLES)
    ),
)
@click.argument("items_positional", metavar="[IMAGES]...", nargs=-1)
@click.option(
    "-i",
    "--image",
    "items_option",
    multiple=True,
    help='图片项（可多次传入），支持纯路径/URL 或 "PATH_OR_URL|说明"，如 "/Users/a/1.png|图 1：主视觉"。',
)
@click.option(
    "-t",
    "--title",
    default=None,
    help="选填：图片网格卡片顶部的整体标题。",
)
@click.option(
    "-c",
    "--caption",
    "captions",
    multiple=True,
    help="选填：按顺序为图片附加说明文字（也可直接写在 -i \"地址|说明\" 中）。",
)
@click.option(
    "--columns",
    default=None,
    help="选填：固定网格列数（1~4）或 auto（默认按屏幕宽度与图片数量自适应）。",
)
def image_cmd(
    items_positional: tuple[str, ...],
    items_option: tuple[str, ...],
    captions: tuple[str, ...],
    title: str | None,
    columns: str | None,
) -> None:
    payload = validate_and_build_image_grid(
        items_positional=items_positional,
        items_option=items_option,
        captions=captions,
        title=title,
        columns=columns,
    )
    # 单行紧凑输出，避免 agent 在命令后接 `| tail -N` / `| head -N` 按行截断时把多行 JSON 切碎。
    click.echo(json.dumps(payload, ensure_ascii=False))
