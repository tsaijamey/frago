# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
"""doubao_seedream_image: 调用 Ark Doubao Seedream 同步图像生成 API。"""

import base64
import json
import mimetypes
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
GENERATE_PATH = "/images/generations"
DEFAULT_MODEL = "doubao-seedream-5-0-lite"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def emit(result: dict) -> None:
    print(json.dumps(result, ensure_ascii=False))


def get_api_key() -> str | None:
    try:
        secrets = json.loads(os.environ.get("FRAGO_SECRETS", "{}"))
    except json.JSONDecodeError:
        secrets = {}
    key = secrets.get("api_key")
    if key:
        return key.strip() or None
    return None


def get_base_url() -> str:
    """secrets 可带 base_url（如 Agent Plan 专属通道 /api/plan/v3），缺省走标准端点。"""
    try:
        secrets = json.loads(os.environ.get("FRAGO_SECRETS", "{}"))
    except json.JSONDecodeError:
        secrets = {}
    return (secrets.get("base_url") or ARK_BASE_URL).rstrip("/")


def normalize_image_input(value):
    """image 参数支持本地路径 / URL / data URI，本地文件读入后转 base64 data URI。"""
    if isinstance(value, list):
        return [normalize_image_input(v) for v in value]
    if not isinstance(value, str) or not value.strip():
        raise ValueError("image 参数必须是非空字符串或字符串数组")
    value = value.strip()
    if value.startswith(("http://", "https://", "data:")):
        return value
    path = Path(os.path.expanduser(value)).resolve()
    if not path.is_file():
        raise ValueError(f"参考图不存在: {path}")
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def build_request_body(params: dict) -> dict:
    body: dict = {
        "model": params.get("model") or DEFAULT_MODEL,
        "prompt": params["prompt"],
        "sequential_image_generation": params.get("sequential_image_generation")
        or "disabled",
        "response_format": params.get("response_format") or "url",
        # Agent Plan 通道的 size 校验只认小写（'2k'/'3k'/'4k'），统一小写两通道均兼容
        "size": str(params.get("size") or "2k").lower(),
        "stream": False,
        "watermark": bool(params.get("watermark", False)),
    }
    if params.get("image"):
        body["image"] = normalize_image_input(params["image"])
    return body


def call_api(api_key: str, body: dict) -> tuple[dict, str | None]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = f"{get_base_url()}{GENERATE_PATH}"
    log(f"[step2] POST {url}")
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(url, headers=headers, json=body)
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        return {}, f"网络请求失败: {exc}"
    try:
        data = resp.json()
    except ValueError:
        return {"http_status": resp.status_code, "text": resp.text}, (
            f"响应非 JSON (status={resp.status_code}): {resp.text[:500]}"
        )
    if resp.status_code >= 300:
        return data, f"API 调用失败 status={resp.status_code}: {json.dumps(data, ensure_ascii=False)}"
    return data, None


def extract_image_url(resp: dict) -> str | None:
    data = resp.get("data") if isinstance(resp, dict) else None
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            url = first.get("url")
            if isinstance(url, str) and url:
                return url
    return None


def download_image(url: str, target: Path, max_attempts: int = 3) -> str | None:
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=120.0, follow_redirects=True) as client:
                with client.stream("GET", url) as resp:
                    if resp.status_code >= 300:
                        last_exc = RuntimeError(f"下载 status={resp.status_code}")
                        time.sleep(2**attempt)
                        continue
                    with target.open("wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=1 << 16):
                            if chunk:
                                f.write(chunk)
            if target.exists() and target.stat().st_size > 0:
                return None
            last_exc = RuntimeError("下载产物为空")
        except (httpx.TransportError, httpx.TimeoutException, OSError) as exc:
            last_exc = exc
        time.sleep(2**attempt)
    return f"图片下载失败: {last_exc}"


def main() -> None:
    if len(sys.argv) < 2:
        params: dict = {}
    else:
        try:
            params = json.loads(sys.argv[1])
        except json.JSONDecodeError as exc:
            emit({"success": False, "error": f"参数解析失败: {exc}"})
            sys.exit(1)

    prompt = (params.get("prompt") or "").strip()
    if not prompt:
        emit({"success": False, "error": "prompt 不能为空"})
        sys.exit(1)
    params["prompt"] = prompt

    output_dir_raw = params.get("output_dir")
    if not output_dir_raw:
        emit({"success": False, "error": "output_dir 是必填参数"})
        sys.exit(1)
    output_dir = Path(os.path.expanduser(output_dir_raw)).resolve()

    api_key = get_api_key()
    if not api_key:
        emit(
            {
                "success": False,
                "error": "缺少 api_key：请在 ~/.frago/recipes.local.json 的 doubao_seedream_image.api_key 配置",
            }
        )
        sys.exit(1)

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        emit({"success": False, "error": f"output_dir 创建失败: {exc}"})
        sys.exit(1)

    try:
        request_body = build_request_body(params)
    except ValueError as exc:
        emit({"success": False, "error": str(exc)})
        sys.exit(1)
    log(f"[step1] ✓ request built, model={request_body['model']}, size={request_body['size']}")

    started_at = datetime.now().isoformat()
    resp_data, err = call_api(api_key, request_body)

    # 元数据里不落 base64 原文，避免 JSON 膨胀到几 MB
    meta_body = dict(request_body)
    if "image" in meta_body:
        imgs = meta_body["image"]
        imgs_list = imgs if isinstance(imgs, list) else [imgs]
        meta_body["image"] = [
            f"<data-uri {len(i)} chars>" if i.startswith("data:") else i
            for i in imgs_list
        ]

    metadata = {
        "prompt": prompt,
        "model": request_body["model"],
        "request_body": meta_body,
        "api_response": resp_data,
        "usage": resp_data.get("usage") if isinstance(resp_data, dict) else None,
        "started_at": started_at,
        "finished_at": None,
    }

    if err:
        log(f"[step2] ✗ {err}")
        metadata["finished_at"] = datetime.now().isoformat()
        meta_path = output_dir / f"seedream_failed_{int(time.time())}.json"
        try:
            meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
        except OSError:
            meta_path = None
        emit(
            {
                "success": False,
                "error": err,
                "metadata_file": str(meta_path) if meta_path else None,
                "prompt": prompt,
                "size": request_body["size"],
            }
        )
        sys.exit(1)

    image_url = extract_image_url(resp_data)
    if not image_url:
        emit(
            {
                "success": False,
                "error": f"响应缺少 data[0].url: {json.dumps(resp_data, ensure_ascii=False)}",
                "prompt": prompt,
            }
        )
        sys.exit(1)

    log(f"[step2] ✓ got image_url")

    filename = params.get("filename")
    if not filename:
        filename = f"seedream_{int(time.time())}"
    image_path = output_dir / f"{filename}.png"

    log(f"[step3] downloading -> {image_path}")
    dl_err = download_image(image_url, image_path)
    if dl_err:
        emit(
            {
                "success": False,
                "error": dl_err,
                "image_url": image_url,
                "prompt": prompt,
            }
        )
        sys.exit(1)
    log(f"[step3] ✓ saved: {image_path}")

    metadata["finished_at"] = datetime.now().isoformat()
    meta_path = output_dir / f"{filename}.json"
    try:
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
        meta_path_str: str | None = str(meta_path)
    except OSError as exc:
        log(f"[step4] 元数据写入失败: {exc}")
        meta_path_str = None

    emit(
        {
            "success": True,
            "image_path": str(image_path),
            "image_url": image_url,
            "size": request_body["size"],
            "prompt": prompt,
            "metadata_file": meta_path_str,
            "usage": metadata["usage"],
            "error": None,
        }
    )


if __name__ == "__main__":
    main()
