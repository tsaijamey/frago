#!/bin/bash
# Recipe: youtube_extract_subtitles_ytdlp
# Description: 使用 yt-dlp 仅下载 YouTube 视频字幕

set -e

# 自动安装依赖函数
install_dependency() {
    local cmd=$1
    local pkg_name=$2

    if command -v "$cmd" &> /dev/null; then
        return 0
    fi

    echo "Installing $pkg_name..." >&2

    if [[ "$OSTYPE" == "darwin"* ]]; then
        if command -v brew &> /dev/null; then
            brew install "$pkg_name" >&2
        else
            echo '{"success": false, "error": "Homebrew not installed"}' >&2
            exit 1
        fi
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux - use uv tool install (no sudo)
        if command -v uv &> /dev/null; then
            uv tool install "$pkg_name" >&2
        else
            echo "{\"success\": false, \"error\": \"$pkg_name not found. Please install manually: apt install $pkg_name (or dnf/pacman equivalent)\"}" >&2
            exit 1
        fi
    else
        echo "{\"success\": false, \"error\": \"Unsupported OS: $OSTYPE\"}" >&2
        exit 1
    fi

    if ! command -v "$cmd" &> /dev/null; then
        echo "{\"success\": false, \"error\": \"Failed to install $pkg_name\"}" >&2
        exit 1
    fi
}

# 解析输入参数
INPUT=$(cat)

URL=$(echo "$INPUT" | jq -r '.url // empty')
OUTPUT_DIR=$(echo "$INPUT" | jq -r '.output_dir // "."')
LANGS=$(echo "$INPUT" | jq -r '.langs // "all"')
AUTO_SUBS=$(echo "$INPUT" | jq -r '.auto_subs // true')
MANUAL_SUBS=$(echo "$INPUT" | jq -r '.manual_subs // true')
OUTPUT_FORMAT=$(echo "$INPUT" | jq -r '.output_format // "srt"')

# 验证必需参数
if [ -z "$URL" ]; then
    echo '{"success": false, "error": "url is required"}' >&2
    exit 1
fi

# 自动安装依赖
install_dependency "yt-dlp" "yt-dlp"

# 创建输出目录
mkdir -p "$OUTPUT_DIR"

# 构建 yt-dlp 命令参数
YT_DLP_ARGS=()

# 添加字幕选项
if [ "$MANUAL_SUBS" = "true" ]; then
    YT_DLP_ARGS+=("--write-subs")
fi

if [ "$AUTO_SUBS" = "true" ]; then
    YT_DLP_ARGS+=("--write-auto-subs")
fi

# 语言选择
if [ "$LANGS" = "all" ]; then
    YT_DLP_ARGS+=("--sub-langs" "all")
else
    YT_DLP_ARGS+=("--sub-langs" "$LANGS")
fi

# 输出格式转换
case "$OUTPUT_FORMAT" in
    "srt")
        YT_DLP_ARGS+=("--convert-subs" "srt")
        ;;
    "vtt")
        YT_DLP_ARGS+=("--convert-subs" "vtt")
        ;;
    "json3")
        # json3 不需要转换，直接指定格式
        YT_DLP_ARGS+=("--sub-format" "json3")
        ;;
    *)
        YT_DLP_ARGS+=("--convert-subs" "srt")
        ;;
esac

# 跳过视频下载
YT_DLP_ARGS+=("--skip-download")

# 输出路径
YT_DLP_ARGS+=("-o" "$OUTPUT_DIR/%(title)s.%(ext)s")
YT_DLP_ARGS+=("$URL")

# 先获取可用字幕语言列表
AVAILABLE_LANGS=$(yt-dlp --list-subs "$URL" 2>&1 | grep -E "^[a-z]{2,}" | awk '{print $1}' | sort -u | head -20 || true)
AVAILABLE_LANGS_JSON="[]"
if [ -n "$AVAILABLE_LANGS" ]; then
    AVAILABLE_LANGS_JSON=$(echo "$AVAILABLE_LANGS" | jq -R -s 'split("\n") | map(select(length > 0))')
fi

# 执行下载
TEMP_OUTPUT=$(mktemp)
if yt-dlp "${YT_DLP_ARGS[@]}" 2>&1 | tee "$TEMP_OUTPUT"; then

    # 查找字幕文件
    SUBS=""
    case "$OUTPUT_FORMAT" in
        "srt")
            SUBS=$(find "$OUTPUT_DIR" -maxdepth 1 -name "*.srt" -newer "$TEMP_OUTPUT" 2>/dev/null || true)
            ;;
        "vtt")
            SUBS=$(find "$OUTPUT_DIR" -maxdepth 1 -name "*.vtt" -newer "$TEMP_OUTPUT" 2>/dev/null || true)
            ;;
        "json3")
            SUBS=$(find "$OUTPUT_DIR" -maxdepth 1 -name "*.json3" -newer "$TEMP_OUTPUT" 2>/dev/null || true)
            ;;
        *)
            SUBS=$(find "$OUTPUT_DIR" -maxdepth 1 \( -name "*.srt" -o -name "*.vtt" \) -newer "$TEMP_OUTPUT" 2>/dev/null || true)
            ;;
    esac

    if [ -n "$SUBS" ]; then
        SUBTITLE_FILES=$(echo "$SUBS" | jq -R -s 'split("\n") | map(select(length > 0))')
    else
        SUBTITLE_FILES="[]"
    fi

    rm -f "$TEMP_OUTPUT"

    # 输出结果
    jq -n \
        --argjson subs "$SUBTITLE_FILES" \
        --argjson available "$AVAILABLE_LANGS_JSON" \
        '{
            success: true,
            subtitle_files: $subs,
            available_langs: $available
        }'
else
    rm -f "$TEMP_OUTPUT"
    echo '{"success": false, "error": "yt-dlp subtitle download failed"}' >&2
    exit 1
fi
