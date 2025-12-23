#!/bin/bash
# TTS Generation and Script Backfill Example

# === Step 1: Generate audio for a single segment ===
uv run frago recipe run volcengine_tts_voice_clone \
  --params '{"text": "Today let'\''s look at the discussion on Twitter", "output_file": "outputs/audio/seg_001.mp3"}'

# Return example: {"duration": 3.2, "file": "outputs/audio/seg_001.mp3"}

# === Step 2: Batch generate audio for all narrations ===
# Assuming narrations.json contains:
# [
#   {"segment_id": "seg_001", "text": "Today let's look at the discussion on Twitter"},
#   {"segment_id": "seg_002", "text": "Some people think this is a good thing"}
# ]

# Iterate and generate
cat outputs/narrations.json | jq -c '.[]' | while read line; do
  seg_id=$(echo $line | jq -r '.segment_id')
  text=$(echo $line | jq -r '.text')

  uv run frago recipe run volcengine_tts_voice_clone \
    --params "{\"text\": \"$text\", \"output_file\": \"outputs/audio/${seg_id}.mp3\"}"
done

# === Step 3: Get audio duration ===
# Use ffprobe to get precise duration
ffprobe -v quiet -show_entries format=duration -of csv=p=0 outputs/audio/seg_001.mp3
# Output: 3.216000

# === Step 4: Call video production ===
uv run frago recipe run video_produce_from_script \
  --params '{
    "script_file": "outputs/video_script.json",
    "output_dir": "outputs/video"
  }'
