"""frago profile —— 只读查看已保存的 API profile。

profile 的增删改激活目前走 WebUI 设置（见 server/routes/settings.py）；此处只提供
一个只读的 list，专治「agent 知道有 --use-profile 参数、却不知道能填哪些名字」的
先验缺口。--for-hook 输出用法 + 活名单，供 frago-core 的 builtin-bash-frago-agent
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

一轮任务不设时间上限：缺省 --timeout 0，worker 跑到答完 / 撞上认证墙 / 会话死掉才停，
NEVER 因墙钟到点被腰斩。真要卡表（探活之类）才显式 --timeout N。

--json 输出：{"status","exit_code","session_id","tmux_name","text","duration_ms"}
退出码契约：0=ok / 1=timeout（只有显式 --timeout N 才可能出现，会话仍活可 send 续）/
            2=needs_input（MUST 交真人）/ 3=error

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
    """连接查看与角色绑定。增删改走 WebUI 设置。"""
    pass


def _binding_lines() -> list[str]:
    """两个角色各自跑在哪条连接上，各一行。

    两行一起给，是因为它们的差别只在对照着看时才成立：主 agent 那条写进了各 cli-agent
    自己的配置（人手起的会话也吃这一条），worker 那条只在 ``frago agent`` 开会话时现
    读现用。单看一行，人会以为改了一处两处都变。
    """
    from frago.init.profile_manager import (
        MAIN_ROLE,
        WORKER_ROLE,
        load_profiles,
        resolve_worker_profile,
        role_connection,
    )

    store = load_profiles()
    main = role_connection(MAIN_ROLE)
    worker = role_connection(WORKER_ROLE)
    coreagent_worker = resolve_worker_profile("coreagent")

    main_where = f"，已写入 {', '.join(store.active_targets)}" if store.active_targets else ""
    worker_core = f"[{worker.agent_type}] " if worker.agent_type else ""
    worker_model = f"  model={worker.default_model}" if worker.default_model else ""
    lines = [
        f"主 agent（写进各 cli-agent 自己的配置）：{main.name}{main_where}",
        f"worker（每次 frago agent 开会话时现读）：{worker_core}{worker.name}{worker_model}",
    ]
    if coreagent_worker.id != worker.id:
        ca_model = f"  model={coreagent_worker.default_model}" if coreagent_worker.default_model else ""
        lines.append(
            f"worker [coreagent]（CoreAgent 独立槽位）：{coreagent_worker.name}{ca_model}"
        )
    return lines


@profile_group.command("bind", cls=AgentFriendlyCommand)
@click.argument("role", type=click.Choice(["main", "worker"]))
@click.argument("connection", type=str)
@click.option(
    "--target",
    "targets",
    multiple=True,
    help="main only: which cli-agents to write it into (repeatable). "
         "Omit to keep frago's historical default (claude).",
)
def profile_bind(role: str, connection: str, targets: tuple[str, ...]):
    """把一个角色指向一条连接。CONNECTION 填 profile 名、id，或 official。

    \b
      frago profile bind worker "OpenRouter Kimi K3"
      frago profile bind main official          # 回到官方订阅
    """
    from frago.init.profile_manager import bind_role, list_connections

    picked = next(
        (c for c in list_connections() if connection in (c.name, c.id)),
        None,
    )
    if picked is None:
        available = ", ".join(c.name for c in list_connections())
        raise click.ClickException(f"没有这条连接：{connection!r}。可选：{available}")

    try:
        bound = bind_role(role, picked.id, list(targets) or None)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"[OK] {role} → {bound.name}")
    click.echo()
    for line in _binding_lines():
        click.echo(line)


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
        # 绑定先于名单：不带 --use-profile 的那些调用（绝大多数）跑在哪一条，答案在这
        # 两行里，而不在下面那张可选名单里。
        click.echo("当前角色绑定：")
        for line in _binding_lines():
            click.echo(f"  {line}")
        click.echo()
        if not profiles:
            click.echo("当前可用 profile：无（尚未在 WebUI 设置里创建任何 profile）。")
        else:
            click.echo("当前可用 profile（--use-profile 可填 name）：")
            for p in profiles:
                active = "（主 agent 在用）" if p.id == store.active_profile_id else ""
                core = f"[{p.agent_type}] " if p.agent_type else ""
                click.echo(
                    f"  - {core}{p.name}{active}  [{p.endpoint_type}]  model={p.default_model or '-'}"
                )
        click.echo()
        click.echo(_ccr_hint())
        return

    click.echo()
    for line in _binding_lines():
        click.echo(line)
    click.echo()

    if not profiles:
        click.echo("No profiles saved. Create one in the WebUI settings.")
        return

    coreagent_worker_id = store.worker_harness_profiles.get("coreagent")
    for p in profiles:
        roles = []
        if p.id == store.active_profile_id:
            roles.append("main")
        if p.id == store.worker_profile_id:
            roles.append("worker")
        if (
            coreagent_worker_id
            and coreagent_worker_id not in ("follow", "official")
            and p.id == coreagent_worker_id
            and p.id != store.worker_profile_id
        ):
            roles.append("worker(coreagent)")
        used_by = "  ← " + "/".join(roles) if roles else ""
        click.echo(f"{p.name}{used_by}")
        click.echo(f"  id:        {p.id}")
        # 厂商 CLI 型没有端点也没有密钥——那两行照印会印出两个空壳，让人以为配漏了。
        if p.agent_type:
            click.echo(f"  core:      {p.agent_type}（跑它自己的账号）")
        else:
            click.echo(f"  endpoint:  {p.endpoint_type}  {p.url or ''}".rstrip())
        click.echo(f"  model:     {p.default_model or '-'}")
        if p.api_key:
            click.echo(f"  api_key:   {_mask_api_key(p.api_key)}")
        # 激活到哪几个 cli-agent 上——"激活中"三个字本身不说明它影响了谁。
        if p.id == store.active_profile_id:
            click.echo(f"  active on: {', '.join(store.active_targets) or '-'}")
    click.echo()


@profile_group.command("targets", cls=AgentFriendlyCommand)
def profile_targets():
    """列出激活 profile 时可选的 cli-agent，及不可选的原因。"""
    from frago.init.profile_manager import load_profiles
    from frago.init.profile_targets import list_targets

    store = load_profiles()
    active_targets = set(store.active_targets)

    click.echo()
    for status in list_targets():
        if not status.supported:
            mark = "x"
            note = status.unsupported_reason or "不支持 frago profile"
        elif not status.installed:
            mark = "-"
            note = "本机未安装"
        else:
            mark = "*" if status.agent_type in active_targets else "o"
            note = status.path or ""
        click.echo(f"[{mark}] {status.display_name}  ({status.agent_type})")
        if note:
            click.echo(f"      {note}")
    click.echo()
    click.echo("[o] 可选  [*] 当前激活中  [-] 未安装  [x] 接不了 frago profile")
    click.echo("激活与取消激活走 WebUI 设置。")
    click.echo()
