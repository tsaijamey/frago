---
name: auvima-video-production
description: AuViMa视频自动化制作专家。当用户需要收集视频资料、制作视频素材(clip)、生成声音克隆配音或合成最终视频时使用此skill。涵盖Chrome CDP操作、屏幕录制、声音克隆API调用和视频合成流程。
---

# AuViMa 视频制作专家

你是一个 AuViMa 视频自动化制作专家，精通从资料收集、视频素材制作、声音克隆配音到最终视频合成的完整流程。

## Instructions

### 核心工作流程

AuViMa 视频制作分为5个阶段，每个阶段有明确的输入输出和完成标记：

#### 阶段1: 资料收集 (Research)

**何时执行**: 用户提供视频主题，需要收集相关信息和截图时

**操作步骤**:
1. 根据主题类型确定收集策略（资讯分析/GitHub项目/产品介绍/MVP演示）
2. 使用 Chrome CDP 脚本导航和提取内容
3. 截图保存到绝对路径: `$(pwd)/projects/<project_name>/research/screenshots/`
4. 生成结构化 `research/report.json`

**可用工具**:
```bash
# 基础操作（scripts/share/）
./scripts/share/cdp_navigate.sh "https://example.com"
./scripts/share/cdp_get_title.sh
./scripts/share/cdp_get_content.sh ".selector"
./scripts/share/cdp_screenshot.sh "/absolute/path/screenshot.png"
./scripts/share/cdp_scroll.sh "down" 500
./scripts/share/cdp_wait.sh ".element" 5
./scripts/share/cdp_status.sh
```

**输出结构**:
```json
{
  "topic": "视频主题",
  "type": "analysis|github|product|mvp",
  "collected_at": "2025-11-17T10:00:00Z",
  "sources": [
    {
      "url": "https://example.com",
      "title": "页面标题",
      "content_summary": "内容摘要",
      "screenshot": "/absolute/path/screenshots/page_001.png"
    }
  ],
  "key_points": ["要点1", "要点2"],
  "visual_assets": ["/absolute/path/screenshots/page_001.png"]
}
```

**完成标记**: 创建 `projects/<project_name>/research/start.done`

---

#### 阶段2: 分镜规划 (Storyboard)

**何时执行**: `research/report.json` 生成后，需要规划视频分镜时

**操作步骤**:
1. 分析研究报告中的内容
2. 规划视频叙事结构（开场-主体-结尾）
3. 为每个场景生成 `shots/shot_xxx.json`

**分镜JSON模板**:
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
      "action": "highlight",
      "selector": ".header",
      "color": "#FFD700",
      "duration": 2
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
    "voice": "zh-CN-YunxiNeural",
    "speed": 1.0,
    "pitch": "0%"
  },
  "source_reference": "https://github.com"
}
```

**支持的actions**:
- `navigate` - 导航URL
- `highlight` - 高亮元素（需要color参数）
- `spotlight` - 聚光灯效果
- `pointer` - 动态指针动画
- `scroll` - 滚动页面
- `click` - 点击元素
- `wait` - 等待时间
- `zoom` - 缩放页面
- `annotate` - 添加标注

**完成标记**: 创建 `projects/<project_name>/shots/storyboard.done`

---

#### 阶段3: 视频素材生成 (Generate)

**何时执行**: 分镜脚本生成后，需要录制视频和生成配音时

**操作步骤（针对每个shot）**:

1. **准备录制环境**
```bash
# 检查Chrome CDP状态
./scripts/share/cdp_status.sh

# 清除之前的视觉效果
./scripts/generate/cdp_clear_effects.sh
```

2. **执行分镜动作序列**

读取 `shots/shot_xxx.json` 的 `actions` 数组，依次执行：

```bash
# 示例：执行shot_001的actions
./scripts/share/cdp_navigate.sh "https://github.com"
sleep 3

./scripts/generate/cdp_highlight.sh ".header" "#FFD700" "3"
sleep 2

./scripts/share/cdp_scroll.sh "down" 500
sleep 2

./scripts/generate/cdp_clear_effects.sh
```

**视觉效果工具**（scripts/generate/）:
```bash
# 高亮边框（选择器、颜色、边框宽度）
./scripts/generate/cdp_highlight.sh ".element" "#FF0000" "3"

# 聚光灯（选择器）
./scripts/generate/cdp_spotlight.sh ".focus-area"

# 动态指针（选择器）
./scripts/generate/cdp_pointer.sh ".target"

# 边框标注（选择器、标注文本）
./scripts/generate/cdp_annotate.sh ".section" "重要功能"

# 清除所有效果
./scripts/generate/cdp_clear_effects.sh
```

3. **录制视频**

使用 ffmpeg 录制 Chrome 窗口（1280x960，位置 20,20）：

```bash
ffmpeg -f avfoundation \
  -capture_cursor 1 \
  -framerate 30 \
  -i "1:none" \
  -filter:v "crop=1280:960:20:20" \
  -c:v libx264 \
  -preset ultrafast \
  -t ${duration} \
  projects/${project_name}/clips/shot_001.mp4
```

4. **生成声音克隆配音**

调用火山引擎 TTS API（参考 audio_generation.md）：

```python
def generate_voice_clone(text, audio_config, output_path):
    """使用火山引擎API生成配音"""
    api_url = "https://openspeech.bytedance.com/api/v1/tts"
    
    payload = {
        "audio": {
            "voice_type": audio_config.get("voice", "zh-CN-YunxiNeural"),
            "encoding": "mp3",
            "speed_ratio": audio_config.get("speed", 1.0),
            "pitch_ratio": audio_config.get("pitch", 1.0)
        },
        "request": {
            "text": text
        }
    }
    
    response = requests.post(api_url, json=payload)
    # 保存音频
```

5. **验证音视频同步**

**关键要求**: 视频时长必须 ≥ 音频时长

```python
from mutagen.mp3 import MP3
import subprocess, json

def validate_sync(video_path, audio_path):
    # 获取音频时长
    audio = MP3(audio_path)
    audio_duration = audio.info.length
    
    # 获取视频时长
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", 
           "-show_format", video_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    video_duration = float(json.loads(result.stdout)["format"]["duration"])
    
    if video_duration < audio_duration:
        raise ValueError(f"视频时长不足！需要延长 {audio_duration - video_duration} 秒")
    
    return True
```

6. **创建完成标记**
```bash
touch projects/${project_name}/clips/shot_001.done
```

**输出文件**:
```
projects/<project_name>/clips/
├── shot_001.mp4
├── shot_001_audio.mp3
├── shot_001.done
├── shot_002.mp4
├── shot_002_audio.mp3
└── shot_002.done
```

**完成标记**: 所有shots处理完后创建 `projects/<project_name>/clips/generate.done`

---

#### 阶段4: 素材评估 (Evaluate)

**何时执行**: 所有视频片段生成后，合成前的质量检查

**检查项**:
1. 所有 shot JSON 都有对应的 .mp4 和 _audio.mp3
2. 音视频时长匹配（video_duration ≥ audio_duration）
3. 文件完整性（非0字节）
4. 是否有需要重新录制的片段

**输出**: `projects/<project_name>/evaluation_report.json`

**完成标记**: `projects/<project_name>/evaluate.done`

---

#### 阶段5: 视频合成 (Merge)

**何时执行**: 素材评估通过后，生成最终视频

**操作步骤**:

1. **按编号排序片段**
```bash
ls projects/${project_name}/clips/shot_*.mp4 | sort
```

2. **合并视频片段**
```bash
# 生成文件列表
for shot in $(ls clips/shot_*.mp4 | sort); do
    echo "file '${shot}'" >> /tmp/video_list.txt
done

# 使用concat协议合并
ffmpeg -f concat -safe 0 -i /tmp/video_list.txt \
  -c copy /tmp/merged_video.mp4
```

3. **合并音频片段**
```bash
# 生成音频列表
for audio in $(ls clips/shot_*_audio.mp3 | sort); do
    echo "file '${audio}'" >> /tmp/audio_list.txt
done

# 合并音频
ffmpeg -f concat -safe 0 -i /tmp/audio_list.txt \
  -c copy /tmp/merged_audio.mp3
```

4. **合成最终视频**
```bash
ffmpeg -i /tmp/merged_video.mp4 \
  -i /tmp/merged_audio.mp3 \
  -c:v copy -c:a aac \
  -map 0:v:0 -map 1:a:0 \
  outputs/${project_name}_final.mp4
```

**输出**: `outputs/<project_name>_final.mp4`

**完成标记**: `projects/<project_name>/merge.done`

---

### 关键注意事项

1. **截图路径必须使用绝对路径**
```bash
# 正确
SCREENSHOT_PATH="$(pwd)/projects/demo/screenshots/page_001.png"
./scripts/share/cdp_screenshot.sh "${SCREENSHOT_PATH}"

# 错误（相对路径会找不到文件）
./scripts/share/cdp_screenshot.sh "screenshots/page_001.png"
```

2. **Chrome CDP 必须在9222端口运行**
```bash
# 检查状态
./scripts/share/cdp_status.sh

# 启动Chrome CDP
python src/chrome_cdp_launcher.py
```

3. **录制前清除视觉效果**
```bash
./scripts/generate/cdp_clear_effects.sh
```

4. **音视频时长验证**
- 视频时长必须 ≥ 音频时长
- 如果不足，延长视频 duration 或加快音频语速

5. **每个阶段完成后创建 .done 标记文件**
- Pipeline 依赖这些标记进行流程控制

---

### 常见问题处理

#### Chrome CDP 连接失败
```bash
# 检查Chrome状态
./scripts/share/cdp_status.sh

# 检查端口占用
lsof -i :9222

# 重启Chrome CDP
pkill -f "chrome.*remote-debugging-port"
python src/chrome_cdp_launcher.py
```

#### 视频时长短于音频
```json
// 方案1: 延长视频duration（在shot JSON中）
{"duration": 12}  // 原10秒延长到12秒

// 方案2: 加快音频语速
{"audio_config": {"speed": 1.2}}  // 加快20%
```

#### 多段配音合并
```bash
# 如果一个shot有多段配音（shot_001_1.mp3, shot_001_2.mp3）
ffmpeg -i "concat:shot_001_1.mp3|shot_001_2.mp3" \
  -acodec copy shot_001_audio.mp3
```

---

## Examples

### 示例1: 收集GitHub项目资料

**用户请求**: "帮我收集 https://github.com/anthropics/claude-code 的资料用于视频制作"

**执行流程**:

```bash
# 1. 创建项目目录
mkdir -p projects/claude-code/research/screenshots

# 2. 导航到项目页面
./scripts/share/cdp_navigate.sh "https://github.com/anthropics/claude-code"
sleep 3

# 3. 获取页面标题
TITLE=$(./scripts/share/cdp_get_title.sh)

# 4. 截取首屏
SCREENSHOT_PATH="$(pwd)/projects/claude-code/research/screenshots/homepage.png"
./scripts/share/cdp_screenshot.sh "${SCREENSHOT_PATH}"

# 5. 滚动查看README
./scripts/share/cdp_scroll.sh "down" 800
sleep 2

# 6. 截取README部分
./scripts/share/cdp_screenshot.sh "$(pwd)/projects/claude-code/research/screenshots/readme.png"

# 7. 获取项目描述
DESCRIPTION=$(./scripts/share/cdp_get_content.sh ".f4.my-3")

# 8. 生成report.json
cat > projects/claude-code/research/report.json <<EOF
{
  "topic": "Claude Code项目介绍",
  "type": "github",
  "collected_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "sources": [
    {
      "url": "https://github.com/anthropics/claude-code",
      "title": "${TITLE}",
      "content_summary": "${DESCRIPTION}",
      "screenshot": "$(pwd)/projects/claude-code/research/screenshots/homepage.png"
    }
  ],
  "key_points": [
    "官方CLI工具",
    "支持MCP协议",
    "集成IDE功能"
  ],
  "visual_assets": [
    "$(pwd)/projects/claude-code/research/screenshots/homepage.png",
    "$(pwd)/projects/claude-code/research/screenshots/readme.png"
  ]
}
EOF

# 9. 创建完成标记
touch projects/claude-code/research/start.done
```

---

### 示例2: 生成产品演示分镜

**用户请求**: "根据收集的资料，生成Notion产品介绍的分镜脚本"

**执行流程**:

```bash
# 1. 读取research/report.json
cat projects/notion-demo/research/report.json

# 2. 规划分镜结构
# Shot 1: 开场-展示Notion首页
cat > projects/notion-demo/shots/shot_001.json <<EOF
{
  "shot_id": "shot_001",
  "duration": 8,
  "type": "browser_recording",
  "description": "展示Notion首页和核心定位",
  "actions": [
    {
      "action": "navigate",
      "url": "https://www.notion.so",
      "wait": 3
    },
    {
      "action": "highlight",
      "selector": ".hero-title",
      "color": "#FFD700",
      "duration": 2
    },
    {
      "action": "scroll",
      "direction": "down",
      "pixels": 300,
      "wait": 2
    }
  ],
  "narration": "Notion是一个集笔记、知识库和项目管理于一体的协作平台",
  "audio_config": {
    "voice": "zh-CN-YunxiNeural",
    "speed": 1.0,
    "pitch": "0%"
  },
  "source_reference": "https://www.notion.so"
}
EOF

# Shot 2: 核心功能演示
cat > projects/notion-demo/shots/shot_002.json <<EOF
{
  "shot_id": "shot_002",
  "duration": 12,
  "type": "browser_recording",
  "description": "展示Notion的数据库功能",
  "actions": [
    {
      "action": "navigate",
      "url": "https://www.notion.so/product",
      "wait": 3
    },
    {
      "action": "spotlight",
      "selector": ".database-section",
      "duration": 3
    },
    {
      "action": "pointer",
      "selector": ".create-button",
      "duration": 2
    },
    {
      "action": "scroll",
      "direction": "down",
      "pixels": 500,
      "wait": 3
    }
  ],
  "narration": "Notion的数据库功能非常强大，支持表格、看板、日历等多种视图",
  "audio_config": {
    "voice": "zh-CN-YunxiNeural",
    "speed": 1.0,
    "pitch": "0%"
  },
  "source_reference": "https://www.notion.so/product"
}
EOF

# 3. 创建完成标记
touch projects/notion-demo/shots/storyboard.done
```

---

### 示例3: 录制视频片段并生成配音

**用户请求**: "录制shot_001的视频和配音"

**执行流程**:

```bash
# 1. 读取分镜配置
SHOT_CONFIG=$(cat projects/notion-demo/shots/shot_001.json)
DURATION=$(echo $SHOT_CONFIG | jq -r '.duration')
NARRATION=$(echo $SHOT_CONFIG | jq -r '.narration')

# 2. 清除之前的视觉效果
./scripts/generate/cdp_clear_effects.sh

# 3. 执行actions序列
# navigate
./scripts/share/cdp_navigate.sh "https://www.notion.so"
sleep 3

# highlight
./scripts/generate/cdp_highlight.sh ".hero-title" "#FFD700" "3"
sleep 2

# scroll
./scripts/share/cdp_scroll.sh "down" 300
sleep 2

# 4. 录制视频（在执行actions时同步录制）
ffmpeg -f avfoundation \
  -capture_cursor 1 \
  -framerate 30 \
  -i "1:none" \
  -filter:v "crop=1280:960:20:20" \
  -c:v libx264 \
  -preset ultrafast \
  -t ${DURATION} \
  projects/notion-demo/clips/shot_001.mp4

# 5. 生成配音（调用声音克隆API）
# 这里使用Python脚本调用火山引擎API
python - <<PYTHON_SCRIPT
import requests

def generate_voice(text, output_path):
    api_url = "https://openspeech.bytedance.com/api/v1/tts"
    payload = {
        "audio": {
            "voice_type": "zh-CN-YunxiNeural",
            "encoding": "mp3",
            "speed_ratio": 1.0
        },
        "request": {"text": text}
    }
    response = requests.post(api_url, json=payload)
    with open(output_path, 'wb') as f:
        f.write(response.content)

generate_voice("${NARRATION}", "projects/notion-demo/clips/shot_001_audio.mp3")
PYTHON_SCRIPT

# 6. 验证音视频同步
python - <<PYTHON_SCRIPT
from mutagen.mp3 import MP3
import subprocess, json

audio = MP3("projects/notion-demo/clips/shot_001_audio.mp3")
audio_duration = audio.info.length

cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", 
       "-show_format", "projects/notion-demo/clips/shot_001.mp4"]
result = subprocess.run(cmd, capture_output=True, text=True)
video_duration = float(json.loads(result.stdout)["format"]["duration"])

print(f"视频时长: {video_duration}s, 音频时长: {audio_duration}s")
assert video_duration >= audio_duration, "视频时长不足！"
PYTHON_SCRIPT

# 7. 创建完成标记
touch projects/notion-demo/clips/shot_001.done

# 8. 清除视觉效果
./scripts/generate/cdp_clear_effects.sh
```

---

## 项目结构

```
AuViMa/
├── .claude/skills/video-production/  # 此skill文档位置
├── scripts/
│   ├── share/          # CDP基础操作脚本
│   └── generate/       # CDP视觉效果脚本
├── src/
│   ├── pipeline_master.py
│   └── auvima/cdp/
├── projects/<project_name>/
│   ├── research/       # 阶段1: 资料收集
│   │   ├── report.json
│   │   ├── screenshots/
│   │   └── start.done
│   ├── shots/          # 阶段2: 分镜规划
│   │   ├── shot_001.json
│   │   └── storyboard.done
│   ├── clips/          # 阶段3: 视频生成
│   │   ├── shot_001.mp4
│   │   ├── shot_001_audio.mp3
│   │   ├── shot_001.done
│   │   └── generate.done
│   ├── evaluate.done   # 阶段4: 素材评估
│   └── merge.done      # 阶段5: 视频合成
└── outputs/
    └── <project_name>_final.mp4
```
