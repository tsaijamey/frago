# /auvima.generate

单个视频片段的完整生产流程

## 用法
```
/auvima.generate <shot_json_file>
```

## 核心理念

每个clip的生产是一个**独立的创作过程**：
1. 分析分镜需求，理解要展示什么
2. 编写专属的录制脚本（一次性的）
3. 执行录制并监控过程
4. 验证产出质量
5. 标记完成状态

## 生产方法论

### 1. 脚本化录制策略

为每个clip创建专属脚本 `clips/shot_xxx_record.sh`：

```bash
#!/bin/bash
# Shot 001: 展示GitHub首页
# 预计时长：15秒

# 准备阶段（不录制）
uv run auvima navigate "https://github.com"
uv run auvima wait 3
sleep 2

# 开始录制标记
echo "$(date +%s)" > /tmp/record_start.time

# 启动录制（后台）
ffmpeg -f avfoundation \
       -framerate 30 \
       -i "1:0" \
       -t 20 \
       -vf "crop=1280:960:20:20" \
       clips/shot_001.mp4 &
FFMPEG_PID=$!

sleep 1  # 确保录制开始

# === 执行展示动作 ===
# 高亮重要元素（3秒）
uv run auvima spotlight ".Header-link"
sleep 3

# 滚动展示内容（5秒）
uv run auvima scroll --pixels 300 --direction down
sleep 2
uv run auvima scroll --pixels 300 --direction down
sleep 3

# 点击并展示功能（5秒）
uv run auvima click "a[href='/features']"
uv run auvima wait 5

# 清理效果（2秒）
uv run auvima clear-effects
sleep 2

# 结束录制
kill -SIGINT $FFMPEG_PID
wait $FFMPEG_PID

# 记录结束时间
echo "$(date +%s)" > /tmp/record_end.time

# 验证录制结果
if [ -f clips/shot_001.mp4 ]; then
    echo "✓ 录制完成"
else
    echo "✗ 录制失败"
    exit 1
fi
```

### 2. 时间控制原则

#### 开始录制的时机
- 页面/内容完全加载后
- 所有准备工作完成
- 添加1-2秒缓冲避免突兀开始

#### 动作时长控制
```bash
# 每个动作都要精确控制时长
uv run auvima highlight ".button"
sleep 3  # 保持高亮3秒

uv run auvima pointer "#submit-btn"
sleep 2  # 指针动画2秒

uv run auvima scroll --pixels 500 --direction down
sleep 1  # 滚动后停留1秒便于观看
```

#### 结束录制的时机
- 所有动作执行完毕
- 添加1-2秒尾部缓冲
- 确保不会截断正在进行的动画

### 3. 录制质量控制

#### 录制前检查
```bash
# 检查Chrome是否就绪
uv run auvima status

# 检查目标页面是否可访问
curl -I "$TARGET_URL"

# 清理之前的效果
uv run auvima clear-effects
```

#### 录制中监控
- 使用后台进程录制，前台执行动作
- 记录关键时间点
- 保持动作节奏流畅

#### 录制后验证
```bash
# 检查视频时长
DURATION=$(ffprobe -v error -show_entries format=duration \
           -of default=noprint_wrappers=1:nokey=1 \
           clips/shot_xxx.mp4)

# 提取关键帧检查
ffmpeg -i clips/shot_xxx.mp4 -vf "select='eq(n,0)+eq(n,150)+eq(n,300)'" \
       -vsync vfr clips/shot_xxx_frame_%d.jpg

# 使用VL模型检查关键帧内容（可选）
```

## 可用工具集

### 导航和内容工具
- `uv run auvima navigate <url>` - 导航到页面
- `uv run auvima wait <seconds>` - 等待指定秒数
- `uv run auvima scroll [--pixels <px>] [--direction <up/down>]` - 滚动页面
- `uv run auvima click <selector>` - 点击元素

### 视觉引导工具（录制时使用）
- `uv run auvima highlight <selector>` - 高亮边框
- `uv run auvima spotlight <selector>` - 聚光灯效果
- `uv run auvima annotate <selector> <text>` - 添加说明文字
- `uv run auvima pointer <selector>` - 模拟鼠标指向
- `uv run auvima zoom <factor>` - 设置页面缩放比例
- `uv run auvima clear-effects` - 清除所有效果

### 录制工具
```bash
# macOS屏幕录制（指定区域）
ffmpeg -f avfoundation \
       -framerate 30 \
       -i "1:0" \
       -vf "crop=1280:960:20:20" \
       -t <duration> \
       <output.mp4>

# 全屏录制
ffmpeg -f avfoundation \
       -framerate 30 \
       -i "1:0" \
       -t <duration> \
       <output.mp4>
```

## 音频生成

暂时生成占位音频，后续接入火山引擎API：
```bash
# 生成静音音频作为占位
ffmpeg -f lavfi -i anullsrc=r=44100:cl=stereo \
       -t <duration> \
       clips/shot_xxx_audio.mp3
```

## 输出文件结构

```
clips/
├── shot_001_record.sh      # 录制脚本（一次性）
├── shot_001.mp4           # 视频文件
├── shot_001_audio.mp3     # 音频文件
├── shot_001_metadata.json # 元数据
├── shot_001_frame_1.jpg   # 关键帧（用于验证）
├── shot_001_frame_2.jpg
├── shot_001_frame_3.jpg
└── shot_001.done          # 完成标记

```

## 执行流程

### 第1步：分析分镜需求
```json
{
  "shot_id": "shot_001",
  "duration": 15,
  "type": "browser_recording",
  "actions": [...],
  "narration": {...}
}
```
理解：要展示什么？时长多少？有哪些关键动作？

### 第2步：编写录制脚本
- 创建 `clips/shot_xxx_record.sh`
- 规划每个动作的时间点
- 设置录制参数

### 第3步：执行录制
```bash
chmod +x clips/shot_xxx_record.sh
./clips/shot_xxx_record.sh
```

### 第4步：质量验证
1. **时长检查**：确保视频时长符合预期
2. **关键帧检查**：提取3-5帧验证内容
3. **音频匹配**：确保视频时长 ≥ 音频时长

### 第5步：生成元数据
```json
{
  "shot_id": "shot_001",
  "created_at": "2024-11-14T22:00:00Z",
  "video_duration": 15.2,
  "audio_duration": 14.8,
  "script_iterations": 1,
  "quality_check": "passed"
}
```

### 第6步：创建完成标记
- 生成 `clips/shot_xxx.done`
- 当最后一个shot完成时，生成 `generate.done`

## 错误处理

### 脚本执行失败
1. 分析错误日志
2. **原地修改**脚本（不创建新文件）
3. 重新执行
4. 最多迭代3次

### 时长不匹配
- 视频过短：增加动作间隔或添加停留时间
- 视频过长：减少不必要的等待
- 音频过长：考虑加快动作节奏或延长视频

## 实现要点

1. **每个clip都是独立的创作**：不要批量处理，要精心制作
2. **脚本是一次性的**：针对具体内容定制，不追求复用
3. **时间控制要精确**：每个sleep都有其意义
4. **质量优先于速度**：宁可多迭代几次也要确保质量

## 完成标记
- 单个clip：`clips/shot_xxx.done`
- 全部完成：`generate.done`（项目根目录）