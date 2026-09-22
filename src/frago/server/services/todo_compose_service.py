"""一句话建一件事务：把描述交给 frago 自带的那个小 agent，由它去跑 `frago todo add`。

界面上的「添一件」只收一句话。一件像样的事务需要的其余部分——英文 kebab 标题、
中文摘要、背景、怎么算做完——由 agent 补齐。

**为什么不在这里直接写文件。** 事务的写入口只有命令行一条（读接口那边写着这条
约束）。这里没有破例：服务端只是把话转给 agent，真正落盘的仍然是 `frago todo add`。
这样做还白捡一件事——`todo add` 自带的那些规矩（标题会被 slugify 成 id，中文标题
会变成一串拼音垃圾；同一件事不准开第二条，重复的要用 `todo log` 往上追加）是规则
引擎在 agent 调工具的那一刻注进去的。规矩改了，这里不用跟着改；抄一份到这里，才
是两边迟早对不上账的开始。

**为什么用 CoreAgent 而不是 `frago agent`。** `frago agent` 那条路要起一个 tmux
会话跑完整的 cli-agent，实测一轮 26 秒，还占着一个会话；CoreAgent（frago-core 自己
的 agent 循环）9 秒出结果。它的工具面跟 Claude Code 一样有 Bash、读写文件，所以这里
用 ``--allowed-tools`` 把它收窄到只能执行 `frago todo` 命令——填一句话建一条待办，
用不着别的。管着 todo 写法的两条硬规矩走的是工具调用层，CoreAgent 收得到。

**它可能不新建。** 用户描述的事情如果已经有一条了，规则要求 agent 改用
`frago todo log` 往那条上追加。所以返回里的 ``created`` 会是 False，``todo_id``
指向的是那条旧的。界面要照实说，别把追加说成新建。
"""

from __future__ import annotations

import json
import logging
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# agent 最多来回几轮。它正常要两到三轮：查一遍现有事务，再落一次命令。给到 8 是
# 留给「查完发现要追加、于是换一条命令」这种多一步的走法，再多就是它绕不出来了，
# 与其烧着模型转圈，不如让人看见失败。
MAX_ROUNDS = 8

# 整个过程的墙钟上限。实测一轮 9 秒，查一遍再落一次约 15 秒；120 秒是留给慢端点
# 的余量，不是常态。到点仍未结束就是出事了，界面得拿到一个明确的失败。
TIMEOUT_SECONDS = 120

# 这一场在会话页左栏叫什么。固定一句：这条路上每一场干的是同一件事，区分靠的是时刻
# 与内容，不靠名字。
_SESSION_TITLE = "待办拟稿"

# `frago todo add` 成功时打的那行。id 是它自己定的（由标题 slugify 而来），所以只
# 能从输出里读，不能在这边预测。
_CREATED_RE = re.compile(r"Created todo\s+(\S+)")

# `frago todo log` 成功时打的那行——描述的事情已经有一条，agent 按规矩改成了追加。
# 整行长这样：``Logged to <id> (todo) · session <sid>``。只认紧跟在 "to" 后面那一
# 个词：后半截还有一个会话 id，贪到行尾会把那个当成事务 id 报给人。
_LOGGED_RE = re.compile(r"Logged to\s+(\S+)")

# `frago todo` 里会改动账本的那几个子命令。用来把 agent 的查重动作（list/show）从
# 「它替我执行了什么」里择出去。
_WRITE_SUBCOMMANDS = frozenset({"add", "log", "edit", "done", "rm"})

# 交给 agent 的任务书。
#
# 规矩本身不写在这里——工具调用时规则引擎会把 `todo add` 该守的那几条注进去。用户
# 的原话夹在分隔符里，免得里面的换行或指令样式的句子把任务书本身搅乱。
#
# 开头那句「不要读任何手册」是拿轮数换来的教训：会话开始注入的宪法要求 agent 输出
# 前先跑 `frago book must-output-shape`，那本手册很长，读完轮数和上下文就见底了，
# 事务一件都没建成。那条规矩是给对着人说话的会话用的；这里是一次程序调用，交付物
# 是一条命令的执行结果，不是一段给人读的回答。
_PROMPT = """\
这是一次程序调用，不是对话。不要读任何手册（不要跑 frago book），不要查配方，不要
研究输出格式——直接把事情办了。

把下面这段用户描述登记成一件 frago 事务，现在就用 frago todo add 真正执行，不要只
给建议。

用户描述原文：
<<<DESCRIPTION
{description}
DESCRIPTION

先跑一次 frago todo list 扫一眼标题，确认这件事还没有人开过条目。已经有了就不要开
第二条，改用 frago todo log 往那条上追加。
标题用英文 kebab 词汇，中文内容放 --summary 和 --context，并补上 --done-when。

办完用一两句中文说明你做了什么，并把那条事务的 id 写出来。
"""


_SHELL_SEPARATORS = frozenset({"&&", "||", ";", "|"})


def frago_invocations(events: list[dict[str, Any]]) -> list[list[str]]:
    """agent 通过 Bash 执行过的每一条 frago 命令，按先后给出 `frago` 之后的那些词。

    CoreAgent 跟 Claude Code 一样只有 Bash 这一个执行命令的工具，frago 命令也从这里走。
    一条 Bash 可能是 `cd x && frago todo add ...` 这种组合，按分隔符拆开逐段认；
    拆不开（引号没配对之类）的那条跳过，不要因此整单失败。

    被拦下的调用不算：它没有执行，摆到界面上说「它替你执行了这条」就是假话。
    """
    denied_ids = {
        event.get("tool_call_id")
        for event in events
        if event.get("type") == "result" and event.get("denied")
    }
    found: list[list[str]] = []
    for event in events:
        if event.get("type") != "tool" or event.get("tool_name") != "Bash":
            continue
        if event.get("tool_call_id") in denied_ids:
            continue
        command = (event.get("input") or {}).get("command")
        if not isinstance(command, str):
            continue
        try:
            tokens = shlex.split(command)
        except ValueError:
            continue
        segment: list[str] = []
        for token in [*tokens, ";"]:
            if token in _SHELL_SEPARATORS:
                if segment[:1] == ["frago"] and len(segment) > 1:
                    found.append(segment[1:])
                segment = []
            else:
                segment.append(token)
    return found


class TodoComposeError(RuntimeError):
    """建不成的时候抛这个。``detail`` 是能直接给人看的那句原因。"""

    def __init__(self, detail: str, *, transcript: str = "") -> None:
        super().__init__(detail)
        self.detail = detail
        self.transcript = transcript


class TodoComposeService:
    """把一句话变成一件事务。"""

    @staticmethod
    def compose(description: str) -> dict[str, Any]:
        """交给 agent 去建，返回它建出了什么。

        Args:
            description: 用户在界面上填的那句话，原样转交。

        Returns:
            ``{"todo_id", "created", "message", "command"}``。``todo_id`` 在
            agent 跑完却没落下任何一条事务时为 None——那种情况下 ``message`` 里
            是它自己的说法，让人自己判断是描述太含糊还是它偷懒了。

        Raises:
            TodoComposeError: 模型没配好、二进制不在、超时，或者 agent 非零退出。
        """
        text = description.strip()
        if not text:
            raise TodoComposeError("描述是空的")

        TodoComposeService._require_model()
        binary = TodoComposeService._binary_path()

        # 这一场的编号在这里现发：不发的话内核自己发一个，而 frago 这边就不知道它是
        # 哪一场，既贴不上名字也归不了组。名字是固定的那一句——左栏摆开口第一句的话，
        # 每一场摆的都是同一段说明书，二十场长得一模一样。
        from frago.server.services import coreagent_runner

        session_id = coreagent_runner.start_local_ops(_SESSION_TITLE)

        # 逐步输出才带得回「它执行了哪条命令」；CoreAgent 默认只打印最终答案文字。
        cmd = [
            str(binary),
            "--output-format",
            "stream-json",
            "--session-id",
            session_id,
            "--title",
            _SESSION_TITLE,
            "--prompt",
            _PROMPT.format(description=text),
            "--max-rounds",
            str(MAX_ROUNDS),
            "--allowed-tools",
            "Bash(frago todo:*)",
        ]

        try:
            proc = TodoComposeService._run(cmd)
        except subprocess.TimeoutExpired as exc:
            raise TodoComposeError(f"agent 跑了 {TIMEOUT_SECONDS} 秒还没结束，已放弃") from exc

        events = TodoComposeService._parse_events(proc.stdout or "")

        if proc.returncode != 0:
            # stderr 是给人读的那一路，内核把失败原因写在这里。
            detail = (proc.stderr or "").strip().splitlines()
            reason = detail[-1] if detail else f"exit code {proc.returncode}"
            raise TodoComposeError(f"agent 没能完成：{reason}", transcript=proc.stdout or "")

        todo_id, created = TodoComposeService._extract_todo(events)
        return {
            "todo_id": todo_id,
            "created": created,
            "message": TodoComposeService._final_text(events),
            "command": TodoComposeService._last_command(events, created=created),
        }

    # ── 跑 agent ──────────────────────────────────────────────────────

    @staticmethod
    def _run(cmd: list[str]) -> subprocess.CompletedProcess:
        """在用户自己的家目录里跑。

        内核会把当前目录当成工作现场；服务进程的目录是它自己启动的地方，跟用户
        无关，落在那里只会让 agent 对着一个陌生的仓库做判断。
        """
        from frago.server.services.subprocess_utils import get_utf8_env

        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            cwd=str(Path.home()),
            env=get_utf8_env(),
        )

    @staticmethod
    def _binary_path() -> Path:
        """内核二进制的位置——跟 hook 引擎是同一个文件，不带 --engine 就是内核。"""
        from frago.init.hook_binary import get_binary_name, get_hook_deploy_dir

        binary = get_hook_deploy_dir() / get_binary_name()
        if not binary.exists():
            raise TodoComposeError(
                "frago 的内核还没装好（~/.frago/bin 下找不到），跑一次 frago init 补上"
            )
        return binary

    @staticmethod
    def _require_model() -> None:
        """没有可用的模型就别起进程。

        内核在没配模型时会转成交互式追问 endpoint 和 key。那在命令行里是体贴，
        在服务端是一个永远等不到输入、只能等超时的进程。所以这一关必须在前面拦。
        """
        from frago.server.services.hook_review_service import (
            STATUS_NO_KEY,
            STATUS_NOT_CONFIGURED,
            HookReviewService,
        )

        state, name, _model, detail = HookReviewService._resolve_profile()
        if state == STATUS_NOT_CONFIGURED:
            hint = f"：{detail}" if detail else ""
            raise TodoComposeError(f"还没有可用的模型配置{hint}。去设置里配一个 profile")
        if state == STATUS_NO_KEY:
            who = f"「{name}」" if name else ""
            raise TodoComposeError(f"模型配置{who}缺 API key，补上才能用")

    # ── 读 agent 的输出 ───────────────────────────────────────────────

    @staticmethod
    def _parse_events(stdout: str) -> list[dict[str, Any]]:
        """内核的 stdout 是一行一个 JSON 事件。读不懂的行跳过，不要因此整单失败。"""
        events: list[dict[str, Any]] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("skipping non-JSON kernel output: %s", line[:120])
                continue
            if isinstance(event, dict):
                events.append(event)
        return events

    @staticmethod
    def _extract_todo(events: list[dict[str, Any]]) -> tuple[str | None, bool]:
        """从工具的回显里认出事务 id，以及它是新建的还是追加上去的。

        新建优先：一轮里如果既有追加又有新建（agent 查完发现是另一件事，于是先
        追加又新建），人关心的是新出现的那一条。
        """
        logged: str | None = None
        for event in events:
            if event.get("type") != "result":
                continue
            output = event.get("output")
            if not isinstance(output, str):
                continue
            created = _CREATED_RE.search(output)
            if created:
                return created.group(1), True
            if logged is None:
                appended = _LOGGED_RE.search(output.strip())
                if appended:
                    logged = appended.group(1)
        return logged, False

    @staticmethod
    def _final_text(events: list[dict[str, Any]]) -> str:
        """agent 最后那句话。没有就退回它最后一次想的内容，别给界面一个空白。"""
        for event in reversed(events):
            if event.get("type") == "done":
                text = event.get("final_text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        for event in reversed(events):
            if event.get("type") == "thinking":
                text = event.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        return ""

    @staticmethod
    def _last_command(events: list[dict[str, Any]], *, created: bool) -> list[str] | None:
        """让人看见 agent 替他执行了什么——挑与结论对得上的那一条。

        界面上这条命令就印在「建好了 xxx」下面，两者必须是同一件事。agent 建完常
        常再补一条 `todo log` 记接手第一步；把那条摆上去，人看到的是「说建好了，
        底下却是往已有条目上追加」——比不显示还糟。

        所以新建时认 `add`，追加时认 `log`；再退一步才认别的写命令。查重用的
        `todo list` 一律不算——摆上去像是「按了一下什么也没干」。
        """
        wanted = "add" if created else "log"
        preferred: list[str] | None = None
        fallback: list[str] | None = None

        for args in frago_invocations(events):
            if args[:1] != ["todo"] or len(args) < 2 or args[1] not in _WRITE_SUBCOMMANDS:
                continue
            if args[1] == wanted:
                preferred = ["frago", *args]
            else:
                fallback = ["frago", *args]
        return preferred or fallback
