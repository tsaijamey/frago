"""agent_driver 测试的隔离夹具。

opencode driver 会读 opencode 会话库、写 frago 侧的身份映射文件。开发机上这两处
都真实存在，不隔离的话单测会去读真库、往 ``~/.frago/opencode-sessions.json``
写真绑定。全目录 autouse 指向临时路径，保证测试既不读真库也不写用户数据。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from frago.session import opencode_store


@pytest.fixture(autouse=True)
def _isolate_opencode_store(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path_factory.mktemp("opencode-store")
    # 默认指向一个**不存在**的库：driver 据 db_path().exists() 跳过认领轮询，
    # 需要真库的用例自己再 setenv 覆盖。
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(home / "absent.db"))
    monkeypatch.setattr(
        opencode_store, "BINDINGS_PATH", Path(home / "opencode-sessions.json")
    )
