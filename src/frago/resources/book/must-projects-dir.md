# must-projects-dir

分类: 替代（MUST）

## 解决什么问题
agent 把产出文件散落在 /tmp、Desktop 等随机位置；用 cd 切换目录导致 frago 命令失败。

## 先判断：写进 projects 还是 data

落盘前先看有没有 `FRAGO_CURRENT_RUN` 环境变量：

  有（env | grep FRAGO_CURRENT_RUN 有输出）
  → 你是 frago run 驱动的 sub-agent
  → 产出走 ~/.frago/projects/<domain>/<run>/
  → 本文其余规则都针对这种情况

  没有（claude code 人工直驱，无 FRAGO_CURRENT_RUN）
  → 产出走 ~/.frago/data/<语义-slug>-<YYYYMMDD>/
  → slug 用 kebab-case，日期后缀必带且必须是完整 8 位日期（如 power-seller-reg-audit-20260529）
  → NEVER 用月份（202605）或自创其他日期粒度；日期取任务开始当天
  → 扁平存放，不按 domain 分层；哪怕主题命中已注册 domain 也仍落 data，不并入 projects
  → 若保留工作流水笔记，主文件固定叫 notebook.md（小写），别自创 session.md / log.md 之类的名字

注: `~/.frago/data/` 是 claude code 人工直驱任务的工作区（2026-05-24 起纳入同步）。
    旧定位"recipe 缓存数据用"已作废，别混。

## 目录结构

  ~/.frago/projects/<id>/          # Run 实例的工作目录（每个 frago run 独占一个 <id>）
  ├── project.json                 # 元数据
  ├── logs/
  │   └── execution.jsonl          # 执行日志
  ├── scripts/                     # 执行脚本
  ├── screenshots/                 # 截图
  ├── outputs/                     # 任务产出（数据、报告、视频等）
  └── temp/                        # 临时文件（任务完成后清理）


## 产出物隔离

所有产出必须放在 ~/.frago/projects/<id>/ 内。

  # ✅ 正确：产出在 projects/<id>/ 内
  {{frago_launcher}} recipe run video_produce_from_script \
    --params '{"script_file": "~/.frago/projects/<id>/outputs/script.json", "output_dir": "~/.frago/projects/<id>/outputs/video"}'

  # ❌ 错误：使用外部目录
  {{frago_launcher}} recipe run video_produce_from_script \
    --params '{"script_file": "~/Desktop/script.json"}'

禁止在 Desktop、/tmp、Downloads 等外部位置创建文件。
Recipe 调用时必须显式指定 output_dir 到 ~/.frago/projects/<id>/ 内。

## Run 上下文（自动管理）

Executor 启动 sub-agent 时通过环境变量 FRAGO_CURRENT_RUN 自动注入 run_id。
多个 agent 可以并行执行，各自拥有独立的 run_id 和 projects/<id>/ 目录。

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

日志中用相对于 projects/<id>/ 的路径，执行脚本时用绝对路径：

  # 日志记录用相对路径
  {{frago_launcher}} run log --data '{"file": "scripts/filter.py", "result_file": "outputs/filtered.json"}'

  # 执行脚本用绝对路径
  uv run python ~/.frago/projects/<id>/scripts/filter.py
