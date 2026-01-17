#!/bin/bash
# Recipe: video_clip_annotator_ui
# Description: 复制 UI 资源到目标目录

set -e

# Parse JSON input
INPUT="${1:-{}}"
TARGET_DIR=$(echo "$INPUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('target_dir', ''))")

if [ -z "$TARGET_DIR" ]; then
    echo '{"success": false, "error": "缺少必需参数: target_dir"}'
    exit 1
fi

# Get script directory (where assets folder is)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSETS_DIR="$SCRIPT_DIR/assets"

if [ ! -d "$ASSETS_DIR" ]; then
    echo '{"success": false, "error": "assets 目录不存在"}'
    exit 1
fi

# Create target directory
mkdir -p "$TARGET_DIR"

# Copy assets
cp -r "$ASSETS_DIR"/* "$TARGET_DIR/"

echo "{\"success\": true, \"target_dir\": \"$TARGET_DIR\", \"files\": [\"index.html\", \"app.js\", \"style.css\"]}"
