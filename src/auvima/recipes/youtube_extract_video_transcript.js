/**
 * Recipe: youtube_extract_video_transcript
 * Platform: youtube
 * Description: 提取YouTube视频的"内容转文字"功能显示的完整字幕转录文本（时间戳+文字）
 * Created: 2025-11-19
 * Version: 1
 */

(async function() {
  // 辅助函数：按优先级尝试多个选择器
  function findElement(selectors, description) {
    for (const sel of selectors) {
      const elem = document.querySelector(sel.selector);
      if (elem) return elem;
    }
    throw new Error(`无法找到${description}`);
  }

  // 步骤1: 点击视频描述区域展开
  const descExpander = findElement([
    { selector: '#description-inline-expander', priority: 4 },  // 稳定ID
    { selector: 'tp-yt-paper-button#expand', priority: 4 }      // 降级：另一个可能的ID
  ], '视频描述展开按钮');
  descExpander.click();
  await new Promise(r => setTimeout(r, 500));  // 等待描述区域展开

  // 步骤2: 点击"内容转文字"按钮
  const transcriptBtn = findElement([
    { selector: '[aria-label="内容转文字"]', priority: 5 },     // ARIA标签（中文界面）
    { selector: 'button:has-text("内容转文字")', priority: 3 } // 降级：文本内容匹配
  ], '"内容转文字"按钮');
  transcriptBtn.click();
  await new Promise(r => setTimeout(r, 1500));  // 等待转录内容加载（至少1秒）

  // 步骤3: 提取所有时间戳+文字内容
  const segments = document.querySelectorAll('ytd-transcript-segment-renderer');
  if (segments.length === 0) {
    throw new Error('未找到转录内容片段，请确认视频包含字幕');
  }

  const transcript = [];
  for (const segment of segments) {
    const timestamp = segment.querySelector('.segment-timestamp')?.textContent.trim();
    const text = segment.querySelector('.segment-text')?.textContent.trim();

    if (timestamp && text) {
      transcript.push({
        timestamp: timestamp,
        text: text
      });
    }
  }

  // 返回格式化的结果
  return JSON.stringify({
    totalSegments: transcript.length,
    videoUrl: window.location.href,
    extractedAt: new Date().toISOString(),
    transcript: transcript
  }, null, 2);
})();
