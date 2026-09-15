"""语音合成：文字变成音频文件，外加准确时长与逐句起止时间。

这一层**不出声**，也不依赖舞台在不在跑——`frago desktop voice synth` 直接调它，
broker 的 `say --speak` 也调它。出声、排队、录进片子是 broker 的事。

引擎只有 Edge 语音合成（edge-tts）。它走的是 Edge 浏览器「朗读」功能的非公开
接口：免费、快、够卡节奏，但没有服务保障——出过全部请求 403、握手 503 的故障。
所以这里做两件事兜底：失败带间隔重试；重试完仍失败就抛 VoiceFailed，由调用方
决定降级（broker 退回只显示字幕，并在回执里写明这句没出声）。

缓存
----
落点 ``~/.frago/cache/tts/<引擎>/<指纹前两位>/<指纹>.{mp3,json}``。

- 不放 data/：那是给人翻的事务产出；不放 recipe-data/：这不是配方。
  ``~/.frago/cache/`` 本来就在备份忽略名单里，音频删了能重新生成，不该进备份。
- 指纹 = 引擎 + 声音 + 语速 + 音量 + 音高 + 文字。文字只去首尾空白、统一换行，
  标点一个不动——标点决定停顿与语气。
- 先写临时文件再改名：合成中途断网或进程被杀，不会留下半截音频被当成命中。
- 同样的输入合成结果不变，所以不按时间过期；按总容量上限（默认 500MB，
  config.json 的 ``tts.cache_max_mb``）从最久没用的删起。
- 缓存可以随时删掉。场景要长期留的音频自己复制一份走（录制停录时就是这么做的）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from contextlib import suppress
from pathlib import Path

ENGINE = "edge"
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
MIN_EDGE_TTS = "7.2.8"

CACHE_ROOT = Path.home() / ".frago" / "cache" / "tts"
CONFIG_PATH = Path.home() / ".frago" / "config.json"
DEFAULT_CACHE_MAX_MB = 500

# Edge 固定输出 audio-24khz-48kbitrate-mono-mp3，恒定码率。时长按字节数算是准的，
# edge-tts 7.2.8 自己也改成了这个算法；不用最后一句的边界去推——那不含句尾静音。
BITRATE_BPS = 48_000
SAMPLE_RATE = 24_000

# 边界时间的单位是 100 纳秒（Windows tick）。
TICKS_PER_MS = 10_000

# 第 1 次失败后等 1 秒，第 2 次后等 2 秒，一共试 3 次。参数写错不重试。
RETRY_DELAYS = (1.0, 2.0)

_RATE_RE = re.compile(r"^[+-]\d{1,3}%$")
_PITCH_RE = re.compile(r"^[+-]\d{1,4}Hz$")
_KEY_RE = re.compile(r"^[0-9a-f]{64}$")


class VoiceUnavailable(RuntimeError):
    """本机合成不了：edge-tts 导入不了。它是 frago 的必装依赖，导入不了就是 frago
    没装完整，补救是重装 frago，不是让人去单独补一个包。"""


class VoiceFailed(RuntimeError):
    """合成这一句没做成（网络、服务端、没拿到音频或句子时间）。"""


# ── 指纹与落点 ──────────────────────────────────────────────────────────

def normalize_text(text: str) -> str:
    return str(text).replace("\r\n", "\n").replace("\r", "\n").strip()


def cache_key(text: str, voice: str, rate: str, volume: str, pitch: str,
              engine: str = ENGINE) -> str:
    # 各字段之间用 \0 隔开：直接拼接的话 ("ab", "c") 和 ("a", "bc") 是同一个指纹。
    raw = "\0".join((engine, voice, rate, volume, pitch, normalize_text(text)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _paths(key: str, engine: str = ENGINE) -> tuple[Path, Path]:
    base = CACHE_ROOT / engine / key[:2] / key
    return base.with_suffix(".mp3"), base.with_suffix(".json")


def audio_path(key: str, engine: str = ENGINE) -> Path | None:
    """指纹对应的缓存音频。指纹形状不对或文件不在都给 None——这条给 HTTP 路由用，
    路径拼接之前先把形状卡死，别让一个 `../` 走进文件系统。"""
    if not _KEY_RE.match(key or ""):
        return None
    audio, meta = _paths(key, engine)
    return audio if audio.is_file() and meta.is_file() else None


# ── 参数 ────────────────────────────────────────────────────────────────

def check_params(rate: str, volume: str, pitch: str) -> None:
    """格式错在这儿就说清楚，不交给 edge-tts 抛一句看不出是哪个参数的错。"""
    if not _RATE_RE.match(rate):
        raise ValueError(f"语速写成 +10% / -20% 这种形状，得到: {rate!r}")
    if not _RATE_RE.match(volume):
        raise ValueError(f"音量写成 +10% / -20% 这种形状，得到: {volume!r}")
    if not _PITCH_RE.match(pitch):
        raise ValueError(f"音高写成 +5Hz / -10Hz 这种形状，得到: {pitch!r}")


def _import_edge_tts():
    try:
        import edge_tts  # noqa: PLC0415 —— 只在真要合成时才付这笔 import
    except ImportError:
        raise VoiceUnavailable(
            "frago 安装不完整：随 frago 一起装的语音合成组件 edge-tts 缺失，"
            "合成不了语音。重新安装 frago 即可补上。"
        ) from None
    return edge_tts


# ── 合成 ────────────────────────────────────────────────────────────────

async def _stream_once(edge_tts, text: str, voice: str, rate: str, volume: str,
                       pitch: str) -> tuple[bytes, list[dict]]:
    talker = edge_tts.Communicate(text, voice, rate=rate, volume=volume,
                                  pitch=pitch, boundary="SentenceBoundary")
    chunks: list[bytes] = []
    marks: list[dict] = []
    async for chunk in talker.stream():
        if chunk.get("type") == "audio":
            chunks.append(chunk["data"])
        elif chunk.get("type") == "SentenceBoundary":
            start = int(chunk.get("offset") or 0) // TICKS_PER_MS
            dur = int(chunk.get("duration") or 0) // TICKS_PER_MS
            marks.append({"start_ms": start, "end_ms": start + dur,
                          "text": chunk.get("text")})
    return b"".join(chunks), marks


async def synthesize(text: str, voice: str = DEFAULT_VOICE, rate: str = "+0%",
                     volume: str = "+0%", pitch: str = "+0Hz") -> dict:
    """合成一句，先查缓存。返回说明文件的内容，外加 audio / meta 路径与 cached。

    **句子时间与音频同一趟拿**（SentenceBoundary）：精确、不用猜。NEVER 事后
    做静音检测去推——那是在猜一件已经知道的事。一条句子时间都没给的结果不算
    合成成功，也不进缓存：拿不到时间点，字幕和对齐都无从谈起。
    """
    text = normalize_text(text)
    if not text:
        raise ValueError("没有要合成的文字")
    check_params(rate, volume, pitch)
    key = cache_key(text, voice, rate, volume, pitch)
    audio, meta = _paths(key)

    hit = _read_meta(meta) if audio.is_file() else None
    if hit is not None:
        hit["last_used_at"] = _now_iso()
        _write_atomic(meta, json.dumps(hit, ensure_ascii=False, indent=2).encode())
        return {**hit, "audio": str(audio), "meta": str(meta), "cached": True}

    edge_tts = _import_edge_tts()
    errors: list[str] = []
    data, marks = b"", []
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            data, marks = await _stream_once(edge_tts, text, voice, rate,
                                             volume, pitch)
            if not data:
                raise VoiceFailed("服务端没有返回任何音频")
            if not marks:
                raise VoiceFailed(f"{voice} 一条句子时间都没给，换一个声音再试")
            break
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001 —— 网络与服务端的错一律算可重试
            errors.append(f"第 {attempt + 1} 次：{type(exc).__name__}: {exc}"
                          .rstrip(": "))
            if attempt < len(RETRY_DELAYS):
                await asyncio.sleep(RETRY_DELAYS[attempt])
    else:
        raise VoiceFailed("Edge 语音合成试了 "
                          f"{len(RETRY_DELAYS) + 1} 次都没成：" + "；".join(errors))

    now = _now_iso()
    doc = {
        "key": key, "engine": ENGINE,
        "text": text, "voice": voice, "rate": rate, "volume": volume,
        "pitch": pitch,
        "format": "mp3", "sample_rate": SAMPLE_RATE, "channels": 1,
        "bitrate_bps": BITRATE_BPS,
        "bytes": len(data),
        "duration_ms": round(len(data) * 8 * 1000 / BITRATE_BPS),
        "sentences": marks,
        "created_at": now, "last_used_at": now,
        **({"retried": errors} if errors else {}),
    }
    # 音频先落、说明后落：命中的判据是两份都在，说明文件是最后那一笔。
    _write_atomic(audio, data)
    _write_atomic(meta, json.dumps(doc, ensure_ascii=False, indent=2).encode())
    evicted = evict(keep=key)
    out = {**doc, "audio": str(audio), "meta": str(meta), "cached": False}
    if evicted["files"]:
        out["evicted"] = evicted
    return out


def synthesize_sync(*args, **kwargs) -> dict:
    """命令行那一侧没有事件循环，给它一个同步入口。"""
    return asyncio.run(synthesize(*args, **kwargs))


# ── 容量 ────────────────────────────────────────────────────────────────

def cache_max_bytes() -> int:
    """缓存总容量上限。读不到配置就用默认值，读到的值不像话也用默认值。"""
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        mb = float((data.get("tts") or {}).get("cache_max_mb",
                                                DEFAULT_CACHE_MAX_MB))
        if mb <= 0:
            mb = DEFAULT_CACHE_MAX_MB
    except (OSError, ValueError, AttributeError, TypeError):
        mb = DEFAULT_CACHE_MAX_MB
    return int(mb * 1024 * 1024)


def _entries() -> list[tuple[float, int, Path, Path]]:
    """(最近使用时刻, 两份文件合计字节, 音频, 说明)。最近使用时刻取说明文件的
    mtime——命中时会重写它，比每次打开几百个 JSON 去读 last_used_at 便宜。"""
    out = []
    if not CACHE_ROOT.is_dir():
        return out
    for meta in CACHE_ROOT.glob("*/*/*.json"):
        audio = meta.with_suffix(".mp3")
        try:
            st = meta.stat()
            size = st.st_size + (audio.stat().st_size if audio.exists() else 0)
        except OSError:
            continue
        out.append((st.st_mtime, size, audio, meta))
    return out


def stats() -> dict:
    entries = _entries()
    return {"root": str(CACHE_ROOT), "lines": len(entries),
            "bytes": sum(e[1] for e in entries),
            "max_bytes": cache_max_bytes()}


def evict(keep: str | None = None) -> dict:
    """超出上限就从最久没用的删起，刚写进来的那一句不删。"""
    cap = cache_max_bytes()
    entries = sorted(_entries())
    total = sum(e[1] for e in entries)
    removed, freed = 0, 0
    for _mtime, size, audio, meta in entries:
        if total <= cap:
            break
        if keep and meta.stem == keep:
            continue
        for p in (meta, audio):
            with suppress(OSError):
                p.unlink(missing_ok=True)
        total -= size
        freed += size
        removed += 1
    return {"files": removed, "bytes": freed}


def clear() -> dict:
    """清空整个语音缓存。已经复制进录制目录的音频不受影响。"""
    before = stats()
    if CACHE_ROOT.is_dir():
        shutil.rmtree(CACHE_ROOT, ignore_errors=True)
    return {"root": before["root"], "removed_lines": before["lines"],
            "freed_bytes": before["bytes"]}


# ── 小工具 ──────────────────────────────────────────────────────────────

def _read_meta(meta: Path) -> dict | None:
    try:
        doc = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("sentences") else None


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
