#!/bin/bash
# Do 命令工作流示例
# 适用于: /frago.do（一次性任务执行）

# === 1. 明确输出格式（如用户未指定，需先询问）===
# 使用 AskUserQuestion 工具确认输出格式：
# - 结构化数据（JSON/CSV）
# - 文档报告（Markdown/HTML）
# - 仅执行日志

# === 2. 创建项目 ===
frago run init "upwork python job apply"
frago run set-context upwork-python-job-apply

# === 3. 执行任务 ===
# 导航（自动记录）
frago chrome navigate "https://upwork.com/jobs"

# 搜索
frago chrome exec-js "document.querySelector('input[type=search]').value = 'Python'" --return-value
frago chrome click 'button[type=submit]'
frago chrome wait 2

# 提取数据
frago chrome exec-js "Array.from(document.querySelectorAll('.job-tile')).map(el => ({
  title: el.querySelector('.title')?.textContent,
  url: el.querySelector('a')?.href,
  rate: el.querySelector('.rate')?.textContent
}))" --return-value

# === 4. 使用 Recipe 加速重复操作 ===
frago recipe run upwork_extract_job_list --params '{"keyword": "Python"}' --output-file projects/upwork-python-job-apply/outputs/jobs.json

# 记录 Recipe 执行
frago run log \
  --step "提取Python职位列表" \
  --status "success" \
  --action-type "recipe_execution" \
  --execution-method "recipe" \
  --data '{"recipe_name": "upwork_extract_job_list", "output_file": "outputs/jobs.json"}'

# === 5. 数据处理（脚本文件）===
# 创建筛选脚本
cat > projects/upwork-python-job-apply/scripts/filter_jobs.py <<'EOF'
import json
jobs = json.load(open('outputs/jobs.json'))
filtered = [j for j in jobs if j.get('rate', 0) > 50]
json.dump(filtered, open('outputs/filtered_jobs.json', 'w'), indent=2)
print(f"筛选出 {len(filtered)} 个高薪职位")
EOF

# 执行脚本
cd projects/upwork-python-job-apply && uv run python scripts/filter_jobs.py
cd -  # 返回项目根目录

# 记录脚本执行
frago run log \
  --step "筛选高薪职位" \
  --status "success" \
  --action-type "data_processing" \
  --execution-method "file" \
  --data '{
    "file": "scripts/filter_jobs.py",
    "language": "python",
    "result_file": "outputs/filtered_jobs.json"
  }'

# === 6. 保存最终结果 ===
frago run screenshot "申请成功页面"

frago run log \
  --step "任务完成：成功筛选高薪职位" \
  --status "success" \
  --action-type "analysis" \
  --execution-method "analysis" \
  --data '{
    "task_completed": true,
    "summary": "筛选出 8 个高薪 Python 职位",
    "result_file": "outputs/filtered_jobs.json"
  }'

# === 7. 释放上下文（必须！）===
frago run release
