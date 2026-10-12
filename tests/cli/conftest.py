"""CLI 用例不该依赖跑测试的机器上装了什么、也不该依赖真人的 config.json。

`frago agent` 不点名 `--agent-type` 时要去读默认内核，而那个值住在真人的
`~/.frago/config.json` 里，解析时还要探本机装没装（见 :mod:`frago.init.agent_core`）。
两条都会让用例的结果随机器而变：同一份仓库，在一台没装 claude 的机器上跑、或者默认内核
换过之后跑，结果就不一样——而这两件事都跟"tmux 那条路的契约对不对"无关。

这里把缺省钉成 claude、把"装没装"的探测打开，**只为让不点名内核的那些用例稳定地走它们
要测的那条 tmux 路**。要测内核后端、或要验缺省解析与退回逻辑的用例，自己显式给
`--agent-type`，或自己打桩 `frago.init.agent_core` /
`frago.init.config_manager.get_agent_core`。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _pin_default_core_for_cli_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "frago.init.config_manager.get_agent_core", lambda: "claude", raising=False
    )
    monkeypatch.setattr(
        "frago.init.agent_core.core_installed", lambda _agent_type: True, raising=False
    )
