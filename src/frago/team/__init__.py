"""vibe teaming —— 两个 frago 用户各自的会话结成一个 team。

一方发起拿到连接码，另一方填这个码加入。此后两边的 agent 能读对方会话的上下文，
也能往对方的会话里投一条消息——落到对方那边是一条带前缀的用户发言，对方的 agent
照常响应，不需要为此学任何新协议。

中间那台服务器上跑着 ``vibe_teaming_relay`` 配方，它是**信箱**：不主动连任何人、
不推送、不开长连接。两侧朝它发请求，它收下、存住、下次谁来要就给谁。所以两台个人
机器都不需要公网入口。

这个包只管**本机这一侧**，分三层：

- :mod:`frago.team.state` —— 本机记着的东西：我是谁、中继在哪、哪个连接码绑着哪场会话。
- :mod:`frago.team.relay` —— 朝中继发请求。
- :mod:`frago.team.sync` —— 一轮同步：把自己会话的增量推上去，把对方投来的消息取下来。

**投喂不在这一层。** 把消息送进正在跑的会话要驱动 tmux，那是服务层的事
（:mod:`frago.server.services.team_sync_service`）；这里只把取下来的消息交出去，
由调用方决定怎么落地。这条分界是为了让本包能在没有服务端的地方被引用与测试。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from frago.team.state import TeamBinding, TeamState, load_state, save_state

__all__ = ["TeamBinding", "TeamState", "load_state", "save_state"]
