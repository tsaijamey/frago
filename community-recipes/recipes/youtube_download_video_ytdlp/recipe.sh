#!/bin/bash
# Recipe: youtube_download_video_ytdlp
# Description: 使用 yt-dlp 下载 YouTube 视频，支持指定画质和字幕选项

set -e

# 自动安装依赖函数
install_dependency() {
    local cmd=$1
    local pkg_name=$2

    if command -v "$cmd" &> /dev/null; then
        return 0
    fi

    echo "Installing $pkg_name..." >&2

    # 检测操作系统和包管理器
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        if command -v brew &> /dev/null; then
            brew install "$pkg_name" >&2
        else
            echo '{"success": false, "error": "Homebrew not installed. Please install Homebrew first: https://brew.sh"}' >&2
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

    # 验证安装成功
    if ! command -v "$cmd" &> /dev/null; then
        echo "{\"success\": false, \"error\": \"Failed to install $pkg_name\"}" >&2
        exit 1
    fi

    echo "$pkg_name installed successfully." >&2
}

# 解析输入参数（从 stdin 读取 JSON）
INPUT=$(cat)

URL=$(echo "$INPUT" | jq -r '.url // empty')
OUTPUT_DIR=$(echo "$INPUT" | jq -r '.output_dir // "."')
QUALITY=$(echo "$INPUT" | jq -r '.quality // "1080p"')
WITH_SUBS=$(echo "$INPUT" | jq -r '.with_subs // true')
SUBS_ONLY=$(echo "$INPUT" | jq -r '.subs_only // false')
SUB_LANGS=$(echo "$INPUT" | jq -r '.sub_langs // "all"')
PREFER_CODEC=$(echo "$INPUT" | jq -r '.prefer_codec // empty')

# 验证必需参数
if [ -z "$URL" ]; then
    echo '{"success": false, "error": "url is required"}' >&2
    exit 1
fi

# 自动安装依赖
install_dependency "yt-dlp" "yt-dlp"
install_dependency "ffmpeg" "ffmpeg"

# 创建输出目录
mkdir -p "$OUTPUT_DIR"

# 画质映射到 yt-dlp 格式选择器
case "$QUALITY" in
    "360p")
        HEIGHT_LIMIT=360
        ;;
    "480p")
        HEIGHT_LIMIT=480
        ;;
    "720p")
        HEIGHT_LIMIT=720
        ;;
    "1080p")
        HEIGHT_LIMIT=1080
        ;;
    "1440p"|"2k"|"2K")
        HEIGHT_LIMIT=1440
        ;;
    "4k"|"4K"|"2160p")
        HEIGHT_LIMIT=2160
        ;;
    *)
        HEIGHT_LIMIT=1080
        ;;
esac

# 构建格式选择器
if [ -n "$PREFER_CODEC" ]; then
    case "$PREFER_CODEC" in
        "av1")
            FORMAT_SELECTOR="bestvideo[height<=${HEIGHT_LIMIT}][vcodec^=av01]+bestaudio/bestvideo[height<=${HEIGHT_LIMIT}]+bestaudio/best[height<=${HEIGHT_LIMIT}]"
            ;;
        "vp9")
            FORMAT_SELECTOR="bestvideo[height<=${HEIGHT_LIMIT}][vcodec^=vp9]+bestaudio/bestvideo[height<=${HEIGHT_LIMIT}]+bestaudio/best[height<=${HEIGHT_LIMIT}]"
            ;;
        "h264"|"avc")
            FORMAT_SELECTOR="bestvideo[height<=${HEIGHT_LIMIT}][vcodec^=avc1]+bestaudio/bestvideo[height<=${HEIGHT_LIMIT}]+bestaudio/best[height<=${HEIGHT_LIMIT}]"
            ;;
        *)
            FORMAT_SELECTOR="bestvideo[height<=${HEIGHT_LIMIT}]+bestaudio/best[height<=${HEIGHT_LIMIT}]"
            ;;
    esac
else
    FORMAT_SELECTOR="bestvideo[height<=${HEIGHT_LIMIT}]+bestaudio/best[height<=${HEIGHT_LIMIT}]"
fi

# 构建 yt-dlp 命令参数数组
YT_DLP_ARGS=()

# 添加字幕选项
if [ "$WITH_SUBS" = "true" ] || [ "$SUBS_ONLY" = "true" ]; then
    YT_DLP_ARGS+=("--write-subs" "--write-auto-subs")

    if [ "$SUB_LANGS" = "all" ]; then
        YT_DLP_ARGS+=("--sub-langs" "all")
    else
        YT_DLP_ARGS+=("--sub-langs" "$SUB_LANGS")
    fi

    # 转换为 SRT 格式
    YT_DLP_ARGS+=("--convert-subs" "srt")
fi

# 仅下载字幕模式
if [ "$SUBS_ONLY" = "true" ]; then
    YT_DLP_ARGS+=("--skip-download")
else
    YT_DLP_ARGS+=("-f" "$FORMAT_SELECTOR")
    # 合并为 mp4
    YT_DLP_ARGS+=("--merge-output-format" "mp4")
fi

# 添加元数据和输出路径
YT_DLP_ARGS+=("--write-info-json")
YT_DLP_ARGS+=("-o" "$OUTPUT_DIR/%(title)s.%(ext)s")
YT_DLP_ARGS+=("$URL")

# 执行下载
TEMP_OUTPUT=$(mktemp)
if yt-dlp "${YT_DLP_ARGS[@]}" 2>&1 | tee "$TEMP_OUTPUT"; then
    # 解析输出文件
    VIDEO_FILE=""
    SUBTITLE_FILES="[]"
    METADATA_FILE=""

    # 查找生成的文件
    if [ "$SUBS_ONLY" != "true" ]; then
        VIDEO_FILE=$(find "$OUTPUT_DIR" -maxdepth 1 -name "*.mp4" -newer "$TEMP_OUTPUT" 2>/dev/null | head -1 || true)
        if [ -z "$VIDEO_FILE" ]; then
            VIDEO_FILE=$(find "$OUTPUT_DIR" -maxdepth 1 -name "*.mkv" -newer "$TEMP_OUTPUT" 2>/dev/null | head -1 || true)
        fi
        if [ -z "$VIDEO_FILE" ]; then
            VIDEO_FILE=$(find "$OUTPUT_DIR" -maxdepth 1 -name "*.webm" -newer "$TEMP_OUTPUT" 2>/dev/null | head -1 || true)
        fi
    fi

    # 查找字幕文件
    SUBS=$(find "$OUTPUT_DIR" -maxdepth 1 \( -name "*.srt" -o -name "*.vtt" \) -newer "$TEMP_OUTPUT" 2>/dev/null || true)
    if [ -n "$SUBS" ]; then
        SUBTITLE_FILES=$(echo "$SUBS" | jq -R -s 'split("\n") | map(select(length > 0))')
    fi

    # 查找元数据文件
    METADATA_FILE=$(find "$OUTPUT_DIR" -maxdepth 1 -name "*.info.json" -newer "$TEMP_OUTPUT" 2>/dev/null | head -1 || true)

    rm -f "$TEMP_OUTPUT"

    # 输出结果
    jq -n \
        --arg video "$VIDEO_FILE" \
        --argjson subs "$SUBTITLE_FILES" \
        --arg meta "$METADATA_FILE" \
        '{
            success: true,
            video_file: (if $video == "" then null else $video end),
            subtitle_files: $subs,
            metadata_file: (if $meta == "" then null else $meta end)
        }'
else
    rm -f "$TEMP_OUTPUT"
    echo '{"success": false, "error": "yt-dlp download failed"}' >&2
    exit 1
fi
