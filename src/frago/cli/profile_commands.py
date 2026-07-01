"""frago profile —— 只读查看已保存的 API profile。

profile 的增删改激活目前走 WebUI 设置（见 server/routes/settings.py）；此处只提供
一个只读的 list，专治「agent 知道有 --use-profile 参数、却不知道能填哪些名字」的
先验缺口。--for-hook 输出用法 + 活名单，供 frago-hook 的 builtin-bash-frago-agent
规则动态注入。
"""

import click

from frago.cli.agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup

# 与 inject_literal 曾内联在 builtin-rules.json 里的用法一致；改为 --for-hook 动态输出后
# 这里成为唯一出处，规则只负责跑命令注入 stdout。
_AGENT_USAGE = """# frago agent 用法

frago agent 驱动 CLI agent（默认 claude）跑一轮任务。

常用形态：
  frago agent <prompt>                     # headless 跑一轮
  frago agent <prompt> --driver tmux       # 起常驻 tmux TUI 会话跑
  frago agent <prompt> --use-profile <名>  # 用保存的 API profile 的 endpoint/model/key 运行
  frago agent attach --files '[...]' --dirs '[...]'  # 交付产出文件

--use-profile 取 ~/.frago/profiles.json 里某条 profile（按 name 或 id），把它的 \
endpoint/model/key（ANTHROPIC_BASE_URL / ANTHROPIC_MODEL / ANTHROPIC_API_KEY）注入会话；\
tmux 后端经 new-session -e 注入，claude-p 后端并入进程环境。--endpoint / --api-key 仍优先覆盖它。"""


@click.group("profile", cls=AgentFriendlyGroup)
def profile_group():
    """API profile 查看（只读）。增删改激活走 WebUI 设置。"""
    pass


@profile_group.command("list", cls=AgentFriendlyCommand)
@click.option(
    "--for-hook",
    is_flag=True,
    help="Emit the frago agent usage preamble plus the live profile roster "
         "(consumed by the builtin-bash-frago-agent hook rule).",
)
def profile_list(for_hook: bool):
    """列出已保存的 API profile（api_key 脱敏）。"""
    from frago.init.configurator import _mask_api_key
    from frago.init.profile_manager import load_profiles

    store = load_profiles()
    profiles = store.profiles

    if for_hook:
        click.echo(_AGENT_USAGE)
        click.echo()
        if not profiles:
            click.echo("当前可用 profile：无（尚未在 WebUI 设置里创建任何 profile）。")
            return
        click.echo("当前可用 profile（--use-profile 可填 name）：")
        for p in profiles:
            active = "（激活中）" if p.id == store.active_profile_id else ""
            click.echo(
                f"  - {p.name}{active}  [{p.endpoint_type}]  model={p.default_model or '-'}"
            )
        return

    if not profiles:
        click.echo("No profiles saved. Create one in the WebUI settings.")
        return

    click.echo()
    for p in profiles:
        active = " *active*" if p.id == store.active_profile_id else ""
        click.echo(f"{p.name}{active}")
        click.echo(f"  id:        {p.id}")
        click.echo(f"  endpoint:  {p.endpoint_type}  {p.url or ''}".rstrip())
        click.echo(f"  model:     {p.default_model or '-'}")
        click.echo(f"  api_key:   {_mask_api_key(p.api_key)}")
    click.echo()
