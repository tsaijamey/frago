---
name: video_merge_clips
type: atomic
runtime: python
description: "使用 ffmpeg concat 合并多个视频片段为一个连续视频"
use_cases:
  - "合并多个录制的视频片段"
  - "视频制作流水线中的合并步骤"
  - "批量视频片段的顺序拼接"
tags:
  - video
  - ffmpeg
  - merge
  - concat
output_targets:
  - stdout
  - file
inputs:
  clips:
    type: array
    required: true
    description: "视频文件路径列表（按顺序合并）"
  output_file:
    type: string
    required: true
    description: "输出视频文件路径"
  codec:
    type: string
    required: false
    description: "视频编码，默认 'copy'（无损），可选 'libx264'"
outputs:
  file_path:
    type: string
    description: "输出文件绝对路径"
  duration:
    type: number
    description: "合并后视频时长（秒）"
  file_size:
    type: number
    description: "文件大小（字节）"
  clips_count:
    type: number
    description: "合并的片段数量"
dependencies: []
version: "1.0.0"
---

# video_merge_clips

## 功能描述

使用 ffmpeg 的 concat demuxer 合并多个视频片段。默认使用 stream copy 模式（无损合并），要求所有视频片段具有相同的编码格式和分辨率。

## 使用方法

```bash
# 合并两个视频
uv run frago recipe run video_merge_clips \
  --params '{"clips": ["part1.mp4", "part2.mp4"], "output_file": "merged.mp4"}'

# 使用重编码合并（兼容不同格式）
uv run frago recipe run video_merge_clips \
  --params '{"clips": ["a.mp4", "b.mp4", "c.mp4"], "output_file": "final.mp4", "codec": "libx264"}'
```

## 前置条件

- ffmpeg 已安装
- 所有输入视频文件存在且可读
- 使用 `copy` 模式时，视频格式需一致

## 预期输出

```json
{
  "success": true,
  "file_path": "/absolute/path/to/merged.mp4",
  "duration": 45.5,
  "file_size": 12345678,
  "clips_count": 3,
  "input_clips": [
    {"file": "part1.mp4", "duration": 15.0},
    {"file": "part2.mp4", "duration": 20.5},
    {"file": "part3.mp4", "duration": 10.0}
  ],
  "codec": "copy"
}
```

## 注意事项

- **编码一致性**: `copy` 模式要求所有片段编码格式相同
- **分辨率**: 建议所有片段分辨率一致，否则可能产生问题
- **性能**: `copy` 模式非常快（无重编码），`libx264` 会重编码较慢
- **超时**: 大量/大文件合并时可能需要较长时间

## 更新历史

| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-26 | v1.0.0 | 初始版本 |
