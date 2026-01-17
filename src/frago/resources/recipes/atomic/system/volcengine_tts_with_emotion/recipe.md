---
name: volcengine_tts_with_emotion
type: atomic
runtime: python
description: "使用火山引擎 ICL 2.0 声音克隆API生成带情感表达的语音，支持SSML和 [#语气] 标记"
use_cases:
  - "生成有声书配音（带情感语气）"
  - "AI角色对话配音（带语气控制）"
  - "视频旁白制作（带情绪变化）"
  - "数字人播报（高拟人度表现）"
  - "SSML精确控制发音（多音字、拼音标注）"
tags:
  - tts
  - volcengine
  - emotion
  - audio-generation
  - ssml
output_targets:
  - stdout
  - file
inputs:
  text:
    type: string
    required: true
    description: "要合成的文本，支持 [#语气]文本 格式、纯文本或SSML格式"
  speaker_id:
    type: string
    required: false
    description: "音色ID，不传则使用环境变量VOICE_ID"
  output_file:
    type: string
    required: false
    description: "输出音频文件路径，不指定则返回base64编码"
  output_format:
    type: string
    required: false
    default: "wav"
    description: "输出音频格式：wav/mp3/ogg_opus/pcm"
  sample_rate:
    type: number
    required: false
    default: 16000
    description: "采样率，可选8000/16000/22050/24000/32000/44100/48000"
  speech_rate:
    type: number
    required: false
    default: 0
    description: "语速，范围[-50,100]，100为2倍速，-50为0.5倍速"
  silence_duration:
    type: number
    required: false
    default: 0
    description: "句尾静音时长（毫秒）"
outputs:
  success:
    type: boolean
    description: "是否成功"
  audio_file:
    type: string
    description: "生成的音频文件路径（如果指定了output_file）"
  audio_base64:
    type: string
    description: "音频的base64编码（如果没指定output_file）"
  duration_ms:
    type: number
    description: "估算的音频时长（毫秒）"
  text_length:
    type: number
    description: "文本字符数"
  emotion_context:
    type: string
    description: "解析出的语气描述（如果文本包含 [#语气] 标记）"
env:
  X_APP_ID:
    required: true
    description: "火山引擎 App ID，从 ~/.frago/.env 自动加载"
  X_ACCESS_TOKEN:
    required: true
    description: "火山引擎 Access Token，从 ~/.frago/.env 自动加载"
  VOICE_ID:
    required: false
    description: "默认音色ID，可通过 speaker_id 参数覆盖"
dependencies: []
version: "3.0.0"
---

# volcengine_tts_with_emotion

## 功能描述

调用火山引擎 ICL 2.0 声音克隆API（V3 HTTP单向流式接口）生成带情感表达的语音。

**支持三种文本格式**：

1. **语气标记**：`[#语气描述]文本内容` - 自动解析语气，传递给 `context_texts`
2. **纯文本**：直接输入文字
3. **SSML**：使用 `<speak>` 标签精确控制发音（多音字、拼音标注等）

**语气标记示例**：
```
[#用兴奋激动的语气说]太棒了！我们成功了！
[#用特别痛心的语气说]这太遗憾了
[#低沉沙哑]你好，老朋友
```

**SSML 示例**：
```xml
<speak>《<phoneme alphabet="py" ph="xi1 xi1">茜茜</phoneme>公主》是奥地利电影</speak>
```

## 使用方法

**带语气控制**（推荐）：
```bash
uv run frago recipe run volcengine_tts_with_emotion \
  --params '{
    "text": "[#用兴奋激动的语气说]太棒了！我们成功了！",
    "output_file": "output.wav"
  }'
```

**纯文本**：
```bash
uv run frago recipe run volcengine_tts_with_emotion \
  --params '{
    "text": "你好，很高兴认识你。",
    "output_file": "output.wav"
  }'
```

**SSML 精确控制发音**：
```bash
uv run frago recipe run volcengine_tts_with_emotion \
  --params '{
    "text": "<speak>《<phoneme alphabet=\"py\" ph=\"xi1 xi1\">茜茜</phoneme>公主》</speak>",
    "output_file": "output.wav"
  }'
```

**直接执行**：
```bash
uv run python examples/atomic/system/volcengine_tts_with_emotion/recipe.py '{
  "text": "[#用兴奋激动的语气说]太棒了！我们成功了！",
  "output_file": "/tmp/hello.wav"
}'
```

## 前置条件

1. **环境变量配置**（在 `.env` 文件中）：
   ```bash
   # 火山引擎凭证
   X_APP_ID=your_app_id
   X_ACCESS_TOKEN=your_access_token

   # 声音克隆音色ID
   VOICE_ID=your_cloned_voice_id
   ```

2. **声音克隆音色准备**：
   - 在火山引擎控制台上传训练音频
   - 获取训练后的 `speaker_id`

## 预期输出

成功时（带语气控制）：
```json
{
  "success": true,
  "audio_file": "/tmp/output.wav",
  "text_length": 10,
  "duration_ms": 3418,
  "format": "wav",
  "sample_rate": 16000,
  "emotion_context": "用兴奋激动的语气说"
}
```

失败时：
```json
{
  "success": false,
  "error": "缺少环境变量: X_APP_ID"
}
```

## 注意事项

- **API 接口**：使用 `seed-icl-2.0` 声音克隆接口
- **语气控制**：`[#语气]` 格式会自动解析，语气描述传递给 `context_texts` 参数
- **SSML 支持**：可使用 `<phoneme>` 标签精确控制多音字发音
- **流式返回**：API返回流式JSON，每行包含一段base64音频
- **默认格式**：WAV, 16-bit PCM, mono, 16kHz

## 更新历史

| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-29 | v3.0.0 | 添加 [#语气] 自动解析，context_texts 语气控制 |
| 2025-11-28 | v2.0.0 | 切换到 ICL 2.0 接口，添加 SSML 支持，默认 wav 格式 |
| 2025-11-28 | v1.0.0 | 初始版本 |
