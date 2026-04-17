---
name: bilibili_download_video
type: atomic
runtime: shell
version: "1.0.0"
description: "使用 yt-dlp 下载 B站视频，支持指定画质和字幕选项"
use_cases:
  - "下载 B站视频用于本地观看或剪辑"
  - "下载视频同时获取 AI 字幕用于内容解读"
  - "批量下载 B站视频"
output_targets:
  - file
  - stdout
tags:
  - bilibili
  - video
  - download
  - yt-dlp
inputs:
  url:
    type: string
    required: true
    description: "B站视频 URL（支持 BV 号格式）"
  output_dir:
    type: string
    required: false
    description: "输出目录，默认当前目录"
  quality:
    type: string
    required: false
    description: "视频质量：360p/480p/720p/1080p/4k，默认 1080p"
  with_subs:
    type: boolean
    required: false
    description: "是否下载字幕，默认 true"
  subs_only:
    type: boolean
    required: false
    description: "仅下载字幕不下载视频，默认 false"
  browser:
    type: string
    required: false
    description: "浏览器类型：chrome/firefox/chromium，默认 chrome"
  browser_profile:
    type: string
    required: false
    description: "浏览器 profile 路径（可选）"
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
---

# bilibili_download_video

## 功能描述

使用 yt-dlp 从 B站下载视频，支持：
- 指定视频画质（360p ~ 4K）
- 下载 AI 生成字幕（中/英/日）
- 下载弹幕文件
- 仅下载字幕模式

## 使用方法

```bash
# 基本用法：下载 1080p 视频 + 所有字幕
frago recipe run bilibili_download_video --params '{
  "url": "https://www.bilibili.com/video/BV18HUZBPE5w/"
}'

# 指定输出目录和画质
frago recipe run bilibili_download_video --params '{
  "url": "https://www.bilibili.com/video/BV18HUZBPE5w/",
  "output_dir": "./downloads",
  "quality": "720p"
}'

# 仅下载字幕
frago recipe run bilibili_download_video --params '{
  "url": "https://www.bilibili.com/video/BV18HUZBPE5w/",
  "subs_only": true
}'

# 使用 Firefox 浏览器
frago recipe run bilibili_download_video --params '{
  "url": "https://www.bilibili.com/video/BV18HUZBPE5w/",
  "browser": "firefox"
}'
```

## 前置条件

1. **浏览器已登录 B站**
   - 需要登录才能下载 1080p 及以上画质
   - 4K 需要大会员

2. **依赖自动安装**
   - 配方会自动检测并安装 yt-dlp 和 ffmpeg
   - macOS 需要预装 Homebrew
   - Linux 支持 pip/apt/pacman

## 预期输出

```json
{
  "success": true,
  "video_file": "./决战A股！全公司AI炒股一个月.mp4",
  "subtitle_files": [
    "./决战A股！全公司AI炒股一个月.ai-zh.srt",
    "./决战A股！全公司AI炒股一个月.ai-en.srt"
  ],
  "metadata_file": "./决战A股！全公司AI炒股一个月.info.json"
}
```

## 注意事项

1. **反爬保护**：直接请求会被拦截(HTTP 412)，必须使用浏览器 cookies
2. **下载速度**：B站限速约 1MB/s
3. **编码选择**：AV1 体积最小，H.264 兼容性最好
4. **定期更新**：运行 `yt-dlp -U` 保持工具更新

## 更新历史

- v1.0.0 (2025-12-22): 初始版本
