"""关键词 → 目录名的模糊匹配。纯函数，不碰文件系统。

## 为什么不是简单的 substring

``~/.frago/data`` 下的目录名是人（和 agent）随手起的语义名，形态高度不齐：
``20260725-cxmt-ipo-video``（带日期前缀）、``etf-dma-trading-plan``（纯语义）、
``hook_rules_dashboard``（下划线）、``gopro-采集-方案``（中英混排）。

agent 记住的往往是其中一小段（``cxmt``）、几个不连续的词（``session workbench``）、
或者一个记岔了半个字母的词。单靠 ``in`` 判断，前两种能中，第三种一定落空；
而全靠编辑距离，``etf`` 会跟一堆八竿子打不着的短名字算出高分。

所以用分层：先试确定性最强的判据（完全相同 → 前缀 → 子串 → 全词覆盖），
一层命中就定分，都不中才落到 difflib 的相似度兜底。分数区间不重叠，
排序结果因此是可解释的——agent 看见 ``substring`` 和 ``similar`` 就知道
后者是猜出来的，值得再确认一眼。

## 归一化

比较前统一：转小写、把一切非字母数字（含 CJK 之外的符号）折成单个连字符、
去掉首尾连字符。``Hook_Rules Dashboard`` 与 ``hook-rules-dashboard`` 因此等价。
CJK 字符保留原样并各自成字，中文关键词按子串匹配自然生效。

日期前缀（``20260725-`` 这种 6~8 位数字加连字符）在比较时另存一份剥掉的版本：
人记的是 ``cxmt-ipo-video``，NEVER 是那串日期。
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

# 判据分层。区间刻意不重叠：同一个候选只会落在一层里，排序时层级永远压过层内差异。
SCORE_EXACT = 100
SCORE_PREFIX = 90
SCORE_SUBSTRING = 80
SCORE_ALL_TOKENS = 70
SCORE_SUBSEQUENCE = 60
# 相似度兜底的满分。乘 ratio 后落在 [0, 60]，与 SUBSEQUENCE 同顶但恒不超过它，
# 因为 ratio 达到 1.0 时 EXACT 早已命中。
SCORE_SIMILAR_MAX = 60

# 相似度低于这条线就当没匹配上。0.6 是 difflib 文档给的"大致算像"的经验值，
# 再低会把 etf 和 fengsu 这种毫不相干的短名字也算进来。
SIMILAR_FLOOR = 0.6

# 低于此分一律不算候选（= SIMILAR_FLOOR × SCORE_SIMILAR_MAX，取整）。
MIN_SCORE = 36

# 按序匹配的两道松紧闸，理由见 _is_tight_subsequence。
_MIN_SUBSEQUENCE_LEN = 3
_SUBSEQUENCE_SPAN_FACTOR = 2

_DATE_PREFIX = re.compile(r"^\d{6,8}-")
_NON_WORD = re.compile(r"[^0-9a-z一-鿿]+")


def normalize(text: str) -> str:
    """转小写、非字母数字折成单连字符、去首尾连字符。"""
    return _NON_WORD.sub("-", text.lower()).strip("-")


def strip_date_prefix(normalized: str) -> str:
    """剥掉 ``20260725-`` 这类日期前缀；没有前缀时原样返回。"""
    return _DATE_PREFIX.sub("", normalized)


def tokens(normalized: str) -> list[str]:
    """按连字符切词，丢掉空片段。"""
    return [t for t in normalized.split("-") if t]


def _is_tight_subsequence(needle: str, haystack: str) -> bool:
    """needle 的字符能否按序（可不连续）、且落在一段够紧凑的区间里找齐。

    这是 fzf 那套匹配的最小内核，管的是缩写和漏字：``sesswrkbench`` 命中
    ``session-workbench``，而 difflib 对这种大段缺失给的分数很低。

    松紧度是必须的。裸的按序匹配几乎什么都能中——``video`` 的五个字母能在
    ``voice-desktop-pet`` 里逐个找到，跨度铺满整个名字，结果是每次多命中一堆
    毫不相干的目录，agent 得自己筛。所以要求命中区间不超过关键词长度的两倍：
    真缩写的字母是挤在一起的，碰巧撞上的不是。
    """
    if len(needle) < _MIN_SUBSEQUENCE_LEN:
        return False
    first = last = -1
    pos = 0
    for ch in needle:
        found = haystack.find(ch, pos)
        if found < 0:
            return False
        if first < 0:
            first = found
        last = found
        pos = found + 1
    return (last - first + 1) <= len(needle) * _SUBSEQUENCE_SPAN_FACTOR


@dataclass(frozen=True)
class Candidate:
    """一个候选目录名及其命中理由。"""

    name: str
    """原始目录名（未归一化），调用方据此定位。"""

    score: int
    """0~100。见模块头部的分层说明。"""

    reason: str
    """哪一层判据命中，写给 agent 看的自然语言标签。"""

    @property
    def is_exact(self) -> bool:
        """完全同名。目录名在同一层级下唯一，故这类候选至多一个。"""
        return self.score == SCORE_EXACT


def score_name(query: str, name: str) -> Candidate | None:
    """给单个名字打分。低于 :data:`MIN_SCORE` 返回 None。"""
    norm_q = normalize(query)
    if not norm_q:
        return None
    norm_name = normalize(name)
    bare = strip_date_prefix(norm_name)

    if norm_q in (norm_name, bare):
        return Candidate(name, SCORE_EXACT, "完全同名")
    if bare.startswith(norm_q) or norm_name.startswith(norm_q):
        return Candidate(name, SCORE_PREFIX, "名字以关键词开头")
    if norm_q in norm_name:
        return Candidate(name, SCORE_SUBSTRING, "名字含关键词")

    q_tokens = tokens(norm_q)
    if q_tokens and all(t in norm_name for t in q_tokens):
        return Candidate(name, SCORE_ALL_TOKENS, "关键词的每个词都在名字里")

    stripped_q = norm_q.replace("-", "")
    if _is_tight_subsequence(stripped_q, norm_name.replace("-", "")):
        return Candidate(name, SCORE_SUBSEQUENCE, "关键词字符按序出现（缩写/漏字）")

    ratio = difflib.SequenceMatcher(None, norm_q, bare).ratio()
    if ratio >= SIMILAR_FLOOR:
        return Candidate(
            name,
            int(ratio * SCORE_SIMILAR_MAX),
            f"名字相似（{ratio:.0%}，可能是拼写差异）",
        )
    return None


def match_names(query: str, names: list[str]) -> list[Candidate]:
    """给一批名字打分并排序，只留够分的。

    排序键是 ``(-score, name)``：分数优先，同分按名字排以保证结果稳定可复现。
    调用方拿到 mtime 之后可以再按时间重排同分组。
    """
    scored = [c for c in (score_name(query, n) for n in names) if c is not None]
    return sorted(
        [c for c in scored if c.score >= MIN_SCORE],
        key=lambda c: (-c.score, c.name),
    )
