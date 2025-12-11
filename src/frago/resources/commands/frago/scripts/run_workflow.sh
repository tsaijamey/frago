#!/bin/bash
# Run 命令工作流示例
# 适用于: /frago.run（探索调研，为 Recipe 创建做准备）

# === 1. 检查现有项目 ===
frago run list --format json

# === 2. 创建新项目 ===
frago run init "nano-banana-pro image api research"
# 返回 project_id，假设为 nano-banana-pro-image-api-research

# === 3. 设置上下文 ===
frago run set-context nano-banana-pro-image-api-research

# === 4. 执行调研操作 ===
# 导航（自动记录日志）
frago chrome navigate "https://example.com"

# 提取页面链接
frago chrome exec-js "Array.from(document.querySelectorAll('a')).map(a => ({text: a.textContent.trim(), href: a.href})).filter(a => a.text)" --return-value

# 截图验证（自动记录日志）
frago chrome screenshot /tmp/step1.png

# === 5. 手动记录分析结果（含 _insights）===
frago run log \
  --step "分析API文档结构" \
  --status "success" \
  --action-type "analysis" \
  --execution-method "analysis" \
  --data '{
    "conclusion": "API 使用 REST 风格",
    "endpoints": ["/generate", "/status"],
    "_insights": [
      {"type": "key_factor", "summary": "需要 API Key 认证"}
    ]
  }'

# === 6. 记录失败和重试（必须记录 _insights）===
# 假设点击失败
frago chrome click '.api-key-btn'  # 失败

# 记录失败原因
frago run log \
  --step "分析点击失败原因" \
  --status "warning" \
  --action-type "analysis" \
  --execution-method "analysis" \
  --data '{
    "command": "frago chrome click .api-key-btn",
    "error": "Element not found",
    "_insights": [
      {"type": "pitfall", "summary": "动态class不可靠，需用data-testid"}
    ]
  }'

# === 7. 调研完成：生成 Recipe 草稿 ===
frago run log \
  --step "总结调研结论并生成 Recipe 草稿" \
  --status "success" \
  --action-type "analysis" \
  --execution-method "analysis" \
  --data '{
    "ready_for_recipe": true,
    "recipe_spec": {
      "name": "nano_banana_generate_image",
      "type": "atomic",
      "runtime": "chrome-js",
      "description": "使用 Nano Banana Pro 生成图片",
      "inputs": {
        "prompt": {"type": "string", "required": true}
      },
      "outputs": {
        "image_url": "string"
      },
      "key_steps": [
        "1. 输入 prompt",
        "2. 点击生成按钮",
        "3. 等待结果",
        "4. 提取图片 URL"
      ],
      "pitfalls_to_avoid": ["动态class不可靠"],
      "key_factors": ["需要 API Key 认证"]
    }
  }'

# === 8. 释放上下文（必须！）===
frago run release
