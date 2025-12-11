#!/usr/bin/env python3
"""
Frago Agent Command - 通过 Claude CLI 执行非交互式 AI 任务

认证策略：
根据 `frago init` 写入的 ~/.frago/config.json 配置决定：
1. auth_method == "official" → 直接使用 Claude CLI
2. auth_method == "custom" → Claude CLI 使用 ~/.claude/settings.json 的 env
3. ccr_enabled == True 或 --use-ccr → 使用 CCR 代理
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import click


# =============================================================================
# 配置加载
# =============================================================================

def get_frago_config_path() -> Path:
    """获取 frago 配置文件路径"""
    return Path.home() / ".frago" / "config.json"


def load_frago_config() -> Optional[dict]:
    """
    加载 frago 配置

    Returns:
        配置字典，如果不存在或损坏返回 None
    """
    config_path = get_frago_config_path()
    if not config_path.exists():
        return None

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


# =============================================================================
# 工具函数
# =============================================================================

def find_claude_cli() -> Optional[str]:
    """
    查找 claude CLI 路径

    Returns:
        claude 可执行文件路径，未找到返回 None
    """
    return shutil.which("claude")


def check_ccr_auth() -> Tuple[bool, Optional[dict]]:
    """
    检查 CCR (Claude Code Router) 配置

    CCR 通过设置 ANTHROPIC_BASE_URL 指向本地代理来工作

    Returns:
        (是否可用, 配置信息)
    """
    # 检查 ccr 命令是否存在
    ccr_path = shutil.which("ccr")
    if not ccr_path:
        return False, None

    # 检查配置文件
    config_path = Path.home() / ".claude-code-router" / "config.json"
    if not config_path.exists():
        return False, {"error": "CCR config file not found"}

    try:
        with open(config_path, "r") as f:
            config = json.load(f)

        # 检查是否有配置的 Provider
        providers = config.get("Providers", [])
        if not providers:
            return False, {"error": "No providers configured in CCR"}

        # 检查 CCR 服务状态
        try:
            result = subprocess.run(
                ["ccr", "status"],
                capture_output=True,
                text=True,
                timeout=5
            )
            is_running = "Running" in result.stdout and "Not Running" not in result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            is_running = False

        return True, {
            "type": "ccr",
            "config_path": str(config_path),
            "providers": [p.get("name") for p in providers],
            "default_route": config.get("Router", {}).get("default", "unknown"),
            "is_running": is_running,
            "host": config.get("HOST", "127.0.0.1"),
            "port": config.get("PORT", 3456),
        }
    except (json.JSONDecodeError, IOError) as e:
        return False, {"error": f"Failed to read CCR config: {e}"}


def should_use_ccr(config: Optional[dict], force_ccr: bool = False) -> Tuple[bool, Optional[dict]]:
    """
    判断是否应该使用 CCR

    Args:
        config: frago 配置
        force_ccr: 是否强制使用 CCR (--use-ccr 标志)

    Returns:
        (是否使用 CCR, CCR 配置信息)
    """
    # 强制使用 CCR
    if force_ccr:
        ok, info = check_ccr_auth()
        return ok, info

    # 根据配置判断
    if config and config.get("ccr_enabled"):
        ok, info = check_ccr_auth()
        return ok, info

    return False, None


def verify_claude_working(timeout: int = 30) -> Tuple[bool, str]:
    """
    通过运行简单提示词验证 Claude CLI 是否正常工作

    Args:
        timeout: 超时时间（秒）

    Returns:
        (是否正常, 错误信息或成功信息)
    """
    try:
        result = subprocess.run(
            ["claude", "-p", "Say 'OK'", "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=timeout
        )

        if result.returncode == 0:
            try:
                response = json.loads(result.stdout)
                if response.get("type") == "result":
                    return True, "Claude CLI is working"
            except json.JSONDecodeError:
                pass
            return True, "Claude CLI responded"

        # 解析错误信息
        error_msg = result.stderr or result.stdout or "Unknown error"
        if "authentication" in error_msg.lower() or "unauthorized" in error_msg.lower():
            return False, "Authentication failed - please run 'claude' and use /login"
        if "rate limit" in error_msg.lower():
            return False, "Rate limited - please wait and try again"

        return False, f"Claude CLI error: {error_msg[:200]}"

    except subprocess.TimeoutExpired:
        return False, f"Claude CLI timed out after {timeout}s"
    except FileNotFoundError:
        return False, "Claude CLI not found"
    except Exception as e:
        return False, f"Unexpected error: {e}"


def run_claude_command(
    prompt: str,
    env: dict,
    output_format: str = "json",
    timeout: int = 120,
    model: Optional[str] = None,
    skip_permissions: bool = True
) -> Tuple[bool, str, Optional[dict]]:
    """
    执行 claude 命令并返回结果

    Args:
        prompt: 提示词
        env: 环境变量
        output_format: 输出格式
        timeout: 超时时间
        model: 模型
        skip_permissions: 是否跳过权限确认

    Returns:
        (是否成功, 原始输出, 解析后的 JSON)
    """
    cmd = ["claude", "-p", prompt, "--output-format", output_format]

    if model:
        cmd.extend(["--model", model])

    if skip_permissions:
        cmd.append("--dangerously-skip-permissions")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout
        )

        output = result.stdout

        if result.returncode == 0 and output_format == "json":
            try:
                parsed = json.loads(output)
                return True, output, parsed
            except json.JSONDecodeError:
                return True, output, None

        return result.returncode == 0, output, None

    except subprocess.TimeoutExpired:
        return False, f"Timeout after {timeout}s", None
    except Exception as e:
        return False, str(e), None


def parse_routing_response(response_text: str) -> Optional[dict]:
    """
    解析路由响应，提取 JSON

    Args:
        response_text: Claude 返回的文本

    Returns:
        解析后的路由信息，或 None
    """
    # 尝试直接解析
    try:
        return json.loads(response_text.strip())
    except json.JSONDecodeError:
        pass

    # 尝试从 markdown code block 中提取
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试从文本中找 JSON 对象
    json_match = re.search(r'\{[^{}]*"command"[^{}]*\}', response_text)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


# =============================================================================
# Slash Command 展开
# =============================================================================

def find_slash_command_file(command: str) -> Optional[Path]:
    """
    查找 slash command 对应的 markdown 文件

    命令格式转换规则：
    - /frago.dev.agent → frago.dev.agent.md（开发环境）
    - /frago.agent → frago.agent.md（生产环境）

    支持 .dev fallback：
    - 请求 /frago.dev.agent 时，先找 frago.dev.agent.md
    - 找不到则 fallback 到 frago.agent.md（去掉 .dev）

    搜索路径优先级（每个路径都尝试 .dev 和非 .dev 版本）：
    1. 当前工作目录 .claude/commands/
    2. 用户目录 ~/.claude/commands/
    3. frago 资源目录（打包的默认命令）

    Args:
        command: slash command 名称，如 "/frago.dev.agent" 或 "frago.agent"

    Returns:
        找到的文件路径，或 None
    """
    # 规范化命令名：去掉前导 /
    cmd_name = command.lstrip("/")

    # 生成候选文件名列表
    # 如果是 .dev 命名，同时生成 .dev 版本和非 .dev 版本
    filenames = [f"{cmd_name}.md"]
    if ".dev." in cmd_name:
        # frago.dev.agent → frago.agent
        non_dev_name = cmd_name.replace(".dev.", ".")
        filenames.append(f"{non_dev_name}.md")

    # 搜索目录
    search_dirs = [
        Path.cwd() / ".claude" / "commands",
        Path.home() / ".claude" / "commands",
    ]

    # 添加 frago 资源目录（打包的默认命令）
    try:
        from importlib.resources import files
        resources_dir = files("frago") / "resources" / "commands"
        # importlib.resources 返回 Traversable，需要转换
        if hasattr(resources_dir, '_path'):
            search_dirs.append(Path(resources_dir._path))
        else:
            search_dirs.append(Path(str(resources_dir)))
    except (ImportError, TypeError):
        pass

    # 按目录优先级搜索，每个目录内先尝试 .dev 再尝试非 .dev
    for search_dir in search_dirs:
        for filename in filenames:
            path = search_dir / filename
            if path.exists():
                return path

    return None


def expand_slash_command(command: str, arguments: str = "") -> Tuple[bool, str, str]:
    """
    展开 slash command 为完整的 prompt 内容

    处理流程：
    1. 查找命令文件
    2. 读取并解析 YAML frontmatter（如果有）
    3. 替换 $ARGUMENTS 占位符

    Args:
        command: slash command 名称，如 "/frago.dev.agent"
        arguments: 用户参数，用于替换 $ARGUMENTS

    Returns:
        (是否成功, 展开后的内容, 错误信息)
    """
    cmd_file = find_slash_command_file(command)

    if not cmd_file:
        return False, "", f"Slash command not found: {command}"

    try:
        content = cmd_file.read_text(encoding="utf-8")
    except IOError as e:
        return False, "", f"Failed to read command file: {e}"

    # 移除 YAML frontmatter（如果存在）
    # frontmatter 格式：以 --- 开头和结尾
    if content.startswith("---"):
        # 找到第二个 ---
        second_delimiter = content.find("---", 3)
        if second_delimiter != -1:
            content = content[second_delimiter + 3:].lstrip("\n")

    # 替换 $ARGUMENTS 占位符
    content = content.replace("$ARGUMENTS", arguments)

    return True, content, ""


def get_available_slash_commands() -> dict:
    """
    获取所有可用的 frago slash commands

    Returns:
        命令名到描述的映射，如 {"/frago.dev.run": "执行AI主持的..."}
    """
    commands = {}

    # 搜索路径
    search_dirs = [
        Path.cwd() / ".claude" / "commands",
        Path.home() / ".claude" / "commands",
    ]

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue

        # 查找 frago.*.md 文件
        for md_file in search_dir.glob("frago*.md"):
            cmd_name = "/" + md_file.stem  # frago.dev.run.md → /frago.dev.run

            if cmd_name in commands:
                continue  # 优先使用先找到的

            # 尝试提取 description
            try:
                content = md_file.read_text(encoding="utf-8")
                if content.startswith("---"):
                    # 解析 YAML frontmatter
                    second_delimiter = content.find("---", 3)
                    if second_delimiter != -1:
                        frontmatter = content[3:second_delimiter].strip()
                        # 简单提取 description
                        for line in frontmatter.split("\n"):
                            if line.startswith("description:"):
                                desc = line[12:].strip().strip('"\'')
                                commands[cmd_name] = desc
                                break
                        else:
                            commands[cmd_name] = ""
                else:
                    commands[cmd_name] = ""
            except IOError:
                commands[cmd_name] = ""

    return commands


# =============================================================================
# CLI 命令
# =============================================================================

@click.command("agent")
@click.argument("prompt", nargs=-1, required=True)
@click.option(
    "--model",
    type=str,
    default=None,
    help="指定模型 (sonnet, opus, haiku 或完整模型名)"
)
@click.option(
    "--timeout",
    type=int,
    default=600,
    help="执行超时时间（秒），默认 600"
)
@click.option(
    "--use-ccr",
    is_flag=True,
    help="强制使用 CCR (Claude Code Router)"
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="仅显示将要执行的命令，不实际执行"
)
@click.option(
    "--ask",
    is_flag=True,
    help="启用权限确认（默认跳过）"
)
@click.option(
    "--direct",
    is_flag=True,
    help="直接执行，跳过路由分析"
)
@click.option(
    "--quiet", "-q",
    is_flag=True,
    help="静默模式，不显示实时监控状态"
)
@click.option(
    "--json-status",
    is_flag=True,
    help="以 JSON 格式输出监控状态（用于机器处理）"
)
@click.option(
    "--no-monitor",
    is_flag=True,
    help="禁用会话监控（不记录会话数据）"
)
@click.option(
    "--yes", "-y",
    is_flag=True,
    help="跳过权限确认提示，直接执行"
)
@click.option(
    "--resume", "-r",
    type=str,
    default=None,
    help="在指定会话中继续对话（传入 session_id）"
)
def agent(
    prompt: tuple,
    model: Optional[str],
    timeout: int,
    use_ccr: bool,
    dry_run: bool,
    ask: bool,
    direct: bool,
    quiet: bool,
    json_status: bool,
    no_monitor: bool,
    yes: bool,
    resume: Optional[str]
):
    """
    智能 Agent：分析意图并路由到对应的 frago 子命令

    两阶段执行流程：
    1. 分析用户提示词，判断应调用哪个 /frago.* 命令
    2. 使用对应命令执行实际任务

    \b
    示例:
      frago agent 帮我在 Upwork 上找 Python 工作
      frago agent 调研 YouTube 字幕提取接口
      frago agent 写一个配方提取 Twitter 评论
      frago agent --direct 列出当前目录     # 跳过路由，直接执行

    \b
    可用的子命令路由:
      /frago.run    - 探索调研、信息收集
      /frago.exec   - 一次性任务执行
      /frago.recipe - 创建自动化配方
      /frago.test   - 测试验证配方

    \b
    可用模型 (--model):
      sonnet, opus, haiku 或完整模型名
    """
    # 将多个参数拼接成完整提示词
    prompt_text = " ".join(prompt)

    # Step 1: 检查 claude CLI 是否存在
    claude_path = find_claude_cli()
    if not claude_path:
        click.echo("错误: 未找到 claude CLI", err=True)
        click.echo("请先安装 Claude Code: https://claude.ai/code", err=True)
        sys.exit(1)

    click.echo(f"✓ Claude CLI: {claude_path}")

    # Step 2: 加载 frago 配置
    frago_config = load_frago_config()
    if frago_config:
        auth_method = frago_config.get("auth_method", "official")
        if auth_method == "official":
            click.echo("✓ 认证方式: Claude CLI 原生")
        else:
            click.echo("✓ 认证方式: 自定义 API 端点")
    else:
        click.echo("⚠ 未找到 frago 配置，使用 Claude CLI 默认认证")
        click.echo("  提示: 运行 'frago init' 进行初始化配置")

    # Step 3: 判断是否使用 CCR
    env = os.environ.copy()
    use_ccr_mode, ccr_info = should_use_ccr(frago_config, use_ccr)

    if use_ccr_mode:
        if not ccr_info:
            click.echo("\n错误: CCR 配置无效", err=True)
            sys.exit(1)

        host = ccr_info.get("host", "127.0.0.1")
        port = ccr_info.get("port", 3456)
        env["ANTHROPIC_AUTH_TOKEN"] = "test"
        env["ANTHROPIC_BASE_URL"] = f"http://{host}:{port}"
        env["NO_PROXY"] = "127.0.0.1"
        env["DISABLE_TELEMETRY"] = "true"

        if not ccr_info.get("is_running"):
            click.echo("正在启动 CCR 服务...")
            subprocess.run(["ccr", "start"], capture_output=True, env=env)

        click.echo(f"✓ 使用 CCR: http://{host}:{port}")

    # Step 4: 权限确认（--yes 跳过确认）
    if not ask and not dry_run and not yes:
        click.echo()
        click.echo("⚠ 将以 --dangerously-skip-permissions 模式运行")
        click.echo("  Claude 将跳过所有权限确认，直接执行任何操作")
        if not click.confirm("确认继续？", default=False):
            click.echo("已取消")
            sys.exit(0)

    skip_permissions = not ask

    # =========================================================================
    # 两阶段执行流程
    # =========================================================================

    if direct or resume:
        # 直接模式或继续会话模式：跳过路由，直接执行用户提示词
        if resume:
            click.echo(f"\n[Resume] 在会话 {resume[:8]}... 中继续: {prompt_text}")
        else:
            click.echo(f"\n[Direct] 直接执行: {prompt_text}")
        target_command = None
        final_prompt = prompt_text
    else:
        # 阶段一：路由分析
        click.echo(f"\n[阶段一] 分析意图: {prompt_text}")

        # 展开 /frago.dev.agent slash command
        # 注意：claude -p 模式不支持 slash commands，必须手动展开
        ok, routing_template, error = expand_slash_command("/frago.dev.agent", prompt_text)
        if not ok:
            click.echo(f"✗ 无法加载路由命令: {error}", err=True)
            click.echo("  降级为直接执行模式...")
            target_command = None
            final_prompt = prompt_text
        else:
            routing_prompt = routing_template

            if dry_run:
                click.echo(f"[Dry Run] 路由提示词长度: {len(routing_prompt)} 字符")
                click.echo("[Dry Run] 跳过实际执行")
                return

            click.echo("  正在分析...")

            ok, output, parsed = run_claude_command(
                routing_prompt,
                env=env,
                output_format="json",
                timeout=60,
                model=model or "haiku",  # 路由分析用快速模型
                skip_permissions=skip_permissions
            )

            if not ok:
                click.echo(f"✗ 路由分析失败: {output}", err=True)
                return

            # 从 JSON 响应中提取 result
            result_text = ""
            if parsed and parsed.get("result"):
                result_text = parsed.get("result", "")
            else:
                result_text = output

            # 解析路由结果
            routing = parse_routing_response(result_text)

            if not routing or "command" not in routing:
                click.echo(f"✗ 无法解析路由结果", err=True)
                click.echo(f"  原始响应: {result_text[:500]}", err=True)
                # 降级：直接执行
                click.echo("  降级为直接执行模式...")
                target_command = None
                final_prompt = prompt_text
            else:
                target_command = routing.get("command")
                final_prompt = routing.get("prompt", prompt_text)
                reason = routing.get("reason", "")

                click.echo(f"  ✓ 路由到: {target_command}")
                if reason:
                    click.echo(f"  原因: {reason}")

    # 阶段二：执行实际命令
    if target_command:
        click.echo(f"\n[阶段二] 执行: {target_command}")

        # 展开目标 slash command
        # 注意：claude -p 模式不支持 slash commands，必须手动展开
        # 这里传空字符串，因为我们会在后面手动拼接用户提示词
        ok, expanded_prompt, error = expand_slash_command(target_command, "")
        if not ok:
            click.echo(f"✗ 无法加载命令 {target_command}: {error}", err=True)
            click.echo("  降级为直接执行用户提示词...")
            execution_prompt = final_prompt
        else:
            # 拼接：展开的命令文档 + 用户原始提示词
            execution_prompt = f"{expanded_prompt}\n\n---\n\n## 当前任务\n\n{final_prompt}"
            click.echo(f"  ✓ 已展开命令 ({len(execution_prompt)} 字符)")
    else:
        click.echo(f"\n[执行] {final_prompt}")
        execution_prompt = final_prompt

    # 构建最终命令 - 使用 stream-json 实现实时输出
    # 注意：stream-json 必须配合 --verbose 使用
    cmd = ["claude", "-p", execution_prompt, "--output-format", "stream-json", "--verbose"]

    if resume:
        cmd.extend(["--resume", resume])

    if model:
        cmd.extend(["--model", model])

    if skip_permissions:
        cmd.append("--dangerously-skip-permissions")

    click.echo("-" * 60)

    # 启动会话监控（如果未禁用）
    monitor = None
    monitor_enabled = not no_monitor and os.environ.get("FRAGO_MONITOR_ENABLED", "1") != "0"

    if monitor_enabled:
        try:
            from frago.session.monitor import SessionMonitor

            start_time = datetime.now(timezone.utc)
            project_path = os.getcwd()

            monitor = SessionMonitor(
                project_path=project_path,
                start_time=start_time,
                json_mode=json_status,
                persist=True,
                quiet=quiet,
                target_session_id=resume,  # resume 时直接监控指定会话
            )
            monitor.start()
        except ImportError as e:
            # session 模块可能未安装，静默忽略
            if not quiet:
                click.echo(f"  ⚠ 会话监控未启用: {e}", err=True)
        except Exception as e:
            if not quiet:
                click.echo(f"  ⚠ 启动监控失败: {e}", err=True)

    # 执行命令（实时流式输出）
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            bufsize=1,
            universal_newlines=True
        )

        # [临时禁用] 解析 stream-json 格式并实时显示
        # 目的：测试新的 SessionMonitor 监控功能
        # TODO: 测试完成后决定保留哪套或合并
        for line in iter(process.stdout.readline, ""):
            pass  # 消费 stdout 但不处理，让 SessionMonitor 接管显示
        #     line = line.strip()
        #     if not line:
        #         continue
        #
        #     try:
        #         event = json.loads(line)
        #         event_type = event.get("type", "")
        #
        #         # 处理不同类型的流式事件
        #         if event_type == "assistant":
        #             # 助手消息 - 包含文本或工具调用
        #             message = event.get("message", {})
        #             content = message.get("content", [])
        #             for block in content:
        #                 block_type = block.get("type")
        #                 if block_type == "text":
        #                     text = block.get("text", "")
        #                     if text:
        #                         click.echo(text)
        #                 elif block_type == "tool_use":
        #                     tool_name = block.get("name", "unknown")
        #                     tool_input = block.get("input", {})
        #                     # 显示工具调用信息
        #                     if tool_name == "Bash":
        #                         cmd = tool_input.get("command", "")
        #                         desc = tool_input.get("description", "")
        #                         click.echo(f"[Bash] {desc or cmd[:50]}")
        #                     else:
        #                         click.echo(f"[{tool_name}]")
        #         elif event_type == "user":
        #             # 工具执行结果
        #             tool_result = event.get("tool_use_result", {})
        #             if tool_result and isinstance(tool_result, dict):
        #                 stdout = tool_result.get("stdout", "")
        #                 stderr = tool_result.get("stderr", "")
        #                 if stdout:
        #                     # 只显示前几行，避免输出过多
        #                     lines = stdout.strip().split("\n")
        #                     if len(lines) > 10:
        #                         click.echo(f"  (输出 {len(lines)} 行，显示前 5 行)")
        #                         click.echo("\n".join(lines[:5]))
        #                         click.echo("  ...")
        #                     elif stdout.strip():
        #                         click.echo(f"  {stdout.strip()[:200]}")
        #                 if stderr:
        #                     click.echo(f"  [stderr] {stderr.strip()[:100]}", err=True)
        #         elif event_type == "result":
        #             # 最终结果
        #             pass  # 不重复显示，assistant 已经输出过了
        #         # 忽略其他事件类型（如 system, content_block_delta 等）
        #
        #     except json.JSONDecodeError:
        #         # 非 JSON 行直接输出
        #         click.echo(line)

        # 读取 stderr
        stderr_output = process.stderr.read()
        if stderr_output:
            click.echo(f"\n[stderr] {stderr_output}", err=True)

        process.wait(timeout=timeout)

        click.echo("\n" + "-" * 60)

        if process.returncode == 0:
            click.echo("✓ 执行完成")
        else:
            # 非零退出码不强制退出，Claude CLI 会自适应处理工具错误
            click.echo(f"⚠ 执行结束 (退出码: {process.returncode})")

    except subprocess.TimeoutExpired:
        process.kill()
        click.echo(f"\n✗ 执行超时 ({timeout}s)", err=True)
    except KeyboardInterrupt:
        process.kill()
        click.echo("\n✗ 用户中断", err=True)
    except Exception as e:
        click.echo(f"\n✗ 执行错误: {e}", err=True)
    finally:
        # 停止会话监控
        if monitor:
            try:
                monitor.stop()
            except Exception:
                pass


# =============================================================================
# 辅助命令：检查认证状态
# =============================================================================

@click.command("agent-status")
def agent_status():
    """
    检查 Claude CLI 认证状态

    显示当前可用的认证方式和配置信息。
    """
    click.echo("Claude CLI 认证状态检查")
    click.echo("=" * 50)

    # 检查 claude CLI
    claude_path = find_claude_cli()
    if claude_path:
        click.echo(f"✓ Claude CLI: {claude_path}")
        # 获取版本
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                click.echo(f"  版本: {result.stdout.strip()}")
        except Exception:
            pass
    else:
        click.echo("✗ Claude CLI: 未安装")
        return

    click.echo()

    # 加载 frago 配置
    click.echo("Frago 配置:")
    frago_config = load_frago_config()
    if frago_config:
        auth_method = frago_config.get("auth_method", "official")
        ccr_enabled = frago_config.get("ccr_enabled", False)
        init_completed = frago_config.get("init_completed", False)

        click.echo(f"  配置文件: {get_frago_config_path()}")
        click.echo(f"  认证方式: {'Claude CLI 原生' if auth_method == 'official' else '自定义 API 端点'}")
        click.echo(f"  CCR 启用: {'是' if ccr_enabled else '否'}")
        click.echo(f"  初始化状态: {'已完成' if init_completed else '未完成'}")
    else:
        click.echo("  ⚠ 未找到配置文件")
        click.echo(f"  提示: 运行 'frago init' 进行初始化配置")

    click.echo()

    # 检查 CCR 状态（如果启用）
    if frago_config and frago_config.get("ccr_enabled"):
        click.echo("CCR 状态:")
        ok, info = check_ccr_auth()
        if ok:
            click.echo(f"  ✓ CCR 可用")
            click.echo(f"    Providers: {', '.join(info.get('providers', []))}")
            click.echo(f"    运行状态: {'运行中' if info.get('is_running') else '未运行'}")
        else:
            click.echo("  ✗ CCR 不可用")
            if info and info.get("error"):
                click.echo(f"    原因: {info['error']}")
