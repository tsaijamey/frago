---
name: video_clip_annotator_ui
type: atomic
runtime: shell
version: "1.0.0"
description: "视频剪辑标注工具的静态 UI 资源，包含 HTML/JS/CSS 文件"
use_cases:
  - "被 video_clip_annotator workflow 配方复制使用"
  - "提供视频播放、波形显示、时间轴标注、TTS 生成等前端功能"
output_targets:
  - stdout
tags:
  - video
  - editor
  - annotation
  - ui
inputs:
  target_dir:
    type: string
    required: true
    description: "目标目录路径"
outputs:
  success:
    type: boolean
    description: "是否成功复制"
dependencies: []
---

# video_clip_annotator_ui

## 功能描述

视频剪辑标注工具的静态前端资源包，包含完整的 HTML/JS/CSS 文件。

此配方为纯静态资源，由 `video_clip_annotator` workflow 配方在运行时复制到 viewer content 目录使用。

## 文件结构

```
assets/
├── index.html    # 主页面
├── app.js        # 应用逻辑
└── style.css     # 样式表
```

## UI 功能模块

### 左侧面板 - 素材列表
- 显示目录中的媒体文件
- 按文件名编号自动排序
- 支持拖拽调整顺序
- 显示每个素材的标记数量

### 中间区域 - 播放器与时间轴
- HTML5 视频播放器
- Web Audio API 音频波形可视化
- 播放头位置指示
- 标记区域高亮
- 多轨时间轴编排（视频轨 + 旁白轨）
- 时间刻度尺

### 右侧面板 - 标注与 TTS
- 当前素材的标记列表
- 标记时间点显示
- 添加到时间轴按钮
- TTS 文本输入区
- 情感选择下拉菜单
- TTS 生成按钮
- 已生成的旁白列表

## 键盘快捷键

| 按键 | 功能 |
|------|------|
| `I` | 标记起始点 |
| `O` | 标记结束点 |
| `Space` | 播放/暂停 |
| `←` | 后退 1 秒 |
| `→` | 前进 1 秒 |
| `Shift+←` | 后退 5 秒 |
| `Shift+→` | 前进 5 秒 |
| `Ctrl+S` | 保存项目 |

## API 依赖

前端通过 frago server API 进行数据交互：

- `GET /api/file?path=...` - 读取文件/目录
- `POST /api/file?path=...` - 写入文件
- `POST /api/recipes/{name}/run` - 执行配方（TTS、视频合并）

## 注意事项

- 此配方不直接运行，仅作为资源包被其他配方使用
- 需要 frago server 运行中才能正常工作
- 波形绘制使用 Web Audio API，部分格式可能不支持
