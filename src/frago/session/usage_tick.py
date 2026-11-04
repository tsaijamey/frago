"""会话用量刻度与月历统计的唯一口径。

一条 ``usage.tick`` 记录 = 会话记录流里的一道刻度。它在**每一次模型调用返回、档案里
新出现一份用量之后**插进流里，只报两个数。两个数不是一回事，NEVER 混着算：

- **上下文**（``context_tokens``）是一个**水位**：这一次请求送进去的提示词有多大。
  它随对话涨上去，也随一次压缩掉下来。所以它不累加——累加出来的数没有任何含义。
- **累计**（``total_tokens``）是一道**流水**：从这场会话第一次调用起，每一轮消耗的
  token 加起来。

一轮消耗 = 输入 + 输出 + 缓存写入 + 缓存读取。**缓存读取算在里面**：那些 token 确实
被模型读了一遍，也确实计费（只是便宜）。把它扣掉得到的是另一个数，不是这个数。

五家内核（Claude Code、CoreAgent、Antigravity ``agy``、Codex、OpenCode）的原始用量字段
各不相同，统一在本模块换算成四个互不重叠的分项（``input`` / ``output`` / ``cache_creation`` /
``cache_read``）：

- **Claude Code / CoreAgent**（``message.usage``）：四项原本就分开记，直接按字段名取。
- **Antigravity ``agy``**（``PLANNER_RESPONSE`` 顶层字段）：``input_tokens``（已扣缓存读取的新输入）、
  ``output_tokens``、``cache_read_tokens``；无 ``cache_creation``，恒补 0。
- **Codex**（``token_count`` 的 ``last_token_usage``）：``input_tokens`` 是含缓存读取与缓存写入的
  提示词总长，故 ``input = max(input_tokens - cached_input_tokens - cache_write_input_tokens, 0)``；
  ``output_tokens`` 已含 ``reasoning_output_tokens``，不另加。
- **OpenCode**（``step-finish`` 片段的 ``tokens``）：``input`` 是新输入，``output`` 与 ``reasoning``
  分开记故相加归入 ``output``，``cache.write`` 与 ``cache.read`` 分别归入缓存写入与读取。

单场会话记录流与用量月历（:mod:`frago.session.token_calendar`）共用本模块的四个换算函数——
同一场会话在两处看到的数对不上，人两个都不会信。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "CLAUDE_USAGE_KEYS",
    "PROMPT_FIELDS",
    "USAGE_FIELDS",
    "breakdown_from_agy_record",
    "breakdown_from_claude_usage",
    "breakdown_from_codex_usage",
    "breakdown_from_opencode_tokens",
    "build_tick",
    "empty_breakdown",
]

#: 四个分项在统一记录里叫什么 → Claude Code / CoreAgent 原始 ``usage`` 里叫什么。
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
    """Claude Code / CoreAgent 的 ``message.usage`` → 四个分项。

    缺项按 0 补，不缺席——缺项和零在界面上长得一样，但"没报"和"是零"是两回事，这里
    统一收敛成零，由调用方靠"整份用量在不在"判有无。
    """
    out = empty_breakdown()
    for field, key in CLAUDE_USAGE_KEYS.items():
        value = usage.get(key)
        if isinstance(value, int | float):
            out[field] = int(value)
    return out


def breakdown_from_agy_record(record: dict[str, Any]) -> dict[str, int] | None:
    """agy 的模型回复记录 → 四个分项。这一条没带用量时返回 None。

    agy 把三个数分开记：``input_tokens`` 是这次真正新送进提示词的、``cache_read_tokens``
    是命中缓存的那部分、``output_tokens`` 是它写出来的。前两个相加才是上下文水位——
    与 claude 那边的口径一致，缓存读取算在里面（那些 token 确实被模型读了一遍）。

    ``cache_creation`` 恒为 0：agy 的转录里没有这一项。**键留着、值给 0**，不是省掉——
    四个分项在界面上按固定顺序摆，少一个键那一格看起来像"没读到"。
    """
    if not isinstance(record.get("input_tokens"), int | float) and not isinstance(
        record.get("output_tokens"), int | float
    ):
        return None

    def n(key: str) -> int:
        value = record.get(key)
        return int(value) if isinstance(value, int | float) else 0

    return {
        "input": n("input_tokens"),
        "output": n("output_tokens"),
        "cache_creation": 0,
        "cache_read": n("cache_read_tokens"),
    }


def breakdown_from_codex_usage(last: dict[str, Any]) -> dict[str, int]:
    """codex 的 ``last_token_usage`` → 四个分项。

    codex 的 ``input_tokens`` 把缓存命中的（``cached_input_tokens``）与缓存写入的
    （``cache_write_input_tokens``）都包在里面，所以"新输入"要把这两项都减掉，否则同一批
    token 在两格里各数一遍，四项之和也会比 ``total_tokens`` 大出一截。``output_tokens``
    已经含了 ``reasoning_output_tokens``，不另加。
    """

    def n(key: str) -> int:
        value = last.get(key)
        return int(value) if isinstance(value, int | float) else 0

    cached = n("cached_input_tokens")
    cache_write = n("cache_write_input_tokens")
    return {
        "input": max(n("input_tokens") - cached - cache_write, 0),
        "output": n("output_tokens"),
        "cache_creation": cache_write,
        "cache_read": cached,
    }


def breakdown_from_opencode_tokens(tokens: dict[str, Any]) -> dict[str, int] | None:
    """opencode 的步骤用量 → 统一记录那四个分项。一个数都报不出时返回 None。

    形状是 ``{"input":…, "output":…, "reasoning":…, "cache":{"read":…,"write":…}}``。
    **推理那一段不另立一格**：它是输出的一部分，单摆出来会让四项之和对不上本轮那个数。
    """

    def n(source: dict[str, Any], key: str) -> int:
        value = source.get(key)
        return int(value) if isinstance(value, int | float) else 0

    cache = tokens.get("cache")
    cache = cache if isinstance(cache, dict) else {}
    breakdown = {
        "input": n(tokens, "input"),
        "output": n(tokens, "output") + n(tokens, "reasoning"),
        "cache_creation": n(cache, "write"),
        "cache_read": n(cache, "read"),
    }
    return breakdown if any(breakdown.values()) else None


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
