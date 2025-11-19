# youtube_extract_video_transcript

## 功能描述

提取YouTube视频的"内容转文字"功能显示的完整转录文本（包括时间戳和对应文字）。

YouTube的"内容转文字"功能会将视频语音内容转换为带时间戳的文字片段，方便用户快速浏览和定位视频内容。此配方自动化了展开描述、点击"内容转文字"按钮、等待加载并提取所有转录片段的完整流程。

**适用场景**：
- 批量提取视频字幕内容用于文本分析
- 为视频创建索引或摘要
- 学习材料的文字化存档
- 无障碍访问支持

**重要限制**：此功能仅在视频语音语言与浏览器界面语言不同时出现。例如，中文界面下观看英文视频时才会显示"内容转文字"按钮。

## 使用方法

**配方执行器说明**：生成的配方本质上是JavaScript代码，通过CDP的Runtime.evaluate接口注入到浏览器中执行。因此，执行配方的标准方式是使用 `uv run auvima exec-js` 命令。

1. 在浏览器中打开目标YouTube视频页面（必须是长视频，不能是Shorts）
2. 确认浏览器界面语言与视频语音语言不同（例如中文界面+英文视频）
3. 执行配方：
   ```bash
   # 将配方JS文件内容作为脚本注入浏览器执行
   uv run auvima exec-js src/auvima/recipes/youtube_extract_video_transcript.js --return-value
   ```
4. 查看控制台输出的JSON格式转录文本

**注意**：AI调试时请记住，你生成的 `.js` 文件不是在 Node.js 环境中运行，而是在浏览器的上下文中运行（类似 Chrome Console）。因此：
- 不能使用 `require()` 或 `import`
- 可以直接使用 `document`, `window` 等浏览器 API
- `console.log` 的输出通常需要查看 `--return-value` 或浏览器控制台

## 前置条件

- Chrome CDP已连接（`uv run auvima status` 显示连接正常）
- 已打开YouTube长视频页面（非Shorts短视频）
- **关键**：浏览器界面语言与视频语音语言不同
  - 示例：中文界面 + 英文视频 ✅
  - 示例：中文界面 + 中文视频 ❌（不会显示"内容转文字"按钮）
- 视频包含可用的字幕或转录文本

## 预期输出

返回一个JSON对象，包含：
- `totalSegments`: 转录片段总数
- `videoUrl`: 当前视频URL
- `extractedAt`: 提取时间（ISO 8601格式）
- `transcript`: 转录数组，每个元素包含：
  - `timestamp`: 时间戳（格式如 "0:00", "1:23"）
  - `text`: 对应时间的文字内容

**示例输出**：
```json
{
  "totalSegments": 2270,
  "videoUrl": "https://www.youtube.com/watch?v=K5KVEU3aaeQ",
  "extractedAt": "2025-11-19T03:30:00.000Z",
  "transcript": [
    {
      "timestamp": "0:00",
      "text": "[Music] welcome to the complete python Mastery course..."
    },
    {
      "timestamp": "0:06",
      "text": "Basics to more advanced concepts so by the end..."
    }
  ]
}
```

## 注意事项

- **选择器稳定性**：使用了1个ARIA选择器（优先级5），1个ID选择器（优先级4），2个类选择器（优先级3）
- **脆弱选择器**：`.segment-timestamp` 和 `.segment-text` 是CSS类名，可能在YouTube改版后失效
- **界面语言要求**：配方中硬编码了中文ARIA标签 `[aria-label="内容转文字"]`。如果使用其他语言界面（如英文界面的 "Show transcript"），需要修改此选择器
- **加载时间**：转录内容较长的视频可能需要更长的加载时间，当前等待1.5秒。如果提取失败，可以增加等待时间
- **视频类型限制**：仅适用于长视频，YouTube Shorts不支持"内容转文字"功能
- 如果YouTube改版导致脚本失效，使用 `/auvima_recipe update youtube_extract_video_transcript` 更新

## 更新历史

| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-19 | v1 | 初始版本，支持中文界面提取英文视频转录文本 |
