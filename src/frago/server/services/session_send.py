"""把工作台中栏的一句话送进那场会话所在的 CLI —— 三家共用这一条路。

在这个模块出现之前，发送这条通道背后写死了一个 claude：会话编号原样交给 claude
driver、工作目录只从 claude 的 jsonl 里读。codex 与 opencode 的会话编号在 claude
那边根本不存在，发过去**不报错**——claude 拿 ``--session-id <编号>`` 当场开一场空
白新会话，人在页面上等来的是一句答非所问，原来那场会话一个字都没动。界面因此只
能在打字之前就把这两家闸死。

驱动层其实一直支持另外两家续接（``codex resume <id>`` / ``opencode -s <id>``，各自
driver 里都有 native 分支），缺的只是"告诉 runner 这个编号是哪一家的、当初跑在哪个
目录"。这个模块补的就是这一句：

- **哪一家**由 :func:`~frago.session.record_reader.detect_family` 判——与左栏清单、
  记录流用的是同一份判据，NEVER 在这里另写一套形状匹配。
- **哪个目录**各家问各家的档案：claude 读 jsonl 首条记录的 ``cwd``，codex 读 rollout
  首行的 ``session_meta.cwd``，opencode 查会话行的 ``directory``。
- **目录问不出来就不发**（claude 的新会话除外，见 :class:`SendTarget`）。续接命令本身
  不带目录，tmux 在哪儿起，agent 的工作目录就是哪儿；给错目录续接照样成功，但 agent
  看到的是另一个仓库——比起不了还难发现。

分层：服务层。可以 import ``session/`` 与 ``agent_driver/``，NEVER import ``cli/``。
"""

from __future__ import annotations

import contextlib
import json
import logging
from dataclasses import dataclass

from frago.session import claude_sessions as claude_svc
from frago.session import codex_store, opencode_store, record_reader
from frago.session import transcript_completion as tc
from frago.session.unified_record import RecordFamily

logger = logging.getLogger(__name__)

# 家族 → 驱动这一家的 agent driver key（``frago.agent_driver.drivers`` 里注册的名字）。
# 三家齐全：少一家就等于那一家的会话在页面上发不出去，而不是发错地方。
AGENT_TYPE_BY_FAMILY: dict[RecordFamily, str] = {
    "claude-code": "claude",
    "opencode": "opencode",
    "codex": "codex",
}


class SessionGone(LookupError):
    """这场会话的记录已经不在了（被用户删了 / 库里查不到），续不上。

    这一档 MUST 单独存在：驱动层遇到"续接目标不存在"会自愈成裸起一个新会话，那正是
    页面上最不该发生的事——人以为在跟原来那场说话，实际开了新的一场。
    """


class SessionDirectoryUnknown(LookupError):
    """问不出这场会话当初跑在哪个目录，因此不能替它决定在哪儿续接。"""


@dataclass(frozen=True)
class SendTarget:
    """一次投喂的落点：驱动哪一家、在哪个目录续接。"""

    session_id: str
    family: RecordFamily
    agent_type: str
    cwd: str | None
    """起 tmux 用的工作目录。只有"页面刚 mint 的新 claude 会话"才允许为 None，
    那时由调用方给的起始目录决定（给不出就退回家目录）。"""

    is_new: bool
    """这个编号在档案里还没有任何记录——即页面新建会话时自己 mint 的那个 uuid。
    只可能出现在 claude 一家：另外两家的编号是各自的 CLI 建会话时分配的，页面
    只能续接已经存在的那些。"""


def _claude_cwd(session_id: str) -> str | None:
    """从这场 claude 会话的 jsonl 里读出 cwd，供 resume 重建时落回原目录。

    读不到返回 None（会话还不存在，或档案损坏），调用方据此判断这是不是一场新会话。
    只读首批记录里的 cwd 字段，不整读几十 MB 的流水账。
    """
    path = tc.locate_transcript(session_id)
    if path is None:
        return None
    with contextlib.suppress(OSError), open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            cwd = record.get("cwd")
            if cwd:
                return str(cwd)
    return None


def resolve_target(session_id: str, *, cwd_hint: str | None = None) -> SendTarget:
    """判出这个会话编号该由哪一家驱动、在哪个目录续接。

    ``cwd_hint`` 只对"页面刚 mint 的新 claude 会话"有意义（新建会话对话框里挑的那个
    起始目录）。已经有记录的会话一律以档案里记着的目录为准，NEVER 让页面传来的值
    覆盖它——同一场会话换个目录续接，等于把 agent 挪到另一个仓库里接着干。

    抛 :class:`~frago.session.record_reader.UnknownSessionFamily`（编号形状三家都不像）、
    :class:`SessionGone`（记录没了）、:class:`SessionDirectoryUnknown`（问不出目录）。
    """
    family = record_reader.detect_family(session_id)
    agent_type = AGENT_TYPE_BY_FAMILY[family]

    if family == "claude-code":
        recorded = _claude_cwd(session_id)
        if recorded:
            return SendTarget(session_id, family, agent_type, recorded, is_new=False)
        # 档案里没有这个编号：页面新建会话就是这条路——claude 以 ``--session-id`` 起，
        # 自己把 jsonl 写到该去的地方，下一次扫描它就是一行普通会话。
        return SendTarget(session_id, family, agent_type, cwd_hint, is_new=True)

    if family == "codex":
        meta = codex_store.session_meta(session_id)
        if meta is None:
            raise SessionGone(f"codex 那边找不到会话 {session_id} 的记录，续不上")
        if not meta.cwd:
            raise SessionDirectoryUnknown(
                f"codex 会话 {session_id} 的记录里没写工作目录，不能替它决定在哪儿续接"
            )
        return SendTarget(session_id, family, agent_type, meta.cwd, is_new=False)

    # opencode
    if not opencode_store.session_exists(session_id):
        raise SessionGone(f"opencode 库里没有会话 {session_id}，续不上")
    directory = opencode_store.session_directory(session_id)
    if not directory:
        raise SessionDirectoryUnknown(
            f"读不到 opencode 会话 {session_id} 的工作目录，不能替它决定在哪儿续接"
        )
    return SendTarget(session_id, family, agent_type, directory, is_new=False)


def send(session_id: str, prompt: str, *, cwd_hint: str | None = None, timeout_s: float = 180.0):
    """把一段提示词投进这场会话，返回激活态（阻塞：tmux + 轮询，调用方丢线程里跑）。

    新的 claude 会话顺手登记一次 ``register_webui_session``：会话编号是页面自己 mint
    的，claude 不会给它派 slug，扫描那一侧因此认不出"这场是人从网页开的"。
    """
    from frago.server.services.ui_session_runner import get_runner

    target = resolve_target(session_id, cwd_hint=cwd_hint)
    if target.is_new and cwd_hint:
        claude_svc.register_webui_session(session_id)
    logger.info(
        "webui send → session=%s family=%s agent=%s cwd=%s",
        session_id,
        target.family,
        target.agent_type,
        target.cwd,
    )
    return get_runner().send(
        session_id,
        prompt,
        agent_type=target.agent_type,
        cwd=target.cwd,
        timeout_s=timeout_s,
    )
