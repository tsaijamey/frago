#!/bin/bash
# Recipe 命令工作流示例
# 适用于: /frago.recipe（配方创建/更新）

# === 1. 查看现有配方 ===
frago recipe list
frago recipe info <recipe_name> --format json

# === 2. 探索步骤（带验证）===

# Step 2.1: 执行操作
frago chrome click '[aria-label="提交"]'

# Step 2.2: 等待
frago chrome wait 0.5

# Step 2.3: 验证结果
frago chrome screenshot /tmp/step1_result.png
# 或验证元素出现
frago chrome exec-js "document.querySelector('.success-message') !== null" --return-value

# === 3. 验证选择器 ===
# 检查选择器是否存在
frago chrome exec-js "document.querySelector('[aria-label=\"提交\"]') !== null" --return-value

# 高亮元素确认位置
frago chrome highlight '[aria-label="提交"]'

# 获取元素文本确认内容
frago chrome exec-js "document.querySelector('[aria-label=\"提交\"]')?.textContent" --return-value

# === 4. Atomic Recipe 目录结构 ===
# examples/atomic/chrome/<recipe_name>/
# ├── recipe.md      # 元数据 + 文档
# └── recipe.js      # 执行脚本

# === 5. Workflow Recipe 目录结构 ===
# examples/workflows/<workflow_name>/
# ├── recipe.md      # 元数据 + 文档
# ├── recipe.py      # 执行脚本
# └── examples/      # 示例数据（可选）

# === 6. 执行配方测试 ===
# 使用 Recipe 系统
frago recipe run <recipe_name>
frago recipe run <recipe_name> --output-file result.json

# 直接执行 chrome-js 配方
frago chrome exec-js examples/atomic/chrome/<recipe_name>/recipe.js --return-value

# === 7. 更新配方 ===
# 1. 查看配方位置
frago recipe info <recipe_name> --format json

# 2. 重新探索并更新文件
# 3. 更新版本号和更新历史
