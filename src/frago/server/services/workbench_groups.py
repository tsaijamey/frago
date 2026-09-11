"""会话分组：左栏按主题把会话收成一组一组，存在服务端的一份 JSON 里。

**为什么要分组。** 会话是在对同一类工作做持续、周期性的处理，一个主题前后会开很多场，
按时间摊平的一列里它们散在各天中间。分组把同一主题的那几场收到一起。

**文件里只有两部分，外加一个开关。**

- ``tags``：有哪些标签。每个标签记名字，和它是 AI 建的还是人建的。
- ``sessions``：每个标签下挂哪些会话编号。
- ``ai_tags_created``：AI 是不是已经从零拟过一套标签。从零拟只做这一回；此后标签只会在
  归组时按门槛零星添几个。

**一场会话只在一个组里。** 分组答的是"这场归哪个主题"，放进另一个组就是从原来那组搬
走。挂两处的话左栏同一场摆两遍，人会以为是两场。

**名单里存的是会话编号，NEVER 与会话清单核对。** Claude Code 会定期清理旧会话文件，
frago 的备份里还留着同一个编号的逐字节副本；会话在另一个目录里被恢复，文件会挪到别的
项目文件夹。这几种情况编号都不变，按编号记就都不受影响。清单里暂时没有那场，就是不显示，
编号照样留着。

**AI 分组走两步，标签尽量少。**

1. 拟标签——一个标签都没有、且从没拟过时才做。
2. 给未分组的会话归组——尽量放进现有标签；没有合适的才可以新建，而且同一批里至少
   :data:`MIN_NEW_TAG_SIZE` 场归到它才建，零零星星的新标签不建，那几场留在未分组。

**AI 只动还没分组的会话。** 人搬过的会话已经在某个组里，归组不会再碰；写盘之前人把那场
搬走了，以人为准。

**所有写入都经过这一个模块、这一把锁。** 页面上人在搬、后台 AI 在分，两边读改写同一份
文件，不上锁的话后写的一方会把先写的整份盖掉。

**问模型一律交给 ``frago-core ask --role lightagent``。** 分组是纯文字判断，不读文件、
不跑命令，用不着一个会动手的 agent。最早这里是在 tmux 里整场拉起一个 Claude Code 会话
再喂提示词：首趟 700 多场要起八场，每场都等 CLI 启动、走主力模型的额度，而且每场都作为
一场认不出出处的 worker 留在左栏里。现在是一次问一句、拿回一行，用轻量 ai 那一格绑的
连接（没绑就退到当前连接）。说明书在 ``~/.frago/hook/`` 下，随包发、人可以改。

分层：服务层。只碰 ``~/.frago`` 下的一个 JSON 文件，NEVER import ``cli/``。
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

GROUPS_FILE = Path.home() / ".frago" / "workbench_groups.json"

#: frago-core 读说明书的目录。
HOOK_DIR = Path.home() / ".frago" / "hook"

#: 两步各一份说明书。
TAGS_INSTRUCTIONS = "group-tags.md"
ASSIGN_INSTRUCTIONS = "group-assign.md"

#: 标签名最长多少字。左栏分区标题是一行，再长就只能截断，截断后两个标签可能看起来一样。
MAX_TAG_NAME = 40

#: 会话编号最长多少字符，与置顶名单同一道线。
MAX_ID_LEN = 128

#: 拟标签那一轮最多给模型看多少条标题。够看出有哪些主题，又不至于让一轮问话过长。
TAG_SAMPLE_LIMIT = 500

#: 归组那一轮一批给模型多少场。轻量 ai 一次回的字有上限，一场约十几个 token，六十场
#: 留足余量；批太大回的 JSON 会被截断，整批作废。
ASSIGN_BATCH = 60

#: 归组时新建一个标签的门槛：同一批里至少这么多场归到它。标签越少越好，一两场撑不起
#: 一个组，它们留在未分组比多一个分区强。
MIN_NEW_TAG_SIZE = 3

#: 标题在问话里最多留多少字。
TITLE_CLIP = 60

ASK_TIMEOUT_MS = 60_000
ASK_MAX_TOKENS = 3_000
#: 等 frago-core 的墙钟上限，比它自己的期限多留几秒给进程起落。
PROCESS_TIMEOUT_S = ASK_TIMEOUT_MS / 1000 + 10

_LOCK = threading.Lock()

_UUID_LIKE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


# ── 存盘 ────────────────────────────────────────────────────────────
def _empty() -> dict[str, Any]:
    return {"tags": [], "sessions": {}, "ai_tags_created": False}


def _normalize(data: Any) -> dict[str, Any]:
    """把盘上读到的东西洗成预期的形状。认不出的部分丢掉，NEVER 抛。

    同一场会话出现在两个组里时，留排在前面的那个标签——一场只在一个组里。
    """
    if not isinstance(data, dict):
        return _empty()
    tags: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for item in data.get("tags") or []:
        if not isinstance(item, dict):
            continue
        tag_id = item.get("id")
        name = item.get("name")
        if not isinstance(tag_id, str) or not tag_id or tag_id in seen_ids:
            continue
        if not isinstance(name, str) or not name.strip():
            continue
        source = item.get("source") if item.get("source") in ("ai", "human") else "human"
        seen_ids.add(tag_id)
        tags.append({"id": tag_id, "name": name.strip(), "source": source})

    raw_sessions = data.get("sessions") if isinstance(data.get("sessions"), dict) else {}
    placed: set[str] = set()
    sessions: dict[str, list[str]] = {}
    for tag in tags:
        members: list[str] = []
        for sid in raw_sessions.get(tag["id"]) or []:
            if isinstance(sid, str) and sid.strip() and sid not in placed:
                placed.add(sid)
                members.append(sid)
        sessions[tag["id"]] = members

    return {
        "tags": tags,
        "sessions": sessions,
        "ai_tags_created": bool(data.get("ai_tags_created")),
    }


def _read() -> dict[str, Any]:
    """读盘。读不动一律当没分过组——分组坏了不该连累人看会话清单。"""
    if not GROUPS_FILE.exists():
        return _empty()
    try:
        data = json.loads(GROUPS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("会话分组读不动，当作没分过组：%s", e)
        return _empty()
    return _normalize(data)


def _write(state: dict[str, Any]) -> None:
    """整份落盘：先写同目录临时文件再 ``replace``，断电也不会留下半截 JSON。"""
    GROUPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2, ensure_ascii=False)
    fd, tmp_path = tempfile.mkstemp(dir=str(GROUPS_FILE.parent), prefix=".workbench_groups-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_path, GROUPS_FILE)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _find_tag_by_name(state: dict[str, Any], name: str) -> dict[str, str] | None:
    key = name.strip().casefold()
    for tag in state["tags"]:
        if tag["name"].casefold() == key:
            return tag
    return None


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ValueError("标签名不能是空的")
    if len(cleaned) > MAX_TAG_NAME:
        raise ValueError(f"标签名太长了（超过 {MAX_TAG_NAME} 字）")
    return cleaned


def _add_tag(state: dict[str, Any], name: str, source: str) -> dict[str, str]:
    tag = {"id": f"tag_{uuid.uuid4().hex[:10]}", "name": name, "source": source}
    state["tags"].append(tag)
    state["sessions"][tag["id"]] = []
    return tag


def _grouped_ids(state: dict[str, Any]) -> set[str]:
    return {sid for members in state["sessions"].values() for sid in members}


def _place(state: dict[str, Any], session_id: str, tag_id: str | None) -> None:
    for members in state["sessions"].values():
        if session_id in members:
            members.remove(session_id)
    if tag_id is not None:
        state["sessions"][tag_id].append(session_id)


# ── 人的操作 ────────────────────────────────────────────────────────
def load() -> dict[str, Any]:
    """整份分组：有哪些标签、每个标签下有哪些会话、AI 拟没拟过标签。"""
    with _LOCK:
        return _read()


def create_tag(name: str) -> dict[str, Any]:
    """人建一个标签。重名（不分大小写）不受理——两个同名分区人分不清该往哪个里放。"""
    cleaned = _clean_name(name)
    with _LOCK:
        state = _read()
        if _find_tag_by_name(state, cleaned):
            raise FileExistsError(f"已经有叫「{cleaned}」的标签了")
        _add_tag(state, cleaned, "human")
        _write(state)
        return state


def delete_tag(tag_id: str) -> dict[str, Any]:
    """删掉一个标签，里面的会话回到未分组。本来就没有这个标签也算成功。

    会话本身一个字都不动：删的只是"这几场归一组"这件事。
    """
    with _LOCK:
        state = _read()
        before = len(state["tags"])
        state["tags"] = [t for t in state["tags"] if t["id"] != tag_id]
        state["sessions"].pop(tag_id, None)
        if len(state["tags"]) != before:
            _write(state)
        return state


def assign(session_id: str, tag_id: str | None) -> dict[str, Any]:
    """把这场会话放进某个组；``tag_id`` 为 None 就是移出分组。

    放进另一个组即从原来那组搬走——一场只在一个组里。
    """
    sid = session_id.strip()
    if not sid:
        raise ValueError("会话编号不能是空的")
    if len(sid) > MAX_ID_LEN:
        raise ValueError(f"会话编号太长了（超过 {MAX_ID_LEN} 字符）")
    with _LOCK:
        state = _read()
        if tag_id is not None and tag_id not in state["sessions"]:
            raise KeyError(tag_id)
        _place(state, sid, tag_id)
        _write(state)
        return state


# ── AI 分组 ─────────────────────────────────────────────────────────
class CardLike(Protocol):
    session_id: str
    title: str
    directory: str
    origin: str


@dataclass
class AiJob:
    """后台那一趟 AI 分组走到哪了。页面轮询它来报进度。"""

    running: bool = False
    phase: str | None = None
    """``tags`` 在拟标签 / ``assign`` 在归组。"""
    done: int = 0
    total: int = 0
    assigned: int = 0
    created_tags: int = 0
    error: str | None = None
    finished_at: float | None = None


_JOB = AiJob()
_JOB_LOCK = threading.Lock()


def job_state() -> dict[str, Any]:
    with _JOB_LOCK:
        return asdict(_JOB)


def _has_content_title(card: CardLike) -> bool:
    """标题里有没有能拿来判主题的东西。只剩一串会话编号的，模型也判不出。"""
    title = (card.title or "").strip()
    if not title or title == card.session_id:
        return False
    return not _UUID_LIKE.match(title)


def candidates(cards: Iterable[CardLike], state: dict[str, Any]) -> list[CardLike]:
    """这一趟 AI 该分哪几场：还没分组的、人开的主会话，且标题里有内容。

    worker 不单独分：它们在左栏折在派活的那场下面，跟着那场走。
    """
    grouped = _grouped_ids(state)
    return [
        card
        for card in cards
        if card.origin != "worker"
        and card.session_id not in grouped
        and _has_content_title(card)
    ]


#: 问一次模型：``(说明书文件名, 问话) → 回答原文``。没答上来就抛 :class:`AskFailed`。
AskFn = Callable[[str, str], str | None]


class AskFailed(RuntimeError):
    """这一次没问到。消息就是原因，原样写进进度给人看。"""


_ask_support: dict[str, tuple[float, int, bool]] = {}


def _supports_ask(binary: str) -> bool:
    """装着的 frago-core 有没有 ask 入口。

    NEVER 省掉这一步：旧版遇到不认识的第一个参数会进入带工具的完整 agent 循环，对它调
    ``frago-core ask`` 等于在这台机器上起了一个会动手的 agent。按文件大小和修改时刻记住
    结论，换了二进制就重查。
    """
    try:
        st = os.stat(binary)
    except OSError:
        return False
    cached = _ask_support.get(binary)
    if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
        return cached[2]
    try:
        out = subprocess.run([binary, "--help"], capture_output=True, text=True, timeout=10).stdout
        ok = "frago-core ask" in out
    except (OSError, subprocess.SubprocessError):
        ok = False
    _ask_support[binary] = (st.st_mtime, st.st_size, ok)
    return ok


def _ensure_instructions(name: str) -> None:
    """说明书还没铺到 ``~/.frago/hook/`` 就先铺一次。已有的一律不动——那是人改过的版本。"""
    if (HOOK_DIR / name).exists():
        return
    from frago.init.user_resource_seed import seed_user_resources

    seed_user_resources(HOOK_DIR.parent)


def _ask_model(instructions: str, prompt: str) -> str:
    """问轻量 ai 一次，拿回它的原话。没问到就抛 :class:`AskFailed`，消息是原因。"""
    from frago.init.hook_binary import get_hook_binary_path

    binary = get_hook_binary_path()
    if not _supports_ask(binary):
        raise AskFailed("装着的 frago-core 还没有 ask 入口，AI 分组用不了；升级 frago 后恢复")
    _ensure_instructions(instructions)
    argv = [
        binary,
        "ask",
        "--role",
        "lightagent",
        "--instructions",
        instructions,
        "--timeout-ms",
        str(ASK_TIMEOUT_MS),
        "--max-tokens",
        str(ASK_MAX_TOKENS),
    ]
    try:
        proc = subprocess.run(
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=PROCESS_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise AskFailed("轻量 ai 超时没回来") from exc
    except OSError as exc:
        raise AskFailed(f"起不来 frago-core：{exc}") from exc
    line = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.strip()), "")
    try:
        reply = json.loads(line)
    except ValueError as exc:
        raise AskFailed("frago-core 的输出不是约定的 JSON") from exc
    if not isinstance(reply, dict):
        raise AskFailed("frago-core 的输出形状不对")
    if not reply.get("ok"):
        raise AskFailed(str(reply.get("error") or "轻量 ai 没答上来"))
    return str(reply.get("text") or "")


def _parse_json(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _clip(text: str) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= TITLE_CLIP else flat[: TITLE_CLIP - 1] + "…"


def _dir_tail(directory: str) -> str:
    return "/".join([p for p in (directory or "").split("/") if p][-2:])


def _draft_tags(pending: list[CardLike], ask: AskFn) -> list[str] | None:
    """从零拟一套标签。问话里只有数据，规矩在说明书 ``group-tags.md`` 里。"""
    prompt = "\n".join(["## 会话标题", *(_clip(c.title) for c in pending[:TAG_SAMPLE_LIMIT])])
    parsed = _parse_json(ask(TAGS_INSTRUCTIONS, prompt))
    if parsed is None or not isinstance(parsed.get("tags"), list):
        return None
    names: list[str] = []
    for item in parsed["tags"]:
        if not isinstance(item, str):
            continue
        try:
            names.append(_clean_name(item))
        except ValueError:
            continue
    return names


def _assign_batch(
    batch: list[CardLike], tag_names: list[str], ask: AskFn
) -> tuple[dict[str, str], list[str]] | None:
    """一批会话 → ``({会话编号: 标签名}, 要新建的标签名)``。回答用不了回 None。

    新标签在这里就过门槛：模型提议的新名字，这一批里归到它的不够 :data:`MIN_NEW_TAG_SIZE`
    场就不建，归到它的那几场也不放。值既不是现有标签、也不是过了门槛的新名字的，一律不放。
    """
    prompt = "\n".join(
        [
            "## 可用的标签",
            *([f"- {n}" for n in tag_names] or ["（还没有）"]),
            "",
            "## 会话（序号. 标题 ｜ 工作目录）",
            *(f"{i}. {_clip(c.title)} ｜ {_dir_tail(c.directory)}" for i, c in enumerate(batch, start=1)),
        ]
    )
    parsed = _parse_json(ask(ASSIGN_INSTRUCTIONS, prompt))
    if parsed is None or not isinstance(parsed.get("assign"), dict):
        return None

    existing = {n.casefold() for n in tag_names}
    proposed: dict[str, str] = {}
    for item in parsed.get("new_tags") or []:
        if not isinstance(item, str):
            continue
        try:
            name = _clean_name(item)
        except ValueError:
            continue
        if name.casefold() not in existing:
            proposed[name.casefold()] = name

    raw: dict[str, str] = {}
    for key, value in parsed["assign"].items():
        if not isinstance(value, str) or not str(key).strip().isdigit():
            continue
        index = int(str(key).strip()) - 1
        if 0 <= index < len(batch):
            raw[batch[index].session_id] = value.strip()

    usage = Counter(v.casefold() for v in raw.values() if v.casefold() in proposed)
    kept = {key for key, n in usage.items() if n >= MIN_NEW_TAG_SIZE}
    decisions = {
        sid: value
        for sid, value in raw.items()
        if value.casefold() in existing or value.casefold() in kept
    }
    return decisions, [proposed[key] for key in kept]


def _update_job(**changes: Any) -> None:
    with _JOB_LOCK:
        for key, value in changes.items():
            setattr(_JOB, key, value)


def _bump_job(**deltas: int) -> None:
    with _JOB_LOCK:
        for key, value in deltas.items():
            setattr(_JOB, key, getattr(_JOB, key) + value)


def run_ai_grouping(cards: list[CardLike], ask: AskFn | None = None) -> None:
    """跑一整趟 AI 分组。在后台线程里调用；进度写进 :func:`job_state`。两步见模块说明。"""
    ask = ask or _ask_model
    problems: list[str] = []
    try:
        with _LOCK:
            state = _read()
        pending = candidates(cards, state)
        _update_job(total=len(pending))
        if not pending:
            return

        # 1. 从零拟标签：一个标签都没有、且从没拟过。
        if not state["tags"] and not state["ai_tags_created"]:
            _update_job(phase="tags")
            try:
                names = _draft_tags(pending, ask)
            except AskFailed as exc:
                _update_job(error=f"拟标签那一轮没跑成：{exc}")
                return
            if names is None:
                _update_job(error="拟标签那一轮没跑成，模型没有给出可用的标签")
                return
            with _LOCK:
                state = _read()
                created = 0
                for name in names:
                    if not _find_tag_by_name(state, name):
                        _add_tag(state, name, "ai")
                        created += 1
                state["ai_tags_created"] = True
                _write(state)
            _bump_job(created_tags=created)

        # 2. 给未分组的会话归组。
        _update_job(phase="assign")
        tag_names = [t["name"] for t in state["tags"]]
        failed_batches = 0
        last_reason: str | None = None
        for start in range(0, len(pending), ASSIGN_BATCH):
            batch = pending[start : start + ASSIGN_BATCH]
            try:
                outcome = _assign_batch(batch, tag_names, ask)
            except AskFailed as exc:
                outcome, last_reason = None, str(exc)
            if outcome is None:
                failed_batches += 1
            else:
                decisions, new_names = outcome
                with _LOCK:
                    state = _read()
                    created = 0
                    for name in new_names:
                        if not _find_tag_by_name(state, name):
                            _add_tag(state, name, "ai")
                            created += 1
                    grouped = _grouped_ids(state)
                    placed = 0
                    for sid, name in decisions.items():
                        tag = _find_tag_by_name(state, name)
                        if tag is None or sid in grouped:
                            continue
                        _place(state, sid, tag["id"])
                        placed += 1
                    if placed or created:
                        _write(state)
                # 这一批新建的标签，后面几批也能用。
                tag_names = [t["name"] for t in state["tags"]]
                _bump_job(assigned=placed, created_tags=created)
            _update_job(done=min(start + len(batch), len(pending)))
        if failed_batches:
            reason = f"（{last_reason}）" if last_reason else ""
            problems.append(f"{failed_batches} 批没跑成{reason}，那几批的会话还在未分组里")
    except Exception as exc:  # noqa: BLE001 - 后台线程里的异常 NEVER 吞掉不报
        logger.exception("AI 分组中途出错")
        problems.append(f"中途出错：{exc}")
    finally:
        if problems:
            _update_job(error="；".join(problems))
        _update_job(running=False, phase=None, finished_at=time.time())


def start_ai_grouping(cards: list[CardLike], ask: AskFn | None = None) -> dict[str, Any]:
    """在后台起一趟 AI 分组，立刻返回进度。已经在跑就不再起第二趟。"""
    global _JOB
    with _JOB_LOCK:
        if _JOB.running:
            return asdict(_JOB)
        _JOB = AiJob(running=True)
    threading.Thread(
        target=run_ai_grouping, args=(cards, ask), name="workbench-ai-grouping", daemon=True
    ).start()
    return job_state()
