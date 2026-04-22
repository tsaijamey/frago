# must-workspace

分类: 替代（MUST）

## 解决什么问题
agent 把产出文件散落在 /tmp、Desktop 等随机位置；用 cd 切换目录导致 frago 命令失败。

## 目录结构

  ~/.frago/projects/<id>/          # Run 实例的 workspace 根目录
  ├── project.json                 # 元数据
  ├── logs/
  │   └── execution.jsonl          # 执行日志
  ├── scripts/                     # 执行脚本
  ├── screenshots/                 # 截图
  ├── outputs/                     # 任务产出（数据、报告、视频等）
  └── temp/                        # 临时文件（任务完成后清理）

## 产出物隔离

所有产出必须放在 workspace 内。

  # ✅ 正确：产出在 workspace 内
  {{frago_launcher}} recipe run video_produce_from_script \
    --params '{"script_file": "~/.frago/projects/<id>/outputs/script.json", "output_dir": "~/.frago/projects/<id>/outputs/video"}'

  # ❌ 错误：使用外部目录
  {{frago_launcher}} recipe run video_produce_from_script \
    --params '{"script_file": "~/Desktop/script.json"}'

禁止在 Desktop、/tmp、Downloads 等外部位置创建文件。
Recipe 调用时必须显式指定 output_dir 到 workspace 内。

## Run 上下文（自动管理）

Executor 启动 sub-agent 时通过环境变量 FRAGO_CURRENT_RUN 自动注入 run_id。
多个 agent 可以并行执行，各自拥有独立的 run_id 和 workspace。

NEVER 手动调用 {{frago_launcher}} run set-context 或 {{frago_launcher}} run release。
这些命令仅供 CLI 手动调试使用，sub-agent 不需要也不应该调用。

## 禁止使用 cd

所有命令从项目根目录执行，用绝对路径或相对路径访问文件。

  # ✅ 正确
  uv run python ~/.frago/projects/<id>/scripts/filter_jobs.py
  cat ~/.frago/projects/<id>/outputs/result.json

  # ❌ 错误：cd 后 frago 命令会失败
  cd ~/.frago/projects/<id>
  {{frago_launcher}} run log ...                            # 会报错

## 路径约定

日志中用相对于 workspace 的路径，执行脚本时用绝对路径：

  # 日志记录用相对路径
  {{frago_launcher}} run log --data '{"file": "scripts/filter.py", "result_file": "outputs/filtered.json"}'

  # 执行脚本用绝对路径
  uv run python ~/.frago/projects/<id>/scripts/filter.py
