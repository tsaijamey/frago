"""会话页上给会话起的名字（alias），存在服务端每场会话自己的备份目录里，盖在各家自己的标题上面。

**为什么不写回各家的档案。** 五家存标题的地方各不相同：Claude Code 往会话 jsonl 末尾追一行
``custom-title``，codex 根本不让改名，opencode 在自己的库里，CoreAgent 与 agy 另有一套。往别人的
档案里写东西，那场会话此刻正开着时还会跟引擎抢同一个文件。这里在 ``~/.frago/sessions/<家族>/<编号>/``
下跟 ``observer-slots.json``、``workbench-marks.json`` 并排存一份 ``workbench-title.json``，
清单出门前盖上去，五家一个样，原档案一个字不动。

**两个来源都写这里：**

1. 会话详情页顶部的标题：人直接点标题改字，或点旁边的星号按钮让 CoreAgent 单轮生成一个标题；
2. 交接到新会话：原会话改叫「甲 #1」，新会话叫「甲 #2」。

**问模型走 ``frago-core --mode chat --as-role coreagent``。** 与旁路观察、轻量 AI 一样是一次问一句、
拿回一行 JSON，没有工具、不落会话记录，走设置里 CoreAgent 那一格绑定的连接（未单绑时跟默认连接）。

分层：服务层。只碰 ``~/.frago`` 下的文件与 ``session/``，NEVER import ``cli/``。
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TITLES_FILE = Path.home() / ".frago" / "workbench_titles.json"
#: 历史集中存盘文件（保留兼容只读，且供旧单测 monkeypatch 定位临时目录）。
TITLES_FILE = _DEFAULT_TITLES_FILE

#: 每场会话备份目录下的标题文件名（与 ``observer-slots.json``、``workbench-marks.json`` 同目录）。
TITLE_FILENAME = "workbench-title.json"

#: CoreAgent 单轮生成标题的说明书文件名，在 ``~/.frago/coreagent/`` 下。
COREAGENT_DIR = Path.home() / ".frago" / "coreagent"
TITLE_INSTRUCTIONS = "session-title.md"

#: 备份根下可能放会话的家族目录名。
_FAMILY_DIRS = ("claude", "claude-misc", "opencode", "codex", "coreagent", "agy")

#: 名字最长多少字。清单标题本来就只露头一行，再长只是占盘。
MAX_TITLE_LEN = 120
#: 起序号名时，原标题最多留多少字。开口第一句当标题时常有一百字，后面再挂序号就看不见了。
BASE_LEN = 60

#: 生成标题时喂给模型的记录上限。
PROMPT_HUMAN_KEEP = 6
PROMPT_HUMAN_CLIP = 500
PROMPT_RECORD_KEEP = 30
PROMPT_REPLY_CLIP = 600

ASK_TIMEOUT_S = 60
PROCESS_TIMEOUT_S = ASK_TIMEOUT_S + 10

_NUMBERED = re.compile(r"^(?P<base>.*?)\s*#(?P<n>\d+)$")
_SURROUNDING_QUOTES = re.compile(r'^[\s"“”\'‘’《》「」『』`]+|[\s"“”\'‘’《》「」『』`。！？.!?\n\r]+$')
_lock = threading.Lock()

AskFn = Callable[[str], str]


class TitleGenerationUnavailable(LookupError):
    """这场会话还没有任何对话内容，生成不了标题。路由据此回 409。"""


class TitleGenerationFailed(RuntimeError):
    """调用 CoreAgent 生成标题没成功。路由据此回 503。"""


def _sessions_base_dir() -> Path:
    """会话备份根目录（``~/.frago/sessions``）。

    若单测把 :data:`TITLES_FILE` 指到了临时目录，跟着落在该临时目录的 ``sessions/`` 下，
    NEVER 让单测写进真机的 ``~/.frago/sessions``。
    """
    if TITLES_FILE != _DEFAULT_TITLES_FILE:
        return TITLES_FILE.parent / "sessions"
    from frago.session.storage import get_session_base_dir

    return get_session_base_dir()


def _resolve_session_dir(session_id: str, family: str | None = None) -> Path:
    """找到这场会话在 ``~/.frago/sessions/`` 下的目录。

    先看盘上哪个家族目录里已经有这场的备份目录；还没有时按家族名（或现判家族）定落点。
    """
    base = _sessions_base_dir()
    for folder in _FAMILY_DIRS:
        candidate = base / folder / session_id
        if candidate.is_dir():
            return candidate

    from frago.server.services.session_observer import _FAMILY_DIR
    from frago.session import record_reader

    resolved_family = family
    if not resolved_family:
        try:
            resolved_family = record_reader.detect_family(session_id)
        except Exception:  # noqa: BLE001 — 未知形状（如单测假编号）落回 claude 目录
            resolved_family = "claude-code"
    folder = _FAMILY_DIR.get(resolved_family, "claude")
    return base / folder / session_id


def title_file_for(session_id: str, family: str | None = None) -> Path:
    """这场会话存修改后标题的文件路径。"""
    return _resolve_session_dir(session_id.strip(), family) / TITLE_FILENAME


def _read_legacy_file() -> dict[str, str]:
    """读旧版集中式 ``workbench_titles.json``（若存在）。"""
    if not TITLES_FILE.exists():
        return {}
    try:
        data = json.loads(TITLES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("会话改名表读不动，当作没改过：%s", e)
        return {}
    titles = data.get("titles") if isinstance(data, dict) else None
    if not isinstance(titles, dict):
        return {}
    return {k: v for k, v in titles.items() if isinstance(k, str) and isinstance(v, str) and v}


def _read_session_title_file(path: Path) -> str | None:
    """读单个会话目录下的 ``workbench-title.json``。坏文件当没改过。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("会话标题文件读不动，当作没改过：%s（%s）", path, e)
        return None
    if not isinstance(data, dict):
        return None
    title = data.get("title")
    if isinstance(title, str) and title.strip():
        return " ".join(title.split())[:MAX_TITLE_LEN]
    return None


def _write_session_title_file(path: Path, title: str) -> None:
    """先写同目录临时文件再 ``replace``，断电不会留下半截 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"title": title}, indent=2, ensure_ascii=False)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".workbench-title-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_path, path)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def load() -> dict[str, str]:
    """全部改过的名字，``编号 → 名字``。

    会话备份目录 ``~/.frago/sessions/<家族>/<编号>/workbench-title.json`` 优先；
    早期写在 ``~/.frago/workbench_titles.json`` 里的做兜底。
    """
    titles = _read_legacy_file()
    base = _sessions_base_dir()
    if not base.is_dir():
        return titles
    for folder in _FAMILY_DIRS:
        family_dir = base / folder
        if not family_dir.is_dir():
            continue
        try:
            entries = list(family_dir.iterdir())
        except OSError:
            continue
        for entry in entries:
            title_path = entry / TITLE_FILENAME
            if not title_path.is_file():
                continue
            name = _read_session_title_file(title_path)
            if name:
                titles[entry.name] = name
    return titles


def get_title(session_id: str, *, family: str | None = None) -> str | None:
    """取单场会话修改过的标题；没改过返回 None。"""
    sid = session_id.strip()
    if not sid:
        return None
    base = _sessions_base_dir()
    for folder in _FAMILY_DIRS:
        candidate = base / folder / sid / TITLE_FILENAME
        if candidate.is_file():
            name = _read_session_title_file(candidate)
            if name:
                return name
    if family:
        name = _read_session_title_file(title_file_for(sid, family))
        if name:
            return name
    return _read_legacy_file().get(sid)


def set_title(session_id: str, title: str, *, family: str | None = None) -> str:
    """把修改后的标题存进该会话在 ``~/.frago/sessions`` 下的同目录数据文件里。"""
    sid = session_id.strip()
    name = " ".join(title.split())[:MAX_TITLE_LEN]
    if not sid or not name:
        raise ValueError("会话编号和名字都不能是空的")
    target = title_file_for(sid, family)
    with _lock:
        _write_session_title_file(target, name)
    return name


def numbered_pair(current: str) -> tuple[str, str]:
    """交接时两场各叫什么：``(原会话的名字, 新会话的名字)``。

    原会话已经带序号（它本身就是某次交接出来的）就不动它，新会话接着往下数；没带序号就
    从 1 开始，原会话改叫 ``#1``，新会话叫 ``#2``。
    """
    text = " ".join(current.split())
    matched = _NUMBERED.match(text)
    if matched and matched.group("base").strip():
        base, n = matched.group("base").strip(), int(matched.group("n"))
        return text, f"{base} #{n + 1}"
    base = text[:BASE_LEN].rstrip() or "会话"
    if len(text) > BASE_LEN:
        base += "…"
    return f"{base} #1", f"{base} #2"


# ── AI 生成标题（CoreAgent 单轮对话） ────────────────────────────────


def _ensure_instructions() -> Path:
    """确保 ``~/.frago/coreagent/session-title.md`` 在盘上；若无则先跑一次资源铺设。"""
    target = COREAGENT_DIR / TITLE_INSTRUCTIONS
    if target.exists():
        return target
    try:
        from frago.init.user_resource_seed import seed_user_resources

        seed_user_resources(COREAGENT_DIR.parent)
    except Exception:  # noqa: BLE001
        logger.debug("seed_user_resources failed when preparing %s", target, exc_info=True)
    if target.exists():
        return target
    # 兜底：若包内资源存在但尚未铺进 ~/.frago/coreagent/，直接拷过去
    packaged = Path(__file__).resolve().parents[2] / "resources" / "coreagent" / TITLE_INSTRUCTIONS
    if packaged.exists():
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(packaged.read_text(encoding="utf-8"), encoding="utf-8")
            return target
        except OSError:
            return packaged
    return target


_HTTP_JSON_ERR = re.compile(r"HTTP\s+(\d{3})\s+(\{[\s\S]*\})")


def _format_core_error(reply: dict[str, Any]) -> str:
    """将 frago-core 返回的错误（含上游 HTTP 原始 JSON）整理为可读说明。"""
    raw = str(reply.get("error") or "").strip()
    model = str(reply.get("model") or "").strip()
    if not raw:
        return f"LightAgent（{model}）没答上来" if model else "LightAgent 没答上来"

    matched = _HTTP_JSON_ERR.search(raw)
    if matched:
        status = matched.group(1)
        body_text = matched.group(2)
        upstream_msg = ""
        try:
            body = json.loads(body_text)
            if isinstance(body, dict):
                err_obj = body.get("error")
                if isinstance(err_obj, dict):
                    upstream_msg = str(
                        err_obj.get("message") or err_obj.get("type") or ""
                    ).strip()
                elif isinstance(err_obj, str):
                    upstream_msg = err_obj.strip()
                if not upstream_msg:
                    upstream_msg = str(
                        body.get("message") or body.get("detail") or ""
                    ).strip()
        except ValueError:
            upstream_msg = ""

        status_hint = {
            "400": "模型接口拒绝了请求参数（HTTP 400）",
            "401": "模型连接密钥无效或已过期（HTTP 401）",
            "403": "模型连接无权限访问该模型（HTTP 403）",
            "404": "模型或接口地址不存在（HTTP 404）",
            "429": "模型请求过于频繁或额度不足（HTTP 429）",
        }.get(status, f"模型接口返回异常（HTTP {status}）")

        prefix = f"{status_hint}，模型：{model}" if model else status_hint
        return f"{prefix} —— {upstream_msg}" if upstream_msg else prefix

    if model and model not in raw:
        return f"{raw}（模型：{model}）"
    return raw


def _ask_coreagent(prompt: str) -> str:
    """单轮调用 LightAgent（``--mode chat --as-role lightagent``），拿回模型回答正文。"""
    from frago.init.hook_binary import get_hook_binary_path
    from frago.server.services.subprocess_utils import get_utf8_env

    binary = get_hook_binary_path()
    if not Path(binary).exists():
        raise TitleGenerationFailed("frago-core 内核还没装好，跑一次 frago init 补上")
    instructions = _ensure_instructions()
    argv = [
        binary,
        "--mode",
        "chat",
        "--as-role",
        "lightagent",
        "--output-format",
        "json",
        "--timeout",
        str(ASK_TIMEOUT_S),
    ]
    if instructions.exists():
        argv += ["--instructions", instructions.name]
    argv += ["-p", "-"]

    try:
        proc = subprocess.run(  # noqa: S603 — 命令由本模块拼，无 shell
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=get_utf8_env(),
            timeout=PROCESS_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TitleGenerationFailed("LightAgent 生成标题超时没回来") from exc
    except OSError as exc:
        raise TitleGenerationFailed(f"起不来 frago-core：{exc}") from exc

    line = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.strip().startswith("{")), "")
    if not line:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise TitleGenerationFailed(detail[:200] or "frago-core 没有返回 JSON")
    try:
        reply = json.loads(line)
    except ValueError as exc:
        raise TitleGenerationFailed("frago-core 的输出不是约定的 JSON") from exc
    if not isinstance(reply, dict):
        raise TitleGenerationFailed("frago-core 的输出形状不对")
    if not reply.get("ok"):
        raise TitleGenerationFailed(_format_core_error(reply))
    return str(reply.get("text") or "")


def _parse_generated_title(raw: str) -> str:
    """从模型回答里取出标题文字。兼容 ``{"title": "..."}`` JSON 与直接回一行文字两种情况。"""
    text = (raw or "").strip()
    if not text:
        raise TitleGenerationFailed("LightAgent 返回了空标题")

    candidate = ""
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict) and isinstance(parsed.get("title"), str):
                candidate = parsed["title"]
        except (ValueError, TypeError):
            candidate = ""

    if not candidate:
        # 若模型没包 JSON，取第一个非空、非代码块围栏行
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("```"):
                continue
            candidate = stripped
            break

    cleaned = _SURROUNDING_QUOTES.sub("", " ".join(candidate.split()))[:MAX_TITLE_LEN].strip()
    if not cleaned:
        raise TitleGenerationFailed("LightAgent 没有给出可用的标题")
    return cleaned


def _build_title_prompt(session_id: str, family: str) -> str:
    """从会话记录与旁路槽位里摘出够起名的材料。一条可用内容都没有时抛 :class:`TitleGenerationUnavailable`。"""
    from frago.server.services import session_observer
    from frago.session import record_reader

    try:
        slots = session_observer.load_slots(
            session_observer.session_dir(session_id, family), session_id, family
        )
    except Exception:  # noqa: BLE001
        slots = {}

    head_records = list(record_reader.read_records(session_id, after=0, limit=80))
    tail_records = list(record_reader.read_records(session_id, limit=120, tail=True))
    seen_ids: set[str] = set()
    merged = []
    for rec in head_records + tail_records:
        if rec.id not in seen_ids:
            seen_ids.add(rec.id)
            merged.append(rec)

    humans: list[str] = []
    for rec in merged:
        if rec.agent_path:
            continue
        spoken = session_observer.human_text(rec)
        if spoken and spoken.strip():
            humans.append(" ".join(spoken.split())[:PROMPT_HUMAN_CLIP])

    last_agent = ""
    for rec in reversed(merged):
        if rec.kind == "agent.say" and not rec.agent_path:
            txt = rec.payload.get("text")
            if isinstance(txt, str) and txt.strip():
                last_agent = " ".join(txt.split())[:PROMPT_REPLY_CLIP]
                break

    shown = session_observer.showable(merged[-PROMPT_RECORD_KEEP:])
    anchor = (slots.get("anchor") or {}).get("text") if isinstance(slots.get("anchor"), dict) else None
    happened = [
        h.strip() for h in (slots.get("happened") or []) if isinstance(h, str) and h.strip()
    ][-6:]

    parts: list[str] = []
    if isinstance(anchor, str) and anchor.strip():
        parts.append(f"## 这场在做什么\n{anchor.strip()[:PROMPT_HUMAN_CLIP]}")
    if humans:
        selected_humans = humans[:2] + (humans[-max(0, PROMPT_HUMAN_KEEP - 2) :] if len(humans) > 2 else [])
        # 去重保序
        dedup_humans = list(dict.fromkeys(selected_humans))
        parts.append("## 人说的话\n" + "\n".join(f"- {h}" for h in dedup_humans))
    if happened:
        parts.append("## 已经发生的事\n" + "\n".join(f"- {h}" for h in happened))
    if last_agent:
        parts.append(f"## 最近一段 Agent 回复\n{last_agent}")
    elif shown:
        parts.append("## 会话记录摘录\n" + "\n".join(shown[-15:]))

    if not parts:
        raise TitleGenerationUnavailable(f"会话 {session_id} 还没有任何对话记录，生成不了标题")

    return "\n\n".join(parts)


def generate_title(session_id: str, *, ask: AskFn | None = None) -> str:
    """用 CoreAgent 单轮对话为这场会话生成标题，落盘到会话备份目录并返回。"""
    from frago.session import record_reader

    sid = session_id.strip()
    family = record_reader.detect_family(sid)
    prompt = _build_title_prompt(sid, family)
    ask_fn = ask or _ask_coreagent
    raw = ask_fn(prompt)
    title = _parse_generated_title(raw)
    return set_title(sid, title, family=family)
