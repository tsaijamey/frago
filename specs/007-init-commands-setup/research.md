# Research: frago init 命令与 Recipe 资源安装

## 研究问题

1. Python 包如何打包非代码资源文件？
2. 现有 frago 资源文件有哪些？
3. 如何区分系统资源与用户自定义内容？

---

## 决策 1: 资源打包方案

### 选择: 使用 hatchling include 配置 + importlib.resources

### 理由

- hatchling 是项目现有构建后端，无需引入新依赖
- `importlib.resources` 是 Python 3.9+ 标准库，项目已要求 `>=3.9`
- 兼容 wheel/zip 等多种分发格式

### 实现方式

**pyproject.toml 配置**:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/frago"]

# 包含资源文件
include = [
    "src/frago/**/*.py",
    "src/frago/**/*.js",
    "src/frago/**/*.md",
    "src/frago/**/*.yaml",
    "src/frago/**/*.yml",
    "src/frago/**/*.sh",
]
```

**运行时资源访问** (`src/frago/init/resources.py`):

```python
from importlib.resources import files
from pathlib import Path

def get_resource_path(package: str, resource: str) -> Path:
    """获取包内资源的临时路径（用于复制）"""
    try:
        package_files = files(package)
        return package_files.joinpath(resource)
    except (FileNotFoundError, AttributeError):
        # 开发环境降级
        import importlib
        module = importlib.import_module(package)
        return Path(module.__file__).parent / resource
```

### 考虑的替代方案

| 方案 | 优点 | 缺点 |
|------|------|------|
| pkg_resources (setuptools) | 兼容性好 | 性能差，启动慢，已弃用 |
| `__file__` 相对路径 | 简单 | 不兼容 zip 包 |
| 外部配置文件 | 无需打包 | 增加安装复杂度 |

---

## 决策 2: 资源目录结构

### 选择: 在 `src/frago/resources/` 下创建资源目录

### 理由

- 与代码模块分离，结构清晰
- 便于在 pyproject.toml 中配置
- 符合 Python 包资源组织惯例

### 目录结构

```text
src/frago/resources/
├── __init__.py          # 使其成为 Python 包
├── commands/            # Claude Code slash 命令
│   ├── frago.run.md
│   ├── frago.recipe.md
│   ├── frago.exec.md
│   └── frago.test.md
├── skills/              # Claude Code skills（可选）
│   └── frago-browser-automation/
│       └── SKILL.md
└── recipes/             # 示例 recipe
    ├── atomic/
    │   ├── chrome/
    │   │   ├── youtube_extract_video_transcript.md
    │   │   └── youtube_extract_video_transcript.js
    │   └── system/
    │       ├── clipboard_read.md
    │       └── clipboard_read.py
    └── workflows/
        ├── upwork_batch_extract.md
        └── upwork_batch_extract.py
```

### 考虑的替代方案

| 方案 | 优点 | 缺点 |
|------|------|------|
| 直接使用 `.claude/commands/` | 无需复制 | 不在包内，分发困难 |
| 使用 `examples/` 目录 | 已存在 | pyproject.toml 已排除 examples |
| 放在 `src/frago/` 根目录 | 简单 | 与代码混在一起 |

---

## 决策 3: 安装目标路径

### 选择

| 资源类型 | 安装位置 |
|----------|----------|
| slash 命令 | `~/.claude/commands/frago.*.md` |
| skills | `~/.claude/skills/frago-*/` |
| 示例 recipe | `~/.frago/recipes/` |

### 理由

- `~/.claude/commands/` 是 Claude Code 标准的用户级命令目录
- `~/.claude/skills/` 是 Claude Code 标准的用户级 skills 目录
- `~/.frago/recipes/` 是 frago 项目约定的用户级 recipe 目录

### 目录创建策略

```python
from pathlib import Path

INSTALL_TARGETS = {
    "commands": Path.home() / ".claude" / "commands",
    "skills": Path.home() / ".claude" / "skills",
    "recipes": Path.home() / ".frago" / "recipes",
}
```

---

## 决策 4: 文件覆盖策略

### 选择: 分层策略

| 文件类型 | 策略 |
|----------|------|
| slash 命令 (`frago.*.md`) | 始终覆盖（系统文件） |
| skills (`frago-*/`) | 始终覆盖（系统文件） |
| 示例 recipe | 仅首次安装时复制，后续跳过 |
| 用户自定义 recipe | 永不覆盖 |

### 理由

- slash 命令和 skills 是系统提供的，用户不应修改，升级时应更新
- 示例 recipe 可能被用户修改作为学习参考，不应覆盖
- 用户自定义 recipe 需要保护

### 实现方式

```python
def install_commands(source_dir: Path, target_dir: Path) -> list[str]:
    """安装 slash 命令（始终覆盖）"""
    installed = []
    target_dir.mkdir(parents=True, exist_ok=True)
    for file in source_dir.glob("frago.*.md"):
        target = target_dir / file.name
        shutil.copy2(file, target)
        installed.append(file.name)
    return installed

def install_recipes(source_dir: Path, target_dir: Path) -> tuple[list, list]:
    """安装示例 recipe（仅首次安装）"""
    installed, skipped = [], []
    for src_file in source_dir.rglob("*"):
        if src_file.is_file():
            rel_path = src_file.relative_to(source_dir)
            target = target_dir / rel_path
            if target.exists():
                skipped.append(str(rel_path))
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, target)
                installed.append(str(rel_path))
    return installed, skipped
```

---

## 决策 5: 区分系统 vs 用户资源

### 选择: 文件名前缀 + 元数据标记

### 理由

- 系统 slash 命令使用 `frago.` 前缀，易于识别
- recipe 元数据中可添加 `source: system` 或 `source: user` 字段

### 实现示例

**recipe 元数据标记**:

```yaml
---
name: youtube_extract_video_transcript
type: atomic
runtime: chrome-js
source: example  # system | example | user
---
```

**检测逻辑**:

```python
def is_system_command(filename: str) -> bool:
    """判断是否为系统 slash 命令"""
    return filename.startswith("frago.") and filename.endswith(".md")

def is_system_recipe(metadata: dict) -> bool:
    """判断是否为系统示例 recipe"""
    return metadata.get("source") in ("system", "example")
```

---

## 现有资源清单

### slash 命令（需打包）

| 文件名 | 大小 | 功能描述 |
|--------|------|----------|
| `frago.run.md` | 17.5KB | Run 命令系统，管理 AI 主持的自动化任务 |
| `frago.recipe.md` | 19.0KB | Recipe 创建和管理 |
| `frago.exec.md` | 12.8KB | 一次性复杂任务执行 |
| `frago.test.md` | 4.1KB | Recipe 测试验证 |

### skills（考虑打包）

| 目录名 | 功能描述 |
|--------|----------|
| `frago-browser-automation/` | 浏览器自动化基础 skill |
| `ones-task-form-automation/` | ONES 任务表单填写 |
| `video-production/` | 视频制作自动化 |

### 示例 recipe（需打包）

**atomic/chrome/** (4 个):
- `youtube_extract_video_transcript`
- `upwork_extract_job_details_as_markdown`
- `x_extract_tweet_with_comments`
- `test_inspect_tab`

**atomic/system/** (9 个):
- `clipboard_read`
- `file_copy`
- `arxiv_search_papers`
- `arxiv_fetch_paper`
- `pubmed_search_papers`
- `pubmed_fetch_paper`
- `akshare_fetch_stock_latest_price`
- `akshare_fetch_stock_minute_data`
- `akshare_monitor_stock_with_alert`

**workflows/** (6 个):
- `upwork_batch_extract`
- `git_extract_commits_to_ones_tasks`
- `project_specific_task`
- `stock_batch_monitor_multiple`
- `search_academic_papers`
- `fetch_academic_paper`

---

## 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 用户无 ~/.claude/ 写入权限 | 捕获 PermissionError，提示手动创建 |
| 资源文件损坏 | 每次 init 重新复制系统文件 |
| 版本不匹配 | 可考虑在元数据中加入版本号 |
| skills 体积过大 | 初期仅包含核心 skill，其他按需下载 |

---

## 下一步

1. 创建 `src/frago/resources/` 目录结构
2. 将现有资源复制到该目录
3. 更新 pyproject.toml 配置
4. 实现 `src/frago/init/resources.py` 模块
5. 扩展 `frago init` 命令调用资源安装
