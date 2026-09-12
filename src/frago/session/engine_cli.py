"""让引擎用自己的命令删掉自己的一场会话。

三家各有一个「会话躺在哪儿」的答案，其中两家的答案不是一个文件。opencode 把会话摊在
一张 SQLite 库的七张表里（``message`` / ``part`` / ``todo`` / ``session_share`` /
``session_message`` / ``session_input`` / ``session_context_epoch``），另有一张十一万行的
事件流水按会话编号分片。codex 更散，会话数据横跨 ``state_5.sqlite``、
``thread_history_1.sqlite``、``history.jsonl`` 与 ``sessions/`` 下的 rollout 文件，而且
这几个落点随版本改过——``codex migrate-rollouts`` 这个命令本身就是一次迁移的产物。

对着一本别人的库手写 ``DELETE``，赌的是「我读到的表结构就是它此刻的表结构」。赌输的
样子很难看：**这个库默认不强制外键**（``PRAGMA foreign_keys`` 为 0），漏掉的子表不会
报错，只会留下一堆谁也指不到的行；事件流水的序列号对不上时，坏的是引擎自己的同步，
而这一切在界面上都表现为「删干净了」。所以另两家一律借引擎自己的删除命令：它怎么存就
怎么删，它换了版本也不用跟着改。

Claude Code 不走这条路。它的记录就是一个 JSONL 加一个同名目录，位置稳定、格式公开，
直接删干净，不必为它起一个进程——见
:func:`frago.session.adapters.claude_code_records.delete_session_files`。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from frago.compat import find_agent_cli, get_windows_subprocess_kwargs

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_TIMEOUT",
    "EngineCliFailed",
    "EngineCliMissing",
    "run_engine_command",
]

DEFAULT_TIMEOUT = 60.0
"""一条删除命令最多等多久。

删一场大会话要引擎扫库、清事件流水，慢起来几十秒是正常的；再长就不是慢，是卡住了。
"""

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class EngineCliMissing(RuntimeError):
    """这台机器上找不到那个引擎的命令行。"""


class EngineCliFailed(RuntimeError):
    """命令跑起来了，但它自己说没删成。

    ``output`` 是它原样吐出来的那句话——拒绝的理由只有它知道，NEVER 由我们转述。
    """

    def __init__(self, message: str, output: str = "") -> None:
        super().__init__(message)
        self.output = output


@dataclass(frozen=True)
class EngineCommandResult:
    """一条引擎命令跑完的样子。"""

    argv: list[str]
    output: str
    """它吐出来的话，ANSI 颜色已剥掉。失败时这里就是它给的拒绝理由。"""


def run_engine_command(
    agent: str, argv: list[str], *, timeout: float = DEFAULT_TIMEOUT
) -> EngineCommandResult:
    """跑一条引擎命令，要它把话说出来。

    ``output`` 把标准输出与标准错误合在一处。这两个引擎的报错走标准错误、确认话走
    标准输出，分开收的话调用方得猜哪边才是人想看的那句——真话在哪边只有它们自己知道，
    收的人不该替它们选。

    **两种失败分开抛。** 找不到命令抛 :class:`EngineCliMissing`（这台机器没装这个
    引擎）；跑了但非零退出抛 :class:`EngineCliFailed`，把它的话带在 ``output`` 里
    （引擎拒绝了这次删除）。人在这两种情况要做的事完全不同，界面上的下一步也不同。

    输入掐断：这两个命令都不该向人提问，把标准输入接到空设备上，免得有一条路悄悄
    挂在那儿等人打字，而这边只看得到一个超时。

    工作目录定在家目录。删会话与当前目录无关，别让 frago 的工作目录渗进去——engine
    若按目录决定删的是哪一份记录，这里就到了另一个仓库。
    """
    binary = find_agent_cli(agent)
    if not binary:
        raise EngineCliMissing(f"这台机器上找不到 {agent} 命令，删不了它的会话")

    full_argv = [binary, *argv]
    try:
        proc = subprocess.run(
            full_argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(Path.home()),
            timeout=timeout,
            check=False,
            **get_windows_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        raise EngineCliFailed(
            f"{agent} 这条命令超过 {timeout:g} 秒没回来，没法确定删掉没有"
        ) from exc
    except OSError as exc:
        raise EngineCliMissing(f"{agent} 命令起不来：{exc}") from exc

    output = _ANSI.sub("", (proc.stdout or b"").decode("utf-8", "replace")).strip()
    if proc.returncode != 0:
        raise EngineCliFailed(f"{agent} 没删掉：{output or f'退出码 {proc.returncode}'}", output)
    return EngineCommandResult(argv=full_argv, output=output)
