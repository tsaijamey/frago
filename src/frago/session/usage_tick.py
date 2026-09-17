"""会话用量刻度：界面上那两个数的唯一口径。

一条 ``usage.tick`` 记录 = 会话记录流里的一道刻度。它在**每一次模型调用返回、档案里
新出现一份用量之后**插进流里，只报两个数。两个数不是一回事，NEVER 混着算：

- **上下文**（``context_tokens``）是一个**水位**：这一次请求送进去的提示词有多大。
  它随对话涨上去，也随一次压缩掉下来。所以它不累加——累加出来的数没有任何含义。
- **累计**（``total_tokens``）是一道**流水**：从这场会话第一次调用起，每一轮消耗的
  token 加起来。

一轮消耗 = 输入 + 输出 + 缓存写入 + 缓存读取。**缓存读取算在里面**：那些 token 确实
被模型读了一遍，也确实计费（只是便宜）。把它扣掉得到的是另一个数，不是这个数。

口径与用量月历（:mod:`frago.session.token_calendar`）逐字相同，四个分项的名字也共用
:data:`CLAUDE_USAGE_KEYS` 这一份——同一场会话在两处看到的数对不上，人两个都不会信。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "CLAUDE_USAGE_KEYS",
    "PROMPT_FIELDS",
    "USAGE_FIELDS",
    "breakdown_from_claude_usage",
    "build_tick",
    "empty_breakdown",
]

#: 四个分项在统一记录里叫什么 → Claude Code 原始 ``usage`` 里叫什么。
CLAUDE_USAGE_KEYS: dict[str, str] = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_creation": "cache_creation_input_tokens",
    "cache_read": "cache_read_input_tokens",
}

USAGE_FIELDS: tuple[str, ...] = ("input", "output", "cache_creation", "cache_read")
"""四个分项的固定顺序。界面照这个顺序摆，两处不许各排各的。"""

PROMPT_FIELDS: tuple[str, ...] = ("input", "cache_creation", "cache_read")
"""算上下文水位时数哪几项：提示词那一侧的全部，输出不算。

输出那一段要到**下一次**请求才进得了上下文，这一刻它还没在里面。把它算进来会让水位
凭空高出一截，而那一截在界面上没有任何东西解释得了。
"""


def empty_breakdown() -> dict[str, int]:
    return dict.fromkeys(USAGE_FIELDS, 0)


def breakdown_from_claude_usage(usage: dict[str, Any]) -> dict[str, int]:
    """Claude Code 的 ``message.usage`` → 四个分项。

    缺项按 0 补，不缺席——缺项和零在界面上长得一样，但"没报"和"是零"是两回事，这里
    统一收敛成零，由调用方靠"整份用量在不在"判有无。
    """
    out = empty_breakdown()
    for field, key in CLAUDE_USAGE_KEYS.items():
        value = usage.get(key)
        if isinstance(value, int | float):
            out[field] = int(value)
    return out


def build_tick(
    breakdown: dict[str, int],
    *,
    total_before: int = 0,
    turn_tokens: int | None = None,
    total_tokens: int | None = None,
    context_tokens: int | None = None,
    context_window: int | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """拼一条 ``usage.tick`` 的载荷。

    ``total_before`` 是这场会话到上一条刻度为止的累计。三个 ``*_tokens`` 的显式入参
    是给**引擎自己就报了这个数**的那一家用的（codex 的 ``token_count`` 同时给了本次
    与累计）：引擎报的优先，我们算的只是没人报时的退路。两个数出自同一份原始记录，
    却一个照抄一个另算，对不上的时候没人解释得清。
    """
    turn = sum(breakdown.values()) if turn_tokens is None else turn_tokens
    if context_tokens is None:
        context_tokens = sum(breakdown.get(field, 0) for field in PROMPT_FIELDS)
    return {
        "context_tokens": context_tokens,
        "context_window": context_window,
        "turn_tokens": turn,
        "total_tokens": total_before + turn if total_tokens is None else total_tokens,
        "breakdown": dict(breakdown),
        "model": model,
    }
