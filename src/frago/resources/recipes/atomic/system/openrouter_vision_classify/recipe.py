# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
"""openrouter_vision_classify: 通过 OpenRouter chat/completions 调多模态模型做图像理解/分类。"""

import base64
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.5-flash-lite"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 256
TIMEOUT_SEC = 60.0
# 免费/共享额度的多模态模型经常被上游按池限流（HTTP 429），单次调用失败率实测
# 可达一半。重试是让调用方拿到结果的唯一办法，退避时长按实测的恢复速度取。
DEFAULT_RETRIES = 2
RETRY_BACKOFF_SEC = (1.5, 3.0)
RETRIABLE_STATUS = (408, 429, 500, 502, 503, 504)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def emit(result: dict) -> None:
    print(json.dumps(result, ensure_ascii=False))


def fail(msg: str, code: int = 1) -> None:
    emit({"success": False, "error": msg})
    sys.exit(code)


def get_api_key() -> str:
    try:
        secrets = json.loads(os.environ.get("FRAGO_SECRETS", "{}"))
    except json.JSONDecodeError:
        secrets = {}
    key = secrets.get("api_key")
    if not (isinstance(key, str) and key.strip()):
        fail("api_key missing；请在 ~/.frago/recipes.local.json 配置 openrouter_vision_classify.api_key")
    return key.strip()


def encode_image_to_data_url(path: str) -> str:
    p = Path(os.path.expanduser(path)).resolve()
    raw = p.read_bytes()
    suffix = p.suffix.lower().lstrip(".") or "png"
    mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif"}
    mime = mime_map.get(suffix, "png")
    return f"data:image/{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def normalize_image_input(image_input) -> list[str]:
    if isinstance(image_input, str):
        items = [image_input]
    elif isinstance(image_input, list):
        items = [x for x in image_input if isinstance(x, str)]
    else:
        items = []
    if not items:
        fail("image_input 为必填，且必须是字符串或字符串数组")
    out: list[str] = []
    for img in items:
        if img.startswith(("http://", "https://", "data:")):
            out.append(img)
        else:
            out.append(encode_image_to_data_url(img))
    return out


def build_request(params: dict, api_key: str) -> tuple[dict, dict]:
    prompt = params.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        fail("prompt 为必填")
    image_urls = normalize_image_input(params.get("image_input"))

    content: list[dict] = [{"type": "text", "text": prompt}]
    for url in image_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})

    body: dict = {
        "model": params.get("model") or DEFAULT_MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": params.get("temperature", DEFAULT_TEMPERATURE),
        "max_tokens": params.get("max_tokens", DEFAULT_MAX_TOKENS),
    }
    if (params.get("response_format") or "").lower() == "json":
        body["response_format"] = {"type": "json_object"}
    # 推理型模型（qwen3.x-flash 等）默认会先烧一大段 reasoning token，正文经常
    # 还没开始写就撞上 max_tokens，返回空 content。描述/分类这类任务不需要推理，
    # 显式关掉既省时间又省钱。不传该参数时保持模型自身默认，不影响老调用方。
    reasoning = params.get("reasoning_enabled")
    if isinstance(reasoning, bool):
        body["reasoning"] = {"enabled": reasoning}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://frago.local/recipes/openrouter_vision_classify",
        "X-Title": "frago openrouter_vision_classify",
    }
    return body, headers


def request_with_retry(body: dict, headers: dict, retries: int) -> httpx.Response:
    """POST 一次，限流或网络抖动时按退避重试，仍不成则直接结束进程。

    只重试上游明确「稍后再来」的那几类状态（限流、超时、网关故障）。4xx 里的
    参数错、鉴权错重试多少次都是同一个结果，立即报错才看得见真正的问题。
    """
    last_error = ""
    for attempt in range(retries + 1):
        try:
            resp = httpx.post(OPENROUTER_URL, json=body, headers=headers, timeout=TIMEOUT_SEC)
        except httpx.HTTPError as e:
            last_error = f"OpenRouter 请求失败: {e}"
        else:
            if resp.status_code == 200:
                return resp
            log(f"OpenRouter HTTP {resp.status_code}: {resp.text[:500]}")
            last_error = f"OpenRouter 返回 HTTP {resp.status_code}: {resp.text[:300]}"
            if resp.status_code not in RETRIABLE_STATUS:
                fail(last_error)
        if attempt < retries:
            delay = RETRY_BACKOFF_SEC[min(attempt, len(RETRY_BACKOFF_SEC) - 1)]
            log(f"第 {attempt + 1} 次尝试失败，{delay}s 后重试")
            time.sleep(delay)
    fail(f"{last_error}（已重试 {retries} 次）")
    raise SystemExit(1)  # unreachable: fail() exits


def try_parse_json(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def main() -> None:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        params: dict = {}
    else:
        try:
            params = json.loads(sys.argv[1])
        except json.JSONDecodeError as e:
            fail(f"参数解析失败: {e}")

    api_key = get_api_key()
    body, headers = build_request(params, api_key)

    retries = params.get("retries")
    if not isinstance(retries, int) or retries < 0:
        retries = DEFAULT_RETRIES
    resp = request_with_retry(body, headers, retries)

    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        fail(f"OpenRouter 响应缺少 choices: {data}")
    msg = choices[0].get("message") or {}
    raw_text = msg.get("content") or ""
    if not isinstance(raw_text, str):
        raw_text = json.dumps(raw_text, ensure_ascii=False)

    result: dict = {
        "success": True,
        "raw_text": raw_text,
        "model": data.get("model") or body["model"],
        "usage": data.get("usage") or {},
    }
    if (params.get("response_format") or "").lower() == "json":
        parsed = try_parse_json(raw_text)
        if parsed is not None:
            result["parsed_json"] = parsed

    emit(result)


if __name__ == "__main__":
    main()
