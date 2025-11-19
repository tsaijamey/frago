# /auvima.evaluate

素材评估阶段 - 检查所有生成的clips质量

## 用法
```
/auvima.evaluate [project_name]
```

## 前置条件
- 必须已完成所有clips生成
- `clips/` 目录包含所有视频和音频文件

## 核心任务

### 1. 完整性检查
- 验证每个shot都有对应的视频文件
- 验证每个shot都有对应的音频文件
- 检查是否有遗漏的分镜

### 2. 时长验证（最重要）
对每个clip执行：
```
视频时长(shot_xxx.mp4) >= 音频总时长(shot_xxx_audio.mp3 + shot_xxx_1.mp3 + ...)
```

如果发现问题：
- 记录到评估报告
- 标记需要重新生成的clips
- 提供具体的时长差异数据

### 3. 质量检查
- 视频文件是否可播放
- 音频文件是否可播放
- 文件大小是否异常（过小可能损坏）
- 编码格式是否一致

### 4. 连续性检查
- shot编号是否连续
- 是否有重复的shot_id
- 总时长是否在目标范围（3-5分钟）

## 评估报告格式

```json
{
  "evaluation_time": "2024-11-14T22:00:00Z",
  "total_shots": 10,
  "total_duration": 240,
  "issues": [
    {
      "shot_id": "shot_003",
      "issue_type": "duration_mismatch",
      "video_duration": 15.2,
      "audio_duration": 16.5,
      "difference": -1.3,
      "severity": "critical"
    }, # 只在真实存在质量问题时才有this part
  ],
  "summary": {
    "passed": 8,
    "failed": 2,
    "warnings": 1
  },
  "recommendation": "需要重新生成shot_003和shot_007"
}
```

## 输出文件

```
projects/<project_name>/
├── evaluation_report.json  # 详细评估报告
├── clips_manifest.json     # 所有clips清单
└── evaluate.done           # 完成标记（pipeline检测用）
```

## 处理策略

### 发现严重问题时
1. **音频长于视频**：
   - 标记为"critical"
   - 建议重新录制该clip
   - 或延长视频时长（添加静态画面）

2. **文件缺失**：
   - 标记为"critical"
   - 必须重新生成

3. **轻微时长差异**（<0.5秒）：
   - 标记为"warning"
   - 可以通过后期处理解决

## 使用工具

使用ffprobe获取精确时长：
```bash
ffprobe -v error -show_entries format=duration \
        -of default=noprint_wrappers=1:nokey=1 \
        <video_file>
```

## 完成标记

**必须**在评估完成后创建 `evaluate.done` 空文件，位于项目根目录。

## 决策输出

评估完成后，必须明确输出：
1. ✅ **可以继续合成** - 所有clips质量合格
2. ⚠️ **建议修复后合成** - 有轻微问题但可继续
3. ❌ **必须修复** - 有严重问题，不能合成

## 实现脚本
`scripts/auvima_evaluate.py` (待实现)