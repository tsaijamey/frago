# Frago 示例参考

## 分镜JSON示例

### 基础分镜结构

```json
{
  "shot_id": "shot_001",
  "duration": 10,
  "type": "browser_recording",
  "description": "展示GitHub首页",
  "actions": [
    {
      "action": "navigate",
      "url": "https://github.com",
      "wait": 3
    },
    {
      "action": "scroll",
      "direction": "down",
      "pixels": 500,
      "wait": 2
    }
  ],
  "narration": "GitHub是全球最大的代码托管平台...",
  "audio_config": {
    "voice": "default",
    "speed": 1.0
  },
  "source_reference": "https://github.com/about"
}
```

### 完整分镜示例（带视觉效果）

```json
{
  "shot_id": "shot_002",
  "duration": 15,
  "type": "browser_recording",
  "description": "演示Notion核心功能",
  "actions": [
    {
      "action": "navigate",
      "url": "https://www.notion.so/product",
      "wait": 2
    },
    {
      "action": "spotlight",
      "selector": ".hero-section",
      "duration": 3,
      "wait": 1
    },
    {
      "action": "highlight",
      "selector": ".feature-card:nth-child(1)",
      "color": "#FF6B6B",
      "duration": 2,
      "wait": 1
    },
    {
      "action": "scroll",
      "direction": "down",
      "pixels": 800,
      "smooth": true,
      "wait": 2
    },
    {
      "action": "annotate",
      "selector": ".pricing-section",
      "text": "灵活的定价方案",
      "position": "top",
      "wait": 2
    }
  ],
  "narration": "Notion提供了强大的页面编辑能力，支持多种内容类型，并且拥有灵活的定价方案...",
  "audio_config": {
    "voice": "zh-CN-XiaoxiaoNeural",
    "speed": 1.0,
    "pitch": 1.0
  },
  "source_reference": "https://www.notion.so/product"
}
```

## Recipe脚本示例

### 示例1: YouTube字幕提取

**脚本文件**: `youtube_extract_video_transcript.js`

```javascript
// 提取YouTube视频完整字幕
(async () => {
  // 点击"显示完整字幕"按钮
  const transcriptButton = document.querySelector('button[aria-label*="transcript"]');
  if (transcriptButton) {
    transcriptButton.click();
    await new Promise(resolve => setTimeout(resolve, 1000));
  }

  // 提取字幕文本
  const transcriptSegments = document.querySelectorAll('.ytd-transcript-segment-renderer');
  const transcript = Array.from(transcriptSegments)
    .map(segment => segment.textContent.trim())
    .join('\n');

  return {
    transcript: transcript,
    segmentCount: transcriptSegments.length
  };
})();
```

**元数据文件**: `youtube_extract_video_transcript.md`

```yaml
---
name: youtube_extract_video_transcript
type: atomic
runtime: chrome-js
version: "1.0"
description: "提取YouTube视频完整字幕"
use_cases: ["视频内容分析", "字幕下载", "文本摘要"]
tags: ["youtube", "transcript", "web-scraping"]
output_targets: [stdout, file]
inputs:
  url:
    type: string
    description: "YouTube视频URL"
    required: true
outputs:
  transcript:
    type: string
    description: "完整字幕文本"
  segmentCount:
    type: integer
    description: "字幕段落数量"
---

# 功能描述

从YouTube视频页面提取完整字幕文本。

## 使用方法

```bash
uv run frago recipe run youtube_extract_video_transcript \
    --params '{"url": "https://youtube.com/watch?v=..."}' \
    --output-file transcript.txt
```

## 前置条件

- Chrome已通过CDP启动（9222端口）
- 已导航到YouTube视频页面
- 视频必须有字幕可用

## 预期输出

返回JSON格式：
```json
{
  "transcript": "字幕完整文本...",
  "segmentCount": 150
}
```

## 注意事项

- 需要先点击"显示字幕"按钮
- 某些视频可能没有字幕
- 建议等待页面完全加载后执行

## 更新历史

- v1.0 (2025-01-15): 初始版本
```

### 示例2: 页面诊断工具

**脚本文件**: `test_inspect_tab.js`

```javascript
// 获取当前标签页诊断信息
(() => {
  const pageInfo = {
    title: document.title,
    url: window.location.href,
    readyState: document.readyState,
    stats: {
      totalElements: document.querySelectorAll('*').length,
      images: document.images.length,
      links: document.links.length,
      forms: document.forms.length,
      scripts: document.scripts.length
    },
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight
    },
    performance: {
      loadTime: performance.timing.loadEventEnd - performance.timing.navigationStart,
      domContentLoaded: performance.timing.domContentLoadedEventEnd - performance.timing.navigationStart
    }
  };

  return pageInfo;
})();
```

**元数据文件**: `test_inspect_tab.md`

```yaml
---
name: test_inspect_tab
type: atomic
runtime: chrome-js
version: "1.0"
description: "获取当前标签页诊断信息（标题、URL、DOM统计）"
use_cases: ["页面调试", "性能分析", "DOM结构检查"]
tags: ["debug", "diagnostic", "page-info"]
output_targets: [stdout]
inputs: {}
outputs:
  pageInfo:
    type: object
    description: "页面诊断信息"
---

# 功能描述

获取当前标签页的诊断信息，包括标题、URL、DOM统计和性能数据。

## 使用方法

```bash
uv run frago recipe run test_inspect_tab
```

## 前置条件

- Chrome已通过CDP启动（9222端口）
- 已导航到目标页面

## 预期输出

```json
{
  "title": "页面标题",
  "url": "https://example.com",
  "readyState": "complete",
  "stats": {
    "totalElements": 1234,
    "images": 56,
    "links": 78,
    "forms": 2,
    "scripts": 12
  },
  "viewport": {
    "width": 1280,
    "height": 720
  },
  "performance": {
    "loadTime": 1234,
    "domContentLoaded": 567
  }
}
```

## 注意事项

- 建议在页面完全加载后执行
- 性能数据可能为0（如果页面还在加载）

## 更新历史

- v1.0 (2025-01-15): 初始版本
```

## 录制脚本示例

### 示例1: 简单页面录制

```bash
#!/bin/bash
# shot_001_record.sh - 录制GitHub首页

set -e

# 导航到GitHub
frago chrome navigate https://github.com
sleep 3

# 开始录制
ffmpeg -f avfoundation -i "1:0" -t 10 shot_001.mp4 &
RECORD_PID=$!

# 执行页面操作
sleep 2
frago chrome scroll down 500
sleep 3

# 停止录制
wait $RECORD_PID

echo "录制完成: shot_001.mp4"
```

### 示例2: 带视觉效果的录制

```bash
#!/bin/bash
# shot_002_record.sh - 录制Notion产品页面（带视觉效果）

set -e

# 导航到Notion产品页
frago chrome navigate https://www.notion.so/product
sleep 3

# 开始录制
ffmpeg -f avfoundation -i "1:0" -t 15 shot_002.mp4 &
RECORD_PID=$!

# 添加视觉效果并执行操作
sleep 2

# 聚光灯效果
frago chrome spotlight ".hero-section" 3
sleep 3

# 高亮特性卡片
frago chrome highlight ".feature-card:nth-child(1)" --color "#FF6B6B" --duration 2
sleep 2

# 滚动页面
frago chrome scroll down 800 --smooth
sleep 2

# 添加标注
frago chrome annotate ".pricing-section" "灵活的定价方案" --position top
sleep 2

# 停止录制
wait $RECORD_PID

echo "录制完成: shot_002.mp4"
```

## 典型使用场景

### 场景1: 资讯深度分析

**主题**: "AI将如何改变教育行业 - 观点：个性化学习是核心"

**工作流程**:
1. AI收集相关网页和研究报告
2. AI设计论证结构（观点→论据→案例→结论）
3. 为每个论点创建分镜
4. 录制屏幕操作和数据展示
5. 合成最终视频

**分镜示例**:
```json
{
  "shot_id": "shot_001",
  "type": "browser_recording",
  "description": "展示传统教育的局限性",
  "actions": [
    {"action": "navigate", "url": "..."},
    {"action": "highlight", "selector": ".statistics"}
  ]
}
```

### 场景2: GitHub项目解析

**主题**: "分析 https://github.com/langchain-ai/langchain"

**工作流程**:
1. AI克隆仓库，分析代码结构
2. AI提取核心功能和架构亮点
3. 设计代码展示和功能演示分镜
4. 录制代码浏览和功能演示
5. 合成最终视频

**分镜示例**:
```json
{
  "shot_id": "shot_001",
  "type": "browser_recording",
  "description": "展示LangChain的核心架构",
  "actions": [
    {"action": "navigate", "url": "https://github.com/langchain-ai/langchain"},
    {"action": "spotlight", "selector": ".repository-content"}
  ]
}
```

### 场景3: 产品介绍

**主题**: "介绍 Notion 的核心功能"

**工作流程**:
1. AI浏览Notion官网和文档
2. AI规划功能演示顺序
3. 为每个核心功能创建演示分镜
4. 录制产品界面和功能操作
5. 合成最终视频

**分镜示例**:
```json
{
  "shot_id": "shot_001",
  "type": "browser_recording",
  "description": "演示Notion的页面编辑功能",
  "actions": [
    {"action": "navigate", "url": "https://www.notion.so/product"},
    {"action": "highlight", "selector": ".feature-editor"}
  ]
}
```

### 场景4: MVP开发演示

**主题**: "用React开发一个番茄钟应用"

**工作流程**:
1. AI规划MVP功能和技术栈
2. AI设计开发步骤
3. 为每个开发步骤创建录制分镜
4. 录制代码编写和功能实现
5. 合成最终视频

**分镜示例**:
```json
{
  "shot_id": "shot_001",
  "type": "code_recording",
  "description": "创建React项目并安装依赖",
  "actions": [
    {"action": "terminal", "command": "npx create-react-app pomodoro"},
    {"action": "highlight", "file": "package.json"}
  ]
}
```

## Recipe使用模式

### 模式1: 单次信息提取

```bash
# 提取YouTube字幕
uv run frago recipe run youtube_extract_video_transcript \
    --params '{"url": "https://youtube.com/watch?v=..."}' \
    --output-file transcript.txt
```

### 模式2: 批量数据收集

```bash
# 循环提取多个视频的字幕
for url in $(cat video_urls.txt); do
  uv run frago recipe run youtube_extract_video_transcript \
      --params "{\"url\": \"$url\"}" \
      --output-file "transcripts/$(basename $url).txt"
done
```

### 模式3: Pipeline集成

```bash
# 在Pipeline的prepare阶段使用Recipe
uv run frago recipe run youtube_extract_video_transcript \
    --params '{"url": "..."}' \
    --output-file research/video_transcript.txt

# 后续阶段可以读取这个文件
```

## 常见问题排查

### 问题1: Recipe执行失败

**症状**: Recipe运行时抛出异常

**排查步骤**:
1. 检查Chrome CDP是否正在运行（端口9222）
2. 验证Recipe元数据是否完整
3. 检查输入参数是否正确
4. 查看Recipe日志输出

### 问题2: 截图路径错误

**症状**: 截图保存失败或路径不正确

**解决方案**:
- 必须使用绝对路径
- 确保目标目录存在
- 检查文件写入权限

### 问题3: CDP连接超时

**症状**: CDP命令执行超时

**解决方案**:
- 检查Chrome是否以CDP模式启动
- 验证9222端口是否可访问
- 检查代理配置（如果使用代理）
- 增加超时时间（`--timeout`参数）
