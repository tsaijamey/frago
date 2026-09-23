"""本机这一侧记着的东西：我是谁、中继在哪、哪个连接码绑着哪场会话。

三件事存在一起，因为它们一起失效：换了中继地址，旧连接码上的绑定全都没意义了。

**身份不取登录账号。** 中继认人靠的是 ``member``——本机第一次用 team 时生成、此后
长期不变的一串随机标识。用账号 id 认人会在两个地方出错：配方拿到的调用方身份在不同
部署形态下含义不同（本机跑是主人、服务器上跑是那个登录用户），而 team 的两侧本来就
是「谁发起、谁加入」，跟账号体系没有关系。同一个人换机器重装，把 ``member`` 带过去
就能接回原来那一侧。

**这里没有中继那台服务器的账号口令。** 那扇门认的是连接码本身，所以中继这一项只剩
一个地址。真正值钱的是每个连接码下面那把 ``secret``——进场之后各自领的钥匙，码泄露了
也顶不掉已经坐满的位置。文件权限 0600 挡的就是同一台机器上的**别的**账号；不做额外
加密，因为能读到这个文件的人已经在以这个账号的身份运行，加密只是把钥匙和锁放进同一个
抽屉。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

#: 出厂默认的中继地址。
#:
#: **这里必须是一台公网上的服务器，NEVER 是本机。** 中继的用处是给两台各自没有
#: 公网入口的机器当中间人；指向本机等于让同一台机器既当甲方又当乙方又当中间人，
#: 那不是协作，是自己跟自己说话。装完 frago 的人不该为了跟朋友结对再去搭一台服务器，
#: 所以这里给一个开箱就能用的。
DEFAULT_RELAY_URL = "https://demo.frago.ai"

#: 本机 team 状态的落点。放在 ``~/.frago/team/`` 而不是配方的数据树下：这是 frago
#: 自己的东西，配方那棵树属于中继那一侧，两边在同一台机器上都跑得起来（自己跟自己
#: 结 team 是测试时的常规动作），混在一处会让人分不清在看哪一侧。
STATE_PATH = Path.home() / ".frago" / "team" / "state.json"

#: 投进对方会话的那条消息，默认长什么样。
#:
#: 前缀不是装饰：接收侧的 agent 看到的是一条普通的用户发言，没有这一句它会把队友的
#: 请求当成自己主人的指令。留着 ``{code}`` 两个占位，由 :func:`render_prefix` 填。
DEFAULT_PREFIX = "我是 team 伙伴的 Agent（连接码 {code}）。现在我希望你做："

#: 一轮同步之间隔多久。15 秒是「对面刚说完话，这边几乎马上就知道」与「别把中继
#: 打爆」之间的位置；改它要同时想到中继上每个 team 每分钟会被敲几次。
DEFAULT_INTERVAL_SECONDS = 15

#: 记着多少条已投递的消息编号。50 是中继单侧信箱的容量——比它少，一次积压就会让
#: 最早那几条重复投递；比它多，留的是永远不会再出现的编号。
DELIVERED_KEPT = 50

#: 一次推多少条记录上去。会话记录里单条工具结果见过七万字符，一次推整场会把中继
#: 的一次请求撑到几十兆——所以推的是增量，而且每轮有上限，没推完的下一轮接着推。
DEFAULT_PUSH_BATCH = 60


@dataclass
class TeamBinding:
    """一个连接码在本机这一侧的全部状态。"""

    code: str
    """连接码。"""

    session_id: str
    """本机这一侧拿哪一场会话参加这个 team。对方读到的是这场会话的记录，
    对方投来的消息也送进这一场。"""

    side: str
    """本机在这个 team 里是 A 侧还是 B 侧。由中继在 open / join 时判定并告知，
    本机只是记下来，NEVER 自己推断——两边各自推断出「我是 A」是这类结构最典型的坏法。"""

    secret: str = ""
    """进场时领到的那把钥匙，此后每次说话都带上。

    连接码要转交给对方，转交途中可能被人看见；这把不会。码泄露之后，已经坐满的
    两个位置靠它顶不掉。"""

    pushed_seq: int = -1
    """已经推给中继的最后一条记录的 ``seq``。下一轮从它加一开始取。

    起始值是 -1 而不是 0：``seq`` 从 0 起算，用 0 当「还没推过」会把第一条记录跳掉。"""

    active: bool = True
    """还在这个 team 里。``frago team leave`` 之后置 False，但不删这一条——
    留着是为了让人还能看到自己参加过什么、以及上次推到哪儿了。"""

    delivered: list[str] = field(default_factory=list)
    """已经投进本机会话的那些消息的编号。

    **这一格是必需的，不是优化。** 中继那边「收下消息」和「告诉中继我收下了」是
    两次调用（登录用户的写入那扇门不作答，见 :mod:`frago.team.relay`），确认那一次
    丢了，同一条消息下一轮还会再来。没有这一格，对方的一句话会被投进会话两遍，而
    agent 会老老实实照做两遍。

    只留最近 :data:`DELIVERED_KEPT` 条：中继那边消息取走就删了，一条被删掉的消息
    不会再出现，留着它的编号没有意义。"""

    def __post_init__(self) -> None:
        if self.side not in ("A", "B"):
            raise ValueError(f"team 只有 A、B 两侧，收到 {self.side!r}")


@dataclass
class Relay:
    """中继在哪、拿什么身份去敲它。"""

    url: str = DEFAULT_RELAY_URL
    """中继那台 frago 服务器的地址。末尾的斜杠在 :meth:`base` 里剥掉。

    **不需要任何账号或 token。** 那扇门认的是连接码本身。"""

    def base(self) -> str:
        return self.url.rstrip("/")

    def loopback(self) -> bool:
        """中继是不是就在本地回环上。

        两种情况会这样，而且都是常规接法：中继跑在本机（自己跟自己结 team，调试
        时天天用），或者经 SSH 隧道把服务器那一端映射到本地——``frago book
        remote-frago`` 推荐的正是后者，控制面完全不上公网。

        这件事影响的是要不要配凭证：落在回环上的请求，服务端当场判成「主人」，
        再要一份账号口令是多余的一道，而多余那一道会把最常见的接法挡在门外。
        """
        base = self.base().lower()
        for prefix in ("http://127.0.0.1", "http://localhost", "http://[::1]",
                       "https://127.0.0.1", "https://localhost", "https://[::1]"):
            if base == prefix or base.startswith(prefix + ":") or base.startswith(prefix + "/"):
                return True
        return False

    def configured(self) -> bool:
        return bool(self.url)


@dataclass
class TeamState:
    """本机这一侧的全部 team 状态。"""

    member: str = ""
    """这台机器在中继眼里的指纹。

    取的是本机 frago 安装时生成的身份（``~/.frago/identity.json`` 里那个 id），
    不是现生成的随机串——一个连接码只认第一次发起和第一次加入时见到的那两个指纹，
    所以它必须**跨重启不变**。重装才变，那时这一侧需要重新加入。"""

    prefix: str = DEFAULT_PREFIX
    """投进本机会话的消息用什么前缀。允许改，因为不同的人对「队友的 agent 在跟我
    说话」这件事想看到的措辞不一样。"""

    interval_seconds: int = DEFAULT_INTERVAL_SECONDS
    """两轮同步之间隔多久。"""

    relay: Relay = field(default_factory=Relay)

    teams: dict[str, TeamBinding] = field(default_factory=dict)
    """连接码 → 本机这一侧的状态。"""

    def active_teams(self) -> list[TeamBinding]:
        """还在里面的那些。同步循环只管这些。"""
        return [one for one in self.teams.values() if one.active]

    def require(self, code: str) -> TeamBinding:
        """取出这个连接码的绑定，没有就说清楚该怎么办。"""
        binding = self.teams.get(code)
        if binding is None:
            raise LookupError(
                f"本机没有连接码 {code} 的记录。发起用 frago team open，"
                f"加入用 frago team join --team-code {code}"
            )
        return binding


def render_prefix(template: str, code: str) -> str:
    """把前缀模板里的占位填上。

    模板是人改得到的，所以它可能一个占位都没写、也可能写了别的名字。两种都按「照原样
    用」处理而不是报错：一条投不进去的消息比一条措辞不合心意的消息坏得多。
    """
    try:
        return template.format(code=code)
    except (KeyError, IndexError, ValueError):
        return template


def machine_fingerprint() -> str:
    """本机这台机器的指纹：frago 安装时生成的那个身份。

    用它而不是现生成一串随机数，是因为中继那边一个连接码只认两个指纹，认的依据必须
    跨重启、跨重装 frago 之外的一切变化都不变。读不到就退回一个随机串——那样这台机器
    每次重启都会被中继当成新的一台，会话接不上，但至少不会在这里崩掉，而且错法是
    「接不上」这种看得见的形态，不是「悄悄认成了别人」。
    """
    try:
        from frago.recipes.context import default_identity

        return str(default_identity())
    except Exception:  # noqa: BLE001
        return secrets.token_hex(16)


def load_state() -> TeamState:
    """读本机的 team 状态；没有就返回一份带着新 member 的空状态。

    **不在这里写盘。** 读一次就落一次盘会让 ``frago team list`` 这种纯查看的命令也
    改文件，人看不出自己做了什么。生成的 member 由第一个真正要用它的命令通过
    :func:`save_state` 定下来。
    """
    raw: dict = {}
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}

    # 只取地址。中继早先要配账号口令，后来定成「连接码本身就是凭证」，
    # :class:`Relay` 上那三个字段随之删掉——磁盘上那份是旧版写的，里面还留着它们，
    # 照单全收会当场抛「不认识这个参数」。多出来的键一律忽略：这个文件的形状由
    # 代码说了算，读的时候点名要什么就只拿什么。
    relay_raw = raw.get("relay")
    relay = Relay(url=str((relay_raw or {}).get("url", "")))

    teams: dict[str, TeamBinding] = {}
    for code, one in (raw.get("teams") or {}).items():
        if not isinstance(one, dict):
            continue
        side = str(one.get("side", "A"))
        if side not in ("A", "B"):
            # 手改文件改坏的那一条，跳过而不是让整份状态读不出来——另一个 team
            # 还在正常运转，不该被这一条拖垮。
            continue
        teams[str(code)] = TeamBinding(
            code=str(code),
            session_id=str(one.get("session_id", "")),
            side=side,
            secret=str(one.get("secret", "")),
            pushed_seq=int(one.get("pushed_seq", -1)),
            active=bool(one.get("active", True)),
            delivered=[str(x) for x in (one.get("delivered") or [])][-DELIVERED_KEPT:],
        )

    interval = int(raw.get("interval_seconds") or DEFAULT_INTERVAL_SECONDS)
    return TeamState(
        member=str(raw.get("member") or machine_fingerprint()),
        prefix=str(raw.get("prefix") or DEFAULT_PREFIX),
        interval_seconds=max(interval, 5),
        relay=relay,
        teams=teams,
    )


def ensure_member() -> TeamState:
    """读状态，并保证本机标识已经定下来。

    :func:`load_state` 读不到标识时会现生成一个但**不落盘**，于是在标识定下来之前，
    每问一次得到的都是一个不一样的值——命令行报一个、界面报另一个，而它们说的是
    同一台机器。人照着其中一个去核对，对不上。

    所以凡是要把这个标识**说给人听**、或者要拿它去跟中继打交道的地方，走这一条：
    第一次问起时就把它定下来，此后永远是同一个。
    """
    state = load_state()
    if not STATE_PATH.exists():
        save_state(state)
    return state


def save_state(state: TeamState) -> None:
    """把状态写回去。先写临时文件再改名，权限 0600。

    改名是原子的，所以同步循环与命令行同时动这份文件时，读到的要么是改前要么是改后，
    不会是写了一半的 JSON。
    """
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "member": state.member,
        "prefix": state.prefix,
        "interval_seconds": state.interval_seconds,
        "relay": asdict(state.relay),
        "teams": {code: asdict(one) for code, one in state.teams.items()},
    }
    handle, tmp = tempfile.mkstemp(dir=str(STATE_PATH.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, STATE_PATH)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
