---
name: youtube_extract_subtitles_ytdlp
type: atomic
runtime: shell
version: "1.0.0"
description: "使用 yt-dlp 仅下载 YouTube 视频字幕，支持自动字幕和人工字幕"
use_cases:
  - "快速获取视频文字内容用于 LLM 分析"
  - "提取字幕用于翻译或学习"
  - "批量提取视频字幕"
output_targets:
  - file
  - stdout
tags:
  - youtube
  - subtitle
  - extraction
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
  langs:
    type: string
    required: false
    description: "字幕语言：all/en/zh-Hans/zh-Hant/ja/ko，默认 all"
  auto_subs:
    type: boolean
    required: false
    description: "是否下载自动生成字幕，默认 true"
  manual_subs:
    type: boolean
    required: false
    description: "是否下载人工上传字幕，默认 true"
  output_format:
    type: string
    required: false
    description: "输出格式：srt/vtt/json3，默认 srt"
outputs:
  subtitle_files:
    type: array
    description: "下载的字幕文件路径列表（保留完整时间戳）"
  available_langs:
    type: array
    description: "该视频可用的字幕语言列表"
---

# youtube_extract_subtitles_ytdlp

## 功能描述

快速下载 YouTube 视频的字幕，无需下载视频文件。适合：
- 快速获取视频内容用于 LLM 分析/总结
- 字幕翻译和语言学习
- 批量视频内容提取

支持：
- 人工上传的字幕（更准确）
- YouTube 自动生成字幕（ASR）
- 多语言字幕同时下载

## 使用方法

```bash
# 下载所有字幕
frago recipe run youtube_extract_subtitles_ytdlp --params '{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
}'

# 仅下载中英文字幕
frago recipe run youtube_extract_subtitles_ytdlp --params '{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "langs": "en,zh-Hans,zh-Hant"
}'

# 仅下载人工字幕（不要自动生成的）
frago recipe run youtube_extract_subtitles_ytdlp --params '{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "auto_subs": false
}'

# 输出为 VTT 格式
frago recipe run youtube_extract_subtitles_ytdlp --params '{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "output_format": "vtt"
}'

# 指定输出目录
frago recipe run youtube_extract_subtitles_ytdlp --params '{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "output_dir": "./subtitles"
}'
```

## 前置条件

1. **依赖自动安装**：yt-dlp
2. **无需登录**：公开视频字幕无需账号

## 预期输出

```json
{
  "success": true,
  "subtitle_files": [
    "./Never Gonna Give You Up.en.srt",
    "./Never Gonna Give You Up.zh-Hans.srt"
  ],
  "available_langs": ["en", "zh-Hans", "zh-Hant", "ja", "ko"]
}
```

字幕文件保留完整的 SRT 格式（含时间戳）：
```srt
1
00:00:00,000 --> 00:00:04,000
Never gonna give you up

2
00:00:04,000 --> 00:00:08,000
Never gonna let you down
```

## 字幕语言代码

| 语言代码 | 说明 |
|---------|------|
| `en` | 英文 |
| `zh-Hans` | 简体中文 |
| `zh-Hant` | 繁体中文 |
| `ja` | 日文 |
| `ko` | 韩文 |
| `es` | 西班牙语 |
| `fr` | 法语 |
| `de` | 德语 |
| `all` | 全部可用语言 |

## 与其他配方的区别

| 配方 | 方式 | 优点 | 缺点 |
|------|------|------|------|
| `youtube_extract_video_transcript` | 浏览器网页版 | 无需安装工具 | 需要打开浏览器，速度慢 |
| `youtube_extract_subtitles_ytdlp`（本配方） | yt-dlp 命令行 | 快速、批量友好 | 需要安装 yt-dlp |

## 更新历史

- v1.0.0 (2025-12-22): 初始版本
