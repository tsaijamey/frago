"""agy 会话转录备份进会话存储这一件事的单测。

要点与 CoreAgent 那一份相同：**命令行那一侧读的是 ``~/.frago/sessions/``，不是 agy 自己
的 brain 目录。** 少这一份镜像，agy 的会话在 ``frago session search`` 里搜不到——而网页
会话工作台因为直接读原生根，一直看得见。两边对不上，人才会以为"没做过"。

所以这里盯三件事：镜像的落点与增量语义（与另外几家同构）、检索语料那条路真的认得它，
以及命中之后给出的续接命令与时刻是对的。
"""

import json
import os
import sqlite3
import time

import pytest

from frago.session import agy_store, agy_sync, search
from frago.session.models import AgentType
from frago.session.storage import get_session_base_dir

_CID = "481b5141-cdf9-4a3a-aeea-535dfa1c0df0"
_SHELL_CID = "22222222-2222-2222-2222-222222222222"

_ROW = {
    "step_index": 0,
    "source": "USER_EXPLICIT",
    "type": "USER_INPUT",
    "status": "DONE",
    "created_at": "2026-10-13T11:42:52Z",
    "content": "<USER_REQUEST>第一句</USER_REQUEST>",
}


@pytest.fixture()
def brain(mock_home):
    """agy 的应用数据目录（``mock_home`` 已经把 ``Path.home()`` 指到临时目录）。"""
    root = mock_home / ".gemini" / "antigravity-cli"
    (root / "brain").mkdir(parents=True)
    return root


def _write_summaries(root, rows):
    conn = sqlite3.connect(root / "conversation_summaries.db")
    conn.execute(
        "CREATE TABLE conversation_summaries ("
        "conversation_id text, title text, preview text, step_count integer,"
        " last_modified_time datetime, workspace_uris text, last_user_input_time datetime)"
    )
    conn.executemany(
        "INSERT INTO conversation_summaries VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def _summary_row(cid, *, title="", preview="", modified="2026-10-13 11:43:12.043398+00:00"):
    return (cid, title, preview, 2, modified, json.dumps(["file:///tmp/proj"]), modified)


def _write_transcript(cid, records):
    path = agy_store.transcript_path(cid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{json.dumps(r, ensure_ascii=False)}\n" for r in records), encoding="utf-8"
    )
    return path


def _mirror(cid=_CID):
    return agy_sync.raw_backup_path(cid)


def _lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_镜像落在会话目录下与另外几家同构(brain):
    """落点是 ``~/.frago/sessions/agy/<会话编号>/raw.jsonl``，内容逐行照抄。"""
    _write_transcript(_CID, [_ROW])
    _write_summaries(brain, [_summary_row(_CID)])

    result = agy_sync.sync_agy_sessions()

    assert (result.synced, result.updated, result.skipped, result.errors) == (1, 0, 0, [])
    mirror = _mirror()
    assert mirror.parent.parent.name == AgentType.AGY.value
    assert _lines(mirror) == [json.dumps(_ROW, ensure_ascii=False)]


def test_副本的时刻跟着源走(brain):
    """清单对只有副本的会话，拿文件的修改时刻当它的最后活动。

    副本要是记着「写盘那一刻」，一次全量备份会让每一场都读成"刚刚还在跑"，还会把清单
    前几名整个占满。
    """
    source = _write_transcript(_CID, [_ROW])
    _write_summaries(brain, [_summary_row(_CID)])
    long_ago = time.time() - 40 * 24 * 3600
    os.utime(source, (long_ago, long_ago))

    agy_sync.sync_agy_sessions()

    assert abs(_mirror().stat().st_mtime - long_ago) < 2


def test_再跑一趟不重复备份(brain):
    """幂等：没动过的会话第二次直接跳过，文件不会长出一份重复内容。"""
    _write_transcript(_CID, [_ROW])
    _write_summaries(brain, [_summary_row(_CID)])
    agy_sync.sync_agy_sessions()

    result = agy_sync.sync_agy_sessions()

    assert (result.synced, result.updated, result.skipped) == (0, 0, 1)
    assert len(_lines(_mirror())) == 1


def test_新增的记录只追加(brain):
    """转录只被追加，所以行数就是游标——第二次只补后面那几行。"""
    source = _write_transcript(_CID, [_ROW])
    _write_summaries(brain, [_summary_row(_CID)])
    agy_sync.sync_agy_sessions()

    with source.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({**_ROW, "step_index": 1, "type": "PLANNER_RESPONSE"}) + "\n")
    result = agy_sync.sync_agy_sessions(since_mtime_cache={})

    assert (result.synced, result.updated) == (0, 1)
    assert len(_lines(_mirror())) == 2


def test_源被重写时手上那份跟着重写(brain):
    """源比手上这份还短，说明这场被重写过，手上那份是一个已经不存在的版本。"""
    source = _write_transcript(_CID, [_ROW, {**_ROW, "step_index": 1}, {**_ROW, "step_index": 2}])
    _write_summaries(brain, [_summary_row(_CID)])
    agy_sync.sync_agy_sessions()

    source.write_text(json.dumps(_ROW) + "\n", encoding="utf-8")
    result = agy_sync.sync_agy_sessions(since_mtime_cache={})

    assert (result.synced, result.updated) == (0, 1)
    assert len(_lines(_mirror())) == 1


def test_摘要库里有转录却不在的空会话不建目录(brain):
    """那是一场空壳会话（agy 连一次输入都没记下），没有源可备，NEVER 为它建空目录。"""
    _write_transcript(_CID, [_ROW])
    _write_summaries(
        brain,
        [
            _summary_row(_CID),
            _summary_row(_SHELL_CID, modified="0001-01-01 00:00:00+00:00"),
        ],
    )

    result = agy_sync.sync_agy_sessions()

    assert (result.synced, result.skipped) == (1, 1)
    assert not _mirror(_SHELL_CID).parent.exists()


def test_agy_没装时不报错(mock_home):
    """这一家还没跑过时是一份空结果，NEVER 抛。"""
    result = agy_sync.sync_agy_sessions()

    assert (result.synced, result.updated, result.skipped, result.errors) == (0, 0, 0, [])


def test_检索语料把这一家算进去(brain):
    """语料目录表要与备份的写入侧对齐，否则命中了也会在归属那一步被丢掉。"""
    _write_transcript(_CID, [_ROW])
    _write_summaries(brain, [_summary_row(_CID)])
    agy_sync.sync_agy_sessions()

    root = get_session_base_dir()

    assert search._CORE_DIRS["agy"] == "agy"
    assert search.count_sessions(root) >= 1
    assert search._split_location(root, _mirror()) == ("agy", _CID)


def test_命中后给的续接命令是agy自己那条():
    """agy 认这个编号：``--conversation`` 续接那一场。

    落到 Claude Code 那条默认分支上会给出 ``claude --resume 481b...``——照做必然失败。
    """
    assert search._resume_command("agy", _CID) == f"agy --conversation {_CID}"


def test_转录行的时刻认得出来():
    """agy 的行用 ``created_at`` 而不是 ``timestamp``；认不出这一格，带 ``--days`` 检索就漏掉它。"""
    moment = search._record_epoch(_ROW)

    assert moment is not None
    assert moment == pytest.approx(1_791_891_772.0)


def test_别家同名字段不被当成agy的格式():
    """没有 ``step_index`` 的行不走 agy 那条分支，别家的记录格式一字不改。"""
    record = {"timestamp": "2026-10-13T11:42:52Z", "created_at": "不是时间"}

    assert search._record_epoch(record) == pytest.approx(1_791_891_772.0)


def test_命中后能取到标题与工作目录(brain):
    """转录里两样都没有，只有 agy 自己的摘要库有。"""
    _write_summaries(brain, [_summary_row(_CID, title="Claude Opus Usage Limits", preview="预览")])

    meta = search._agy_titles([_CID])

    assert meta[_CID] == ("Claude Opus Usage Limits", "/tmp/proj")


def test_没有标题时退回提要(brain):
    """与会话清单同一个退让：模型起的名字优先，没有就用 agy 自己存的那句提要。"""
    _write_summaries(brain, [_summary_row(_CID, title="", preview="开口那句")])

    assert search._agy_titles([_CID])[_CID][0] == "开口那句"


def test_摘要库读不到时留空不炸(mock_home):
    """查不到（库不在、或这场已从摘要库里滚掉）就留空，NEVER 因此让检索失败。"""
    assert search._agy_titles([_CID]) == {}
