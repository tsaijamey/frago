"""opencode driver 单测的隔离夹具。

driver 会读 opencode 会话库、写 frago 侧身份映射文件。开发机上两处都真实存在，
不隔离的话单测会读真库、往 ``~/.frago/opencode-sessions.json`` 写真绑定。
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
    # 默认指向一个**不存在**的库：需要真库行为的用例自己 setenv 覆盖。
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(home / "absent.db"))
    monkeypatch.setattr(
        opencode_store, "BINDINGS_PATH", Path(home / "opencode-sessions.json")
    )
