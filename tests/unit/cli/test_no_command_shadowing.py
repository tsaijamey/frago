"""两个命令不许重名。

click 的 Group 遇到同名 `add_command` 会**静默保留后注册的那个**，前一个就此消失，
既不报错也不警告。20260817 出过两次：审计员逮到「登录会话要挂进已被占用的 frago session」，
而 `frago recipe publish` 是真的被顶掉了——它原本是配方发布自己页面状态的入口，
被一个同名的「把配方开放到公网」覆盖，所有带界面的配方从 WebUI 点运行都打不开页面，
服务端日志里只有一句看起来像配方自己有问题的报错。

这个测试遍历整棵命令树，任何一层出现重名都当场失败。
"""

from __future__ import annotations

import click
import pytest

from frago.cli.main import cli


def _walk(group: click.Group, path: str = "frago"):
    """产出 (路径, 组对象) —— 命令树里的每一个 Group。"""
    yield path, group
    for name in group.list_commands(click.Context(group)):
        cmd = group.get_command(click.Context(group), name)
        if isinstance(cmd, click.Group):
            yield from _walk(cmd, f"{path} {name}")


def test_no_two_commands_share_a_name():
    """`list_commands` 已经去重，所以直接查注册表本身。"""
    offenders = []
    for path, group in _walk(cli):
        registered = getattr(group, "commands", {})
        seen: dict[str, int] = {}
        for name in registered:
            seen[name] = seen.get(name, 0) + 1
        offenders += [f"{path} {n}" for n, c in seen.items() if c > 1]
    assert not offenders, f"命令重名：{offenders}"


@pytest.mark.parametrize(
    ("group_path", "must_have"),
    [
        # 配方发布页面状态——配方自己在调，被顶掉会让所有带界面的配方打不开
        ("recipe", ["publish", "expose", "unexpose", "exposed"]),
        # agent 会话记录——审计员点名的那一组
        ("session", ["list", "search", "show", "watch", "clean", "delete", "sync"]),
    ],
)
def test_command_groups_keep_their_subcommands(group_path: str, must_have: list[str]):
    group = cli.get_command(click.Context(cli), group_path)
    assert isinstance(group, click.Group)
    available = set(group.list_commands(click.Context(group)))
    missing = [c for c in must_have if c not in available]
    assert not missing, f"frago {group_path} 少了子命令：{missing}"


def test_recipe_publish_is_still_the_state_publisher():
    """名字对了不够，得是原来那个东西。

    `frago recipe publish` 的职责是把一次运行的状态写进 slot 给页面读，
    不是把配方开放到公网——后者叫 expose。
    """
    recipe = cli.get_command(click.Context(cli), "recipe")
    publish = recipe.get_command(click.Context(recipe), "publish")
    params = {p.name for p in publish.params}
    assert "state_file" in params, "frago recipe publish 不再是发布页面状态的那个命令"
