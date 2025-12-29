"""
Configuration Management Module

Provides configuration loading, saving, and interactive configuration:
- Authentication method selection (official vs custom endpoint)
- Configuration persistence to ~/.frago/config.json
- Configuration summary display
- Configuration update workflow
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import click

from frago.init.models import Config, APIEndpoint


# Preset endpoint configuration (for Claude Code settings.json env field)
# All vendors provide Anthropic API compatible interfaces
# Model fields: ANTHROPIC_MODEL (default), ANTHROPIC_DEFAULT_SONNET_MODEL, ANTHROPIC_DEFAULT_HAIKU_MODEL
PRESET_ENDPOINTS = {
    "deepseek": {
        "display_name": "DeepSeek (deepseek-chat)",
        "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
        "ANTHROPIC_MODEL": "deepseek-reason",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-reason",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-chat",
        "API_TIMEOUT_MS": 600000,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": 1,
    },
    "aliyun": {
        "display_name": "Aliyun Bailian (qwen3-max)",
        "ANTHROPIC_BASE_URL": "https://dashscope.aliyuncs.com/apps/anthropic",
        "ANTHROPIC_MODEL": "qwen3-max",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "qwen3-max",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "qwen3-max",
        "API_TIMEOUT_MS": 600000,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": 1,
    },
    "kimi": {
        "display_name": "Kimi K2 (kimi-k2-turbo-preview)",
        "ANTHROPIC_BASE_URL": "https://api.moonshot.cn/anthropic",
        "ANTHROPIC_MODEL": "kimi-k2-turbo-preview",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "kimi-k2-turbo-preview",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "kimi-k2-turbo-preview",
        "API_TIMEOUT_MS": 600000,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": 1,
    },
    "minimax": {
        "display_name": "MiniMax M2",
        "ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic",
        "ANTHROPIC_MODEL": "MiniMax-M2",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "MiniMax-M2",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "MiniMax-M2",
        "API_TIMEOUT_MS": 3000000,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": 1,
    },
}

# Claude Code configuration file paths
CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
CLAUDE_JSON_PATH = Path.home() / ".claude.json"

# ~/.claude.json minimal configuration (to skip official login flow)
# Reference: https://github.com/anthropics/claude-code/issues/441
CLAUDE_JSON_MINIMAL = {
    "hasCompletedOnboarding": True,
    "lastOnboardingVersion": "1.0.0",
    "isQualifiedForDataSharing": False,
}


# =============================================================================
# Phase 6: User Story 4 - Custom API Endpoint Configuration Functions
# =============================================================================


def validate_endpoint_url(url: str) -> bool:
    """
    Validate API endpoint URL format

    Args:
        url: URL to validate

    Returns:
        True if URL is valid
    """
    if not url or not isinstance(url, str):
        return False

    url = url.strip()
    if not url:
        return False

    # Must start with http:// or https://
    if not (url.startswith("http://") or url.startswith("https://")):
        return False

    # Simple format check: protocol must be followed by content
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return bool(parsed.scheme and parsed.netloc)
    except Exception:
        return False


def prompt_endpoint_type() -> str:
    """
    Prompt user to select endpoint type (using interactive menu)

    Returns:
        Endpoint type: deepseek, aliyun, kimi, minimax, custom
    """
    from frago.init.ui import ask_question

    # Build options list
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
    Prompt user to enter API Key (hidden input)

    Args:
        endpoint_name: Optional endpoint name for the prompt

    Returns:
        User's API Key input
    """
    prompt_text = "API Key"
    if endpoint_name:
        prompt_text = f"{endpoint_name} API Key"

    return click.prompt(prompt_text, hide_input=True, type=str)


def prompt_custom_endpoint_url() -> str:
    """
    Prompt user to enter custom endpoint URL (with validation)

    Returns:
        Validated URL
    """
    while True:
        url = click.prompt("API Endpoint URL", type=str)

        if validate_endpoint_url(url):
            return url

        click.echo("[X] Invalid URL format, please enter a complete HTTP/HTTPS URL")


def prompt_custom_models() -> tuple[str, str]:
    """
    Prompt user to enter custom model names (sonnet and haiku)

    Returns:
        Tuple of (sonnet_model, haiku_model)
    """
    sonnet_model = click.prompt("Main model (ANTHROPIC_MODEL)", type=str, default="gpt-4")
    haiku_model = click.prompt("Fast model (ANTHROPIC_DEFAULT_HAIKU_MODEL)", type=str, default=sonnet_model)
    return sonnet_model, haiku_model


def load_claude_settings() -> dict:
    """
    Load Claude Code settings.json

    Returns:
        Configuration dictionary, or empty dict if file doesn't exist
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
    Save Claude Code settings.json (merge write, don't overwrite existing fields)

    Args:
        settings: Configuration dictionary to merge
    """
    # Ensure directory exists
    CLAUDE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Load existing configuration
    existing = load_claude_settings()

    # Merge env field (deep merge)
    if "env" in settings:
        if "env" not in existing:
            existing["env"] = {}
        existing["env"].update(settings["env"])
        del settings["env"]

    # Merge other top-level fields
    existing.update(settings)

    # Write file
    with open(CLAUDE_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)


def delete_claude_settings() -> bool:
    """
    Delete Claude Code settings.json file

    Called when user switches from custom to official mode.
    Deletes the entire config file to let Claude Code use official defaults.

    Returns:
        True if deletion succeeded or file doesn't exist, False if error
    """
    if not CLAUDE_SETTINGS_PATH.exists():
        return True

    try:
        CLAUDE_SETTINGS_PATH.unlink()
        return True
    except Exception:
        return False


def check_claude_json_exists() -> bool:
    """
    Check if ~/.claude.json exists

    Returns:
        True if file exists
    """
    return CLAUDE_JSON_PATH.exists()


def load_claude_json() -> dict:
    """
    Load ~/.claude.json

    Returns:
        Configuration dictionary, or empty dict if file doesn't exist
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
    Ensure ~/.claude.json exists with minimal fields required to skip official login

    Called when user selects custom API endpoint.
    If file doesn't exist, creates minimal configuration.
    If file exists but missing key fields, adds missing fields.

    Returns:
        True if file was created or modified, False if file already existed and complete
    """
    import click

    file_existed = check_claude_json_exists()
    existing = load_claude_json()
    modified = False

    # Check and add missing key fields
    for key, value in CLAUDE_JSON_MINIMAL.items():
        if key not in existing:
            existing[key] = value
            modified = True

    if modified:
        # Write file
        try:
            with open(CLAUDE_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)

            # Use ASCII compatible symbols to avoid Windows GBK encoding issues
            if not file_existed:
                click.echo("   [OK] Created ~/.claude.json (skip official login)")
            else:
                click.echo("   [OK] Updated ~/.claude.json (added missing fields)")

            return True
        except IOError as e:
            click.secho(f"   [WARN] Cannot write ~/.claude.json: {e}", fg="yellow")
            return False

    return False


def build_claude_env_config(
    endpoint_type: str,
    api_key: str,
    custom_url: str = None,
    default_model: str = None,
    sonnet_model: str = None,
    haiku_model: str = None,
) -> dict:
    """
    Build env configuration for Claude Code settings.json

    Args:
        endpoint_type: Endpoint type (deepseek, aliyun, kimi, minimax, custom)
        api_key: API Key
        custom_url: Custom URL (only needed for custom type)
        default_model: Override for ANTHROPIC_MODEL
        sonnet_model: Override for ANTHROPIC_DEFAULT_SONNET_MODEL
        haiku_model: Override for ANTHROPIC_DEFAULT_HAIKU_MODEL

    Returns:
        env configuration dictionary
    """
    if endpoint_type in PRESET_ENDPOINTS:
        env = PRESET_ENDPOINTS[endpoint_type].copy()
        # Remove display_name (only for display, not written to config)
        env.pop("display_name", None)
    else:
        # custom type - requires model configuration
        model = default_model or "gpt-4"
        env = {
            "ANTHROPIC_BASE_URL": custom_url,
            "ANTHROPIC_MODEL": model,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": sonnet_model or model,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": haiku_model or model,
            "API_TIMEOUT_MS": 600000,
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": 1,
        }

    # Override model names if explicitly provided (for preset endpoints too)
    if default_model:
        env["ANTHROPIC_MODEL"] = default_model
    if sonnet_model:
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = sonnet_model
    if haiku_model:
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = haiku_model

    env["ANTHROPIC_API_KEY"] = api_key
    return env


def get_config_path() -> Path:
    """
    Get configuration file path

    Returns:
        Configuration file path (~/.frago/config.json)
    """
    return Path.home() / ".frago" / "config.json"


def config_exists() -> bool:
    """
    Check if configuration file exists

    Returns:
        True if configuration file exists
    """
    return get_config_path().exists()


# DEPRECATED: load_config and save_config have been moved to config_manager.py
# Import from frago.init.config_manager instead
# These re-exports are kept for backward compatibility but will be removed in a future version
from frago.init.config_manager import load_config, save_config  # noqa: F401


def prompt_auth_method() -> str:
    """
    Prompt user to select authentication method (using AskUserQuestion interactive menu)

    Returns:
        "official" or "custom"
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

    # Map Default -> official (internally still use official to represent no intervention)
    return "official" if answer == "Default" else "custom"


def configure_official_auth(existing_config: Optional[Config] = None) -> Config:
    """
    Configure official authentication

    Args:
        existing_config: Existing configuration (to preserve other fields)

    Returns:
        Updated Config object
    """
    if existing_config:
        # Preserve other configuration, only update authentication-related fields
        data = existing_config.model_dump()
        data["auth_method"] = "official"
        data["api_endpoint"] = None
        # Recreate to trigger validation
        return Config(**data)
    else:
        return Config(auth_method="official")


def configure_custom_endpoint(existing_config: Optional[Config] = None) -> Config:
    """
    Configure custom API endpoint

    Writes configuration to Claude Code's ~/.claude/settings.json env field

    Args:
        existing_config: Existing configuration (to preserve other fields)

    Returns:
        Updated Config object
    """
    click.echo("\n📡 Custom API Endpoint Configuration")
    click.echo("   Configuration will be written to ~/.claude/settings.json\n")

    # Get endpoint type
    endpoint_type = prompt_endpoint_type()

    # Get custom URL and model (only needed for custom type)
    custom_url = None
    sonnet_model = None
    haiku_model = None
    if endpoint_type == "custom":
        custom_url = prompt_custom_endpoint_url()
        sonnet_model, haiku_model = prompt_custom_models()

    # Get API Key
    api_key = prompt_api_key()

    # Build env configuration
    env_config = build_claude_env_config(
        endpoint_type=endpoint_type,
        api_key=api_key,
        custom_url=custom_url,
        sonnet_model=sonnet_model,
        haiku_model=haiku_model,
    )

    # Ensure ~/.claude.json exists (skip official login flow)
    ensure_claude_json_for_custom_auth()

    # Write Claude Code settings.json
    try:
        save_claude_settings({"env": env_config})
        click.echo(f"   [OK] Saved to {CLAUDE_SETTINGS_PATH}")

        # Display configuration summary (hide API Key)
        click.echo("\n   Config:")
        click.echo(f"   ANTHROPIC_BASE_URL: {env_config.get('ANTHROPIC_BASE_URL')}")
        click.echo(f"   ANTHROPIC_DEFAULT_SONNET_MODEL: {env_config.get('ANTHROPIC_DEFAULT_SONNET_MODEL')}")
        click.echo(f"   ANTHROPIC_DEFAULT_HAIKU_MODEL: {env_config.get('ANTHROPIC_DEFAULT_HAIKU_MODEL')}")
        click.echo(f"   ANTHROPIC_API_KEY: ****configured****")

    except Exception as e:
        click.echo(f"\n[ERROR] Failed to write config: {e}")
        click.echo("   Please check ~/.claude/ directory permissions")

    # Create APIEndpoint object for frago configuration
    if endpoint_type == "custom":
        api_endpoint = APIEndpoint(
            type="custom",
            api_key=api_key,
            url=custom_url,
            sonnet_model=sonnet_model,
            haiku_model=haiku_model,
        )
    else:
        # Preset endpoint type
        api_endpoint = APIEndpoint(type=endpoint_type, api_key=api_key, url=None)

    # Update frago configuration
    if existing_config:
        data = existing_config.model_dump()
        data["auth_method"] = "custom"
        data["api_endpoint"] = api_endpoint
        return Config(**data)
    else:
        return Config(auth_method="custom", api_endpoint=api_endpoint)


def display_config_summary(config: Config) -> str:
    """
    Generate configuration summary string (concise version, core information only)

    Args:
        config: Config object

    Returns:
        Formatted configuration summary string
    """
    items = []

    # Dependency information
    if config.node_version:
        items.append(("Node.js", config.node_version))
    if config.claude_code_version:
        items.append(("Claude Code", config.claude_code_version))

    # Authentication information
    if config.auth_method == "official":
        items.append(("Authentication", "User configured"))
    else:
        endpoint_type = config.api_endpoint.type if config.api_endpoint else "custom"
        items.append(("Authentication", f"Frago managed ({endpoint_type})"))

    # Initialization status
    status = "Completed" if config.init_completed else "Incomplete"
    items.append(("Status", status))

    # Format output
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
    Ask user whether to update configuration

    Returns:
        True if user chooses to update
    """
    click.echo()
    return click.confirm("Update configuration?", default=False)


def select_config_items_to_update() -> List[str]:
    """
    Let user select configuration items to update

    Returns:
        List of configuration items to update
    """
    click.echo("\nAvailable configuration items:")
    click.echo("  auth     - Authentication method")
    click.echo("  endpoint - API endpoint configuration")
    click.echo("  ccr      - Claude Code Router")
    click.echo("")

    choice = click.prompt(
        "Select items to update (comma-separated)",
        type=str,
        default="auth",
    )

    return [item.strip().lower() for item in choice.split(",")]


def run_auth_configuration(existing_config: Optional[Config] = None) -> Config:
    """
    Run authentication configuration workflow

    Args:
        existing_config: Existing configuration

    Returns:
        Configured Config object
    """
    auth_method = prompt_auth_method()

    if auth_method == "official":
        return configure_official_auth(existing_config)
    else:
        return configure_custom_endpoint(existing_config)


def warn_auth_switch(current_method: str, new_method: str) -> bool:
    """
    Authentication method switch warning

    Args:
        current_method: Current authentication method
        new_method: New authentication method

    Returns:
        True if user confirms the switch
    """
    if current_method == new_method:
        return True

    if current_method == "custom" and new_method == "official":
        click.echo("\n[!]  Warning: Switching to official authentication will clear existing API endpoint configuration")
    elif current_method == "official" and new_method == "custom":
        click.echo("\n[!]  Warning: Switching to custom endpoint requires providing an API Key")

    return click.confirm("Confirm switch?", default=True)


# =============================================================================
# Phase 8: User Story 6 - Configuration Persistence and Summary Report
# =============================================================================


def format_final_summary(config: Config) -> str:
    """
    Generate final configuration summary (displayed when initialization completes)

    Args:
        config: Config object

    Returns:
        Formatted final summary string
    """
    lines = ["", "🎉 Frago initialization completed!", ""]
    lines.append("=" * 40)
    lines.append("")

    # Dependency information
    lines.append("📦 Installed components:")
    if config.node_version:
        lines.append(f"   - Node.js: {config.node_version}")
    if config.claude_code_version:
        lines.append(f"   - Claude Code: {config.claude_code_version}")

    lines.append("")

    # Authentication information
    lines.append("🔐 Authentication configuration:")
    if config.auth_method == "official":
        lines.append("   - Method: User configured")
    else:
        lines.append("   - Method: Frago configured API endpoint")
        if config.api_endpoint:
            lines.append(f"   - Endpoint: {config.api_endpoint.type}")
            if config.api_endpoint.url:
                lines.append(f"   - URL: {config.api_endpoint.url}")
            lines.append("   - API Key: ****configured****")

    # CCR status
    if config.ccr_enabled:
        lines.append("")
        lines.append("🔄 Claude Code Router: Enabled")

    lines.append("")
    lines.append("=" * 40)

    return "\n".join(lines)


def suggest_next_steps(config: Config) -> list[str]:
    """
    Generate next step suggestions based on configuration

    Args:
        config: Config object

    Returns:
        List of suggestions
    """
    steps = []

    if config.auth_method == "official":
        steps.append("If not logged in, run `claude` command to complete Claude Code login")
        steps.append("Use `frago recipe list` to view available automation recipes")
    else:
        steps.append("Use `frago recipe list` to view available automation recipes")
        steps.append("Run `frago recipe run <name>` to execute a recipe")

    steps.append("View documentation: https://github.com/tsaijamey/frago")

    return steps


def display_next_steps(config: Config) -> str:
    """
    Display next step suggestions

    Args:
        config: Config object

    Returns:
        Formatted suggestion string
    """
    steps = suggest_next_steps(config)

    lines = ["", "📋 Next steps:"]
    for i, step in enumerate(steps, 1):
        lines.append(f"   {i}. {step}")
    lines.append("")

    return "\n".join(lines)
