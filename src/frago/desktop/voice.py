"""语音合成：文字变成音频文件，外加准确时长与逐句起止时间。

这一层**不出声**，也不依赖舞台在不在跑——`frago desktop voice synth` 直接调它，
broker 的 `say --speak` 也调它。出声、排队、录进片子是 broker 的事。

引擎只有 Edge 语音合成（edge-tts）。它走的是 Edge 浏览器「朗读」功能的非公开
接口：免费、快、够卡节奏，但没有服务保障——出过全部请求 403、握手 503 的故障。
所以这里做两件事兜底：失败带间隔重试；重试完仍失败就抛 VoiceFailed，由调用方
决定降级（broker 退回只显示字幕，并在回执里写明这句没出声）。

端点
----
朗读的合成端点换过一次家（2026-10-12 记）。旧主机 ``speech.platform.bing.com``
从 2026-10 起对合成用的那条 WebSocket 一律回 403，分地区推进，轮到本机是 10-12；
同一时刻、同一台机器上取声音列表的那条普通 HTTPS 接口仍回 200，被拒的不是整站，
也不是这台机器的出口。重试兜不住换家——三次打的是同一扇关着的门。

接手的是新主机 ``api.msedgeservices.com``，Edge 155 的朗读走这条：

- 网址 ``wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1``
- 凭证参数改叫 ``Ocp-Apim-Subscription-Key``。沿用旧名 ``TrustedClientToken``
  在新主机上同样回 403——两处必须一起换（2026-10-12 实测，同一枚 token 只有换成
  新名才握手成）
- 版本标识 Edge 155 自己发的是 ``2-155.0.4283.45``；实测沿用旧的
  ``1-143.0.3650.75`` 也被接受，这一项没动

2026-10-12 实测：同一枚旧 ``Sec-MS-GEC``、同一套请求头，打旧主机回 403，
打新主机回 ``101 Switching Protocols``。一拒一收，被拒的是旧那台主机，签名没问题。

**切在调用前，不等上游。** edge-tts 7.2.8（PyPI 上的最新版）把网址写死在它自己的
``constants.py`` 里，仍指着旧主机，上游的切换改动尚未发版。每次合成前由
``_point_at_new_endpoint`` 把库里的网址覆盖成上面那条；库若把内部的名字挪了地方，
那里当场报出库的版本，不退化成一句看不出原因的 403。

语言
----
这一层只说英文（2026-10-09 定）：嗓子限 ``en-*``，正文里不许出现中日文字符。
演示是给外面看的，两样都得是英文。只锁嗓子锁不住语言——Multilingual 那一代给什么
文字就念什么语言，英文嗓子念中文，出来的仍是中文；只锁正文也锁不住——中文嗓子念
英文台词，出来的是一口中文腔。所以两样分开卡，开关是 ``ENFORCE_ENGLISH_VOICE``
与 ``ENFORCE_ENGLISH_TEXT``，要放宽就改这两个常量，别在调用处绕。

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
DEFAULT_VOICE = "en-US-AndrewMultilingualNeural"
MIN_EDGE_TTS = "7.2.8"

#: 合成端点。edge-tts 把旧主机写死在它自己的 constants 里，调用前由
#: ``_point_at_new_endpoint`` 换掉（旧主机自 2026-10 起一律 403，见文件头「端点」）。
WSS_ENDPOINT = "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"
#: 新主机认的凭证参数名。旧主机叫 ``TrustedClientToken``，写成旧名同样 403。
CREDENTIAL_PARAM = "Ocp-Apim-Subscription-Key"

#: 这一层只说英文。两处开关：嗓子必须 en- 开头；正文里不许出现中日文字符。
#: 两个都得开着才锁得住语言，理由见文件头「语言」一节。
LANGUAGE = "en"
ENFORCE_ENGLISH_VOICE = True
ENFORCE_ENGLISH_TEXT = True

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
#: 中日韩文字与中日文标点。正文里出现任何一个，就说明这不是英文台词。
_CJK_RE = re.compile(r"[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf"
                     r"\u4e00-\u9fff\uf900-\ufaff]")


class VoiceUnavailable(RuntimeError):
    """这一层起不来：edge-tts 导入不了，或者它的内部结构与预期不符（换端点那段
    找不到要改的名字）。两种都是这个包的问题，不是这一句台词的问题——当场报出来，
    别退化成「这句没出声」，也别被当成网络错重试三次再降级。

    导入不了就是 frago 没装完整，补救是重装 frago，不是让人去单独补一个包。"""


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


def check_language(text: str, voice_name: str) -> None:
    """这一层只说英文：不达标就停在这儿，并说清怎么改。

    抛 ValueError 是刻意的——它跟 VoiceFailed 不是一类：VoiceFailed 是「这次没合成
    成」，调用方退回只显示字幕照常往下走；这个是「这个要求这一层不做」，必须当场可见。
    闷声把中文台词念成英文腔，或退回字幕让人以为只是没声音，两种都比报错更坏。
    """
    if ENFORCE_ENGLISH_VOICE and not voice_name.startswith(f"{LANGUAGE}-"):
        raise ValueError(
            f"语音层只说英文：嗓子要 en- 开头的英文嗓子，得到 {voice_name!r}。"
            f"念英文就用 {DEFAULT_VOICE}；真要放宽，把 frago.desktop.voice 里的 "
            "ENFORCE_ENGLISH_VOICE 改成 False。")
    if ENFORCE_ENGLISH_TEXT and _CJK_RE.search(text):
        raise ValueError(
            "语音层只说英文：这句里有中日文字符，这一层不合成。"
            "台词写成英文再来；真要放宽，把 frago.desktop.voice 里的 "
            "ENFORCE_ENGLISH_TEXT 改成 False。")


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

def _point_at_new_endpoint(edge_tts) -> None:
    """把库里的合成网址换到新主机，不换就是每句 403。

    ``edge_tts.communicate`` 导入时把常量绑进了自己的命名空间
    （``from .constants import WSS_URL``），只改常量模块改不动它，两处都得写。
    库若把这两个名字挪了地方，这里当场报出库的版本，别让它漏成一句看不出原因的 403。
    """
    try:
        token = edge_tts.constants.TRUSTED_CLIENT_TOKEN
        edge_tts.communicate.WSS_URL  # noqa: B018 —— 只为确认这个绑定还在
    except AttributeError as exc:
        version = getattr(edge_tts, "__version__", "版本读不出来")
        raise VoiceUnavailable(
            f"edge-tts {version} 的内部结构与预期不符，改不了合成端点。"
            "核对这个包，再调整 frago.desktop.voice 里换端点那一段。") from exc
    url = f"{WSS_ENDPOINT}?{CREDENTIAL_PARAM}={token}"
    edge_tts.constants.WSS_URL = url
    edge_tts.communicate.WSS_URL = url


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
    check_language(text, voice)
    key = cache_key(text, voice, rate, volume, pitch)
    audio, meta = _paths(key)

    hit = _read_meta(meta) if audio.is_file() else None
    if hit is not None:
        hit["last_used_at"] = _now_iso()
        _write_atomic(meta, json.dumps(hit, ensure_ascii=False, indent=2).encode())
        return {**hit, "audio": str(audio), "meta": str(meta), "cached": True}

    edge_tts = _import_edge_tts()
    # 换端点放在重试之前：它失败说明这个包不能用，重试三次还是同一个包，
    # 而且那属于 VoiceUnavailable，不该被当成可重试的网络错吞成 VoiceFailed。
    _point_at_new_endpoint(edge_tts)
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
