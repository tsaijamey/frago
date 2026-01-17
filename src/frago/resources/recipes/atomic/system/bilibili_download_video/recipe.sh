#!/bin/bash
# Recipe: bilibili_download_video
# Description: 使用 yt-dlp 下载 B站视频，支持指定画质和字幕选项

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
            echo '{"success": false, "error": "Homebrew not installed. Install with: /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""}' >&2
            exit 1
        fi
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux - 优先使用 uv
        if command -v uv &> /dev/null; then
            uv tool install "$pkg_name" >&2
        elif command -v apt &> /dev/null; then
            sudo apt update && sudo apt install -y "$pkg_name" >&2
        elif command -v dnf &> /dev/null; then
            sudo dnf install -y "$pkg_name" >&2
        elif command -v pacman &> /dev/null; then
            sudo pacman -S --noconfirm "$pkg_name" >&2
        else
            echo "{\"success\": false, \"error\": \"Cannot auto-install $pkg_name. Please install manually.\"}" >&2
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
BROWSER=$(echo "$INPUT" | jq -r '.browser // "chrome"')
BROWSER_PROFILE=$(echo "$INPUT" | jq -r '.browser_profile // empty')

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

# 构建 cookies 参数
COOKIES_ARG="--cookies-from-browser $BROWSER"
if [ -n "$BROWSER_PROFILE" ]; then
    COOKIES_ARG="--cookies-from-browser $BROWSER:$BROWSER_PROFILE"
fi

# 画质映射到 yt-dlp 格式选择器
case "$QUALITY" in
    "360p")
        FORMAT_SELECTOR="bestvideo[height<=360]+bestaudio/best[height<=360]"
        ;;
    "480p")
        FORMAT_SELECTOR="bestvideo[height<=480]+bestaudio/best[height<=480]"
        ;;
    "720p")
        FORMAT_SELECTOR="bestvideo[height<=720]+bestaudio/best[height<=720]"
        ;;
    "1080p")
        FORMAT_SELECTOR="bestvideo[height<=1080]+bestaudio/best[height<=1080]"
        ;;
    "4k"|"4K"|"2160p")
        FORMAT_SELECTOR="bestvideo[height<=2160]+bestaudio/best[height<=2160]"
        ;;
    *)
        FORMAT_SELECTOR="bestvideo[height<=1080]+bestaudio/best[height<=1080]"
        ;;
esac

# 构建 yt-dlp 命令
YT_DLP_CMD="yt-dlp $COOKIES_ARG"

# 添加字幕选项
if [ "$WITH_SUBS" = "true" ] || [ "$SUBS_ONLY" = "true" ]; then
    YT_DLP_CMD="$YT_DLP_CMD --write-subs --sub-langs all"
fi

# 仅下载字幕模式
if [ "$SUBS_ONLY" = "true" ]; then
    YT_DLP_CMD="$YT_DLP_CMD --skip-download"
else
    YT_DLP_CMD="$YT_DLP_CMD -f \"$FORMAT_SELECTOR\""
fi

# 添加元数据和输出路径
YT_DLP_CMD="$YT_DLP_CMD --write-info-json"
YT_DLP_CMD="$YT_DLP_CMD -o \"$OUTPUT_DIR/%(title)s.%(ext)s\""
YT_DLP_CMD="$YT_DLP_CMD \"$URL\""

# 执行下载
TEMP_OUTPUT=$(mktemp)
if eval $YT_DLP_CMD 2>&1 | tee "$TEMP_OUTPUT"; then
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
    fi

    # 查找字幕文件
    SUBS=$(find "$OUTPUT_DIR" -maxdepth 1 -name "*.srt" -newer "$TEMP_OUTPUT" 2>/dev/null || true)
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
