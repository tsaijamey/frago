#!/usr/bin/env python3
"""
Frago Agent Command - 通过 Claude CLI 执行非交互式 AI 任务

支持多种认证方式的检测：
1. Claude 订阅登录 (claudeAiOauth)
2. Anthropic API Key (ANTHROPIC_API_KEY)
3. 第三方 API (AWS Bedrock, Google Vertex)
4. CCR (Claude Code Router) 本地代理
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

import click


# =============================================================================
# 认证状态枚举
# =============================================================================

class AuthType:
    """认证类型"""
    SUBSCRIPTION = "subscription"  # Claude 订阅 (Pro/Max/Team)
    API_KEY = "api_key"           # Anthropic API Key
    BEDROCK = "bedrock"           # AWS Bedrock
    VERTEX = "vertex"             # Google Vertex AI
    CCR = "ccr"                   # Claude Code Router
    NONE = "none"                 # 未认证


# =============================================================================
# 认证检测函数
# =============================================================================

def find_claude_cli() -> Optional[str]:
    """
    查找 claude CLI 路径

    Returns:
        claude 可执行文件路径，未找到返回 None
    """
    return shutil.which("claude")


def check_subscription_auth() -> Tuple[bool, Optional[dict]]:
    """
    检查 Claude 订阅认证状态

    Returns:
        (是否已认证, 认证信息)
    """
    creds_path = Path.home() / ".claude" / ".credentials.json"
    if not creds_path.exists():
        return False, None

    try:
        with open(creds_path, "r") as f:
            creds = json.load(f)

        oauth = creds.get("claudeAiOauth")
        if oauth and oauth.get("accessToken"):
            return True, {
                "type": AuthType.SUBSCRIPTION,
                "subscription_type": oauth.get("subscriptionType", "unknown"),
                "rate_limit_tier": oauth.get("rateLimitTier", "unknown"),
                "expires_at": oauth.get("expiresAt"),
            }
    except (json.JSONDecodeError, IOError):
        pass

    return False, None


def check_api_key_auth() -> Tuple[bool, Optional[dict]]:
    """
    检查 Anthropic API Key 认证

    Returns:
        (是否已认证, 认证信息)
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key and api_key.startswith("sk-ant-"):
        return True, {
            "type": AuthType.API_KEY,
            "key_prefix": api_key[:15] + "...",
        }
    return False, None


def check_bedrock_auth() -> Tuple[bool, Optional[dict]]:
    """
    检查 AWS Bedrock 认证

    Returns:
        (是否已认证, 认证信息)
    """
    use_bedrock = os.environ.get("CLAUDE_CODE_USE_BEDROCK")
    if use_bedrock and use_bedrock.lower() in ("1", "true", "yes"):
        return True, {
            "type": AuthType.BEDROCK,
            "region": os.environ.get("AWS_REGION", "unknown"),
        }
    return False, None


def check_vertex_auth() -> Tuple[bool, Optional[dict]]:
    """
    检查 Google Vertex AI 认证

    Returns:
        (是否已认证, 认证信息)
    """
    use_vertex = os.environ.get("CLAUDE_CODE_USE_VERTEX")
    if use_vertex and use_vertex.lower() in ("1", "true", "yes"):
        return True, {
            "type": AuthType.VERTEX,
            "project": os.environ.get("GOOGLE_CLOUD_PROJECT", "unknown"),
        }
    return False, None


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
            "type": AuthType.CCR,
            "config_path": str(config_path),
            "providers": [p.get("name") for p in providers],
            "default_route": config.get("Router", {}).get("default", "unknown"),
            "is_running": is_running,
            "host": config.get("HOST", "127.0.0.1"),
            "port": config.get("PORT", 3456),
        }
    except (json.JSONDecodeError, IOError) as e:
        return False, {"error": f"Failed to read CCR config: {e}"}


def detect_auth_method() -> Tuple[str, Optional[dict]]:
    """
    检测当前可用的认证方式（按优先级）

    优先级：
    1. Anthropic API Key (环境变量优先)
    2. AWS Bedrock
    3. Google Vertex AI
    4. Claude 订阅
    5. CCR (作为后备)

    Returns:
        (认证类型, 认证信息)
    """
    # 1. 检查 API Key
    ok, info = check_api_key_auth()
    if ok:
        return AuthType.API_KEY, info

    # 2. 检查 Bedrock
    ok, info = check_bedrock_auth()
    if ok:
        return AuthType.BEDROCK, info

    # 3. 检查 Vertex
    ok, info = check_vertex_auth()
    if ok:
        return AuthType.VERTEX, info

    # 4. 检查订阅
    ok, info = check_subscription_auth()
    if ok:
        return AuthType.SUBSCRIPTION, info

    # 5. 检查 CCR（作为后备方案）
    ok, info = check_ccr_auth()
    if ok:
        return AuthType.CCR, info

    return AuthType.NONE, None


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
    import re
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
    "--skip-auth-check",
    is_flag=True,
    help="跳过认证检查，直接执行"
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
def agent(
    prompt: tuple,
    model: Optional[str],
    timeout: int,
    use_ccr: bool,
    skip_auth_check: bool,
    dry_run: bool,
    ask: bool,
    direct: bool
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
      /frago.dev.run    - 探索调研、信息收集
      /frago.dev.exec   - 一次性任务执行
      /frago.dev.recipe - 创建自动化配方
      /frago.dev.test   - 测试验证配方

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

    # Step 2: 检测认证方式
    if not skip_auth_check:
        auth_type, auth_info = detect_auth_method()

        if auth_type == AuthType.NONE:
            click.echo("\n错误: 未检测到有效的认证方式", err=True)
            click.echo("\n可用的认证方式:", err=True)
            click.echo("  1. 订阅登录: 运行 'claude' 后使用 /login", err=True)
            click.echo("  2. API Key: export ANTHROPIC_API_KEY=sk-ant-...", err=True)
            click.echo("  3. CCR: 配置 ~/.claude-code-router/config.json 并运行 'ccr start'", err=True)
            sys.exit(1)

        # 显示认证信息
        click.echo(f"✓ 认证方式: {auth_type}")
        if auth_info:
            if auth_type == AuthType.SUBSCRIPTION:
                click.echo(f"  订阅类型: {auth_info.get('subscription_type', 'unknown')}")
            elif auth_type == AuthType.API_KEY:
                click.echo(f"  API Key: {auth_info.get('key_prefix', 'unknown')}")
            elif auth_type == AuthType.CCR:
                click.echo(f"  Providers: {', '.join(auth_info.get('providers', []))}")
                if not auth_info.get("is_running"):
                    click.echo("  ⚠ CCR 服务未运行，正在启动...", err=True)
                    subprocess.run(["ccr", "start"], capture_output=True)

    # Step 3: 设置环境变量
    env = os.environ.copy()
    if use_ccr:
        ok, ccr_info = check_ccr_auth()
        if not ok:
            click.echo(f"\n错误: CCR 不可用 - {ccr_info.get('error', 'unknown')}", err=True)
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

    # Step 4: 权限确认
    if not ask and not dry_run:
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

    if direct:
        # 直接模式：跳过路由，直接执行用户提示词
        click.echo(f"\n[Direct] 直接执行: {prompt_text}")
        target_command = None
        final_prompt = prompt_text
    else:
        # 阶段一：路由分析
        click.echo(f"\n[阶段一] 分析意图: {prompt_text}")

        routing_prompt = f"/frago.agent {prompt_text}"

        if dry_run:
            click.echo(f"[Dry Run] 路由提示词: {routing_prompt}")
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
            sys.exit(1)

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
        click.echo(f"\n[阶段二] 执行: {target_command} {final_prompt}")
        execution_prompt = f"{target_command} {final_prompt}"
    else:
        click.echo(f"\n[执行] {final_prompt}")
        execution_prompt = final_prompt

    # 构建最终命令
    cmd = ["claude", "-p", execution_prompt, "--output-format", "text"]

    if model:
        cmd.extend(["--model", model])

    if skip_permissions:
        cmd.append("--dangerously-skip-permissions")

    click.echo("-" * 60)

    # 执行命令（实时输出）
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            bufsize=1,
            universal_newlines=True
        )

        for line in iter(process.stdout.readline, ""):
            click.echo(line, nl=False)

        process.wait(timeout=timeout)

        click.echo("-" * 60)

        if process.returncode == 0:
            click.echo("✓ 执行完成")
        else:
            click.echo(f"✗ 执行失败 (退出码: {process.returncode})", err=True)
            sys.exit(process.returncode)

    except subprocess.TimeoutExpired:
        process.kill()
        click.echo(f"\n✗ 执行超时 ({timeout}s)", err=True)
        sys.exit(1)
    except KeyboardInterrupt:
        process.kill()
        click.echo("\n✗ 用户中断", err=True)
        sys.exit(130)
    except Exception as e:
        click.echo(f"\n✗ 执行错误: {e}", err=True)
        sys.exit(1)


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

    # 检查各种认证方式
    checks = [
        ("Anthropic API Key", check_api_key_auth),
        ("AWS Bedrock", check_bedrock_auth),
        ("Google Vertex AI", check_vertex_auth),
        ("Claude 订阅", check_subscription_auth),
        ("CCR (Claude Code Router)", check_ccr_auth),
    ]

    available_auth = []

    for name, check_func in checks:
        ok, info = check_func()
        if ok:
            click.echo(f"✓ {name}")
            available_auth.append(name)
            if info:
                for key, value in info.items():
                    if key != "type":
                        click.echo(f"    {key}: {value}")
        else:
            click.echo(f"✗ {name}")
            if info and info.get("error"):
                click.echo(f"    原因: {info['error']}")

    click.echo()

    # 总结
    if available_auth:
        click.echo(f"可用认证方式: {', '.join(available_auth)}")

        # 验证实际工作状态
        click.echo("\n验证 Claude CLI 连接...")
        ok, msg = verify_claude_working(timeout=30)
        if ok:
            click.echo(f"✓ {msg}")
        else:
            click.echo(f"✗ {msg}")
    else:
        click.echo("⚠ 未检测到可用的认证方式")
        click.echo("\n请使用以下方式之一进行认证:")
        click.echo("  1. 订阅登录: 运行 'claude' 后使用 /login")
        click.echo("  2. API Key: export ANTHROPIC_API_KEY=sk-ant-...")
        click.echo("  3. CCR: 配置并启动 Claude Code Router")
