"""
配置管理模块

提供 Frago 配置的加载、保存和交互式配置功能：
- 认证方式选择（官方 vs 自定义端点）
- 配置持久化到 ~/.frago/config.json
- 配置摘要显示
- 配置更新流程
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import click

from frago.init.models import Config, APIEndpoint


# 预设端点配置（用于 Claude Code settings.json 的 env 字段）
# 各厂商均提供 Anthropic API 兼容接口
PRESET_ENDPOINTS = {
    "deepseek": {
        "display_name": "DeepSeek (deepseek-chat)",
        "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
        "ANTHROPIC_MODEL": "deepseek-reason",
        "ANTHROPIC_SMALL_FAST_MODEL": "deepseek-chat",
        "API_TIMEOUT_MS": 600000,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": 1,
    },
    "aliyun": {
        "display_name": "阿里云百炼 (qwen3-coder-plus)",
        "ANTHROPIC_BASE_URL": "https://dashscope.aliyuncs.com/apps/anthropic",
        "ANTHROPIC_MODEL": "qwen3-coder-plus",
        "ANTHROPIC_SMALL_FAST_MODEL": "qwen3-coder-plus",
        "API_TIMEOUT_MS": 600000,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": 1,
    },
    "kimi": {
        "display_name": "Kimi K2 (kimi-k2-turbo-preview)",
        "ANTHROPIC_BASE_URL": "https://api.moonshot.cn/anthropic",
        "ANTHROPIC_MODEL": "kimi-k2-turbo-preview",
        "ANTHROPIC_SMALL_FAST_MODEL": "kimi-k2-turbo-preview",
        "API_TIMEOUT_MS": 600000,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": 1,
    },
    "minimax": {
        "display_name": "MiniMax M2",
        "ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic",
        "ANTHROPIC_MODEL": "MiniMax-M2",
        "ANTHROPIC_SMALL_FAST_MODEL": "MiniMax-M2",
        "API_TIMEOUT_MS": 3000000,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": 1,
    },
}

# Claude Code 配置文件路径
CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
CLAUDE_JSON_PATH = Path.home() / ".claude.json"

# ~/.claude.json 最小化配置（用于跳过官方登录流程）
# 参考: https://github.com/anthropics/claude-code/issues/441
CLAUDE_JSON_MINIMAL = {
    "hasCompletedOnboarding": True,
    "lastOnboardingVersion": "1.0.0",
    "isQualifiedForDataSharing": False,
}


# =============================================================================
# Phase 6: User Story 4 - 自定义 API 端点配置函数
# =============================================================================


def validate_endpoint_url(url: str) -> bool:
    """
    验证 API 端点 URL 格式

    Args:
        url: 待验证的 URL

    Returns:
        True 如果 URL 有效
    """
    if not url or not isinstance(url, str):
        return False

    url = url.strip()
    if not url:
        return False

    # 必须以 http:// 或 https:// 开头
    if not (url.startswith("http://") or url.startswith("https://")):
        return False

    # 简单检查格式：协议后面需要有内容
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return bool(parsed.scheme and parsed.netloc)
    except Exception:
        return False


def prompt_endpoint_type() -> str:
    """
    提示用户选择端点类型（使用交互菜单）

    Returns:
        端点类型：deepseek, aliyun, kimi, minimax, custom
    """
    from frago.init.ui import ask_question

    # 构建选项列表
    options = []
    for key, config in PRESET_ENDPOINTS.items():
        options.append({
            "label": key,
            "description": config['display_name']
        })
    options.append({
        "label": "custom",
        "description": "Custom endpoint with manual URL configuration"
    })

    answer = ask_question(
        question="Which API endpoint do you want to use?",
        header="API Endpoint",
        options=options,
        default_index=0  # deepseek
    )

    return answer.lower()


def prompt_api_key(endpoint_name: Optional[str] = None) -> str:
    """
    提示用户输入 API Key（隐藏输入）

    Args:
        endpoint_name: 可选的端点名称，用于提示

    Returns:
        用户输入的 API Key
    """
    prompt_text = "API Key"
    if endpoint_name:
        prompt_text = f"{endpoint_name} API Key"

    return click.prompt(prompt_text, hide_input=True, type=str)


def prompt_custom_endpoint_url() -> str:
    """
    提示用户输入自定义端点 URL（带验证）

    Returns:
        验证通过的 URL
    """
    while True:
        url = click.prompt("API 端点 URL", type=str)

        if validate_endpoint_url(url):
            return url

        click.echo("❌ 无效的 URL 格式，请输入完整的 HTTP/HTTPS URL")


def prompt_custom_model() -> str:
    """
    提示用户输入自定义模型名称

    Returns:
        模型名称
    """
    return click.prompt("模型名称", type=str, default="gpt-4")


def load_claude_settings() -> dict:
    """
    加载 Claude Code settings.json

    Returns:
        配置字典，如果文件不存在则返回空字典
    """
    if not CLAUDE_SETTINGS_PATH.exists():
        return {}

    try:
        with open(CLAUDE_SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_claude_settings(settings: dict) -> None:
    """
    保存 Claude Code settings.json（合并写入，不覆盖原有字段）

    Args:
        settings: 要合并的配置字典
    """
    # 确保目录存在
    CLAUDE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

    # 加载现有配置
    existing = load_claude_settings()

    # 合并 env 字段（深度合并）
    if "env" in settings:
        if "env" not in existing:
            existing["env"] = {}
        existing["env"].update(settings["env"])
        del settings["env"]

    # 合并其他顶级字段
    existing.update(settings)

    # 写入文件
    with open(CLAUDE_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)


def check_claude_json_exists() -> bool:
    """
    检查 ~/.claude.json 是否存在

    Returns:
        True 如果文件存在
    """
    return CLAUDE_JSON_PATH.exists()


def load_claude_json() -> dict:
    """
    加载 ~/.claude.json

    Returns:
        配置字典，如果文件不存在则返回空字典
    """
    if not CLAUDE_JSON_PATH.exists():
        return {}

    try:
        with open(CLAUDE_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def ensure_claude_json_for_custom_auth() -> bool:
    """
    确保 ~/.claude.json 存在并包含跳过官方登录所需的最小字段

    当用户选择 custom API 端点时调用此函数。
    如果文件不存在，创建最小化配置；
    如果文件存在但缺少关键字段，补充缺失字段。

    Returns:
        True 如果创建或修改了文件，False 如果文件已存在且完整
    """
    import click

    file_existed = check_claude_json_exists()
    existing = load_claude_json()
    modified = False

    # 检查并补充缺失的关键字段
    for key, value in CLAUDE_JSON_MINIMAL.items():
        if key not in existing:
            existing[key] = value
            modified = True

    if modified:
        # 写入文件
        try:
            with open(CLAUDE_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)

            if not file_existed:
                click.echo("   ✓ 创建 ~/.claude.json（跳过官方登录）")
            else:
                click.echo("   ✓ 更新 ~/.claude.json（补充缺失字段）")

            return True
        except IOError as e:
            click.secho(f"   ⚠ 无法写入 ~/.claude.json: {e}", fg="yellow")
            return False

    return False


def build_claude_env_config(endpoint_type: str, api_key: str, custom_url: str = None, custom_model: str = None) -> dict:
    """
    构建 Claude Code settings.json 的 env 配置

    Args:
        endpoint_type: 端点类型 (deepseek, aliyun, kimi, minimax, custom)
        api_key: API Key
        custom_url: 自定义 URL（仅 custom 类型需要）
        custom_model: 自定义模型名称（仅 custom 类型需要）

    Returns:
        env 配置字典
    """
    if endpoint_type in PRESET_ENDPOINTS:
        env = PRESET_ENDPOINTS[endpoint_type].copy()
        # 移除 display_name（仅用于显示，不写入配置）
        env.pop("display_name", None)
    else:
        # custom 类型
        env = {
            "ANTHROPIC_BASE_URL": custom_url,
            "ANTHROPIC_MODEL": custom_model,
            "ANTHROPIC_SMALL_FAST_MODEL": custom_model,
            "API_TIMEOUT_MS": 600000,
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": 1,
        }

    env["ANTHROPIC_API_KEY"] = api_key
    return env


def get_config_path() -> Path:
    """
    获取配置文件路径

    Returns:
        配置文件路径 (~/.frago/config.json)
    """
    return Path.home() / ".frago" / "config.json"


def config_exists() -> bool:
    """
    检查配置文件是否存在

    Returns:
        True 如果配置文件存在
    """
    return get_config_path().exists()


def load_config(config_file: Optional[Path] = None) -> Config:
    """
    加载配置文件

    Args:
        config_file: 配置文件路径，默认使用 get_config_path()

    Returns:
        Config 对象，如果文件不存在或损坏则返回默认配置
    """
    if config_file is None:
        config_file = get_config_path()

    if not config_file.exists():
        return Config()

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 处理 datetime 字段
        for field in ["created_at", "updated_at"]:
            if field in data and isinstance(data[field], str):
                try:
                    data[field] = datetime.fromisoformat(data[field])
                except ValueError:
                    del data[field]

        # 处理嵌套的 api_endpoint
        if "api_endpoint" in data and data["api_endpoint"]:
            data["api_endpoint"] = APIEndpoint(**data["api_endpoint"])

        return Config(**data)

    except (json.JSONDecodeError, TypeError, ValueError) as e:
        # 配置文件损坏，备份后返回默认配置
        backup_file = config_file.with_suffix(".json.bak")
        if config_file.exists():
            config_file.rename(backup_file)
            click.echo(f"配置文件损坏，已备份到: {backup_file}")
        return Config()


def save_config(config: Config, config_file: Optional[Path] = None) -> None:
    """
    保存配置文件

    Args:
        config: Config 对象
        config_file: 配置文件路径，默认使用 get_config_path()
    """
    if config_file is None:
        config_file = get_config_path()

    # 确保目录存在
    config_file.parent.mkdir(parents=True, exist_ok=True)

    # 更新时间戳
    config.updated_at = datetime.now()

    # 序列化为字典
    data = config.model_dump()

    # 处理 datetime 序列化
    for key, value in data.items():
        if isinstance(value, datetime):
            data[key] = value.isoformat()

    # 处理 api_endpoint 嵌套对象
    if data.get("api_endpoint"):
        data["api_endpoint"] = dict(data["api_endpoint"])

    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def prompt_auth_method() -> str:
    """
    提示用户选择认证方式（使用 AskUserQuestion 交互菜单）

    Returns:
        "official" 或 "custom"
    """
    from frago.init.ui import ask_question

    answer = ask_question(
        question="How do you want to configure Claude Code authentication?",
        header="Authentication",
        options=[
            {
                "label": "Default",
                "description": "Keep current configuration (user manages login/API key)"
            },
            {
                "label": "Custom",
                "description": "Configure a third-party API endpoint (e.g., DeepSeek, Kimi)"
            }
        ],
        default_index=0
    )

    # 映射 Default -> official（内部仍使用 official 表示不干预）
    return "official" if answer == "Default" else "custom"


def configure_official_auth(existing_config: Optional[Config] = None) -> Config:
    """
    配置官方认证

    Args:
        existing_config: 现有配置（用于保留其他字段）

    Returns:
        更新后的 Config 对象
    """
    if existing_config:
        # 保留其他配置，只更新认证相关字段
        data = existing_config.model_dump()
        data["auth_method"] = "official"
        data["api_endpoint"] = None
        # 重新创建以触发验证
        return Config(**data)
    else:
        return Config(auth_method="official")


def configure_custom_endpoint(existing_config: Optional[Config] = None) -> Config:
    """
    配置自定义 API 端点

    将配置写入 Claude Code 的 ~/.claude/settings.json 的 env 字段

    Args:
        existing_config: 现有配置（用于保留其他字段）

    Returns:
        更新后的 Config 对象
    """
    click.echo("\n📡 自定义 API 端点配置")
    click.echo("   配置将写入 ~/.claude/settings.json\n")

    # 获取端点类型
    endpoint_type = prompt_endpoint_type()

    # 获取自定义 URL 和模型（仅 custom 类型需要）
    custom_url = None
    custom_model = None
    if endpoint_type == "custom":
        custom_url = prompt_custom_endpoint_url()
        custom_model = prompt_custom_model()

    # 获取 API Key
    api_key = prompt_api_key()

    # 构建 env 配置
    env_config = build_claude_env_config(endpoint_type, api_key, custom_url, custom_model)

    # 确保 ~/.claude.json 存在（跳过官方登录流程）
    ensure_claude_json_for_custom_auth()

    # 写入 Claude Code settings.json
    try:
        save_claude_settings({"env": env_config})
        click.echo(f"   ✓ 已写入 {CLAUDE_SETTINGS_PATH}")

        # 显示配置摘要（隐藏 API Key）
        click.echo("\n   配置内容:")
        click.echo(f"   ANTHROPIC_BASE_URL: {env_config.get('ANTHROPIC_BASE_URL')}")
        click.echo(f"   ANTHROPIC_MODEL: {env_config.get('ANTHROPIC_MODEL')}")
        click.echo(f"   ANTHROPIC_API_KEY: ****已配置****")

    except Exception as e:
        click.echo(f"\n❌ 写入配置失败: {e}")
        click.echo("   请检查 ~/.claude/ 目录权限")

    # 创建 APIEndpoint 对象用于 frago 配置
    if endpoint_type == "custom":
        api_endpoint = APIEndpoint(type="custom", api_key=api_key, url=custom_url)
    else:
        # 预设端点类型
        api_endpoint = APIEndpoint(type=endpoint_type, api_key=api_key, url=None)

    # 更新 frago 配置
    if existing_config:
        data = existing_config.model_dump()
        data["auth_method"] = "custom"
        data["api_endpoint"] = api_endpoint
        return Config(**data)
    else:
        return Config(auth_method="custom", api_endpoint=api_endpoint)


def display_config_summary(config: Config) -> str:
    """
    生成配置摘要字符串（简洁版，仅核心信息）

    Args:
        config: Config 对象

    Returns:
        格式化的配置摘要字符串
    """
    items = []

    # 依赖信息
    if config.node_version:
        items.append(("Node.js", config.node_version))
    if config.claude_code_version:
        items.append(("Claude Code", config.claude_code_version))

    # 认证信息
    if config.auth_method == "official":
        items.append(("Authentication", "User configured"))
    else:
        endpoint_type = config.api_endpoint.type if config.api_endpoint else "custom"
        items.append(("Authentication", f"Frago managed ({endpoint_type})"))

    # 工作目录
    workdir = config.working_directory or "current directory"
    items.append(("Working Directory", workdir))

    # 初始化状态
    status = "Completed" if config.init_completed else "Incomplete"
    items.append(("Status", status))

    # 格式化输出
    if not items:
        return ""

    max_key_len = max(len(k) for k, _ in items)
    lines = []
    for key, value in items:
        padded_key = key.ljust(max_key_len)
        lines.append(f"  {padded_key}  {value}")

    return "\n".join(lines)


def prompt_config_update() -> bool:
    """
    询问用户是否更新配置

    Returns:
        True 如果用户选择更新
    """
    click.echo()
    return click.confirm("Update configuration?", default=False)


def select_config_items_to_update() -> List[str]:
    """
    让用户选择要更新的配置项

    Returns:
        要更新的配置项列表
    """
    click.echo("\n可更新的配置项:")
    click.echo("  auth     - 认证方式")
    click.echo("  endpoint - API 端点配置")
    click.echo("  ccr      - Claude Code Router")
    click.echo("")

    choice = click.prompt(
        "选择要更新的项目（多个用逗号分隔）",
        type=str,
        default="auth",
    )

    return [item.strip().lower() for item in choice.split(",")]


def run_auth_configuration(existing_config: Optional[Config] = None) -> Config:
    """
    运行认证配置流程

    Args:
        existing_config: 现有配置

    Returns:
        配置后的 Config 对象
    """
    auth_method = prompt_auth_method()

    if auth_method == "official":
        return configure_official_auth(existing_config)
    else:
        return configure_custom_endpoint(existing_config)


def warn_auth_switch(current_method: str, new_method: str) -> bool:
    """
    认证方式切换警告

    Args:
        current_method: 当前认证方式
        new_method: 新认证方式

    Returns:
        True 如果用户确认切换
    """
    if current_method == new_method:
        return True

    if current_method == "custom" and new_method == "official":
        click.echo("\n⚠️  警告: 切换到官方认证将清除现有的 API 端点配置")
    elif current_method == "official" and new_method == "custom":
        click.echo("\n⚠️  警告: 切换到自定义端点需要提供 API Key")

    return click.confirm("确认切换?", default=True)


# =============================================================================
# Phase 8: User Story 6 - 配置持久化和摘要报告
# =============================================================================


def format_final_summary(config: Config) -> str:
    """
    生成最终配置摘要（用于初始化完成时显示）

    Args:
        config: Config 对象

    Returns:
        格式化的最终摘要字符串
    """
    lines = ["", "🎉 Frago 初始化完成!", ""]
    lines.append("=" * 40)
    lines.append("")

    # 依赖信息
    lines.append("📦 已安装组件:")
    if config.node_version:
        lines.append(f"   • Node.js: {config.node_version}")
    if config.claude_code_version:
        lines.append(f"   • Claude Code: {config.claude_code_version}")

    lines.append("")

    # 认证信息
    lines.append("🔐 认证配置:")
    if config.auth_method == "official":
        lines.append("   • 方式: 用户自行配置")
    else:
        lines.append("   • 方式: Frago 配置的 API 端点")
        if config.api_endpoint:
            lines.append(f"   • 端点: {config.api_endpoint.type}")
            if config.api_endpoint.url:
                lines.append(f"   • URL: {config.api_endpoint.url}")
            lines.append("   • API Key: ****已配置****")

    # CCR 状态
    if config.ccr_enabled:
        lines.append("")
        lines.append("🔄 Claude Code Router: 已启用")

    lines.append("")
    lines.append("=" * 40)

    return "\n".join(lines)


def prompt_working_directory() -> Optional[str]:
    """
    提示用户选择工作目录（使用交互菜单）

    Returns:
        工作目录绝对路径，选择 current 时返回 None（使用当前目录）
    """
    import os
    from frago.init.ui import ask_question

    cwd = os.getcwd()

    answer = ask_question(
        question=f"Where should Frago store project data?\nCurrent directory: {cwd}",
        header="Working Directory",
        options=[
            {
                "label": "Current",
                "description": "Use current directory (default)"
            },
            {
                "label": "Custom",
                "description": "Specify a custom absolute path"
            }
        ],
        default_index=0
    )

    if answer == "Current":
        return None  # None 表示使用当前运行目录

    # 用户输入自定义路径
    while True:
        click.echo()
        path = click.prompt("Enter absolute path", type=str)
        path = os.path.expanduser(path)  # 展开 ~

        if not os.path.isabs(path):
            click.secho("Error: Path must be absolute (start with / or ~)", fg="red")
            continue

        # 检查路径是否存在，不存在则询问是否创建
        if not os.path.exists(path):
            if click.confirm(f"Directory does not exist. Create {path}?", default=True):
                try:
                    os.makedirs(path, exist_ok=True)
                    click.secho(f"Created directory: {path}", fg="green")
                except Exception as e:
                    click.secho(f"Failed to create directory: {e}", fg="red")
                    continue
            else:
                continue

        return path


def suggest_next_steps(config: Config) -> list[str]:
    """
    根据配置生成下一步操作建议

    Args:
        config: Config 对象

    Returns:
        建议列表
    """
    steps = []

    if config.auth_method == "official":
        steps.append("如未登录，运行 `claude` 命令完成 Claude Code 登录")
        steps.append("使用 `frago recipe list` 查看可用的自动化配方")
    else:
        steps.append("使用 `frago recipe list` 查看可用的自动化配方")
        steps.append("运行 `frago recipe run <name>` 执行配方")

    steps.append("查看文档: https://github.com/tsaijamey/frago")

    return steps


def display_next_steps(config: Config) -> str:
    """
    显示下一步操作建议

    Args:
        config: Config 对象

    Returns:
        格式化的建议字符串
    """
    steps = suggest_next_steps(config)

    lines = ["", "📋 下一步:"]
    for i, step in enumerate(steps, 1):
        lines.append(f"   {i}. {step}")
    lines.append("")

    return "\n".join(lines)
