"""CoreAgent 会话镜像进会话存储这一件事的单测。

要点只有一个：**命令行那一侧读的是 ``~/.frago/sessions/``，不是 CoreAgent 自己的根。**
少这一份镜像，CoreAgent 的会话在 ``frago session list`` 里没有、在 ``frago session search``
里也搜不到——而网页会话页因为直接读原生根，一直看得见。两边对不上，人才会以为"没做过"。

所以这里盯两件事：镜像的落点与增量语义（与另外三家同构），以及镜像落下去之后命令行这一侧
真的认得它。
"""

import os
import time

from frago.session import coreagent_store, coreagent_sync, search, storage
from frago.session.models import AgentType

_SID = "core_e2edemo0001"
_WORKDIR = "-private-tmp-work"


def _write_source(home, lines, session_id=_SID, workdir=_WORKDIR):
    """照 frago-core 的落点摆一份：``<根>/<工作目录编码>/<会话编号>.jsonl``。"""
    directory = coreagent_store.sessions_root() / workdir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session_id}.jsonl"
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


def _mirror(session_id=_SID):
    return coreagent_sync.raw_backup_path(session_id)


def _lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_镜像落在会话目录下与另外三家同构(mock_home):
    """落点是 ``~/.frago/sessions/coreagent/<编号>/raw.jsonl``，内容逐字节照抄。"""
    _write_source(mock_home, ["第一行", "第二行"])

    result = coreagent_sync.sync_coreagent_sessions()

    assert (result.synced, result.updated, result.skipped, result.errors) == (1, 0, 0, [])
    mirror = _mirror()
    assert mirror.parent.parent.name == AgentType.COREAGENT.value
    assert _lines(mirror) == ["第一行", "第二行"]


def test_副本的时刻跟着源走(mock_home):
    """清单对只有副本的会话，拿文件的修改时刻当它的最后活动。

    副本要是记着「写盘那一刻」，一次全量备份会让每一场都读成"刚刚还在跑"，还会把清单
    前几名整个占满——实测 164 场一起备进来就是这个样子。
    """
    source = _write_source(mock_home, ["第一行"])
    long_ago = time.time() - 40 * 24 * 3600
    os.utime(source, (long_ago, long_ago))

    coreagent_sync.sync_coreagent_sessions()

    assert abs(_mirror().stat().st_mtime - long_ago) < 2


def test_再跑一趟不重复备份(mock_home):
    """幂等：没动过的会话第二次直接跳过，文件不会长出一份重复内容。"""
    _write_source(mock_home, ["第一行", "第二行"])
    coreagent_sync.sync_coreagent_sessions()

    result = coreagent_sync.sync_coreagent_sessions()

    assert (result.synced, result.updated, result.skipped) == (0, 0, 1)
    assert _lines(_mirror()) == ["第一行", "第二行"]


def test_新增的记录只追加(mock_home):
    """记录只被追加，所以行数就是游标——第二次只补后面那几行。"""
    source = _write_source(mock_home, ["第一行", "第二行"])
    coreagent_sync.sync_coreagent_sessions()

    source.write_text("第一行\n第二行\n第三行\n", encoding="utf-8")
    result = coreagent_sync.sync_coreagent_sessions()

    assert (result.synced, result.updated) == (0, 1)
    assert _lines(_mirror()) == ["第一行", "第二行", "第三行"]


def test_源被重写时手上那份跟着重写(mock_home):
    """源比手上这份还短，说明这个会话被重写过，手上那份是一个已经不存在的版本。"""
    source = _write_source(mock_home, ["第一行", "第二行", "第三行"])
    coreagent_sync.sync_coreagent_sessions()

    source.write_text("只剩这一行\n", encoding="utf-8")
    result = coreagent_sync.sync_coreagent_sessions()

    assert (result.synced, result.updated) == (0, 1)
    assert _lines(_mirror()) == ["只剩这一行"]


def test_记录目录里按扩展名认会话(mock_home):
    """记录根下每场会话就是一个 ``<编号>.jsonl``，别的东西不认成会话。"""
    _write_source(mock_home, ["第一行"])
    directory = coreagent_store.sessions_root() / _WORKDIR
    (directory / "notes.txt").write_text("x", encoding="utf-8")

    found = coreagent_store.iter_session_files()

    assert [p.stem for p in found] == [_SID]


def test_观察者槽位不会被当成一场会话(mock_home):
    """观察者槽位与记录共用 ``~/.frago/sessions/coreagent/``，但槽位只有几个 json。

    清单的判据是「目录里有原文副本或 metadata」，只装槽位的目录不该进清单——本机真有的
    46 个槽位目录正是这个样子。
    """
    slots = storage.get_session_base_dir() / AgentType.COREAGENT.value / "core_只有槽位"
    slots.mkdir(parents=True, exist_ok=True)
    (slots / "observer-slots.json").write_text("{}", encoding="utf-8")
    (slots / "observer-runs.jsonl").write_text("{}\n", encoding="utf-8")

    assert "core_只有槽位" not in [s.session_id for s in storage.list_sessions(limit=100)]


def test_镜像不碰同一会话目录里的观察者文件(mock_home):
    """观察者先在这个会话目录里写了槽位，镜像只添一个 ``raw.jsonl``，别人的文件一个字不动。"""
    slots = storage.get_session_base_dir() / AgentType.COREAGENT.value / _SID
    slots.mkdir(parents=True, exist_ok=True)
    (slots / "observer-slots.json").write_text('{"槽位": 1}', encoding="utf-8")
    _write_source(mock_home, ["第一行"])

    coreagent_sync.sync_coreagent_sessions()

    assert (slots / "observer-slots.json").read_text(encoding="utf-8") == '{"槽位": 1}'
    assert _lines(slots / "raw.jsonl") == ["第一行"]


def test_CoreAgent_没跑过时不报错(mock_home):
    """这一家还没落过盘时是一份空结果，NEVER 抛。"""
    result = coreagent_sync.sync_coreagent_sessions()

    assert (result.synced, result.updated, result.skipped, result.errors) == (0, 0, 0, [])


def test_命令行清单里认得这一家(mock_home):
    """这是本条要解决的问题本身：镜像落下去之后，清单里要能看见它。"""
    _write_source(mock_home, ["第一行"])
    coreagent_sync.sync_coreagent_sessions()

    sessions = storage.list_sessions(limit=100)

    hit = next(s for s in sessions if s.session_id == _SID)
    assert hit.agent_type is AgentType.COREAGENT


def test_检索语料把这一家算进去(mock_home):
    """语料目录表要与备份的写入侧对齐，否则命中了也会在归属那一步被丢掉。"""
    _write_source(mock_home, ["第一行"])
    coreagent_sync.sync_coreagent_sessions()

    root = storage.get_session_base_dir()

    assert search._CORE_DIRS["coreagent"] == "coreagent"
    assert search.count_sessions(root) >= 1
    assert search._split_location(root, _mirror()) == ("coreagent", _SID)


def test_命中后给的续接命令是内核自己那条():
    """内核认这个编号：``--resume`` 把先前的回合重放进上下文再接着跑。

    落到 Claude Code 那条默认分支上会给出 ``claude --resume core_xxx``——照做必然失败。
    """
    assert search._resume_command("coreagent", _SID) == f"frago-core --resume {_SID}"
