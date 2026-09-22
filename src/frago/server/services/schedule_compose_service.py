"""一句话建一条定时任务：把描述交给 frago 自带的那个小 agent，由它去跑 `frago schedule add`。

界面上的「新建」只收一句话，比如「每天早上九点看一眼磁盘剩多少，满了推飞书」。
一条定时任务需要的其余部分——是配方、shell 命令还是自然语言任务，多久跑一次，
通知推到哪——由 agent 补齐。

**为什么不在这里直接写 schedules.json。** `schedule add` 自带一整套校验：配方得
真的存在、cron 表达式得解析得过、通知落点得是已配置的 channel、三种形态只能给
一种。抄一份到这里，两边迟早对不上账；让 agent 走命令行，这些规矩一条不落。

跑 agent 的那几步（找内核、查模型配置、读内核的 JSON 输出）与事务页的「添一件」
完全相同，直接借 :mod:`todo_compose_service` 的实现，这里只管任务书和怎么认出
「建出了哪一条」。

**它可能不新建。** 描述的事情已经有一条定时任务了，任务书要求 agent 不再开第二条。
这时返回里的 ``schedule_id`` 为 None，``message`` 里是它自己的说法。
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

from frago.server.services.todo_compose_service import (
    TIMEOUT_SECONDS,
    TodoComposeError,
    TodoComposeService,
    frago_invocations,
)

_ALLOWED_TOOLS = [
    arg
    for rule in (
        "Bash(frago schedule list:*)",
        "Bash(frago schedule add:*)",
        "Bash(frago recipe list:*)",
        "Bash(frago channel list:*)",
    )
    for arg in ("--allowed-tools", rule)
]

# 查一遍现有任务、确认配方或通知落点、再落一次命令，比建事务多一两步。
MAX_ROUNDS = 10

# 这一场在会话页左栏叫什么。固定一句，理由同 todo_compose_service 里那一处。
_SESSION_TITLE = "定时任务拟稿"

# `frago schedule add` 成功时打的那行。id 是服务层随机生成的，只能从输出里读。
_CREATED_RE = re.compile(r"Schedule created:\s+(\S+)")

# 交给 agent 的任务书。用户原话夹在分隔符里，免得里面的指令样式的句子把任务书搅乱。
# 开头那句「不要读任何手册」的来由见 todo_compose_service 里同一句的注释。
_PROMPT = """\
这是一次程序调用，不是对话。不要读任何手册（不要跑 frago book），不要研究输出格式
——直接把事情办了。

把下面这段用户描述登记成一条 frago 定时任务，现在就用 frago schedule add 真正执行，
不要只给建议。

用户描述原文：
<<<DESCRIPTION
{description}
DESCRIPTION

怎么办：
1. 先跑一次 frago schedule list，同样的任务已经有了就不要再建，说明是哪一条。
2. 定形态，三选一：
   - 描述里点名了某个配方：先 frago recipe list 确认它存在，写成 frago schedule add <配方名>
   - 一条 shell 命令就能做完的：--command "<命令>"
   - 需要理解和判断的：--prompt "<自然语言任务>"
3. 时间用 --every（30s / 10m / 2h）或 --cron（五段式），二者只给一个。
4. 时限用 --timeout（秒），不给就是 7200 秒（2 小时），到点整次运行被掐掉、算失败。
   拿不准就不写，默认的 2 小时对绝大多数活够用；明显要跑过 2 小时的才显式写大。
   命令和配方跑得快，想卡紧一点可以按实际耗时显式给。
5. 用 --name 给一个简短的中文名字。
6. 通知：描述里没说推到哪，就写 --notify-on never。说了推到某处，先 frago channel list
   确认那个 channel 存在，再写 --notify-to；本机系统通知写 desktop。

办完用一两句中文说明你建了什么，并把 frago schedule add 输出里的 id 写出来。
"""


class ScheduleComposeService:
    """把一句话变成一条定时任务。"""

    @staticmethod
    def compose(description: str) -> dict[str, Any]:
        """交给 agent 去建，返回它建出了什么。

        Returns:
            ``{"schedule_id", "message", "command"}``。agent 跑完却没建出任何
            一条时 ``schedule_id`` 为 None。

        Raises:
            TodoComposeError: 模型没配好、内核不在、超时，或者 agent 非零退出。
        """
        text = description.strip()
        if not text:
            raise TodoComposeError("描述是空的")

        TodoComposeService._require_model()
        binary = TodoComposeService._binary_path()

        # 编号在这里现发（不发就贴不上名字、归不了组），名字固定，与「待办拟稿」同一个
        # 道理：这条路上每一场干的都是同一件事。
        from frago.server.services import coreagent_runner

        session_id = coreagent_runner.start_local_ops(_SESSION_TITLE)

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
            # 建定时任务只需要查现有任务、查配方、查 channel、落一条 add。
            *_ALLOWED_TOOLS,
        ]

        try:
            proc = ScheduleComposeService._run(cmd)
        except subprocess.TimeoutExpired as exc:
            raise TodoComposeError(f"agent 跑了 {TIMEOUT_SECONDS} 秒还没结束，已放弃") from exc

        events = TodoComposeService._parse_events(proc.stdout or "")

        if proc.returncode != 0:
            detail = (proc.stderr or "").strip().splitlines()
            reason = detail[-1] if detail else f"exit code {proc.returncode}"
            raise TodoComposeError(f"agent 没能完成：{reason}", transcript=proc.stdout or "")

        return {
            "schedule_id": ScheduleComposeService._extract_schedule(events),
            "message": TodoComposeService._final_text(events),
            "command": ScheduleComposeService._add_command(events),
        }

    @staticmethod
    def _run(cmd: list[str]) -> subprocess.CompletedProcess:
        # 单独留一个入口，用例替掉这一步就不会真起进程。
        return TodoComposeService._run(cmd)

    @staticmethod
    def _extract_schedule(events: list[dict[str, Any]]) -> str | None:
        """从工具回显里认出新建的那条定时任务。建了不止一条时报最后那条。"""
        found: str | None = None
        for event in events:
            if event.get("type") != "result":
                continue
            output = event.get("output")
            if not isinstance(output, str):
                continue
            match = _CREATED_RE.search(output)
            if match:
                found = match.group(1)
        return found

    @staticmethod
    def _add_command(events: list[dict[str, Any]]) -> list[str] | None:
        """它替人敲下去的那条 `schedule add`。查重用的 list、查配方用的 recipe list 不算。"""
        found: list[str] | None = None
        for args in frago_invocations(events):
            if args[:2] == ["schedule", "add"]:
                found = ["frago", *args]
        return found
