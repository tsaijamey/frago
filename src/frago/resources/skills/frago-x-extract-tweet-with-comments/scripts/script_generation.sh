#!/bin/bash
# TTS 生成与脚本回填示例

# === Step 1: 生成单个 segment 的音频 ===
uv run frago recipe run volcengine_tts_voice_clone \
  --params '{"text": "今天我们来看看 Twitter 上的讨论", "output_file": "outputs/audio/seg_001.mp3"}'

# 返回示例: {"duration": 3.2, "file": "outputs/audio/seg_001.mp3"}

# === Step 2: 批量生成所有 narration 的音频 ===
# 假设 narrations.json 包含:
# [
#   {"segment_id": "seg_001", "text": "今天我们来看看 Twitter 上的讨论"},
#   {"segment_id": "seg_002", "text": "有人认为这是一件好事"}
# ]

# 遍历生成
cat outputs/narrations.json | jq -c '.[]' | while read line; do
  seg_id=$(echo $line | jq -r '.segment_id')
  text=$(echo $line | jq -r '.text')

  uv run frago recipe run volcengine_tts_voice_clone \
    --params "{\"text\": \"$text\", \"output_file\": \"outputs/audio/${seg_id}.mp3\"}"
done

# === Step 3: 获取音频时长 ===
# 使用 ffprobe 获取精确时长
ffprobe -v quiet -show_entries format=duration -of csv=p=0 outputs/audio/seg_001.mp3
# 输出: 3.216000

# === Step 4: 调用视频生产 ===
uv run frago recipe run video_produce_from_script \
  --params '{
    "script_file": "outputs/video_script.json",
    "output_dir": "outputs/video"
  }'
