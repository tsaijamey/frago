"""界面上按下「弃置」：把事务 id 和人填的理由交给 `frago todo drop` 去执行。

**为什么不在这里直接写文件。** 与「添一件」那一路同一条约束：事务的写入口只有命令
行一条（读接口那边写着为什么）。服务端只负责把人填的话原样递过去，真正落盘的是
`frago todo drop`——理由必填、已弃置的不许再弃置一次，这些规矩长在那条命令上，两边
各写一份迟早对不上账。

**为什么不像「添一件」那样交给 agent。** 建一件事务要把一句话摊成标题、背景、完成
判据，那是需要判断的活；弃置不需要：事务 id 是人点中的那一件，理由是人自己的原话。
交给模型只会多十几秒等待，还多一个它把理由改写一遍的机会——而理由是要留档给半年后
的人看的，必须一个字不差。

**参数用列表传，不拼命令行字符串。** 理由是人自由输入的一段话，里面有引号、分号、
反引号都很正常。拼成一行交给 shell，那些字符就成了命令的一部分。
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 一次本地文件读写，正常是毫秒级。给到 30 秒是留给机器卡顿，不是常态；到点没回来
# 就是出事了，界面得拿到一个明确的失败，而不是一直转圈。
TIMEOUT_SECONDS = 30


class TodoDropError(RuntimeError):
    """弃置没做成。``detail`` 是能直接给人看的那句原因。"""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class TodoDropService:
    """把一件事务弃置掉。"""

    @staticmethod
    def drop(todo_id: str, reason: str) -> dict[str, Any]:
        """执行弃置，返回界面要显示的三件事。

        Args:
            todo_id: 要弃置哪一件。命令那边认唯一前缀，界面给的是完整 id。
            reason: 人填的理由，原样转交。

        Returns:
            ``{"todo", "command"}``——弃置之后那件事务的全貌，以及实际执行的那条
            命令。后者摆给人看：看不见执行了什么的按钮，没人敢按第二次。

        Raises:
            TodoDropError: 理由是空的、事务不存在、它已经弃置过了，或者命令没跑成。
        """
        text = (reason or "").strip()
        if not text:
            # 命令那边也会拦，但空理由连子进程都不必起：这是界面上最常见的一种失手。
            raise TodoDropError("弃置理由是必填的：说清为什么不做了")
        if not todo_id:
            raise TodoDropError("没说要弃置哪一件")

        from frago.server.services.agent_service import _resolve_frago_cmd

        cmd = [*_resolve_frago_cmd(), "todo", "drop", todo_id, "--reason", text]

        try:
            proc = TodoDropService._run(cmd)
        except FileNotFoundError as exc:
            raise TodoDropError("找不到 frago 命令，服务端跑不动它") from exc
        except subprocess.TimeoutExpired as exc:
            raise TodoDropError(f"命令跑了 {TIMEOUT_SECONDS} 秒还没结束，已放弃") from exc

        if proc.returncode != 0:
            # 命令把拒绝的原因写在 stderr 最后一行（事务不存在、前缀撞了多条、它已经
            # 弃置过了）。那几句话本来就是写给人读的，原样带回去，别改写成别的说法。
            lines = [line for line in (proc.stderr or "").strip().splitlines() if line.strip()]
            reason_line = lines[-1] if lines else f"exit code {proc.returncode}"
            # 开头那个 "Error: " 是命令行自己加的前缀，不是话的一部分。界面上另有报错
            # 的样式，再顶一个 "Error:" 上去，人读到的是「错误：错误：……」。
            raise TodoDropError(reason_line.removeprefix("Error: "))

        return {"todo": TodoDropService._reload(todo_id), "command": cmd}

    @staticmethod
    def _run(cmd: list[str]) -> subprocess.CompletedProcess:
        """在用户自己的家目录里跑，与「添一件」那一路同一个现场。"""
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
    def _reload(todo_id: str) -> dict[str, Any]:
        """命令跑完之后重新读一遍那个文件，把结果给界面。

        不拿请求里的那点信息拼一份「应该变成什么样」交回去：落盘的是另一个进程，
        它记下的日期和理由才是真的。拼一份出来，界面显示的就可能与文件里不一致。
        """
        from dataclasses import asdict

        from frago.todo.store import get as get_todo

        try:
            return asdict(get_todo(todo_id))
        except (KeyError, ValueError) as exc:
            # 命令说成功了，回头却读不到——盘上出了别的事，如实说，别假装成功。
            raise TodoDropError(f"弃置执行完了，但读不回那件事务：{exc}") from exc
