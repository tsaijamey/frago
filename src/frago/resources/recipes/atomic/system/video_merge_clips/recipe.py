#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Recipe: video_merge_clips
Description: 合并多个视频片段为一个视频
Created: 2025-11-26
Version: 1.0.0
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def get_video_info(file_path: str) -> dict:
    """获取视频信息"""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        file_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    if result.returncode == 0:
        data = json.loads(result.stdout)
        format_info = data.get("format", {})
        return {
            "duration": float(format_info.get("duration", 0)),
            "size": int(format_info.get("size", 0)),
            "bit_rate": int(format_info.get("bit_rate", 0))
        }
    return {"duration": 0, "size": 0, "bit_rate": 0}


def merge_videos_concat(clips: list, output_file: str, codec: str = "copy") -> dict:
    """使用 ffmpeg concat demuxer 合并视频"""

    # 创建临时文件列表
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        list_file = f.name
        for clip in clips:
            # 使用绝对路径
            abs_path = str(Path(clip).absolute())
            f.write(f"file '{abs_path}'\n")

    try:
        # 构建 ffmpeg 命令
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
        ]

        if codec == "copy":
            cmd.extend(["-c", "copy"])
        else:
            cmd.extend(["-c:v", codec, "-c:a", "aac"])

        cmd.append(output_file)

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg 合并失败: {result.stderr}")

        return {"command": " ".join(cmd), "list_file": list_file}

    finally:
        # 清理临时文件
        Path(list_file).unlink(missing_ok=True)


def main():
    """主函数"""
    # 解析参数
    if len(sys.argv) < 2:
        params = {}
    else:
        try:
            params = json.loads(sys.argv[1])
        except json.JSONDecodeError as e:
            print(json.dumps({
                "success": False,
                "error": f"参数 JSON 解析失败: {e}"
            }), file=sys.stderr)
            sys.exit(1)

    # 验证必需参数
    clips = params.get("clips")
    output_file = params.get("output_file")

    if not clips:
        print(json.dumps({
            "success": False,
            "error": "缺少必需参数: clips"
        }), file=sys.stderr)
        sys.exit(1)

    if not isinstance(clips, list) or len(clips) == 0:
        print(json.dumps({
            "success": False,
            "error": "clips 必须是非空数组"
        }), file=sys.stderr)
        sys.exit(1)

    if not output_file:
        print(json.dumps({
            "success": False,
            "error": "缺少必需参数: output_file"
        }), file=sys.stderr)
        sys.exit(1)

    # 可选参数
    codec = params.get("codec", "copy")

    try:
        # 确保输出目录存在
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 验证输入文件存在
        missing_files = []
        for clip in clips:
            if not Path(clip).exists():
                missing_files.append(clip)

        if missing_files:
            print(json.dumps({
                "success": False,
                "error": f"以下文件不存在: {missing_files}"
            }), file=sys.stderr)
            sys.exit(1)

        # 获取输入视频信息
        input_info = []
        total_duration = 0
        for clip in clips:
            info = get_video_info(clip)
            input_info.append({
                "file": clip,
                "duration": info["duration"]
            })
            total_duration += info["duration"]

        print(f"合并 {len(clips)} 个视频片段", file=sys.stderr)
        print(f"预计总时长: {total_duration:.2f} 秒", file=sys.stderr)

        # 合并视频
        merge_info = merge_videos_concat(clips, output_file, codec)

        # 获取输出视频信息
        output_info = get_video_info(output_file)

        # 输出结果
        result = {
            "success": True,
            "file_path": str(output_path.absolute()),
            "duration": output_info["duration"],
            "file_size": output_info["size"],
            "clips_count": len(clips),
            "input_clips": input_info,
            "codec": codec
        }

        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0)

    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
