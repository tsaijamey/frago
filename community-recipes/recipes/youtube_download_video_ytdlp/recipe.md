---
name: youtube_download_video_ytdlp
type: atomic
runtime: shell
version: "1.0.0"
description: "使用 yt-dlp 下载 YouTube 视频，支持指定画质和字幕选项"
use_cases:
  - "下载 YouTube 视频用于本地观看或剪辑"
  - "下载视频同时获取字幕用于内容解读"
  - "批量下载 YouTube 视频"
output_targets:
  - file
  - stdout
tags:
  - youtube
  - video
  - download
  - yt-dlp
inputs:
  url:
    type: string
    required: true
    description: "YouTube 视频 URL"
  output_dir:
    type: string
    required: false
    description: "输出目录，默认当前目录"
  quality:
    type: string
    required: false
    description: "视频质量：360p/480p/720p/1080p/1440p/4k，默认 1080p"
  with_subs:
    type: boolean
    required: false
    description: "是否下载字幕，默认 true"
  subs_only:
    type: boolean
    required: false
    description: "仅下载字幕不下载视频，默认 false"
  sub_langs:
    type: string
    required: false
    description: "字幕语言：all/en/zh-Hans/zh-Hant/ja/auto，默认 all"
  prefer_codec:
    type: string
    required: false
    description: "视频编码偏好：av1/vp9/h264，默认不限"
outputs:
  video_file:
    type: string
    description: "下载的视频文件路径"
  subtitle_files:
    type: array
    description: "下载的字幕文件路径列表"
  metadata_file:
    type: string
    description: "视频元数据 JSON 文件路径"
warnings:
  - type: software_install
    command: "brew install"
    reason: "Auto-install yt-dlp and ffmpeg on macOS via Homebrew"
  - type: software_install
    command: "uv tool install"
    reason: "Auto-install yt-dlp and ffmpeg on Linux via uv"
  - type: file_deletion
    command: "rm"
    reason: "Clean up temporary files after download"
---

# youtube_download_video_ytdlp

## 功能描述

使用 yt-dlp 从 YouTube 下载视频，支持：
- 指定视频画质（360p ~ 4K）
- 下载自动生成字幕和人工字幕
- 支持多种语言字幕
- 仅下载字幕模式
- 视频编码选择（AV1/VP9/H.264）

## 使用方法

```bash
# 基本用法：下载 1080p 视频 + 所有字幕
frago recipe run youtube_download_video_ytdlp --params '{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
}'

# 指定输出目录和画质
frago recipe run youtube_download_video_ytdlp --params '{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "output_dir": "./downloads",
  "quality": "720p"
}'

# 下载 4K + 中文字幕
frago recipe run youtube_download_video_ytdlp --params '{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "quality": "4k",
  "sub_langs": "zh-Hans,zh-Hant,en"
}'

# 仅下载字幕
frago recipe run youtube_download_video_ytdlp --params '{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "subs_only": true
}'

# 偏好 AV1 编码（更小体积）
frago recipe run youtube_download_video_ytdlp --params '{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "prefer_codec": "av1"
}'
```

## 前置条件

1. **依赖自动安装**
   - 配方会自动检测并安装 yt-dlp 和 ffmpeg
   - macOS: 需要预装 Homebrew，会自动 `brew install`
   - Linux: 需要预装 uv，会自动 `uv tool install`；若无 uv 需手动安装依赖

2. **无需登录**
   - YouTube 公开视频无需登录即可下载
   - 私有视频需要浏览器 cookies（使用 --cookies-from-browser）

## 预期输出

```json
{
  "success": true,
  "video_file": "./Never Gonna Give You Up.mp4",
  "subtitle_files": [
    "./Never Gonna Give You Up.en.srt",
    "./Never Gonna Give You Up.zh-Hans.srt"
  ],
  "metadata_file": "./Never Gonna Give You Up.info.json"
}
```

## 字幕语言说明

| 语言代码 | 说明 |
|---------|------|
| `en` | 英文字幕 |
| `zh-Hans` | 简体中文 |
| `zh-Hant` | 繁体中文 |
| `ja` | 日文 |
| `ko` | 韩文 |
| `auto` | 自动生成字幕 |
| `all` | 全部可用字幕 |

## 视频编码说明

| 编码 | 说明 |
|------|------|
| `av1` | 最新编码，体积最小，需要较新设备支持 |
| `vp9` | Google 开源编码，体积较小 |
| `h264` | 最广泛兼容，体积较大 |

## 注意事项

1. **下载速度**：受网络环境影响
2. **定期更新**：运行 `yt-dlp -U` 保持工具更新
3. **版权声明**：请遵守 YouTube 服务条款

## 与其他配方的区别

- `youtube_extract_video_transcript`：通过浏览器网页版提取字幕，需要浏览器打开视频页面
- `youtube_download_video_ytdlp`（本配方）：命令行直接下载，无需浏览器，支持视频+字幕

## 更新历史

- v1.0.0 (2025-12-22): 初始版本
