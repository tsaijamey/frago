#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Recipe: video_cut_studio
Description: 视频剪辑工作台 - 启动交互式 Web UI
"""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

# Supported media extensions
MEDIA_EXTENSIONS = {'.mp4', '.webm', '.mov', '.mkv', '.avi', '.mp3', '.wav', '.ogg', '.m4a'}

# Paths
FRAGO_HOME = Path.home() / '.frago'
VIEWER_CONTENT_DIR = FRAGO_HOME / 'viewer' / 'content'
UI_ASSETS_DIR = FRAGO_HOME / 'recipes' / 'atomic' / 'system' / 'video_cut_studio_ui' / 'assets'


def generate_content_id(dir_path: str) -> str:
    """Generate a unique content ID based on directory path."""
    return hashlib.sha256(dir_path.encode()).hexdigest()[:12]


def scan_media_files(dir_path: Path) -> list:
    """Scan directory for media files."""
    files = []
    for f in dir_path.iterdir():
        if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS:
            # Get file info
            stat = f.stat()
            files.append({
                'name': f.name,
                'path': str(f),
                'size': stat.st_size,
                'modified': stat.st_mtime
            })
    return files


def extract_number(filename: str) -> tuple:
    """Extract number from filename for sorting."""
    import re
    match = re.search(r'(\d+)', filename)
    if match:
        return (0, int(match.group(1)), filename)
    return (1, 0, filename)


def setup_viewer_content(content_id: str, dir_path: str, media_files: list) -> Path:
    """Setup viewer content directory with UI files and config."""
    content_dir = VIEWER_CONTENT_DIR / content_id
    content_dir.mkdir(parents=True, exist_ok=True)

    # Copy UI assets
    if UI_ASSETS_DIR.exists():
        for asset in UI_ASSETS_DIR.iterdir():
            if asset.is_file():
                shutil.copy2(asset, content_dir / asset.name)
    else:
        raise FileNotFoundError(f"UI assets not found: {UI_ASSETS_DIR}")

    # Generate config.json
    config = {
        'dir': dir_path,
        'mediaFiles': media_files,
        'contentId': content_id,
        'apiBase': 'http://127.0.0.1:8093/api'
    }

    config_path = content_dir / 'config.json'
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2))

    return content_dir


def ensure_subdirs(dir_path: Path):
    """Ensure necessary subdirectories exist."""
    (dir_path / 'tts').mkdir(exist_ok=True)
    (dir_path / 'output').mkdir(exist_ok=True)
    (dir_path / 'temp').mkdir(exist_ok=True)


def main():
    """Main entry point."""
    # Parse parameters
    if len(sys.argv) < 2:
        print(json.dumps({
            'success': False,
            'error': '缺少必需参数: dir'
        }))
        sys.exit(1)

    try:
        params = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        print(json.dumps({
            'success': False,
            'error': f'参数解析失败: {e}'
        }))
        sys.exit(1)

    # Get directory path
    dir_path_str = params.get('dir')
    if not dir_path_str:
        print(json.dumps({
            'success': False,
            'error': '缺少必需参数: dir'
        }))
        sys.exit(1)

    dir_path = Path(dir_path_str).expanduser().resolve()

    # Validate directory
    if not dir_path.exists():
        print(json.dumps({
            'success': False,
            'error': f'目录不存在: {dir_path}'
        }))
        sys.exit(1)

    if not dir_path.is_dir():
        print(json.dumps({
            'success': False,
            'error': f'路径不是目录: {dir_path}'
        }))
        sys.exit(1)

    # Scan media files
    print(f"扫描媒体文件: {dir_path}", file=sys.stderr)
    media_files = scan_media_files(dir_path)

    if not media_files:
        print(json.dumps({
            'success': False,
            'error': f'目录中没有找到媒体文件 (支持: {", ".join(MEDIA_EXTENSIONS)})'
        }))
        sys.exit(1)

    # Sort by number in filename
    media_files.sort(key=lambda f: extract_number(f['name']))
    print(f"找到 {len(media_files)} 个媒体文件", file=sys.stderr)

    # Generate content ID
    content_id = generate_content_id(str(dir_path))

    # Setup viewer content
    print(f"设置 UI 资源...", file=sys.stderr)
    try:
        content_dir = setup_viewer_content(content_id, str(dir_path), media_files)
    except FileNotFoundError as e:
        print(json.dumps({
            'success': False,
            'error': str(e)
        }))
        sys.exit(1)

    # Ensure subdirectories
    ensure_subdirs(dir_path)

    # Build URL (cache-bust to force fresh assets)
    import time as _time
    url = f"http://127.0.0.1:8093/viewer/content/{content_id}/index.html?v={int(_time.time())}"

    # Output result (open_url tells runner to open browser)
    result = {
        'success': True,
        'open_url': url,
        'url': url,
        'content_id': content_id,
        'content_dir': str(content_dir),
        'media_count': len(media_files),
        'media_files': [f['name'] for f in media_files],
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == '__main__':
    main()
