"""本机这一侧的全部动作：发起、加入、退出、投消息、读对方、跑一轮同步。

**一轮同步做两件事**：把自己会话从上次推到哪儿之后的新记录推给中继，再把对方投来的
消息取下来交给调用方投进本机会话。

顺序是「先推后收」，不是随便定的：对方的 agent 常常是看了这边最新的进展才决定说什么，
先把自己这边的新内容送上去，对方下一轮读到的就是当下的。反过来先收后推，对方永远看
的是上一轮的旧状态。

**每次说话都带两样东西**：这台机器的指纹，和进场时领到的钥匙。连接码只在发起和加入
时用一次——它是入场券，转交给对方的那张；钥匙留在本机，证明「我就是已经坐在这一侧的
那台机器」。券可能在转交途中被人看见，钥匙不会。

**投递交给调用方。** 把一句话送进正在跑的会话要驱动 tmux，那是服务层的事。这里只把
取下来的消息连同前缀交出去——这条分界让整个包在没有服务端的地方也能引用与测试。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from frago.session import record_reader
from frago.team.relay import RelayClient, RelayError
from frago.team.state import (
    DEFAULT_PUSH_BATCH,
    DELIVERED_KEPT,
    TeamBinding,
    TeamState,
    render_prefix,
    save_state,
)

logger = logging.getLogger(__name__)

__all__ = [
    "SyncOutcome",
    "TeamRefused",
    "join_team",
    "leave_team",
    "open_team",
    "peer_records",
    "send_to_peer",
    "sync_once",
    "team_status",
]


class TeamRefused(RuntimeError):
    """中继那边不接受这个动作，而且这不是网络问题。

    与 :class:`~frago.team.relay.RelayError` 分开：那一类是「没说上话」，这一类是
    「说上了，对方说不行」。两者的下一步动作完全不同——前者重试有意义，后者重试只是
    把同一句拒绝再听一遍。
    """


@dataclass
class SyncOutcome:
    """一轮同步做成了什么。给日志和 ``frago team sync`` 的输出用。"""

    code: str
    pushed: int = 0
    delivered: int = 0
    skipped: int = 0
    peer_present: bool = False
    note: str = ""


# ── 结成 team ──────────────────────────────────────────────────────────


def open_team(state: TeamState, session_id: str) -> TeamBinding:
    """发起一个 team。

    中继当场把连接码和这一侧的钥匙一起给回来：码是发给对方的入场券，钥匙留在本机。
    """
    client = RelayClient(state.relay)
    got = client.call("open", fingerprint=state.member)
    code = str(got.get("code") or "")
    if not code:
        raise TeamRefused("中继没给出连接码，这个地址可能不是一台 frago 中继")
    binding = TeamBinding(
        code=code, session_id=session_id, side="A", secret=str(got.get("secret") or "")
    )
    state.teams[code] = binding
    save_state(state)
    return binding


def join_team(state: TeamState, code: str, session_id: str) -> TeamBinding:
    """用连接码加入别人发起的 team。

    同一台机器断线回来、重启之后再来，算恢复原来那一侧，不算第三台——中继按指纹认人，
    认得出是老面孔，但还要看它拿不拿得出当初那把钥匙。
    """
    code = code.strip().upper()
    client = RelayClient(state.relay)
    known = state.teams.get(code)
    got = client.call(
        "join",
        code=code,
        fingerprint=state.member,
        secret=(known.secret if known else ""),
    )
    side = got.get("side")
    if side not in ("A", "B"):
        raise TeamRefused(f"中继没说本机落在 {code} 的哪一侧")
    binding = TeamBinding(
        code=code,
        session_id=session_id,
        side=str(side),
        secret=str(got.get("secret") or ""),
    )
    state.teams[code] = binding
    save_state(state)
    return binding


def leave_team(state: TeamState, code: str) -> str:
    """退出这个 team。

    只有这一侧退出时连接码**仍然有效**：这是为了兜住网络断开——断线的人回来还接得上。
    两侧都退出，中继那边才把这个码作废。

    **本机这一侧先落定，中继通不通只决定对方多久才知道。**

    「我不干了」是这台机器自己的决定，不需要任何人批准。从前这里先敲中继、敲不通就整个
    失败，于是一个中继早已扫掉的旧 team——码过期、服务器重装过、网断了——在本机永远退不
    掉：人点一次退出，界面原地不动，只多一行「这个连接码在中继上不可用」的红字，再点还是
    那样。越是中继不认识它，越该让它从本机消失，而那时的行为恰好相反。

    「两侧都退出才作废」说的是中继那边何时销号，不是本机能不能退——这两件事从前被绑成
    了一件。

    告诉中继仍然要做，只是挪到后面，而且它失败不改变结果。返回说明是哪一种：``done``
    两边都知道了，``local-only`` 只有本机知道，调用方据此决定要不要提醒「对方那边可能
    还显示你在」。
    """
    binding = state.require(code)
    binding.active = False
    save_state(state)

    try:
        _call(state, binding, "leave")
    except (RelayError, TeamRefused, LookupError) as err:
        # 中继那边没销号。对方会看到「队友在」再挂一阵，直到它自己超时——这是一个会
        # 自己愈合的小偏差，而「本机退不掉」不会自己好。
        logger.info("退出 %s 时没能通知中继：%s", code, err)
        return "local-only"
    return "done"


# ── 隔着中继说话 ────────────────────────────────────────────────────────


def _call(state: TeamState, binding: TeamBinding, action: str, **params: Any) -> dict:
    """带着指纹和钥匙敲一次门。进场之后每一次都走这里。"""
    client = RelayClient(state.relay)
    return client.call(
        action,
        code=binding.code,
        fingerprint=state.member,
        secret=binding.secret,
        **params,
    )


def send_to_peer(state: TeamState, code: str, text: str, note: str = "") -> None:
    """往对方的会话投一条消息。

    **前缀不在这里加。** 中继只运原文，前缀由收的那一侧按自己的设置加上——两边对
    「队友的 agent 在跟我说话」想看到的措辞不一样，而措辞是收的人的事。
    """
    if not text.strip():
        raise TeamRefused("要投的消息是空的")
    binding = state.require(code)
    if not binding.active:
        raise TeamRefused(f"本机已经退出 {code} 了，先 frago team join --team-code {code}")
    _call(state, binding, "send", text=text, note=note)


def peer_records(
    state: TeamState, code: str, limit: int = 80, after_seq: int | None = None
) -> list[dict[str, Any]]:
    """读对方会话的记录。这是「远程的 read 动作」。"""
    binding = state.require(code)
    params: dict[str, Any] = {"limit": limit}
    if after_seq is not None:
        params["after_seq"] = after_seq
    got = _call(state, binding, "peer", **params)
    records = got.get("records")
    return records if isinstance(records, list) else []


def team_status(state: TeamState, code: str) -> dict[str, Any]:
    """这个连接码现在什么状态。"""
    binding = state.require(code)
    return _call(state, binding, "status")


# ── 一轮同步 ────────────────────────────────────────────────────────────


def sync_once(
    state: TeamState,
    binding: TeamBinding,
    deliver: Callable[[str], None],
    *,
    batch: int = DEFAULT_PUSH_BATCH,
) -> SyncOutcome:
    """跑一轮：先把自己这边的新记录推上去，再把对方投来的消息交给 ``deliver``。

    ``deliver`` 收到的是**已经加好前缀的整段话**，直接投进会话即可。
    """
    outcome = SyncOutcome(code=binding.code)

    try:
        outcome.pushed = _push_records(state, binding, batch)
    except RelayError as err:
        # 推不上去不该让收消息那一半也停——对方可能正等着这边回话。
        outcome.note = str(err)

    got = _call(state, binding, "pull")
    messages = got.get("messages")
    outcome.peer_present = bool(got.get("peer_present", True))
    if not isinstance(messages, list) or not messages:
        return outcome

    already = set(binding.delivered)
    for one in messages:
        if not isinstance(one, dict):
            continue
        mid = str(one.get("id") or "")
        text = str(one.get("text") or "")
        if not mid or not text:
            continue
        if mid in already:
            outcome.skipped += 1
            continue
        prefix = render_prefix(state.prefix, binding.code)
        try:
            deliver(f"{prefix}\n\n{text}")
        except Exception:
            logger.warning(
                "team %s：消息 %s 没能投进会话 %s",
                binding.code, mid, binding.session_id, exc_info=True,
            )
            continue
        outcome.delivered += 1
        binding.delivered.append(mid)

    binding.delivered = binding.delivered[-DELIVERED_KEPT:]
    save_state(state)
    return outcome


def _push_records(state: TeamState, binding: TeamBinding, batch: int) -> int:
    """把本机这场会话从上次推到哪儿之后的新记录送上去，返回送了几条。

    游标是记录在会话里的序号，不是下标——会话被重新解析后序号会变，所以中继那边按
    序号覆盖同名的记录而不是追加。推一批就把游标落盘：中途断了，下一轮从断点接着推。

    **一条新记录都没有时也要敲一下。** 心跳就搭在这上面，不发的话中继二十四小时后
    会把这个 team 当成没人要的清掉。
    """
    try:
        records = record_reader.read_records(
            binding.session_id, after=binding.pushed_seq + 1, limit=batch
        )
    except Exception:
        # 会话被删了、编号形状不认得了——这一侧推不上去，但收消息那一半还能用，
        # 所以这个 team 不该因此被判死。心跳照发。
        logger.warning(
            "team %s：读不到会话 %s 的记录",
            binding.code, binding.session_id, exc_info=True,
        )
        _call(state, binding, "push", records=[])
        return 0
    if not records:
        _call(state, binding, "push", records=[])
        return 0

    payload = [asdict(one) for one in records]
    _call(state, binding, "push", records=payload)
    binding.pushed_seq = max(one.seq for one in records)
    save_state(state)
    return len(payload)
