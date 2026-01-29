#!/usr/bin/env bash

# Claude Code Third-Party Endpoint Configuration Script
# Configures ~/.claude/settings.json env field for various API providers
# Compatible with bash 3.2+ (macOS default)

set -e

SETTINGS_FILE="$HOME/.claude/settings.json"
CLAUDE_JSON="$HOME/.claude.json"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m' # No Color

# Provider data (bash 3.2 compatible - no associative arrays)
# Format: provider|display_name|endpoint_url|default_model|sonnet_model|haiku_model|timeout_ms
PROVIDERS="
deepseek|DeepSeek (deepseek-chat)|https://api.deepseek.com/anthropic|deepseek-reasoner|deepseek-reasoner|deepseek-chat|600000
aliyun|Aliyun Bailian (qwen3-max)|https://dashscope.aliyuncs.com/apps/anthropic|qwen3-max|qwen3-max|qwen3-max|600000
kimi|Kimi K2 (kimi-k2-turbo-preview)|https://api.moonshot.cn/anthropic|kimi-k2-turbo-preview|kimi-k2-turbo-preview|kimi-k2-turbo-preview|600000
minimax|MiniMax M2|https://api.minimaxi.com/anthropic|MiniMax-M2|MiniMax-M2|MiniMax-M2|3000000
mimo|Xiaomi MiMo (mimo-v2-flash)|https://api.xiaomimimo.com/anthropic|mimo-v2-flash|mimo-v2-flash|mimo-v2-flash|600000
"

# Get provider field by index
# Usage: get_provider_field "deepseek" 2  # returns endpoint URL
get_provider_field() {
    local provider="$1"
    local field_idx="$2"
    echo "$PROVIDERS" | grep "^${provider}|" | cut -d'|' -f"$field_idx"
}

get_display_name() { get_provider_field "$1" 2; }
get_endpoint_url() { get_provider_field "$1" 3; }
get_default_model() { get_provider_field "$1" 4; }
get_sonnet_model() { get_provider_field "$1" 5; }
get_haiku_model() { get_provider_field "$1" 6; }
get_timeout_ms() { get_provider_field "$1" 7; }

# Display frago banner and promotion
show_banner() {
    echo -e "${MAGENTA}"
    cat << 'EOF'
    ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
    ┃                                                             ┃
    ┃     ██████╗██████╗  █████╗  ██████╗  ██████╗                ┃
    ┃     ██╔═══╝██╔══██╗██╔══██╗██╔════╝ ██╔═══██╗               ┃
    ┃     █████╗ ██████╔╝███████║██║  ███╗██║   ██║               ┃
    ┃     ██╔══╝ ██╔══██╗██╔══██║██║   ██║██║   ██║               ┃
    ┃     ██║    ██║  ██║██║  ██║╚██████╔╝╚██████╔╝               ┃
    ┃     ╚═╝    ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝                ┃
    ┃                                                             ┃
    ┃              AI-Powered Browser Automation                  ┃
    ┃                                                             ┃
    ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
EOF
    echo -e "${NC}"

    echo -e "${BOLD}${CYAN}Why use frago? / 为什么使用 frago?${NC}\n"

    echo -e "${GREEN}English:${NC}"
    echo -e "  ${BOLD}•${NC} One-command endpoint setup: ${DIM}frago init${NC}"
    echo -e "  ${BOLD}•${NC} Interactive GUI for configuration management"
    echo -e "  ${BOLD}•${NC} Secure API key storage in ~/.claude/settings.json"
    echo -e "  ${BOLD}•${NC} Browser automation with Chrome DevTools Protocol"
    echo -e "  ${BOLD}•${NC} Reusable recipes for repetitive tasks"
    echo

    echo -e "${GREEN}中文:${NC}"
    echo -e "  ${BOLD}•${NC} 一键配置端点: ${DIM}frago init${NC}"
    echo -e "  ${BOLD}•${NC} 交互式图形界面管理配置"
    echo -e "  ${BOLD}•${NC} 安全存储 API 密钥到 ~/.claude/settings.json"
    echo -e "  ${BOLD}•${NC} 基于 Chrome DevTools Protocol 的浏览器自动化"
    echo -e "  ${BOLD}•${NC} 可复用的 Recipe 脚本，告别重复劳动"
    echo

    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}  Install / 安装:${NC}  ${CYAN}uv tool install frago-cli${NC}"
    echo -e "${BOLD}  GitHub:${NC}          ${CYAN}https://github.com/anthropics/frago${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo
}

# Ensure jq is installed
check_dependencies() {
    if ! command -v jq &> /dev/null; then
        echo -e "${RED}Error: jq is required but not installed.${NC}"
        echo "Install with: brew install jq (macOS) or apt install jq (Linux)"
        exit 1
    fi
}

# Initialize settings file if not exists
init_settings() {
    mkdir -p "$(dirname "$SETTINGS_FILE")"
    if [[ ! -f "$SETTINGS_FILE" ]]; then
        echo '{}' > "$SETTINGS_FILE"
    fi
}

# Ensure ~/.claude.json exists (required for custom auth)
ensure_claude_json() {
    if [[ ! -f "$CLAUDE_JSON" ]]; then
        echo '{}' > "$CLAUDE_JSON"
    fi
}

# Read current settings
read_settings() {
    cat "$SETTINGS_FILE"
}

# Write settings with merge
write_settings() {
    local new_settings="$1"
    local current=$(read_settings)

    # Deep merge env field
    local merged=$(echo "$current" | jq --argjson new "$new_settings" '
        . as $current |
        $new | to_entries | reduce .[] as $item ($current;
            if $item.key == "env" then
                .env = (.env // {}) + $item.value
            else
                .[$item.key] = $item.value
            end
        )
    ')

    echo "$merged" > "$SETTINGS_FILE"
}

# Mask API key for display
mask_api_key() {
    local key="$1"
    if [[ -z "$key" ]]; then
        echo ""
    elif [[ ${#key} -le 8 ]]; then
        echo "********"
    else
        echo "${key:0:4}****${key: -4}"
    fi
}

# Infer endpoint type from URL
infer_endpoint_type() {
    local url="$1"
    case "$url" in
        *api.deepseek.com*) echo "deepseek" ;;
        *dashscope.aliyuncs.com*) echo "aliyun" ;;
        *api.moonshot.cn*) echo "kimi" ;;
        *api.minimaxi.com*) echo "minimax" ;;
        *api.xiaomimimo.com*) echo "mimo" ;;
        *) echo "custom" ;;
    esac
}

# Display current configuration
show_current_config() {
    echo -e "\n${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}                   Current Configuration                    ${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"

    if [[ -f "$SETTINGS_FILE" ]]; then
        local settings=$(read_settings)
        local env=$(echo "$settings" | jq -r '.env // {}')

        local api_key=$(echo "$env" | jq -r '.ANTHROPIC_API_KEY // empty')
        local base_url=$(echo "$env" | jq -r '.ANTHROPIC_BASE_URL // empty')
        local default_model=$(echo "$env" | jq -r '.ANTHROPIC_MODEL // empty')
        local sonnet_model=$(echo "$env" | jq -r '.ANTHROPIC_DEFAULT_SONNET_MODEL // empty')
        local haiku_model=$(echo "$env" | jq -r '.ANTHROPIC_DEFAULT_HAIKU_MODEL // empty')
        local timeout=$(echo "$env" | jq -r '.API_TIMEOUT_MS // empty')

        if [[ -n "$api_key" ]]; then
            local endpoint_type=$(infer_endpoint_type "$base_url")
            echo -e "${GREEN}Endpoint Type:${NC} $endpoint_type"
            echo -e "${GREEN}Base URL:${NC} $base_url"
            echo -e "${GREEN}API Key:${NC} $(mask_api_key "$api_key")"
            echo -e "\n${GREEN}Model Mappings:${NC}"
            echo -e "  ANTHROPIC_MODEL (default):       ${default_model:-${YELLOW}not set${NC}}"
            echo -e "  ANTHROPIC_DEFAULT_SONNET_MODEL:  ${sonnet_model:-${YELLOW}not set${NC}}"
            echo -e "  ANTHROPIC_DEFAULT_HAIKU_MODEL:   ${haiku_model:-${YELLOW}not set${NC}}"
            [[ -n "$timeout" ]] && echo -e "\n${GREEN}Timeout:${NC} ${timeout}ms"
        else
            echo -e "${YELLOW}No API configuration found in env field.${NC}"
        fi
    else
        echo -e "${YELLOW}No configuration file found.${NC}"
    fi
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}\n"
}

# Provider selection menu
select_provider() {
    echo -e "\n${BLUE}Select API Provider:${NC}"
    echo "  1) DeepSeek (deepseek-chat / deepseek-reasoner)"
    echo "  2) Aliyun Bailian (qwen3-max)"
    echo "  3) Kimi K2 (kimi-k2-turbo-preview)"
    echo "  4) MiniMax M2"
    echo "  5) Xiaomi MiMo (mimo-v2-flash)"
    echo "  6) Custom Endpoint"
    echo "  0) Back to main menu"
    echo
    read -p "Choice [0-6]: " choice

    case $choice in
        1) echo "deepseek" ;;
        2) echo "aliyun" ;;
        3) echo "kimi" ;;
        4) echo "minimax" ;;
        5) echo "mimo" ;;
        6) echo "custom" ;;
        0) echo "" ;;
        *) echo "" ;;
    esac
}

# Build env config for preset endpoint
build_preset_env() {
    local provider="$1"
    local api_key="$2"
    local default_model="${3:-$(get_default_model "$provider")}"
    local sonnet_model="${4:-$(get_sonnet_model "$provider")}"
    local haiku_model="${5:-$(get_haiku_model "$provider")}"
    local endpoint_url=$(get_endpoint_url "$provider")
    local timeout=$(get_timeout_ms "$provider")

    jq -n \
        --arg key "$api_key" \
        --arg url "$endpoint_url" \
        --arg model "$default_model" \
        --arg sonnet "$sonnet_model" \
        --arg haiku "$haiku_model" \
        --arg timeout "$timeout" \
        '{
            env: {
                ANTHROPIC_API_KEY: $key,
                ANTHROPIC_BASE_URL: $url,
                ANTHROPIC_MODEL: $model,
                ANTHROPIC_DEFAULT_SONNET_MODEL: $sonnet,
                ANTHROPIC_DEFAULT_HAIKU_MODEL: $haiku,
                API_TIMEOUT_MS: ($timeout | tonumber),
                CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: 1
            }
        }'
}

# Build env config for custom endpoint
build_custom_env() {
    local api_key="$1"
    local base_url="$2"
    local default_model="${3:-gpt-4}"
    local sonnet_model="${4:-gpt-4}"
    local haiku_model="${5:-gpt-4}"

    jq -n \
        --arg key "$api_key" \
        --arg url "$base_url" \
        --arg model "$default_model" \
        --arg sonnet "$sonnet_model" \
        --arg haiku "$haiku_model" \
        '{
            env: {
                ANTHROPIC_API_KEY: $key,
                ANTHROPIC_BASE_URL: $url,
                ANTHROPIC_MODEL: $model,
                ANTHROPIC_DEFAULT_SONNET_MODEL: $sonnet,
                ANTHROPIC_DEFAULT_HAIKU_MODEL: $haiku,
                API_TIMEOUT_MS: 600000,
                CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: 1
            }
        }'
}

# Configure provider endpoint
configure_provider() {
    local provider=$(select_provider)
    [[ -z "$provider" ]] && return

    if [[ "$provider" == "custom" ]]; then
        configure_custom_endpoint
        return
    fi

    local display_name=$(get_display_name "$provider")
    local endpoint_url=$(get_endpoint_url "$provider")
    local def_model=$(get_default_model "$provider")
    local son_model=$(get_sonnet_model "$provider")
    local hai_model=$(get_haiku_model "$provider")

    echo -e "\n${GREEN}Provider:${NC} $display_name"
    echo -e "${GREEN}Endpoint:${NC} $endpoint_url"
    echo -e "${GREEN}Default models:${NC}"
    echo -e "  default: $def_model"
    echo -e "  sonnet:  $son_model"
    echo -e "  haiku:   $hai_model"

    # Get API key
    echo
    read -sp "Enter API Key: " api_key
    echo

    if [[ -z "$api_key" ]]; then
        echo -e "${RED}API key is required.${NC}"
        return
    fi

    # Ask about model customization
    echo
    read -p "Use default model mappings? (Y/n): " use_defaults

    local default_model=""
    local sonnet_model=""
    local haiku_model=""

    if [[ "$use_defaults" =~ ^[Nn]$ ]]; then
        echo -e "\n${BLUE}Custom Model Configuration${NC}"
        read -p "Default model [$def_model]: " default_model
        read -p "Sonnet model [$son_model]: " sonnet_model
        read -p "Haiku model [$hai_model]: " haiku_model
    fi

    local env_config=$(build_preset_env "$provider" "$api_key" "$default_model" "$sonnet_model" "$haiku_model")

    write_settings "$env_config"
    ensure_claude_json

    echo -e "\n${GREEN}✓ Configuration saved to ~/.claude/settings.json${NC}"
}

# Configure custom endpoint
configure_custom_endpoint() {
    echo -e "\n${BLUE}Custom Endpoint Configuration${NC}"

    read -p "Base URL (e.g., https://api.example.com/v1): " base_url
    if [[ -z "$base_url" ]]; then
        echo -e "${RED}Base URL is required.${NC}"
        return
    fi

    read -sp "API Key: " api_key
    echo
    if [[ -z "$api_key" ]]; then
        echo -e "${RED}API key is required.${NC}"
        return
    fi

    echo -e "\n${BLUE}Model Configuration${NC}"
    read -p "Default model (ANTHROPIC_MODEL) [gpt-4]: " default_model
    read -p "Sonnet model (ANTHROPIC_DEFAULT_SONNET_MODEL) [gpt-4]: " sonnet_model
    read -p "Haiku model (ANTHROPIC_DEFAULT_HAIKU_MODEL) [gpt-4]: " haiku_model

    local env_config=$(build_custom_env "$api_key" "$base_url" "$default_model" "$sonnet_model" "$haiku_model")

    write_settings "$env_config"
    ensure_claude_json

    echo -e "\n${GREEN}✓ Configuration saved to ~/.claude/settings.json${NC}"
}

# Configure API key only (preserve other settings)
configure_api_key() {
    echo -e "\n${BLUE}Update API Key${NC}"

    read -sp "Enter new API Key: " api_key
    echo

    if [[ -n "$api_key" ]]; then
        local settings=$(read_settings)
        settings=$(echo "$settings" | jq --arg key "$api_key" '.env.ANTHROPIC_API_KEY = $key')
        echo "$settings" > "$SETTINGS_FILE"
        echo -e "${GREEN}✓ API key updated!${NC}"
    fi
}

# Configure model mappings only
configure_models() {
    echo -e "\n${BLUE}Update Model Mappings${NC}"
    echo "(Leave empty to keep current value)"

    local settings=$(read_settings)
    local env=$(echo "$settings" | jq -r '.env // {}')

    local current_default=$(echo "$env" | jq -r '.ANTHROPIC_MODEL // empty')
    local current_sonnet=$(echo "$env" | jq -r '.ANTHROPIC_DEFAULT_SONNET_MODEL // empty')
    local current_haiku=$(echo "$env" | jq -r '.ANTHROPIC_DEFAULT_HAIKU_MODEL // empty')

    read -p "Default model (ANTHROPIC_MODEL) [$current_default]: " default_model
    read -p "Sonnet model (ANTHROPIC_DEFAULT_SONNET_MODEL) [$current_sonnet]: " sonnet_model
    read -p "Haiku model (ANTHROPIC_DEFAULT_HAIKU_MODEL) [$current_haiku]: " haiku_model

    if [[ -n "$default_model" ]]; then
        settings=$(echo "$settings" | jq --arg model "$default_model" '.env.ANTHROPIC_MODEL = $model')
    fi
    if [[ -n "$sonnet_model" ]]; then
        settings=$(echo "$settings" | jq --arg model "$sonnet_model" '.env.ANTHROPIC_DEFAULT_SONNET_MODEL = $model')
    fi
    if [[ -n "$haiku_model" ]]; then
        settings=$(echo "$settings" | jq --arg model "$haiku_model" '.env.ANTHROPIC_DEFAULT_HAIKU_MODEL = $model')
    fi

    echo "$settings" > "$SETTINGS_FILE"
    echo -e "\n${GREEN}✓ Model mappings updated!${NC}"
}

# Quick setup presets
quick_setup() {
    echo -e "\n${BLUE}Quick Setup Presets${NC}"
    echo "  1) DeepSeek (deepseek-reasoner + deepseek-chat)"
    echo "  2) Aliyun Bailian (qwen3-max)"
    echo "  3) Kimi K2 (kimi-k2-turbo-preview)"
    echo "  4) MiniMax M2"
    echo "  5) Xiaomi MiMo (mimo-v2-flash)"
    echo "  0) Back"
    echo
    read -p "Choice [0-5]: " choice

    local provider=""
    case $choice in
        1) provider="deepseek" ;;
        2) provider="aliyun" ;;
        3) provider="kimi" ;;
        4) provider="minimax" ;;
        5) provider="mimo" ;;
        0) return ;;
        *) return ;;
    esac

    local display_name=$(get_display_name "$provider")
    echo -e "\n${GREEN}Selected:${NC} $display_name"
    read -sp "Enter API Key: " api_key
    echo

    if [[ -z "$api_key" ]]; then
        echo -e "${RED}API key is required.${NC}"
        return
    fi

    local env_config=$(build_preset_env "$provider" "$api_key")
    write_settings "$env_config"
    ensure_claude_json

    echo -e "\n${GREEN}✓ Quick setup complete!${NC}"
    echo -e "Endpoint: $(get_endpoint_url "$provider")"
    echo -e "Models: default=$(get_default_model "$provider"), sonnet=$(get_sonnet_model "$provider"), haiku=$(get_haiku_model "$provider")"
}

# Clear API configuration
clear_api_config() {
    echo -e "\n${YELLOW}Warning: This will remove all API endpoint configuration.${NC}"
    read -p "Are you sure? (y/N): " confirm

    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        local settings=$(read_settings)
        settings=$(echo "$settings" | jq 'del(.env.ANTHROPIC_API_KEY, .env.ANTHROPIC_BASE_URL, .env.ANTHROPIC_MODEL, .env.ANTHROPIC_DEFAULT_SONNET_MODEL, .env.ANTHROPIC_DEFAULT_HAIKU_MODEL, .env.API_TIMEOUT_MS, .env.CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC)')

        # Clean up empty env object
        settings=$(echo "$settings" | jq 'if .env == {} then del(.env) else . end')

        echo "$settings" > "$SETTINGS_FILE"
        echo -e "${GREEN}✓ API configuration cleared!${NC}"
    fi
}

# Main menu
main_menu() {
    while true; do
        echo -e "\n${CYAN}╔═══════════════════════════════════════════════════════════╗${NC}"
        echo -e "${CYAN}║     Claude Code Third-Party Endpoint Configuration        ║${NC}"
        echo -e "${CYAN}╚═══════════════════════════════════════════════════════════╝${NC}"
        echo
        echo "  1) Show current configuration"
        echo "  2) Quick setup (presets)"
        echo "  3) Configure provider & models"
        echo "  4) Update API key only"
        echo "  5) Update model mappings only"
        echo "  6) Clear API configuration"
        echo "  0) Exit"
        echo
        read -p "Choice [0-6]: " choice

        case $choice in
            1) show_current_config ;;
            2) quick_setup ;;
            3) configure_provider ;;
            4) configure_api_key ;;
            5) configure_models ;;
            6) clear_api_config ;;
            0) echo -e "\n${GREEN}Goodbye!${NC}"; exit 0 ;;
            *) echo -e "${RED}Invalid choice${NC}" ;;
        esac
    done
}

# Entry point
check_dependencies
init_settings
show_banner
main_menu
