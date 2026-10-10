"""会话详情里「这一场改过哪些文件」这一组接口的边界。

三个门：列清单、取某一份文件的内容、在文件管理器里打开。后两个都收路径，**服务端不校验
就是口子**，所以这里钉的都是「什么被放行、什么被拒」。

放行面是两处，缺一不可地分清：取内容只认**清单里的文件本身**（文件内容比目录名敏感），
打开目录认**会话自己的工作目录之下的任何东西**再加**清单里那些文件**。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from frago.server.routes import workbench as workbench_routes
from frago.session.record_reader import UnknownSessionFamily
from frago.session.session_files import SessionFile


@pytest.fixture
def session_dir(tmp_path, monkeypatch):
    """一场会话，工作目录就是 tmp_path。"""
    card = SimpleNamespace(session_id="sid-1", directory=str(tmp_path))
    monkeypatch.setattr(workbench_routes.record_reader, "list_sessions", lambda: [card])
    return tmp_path


@pytest.fixture
def touched(monkeypatch):
    """这场会话改过的文件。默认一个都没有；测试里按需塞。"""

    def _set(files: list[SessionFile]):
        monkeypatch.setattr(workbench_routes.session_files, "session_files", lambda sid: files)

    _set([])
    return _set


@pytest.fixture
def unknown_session(monkeypatch):
    """认不出这场会话：记录层抛，服务层该回 404。"""

    def _boom(sid):
        raise UnknownSessionFamily(f"不认识的会话编号：{sid}")

    monkeypatch.setattr(workbench_routes.session_files, "session_files", _boom)


@pytest.fixture
def opened(monkeypatch):
    """记下系统层被叫去干了什么，不真开任何窗口。"""
    calls: list[tuple] = []
    monkeypatch.setattr(
        workbench_routes.SystemService,
        "reveal_or_open",
        staticmethod(lambda path, reveal: calls.append(("reveal", path, reveal))),
    )
    monkeypatch.setattr(
        workbench_routes.SystemService,
        "open_directory",
        staticmethod(lambda path: calls.append(("dir", path))),
    )
    return calls


def _file(path: str, action: str = "modified", count: int = 1, seq: int = 0) -> SessionFile:
    return SessionFile(path=path, action=action, count=count, first_seq=seq)


# ---------- 列清单 ----------


@pytest.mark.asyncio
async def test_the_list_carries_path_action_and_count(session_dir, touched):
    touched([
        _file("/w/new.py", "created", 1, 0),
        _file("/w/old.py", "modified", 3, 4),
        _file("/w/gone.py", "deleted", 1, 6),
    ])

    rows = await workbench_routes.read_session_files("sid-1")

    assert rows == [
        {"path": "/w/new.py", "action": "created", "count": 1, "first_seq": 0},
        {"path": "/w/old.py", "action": "modified", "count": 3, "first_seq": 4},
        {"path": "/w/gone.py", "action": "deleted", "count": 1, "first_seq": 6},
    ]


@pytest.mark.asyncio
async def test_a_session_that_changed_nothing_lists_empty(session_dir, touched):
    assert await workbench_routes.read_session_files("sid-1") == []


@pytest.mark.asyncio
async def test_an_unknown_session_is_a_404(session_dir, unknown_session):
    with pytest.raises(HTTPException) as err:
        await workbench_routes.read_session_files("nope")

    assert err.value.status_code == 404


# ---------- 取某一份文件的内容 ----------


@pytest.mark.asyncio
async def test_a_listed_file_comes_back_as_text(session_dir, touched):
    target = session_dir / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    touched([_file(str(target))])

    body = await workbench_routes.read_session_file("sid-1", str(target))

    assert body["text"] == "x = 1\n"
    assert body["reason"] is None


@pytest.mark.asyncio
async def test_the_content_door_only_opens_for_files_on_the_list(session_dir, touched):
    """工作目录底下的别的文件也读不到——内容这一门的白名单按文件列，不按目录放。"""
    secret = session_dir / "secret.py"
    secret.write_text("token = 'x'\n", encoding="utf-8")
    touched([])

    with pytest.raises(HTTPException) as err:
        await workbench_routes.read_session_file("sid-1", str(secret))

    assert err.value.status_code == 403


@pytest.mark.asyncio
async def test_a_listed_file_that_vanished_is_a_404(session_dir, touched):
    gone = session_dir / "gone.py"
    touched([_file(str(gone))])

    with pytest.raises(HTTPException) as err:
        await workbench_routes.read_session_file("sid-1", str(gone))

    assert err.value.status_code == 404


@pytest.mark.asyncio
async def test_a_too_large_file_says_so_instead_of_dribbling_half(session_dir, touched, monkeypatch):
    big = session_dir / "big.py"
    big.write_text("x" * 64, encoding="utf-8")
    touched([_file(str(big))])
    monkeypatch.setattr(workbench_routes, "_PREVIEW_MAX_BYTES", 8)

    body = await workbench_routes.read_session_file("sid-1", str(big))

    assert body["text"] is None
    assert body["reason"] == "too-large"
    assert body["size"] == 64


@pytest.mark.asyncio
async def test_something_that_is_not_text_says_so(session_dir, touched):
    binary = session_dir / "logo.png"
    binary.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
    touched([_file(str(binary))])

    body = await workbench_routes.read_session_file("sid-1", str(binary))

    assert body["text"] is None
    assert body["reason"] == "not-text"


@pytest.mark.asyncio
async def test_an_unknown_session_cannot_read_content(session_dir, unknown_session):
    with pytest.raises(HTTPException) as err:
        await workbench_routes.read_session_file("nope", "/etc/hosts")

    assert err.value.status_code == 404


# ---------- 改动前后两边的对照 ----------


@pytest.fixture
def head(monkeypatch):
    """捏住「git HEAD 里那一版」这一侧：真去跑 git 是 `test_file_history` 那一层的事。"""

    def _set(before):
        monkeypatch.setattr(
            workbench_routes.file_history, "before_at_head", lambda path, max_bytes: before
        )

    return _set


def _with_before(text):
    from frago.server.services.file_history import GIT_SOURCE, Before

    return Before(text=text, reason=None, source=GIT_SOURCE)


@pytest.mark.asyncio
async def test_the_diff_puts_a_changed_line_on_one_row(session_dir, touched, head):
    target = session_dir / "a.py"
    target.write_text("x = 2\n", encoding="utf-8")
    touched([_file(str(target))])
    head(_with_before("x = 1\n"))

    body = await workbench_routes.read_session_file_diff("sid-1", str(target))

    assert body["reason"] is None
    assert body["source"] == "git HEAD"
    assert body["before"] is None
    [row] = body["rows"]
    assert row[0]["sign"] == "-" and row[0]["text"] == "x = 1"
    assert row[1]["sign"] == "+" and row[1]["text"] == "x = 2"


@pytest.mark.asyncio
async def test_a_file_the_repo_never_saw_is_all_additions(session_dir, touched, head):
    from frago.server.services.file_history import NO_BEFORE_NEW

    target = session_dir / "fresh.py"
    target.write_text("one\ntwo\n", encoding="utf-8")
    touched([_file(str(target), "created")])
    head(_with_before(None))
    # `before_at_head` 在新文件那一档给的是「没有正文 + 缘由」。
    import frago.server.services.file_history as fh

    head(fh.Before(text=None, reason=NO_BEFORE_NEW, source=None))

    body = await workbench_routes.read_session_file_diff("sid-1", str(target))

    assert body["before"] == NO_BEFORE_NEW
    assert body["source"] is None
    # 左边整列空着：这一场新建的，没有上一版可摆。
    assert [row[0] for row in body["rows"]] == [None, None]
    assert [row[1]["sign"] for row in body["rows"]] == ["+", "+"]


@pytest.mark.asyncio
async def test_a_file_outside_a_repo_says_so_instead_of_new(session_dir, touched, head):
    """不在仓库里的：缘由照实说，不许装成新建的。"""
    import frago.server.services.file_history as fh

    target = session_dir / "out.md"
    target.write_text("# hi\n", encoding="utf-8")
    touched([_file(str(target))])
    head(fh.Before(text=None, reason=fh.NO_BEFORE_NOT_GIT, source=None))

    body = await workbench_routes.read_session_file_diff("sid-1", str(target))

    assert body["before"] == fh.NO_BEFORE_NOT_GIT


@pytest.mark.asyncio
async def test_a_file_that_cannot_be_read_has_no_rows(session_dir, touched, head):
    """现在这一份就读不出来：没有可对照的东西，缘由与 `/file` 那套同一句话。"""
    binary = session_dir / "logo.png"
    binary.write_bytes(b"\x89PNG\r\n\x1a\n")
    touched([_file(str(binary))])

    body = await workbench_routes.read_session_file_diff("sid-1", str(binary))

    assert body["reason"] == "not-text"
    assert body["rows"] is None


@pytest.mark.asyncio
async def test_a_file_with_too_many_lines_is_not_diffed(session_dir, touched, head, monkeypatch):
    """行数超过上限：不做对照，照实说，也不把几万行塞给浏览器。"""
    target = session_dir / "big.py"
    target.write_text("x\n" * 40, encoding="utf-8")
    touched([_file(str(target))])
    monkeypatch.setattr(workbench_routes, "_DIFF_MAX_LINES", 5)

    body = await workbench_routes.read_session_file_diff("sid-1", str(target))

    assert body["reason"] == "too-many-lines"
    assert body["rows"] is None


@pytest.mark.asyncio
async def test_the_diff_door_only_opens_for_files_on_the_list(session_dir, touched):
    """对照这一门的白名单与看内容那一门同一套：清单外的读不到。"""
    secret = session_dir / "secret.py"
    secret.write_text("token = 'x'\n", encoding="utf-8")
    touched([])

    with pytest.raises(HTTPException) as err:
        await workbench_routes.read_session_file_diff("sid-1", str(secret))

    assert err.value.status_code == 403


@pytest.mark.asyncio
async def test_a_listed_file_that_vanished_has_no_diff(session_dir, touched):
    gone = session_dir / "gone.py"
    touched([_file(str(gone))])

    with pytest.raises(HTTPException) as err:
        await workbench_routes.read_session_file_diff("sid-1", str(gone))

    assert err.value.status_code == 404


# ---------- 在文件管理器里打开 ----------


@pytest.mark.asyncio
async def test_a_file_inside_the_session_gets_revealed(session_dir, touched, opened):
    target = session_dir / "src" / "a.py"
    target.parent.mkdir()
    target.write_text("x = 1\n", encoding="utf-8")

    result = await workbench_routes.reveal_session_path(
        "sid-1", workbench_routes.RevealPathRequest(path=str(target))
    )

    assert result["status"] == "ok"
    assert opened == [("reveal", str(target.resolve()), True)]


@pytest.mark.asyncio
async def test_a_file_the_session_changed_outside_its_own_directory_opens(
    session_dir, touched, opened, tmp_path_factory
):
    """产物常常写在会话工作目录之外（例如 ~/.frago/data 下），那些也得开得了。"""
    outside = tmp_path_factory.mktemp("products") / "report.md"
    outside.write_text("# r\n", encoding="utf-8")
    touched([_file(str(outside))])

    await workbench_routes.reveal_session_path(
        "sid-1", workbench_routes.RevealPathRequest(path=str(outside))
    )

    assert opened == [("reveal", str(outside.resolve()), True)]


@pytest.mark.asyncio
async def test_a_directory_inside_opens_as_a_directory(session_dir, touched, opened):
    target = session_dir / "docs"
    target.mkdir()

    await workbench_routes.reveal_session_path(
        "sid-1", workbench_routes.RevealPathRequest(path=str(target))
    )

    assert opened == [("dir", str(target.resolve()))]


@pytest.mark.asyncio
async def test_the_session_directory_itself_opens(session_dir, touched, opened):
    await workbench_routes.reveal_session_path(
        "sid-1", workbench_routes.RevealPathRequest(path=str(session_dir))
    )

    assert opened == [("dir", str(session_dir.resolve()))]


@pytest.mark.asyncio
async def test_a_path_outside_is_refused(session_dir, touched, opened):
    outside = session_dir.parent / "somewhere-else"
    outside.mkdir()

    with pytest.raises(HTTPException) as err:
        await workbench_routes.reveal_session_path(
            "sid-1", workbench_routes.RevealPathRequest(path=str(outside))
        )

    assert err.value.status_code == 403
    assert opened == []


@pytest.mark.asyncio
async def test_a_neighbour_sharing_the_name_prefix_is_refused(session_dir, touched, opened):
    """名字只差一个后缀的邻居不算在里面：按路径段判，不按字符串前缀判。"""
    neighbour = session_dir.parent / (session_dir.name + "-evil")
    neighbour.mkdir()

    with pytest.raises(HTTPException) as err:
        await workbench_routes.reveal_session_path(
            "sid-1", workbench_routes.RevealPathRequest(path=str(neighbour))
        )

    assert err.value.status_code == 403
    assert opened == []


@pytest.mark.asyncio
async def test_an_unknown_session_cannot_open_anything(session_dir, unknown_session, opened):
    with pytest.raises(HTTPException) as err:
        await workbench_routes.reveal_session_path(
            "nope", workbench_routes.RevealPathRequest(path=str(session_dir))
        )

    assert err.value.status_code == 404
    assert opened == []


@pytest.mark.asyncio
async def test_a_missing_path_inside_is_a_404(session_dir, touched, opened):
    with pytest.raises(HTTPException) as err:
        await workbench_routes.reveal_session_path(
            "sid-1", workbench_routes.RevealPathRequest(path=str(session_dir / "gone.py"))
        )

    assert err.value.status_code == 404
    assert opened == []
