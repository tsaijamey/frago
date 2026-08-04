---
name: openrouter_vision_classify
type: atomic
runtime: python
version: "1.1.0"
description: "通过 OpenRouter 的 chat/completions 端点调用多模态模型对图像做文本理解/分类（默认 google/gemini-2.5-flash-lite，便宜款），可强制返回 JSON。"
use_cases:
  - "对摄像头帧做视觉判断（如：有无人脸、是否儿童、情绪、性别）"
  - "对 UI 截图做语义识别，作为自动化流程的视觉感知节点"
  - "把任意图片 + prompt 交给便宜的多模态模型，得到结构化文本结果"
output_targets:
  - stdout
tags:
  - vision
  - openrouter
  - multimodal
  - classify
inputs:
  prompt:
    type: string
    required: true
    description: "对模型的指令，例如：判断图中是否有清晰人脸，并判断是否为儿童；以 JSON 输出 {has_face, is_child}"
  image_input:
    type: any
    required: true
    description: "图片输入：本地路径（自动 base64 编码）/ http(s) URL / data URL；支持字符串或字符串数组"
  model:
    type: string
    required: false
    description: "OpenRouter model ID，默认 google/gemini-2.5-flash-lite；也可填 google/gemini-2.5-flash / qwen/qwen-2.5-vl-7b-instruct 等"
  response_format:
    type: string
    required: false
    description: "传 'json' 时要求模型只输出 JSON 对象（启用 OpenRouter response_format=json_object），脚本会尝试解析；默认不限制"
  temperature:
    type: number
    required: false
    description: "采样温度，默认 0.2（分类任务希望稳定）"
  max_tokens:
    type: number
    required: false
    description: "最大输出 token 数，默认 256"
  reasoning_enabled:
    type: boolean
    required: false
    description: "显式开关模型的推理段。推理型模型（如 qwen/qwen3.7-flash）默认会先烧掉大量 reasoning token，正文常常撞上 max_tokens 返回空 content；描述/分类任务传 false 关掉即可。不传则沿用模型自身默认"
  retries:
    type: number
    required: false
    description: "限流(429)/网关故障/网络抖动时的重试次数，默认 2，退避 1.5s、3s。参数错、鉴权错不重试"
outputs:
  success:
    type: boolean
  raw_text:
    type: string
    description: "模型回复的原始文本"
  parsed_json:
    type: object
    description: "当 response_format=json 且解析成功时填充"
  model:
    type: string
  usage:
    type: object
  error:
    type: string
secrets:
  api_key:
    type: string
    required: true
    description: "OpenRouter API Key（在 ~/.frago/recipes.local.json 的 openrouter_vision_classify.api_key 配置；可用与 openrouter_gpt_image 相同的 OpenRouter Key）"
dependencies: []
---

# openrouter_vision_classify

通过 OpenRouter chat/completions 调多模态模型做图像理解：传入一张或多张图 + 一段 prompt，模型返回文本（可强制 JSON）。

## 调用示例

判断摄像头帧中是否有儿童：

```
frago recipe run openrouter_vision_classify --params '{
  "prompt": "看这张照片，判断画面中是否有清晰可见的人脸，以及该人是否为儿童（约 12 岁以下）。仅以 JSON 输出，键为 has_face(bool), is_child(bool)。",
  "image_input": "/path/to/frame.jpg",
  "response_format": "json"
}'
```

## 密钥配置

在 `~/.frago/recipes.local.json` 加入：

```json
{
  "openrouter_vision_classify": {
    "api_key": "sk-or-..."
  }
}
```

可与 `openrouter_gpt_image` 共用同一个 OpenRouter Key。

## 模型选择

- 默认 `google/gemini-2.5-flash-lite`：OpenRouter 上多模态便宜款，适合高频低延迟场景（如摄像头轮询判断）
- 更准 `google/gemini-2.5-flash`：略贵但更稳
- 国产 `qwen/qwen-2.5-vl-7b-instruct`：另一便宜选项
- 详述截图用 `qwen/qwen3.7-flash`：中文界面描述质量好，但**必须传 `reasoning_enabled: false`**，否则推理段吃光 max_tokens 返回空串；实测 594×858 截图出 500 token 描述约 20 秒，共享额度池 429 常见，靠 `retries` 兜

## 限流与推理段

免费/共享池上的多模态模型（qwen 系尤甚）会被上游按池限流，单次调用实测约一半概率吃 429。脚本默认重试 2 次、退避 1.5s 和 3s；参数错和鉴权错不重试，立刻报错。

推理型模型不传 `reasoning_enabled: false` 时，`max_tokens` 会被 reasoning token 吃掉，`raw_text` 返回空字符串——看起来像模型没读懂图，其实是正文还没开始写就没配额了。
