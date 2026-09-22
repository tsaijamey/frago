"""``frago team`` —— vibe teaming 在命令行上的那一面。

这些命令是**给 agent 敲的**，不是给人敲的。所以每一条的输出都写成 agent 读完就知道
下一步做什么的样子：拿到连接码就把码摆在最显眼处，读对方上下文就直接把对话铺出来，
被拒绝就说清楚被谁拒绝、该改什么。

会话编号缺省取「当前这一场」。agent 在自己的会话里敲 ``frago team open``，它参加
这个 team 用的就是自己这一场——要它先去查自己的会话编号再填进来，是把一件本机已经
知道的事推给调用方。

分层：命令行层。可以 import ``team/``、``session/`` 与 ``server/services``。
"""

from __future__ import annotations

import json as jsonlib

import click

from frago.team import sync as team_sync
from frago.team.relay import RelayError
from frago.team.state import ensure_member, load_state, save_state


def _fail(message: str) -> None:
    raise click.ClickException(message)


def _current_session(given: str | None) -> str:
    """这次用哪一场会话。没指定就取当前这一场。"""
    if given:
        return given.strip()
    from frago.session.self_id import resolve_self

    me = resolve_self()
    if me is None:
        _fail(
            "认不出当前是哪一场会话，所以不知道该拿哪一场参加 team。"
            "用 --session <会话编号> 点名；编号用 frago session list 查"
        )
    return me.session_id


def _guard(action):
    """把中继那边的两类失败变成一句人能直接行动的话。"""
    try:
        return action()
    except (RelayError, team_sync.TeamRefused, LookupError) as err:
        _fail(str(err))


@click.group(name="team")
def team_group() -> None:
    """vibe teaming：跟另一个 frago 用户的会话结成一个 team。

    一方 open 拿到连接码，另一方 join 填这个码。此后两边的 agent 能读对方会话的
    上下文（team read），也能往对方的会话里投一条消息（team send）——落到对方那边
    是一条带前缀的用户发言，对方的 agent 照常响应。
    """


@team_group.command("config")
@click.option("--url", default=None, help="中继那台 frago 服务器的地址")
@click.option("--relay-default", is_flag=True, help="把中继地址改回出厂默认")
@click.option("--prefix", default=None,
              help="对方投来的消息落进本机会话时，前面加哪一句。可用 {code} 占位")
@click.option("--interval", type=int, default=None, help="两轮同步之间隔几秒")
def config_cmd(url, relay_default, prefix, interval) -> None:
    """看或改中继在哪。不带参数就打印现状。

    **不需要任何账号或口令。** 中继那扇门认的是连接码本身——两个想结对的人，手里
    只有一个码，不该为此在那台服务器上注册账号，更不该拿到那台机器的钥匙。
    """
    from frago.team.state import DEFAULT_RELAY_URL

    state = ensure_member()
    if relay_default:
        url = DEFAULT_RELAY_URL
    touched = False
    if url is not None:
        state.relay.url = url.strip()
        touched = True
    if prefix is not None:
        state.prefix = prefix
        touched = True
    if interval is not None:
        state.interval_seconds = max(int(interval), 5)
        touched = True

    if touched:
        save_state(state)

    click.echo(f"中继地址   {state.relay.url or '（还没配）'}")
    click.echo(f"本机指纹   {state.member}")
    click.echo(f"同步间隔   {state.interval_seconds} 秒")
    click.echo(f"投递前缀   {state.prefix}")
    if not state.relay.configured():
        click.echo("")
        click.echo("还没有中继地址。跑：frago team config --relay-default")


@team_group.command("open")
@click.option("--session", "session_id", default=None, help="拿哪一场会话参加，缺省是当前这一场")
def open_cmd(session_id) -> None:
    """发起一个 team，拿到连接码。"""
    state = load_state()
    sid = _current_session(session_id)
    binding = _guard(lambda: team_sync.open_team(state, sid))
    click.echo(f"连接码  {binding.code}")
    click.echo("")
    click.echo(f"本机这一侧是 {binding.side} 侧，参加的会话是 {binding.session_id}")
    click.echo(f"把这个码给对方，让对方跑：frago team join --team-code {binding.code}")


@team_group.command("join")
@click.option("--team-code", "code", required=True, help="对方给的连接码")
@click.option("--session", "session_id", default=None, help="拿哪一场会话参加，缺省是当前这一场")
def join_cmd(code, session_id) -> None:
    """用连接码加入别人发起的 team。"""
    state = load_state()
    sid = _current_session(session_id)
    binding = _guard(lambda: team_sync.join_team(state, code, sid))
    click.echo(f"已加入 {binding.code}，本机这一侧是 {binding.side} 侧")
    click.echo(f"参加的会话是 {binding.session_id}")
    click.echo("")
    click.echo(f"读对方在干什么：frago team read --team-code {binding.code}")
    click.echo(f"给对方派活：    frago team send --team-code {binding.code} \"...\"")


@team_group.command("leave")
@click.option("--team-code", "code", required=True)
def leave_cmd(code) -> None:
    """退出这个 team。

    只有本机退出时连接码仍然有效，这是为了兜住网络断开；两侧都退出，码才作废。
    """
    state = load_state()
    _guard(lambda: team_sync.leave_team(state, code))
    click.echo(f"已退出 {code}。对方还在的话，这个码仍然有效")


@team_group.command("send")
@click.option("--team-code", "code", required=True)
@click.argument("text", required=False)
@click.option("--text", "text_opt", default=None, help="要投的内容，与位置参数二选一")
@click.option("--note", default="", help="附一句说明，给人看的")
def send_cmd(code, text, text_opt, note) -> None:
    """往对方的会话投一条消息，它在对方那边是一条带前缀的用户发言。"""
    body = text_opt if text_opt is not None else text
    if not body:
        _fail("没写要投什么。用法：frago team send --team-code XXXXXX \"请你做……\"")
    state = load_state()
    _guard(lambda: team_sync.send_to_peer(state, code, body, note))
    click.echo(f"已投给 {code} 的对方。对方下一轮同步时它会落进对方的会话")


@team_group.command("read")
@click.option("--team-code", "code", required=True)
@click.option("--limit", type=int, default=80, show_default=True, help="取最近几条")
@click.option("--after-seq", type=int, default=None, help="只要这个序号之后的（增量取）")
@click.option("--json", "as_json", is_flag=True, help="输出原始记录，给程序读")
def read_cmd(code, limit, after_seq, as_json) -> None:
    """读对方会话的上下文。这是隔着中继的一次远程 read。"""
    state = load_state()
    records = _guard(lambda: team_sync.peer_records(state, code, limit, after_seq))
    if as_json:
        click.echo(jsonlib.dumps(records, ensure_ascii=False, indent=2))
        return
    if not records:
        click.echo(f"{code} 的对方那一侧还没有内容上来")
        return
    for one in records:
        click.echo(_one_line(one))


#: 十六种记录形态在屏幕上各叫什么。只给最常看的那几种起名，其余原样打形态名——
#: 编一套自己的叫法去盖住平台的形态名，会让人对不上中继与工作台上看到的东西。
_KIND_LABEL = {
    "user.say": "用户",
    "agent.say": "Agent",
    "agent.think": "Agent 思考",
    "tool.call": "调用工具",
    "tool.result": "工具结果",
    "error": "报错",
    "interrupt": "用户打断",
}


def _one_line(record: dict) -> str:
    """一条记录在屏幕上的样子：序号、是谁、说了什么的头一段。"""
    kind = str(record.get("kind", "?"))
    label = _KIND_LABEL.get(kind, kind)
    payload = record.get("payload") or {}
    text = ""
    if isinstance(payload, dict):
        for key in ("text", "content", "command", "name", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                break
    text = " ".join(text.split())
    if len(text) > 160:
        text = text[:160] + "…"
    return f"[{record.get('seq', '?'):>4}] {label:<8} {text}"


@team_group.command("status")
@click.option("--team-code", "code", default=None, help="不给就报本机参加的全部")
def status_cmd(code) -> None:
    """这个 team 现在什么状态：两侧在不在、各自最后上报时间、信箱积了几条。"""
    state = load_state()
    codes = [code] if code else [one.code for one in state.active_teams()]
    if not codes:
        click.echo("本机没有参加任何 team。发起用 frago team open，加入用 frago team join")
        return
    for one in codes:
        seen = _guard(lambda c=one: team_sync.team_status(state, c))
        click.echo(f"连接码 {one}")
        click.echo(f"  本机这一侧   {seen.get('side') or '（不在里面）'}")
        click.echo(f"  对方在不在   {'在' if seen.get('peer_present') else '不在'}")
        click.echo(f"  我的信箱     {seen.get('inbox', 0)} 条待收")
        click.echo(f"  对方信箱     {seen.get('peer_inbox', 0)} 条待收")


@team_group.command("list")
def list_cmd() -> None:
    """本机参加过哪些 team。不联网。"""
    state = load_state()
    if not state.teams:
        click.echo("本机没有参加过任何 team")
        return
    for binding in state.teams.values():
        mark = "在" if binding.active else "已退出"
        click.echo(
            f"{binding.code}  {binding.side} 侧  {mark}  "
            f"会话 {binding.session_id}  已推到 seq {binding.pushed_seq}"
        )


@team_group.command("sync")
@click.option("--team-code", "code", default=None, help="不给就跑本机参加的全部")
def sync_cmd(code) -> None:
    """手动跑一轮同步。

    平时不用敲：服务端有一条循环在按间隔自己跑。这条命令是给「现在就想知道对方说了
    什么」和排查用的。
    """
    from frago.server.services import session_send

    state = load_state()
    todo = [state.require(code)] if code else state.active_teams()
    if not todo:
        click.echo("本机没有在任何 team 里")
        return
    for binding in todo:
        def deliver(prompt: str, sid: str = binding.session_id) -> None:
            session_send.send_queued(sid, prompt)

        outcome = _guard(lambda b=binding: team_sync.sync_once(state, b, deliver))
        click.echo(
            f"{outcome.code}：推了 {outcome.pushed} 条记录，投了 {outcome.delivered} 条消息"
            + (f"，跳过重复 {outcome.skipped} 条" if outcome.skipped else "")
        )
        if outcome.note:
            click.echo(f"  {outcome.note}")
