# 工作目录与空间管理

适用于：`/frago.run`、`/frago.do`

## 一、确定 projects 目录位置

**在开始任务前，必须先确定 `projects/` 目录的位置。**

### 检查流程

```bash
# 步骤1: 检查 ~/.frago/config.yaml 是否指定了工作目录
cat ~/.frago/config.yaml 2>/dev/null | grep -E "workspace|projects"

# 步骤2: 如果没有配置，检查当前目录下是否有 projects 目录
pwd
ls -la projects/ 2>/dev/null
```

### 三种情况处理

| 情况 | 处理方式 |
|------|---------|
| `~/.frago/config.yaml` 指定了 `workspace` | 使用配置中的路径 |
| 当前目录下存在 `projects/` | 使用 `$(pwd)/projects/` |
| 都没有 | **使用 AskUserQuestion 询问用户** |

### 询问用户（当目录不存在时）

```markdown
问题：未找到 projects 目录，请选择如何处理：
选项：
- 在当前目录创建 - 在 $(pwd)/projects/ 创建新目录
- 指定已有目录 - 输入已有的 projects 目录路径
- 使用 ~/.frago/projects - 在用户目录下创建全局工作空间
```

### 确认后记录

确定 projects 目录后，后续所有路径都基于此目录：

```bash
# 示例：确定 projects 目录为 /Users/chagee/Repos/AuViMa/projects
PROJECTS_DIR="/Users/chagee/Repos/AuViMa/projects"

# 后续使用
frago run init "my-task"  # 会在 $PROJECTS_DIR/my-task/ 创建
```

---

## 二、工作空间隔离原则

### 所有产出物必须放在 Project 工作空间内

```
projects/<project_id>/       # Project 工作空间根目录
├── project.json             # 元数据
├── logs/
│   └── execution.jsonl      # 执行日志
├── scripts/                 # 执行脚本
├── screenshots/             # 截图
├── outputs/                 # 任务产出物（数据、报告、视频等）
│   ├── video_script.json    # 生成的脚本实例
│   ├── final_video.mp4      # 视频产出
│   └── analysis.json        # 分析结果
└── temp/                    # 临时文件（任务完成后清理）
```

### 禁止的行为

- ❌ 在桌面、/tmp、下载目录等外部位置创建文件
- ❌ 配方执行时不指定 output_dir，使用配方默认位置
- ❌ 产出物散落在工作空间外的目录

### 正确做法

- ✅ 所有文件使用 `projects/<project_id>/` 下的路径
- ✅ 调用配方时明确指定 `output_dir` 为工作空间内的目录
- ✅ 临时文件放在 `temp/`，任务完成后清理

```bash
# ✅ 正确：所有输出都在工作空间内
frago recipe run video_produce_from_script \
  --params '{
    "script_file": "projects/<project_id>/outputs/video_script.json",
    "output_dir": "projects/<project_id>/outputs/video"
  }'

# ❌ 错误：使用外部目录
frago recipe run video_produce_from_script \
  --params '{"script_file": "~/Desktop/script.json"}'
```

---

## 三、单一运行互斥

**系统仅允许一个活跃的 Project 上下文。** 这是设计约束，确保工作聚焦。

### 互斥规则

- 当 `set-context` 时，若已有其他活跃的 project，命令会失败并提示先释放
- 同一 project 可以重复 `set-context`（恢复工作）
- 任务完成后**必须**释放上下文

### 典型工作流

```bash
# 1. 开始任务
frago run init "upwork python job apply"
frago run set-context upwork-python-job-apply

# 2. 执行任务...

# 3. 任务完成，释放上下文（必须！）
frago run release

# 4. 开始新任务
frago run init "another task"
frago run set-context another-task
```

### 如果忘记释放

```bash
# 尝试设置新上下文时会看到错误
Error: Another run 'upwork-python-job-apply' is currently active.
Run 'frago run release' to release it first,
or 'frago run set-context upwork-python-job-apply' to continue it.
```

---

## 四、工作目录管理

**禁止使用 `cd` 命令切换目录！** 这会导致 `frago` 命令失效。

### 正确做法

**始终在项目根目录执行所有命令**，使用绝对路径或相对路径访问文件：

```bash
# ✅ 正确：使用绝对路径执行脚本
uv run python projects/<project_id>/scripts/filter_jobs.py

# ✅ 正确：使用相对路径读取文件
cat projects/<project_id>/outputs/result.json

# ✅ 正确：使用 find 查看文件结构
find projects/<project_id> -type f -name "*.md" | sort
```

### 错误做法

```bash
# ❌ 错误：不要使用 cd
cd projects/<project_id> && uv run python scripts/filter_jobs.py

# ❌ 错误：切换目录后 frago 会失效
cd projects/<project_id>
frago run log ...  # 这会报错！
```

### 文件路径约定

在 project 实例内部引用文件时，使用**相对于 project 根目录的路径**：

```bash
# 记录日志时，data.file 使用相对路径
frago run log \
  --data '{"file": "scripts/filter_jobs.py", "result_file": "outputs/filtered_jobs.json"}'

# 但执行脚本时，使用完整相对路径或绝对路径
uv run python projects/<project_id>/scripts/filter_jobs.py
```

---

## 五、注意事项

- **上下文优先级**：环境变量 `FRAGO_CURRENT_RUN` > 配置文件 `.frago/current_project`
- **并发安全**：同一时间只在一个 project 中工作
- **日志格式版本**：当前为 `schema_version: "1.0"`
