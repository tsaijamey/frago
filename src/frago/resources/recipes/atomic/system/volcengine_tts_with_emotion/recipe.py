#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["requests>=2.32.0"]
# ///
"""
Recipe: volcengine_tts_with_emotion
Platform: Volcengine (火山引擎)
Description: 使用火山引擎 ICL 2.0 声音克隆API生成带情感表达的语音，支持SSML和 [#语气] 标记
Created: 2025-11-28
Version: 3.0.0

环境变量由 frago recipe run 自动从 ~/.frago/.env 加载
"""

import base64
import json
import os
import re
import sys
from pathlib import Path

import requests


def parse_emotion_from_text(text: str) -> tuple[str, str | None]:
    """
    解析文本中的 [#语气] 标记，拆分成要合成的文本和语气描述。

    支持格式：
    - [#用低沉沙哑的语气说]你好世界  ->  ("你好世界", "用低沉沙哑的语气说")
    - [#痛心地]这太遗憾了  ->  ("这太遗憾了", "痛心地")
    - 普通文本  ->  ("普通文本", None)

    Args:
        text: 可能包含 [#语气] 标记的文本

    Returns:
        tuple: (clean_text, emotion_context)
    """
    # 匹配 [#...] 格式的语气标记
    pattern = r'^\[#([^\]]+)\](.*)$'
    match = re.match(pattern, text.strip(), re.DOTALL)

    if match:
        emotion = match.group(1).strip()
        clean_text = match.group(2).strip()
        return clean_text, emotion
    return text, None


def synthesize_speech(
    text: str,
    speaker_id: str = "",
    output_file: str | None = None,
    output_format: str = "wav",
    sample_rate: int = 16000,
    speech_rate: int = 0,
    silence_duration: int = 0,
) -> dict:
    """
    调用火山引擎 ICL 2.0 声音克隆API生成带情感的语音

    支持三种文本格式：
    1. 语气标记: "[#用兴奋激动的语气说]太棒了！" - 自动解析语气，传递给 context_texts
    2. 纯文本: "你好，很高兴认识你"
    3. SSML: "<speak>《<phoneme alphabet=\"py\" ph=\"xi1 xi1\">茜茜</phoneme>公主》</speak>"

    Args:
        text: 要合成的文本，支持 [#语气]文本 格式、纯文本或SSML格式
        speaker_id: 音色ID（不传则用环境变量VOICE_ID）
        output_file: 输出音频文件路径（可选，不指定则返回base64）
        output_format: 输出格式 wav/mp3/ogg_opus/pcm（默认wav）
        sample_rate: 采样率（默认16000）
        speech_rate: 语速 [-50, 100]（默认0）
        silence_duration: 句尾静音时长毫秒（默认0）

    Returns:
        dict: {
            "success": bool,
            "audio_file": str (如果指定了output_file),
            "audio_base64": str (如果没指定output_file),
            "duration_ms": int (估算时长),
            "text_length": int,
            "emotion_context": str (解析出的语气，如果有)
        }
    """
    # 解析 [#语气] 标记
    clean_text, emotion_context = parse_emotion_from_text(text)

    # 从环境变量获取凭证
    app_id = os.environ.get("X_APP_ID") or os.environ.get("X-APP-ID")
    access_key = os.environ.get("X_ACCESS_TOKEN") or os.environ.get("X-ACCESS-TOKEN")
    voice_id = speaker_id or os.environ.get("VOICE_ID")

    if not app_id:
        return {"success": False, "error": "缺少环境变量: X_APP_ID"}
    if not access_key:
        return {"success": False, "error": "缺少环境变量: X_ACCESS_TOKEN"}
    if not voice_id:
        return {"success": False, "error": "缺少 speaker_id 参数或环境变量 VOICE_ID"}

    # 使用 ICL 2.0 声音克隆接口
    resource_id = "seed-icl-2.0"

    # V3 HTTP单向流式接口
    url = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"

    headers = {
        "X-Api-App-Id": app_id,
        "X-Api-Access-Key": access_key,
        "X-Api-Resource-Id": resource_id,
        "Content-Type": "application/json",
        "Connection": "keep-alive",
    }

    # 构造 additions（语气控制）
    additions_data = {}
    if emotion_context:
        additions_data["context_texts"] = [emotion_context]

    # 构造请求体
    payload = {
        "user": {"uid": "frago_recipe_user"},
        "req_params": {
            "text": clean_text,
            "speaker": voice_id,
            "silence_duration": silence_duration,
            "audio_params": {
                "format": output_format,
                "sample_rate": sample_rate,
                "speech_rate": speech_rate,
            },
            # additions 必须是字符串化的 JSON
            "additions": json.dumps(additions_data, ensure_ascii=False),
        },
    }

    try:
        # 发送流式请求（V3接口返回流式JSON）
        session = requests.Session()
        response = session.post(url, headers=headers, json=payload, stream=True, timeout=60)

        if response.status_code != 200:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text[:500]}",
            }

        # 收集流式返回的音频数据
        audio_chunks = []

        for line in response.iter_lines():
            if not line:
                continue

            try:
                data = json.loads(line.decode("utf-8"))

                # 检查返回码（0和20000000都是成功）
                code = data.get("code")
                if code not in (0, 20000000, None):
                    error_msg = data.get("message", "Unknown error")
                    return {"success": False, "error": f"API错误 [{code}]: {error_msg}"}

                # 提取音频数据
                audio_base64 = data.get("data")
                if audio_base64:
                    audio_bytes = base64.b64decode(audio_base64)
                    audio_chunks.append(audio_bytes)

            except json.JSONDecodeError:
                continue

        if not audio_chunks:
            return {"success": False, "error": "未收到音频数据"}

        full_audio = b"".join(audio_chunks)

        # 估算时长（粗略计算）
        if output_format == "mp3":
            # MP3 比特率约 128kbps
            duration_ms = int(len(full_audio) * 8 / 128)
        else:
            # PCM: 采样率 * 2字节 * 单声道
            duration_ms = int(len(full_audio) / (sample_rate * 2) * 1000)

        result = {
            "success": True,
            "text_length": len(clean_text),
            "duration_ms": duration_ms,
            "format": output_format,
            "sample_rate": sample_rate,
        }

        # 如果解析出语气，添加到结果
        if emotion_context:
            result["emotion_context"] = emotion_context

        # 保存或返回音频
        if output_file:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(full_audio)
            result["audio_file"] = str(output_path.absolute())
        else:
            result["audio_base64"] = base64.b64encode(full_audio).decode("utf-8")

        return result

    except requests.exceptions.Timeout:
        return {"success": False, "error": "请求超时"}
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": f"网络错误: {e!s}"}
    except Exception as e:
        return {"success": False, "error": f"未知错误: {e!s}"}


def main():
    """CLI 入口"""
    # 解析参数
    if len(sys.argv) < 2:
        # 默认示例（使用语气标记）
        params = {
            "text": "[#用兴奋激动的语气说]太棒了！我们成功了！",
            "output_file": "tts_output.wav",
        }
    else:
        try:
            params = json.loads(sys.argv[1])
        except json.JSONDecodeError as e:
            print(json.dumps({"success": False, "error": f"参数解析失败: {e}"}, ensure_ascii=False))
            sys.exit(1)

    # 必需参数检查
    if "text" not in params:
        print(json.dumps({"success": False, "error": "缺少必需参数: text"}, ensure_ascii=False))
        sys.exit(1)

    # 调用合成函数
    result = synthesize_speech(
        text=params["text"],
        speaker_id=params.get("speaker_id", ""),
        output_file=params.get("output_file"),
        output_format=params.get("output_format", "wav"),
        sample_rate=params.get("sample_rate", 16000),
        speech_rate=params.get("speech_rate", 0),
        silence_duration=params.get("silence_duration", 0),
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
