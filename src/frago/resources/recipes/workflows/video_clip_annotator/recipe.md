---
name: video_clip_annotator
type: workflow
runtime: python
version: "1.0.0"
description: "视频剪辑标注工具 - 启动交互式 Web UI 进行视频片段标注、TTS 生成和视频合成"
use_cases:
  - "视频素材标注和片段提取"
  - "时间轴编排和排序"
  - "TTS 旁白生成和插入"
  - "最终视频合成导出"
tags:
  - video
  - editor
  - annotation
  - workflow
  - interactive
output_targets:
  - stdout
  - file
inputs:
  dir:
    type: string
    required: true
    description: "素材目录路径（包含视频/音频文件）"
  output_dir:
    type: string
    required: false
    description: "输出目录，默认为 {dir}/output"
outputs:
  success:
    type: boolean
    description: "是否成功启动"
  url:
    type: string
    description: "标注工具 Web UI 的访问地址"
  content_id:
    type: string
    description: "viewer content ID"
  media_count:
    type: number
    description: "找到的媒体文件数量"
dependencies:
  - video_clip_annotator_ui
  - volcengine_tts_with_emotion
  - video_merge_clips
flow:
  - step: 1
    action: "validate_directory"
    description: "Verify input directory exists and is a directory"
    inputs:
      - source: "params.dir"
  - step: 2
    action: "scan_media_files"
    description: "Scan directory for video/audio files"
    inputs:
      - source: "params.dir"
    outputs:
      - name: "media_files"
        type: "list"
      - name: "media_count"
        type: "number"
  - step: 3
    action: "generate_content_id"
    description: "Generate unique content ID from directory path"
    inputs:
      - source: "params.dir"
    outputs:
      - name: "content_id"
        type: "string"
  - step: 4
    action: "setup_viewer_content"
    description: "Copy UI assets and generate config.json"
    recipe: "video_clip_annotator_ui"
    inputs:
      - source: "step.3.content_id"
      - source: "params.dir"
      - source: "step.2.media_files"
    outputs:
      - name: "content_dir"
        type: "string"
  - step: 5
    action: "ensure_subdirectories"
    description: "Create tts/, output/, temp/ subdirectories"
    inputs:
      - source: "params.dir"
  - step: 6
    action: "open_browser"
    description: "Navigate Chrome to Web UI"
    inputs:
      - source: "step.3.content_id"
    outputs:
      - name: "url"
        type: "string"
      - name: "browser_opened"
        type: "boolean"
---

# video_clip_annotator

## 功能描述

视频剪辑标注工具，启动一个交互式 Web UI，用于：

1. **素材浏览** - 扫描指定目录的视频/音频文件，按编号排序显示
2. **片段标注** - 在时间轴上标记需要使用的片段（起始-结束时间点）
3. **时间轴编排** - 拖拽调整片段顺序和位置
4. **TTS 旁白** - 输入文本生成带情感的语音旁白
5. **视频合成** - 将所有片段和旁白合成为最终视频

## 使用方法

```bash
frago recipe run video_clip_annotator '{"dir": "/path/to/video/clips"}'
```

**参数说明**：
- `dir` (必需): 包含视频/音频素材的目录路径
- `output_dir` (可选): 输出目录，默认为 `{dir}/output`

## 支持的媒体格式

- **视频**: mp4, webm, mov
- **音频**: mp3, wav, ogg, m4a

## 工作流程

1. 验证目录存在且包含媒体文件
2. 按文件名中的数字编号排序媒体文件
3. 复制 UI 资源到 viewer content 目录
4. 生成 config.json 配置文件
5. 创建必要的子目录（tts/, output/, temp/）
6. 调用 `frago chrome navigate` 打开 Web UI

## 数据文件

运行后会在素材目录中创建以下文件：

| 文件 | 说明 |
|------|------|
| `markers.json` | 每个素材的片段标记数据 |
| `timeline.json` | 时间轴编排数据 |
| `tts/*.wav` | 生成的 TTS 音频文件 |
| `tts/*.json` | TTS 元数据文件 |
| `output/*.mp4` | 合成的最终视频 |

## 预期输出

成功时：
```json
{
  "success": true,
  "url": "http://127.0.0.1:8093/viewer/content/abc123def456/index.html",
  "content_id": "abc123def456",
  "media_count": 5,
  "media_files": ["clip_01.mp4", "clip_02.mp4", "..."],
  "browser_opened": true
}
```

失败时：
```json
{
  "success": false,
  "error": "目录中没有找到媒体文件"
}
```

## 前置条件

1. **frago server 运行中**：`frago server`
2. **Chrome 已启动 CDP**：`frago chrome start`
3. **TTS 环境变量配置**（如需使用 TTS 功能）：
   - `X_APP_ID`
   - `X_ACCESS_TOKEN`
   - `VOICE_ID`

## 注意事项

- Web UI 需要 frago server 的 `/api/file` 接口支持
- 波形绘制使用 Web Audio API，某些编码可能不支持
- TTS 生成需要配置火山引擎凭证
- 视频合成使用 ffmpeg，需确保已安装
