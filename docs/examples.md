[简体中文](examples.zh-CN.md)

# Frago Example Reference

## Storyboard JSON Examples

### Basic Storyboard Structure

```json
{
  "shot_id": "shot_001",
  "duration": 10,
  "type": "browser_recording",
  "description": "Show GitHub homepage",
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
  "narration": "GitHub is the world's largest code hosting platform...",
  "audio_config": {
    "voice": "default",
    "speed": 1.0
  },
  "source_reference": "https://github.com/about"
}
```

### Complete Storyboard Example (with Visual Effects)

```json
{
  "shot_id": "shot_002",
  "duration": 15,
  "type": "browser_recording",
  "description": "Demonstrate Notion core features",
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
      "text": "Flexible pricing plans",
      "position": "top",
      "wait": 2
    }
  ],
  "narration": "Notion offers powerful page editing capabilities, supports various content types, and has flexible pricing plans...",
  "audio_config": {
    "voice": "zh-CN-XiaoxiaoNeural",
    "speed": 1.0,
    "pitch": 1.0
  },
  "source_reference": "https://www.notion.so/product"
}
```

## Recipe Script Examples

### Example 1: YouTube Subtitle Extraction

**Script File**: `youtube_extract_video_transcript.js`

```javascript
// Extract complete YouTube video subtitles
(async () => {
  // Click "Show full transcript" button
  const transcriptButton = document.querySelector('button[aria-label*="transcript"]');
  if (transcriptButton) {
    transcriptButton.click();
    await new Promise(resolve => setTimeout(resolve, 1000));
  }

  // Extract subtitle text
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

**Metadata File**: `youtube_extract_video_transcript.md`

```yaml
---
name: youtube_extract_video_transcript
type: atomic
runtime: chrome-js
version: "1.0"
description: "Extract complete YouTube video subtitles"
use_cases: ["Video content analysis", "Subtitle download", "Text summary"]
tags: ["youtube", "transcript", "web-scraping"]
output_targets: [stdout, file]
inputs:
  url:
    type: string
    description: "YouTube video URL"
    required: true
outputs:
  transcript:
    type: string
    description: "Complete subtitle text"
  segmentCount:
    type: integer
    description: "Number of subtitle segments"
---

# Function Description

Extract complete subtitle text from YouTube video page.

## Usage

```bash
uv run frago recipe run youtube_extract_video_transcript \
    --params '{"url": "https://youtube.com/watch?v=..."}' \
    --output-file transcript.txt
```

## Prerequisites

- Chrome launched via CDP (port 9222)
- Navigated to YouTube video page
- Video must have subtitles available

## Expected Output

Returns JSON format:
```json
{
  "transcript": "Complete subtitle text...",
  "segmentCount": 150
}
```

## Notes

- Must click "Show subtitles" button first
- Some videos may not have subtitles
- Recommended to wait for page to fully load before executing

## Update History

- v1.0 (2025-01-15): Initial version
```

### Example 2: Page Diagnostic Tool

**Script File**: `test_inspect_tab.js`

```javascript
// Get current tab diagnostic information
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

**Metadata File**: `test_inspect_tab.md`

```yaml
---
name: test_inspect_tab
type: atomic
runtime: chrome-js
version: "1.0"
description: "Get current tab diagnostic information (title, URL, DOM stats)"
use_cases: ["Page debugging", "Performance analysis", "DOM structure checking"]
tags: ["debug", "diagnostic", "page-info"]
output_targets: [stdout]
inputs: {}
outputs:
  pageInfo:
    type: object
    description: "Page diagnostic information"
---

# Function Description

Get diagnostic information for current tab, including title, URL, DOM statistics, and performance data.

## Usage

```bash
uv run frago recipe run test_inspect_tab
```

## Prerequisites

- Chrome launched via CDP (port 9222)
- Navigated to target page

## Expected Output

```json
{
  "title": "Page title",
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

## Notes

- Recommended to execute after page fully loads
- Performance data may be 0 (if page still loading)

## Update History

- v1.0 (2025-01-15): Initial version
```

## Recording Script Examples

### Example 1: Simple Page Recording

```bash
#!/bin/bash
# shot_001_record.sh - Record GitHub homepage

set -e

# Navigate to GitHub
uv run frago navigate https://github.com
sleep 3

# Start recording
ffmpeg -f avfoundation -i "1:0" -t 10 shot_001.mp4 &
RECORD_PID=$!

# Execute page operations
sleep 2
uv run frago scroll down 500
sleep 3

# Stop recording
wait $RECORD_PID

echo "Recording completed: shot_001.mp4"
```

### Example 2: Recording with Visual Effects

```bash
#!/bin/bash
# shot_002_record.sh - Record Notion product page (with visual effects)

set -e

# Navigate to Notion product page
uv run frago navigate https://www.notion.so/product
sleep 3

# Start recording
ffmpeg -f avfoundation -i "1:0" -t 15 shot_002.mp4 &
RECORD_PID=$!

# Add visual effects and execute operations
sleep 2

# Spotlight effect
uv run frago spotlight ".hero-section" 3
sleep 3

# Highlight feature card
uv run frago highlight ".feature-card:nth-child(1)" --color "#FF6B6B" --duration 2
sleep 2

# Scroll page
uv run frago scroll down 800 --smooth
sleep 2

# Add annotation
uv run frago annotate ".pricing-section" "Flexible pricing plans" --position top
sleep 2

# Stop recording
wait $RECORD_PID

echo "Recording completed: shot_002.mp4"
```

## Typical Use Scenarios

### Scenario 1: In-Depth News Analysis

**Topic**: "How AI Will Change Education Industry - Opinion: Personalized Learning is Key"

**Workflow**:
1. AI collects relevant webpages and research reports
2. AI designs argument structure (viewpoint→evidence→cases→conclusion)
3. Create storyboard for each argument
4. Record screen operations and data displays
5. Synthesize final video

**Storyboard Example**:
```json
{
  "shot_id": "shot_001",
  "type": "browser_recording",
  "description": "Show limitations of traditional education",
  "actions": [
    {"action": "navigate", "url": "..."},
    {"action": "highlight", "selector": ".statistics"}
  ]
}
```

### Scenario 2: GitHub Project Analysis

**Topic**: "Analyze https://github.com/langchain-ai/langchain"

**Workflow**:
1. AI clones repository, analyzes code structure
2. AI extracts core features and architectural highlights
3. Design code display and feature demo storyboard
4. Record code browsing and feature demos
5. Synthesize final video

**Storyboard Example**:
```json
{
  "shot_id": "shot_001",
  "type": "browser_recording",
  "description": "Show LangChain core architecture",
  "actions": [
    {"action": "navigate", "url": "https://github.com/langchain-ai/langchain"},
    {"action": "spotlight", "selector": ".repository-content"}
  ]
}
```

### Scenario 3: Product Introduction

**Topic**: "Introduce Notion's Core Features"

**Workflow**:
1. AI browses Notion official site and documentation
2. AI plans feature demo sequence
3. Create demo storyboard for each core feature
4. Record product interface and feature operations
5. Synthesize final video

**Storyboard Example**:
```json
{
  "shot_id": "shot_001",
  "type": "browser_recording",
  "description": "Demo Notion's page editing features",
  "actions": [
    {"action": "navigate", "url": "https://www.notion.so/product"},
    {"action": "highlight", "selector": ".feature-editor"}
  ]
}
```

### Scenario 4: MVP Development Demo

**Topic**: "Develop a Pomodoro Timer App with React"

**Workflow**:
1. AI plans MVP features and tech stack
2. AI designs development steps
3. Create recording storyboard for each development step
4. Record code writing and feature implementation
5. Synthesize final video

**Storyboard Example**:
```json
{
  "shot_id": "shot_001",
  "type": "code_recording",
  "description": "Create React project and install dependencies",
  "actions": [
    {"action": "terminal", "command": "npx create-react-app pomodoro"},
    {"action": "highlight", "file": "package.json"}
  ]
}
```

## Recipe Usage Patterns

### Pattern 1: Single Information Extraction

```bash
# Extract YouTube subtitles
uv run frago recipe run youtube_extract_video_transcript \
    --params '{"url": "https://youtube.com/watch?v=..."}' \
    --output-file transcript.txt
```

### Pattern 2: Batch Data Collection

```bash
# Loop extract subtitles from multiple videos
for url in $(cat video_urls.txt); do
  uv run frago recipe run youtube_extract_video_transcript \
      --params "{\"url\": \"$url\"}" \
      --output-file "transcripts/$(basename $url).txt"
done
```

### Pattern 3: Pipeline Integration

```bash
# Use Recipe in Pipeline's prepare phase
uv run frago recipe run youtube_extract_video_transcript \
    --params '{"url": "..."}' \
    --output-file research/video_transcript.txt

# Subsequent phases can read this file
```

## Common Problem Troubleshooting

### Problem 1: Recipe Execution Failed

**Symptom**: Recipe throws exception during execution

**Troubleshooting Steps**:
1. Check if Chrome CDP is running (port 9222)
2. Verify Recipe metadata is complete
3. Check input parameters are correct
4. Review Recipe log output

### Problem 2: Screenshot Path Error

**Symptom**: Screenshot save fails or path incorrect

**Solution**:
- Must use absolute path
- Ensure target directory exists
- Check file write permissions

### Problem 3: CDP Connection Timeout

**Symptom**: CDP command execution timeout

**Solution**:
- Check if Chrome launched in CDP mode
- Verify port 9222 is accessible
- Check proxy configuration (if using proxy)
- Increase timeout (`--timeout` parameter)
