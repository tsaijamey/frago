---
name: doubao_seedream_image
type: workflow
runtime: python
version: "1.1.1"
created_at: "2026-04-19T11:15:47+08:00"
updated_at: "2026-08-21T15:20:00+08:00"
description: "调用火山方舟 Doubao Seedream 5.0 图像生成模型（同步接口），支持文生图与图生图（参考图角色一致性），生成图片并下载到本地"
use_cases:
  - "文生图：根据 prompt 同步生成图片并落盘"
  - "图生图：传入参考图（本地路径/URL），保持角色一致性生成新图"
  - "产品素材批量生成：指定分辨率和文件名，快速生产图像资产"
output_targets:
  - stdout
  - file
tags:
  - image-generation
  - doubao
  - ark
  - seedream
  - volcengine
inputs:
  prompt:
    type: string
    required: true
    description: "文本提示词"
  model:
    type: string
    required: false
    description: "Doubao Seedream model ID，默认 doubao-seedream-5-0-lite（Agent Plan 通道唯一支持的 seedream 模型；5.0 正式版在 plan 通道报 UnsupportedModel）"
  image:
    type: array
    required: false
    description: "图生图参考图数组：元素为本地文件路径 / URL / data URI，单图也传数组；本地文件自动转 base64 data URI 上传"
  size:
    type: string
    required: false
    description: "图像分辨率，默认 '2K'（可选 1K/2K/4K 等，透传给 API）"
  sequential_image_generation:
    type: string
    required: false
    description: "多图生成模式，默认 'disabled'（可选 auto）"
  watermark:
    type: boolean
    required: false
    description: "是否添加水印，默认 false"
  response_format:
    type: string
    required: false
    description: "API 响应格式，默认 'url'（可选 b64_json）"
  output_dir:
    type: string
    required: true
    description: "图片保存目录"
  filename:
    type: string
    required: false
    description: "保存文件名（不含扩展名），默认使用 timestamp"
outputs:
  success:
    type: boolean
    description: "是否成功"
  image_path:
    type: string
    description: "本地图片文件路径"
  image_url:
    type: string
    description: "API 返回的图片 URL"
  size:
    type: string
    description: "使用的分辨率"
  prompt:
    type: string
    description: "本次使用的 prompt"
  metadata_file:
    type: string
    description: "元数据 JSON 文件路径"
  usage:
    type: object
    description: "token 消耗统计（如有）"
  error:
    type: string
    description: "失败原因"
secrets:
  api_key:
    type: string
    required: true
    description: "火山方舟 API Key。Web UI 的 Recipe Secrets 面板填，或手写 ~/.frago/recipes.local.json 的 doubao_seedream_image.api_key"
  base_url:
    type: string
    required: false
    description: "端点，必须与 api_key 所属通道一致。Agent Plan 的 key 填 https://ark.cn-beijing.volces.com/api/plan/v3；标准方舟的 key 留空走 /api/v3。填错通道的表现是 UnsupportedModel 或 401，不是「生成质量差」"
dependencies: []
flow:
  - step: 1
    action: "validate_and_build"
    description: "读取并校验参数，构造请求体"
  - step: 2
    action: "call_api"
    description: "POST /images/generations 同步调用，获取图片 URL"
  - step: 3
    action: "download_image"
    description: "下载图片到 output_dir/filename"
  - step: 4
    action: "persist_metadata"
    description: "写入元数据 JSON"
  - step: 5
    action: "emit_result"
    description: "stdout 输出结构化 JSON 结果"
---

# doubao_seedream_image

## 功能描述

调用火山方舟 Ark API 的 Doubao Seedream 5.0 图像生成模型。与 seedance 视频异步 task 机制不同，本接口为**同步调用**，直接返回图片 URL，脚本再将图片下载到本地。

## 使用方式

```bash
frago recipe run doubao_seedream_image --params '{
  "prompt": "一只橘猫在樱花树下，电影感光线",
  "size": "2K",
  "output_dir": "/tmp/seedream_test"
}'
```

## 前置条件：配置火山方舟密钥

密钥走 frago 统一的 Recipe Secrets 通道，配方自己 NEVER 读环境变量、NEVER 落盘明文：
runner 从 `~/.frago/recipes.local.json` 按本配方名取值，照上面 `secrets:` 声明过滤后，
以 `FRAGO_SECRETS` 注入子进程。所以密钥只存在于你自己机器上的那一个文件里。

两种填法二选一。**Web UI**：`frago server start` 后打开设置里的 Recipe Secrets 面板，
选 `doubao_seedream_image`，字段就是上面声明的 `api_key` / `base_url`。
**手写** `~/.frago/recipes.local.json`：

```json
{
  "doubao_seedream_image": {
    "api_key": "你的火山方舟 API Key",
    "base_url": "https://ark.cn-beijing.volces.com/api/plan/v3"
  }
}
```

**端点必须跟着 key 走，这是最容易踩的一脚**：

| 你手上的 key | `base_url` 怎么填 | 可用模型 |
|---|---|---|
| 火山方舟 Agent Plan（订阅制） | `https://ark.cn-beijing.volces.com/api/plan/v3` | 只有 `doubao-seedream-5-0-lite`，也就是本配方默认值 |
| 标准方舟 API Key（按量计费） | 留空，走默认 `https://ark.cn-beijing.volces.com/api/v3` | 含 seedream 5.0 正式版在内的全系 |

配错的表现不是「图不好看」而是直接报错：plan 通道点名 5.0 正式版会回 `UnsupportedModel`，
拿 plan 的 key 打标准端点（或反过来）会回 401。看到这两个错先回来查这张表，别去调提示词。

密钥去哪申请：火山引擎控制台 → 火山方舟 → API Key 管理，并确认账号已开通 Seedream 图像生成模型。

除密钥外，只要求 `output_dir` 所在文件系统可写。

## 预期输出

stdout 输出结构化 JSON，包含 `success`、`image_path`、`image_url`、`size`、`prompt`、`metadata_file`、`usage`、`error` 字段。

## 注意事项

- 默认关闭水印（`watermark: false`）以便用于生产素材
- 默认 `response_format: url`；若传 `b64_json`，当前实现不支持直接解码保存（保留给后续版本）
- 单次请求默认 HTTP 超时 120s

## 更新历史

- 1.1.1 (2026-08-21): 补齐密钥配置说明——端点必须与 key 所属通道一致（Agent Plan `/api/plan/v3` vs 标准 `/api/v3`），配错直接报 UnsupportedModel / 401
- 1.1.0 (2026-07-09): 新增可选 `image` 参数支持图生图（本地路径自动转 base64 data URI）；元数据中 base64 原文做摘要化处理
- 1.0.0 (2026-04-19): 初始版本
