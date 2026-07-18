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

frago agent 恒起一个 tmux 会话、在里面跑指定的 cli-agent（默认 claude）跑一轮任务。
只有这一个后端：没有 headless 形态，没有 --driver 可选。

⚠ 从 Bash 调用 MUST 用后台执行（Bash 工具 run_in_background: true），NEVER 前台干等：
  frago agent 阻塞到本轮跑完才退出，前台起等于把主控会话钉死在一个 worker 上。
  后台起之后无需轮询、无需兜底定时器——harness 托管该进程，它退出即唤醒你。
  NEVER 用 nohup / & 手动脱离：那样进程被摘出 harness 进程树，退出时永远不会唤醒你。

常用形态：
  frago agent <prompt>                        # 跑一轮，打印答案
  frago agent --prompt-file <任务书.md>       # 任务书走文件，长 prompt 首选
  frago agent <prompt> --json                 # 机器可读摘要，调用方判读用这个
  frago agent <prompt> --agent-type opencode  # 换 cli-agent
  frago agent <prompt> --resume <uuid>        # 续接既有会话
  frago agent <prompt> --use-profile <名>     # 跑在某条保存的 profile 的模型上
  frago agent <prompt> --use-ccr              # 跑在 CCR 当前配置的模型上（见下方 CCR 状态）
  frago agent attach --files '[...]' --dirs '[...]'  # 交付产出文件

--json 输出：{"status","exit_code","session_id","tmux_name","text","duration_ms"}
退出码契约：0=ok / 1=timeout（会话仍活可 send 续）/ 2=needs_input（MUST 交真人）/ 3=error

已退场，NEVER 再用：--driver、--ask、--passthrough（传了报错）；--yes/-y 已废弃降为
no-op，收到即忽略（历史调用方不会因此炸掉），新代码 NEVER 写它。

想跑在非默认模型上有两条路：
  --use-profile <名>：从 ~/.frago/profiles.json 取该 profile 的 endpoint/model/key \
（ANTHROPIC_BASE_URL / ANTHROPIC_MODEL / ANTHROPIC_API_KEY），经 tmux new-session -e 注入会话。
  --use-ccr：走本地 CCR 代理，路由到 CCR 配置的那个模型（Anthropic↔OpenAI 协议转换由 CCR 负责）。\
CCR 需在跑；若目标是国内端点，CCR 要直连（起 CCR 时清掉 HTTP(S)_PROXY/ALL_PROXY）。
--endpoint / --api-key / --model 优先覆盖以上二者（同样经 new-session -e 注入）。"""


def _ccr_hint() -> str:
    """一行 CCR 实况：--use-ccr 当前会路由到哪个模型、服务是否在跑。

    model-agnostic —— 只反映 CCR 此刻配置指向的模型，不绑定任何具体品牌。
    """
    from frago.cli.agent_command import check_ccr_auth

    ok, info = check_ccr_auth()
    if not ok or not info or info.get("error"):
        return "CCR 状态：未安装/未配置 → --use-ccr 暂不可用（需先装 ccr 并配 ~/.claude-code-router/config.json）。"
    route = info.get("default_route", "unknown")
    running = "运行中" if info.get("is_running") else "未启动（用 `ccr restart` 起）"
    return f"CCR 状态：--use-ccr 当前路由到 [{route}]，服务{running}。"


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
        else:
            click.echo("当前可用 profile（--use-profile 可填 name）：")
            for p in profiles:
                active = "（激活中）" if p.id == store.active_profile_id else ""
                click.echo(
                    f"  - {p.name}{active}  [{p.endpoint_type}]  model={p.default_model or '-'}"
                )
        click.echo()
        click.echo(_ccr_hint())
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
