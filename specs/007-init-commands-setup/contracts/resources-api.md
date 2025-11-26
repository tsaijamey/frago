# Resources API Contract

## 模块: `frago.init.resources`

### 函数签名

#### `get_package_resources_path(resource_type: str) -> Path`

获取包内资源目录路径

**参数**:
- `resource_type`: 资源类型 (`"commands"`, `"skills"`, `"recipes"`)

**返回**: 资源目录的 Path 对象

**异常**:
- `ValueError`: 无效的资源类型
- `FileNotFoundError`: 资源目录不存在

---

#### `get_target_path(resource_type: str) -> Path`

获取资源安装目标目录

**参数**:
- `resource_type`: 资源类型

**返回**: 目标目录的 Path 对象

**示例**:
```python
>>> get_target_path("commands")
PosixPath('/home/user/.claude/commands')
>>> get_target_path("recipes")
PosixPath('/home/user/.frago/recipes')
```

---

#### `install_commands(source_dir: Path, target_dir: Path) -> InstallResult`

安装 Claude Code slash 命令

**行为**:
- 始终覆盖已存在的 `frago.*.md` 文件
- 创建目标目录（如不存在）

**返回**: `InstallResult` 包含安装结果

---

#### `install_skills(source_dir: Path, target_dir: Path) -> InstallResult`

安装 Claude Code skills

**行为**:
- 始终覆盖已存在的 `frago-*` 目录
- 保留非 frago 开头的 skill

**返回**: `InstallResult` 包含安装结果

---

#### `install_recipes(source_dir: Path, target_dir: Path) -> InstallResult`

安装示例 recipe

**行为**:
- 仅在目标文件不存在时复制
- 保留用户已有文件

**返回**: `InstallResult` 包含安装和跳过的文件列表

---

#### `install_all_resources() -> ResourceStatus`

安装所有资源（主入口）

**行为**:
1. 安装 commands
2. 安装 skills
3. 安装 recipes

**返回**: `ResourceStatus` 包含所有资源的安装状态

---

#### `get_resources_status() -> ResourceStatus`

获取当前资源安装状态（用于 `--status` 选项）

**返回**: 当前安装状态

---

## CLI 扩展

### `frago init` 命令选项

| 选项 | 类型 | 描述 |
|------|------|------|
| `--skip-resources` | flag | 跳过资源安装 |
| `--update-resources` | flag | 强制更新所有资源（包括 recipe） |
| `--status` | flag | 显示资源安装状态并退出 |

### 输出格式

**安装成功**:
```
📦 安装 Claude Code 命令...
  ✅ frago.run.md
  ✅ frago.recipe.md
  ✅ frago.exec.md
  ✅ frago.test.md

📦 安装示例 Recipe...
  ✅ atomic/chrome/youtube_extract_video_transcript (2 files)
  ⏭️ atomic/system/clipboard_read (已存在)
  ✅ workflows/upwork_batch_extract (2 files)

✅ 资源安装完成 (8 个文件安装, 2 个跳过)
```

**状态显示** (`--status`):
```
📋 Frago 资源状态

Claude Code 命令:
  📍 ~/.claude/commands/
  📄 4 个命令已安装

示例 Recipe:
  📍 ~/.frago/recipes/
  📄 15 个 recipe 可用

版本: 0.1.0
最后更新: 2025-11-26 10:30
```
