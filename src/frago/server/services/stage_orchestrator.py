"""虚拟桌面（Agent OS）旁路女声解说与舞台会话服务（Stage Orchestrator）。

现行架构：
1. 虚拟桌面由专职员工 `desktop-operator`（CoCo）+ `SpeechSummarizerDaemon` 驱动；
2. `SpeechSummarizerDaemon` 实时监听用户语音 ASR 与 `desktop-operator` 会话响应，通过 `LightAgent`
   提炼第一人称口语总结后调用 `voice.resolve_emotional_voice(spoken)`，中文默认使用女声
   `zh-CN-XiaoxiaoNeural`，英文默认使用女声 `en-US-AvaMultilingualNeural`；
3. 旧版三角色自动劫持链路（`is_stage_session` -> `orchestrate_stage_session`）、共享账本自动创建与
   `PresenterDaemon` 后台英文男声已退役禁用，仅保留清理接口兼容。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 历史舞台技能标记常量（仅作清理与兼容识别保留，不再触发自动劫持）
STAGE_SKILL_NAME = "how-frago-agent-runs-an-agent-os"
STAGE_SKILL_MARKER = f'name="{STAGE_SKILL_NAME}"'

#: 历史硬性指令头部标记（供 clean_user_requirement 剥离存量尾缀）
DIRECTIVE_HEADER = "【系统硬性编排指令 · 你是虚拟桌面舞台主操作员 (Operator) MUST】"

#: 舞台协同根目录（模块级常量，conftest 的 _redirect_protected_paths 会自动做单测重定向）
STAGE_DATA_ROOT: Path = Path.home() / ".frago" / "data" / "agent_os"

#: 默认女声配音音色（与 desktop.voice 及内置技能/手册全面对齐，中文晓晓女声 / 英文 Ava 女声）
DEFAULT_ZH_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_EN_VOICE = "en-US-AvaMultilingualNeural"
DEFAULT_VOICE = DEFAULT_EN_VOICE

#: 主持人空档垫音阈值（秒）
IDLE_PAD_INTERVAL_S = 18.0
MAX_IDLE_PADS_PER_TURN = 1

#: 已退役主持人守护线程映射（仅保留供 reset_stage_sessions / cleanup_presenter 安全清理兼容）
_presenters: dict[str, PresenterDaemon] = {}
_presenters_lock = threading.Lock()


def is_stage_session(skills: list[str] | None = None, prompt: str = "") -> bool:
    """旧三角色舞台自动劫持判定已退役，始终返回 False（虚拟桌面统一走 desktop-operator + SpeechSummarizerDaemon）。"""
    return False


def clean_user_requirement(raw_text: str) -> str:
    """剥离系统注入的 <must-use-skill>、<system-reminder> 与硬编排指令尾缀，提取干净的用户需求。"""
    if not raw_text:
        return ""
    text = re.sub(r"<must-use-skill[\s\S]*?</must-use-skill>\s*", "", raw_text)
    text = re.sub(r"<system-reminder[\s\S]*?</system-reminder>\s*", "", text)
    if DIRECTIVE_HEADER in text:
        idx = text.find(DIRECTIVE_HEADER)
        # 连同前面的分隔线一起剥离
        prefix = text[:idx].rstrip()
        if prefix.endswith("---"):
            prefix = prefix[:-3].rstrip()
        text = prefix
    return text.strip()


def extract_ascii_keywords(text: str, max_len: int = 48) -> str:
    """从混合文本中提取英文标识符（如配方名、命令名、模块名）供纯英文语音引用。"""
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_.\-/]{1,35}", text or "")
    # 过滤常见无意义标签词
    stop = {
        "must",
        "use",
        "skill",
        "name",
        "path",
        "how",
        "frago",
        "agent",
        "runs",
        "an",
        "os",
        "md",
        "Users",
    }
    filtered = [t for t in tokens if t not in stop and not t.startswith("http")]
    if not filtered:
        return "this task"
    joined = " ".join(dict.fromkeys(filtered))
    return joined[:max_len].strip() or "this task"


def enforce_presenter_perspective(text: str, speaker: str = "presenter") -> str:
    """统一把关当前发言人视角：过滤并改写操作员自称或旁观者转述措辞，保持第一人称连贯语境。"""
    if not text:
        return ""
    if speaker != "presenter":
        return text
    # 剥离或改写操作员视角自报家门与第三人称转述措辞
    rewrites = [
        (r"\b(?:hi|hello)[,\s]+this is (?:your |the )?operator speaking\.?\s*", ""),
        (r"\bthis is (?:your |the )?operator speaking\.?\s*", ""),
        (r"\bnow (?:the |your |our )?operator is speaking\b", "I am walking you through this live"),
        (r"\b(?:the |your |our )?operator is speaking\b", "I am speaking"),
        (r"\bour operator and advisor are\b", "we are"),
        (r"\bour operator has\b", "I have"),
        (r"\bthe operator has\b", "I have"),
        (r"\bour operator is\b", "I am"),
        (r"\bthe operator is\b", "I am"),
        (r"\bwhile our operator prepares\b", "while I prepare"),
        (r"\bwhile the operator prepares\b", "while I prepare"),
        (r"\b(?:our|the|your) operator\b", "I"),
    ]
    out = text
    for pattern, repl in rewrites:
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", out).strip()


def sanitize_english_for_tts(
    text: str,
    fallback: str = "Moving forward with the next step on stage.",
    speaker: str = "presenter",
) -> str:
    """确保送入 frago desktop say 的文本 100% 为纯 ASCII 英文且符合当前发言人视角。"""
    if not text:
        return fallback
    text = enforce_presenter_perspective(text, speaker=speaker)
    # 替换常见全角标点为 ASCII 标点
    replacements = {
        "：": ": ",
        "；": "; ",
        "，": ", ",
        "。": ". ",
        "！": "! ",
        "？": "? ",
        "（": " (",
        "）": ") ",
        "【": " [",
        "】": "] ",
        "「": ' "',
        "」": '" ',
        "『": ' "',
        "』": '" ',
        "、": ", ",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "—": " - ",
        "…": "...",
        "·": " ",
        "→": " to ",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    # 剔除一切非 ASCII 可打印字符（包含所有中日韩文字与 emoji）
    ascii_only = re.sub(r"[^\x20-\x7E]+", " ", text)
    ascii_only = re.sub(r"\s+", " ", ascii_only).strip(" ,;:-")
    # 至少保留 2 个两字母以上的英文词才算有效句子
    if len(re.findall(r"[A-Za-z]{2,}", ascii_only)) < 2:
        return fallback
    if ascii_only[-1] not in ".!?":
        ascii_only += "."
    return ascii_only


def translate_ledger_item_to_english(section: str, line: str) -> str:
    """将 ledger.md 中的一条中文/混合进展转写为自然、纯正的英文主持解说词。"""
    raw = re.sub(r"^[-*]\s*", "", line.strip())
    if not raw or raw.startswith("（等待") or "舞台已由服务端硬性编排就绪" in raw:
        return ""

    kw = extract_ascii_keywords(raw, max_len=45)

    # 如果整行本身已经是英文为主（无 CJK 字符），直接清理标点返回
    if not re.search(r"[⺀-鿿　-〿＀-￯]", raw):
        return sanitize_english_for_tts(raw)

    # 根据常见账本语义映射为地道英文第一人称解说（严禁出现 the operator / our operator 旁观转述）
    if "核实" in raw or "存在" in raw or "找到" in raw:
        return sanitize_english_for_tts(
            f"I have verified {kw} on the local machine and confirmed its source files and runtime records."
        )
    if "第一幕" in raw or "1/" in raw or "recipe info" in raw:
        return sanitize_english_for_tts(
            f"Act one is now live on the terminal, running the inspection command for {kw} so we can see its real parameters."
        )
    if "第二幕" in raw or "2/" in raw or "浏览器" in raw or "browser" in raw or "页面" in raw:
        return sanitize_english_for_tts(
            f"Moving to the browser window, I am opening the live interactive interface for {kw} to inspect the real data."
        )
    if "第三幕" in raw or "3/" in raw or "讲稿" in raw or "slide" in raw or "算法" in raw or "层" in raw:
        return sanitize_english_for_tts(
            f"Now projecting the full-screen slide deck to break down the core architecture and decision logic of {kw}."
        )
    if "第四幕" in raw or "第五幕" in raw or "回测" in raw or "收尾" in raw or "总结" in raw:
        return sanitize_english_for_tts(
            f"Wrapping up with the backtest metrics and key takeaways for {kw} on stage."
        )
    if "拍板" in raw:
        return sanitize_english_for_tts(
            f"I have locked in the execution plan for {kw}: combining terminal output, live browser view, and visual slides."
        )
    if "参谋" in section or "挑刺" in section or "参谋" in raw or "建议" in raw or "看点" in raw:
        return sanitize_english_for_tts(
            f"For {kw}, I will focus on the real runtime data and verify each stage live on screen."
        )
    if "追加需求" in raw:
        return sanitize_english_for_tts(
            f"New audience request logged into the ledger regarding {kw}. I am adjusting the walkthrough now."
        )

    return sanitize_english_for_tts(
        f"Stage update on {kw}: I have completed this step and am advancing to the next view."
    )


def _is_test_isolated() -> bool:
    """单测环境下默认隔离真实 8770 舞台进程与语音推送（除非显式声明 FRAGO_TEST_REAL_STAGE）。"""
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) and not bool(
        os.environ.get("FRAGO_TEST_REAL_STAGE")
    )


def _is_real_fn(fn: Any, expected_module: str) -> bool:
    """判断函数是否仍为未被 monkeypatch 替换的真实实现。"""
    return getattr(fn, "__module__", None) == expected_module


def ensure_stage_up() -> dict[str, Any]:
    """确保虚拟桌面舞台在线（8770 broker 运行态）。"""
    if _is_test_isolated():
        return {"ok": True, "status": "running", "mock": True}

    from frago.desktop import registry, stage

    rec = registry.read_instance(registry.DEFAULT_ID)
    if rec and rec.get("status") == "running" and registry._port_alive(rec.get("port")):
        return rec
    try:
        return stage.up({"open": False})
    except Exception as exc:
        logger.warning("stage_orchestrator: stage.up failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def init_collaboration_dir(session_id: str, requirement: str) -> tuple[Path, Path]:
    """初始化符合 must-data-dir 规范的两层协同目录与共享协商账本 ledger.md。"""
    date_str = time.strftime("%Y%m%d")
    short_sid = session_id.replace("core_", "")[:8]
    stage_dir = STAGE_DATA_ROOT / f"{date_str}-stage-{short_sid}"
    stage_dir.mkdir(parents=True, exist_ok=True)

    # 记录会话归属
    sid_file = stage_dir / "session-id.yaml"
    try:
        if not sid_file.exists():
            sid_file.write_text(f"sid:\n  - {session_id}\n", encoding="utf-8")
        else:
            cur = sid_file.read_text(encoding="utf-8")
            if session_id not in cur:
                sid_file.write_text(f"{cur.strip()}\n  - {session_id}\n", encoding="utf-8")
    except OSError:
        pass

    ledger_path = stage_dir / "ledger.md"
    clean_req = clean_user_requirement(requirement) or "未指定需求"
    if not ledger_path.exists():
        ledger_path.write_text(
            f"""# 任务与追加需求
- 初始需求：{clean_req}

# 参谋挑刺与备选方案
（等待参谋推演或主操作员提问）

# 主操拍板与当前动作
- 状态：舞台已由服务端硬性编排就绪，主操作员接手推进

# 阶段进展与产物
- 工作目录：`{stage_dir}`
""",
            encoding="utf-8",
        )
    return stage_dir, ledger_path


def run_initial_advisor_pass(ledger_path: Path, requirement: str) -> None:
    """参谋（Advisor）首轮自动推演：分析需求重点与展示脉络，写入 ledger.md 的参谋栏。"""
    clean_req = clean_user_requirement(requirement) or "未指定需求"
    kw = extract_ascii_keywords(clean_req, max_len=40)
    now_str = time.strftime("%H:%M:%S")
    advisor_note = (
        f"- 参谋首轮推演（{now_str}）：针对「{clean_req[:50]}」（核心对象 `{kw}`），"
        "建议分三幕呈现：① 在终端执行真实查询展示输入输出契约；"
        "② 在浏览器打开真实运行页面核对落盘数据；"
        "③ 用全屏讲稿拆解核心设计逻辑与边界条件，避免只念源码。"
    )
    try:
        if not ledger_path.is_file():
            return
        content = ledger_path.read_text(encoding="utf-8")
        if "参谋首轮推演" in content:
            return
        if "（等待参谋推演或主操作员提问）" in content:
            content = content.replace("（等待参谋推演或主操作员提问）", advisor_note)
        elif "# 参谋挑刺与备选方案" in content:
            content = content.replace(
                "# 参谋挑刺与备选方案\n", f"# 参谋挑刺与备选方案\n{advisor_note}\n"
            )
        ledger_path.write_text(content, encoding="utf-8")
    except OSError:
        pass


class PresenterDaemon:
    """驻场主持人守护线程：
    1. 盯导演面板（#human-input）做秒级纯英文插播应答；
    2. 盯共享账本（ledger.md）把参谋与主操作员的新增进展实时转成纯英文语音排队播报；
    3. 盯屏幕与语音空档，在主操作员台下准备期间用静默读屏（--observe）垫音防冷场。
    """

    def __init__(self, session_id: str, ledger_path: Path, topic: str):
        self.session_id = session_id
        self.ledger_path = ledger_path
        self.clean_topic = clean_user_requirement(topic) or "任务执行"
        self.en_topic = extract_ascii_keywords(self.clean_topic, max_len=40)
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_seq = 0
        self.acknowledged_prompts: set[str] = {self.clean_topic}
        self.narrated_ledger_lines: set[str] = {
            f"- 初始需求：{self.clean_topic}",
            "（等待参谋推演或主操作员提问）",
            "- 状态：舞台已由服务端硬性编排就绪，主操作员接手推进",
            f"- 工作目录：`{self.ledger_path.parent}`",
        }
        self.last_voice_time = time.time()
        self.idle_pad_index = 0
        self.idle_pad_count = 0
        self.operator_ready = False
        self.saw_operator_busy = False
        self.presenter_straps: set[str] = set()
        self.baseline_acts: dict[str, int] = self._snapshot_acts()

    def start(self) -> None:
        logger.debug(
            "stage_orchestrator: PresenterDaemon is retired; skipping background thread for session=%s",
            self.session_id,
        )
        return

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        logger.info("stage_orchestrator: presenter stopped for session=%s", self.session_id)

    def _loop(self) -> None:
        # 1. 首帧开场字条与纯英文开场白（确保第 0 秒就有声音，且 100% 过纯英文校验与第一人称视角把关）
        opening_en = sanitize_english_for_tts(
            f"Welcome to the live stage. I have received your request on {self.en_topic}, "
            "and I am now preparing the live walkthrough on this desktop.",
            speaker="presenter",
        )
        self._say_interject(
            opening_en,
            zh_Fallback_or_strap=f"接活：{self.clean_topic[:42]}",
        )

        # 2. 触发参谋首轮推演落账（让准备第一幕期间，主持人有参谋结论可播报）
        run_initial_advisor_pass(self.ledger_path, self.clean_topic)

        while not self.stop_event.is_set():
            try:
                self._check_new_user_messages()
                self._check_ledger_updates()
                self._check_idle_pad()
            except Exception as e:
                logger.debug("presenter loop error: %s", e)
            self.stop_event.wait(2.0)

    def _check_new_user_messages(self) -> None:
        """从工作台统一记录模块拉取新增的用户输入，做第一秒内的纯英文插播确认。"""
        from frago.session import record_reader

        try:
            records = record_reader.read_records(
                self.session_id, after=self.last_seq + 1, limit=50
            )
        except Exception:
            return

        if not records:
            return

        for rec in records:
            seq = getattr(rec, "seq", None)
            if isinstance(seq, int) and seq > self.last_seq:
                self.last_seq = seq
            if getattr(rec, "kind", None) != "user.say":
                continue
            payload = getattr(rec, "payload", {}) or {}
            if payload.get("is_tool_result"):
                continue
            raw_text = (payload.get("text") or "").strip()
            clean_text = clean_user_requirement(raw_text)
            if not clean_text or clean_text in self.acknowledged_prompts:
                continue

            self.acknowledged_prompts.add(clean_text)
            en_kw = extract_ascii_keywords(clean_text, max_len=32)
            zh_summary = clean_text[:28].replace("\n", " ")
            logger.info("presenter acknowledged new prompt: %s", zh_summary)
            phrase_en = sanitize_english_for_tts(
                f"Received, passing it on: {en_kw}. I am updating the walkthrough on stage now.",
                speaker="presenter",
            )
            self._say_interject(
                phrase_en,
                zh_Fallback_or_strap=f"收到，已转达：{zh_summary}",
            )
            self._record_to_ledger(clean_text)
            # 新一轮观众追问到来：重置单轮过渡垫音计数，并以当前幕脚本为新基线
            self.baseline_acts = self._snapshot_acts()
            self.operator_ready = False
            self.idle_pad_count = 0
            self.saw_operator_busy = False

    def _snapshot_acts(self) -> dict[str, int]:
        """读取协同目录下 acts/*.txt 的文件修改时间快照，用于判断主操作员是否已产出幕脚本。"""
        if not self.ledger_path:
            return {}
        acts_dir = self.ledger_path.parent / "acts"
        if not acts_dir.is_dir():
            return {}
        snap: dict[str, int] = {}
        with contextlib.suppress(OSError):
            for p in acts_dir.glob("*.txt"):
                if p.is_file():
                    st = p.stat()
                    if st.st_size > 0:
                        snap[p.name] = st.st_mtime_ns
        return snap

    def _refresh_operator_readiness(self) -> tuple[bool, bool, str]:
        """汇总三处真实信号判定主操作员是否已就绪/上台，以及桌面语音队列是否正在发声。

        返回 (operator_ready, speech_busy, live_focus)：
        1. 协同目录 acts/*.txt 已新增或更新 → 主操作员已就绪上台；
        2. 主操作员所在会话从 busy 变为 idle → 本轮执行已结束，视为已就绪；
        3. 桌面 8770 /status 语音队列非空 → 正在发声（刷新 last_voice_time）；
           若桌面底部字条已被主操作员替换为非主持人字条 → 主操作员已上台接管。
        """
        cur_acts = self._snapshot_acts()
        for name, mtime_ns in cur_acts.items():
            if self.baseline_acts.get(name) != mtime_ns:
                self.operator_ready = True
                break

        with contextlib.suppress(Exception):
            from frago.server.services import coreagent_runner

            is_busy = coreagent_runner.busy(self.session_id)
            if is_busy:
                self.saw_operator_busy = True
            elif self.saw_operator_busy:
                self.operator_ready = True

        speech_busy = False
        live_focus = "term"
        with contextlib.suppress(Exception):
            from frago.desktop import registry, stage

            if _is_test_isolated() and _is_real_fn(stage._fetch_status, "frago.desktop.stage"):
                return self.operator_ready, speech_busy, live_focus

            rec = registry.read_instance(registry.DEFAULT_ID)
            port = (rec or {}).get("port") if rec and rec.get("status") == "running" else None
            if port:
                st = stage._fetch_status(int(port))
                if isinstance(st, dict):
                    live_focus = str(st.get("focus") or "term")
                    speech = st.get("speech") or {}
                    if speech.get("current") or speech.get("queued"):
                        speech_busy = True
                        self.last_voice_time = time.time()
                    strap_text = ((st.get("strap") or {}).get("text") or "").strip()
                    if (
                        strap_text
                        and strap_text not in self.presenter_straps
                        and not strap_text.startswith(("接活：", "收到，已转达："))
                    ):
                        self.operator_ready = True

        return self.operator_ready, speech_busy, live_focus

    def _check_ledger_updates(self) -> None:
        """扫描 ledger.md 的新增行，将参谋建议与主操作员进展转为纯英文语音排队播报。"""
        if not self.ledger_path or not self.ledger_path.is_file():
            return
        try:
            content = self.ledger_path.read_text(encoding="utf-8")
        except OSError:
            return

        current_section = ""
        new_speeches: list[str] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                current_section = line.lstrip("#").strip()
                continue
            if not (line.startswith("-") or line.startswith("*") or line.startswith("###")):
                continue
            if line in self.narrated_ledger_lines:
                continue

            self.narrated_ledger_lines.add(line)
            if "主操" in current_section or "进展" in current_section or "产物" in current_section:
                self.operator_ready = True
            en_speech = translate_ledger_item_to_english(current_section, line)
            if en_speech:
                new_speeches.append(en_speech)

        for speech in new_speeches:
            self._say_queue(speech)

    def _check_idle_pad(self, *, force_in_test: bool = False) -> None:
        """仅当主操作员尚未产出首幕且桌面无语音超时，才补入单次基于当前窗口焦点的过渡说明（绝不循环念叨）。"""
        ready, speech_busy, live_focus = self._refresh_operator_readiness()
        if ready or speech_busy:
            return
        if self.idle_pad_count >= MAX_IDLE_PADS_PER_TURN:
            return
        if time.time() - self.last_voice_time < IDLE_PAD_INTERVAL_S:
            return
        if os.environ.get("PYTEST_CURRENT_TEST") and not force_in_test:
            return

        focus_label = "browser window" if live_focus == "browser" else "terminal workspace"
        pad_lines = [
            f"The {focus_label} is now open on screen for {self.en_topic}, and I am lining up the live command output and page view.",
            f"Inspecting the live {focus_label} state for {self.en_topic} so every step is visible directly on the desktop.",
        ]
        phrase = sanitize_english_for_tts(
            pad_lines[self.idle_pad_index % len(pad_lines)], speaker="presenter"
        )
        self.idle_pad_index += 1
        self.idle_pad_count += 1
        self._say_queue(phrase)

    def _say_interject(self, phrase_en: str, zh_Fallback_or_strap: str = "", zh_fallback: str = "") -> None:
        """调用 frago desktop say 开口（带插播标志，纯英文）并更新底部中文字条。"""
        from frago.desktop import aos, registry

        strap_text = (zh_Fallback_or_strap or zh_fallback or phrase_en[:50])[:55]
        self.presenter_straps.add(strap_text)
        if _is_test_isolated() and _is_real_fn(aos.post, "frago.desktop.aos"):
            return
        rec = registry.read_instance(registry.DEFAULT_ID)
        if not rec or rec.get("status") != "running":
            return
        safe_en = sanitize_english_for_tts(phrase_en)
        self.last_voice_time = time.time()
        steps = [
            {
                "op": "say",
                "text": safe_en,
                "speak": True,
                "async": True,
                "interject": True,
                "voice": DEFAULT_VOICE,
                "out": "page",
            },
            {
                "op": "strap.show",
                "text": strap_text,
                "style": "chip",
            },
        ]
        try:
            aos.post(rec, steps, timeout=5.0)
        except Exception as e:
            logger.debug("presenter interject say failed, fallback to strap: %s", e)
            with contextlib.suppress(Exception):
                aos.post(
                    rec,
                    [{"op": "strap.show", "text": strap_text[:55], "style": "chip"}],
                    timeout=3.0,
                )

    def _say_queue(self, phrase_en: str) -> None:
        """将英文解说词按序排入桌面语音队列（不带 interject，避免打断正在说的台词）。"""
        from frago.desktop import aos, registry

        if _is_test_isolated() and _is_real_fn(aos.post, "frago.desktop.aos"):
            return
        rec = registry.read_instance(registry.DEFAULT_ID)
        if not rec or rec.get("status") != "running":
            return
        safe_en = sanitize_english_for_tts(phrase_en)
        self.last_voice_time = time.time()
        step = {
            "op": "say",
            "text": safe_en,
            "speak": True,
            "async": True,
            "interject": False,
            "voice": DEFAULT_VOICE,
            "out": "page",
        }
        try:
            aos.post(rec, [step], timeout=5.0)
        except Exception as e:
            logger.debug("presenter queue say failed: %s", e)

    def _record_to_ledger(self, user_text: str) -> None:
        if not self.ledger_path or not self.ledger_path.is_file():
            return
        try:
            content = self.ledger_path.read_text(encoding="utf-8")
            line = f"- 追加需求（{time.strftime('%H:%M:%S')}）：{user_text}"
            self.narrated_ledger_lines.add(line)
            if "# 任务与追加需求" in content:
                content = content.replace(
                    "# 任务与追加需求\n", f"# 任务与追加需求\n{line}\n"
                )
            else:
                content = f"# 任务与追加需求\n{line}\n\n" + content
            self.ledger_path.write_text(content, encoding="utf-8")
        except OSError:
            pass


def ensure_presenter(session_id: str, ledger_path: Path, topic: str) -> PresenterDaemon:
    """已退役：不再启动或注册后台 PresenterDaemon 英文男声线程，仅返回未启动的兼容实例。"""
    return PresenterDaemon(session_id, ledger_path, topic)


def cleanup_presenter(session_id: str) -> None:
    """清理并停止该会话的主持人守护。"""
    with _presenters_lock:
        got = _presenters.pop(session_id, None)
    if got:
        got.stop()


def cleanup_all_presenters() -> list[str]:
    """停止并清空所有驻场主持人守护线程（用于虚拟桌面全局重置）。"""
    with _presenters_lock:
        items = list(_presenters.items())
        _presenters.clear()
    stopped_ids: list[str] = []
    for sid, daemon in items:
        with contextlib.suppress(Exception):
            daemon.stop()
        stopped_ids.append(sid)
    return stopped_ids


def reset_stage_sessions(session_id: str | None = None) -> dict[str, Any]:
    """销毁虚拟桌面关联的后台运行态：关停全部驻场主持人与旁路语音总结器线程，并终止旧主操作员会话进程与队列。"""
    from frago.employee import EmployeeOntologyService, get_post
    from frago.server.services import coreagent_runner
    from frago.server.services import tmux_sessions_service as tsvc

    with _presenters_lock:
        active_stage_sids = list(_presenters.keys())
    with _speech_summarizers_lock:
        for s_sid in _speech_summarizers.keys():
            if s_sid not in active_stage_sids:
                active_stage_sids.append(s_sid)

    post_active_sids: list[str] = []
    with contextlib.suppress(Exception):
        post = get_post(DESKTOP_OPERATOR_POST_ID)
        if post and post.active_session_ids:
            post_active_sids = [str(s).strip() for s in post.active_session_ids if str(s).strip()]

    target_sids: list[str] = []
    for s in ([session_id] if session_id else []) + active_stage_sids + post_active_sids:
        if s and s not in target_sids:
            target_sids.append(s)

    if target_sids:
        _reset_excluded_sids.update(target_sids)
        with contextlib.suppress(Exception):
            EmployeeOntologyService().unregister_session(DESKTOP_OPERATOR_POST_ID, target_sids)
    global _stage_reset_active
    _stage_reset_active = True

    stopped_presenters = cleanup_all_presenters()
    if session_id and session_id not in stopped_presenters:
        cleanup_presenter(session_id)
    with contextlib.suppress(Exception):
        for s_sid in cleanup_all_speech_summarizers():
            if s_sid not in stopped_presenters:
                stopped_presenters.append(s_sid)

    stopped_sessions: list[str] = []
    for sid in target_sids:
        with contextlib.suppress(Exception):
            out = coreagent_runner.stop(sid, by="虚拟桌面重置")
            if out.get("stopped") or out.get("running"):
                stopped_sessions.append(sid)
        with contextlib.suppress(Exception):
            link = tsvc.find_for_session(sid)
            if link is not None:
                tsvc.close_sessions([link.name])
                if sid not in stopped_sessions:
                    stopped_sessions.append(sid)

    return {
        "stopped_presenters": stopped_presenters,
        "stopped_sessions": stopped_sessions,
        "target_sids": target_sids,
    }


def inject_stage_directive(prompt: str, session_id: str, ledger_path: Path) -> str:
    """已退役：不再向会话提示词尾部强行注入旧三角色 DIRECTIVE_HEADER，原样返回 prompt。"""
    return prompt


def orchestrate_stage_session(session_id: str, prompt: str, user_text: str = "") -> str:
    """已退役：不再自动生成 ledger.md、不再启动 PresenterDaemon、不再注入旧三角色指令，原样返回 prompt。"""
    return prompt


# ── 桌面语音监听（Groq Whisper ASR）+ desktop-operator 主操作员 + LightAgent 旁路语音提炼 ──

GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_WHISPER_MODEL = "whisper-large-v3-turbo"
DESKTOP_OPERATOR_POST_ID = "desktop-operator"

#: Whisper 在静音、呼吸尾音或环境底噪切片上高频产生的经典幻觉词（小写归一化后整句/分句匹配）
WHISPER_HALLUCINATION_PHRASES: frozenset[str] = frozenset(
    {
        "thank you",
        "thank you very much",
        "thank you so much",
        "thanks",
        "thanks a lot",
        "thanks for watching",
        "thank you for watching",
        "thanks for listening",
        "thank you for listening",
        "please subscribe",
        "subscribe",
        "like and subscribe",
        "don't forget to subscribe",
        "see you next time",
        "see you in the next video",
        "bye",
        "bye bye",
        "bye-bye",
        "goodbye",
        "you",
        "uh",
        "um",
        "hmm",
        "hm",
        "ah",
        "eh",
        "oh",
        "subtitles by",
        "captioned by",
        "transcribed by",
        "amara.org",
        "amara org",
        "mbc",
        "music",
        "silence",
        "blank_audio",
        "blank audio",
        "inaudible",
        "谢谢观看",
        "感谢观看",
        "谢谢收看",
        "感谢收看",
        "谢谢大家观看",
        "感谢大家观看",
        "字幕由",
        "字幕制作",
        "优优独播剧场",
        "yoyo television series exclusive",
        "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目",
    }
)

#: Whisper 静音字幕水印子串（出现即判定为幻觉）
WHISPER_HALLUCINATION_SUBSTRINGS: tuple[str, ...] = (
    "请不吝点赞",
    "明镜与点点",
    "优优独播剧场",
    "yoyo television series exclusive",
    "subtitles by ",
    "captioned by ",
    "amara.org",
)

#: 括号包裹的非人声噪声标记，如 [Music]、(Silence)、[Blank_Audio]、（音乐）
_BRACKETED_NON_SPEECH_RE = re.compile(
    r"^\s*(?:[\[(（【][^\]）】]{1,36}[\])）】]\s*)+$"
)

#: 中文有效语句末尾因 880ms 静音尾音被 Whisper 拼接的英文/省略号幻觉尾缀
_TRAILING_HALLUCINATION_SUFFIX_RE = re.compile(
    r"(?<=[\u4e00-\u9fff])[\s,，.。!！?？;；:：…\-—]*"
    r"(?:"
    r"thank\s+you(?:\s+very\s+much|\s+so\s+much|\s+for\s+watching|\s+for\s+listening)?|"
    r"thanks(?:\s+a\s+lot|\s+for\s+watching|\s+for\s+listening)?|"
    r"please\s+subscribe|like\s+and\s+subscribe|see\s+you\s+next\s+time|"
    r"subtitles\s+by\b.*|amara\.org.*|"
    r"(?:[\.…]{2,})"
    r")"
    r"[\s,，.。!！?？;；:：…]*$",
    re.IGNORECASE,
)


def is_whisper_hallucination(
    text: str,
    *,
    segments: list[dict[str, Any]] | None = None,
) -> bool:
    """判定 Whisper ASR 返回文本是否属于静音/底噪触发的幻觉标签（如 `Thank you.`、`...`）。"""
    raw = str(text or "").strip()
    if not raw:
        return True

    # 1. 若 Whisper 返回了 segments 置信度指标，当所有分段均为高无声概率且低对数概率时直接判为静音幻觉
    if isinstance(segments, list) and segments:
        valid_segs = [s for s in segments if isinstance(s, dict)]
        if valid_segs:
            all_no_speech = all(
                float(s.get("no_speech_prob") or 0.0) >= 0.85
                and float(s.get("avg_logprob") or 0.0) < -0.95
                for s in valid_segs
                if "no_speech_prob" in s
            )
            any_has_metric = any("no_speech_prob" in s for s in valid_segs)
            if any_has_metric and all_no_speech:
                return True

    # 2. 括号非人声标记（如 [Music]、(Silence)、[Blank_Audio]）
    if _BRACKETED_NON_SPEECH_RE.match(raw):
        return True

    # 3. 纯标点、省略号、符号或空白（如 `...`、`…`、`..`、`？`、`♪`）
    meaningful_chars = re.sub(r"[\s\W_♪🎵]+", "", raw, flags=re.UNICODE)
    if not meaningful_chars:
        return True

    lowered = raw.lower()
    if any(sub in lowered for sub in WHISPER_HALLUCINATION_SUBSTRINGS):
        return True

    # 4. 归一化整句或重复分句匹配（如 "Thank you."、"Thank you. Thank you."、"... Thank you!"）
    clauses = [
        re.sub(r"\s+", " ", c).strip(" '\"\t\r\n-_")
        for c in re.split(r"[.!?。！？,，;；:：…~～—\n]+", lowered)
    ]
    non_empty_clauses = [c for c in clauses if c]
    if not non_empty_clauses:
        return True
    if all(c in WHISPER_HALLUCINATION_PHRASES for c in non_empty_clauses):
        return True

    return False


def clean_whisper_transcription(
    text: str,
    *,
    segments: list[dict[str, Any]] | None = None,
) -> str:
    """清洗 Whisper 转写结果：拦截孤立静音幻觉（`Thank you.` / `...`）并剥离中文句末附带的幻觉尾缀。"""
    raw = str(text or "").strip()
    if not raw:
        return ""
    if is_whisper_hallucination(raw, segments=segments):
        return ""

    # 剥离中文有效指令末尾因静音尾音附带的 "Thank you." / "..." 尾缀
    cleaned = _TRAILING_HALLUCINATION_SUFFIX_RE.sub("", raw).strip()
    if not cleaned or is_whisper_hallucination(cleaned, segments=segments):
        return ""
    return cleaned

SPEECH_SUMMARIZER_SYSTEM_PROMPT = """你就是正在操作这台虚拟桌面（Agent OS）的「主操作员本人」，正在一边操作桌面上的窗口、终端、浏览器与各类程序，一边用第一人称（「我」/「I」）跟身旁看着屏幕的用户实时交谈。
你的输入由六个部分共同构成：
1. 用户的语音或面板输入文本（`<human_voice_asr>`）
2. 我在虚拟桌面上刚执行的操作（`<operator_actions>`，含调用 `agent_os` 桌面工具的指令与回执语义，限制轮次、不限制字数）
3. 我生成的书面结论与响应（`<operator_responses>`，即我的文本回答，限制轮次、不限制字数）
4. `agent_os` 实时屏幕画面与虚拟应用信息流（`<agent_os_screen_context>`，含当前聚焦窗口、打开的虚拟应用、虚拟终端屏幕可见输出流、虚拟浏览器当前 URL/标题/页面可见文本、幻灯片/视频/字幕条状态）
5. 上一次刚说出的语音总结（`<previous_spoken_summary>`）
6. 当前对话流里我已经先后对用户说过的话（`<spoken_stream_so_far>`，按时间顺序排列的连续语音上下文）

【核心职责、第一人称铁律与上下文连贯规则】
0. **严格第一人称主操作员视角（严禁第三方传话口吻）**：
   - 你就是正在动手操作虚拟桌面的「我」本人！全场必须始终使用第一人称（「我」/「I」）直接跟用户对话（例如：「好的，我现在就打开浏览器看一下……」「我已经拉起研发代理去排查这个问题了……」）；
   - **绝对禁止**出现「主操作员」「操作员」「我这就让主操作员」「转交主操作员」「他正在」等把自己当成传话中介或旁观播报员的第三人称表述！
1. **第一时间响应与“暖场”响应（当 `<response_stage>` 为 `FIRST_RESPONSE_WARMUP`，即刚收到用户的输入文本，但我还没来得及在桌面上执行第一个动作时）**：
   - 你必须理解什么叫「第一时间响应」：用户刚说完话，必须立刻用第一人称（「我」）给出简短、亲切、自然的口头回应，确认我已经听见用户的诉求并马上开始处理（例如：「好的，我马上来看看这个问题。」），起到不冷场的「暖场」衔接作用；
   - **严禁掺杂自己对 prompt 的理解**：在还没实际执行桌面操作的前提下，**绝对禁止**自行拆解需求、猜测操作方案、预判具体执行步骤、提前承诺操作细节，或越俎代庖直接编造尚未查明的结果！只能贴合 `<human_voice_asr>` 的字面意思用第一人称做干净利落的第一时间接话暖场。
2. **增量进展与上下文连贯播报（当 `<response_stage>` 为 `INCREMENTAL_UPDATE`，即我已在桌面上产生实际操作或文本响应时）**：
   - 会话流（`<operator_actions>`）中仅记录了 `frago desktop` 控制指令与 `{"ok": true}` 回执，不包含画面内的真实输出；你必须结合 `<agent_os_screen_context>` 中从 `agent_os` 实时获取的屏幕画面与虚拟应用信息流（如终端屏幕上的命令输出、浏览器页面内容、当前窗口状态），以及 `<human_voice_asr>`、`<operator_actions>`、`<operator_responses>`、`<previous_spoken_summary>` 与 `<spoken_stream_so_far>`，提炼相对于 `<spoken_stream_so_far>` 新增的桌面画面进展或最终结论；
   - **自然上下文承接（拒绝孤立广播）**：你的每一句新播报都是接着 `<spoken_stream_so_far>` 里上一句话继续往下聊的真实续篇。若 `<spoken_stream_so_far>` 已有内容，严禁再次使用「好的」「收到」「没问题」等开场白从头寒暄，也严禁复述 `<spoken_stream_so_far>` 里已经讲过的动作或结论；要用「接着看这里」「现在页面已经打开了」「排查结果出来了」等自然口语衔接词顺畅续接上一句；
   - 若我仍在执行与上一轮相同的动作且屏幕画面与响应没有任何新增进展，只输出 `<SILENCE>`。
3. **严防把「刚启动/已派活/8秒首屏返回」误判为「任务已完成」的认知误区戒备（Anti-Premature-Completion）**：
   - `frago desktop term run` 最多只等 8 秒（或终端画面短暂静默 260ms）就会先返回首屏回执（`{"ok": true}` 仅代表命令已敲入终端，绝不代表命令已跑完）；`frago employee invoke`（尤其 `--spawn`）或 `frago agent` 返回 `session_id`、`status: accepted`、`completion_state: running_in_background`、`is_completed: false` 或后台句柄时，仅代表**子任务刚启动、正在后台或终端中执行**；
   - 哪怕我在 `<operator_responses>` 或命令参数中列出了详细的「四步修复方案」「涉及改动文件清单」，只要终端屏幕或子会话还没有产出真实的修改完成回执与测试通过结果，你的语音播报**必须明确表述为「我已经启动了研发代理开始处理……正在执行中」**，**绝对禁止**把「刚派发/方案计划/启动回执」当成「已经改完/已经修好/任务已完成」播报给用户！
4. **纯文本口语化与母语自适应**：
   - 输出结果必须是**100% 纯自然口语文本**，将直接送入母语级情感语音合成引擎（中文使用 `zh-CN-XiaoxiaoNeural`，纯英文使用 `en-US-AvaMultilingualNeural`）；
   - **严禁**输出任何 JSON 对象、请求返回值（如 `{"ok": true, ...}` 或 `KernelTurn(...)`）、代码块、Markdown 符号（`*`、`#`、`` ` ``）、命令行参数或长路径；必须把工具调用与屏幕画面变化转化为「我」正在做的自然动作与结果描述；
   - 每次输出控制在 1～3 句简短自然的口语（15～80 字），直接输出要说给用户听的纯文本正文，不要加任何前缀、引号或角色标签。"""


def resolve_asr_connection() -> tuple[str, str, str]:
    """从 ~/.frago/profiles.json 的 Profile 体系解析 ASR 鉴权密钥、转写端点 URL 与模型名。"""
    try:
        from frago.init.profile_manager import resolve_asr_profile

        profile = resolve_asr_profile()
        if profile is not None and (profile.api_key or "").strip():
            api_key = profile.api_key.strip()
            raw_url = (profile.url or "").strip().rstrip("/")
            if not raw_url:
                transcription_url = GROQ_TRANSCRIPTION_URL
            elif raw_url.endswith("/audio/transcriptions"):
                transcription_url = raw_url
            elif raw_url.endswith("/openai/v1") or raw_url.endswith("/v1"):
                transcription_url = f"{raw_url}/audio/transcriptions"
            else:
                transcription_url = f"{raw_url}/openai/v1/audio/transcriptions"
            model = (profile.default_model or "").strip() or GROQ_WHISPER_MODEL
            return api_key, transcription_url, model
    except Exception:
        logger.debug("从 Profile 解析 ASR 鉴权配置失败", exc_info=True)

    env_key = os.environ.get("GROQ_API_KEY", "").strip()
    if env_key:
        return env_key, GROQ_TRANSCRIPTION_URL, GROQ_WHISPER_MODEL
    raise ValueError(
        "未找到桌面语音识别（ASR）连接配置：请前往 WebUI「设置 → 常规设置 → 旁路与轻量 AI」配置桌面语音识别连接（或在 ~/.frago/profiles.json 中配置 Groq/Whisper Profile 并绑定 asr_profile_id）。"
    )


def resolve_groq_whisper_api_key() -> str:
    """从 ~/.frago/profiles.json 的 ASR Profile 读取 API Key（兼容旧函数签名，绝不读取 recipes.local.json）。"""
    api_key, _, _ = resolve_asr_connection()
    return api_key


def transcribe_audio_with_groq(
    audio_bytes: bytes,
    *,
    filename: str = "speech.webm",
    mime_type: str = "audio/webm",
    language: str | None = None,
    prompt: str | None = None,
    timeout: float = 25.0,
) -> dict[str, Any]:
    """通过 Profile 鉴权调用 Whisper ASR 端点将语音音频字节流转写为文本。"""
    import urllib.error
    import urllib.request
    import uuid

    if not audio_bytes:
        raise ValueError("音频内容为空，无法转写。")

    api_key, transcription_url, whisper_model = resolve_asr_connection()
    boundary = f"----FragoGroqBoundary{uuid.uuid4().hex}"
    parts: list[bytes] = []

    def _add_field(name: str, value: str) -> None:
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )

    _add_field("model", whisper_model)
    _add_field("response_format", "verbose_json")
    _add_field("temperature", "0")
    if language and language.strip():
        _add_field("language", language.strip())
    if prompt and prompt.strip():
        _add_field("prompt", prompt.strip())

    safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename or "speech.webm")
    safe_mime = (mime_type or "audio/webm").split(";")[0].strip() or "audio/webm"
    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(
        (
            f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
            f"Content-Type: {safe_mime}\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(audio_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)

    req = urllib.request.Request(
        transcription_url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "frago-desktop-listener/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        err_body = ""
        with contextlib.suppress(Exception):
            err_body = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Groq Whisper 转写请求失败 (HTTP {exc.code}): {err_body}") from exc
    except Exception as exc:
        raise RuntimeError(f"Groq Whisper 转写连接异常: {exc}") from exc

    raw_text = str(data.get("text") or "").strip()
    segments = data.get("segments") if isinstance(data.get("segments"), list) else None
    text = clean_whisper_transcription(raw_text, segments=segments)
    return {
        "text": text,
        "raw_text": raw_text,
        "hallucination_filtered": bool(raw_text and not text),
        "model": whisper_model,
        "language": data.get("language"),
    }


def fetch_agent_os_screen_context(port: int = 8770, timeout: float = 2.5) -> str:
    """从 agent_os (broker) 实时获取当前桌面画面与虚拟应用信息流（窗口焦点、虚拟终端屏幕输出、虚拟浏览器页面内容、幻灯片/视频/字幕条）。"""
    import subprocess
    import urllib.request

    screen_data: dict[str, Any] = {}
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/screen", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw.strip() else {}
            if isinstance(parsed, dict) and parsed.get("ok"):
                screen_data = parsed
    except Exception:
        logger.debug("请求 agent_os /screen 失败，尝试回退到 /status 与 tmux capture-pane", exc_info=True)

    if not screen_data:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/status", method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                st = json.loads(raw) if raw.strip() else {}
                if isinstance(st, dict):
                    windows = st.get("windows") or {}
                    open_wins = [
                        wid for wid, meta in windows.items()
                        if isinstance(meta, dict) and meta.get("open")
                    ]
                    screen_data = {
                        "ok": True,
                        "focus": st.get("focus") or "",
                        "windows_open": open_wins,
                        "strap": st.get("strap") or {},
                    }
        except Exception:
            pass

    lines: list[str] = []
    focus = str(screen_data.get("focus") or "").strip()
    raw_windows_open = screen_data.get("windows_open") or []
    if isinstance(raw_windows_open, dict):
        windows_open = [str(k) for k, v in raw_windows_open.items() if v]
    elif isinstance(raw_windows_open, list):
        windows_open = [str(w) for w in raw_windows_open if w]
    else:
        windows_open = []
    if focus or windows_open:
        lines.append(
            f"当前聚焦窗口: {focus or '无'} | 已打开虚拟应用窗口: {', '.join(windows_open) if windows_open else '无'}"
        )

    strap_info = screen_data.get("strap")
    if isinstance(strap_info, dict) and str(strap_info.get("text") or "").strip():
        lines.append(f"桌面顶部状态横幅 (strap): {str(strap_info.get('text')).strip()}")

    term_info = screen_data.get("term") if isinstance(screen_data.get("term"), dict) else {}
    term_lines = term_info.get("visible_lines") or term_info.get("tail_lines") or []
    if not term_lines:
        with contextlib.suppress(Exception):
            proc = subprocess.run(
                ["tmux", "capture-pane", "-p", "-t", "frago-stage", "-S", "-20"],
                capture_output=True,
                text=True,
                timeout=1.5,
            )
            if proc.returncode == 0 and proc.stdout:
                term_lines = [ln.rstrip() for ln in proc.stdout.splitlines() if ln.strip()][-18:]
    if term_lines:
        clean_term = [str(ln) for ln in term_lines if str(ln).strip()][-18:]
        if clean_term:
            term_view = str(term_info.get("view") or "cli")
            lines.append(f"[虚拟终端 win:term ({term_view}) 屏幕可见内容]:\n" + "\n".join(clean_term))

    browser_info = screen_data.get("browser") if isinstance(screen_data.get("browser"), dict) else {}
    b_url = str(browser_info.get("url") or "").strip()
    b_title = str(browser_info.get("title") or "").strip()
    b_text = str(browser_info.get("visible_text") or "").strip()
    if browser_info.get("open") or b_url or b_title or b_text:
        b_header = f"[虚拟浏览器 win:browser] 标题: {b_title or '无'} | URL: {b_url or 'about:blank'}"
        lines.append(b_header)
        if b_text:
            lines.append(f"浏览器页面可见文本:\n{b_text[:1200]}")

    slide_info = screen_data.get("slide") if isinstance(screen_data.get("slide"), dict) else {}
    if slide_info.get("active"):
        lines.append(
            f"[虚拟幻灯片 win:slide] 演示文稿: {slide_info.get('deck')} (第 {slide_info.get('page')}/{slide_info.get('total')} 页)"
        )

    video_info = screen_data.get("video") if isinstance(screen_data.get("video"), dict) else {}
    if video_info.get("active"):
        lines.append(
            f"[虚拟视频播放器 win:video] 片源: {video_info.get('src')} | 播放中: {bool(video_info.get('playing'))}"
        )

    return "\n".join(lines).strip()


def _strip_operator_directive(text: str) -> str:
    """剥离首轮 `<frago-employee>` 员工语境头，还原用户真实输入。"""
    from frago.employee.ledger import strip_injected_session_blocks

    _res = strip_injected_session_blocks(str(text or ""))
    cleaned = _res[1] if isinstance(_res, tuple) else str(_res or "")
    return clean_user_requirement(cleaned).strip()


def extract_recent_operator_turns(
    session_id: str,
    max_turns: int = 3,
) -> list[dict[str, Any]]:
    """提取操作员最近 max_turns 轮完整响应（限制轮次、不限制字数、包含工具调用语义）。"""
    from frago.session import record_reader

    try:
        records = record_reader.read_records(session_id, limit=250, tail=True)
    except Exception:
        return []

    turns: list[dict[str, Any]] = []
    current_turn: dict[str, Any] | None = None

    for rec in records:
        payload = rec.payload or {}
        seq = getattr(rec, "seq", 0) or 0
        if rec.kind == "user.say" and not payload.get("is_tool_result"):
            user_text = _strip_operator_directive(str(payload.get("text") or ""))
            current_turn = {
                "user_text": user_text,
                "start_seq": seq,
                "end_seq": seq,
                "events": [],
            }
            turns.append(current_turn)
            continue

        if current_turn is None:
            current_turn = {
                "user_text": "",
                "start_seq": seq,
                "end_seq": seq,
                "events": [],
            }
            turns.append(current_turn)

        if seq > current_turn["end_seq"]:
            current_turn["end_seq"] = seq

        if rec.kind in ("tool.call", "tool.use"):
            tool_name = str(payload.get("name") or payload.get("tool") or "tool").strip()
            tool_input = (
                payload.get("input")
                if payload.get("input") is not None
                else (payload.get("args") or payload.get("summary") or "")
            )
            if isinstance(tool_input, dict):
                input_repr = json.dumps(tool_input, ensure_ascii=False)
            else:
                input_repr = str(tool_input or "")
            current_turn["events"].append(
                {
                    "seq": seq,
                    "type": "tool.call",
                    "name": tool_name,
                    "input": input_repr,
                }
            )
        elif rec.kind == "tool.result":
            is_error = bool(payload.get("is_error") or payload.get("error"))
            output_text = str(
                payload.get("output") or payload.get("content") or payload.get("text") or ""
            ).strip()
            current_turn["events"].append(
                {
                    "seq": seq,
                    "type": "tool.result",
                    "is_error": is_error,
                    "output": output_text,
                }
            )
        elif rec.kind == "agent.say":
            say_text = str(payload.get("text") or "").strip()
            if say_text:
                current_turn["events"].append(
                    {
                        "seq": seq,
                        "type": "agent.say",
                        "text": say_text,
                    }
                )

    if max_turns > 0 and len(turns) > max_turns:
        turns = turns[-max_turns:]
    return turns


def build_speech_summarizer_prompt(
    recent_turns: list[dict[str, Any]],
    previous_summary: str = "",
    *,
    human_asr: str = "",
    screen_context: str = "",
    spoken_history: list[str] | None = None,
) -> str:
    """按六要素公式组装第一人称主操作员语音总结输入提示词：
    每次语音总结输入 = 用户的语音/面板输入（human_asr） + 我执行的桌面操作（tool.call/result）
                    + 我的文本响应（agent.say） + agent_os 屏幕画面与虚拟应用信息流（screen_context）
                    + 上一次刚说的话（previous_summary） + 当前对话已说出的连续语音流（spoken_history）
    """
    latest_asr = str(human_asr or "").strip()
    if not latest_asr and recent_turns:
        for turn in reversed(recent_turns):
            ut = str(turn.get("user_text") or "").strip()
            if ut:
                latest_asr = ut
                break

    action_lines: list[str] = []
    response_lines: list[str] = []
    turn_blocks: list[str] = []

    for idx, turn in enumerate(recent_turns, start=1):
        lines = [f"[Turn {idx}]"]
        user_text = str(turn.get("user_text") or "").strip()
        if user_text:
            lines.append(f"用户输入: {user_text}")
        for ev in turn.get("events") or []:
            ev_type = ev.get("type")
            if ev_type in ("tool.call", "tool.use"):
                line = f"[Turn {idx}] 我执行的桌面操作 ({ev.get('name')}): {ev.get('input')}"
                action_lines.append(line)
                lines.append(f"我执行的桌面操作 ({ev.get('name')}): {ev.get('input')}")
            elif ev_type == "tool.result":
                status_tag = "失败" if ev.get("is_error") else "完成"
                line = f"[Turn {idx}] 工具回执 ({status_tag}): {ev.get('output')}"
                action_lines.append(line)
                lines.append(f"工具回执 ({status_tag}): {ev.get('output')}")
            elif ev_type == "agent.say":
                line = f"[Turn {idx}] 我的文本结论: {ev.get('text')}"
                response_lines.append(line)
                lines.append(f"我的文本结论: {ev.get('text')}")
        turn_blocks.append("\n".join(lines))

    # 判定当前最新一轮是否尚未产生桌面操作/响应（即处于「第一时间暖场响应」阶段）
    latest_turn_has_events = bool(recent_turns[-1].get("events")) if recent_turns else False
    if human_asr and human_asr.strip():
        if not recent_turns or str(recent_turns[-1].get("user_text") or "").strip() != human_asr.strip():
            latest_turn_has_events = False

    response_stage = "INCREMENTAL_UPDATE" if latest_turn_has_events else "FIRST_RESPONSE_WARMUP"
    asr_body = latest_asr if latest_asr else "（暂无最新用户输入）"
    actions_body = "\n".join(action_lines) if action_lines else "（我刚开始处理当前指令，尚未执行具体桌面操作）"
    responses_body = "\n".join(response_lines) if response_lines else "（我尚未生成最终文本结论）"
    screen_body = (
        str(screen_context or "").strip()
        if screen_context and str(screen_context).strip()
        else "（当前未采集到 agent_os 屏幕画面或虚拟应用活动输出）"
    )
    turns_body = "\n\n".join(turn_blocks) if turn_blocks else f"[Turn 1]\n用户输入: {asr_body}"
    prev_body = previous_summary.strip() if previous_summary and previous_summary.strip() else "（尚无历史播报）"

    history_items = [str(s).strip() for s in (spoken_history or []) if str(s).strip()]
    if not history_items and previous_summary and previous_summary.strip():
        history_items = [previous_summary.strip()]
    stream_body = (
        "\n".join(f"{i}. {item}" for i, item in enumerate(history_items[-6:], start=1))
        if history_items
        else "（当前对话流尚未开口说话）"
    )

    return (
        f"{SPEECH_SUMMARIZER_SYSTEM_PROMPT}\n\n"
        f"<response_stage>{response_stage}</response_stage>\n\n"
        f"<human_voice_asr>\n{asr_body}\n</human_voice_asr>\n\n"
        f"<operator_actions>\n{actions_body}\n</operator_actions>\n\n"
        f"<operator_responses>\n{responses_body}\n</operator_responses>\n\n"
        f"<agent_os_screen_context>\n{screen_body}\n</agent_os_screen_context>\n\n"
        f"<previous_spoken_summary>\n{prev_body}\n</previous_spoken_summary>\n\n"
        f"<spoken_stream_so_far>\n{stream_body}\n</spoken_stream_so_far>\n\n"
        f"<recent_operator_turns turn_count=\"{len(recent_turns)}\">\n{turns_body}\n</recent_operator_turns>\n\n"
        "请直接以第一人称（「我」）输出现在接着对用户说的纯文本口语（若无任何新增进展或无需重复播报，只输出 <SILENCE>）："
    )


def _extract_chat_turn_text(raw_result: Any) -> str:
    """从 kernel_backend.run_chat_turn 的返回值（KernelTurn / dict / str）中提取纯文本，绝不把请求返回结构当成播报词。"""
    if raw_result is None:
        return ""
    if isinstance(raw_result, str):
        s = raw_result.strip()
        m = re.match(
            r"^KernelTurn\(text=(['\"])(.*?)\1,\s*status=['\"](\w+)['\"]",
            s,
            re.DOTALL,
        )
        if m:
            return m.group(2).strip() if m.group(3) == "ok" else ""
        return s
    if isinstance(raw_result, dict):
        if raw_result.get("status") not in (None, "ok") and not raw_result.get("ok", True):
            return ""
        if raw_result.get("is_error"):
            return ""
        return str(raw_result.get("text") or raw_result.get("result") or "").strip()

    status = getattr(raw_result, "status", "ok")
    if status != "ok":
        return ""
    return str(getattr(raw_result, "text", "") or "").strip()


def enforce_first_person_operator_voice(text: str) -> str:
    """将中文或英文口语总结中残余的第三人称「主操作员/操作员/operator」中介转述口吻统一改写为第一人称「我/I」。"""
    if not text:
        return ""
    s = text.strip()
    zh_rewrites = [
        (
            r"我(?:这就|马上|立刻|先|去|帮您|帮你)?(?:让|请|交由|转交|通知|安排|叫)(?:桌面)?(?:主)?操作员(?:帮您|帮你)?",
            "我这就",
        ),
        (
            r"正在(?:转交|交由|通知)(?:给)?(?:桌面)?(?:主)?操作员(?:处理|执行|跟进|排查|研究)?",
            "我马上开始处理",
        ),
        (
            r"已(?:经)?(?:转交|交由|通知)(?:给)?(?:桌面)?(?:主)?操作员(?:处理|执行|跟进|排查|研究)?",
            "我已经在处理",
        ),
        (r"(?:桌面)?(?:主)?操作员(?:正在|正|已经|刚刚|刚|将|会|开始|准备)", "我"),
        (r"(?:桌面)?(?:主)?操作员", "我"),
        (r"我我+", "我"),
        (r"我这就(?:这就|马上|立刻)", "我这就"),
    ]
    for pattern, repl in zh_rewrites:
        s = re.sub(pattern, repl, s)
    if re.search(r"\boperator\b", s, flags=re.IGNORECASE):
        s = enforce_presenter_perspective(s, speaker="presenter")
    return s.strip()


def _clean_spoken_summary(
    raw_text: Any,
    previous_summary: str = "",
    spoken_history: list[str] | None = None,
) -> str:
    """清洗 LightAgent 返回的口语总结文本，过滤 KernelTurn/JSON 请求返回体、<SILENCE>、第三人称转述口吻与重复内容。"""
    cleaned = _extract_chat_turn_text(raw_text)
    if not cleaned:
        return ""
    if "<SILENCE>" in cleaned.upper() or cleaned.upper() == "SILENCE":
        return ""
    cleaned = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", cleaned).strip()
    cleaned = cleaned.strip('"\'“”‘’')
    if not cleaned:
        return ""
    if (cleaned.startswith("{") and cleaned.endswith("}")) or (
        cleaned.startswith("[") and cleaned.endswith("]")
    ):
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                if parsed.get("is_error") or parsed.get("ok") is False or "op" in parsed:
                    return ""
                extracted = str(
                    parsed.get("text") or parsed.get("summary") or parsed.get("result") or ""
                ).strip()
                cleaned = extracted
            else:
                return ""
        except Exception:
            return ""
    if not cleaned:
        return ""
    if any(
        bad in cleaned
        for bad in (
            "KernelTurn(",
            "duration_ms=",
            "tmux_name=",
            "Traceback (most recent call last)",
            '"error_kind"',
            '"status_code"',
        )
    ):
        return ""
    cleaned = enforce_first_person_operator_voice(cleaned)
    if not cleaned:
        return ""
    if previous_summary and cleaned == previous_summary.strip():
        return ""
    if spoken_history and any(cleaned == h.strip() for h in spoken_history if h):
        return ""
    return cleaned


def summarize_operator_for_speech(
    session_id: str,
    previous_summary: str = "",
    *,
    human_asr: str = "",
    screen_context: str | None = None,
    spoken_history: list[str] | None = None,
    max_turns: int = 3,
    cwd: str | None = None,
) -> str:
    """使用 frago-core 单轮对话（--as-role lightagent）结合用户语音 ASR、操作员操作与响应、agent_os 实时屏幕信息流及连续语音上下文生成第一人称纯文本播报词。"""
    from frago.agent_driver import kernel_backend

    recent_turns = extract_recent_operator_turns(session_id, max_turns=max_turns)
    effective_asr = str(human_asr or "").strip()
    if not effective_asr and recent_turns:
        effective_asr = str(recent_turns[-1].get("user_text") or "").strip()
    has_operator_events = any(bool(t.get("events")) for t in recent_turns)
    if not has_operator_events and not effective_asr:
        return ""

    effective_screen = (
        screen_context
        if screen_context is not None
        else fetch_agent_os_screen_context()
    )
    prompt = build_speech_summarizer_prompt(
        recent_turns,
        previous_summary,
        human_asr=effective_asr,
        screen_context=effective_screen,
        spoken_history=spoken_history,
    )
    raw = kernel_backend.run_chat_turn(
        prompt,
        cwd=cwd or str(Path.home()),
        role="lightagent",
        timeout_s=35.0,
    )
    spoken = _clean_spoken_summary(raw, previous_summary, spoken_history=spoken_history)
    if not spoken and getattr(raw, "status", "ok") != "ok":
        with contextlib.suppress(Exception):
            fallback_raw = kernel_backend.run_chat_turn(
                prompt,
                cwd=cwd or str(Path.home()),
                role=None,
                timeout_s=35.0,
            )
            spoken = _clean_spoken_summary(
                fallback_raw, previous_summary, spoken_history=spoken_history
            )
    return spoken


class SpeechSummarizerDaemon:
    """监听用户语音 ASR 与 desktop-operator 会话新增响应并调用 LightAgent + Edge TTS 播报的旁路守护线程。"""

    def __init__(
        self,
        session_id: str,
        *,
        max_turns: int = 3,
        cwd: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.max_turns = max_turns
        self.cwd = cwd or str(Path.home())
        self.previous_summary = ""
        self.spoken_history: list[str] = []
        self.last_summarized_seq = 0
        self.pending_human_asr: str = ""
        self.last_warmed_asr: str = ""
        self._lock = threading.Lock()
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._seed_initial_seq()

    def _seed_initial_seq(self) -> None:
        from frago.session import record_reader

        with contextlib.suppress(Exception):
            recs = record_reader.read_records(self.session_id, limit=1, tail=True)
            if recs:
                self.last_summarized_seq = getattr(recs[-1], "seq", 0) or 0

    def notify_human_asr(self, human_asr: str) -> None:
        """在语音转写完成的瞬间通知播音守护线程，触发第一时间暖场响应。"""
        clean_asr = str(human_asr or "").strip()
        if not clean_asr:
            return
        with self._lock:
            self.pending_human_asr = clean_asr
        self._wake_event.set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"speech-summarizer-{self.session_id[:12]}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()

    def step_once(self) -> str:
        """检查是否有新的用户语音 ASR（第一时间暖场）或新的操作员操作/响应（增量播报）。"""
        from frago.desktop import voice
        from frago.session import record_reader

        with self._lock:
            immediate_asr = self.pending_human_asr
            self.pending_human_asr = ""

        new_records: list[Any] = []
        with contextlib.suppress(Exception):
            new_records = record_reader.read_records(
                self.session_id,
                after=self.last_summarized_seq + 1,
                limit=100,
            )

        has_new_operator_output = False
        latest_record_asr = ""
        max_seq = self.last_summarized_seq
        for rec in new_records:
            seq = getattr(rec, "seq", 0) or 0
            if seq > max_seq:
                max_seq = seq
            payload = getattr(rec, "payload", None) or {}
            if rec.kind == "user.say" and not payload.get("is_tool_result"):
                u_text = _strip_operator_directive(str(payload.get("text") or ""))
                if u_text:
                    latest_record_asr = u_text
            elif rec.kind in ("agent.say", "tool.call", "tool.use", "tool.result"):
                has_new_operator_output = True

        self.last_summarized_seq = max_seq

        effective_asr = immediate_asr or latest_record_asr
        is_warmup = False
        if not has_new_operator_output:
            if effective_asr and effective_asr != self.last_warmed_asr:
                is_warmup = True
            else:
                return ""

        if effective_asr:
            self.last_warmed_asr = effective_asr

        try:
            spoken = summarize_operator_for_speech(
                self.session_id,
                self.previous_summary,
                human_asr=effective_asr,
                spoken_history=self.spoken_history,
                max_turns=self.max_turns,
                cwd=self.cwd,
            )
        except Exception:
            logger.warning("LightAgent 语音总结提炼失败 (%s)", self.session_id, exc_info=True)
            return ""

        if not spoken:
            return ""

        self.previous_summary = spoken
        self.spoken_history = (self.spoken_history + [spoken])[-6:]
        chosen_voice = voice.resolve_emotional_voice(spoken)
        self._speak_on_desktop(spoken, chosen_voice, interject=is_warmup)
        return spoken

    def _speak_on_desktop(
        self,
        spoken_text: str,
        chosen_voice: str,
        *,
        interject: bool = False,
    ) -> bool:
        from frago.desktop import aos, registry

        try:
            rec = registry.read_instance("default")
            if not rec or rec.get("status") != "running":
                return False
            steps: list[dict[str, Any]] = [
                {
                    "op": "say",
                    "text": spoken_text,
                    "speak": True,
                    "async": True,
                    "interject": bool(interject),
                    "voice": chosen_voice,
                    "out": "page",
                }
            ]
            aos.post(rec, steps, timeout=8.0)
            return True
        except Exception:
            logger.debug("旁路语音提炼器向桌面发送语音失败", exc_info=True)
            return False

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.step_once()
            except Exception:
                logger.debug("SpeechSummarizerDaemon 轮询异常", exc_info=True)
            self._wake_event.wait(1.2)
            self._wake_event.clear()


_speech_summarizers_lock = threading.Lock()
_speech_summarizers: dict[str, SpeechSummarizerDaemon] = {}
_reset_excluded_sids: set[str] = set()
_stage_reset_active: bool = False


def ensure_speech_summarizer(
    session_id: str,
    *,
    max_turns: int = 3,
    cwd: str | None = None,
) -> SpeechSummarizerDaemon:
    """确保指定 desktop-operator 会话的旁路语音提炼守护线程已启动。"""
    with _speech_summarizers_lock:
        existing = _speech_summarizers.get(session_id)
        if existing is not None:
            existing.start()
            return existing
        daemon = SpeechSummarizerDaemon(session_id, max_turns=max_turns, cwd=cwd)
        _speech_summarizers[session_id] = daemon
        daemon.start()
        return daemon


def cleanup_speech_summarizer(session_id: str) -> None:
    """停止并移除指定会话的旁路语音提炼守护线程。"""
    with _speech_summarizers_lock:
        daemon = _speech_summarizers.pop(session_id, None)
    if daemon is not None:
        with contextlib.suppress(Exception):
            daemon.stop()


def cleanup_all_speech_summarizers() -> list[str]:
    """停止并清空全部旁路语音提炼守护线程。"""
    with _speech_summarizers_lock:
        items = list(_speech_summarizers.items())
        _speech_summarizers.clear()
    stopped: list[str] = []
    for sid, daemon in items:
        with contextlib.suppress(Exception):
            daemon.stop()
        stopped.append(sid)
    return stopped


def is_desktop_operator_session(session_id: str) -> bool:
    """判断指定会话是否属于专职员工 desktop-operator（若从会话首轮记录识别命中则自动补登记回 active_session_ids）。"""
    clean_sid = str(session_id or "").strip()
    if not clean_sid:
        return False

    from frago.employee import EmployeeOntologyService, get_post
    from frago.session import record_reader

    with contextlib.suppress(Exception):
        post = get_post(DESKTOP_OPERATOR_POST_ID)
        if post and clean_sid in (post.active_session_ids or []):
            return True

    if clean_sid.startswith("core_"):
        with contextlib.suppress(Exception):
            early_records = record_reader.read_records(clean_sid, limit=2, tail=False)
            for rec in early_records:
                if getattr(rec, "kind", None) != "user.say":
                    continue
                payload = getattr(rec, "payload", None) or {}
                text = str(payload.get("text") or "").lstrip()
                if text.startswith(f'<frago-employee id="{DESKTOP_OPERATOR_POST_ID}"'):
                    if clean_sid not in _reset_excluded_sids:
                        with contextlib.suppress(Exception):
                            EmployeeOntologyService().register_session(
                                DESKTOP_OPERATOR_POST_ID, clean_sid
                            )
                    return True
    return False


def maybe_ensure_desktop_operator_speech(
    session_id: str,
    *,
    cwd: str | None = None,
) -> bool:
    """若目标会话是 desktop-operator 会话，自动确保旁路语音守护线程已挂载。"""
    clean_sid = str(session_id or "").strip()
    if not clean_sid:
        return False
    if is_desktop_operator_session(clean_sid):
        ensure_speech_summarizer(clean_sid, cwd=cwd)
        return True
    return False


def resolve_active_desktop_operator_session(
    *,
    ensure_summarizer: bool = True,
) -> dict[str, Any]:
    """解析 desktop-operator 最近一个真实落盘的活跃会话，并按需预挂载旁路语音提炼守护线程。"""
    from frago.employee import (
        EmployeeOntologyService,
        ensure_builtin_desktop_operator_employee,
        get_post,
        load_ledger,
    )
    from frago.session import coreagent_store, record_reader

    post = ensure_builtin_desktop_operator_employee()
    fresh_post = get_post(DESKTOP_OPERATOR_POST_ID) or post
    effective_cwd = (fresh_post.cwd or str(Path.home())).strip() or str(Path.home())

    candidates: list[str] = []

    def _add_candidate(raw_sid: Any) -> None:
        s = str(raw_sid or "").strip()
        if s and s not in _reset_excluded_sids and s not in candidates:
            candidates.append(s)

    for sid in reversed(fresh_post.active_session_ids or []):
        _add_candidate(sid)

    if not candidates and _stage_reset_active:
        return {
            "session_id": None,
            "employee": DESKTOP_OPERATOR_POST_ID,
            "restored": False,
        }

    with contextlib.suppress(Exception):
        ledger = load_ledger(DESKTOP_OPERATOR_POST_ID)
        if ledger is not None:
            recent_attr = getattr(ledger, "recent_sessions", None) or []
            for item in recent_attr:
                if isinstance(item, dict):
                    _add_candidate(item.get("session_id"))
                else:
                    _add_candidate(item)
            claimed = getattr(ledger, "claimed_resources", None) or {}
            if isinstance(claimed, dict):
                for item in claimed.get("matched_sessions") or []:
                    if isinstance(item, dict):
                        _add_candidate(item.get("session_id"))
                    else:
                        _add_candidate(item)

    def _session_has_local_records(sid: str) -> bool:
        with contextlib.suppress(Exception):
            if coreagent_store.session_exists(sid):
                return True
        with contextlib.suppress(Exception):
            if bool(record_reader.read_records(sid, limit=1)):
                return True
        return False

    chosen_sid: str | None = None
    for sid in candidates:
        if _session_has_local_records(sid):
            chosen_sid = sid
            break

    if chosen_sid is None:
        with contextlib.suppress(Exception):
            for path in coreagent_store.iter_session_files()[:100]:
                sid = path.stem.strip()
                if not sid or sid in _reset_excluded_sids:
                    continue
                if is_desktop_operator_session(sid) and _session_has_local_records(sid):
                    chosen_sid = sid
                    break

    if chosen_sid:
        with contextlib.suppress(Exception):
            EmployeeOntologyService().register_session(DESKTOP_OPERATOR_POST_ID, chosen_sid)
        if ensure_summarizer:
            ensure_speech_summarizer(chosen_sid, cwd=effective_cwd)
        return {
            "session_id": chosen_sid,
            "employee": DESKTOP_OPERATOR_POST_ID,
            "restored": True,
        }

    return {
        "session_id": None,
        "employee": DESKTOP_OPERATOR_POST_ID,
        "restored": False,
    }


def dispatch_desktop_voice_command(
    text: str,
    session_id: str | None = None,
    *,
    cwd: str | None = None,
) -> dict[str, Any]:
    """将识别到的文本投喂给专职员工 desktop-operator，并激活旁路 LightAgent 语音提炼器。"""
    import uuid

    from frago.employee import (
        EmployeeOntologyService,
        ensure_builtin_desktop_operator_employee,
        get_post,
    )
    from frago.server.services import session_send
    from frago.session import record_reader

    cleaned_text = clean_whisper_transcription(str(text or ""))
    if not cleaned_text:
        raise ValueError("识别到的语音文本为空或属于静音噪音幻觉，已忽略。")

    # 1. 确保 desktop-operator 员工岗位已存在
    post = ensure_builtin_desktop_operator_employee()
    emp_service = EmployeeOntologyService()

    # 2. 确保虚拟桌面在线
    ensure_stage_up()

    # 3. 解析或分配 desktop-operator 的会话 ID
    sid = str(session_id or "").strip()
    if not sid:
        fresh_post = get_post(DESKTOP_OPERATOR_POST_ID) or post
        if fresh_post.active_session_ids:
            sid = fresh_post.active_session_ids[-1]
        else:
            sid = f"core_{uuid.uuid4().hex[:16]}"

    global _stage_reset_active
    _stage_reset_active = False
    _reset_excluded_sids.discard(sid)
    effective_cwd = (cwd or post.cwd or str(Path.home())).strip() or str(Path.home())

    # 4. 仅在首轮新建会话时前置挂载标准 <frago-employee> 语境块（由终端与网页折叠渲染为 @桌面主操作员 标签），
    #    后续轮次保持纯净用户原话，绝不在用户消息下方拼接裸露的系统提示词尾缀
    from frago.session import coreagent_store

    is_existing = False
    with contextlib.suppress(Exception):
        is_existing = coreagent_store.session_exists(sid) or bool(record_reader.read_records(sid, limit=1))

    full_prompt = cleaned_text
    if not is_existing:
        with contextlib.suppress(Exception):
            ctx_block = emp_service.build_business_context_block(DESKTOP_OPERATOR_POST_ID)
            if ctx_block:
                full_prompt = f"{ctx_block}\n\n{cleaned_text}"
    with contextlib.suppress(Exception):
        emp_service.register_session(DESKTOP_OPERATOR_POST_ID, sid)

    # 5. 启动该会话的旁路 LightAgent 语音提炼守护线程，并将用户语音 ASR 同步通知给播音大模型做第一时间暖场响应
    daemon = ensure_speech_summarizer(sid, cwd=effective_cwd)
    daemon.notify_human_asr(cleaned_text)

    # 7. 异步入队投喂给主操作员
    session_send.send_queued(sid, full_prompt, cwd_hint=effective_cwd)

    return {
        "session_id": sid,
        "employee": DESKTOP_OPERATOR_POST_ID,
        "text": cleaned_text,
        "status": "queued",
    }

