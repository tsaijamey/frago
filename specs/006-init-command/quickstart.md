# Developer Quickstart: frago init

**Feature**: 006-init-command
**Date**: 2025-11-25
**Related**: [spec.md](./spec.md) | [plan.md](./plan.md) | [data-model.md](./data-model.md) | [contracts/cli_commands.md](./contracts/cli_commands.md)

本文档帮助开发者快速搭建本地开发环境，运行和测试 `frago init` 命令。

---

## 1. 环境准备

### 前置要求

- Python 3.9+
- uv (Python 包管理工具)
- Git
- 可选：Node.js 20+ 和 Claude Code（用于测试完整流程）

### 克隆仓库

```bash
cd ~repos
git clone https://github.com/tsaijamey/frago.git
cd Frago

# 切换到功能分支
git checkout 006-init-command
```

### 安装开发依赖

```bash
# 使用 uv 创建虚拟环境并安装依赖
uv sync --dev

# 或者使用 pip (如果没有 uv)
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 验证安装

```bash
# 运行 frago 命令确认安装成功
uv run frago --version

# 或者激活虚拟环境后直接运行
source .venv/bin/activate
frago --version
```

---

## 2. 代码结构导航

### 核心文件位置

```
src/frago/
├── cli/
│   ├── main.py              # CLI 入口，注册所有命令
│   └── init_command.py      # init 命令实现（新增）
├── init/                    # init 功能模块（新增）
│   ├── __init__.py
│   ├── checker.py           # 依赖检查逻辑
│   ├── installer.py         # 安装逻辑
│   ├── configurator.py      # 配置管理
│   ├── recovery.py          # 状态恢复逻辑
│   └── models.py            # Config, TempState 数据模型
└── ...

tests/
├── unit/
│   └── init/                # init 单元测试（新增）
│       ├── test_checker.py
│       ├── test_installer.py
│       ├── test_configurator.py
│       └── test_recovery.py
├── integration/
│   └── test_init_command.py # init 集成测试（新增）
└── ...
```

### 入口点

**src/frago/cli/main.py** (现有文件，需添加 init 命令)：

```python
import click
from frago.cli import commands, recipe_commands
from frago.cli.init_command import init  # 新增导入

@click.group()
@click.version_option()
def cli():
    """Frago - AI-driven multi-runtime automation framework"""
    pass

# 注册现有命令
cli.add_command(commands.navigate)
cli.add_command(commands.click_element)
# ... 其他 CDP 命令

# 注册 recipe 命令组
cli.add_command(recipe_commands.recipe)

# 注册 init 命令（新增）
cli.add_command(init)

if __name__ == "__main__":
    cli()
```

---

## 3. 运行 init 命令

### 本地测试运行

```bash
# 使用 uv run 执行（推荐）
uv run frago init

# 或者激活虚拟环境后运行
source .venv/bin/activate
frago init
```

### 模拟不同环境状态

#### 场景 1: 全新系统（无依赖）

```bash
# 临时移除 Node.js 和 Claude Code 的 PATH
export PATH=$(echo $PATH | tr ':' '\n' | grep -v node | grep -v claude | tr '\n' ':')

# 运行 init
uv run frago init

# 恢复 PATH
hash -r
```

#### 场景 2: 仅有 Node.js，无 Claude Code

```bash
# 确保 Node.js 可用
node --version

# 临时隐藏 Claude Code（如果已安装）
alias claude-code='echo "claude-code: command not found" >&2 && exit 127'

# 运行 init
uv run frago init

# 清除 alias
unalias claude-code
```

#### 场景 3: 所有依赖已满足

```bash
# 确保 Node.js 和 Claude Code 都可用
node --version
npm --version
claude-code --version

# 运行 init（应进入配置更新流程）
uv run frago init
```

#### 场景 4: 模拟 Ctrl+C 中断

```bash
# 运行 init
uv run frago init

# 在安装过程中按 Ctrl+C
# (手动操作)

# 检查临时状态文件
cat ~/.frago/.init_state.json

# 重新运行（应提示恢复）
uv run frago init
```

---

## 4. 测试配置文件

### 配置文件位置

| 文件 | 路径 | 用途 |
|------|------|------|
| **主配置** | `~/.frago/config.json` | 持久化配置 |
| **临时状态** | `~/.frago/.init_state.json` | Ctrl+C 恢复用 |
| **配置备份** | `~/.frago/config.json.bak` | 覆盖时自动创建 |

### 查看配置

```bash
# 使用 init 命令查看
uv run frago init --show-config

# 或直接查看文件
cat ~/.frago/config.json | python -m json.tool

# 查看临时状态
cat ~/.frago/.init_state.json | python -m json.tool
```

### 清理配置（重置测试环境）

```bash
# 删除所有配置和状态文件
rm -rf ~/.frago/

# 或保留配置，仅删除临时状态
rm ~/.frago/.init_state.json

# 使用 --reset 选项
uv run frago init --reset
```

### 手动创建测试配置

```bash
# 创建自定义配置用于测试
mkdir -p ~/.frago
cat > ~/.frago/config.json << 'EOF'
{
  "schema_version": "1.0",
  "node_version": "20.11.0",
  "node_path": "/usr/local/bin/node",
  "npm_version": "10.2.4",
  "claude_code_version": null,
  "claude_code_path": null,
  "auth_method": "official",
  "api_endpoint": null,
  "ccr_enabled": false,
  "ccr_config_path": null,
  "created_at": "2025-11-25T10:00:00Z",
  "updated_at": "2025-11-25T10:00:00Z",
  "init_completed": false
}
EOF

# 验证配置
uv run frago init --show-config
```

---

## 5. 运行测试

### 单元测试

```bash
# 运行所有 init 单元测试
uv run pytest tests/unit/init/ -v

# 运行特定测试文件
uv run pytest tests/unit/init/test_checker.py -v

# 运行特定测试函数
uv run pytest tests/unit/init/test_checker.py::test_check_node_installed -v

# 查看测试覆盖率
uv run pytest tests/unit/init/ --cov=frago.init --cov-report=term-missing
```

### 集成测试

```bash
# 运行 init 集成测试
uv run pytest tests/integration/test_init_command.py -v

# 运行特定场景
uv run pytest tests/integration/test_init_command.py::test_init_fresh_install -v

# 慢速测试（需要真实网络）
uv run pytest tests/integration/test_init_command.py -v --slow
```

### 测试覆盖率报告

```bash
# 生成 HTML 覆盖率报告
uv run pytest tests/unit/init/ --cov=frago.init --cov-report=html

# 在浏览器中查看
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

---

## 6. 调试技巧

### 启用详细日志

```python
# 在 init_command.py 中添加
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# 在关键位置添加日志
logger.debug(f"Checking dependency: {name}")
logger.info(f"Installation completed: {component}")
logger.error(f"Installation failed: {error}")
```

### 使用 pdb 断点

```python
# 在需要调试的地方插入
import pdb; pdb.set_trace()

# 或使用 ipdb (更友好)
import ipdb; ipdb.set_trace()
```

### 模拟外部命令失败

```python
# 在 installer.py 中
import os

# 模拟 npm install 失败
if os.getenv("FRAGO_TEST_INSTALL_FAIL"):
    raise CommandError("Simulated install failure", InitErrorCode.INSTALL_ERROR)
```

```bash
# 运行测试时设置环境变量
FRAGO_TEST_INSTALL_FAIL=1 uv run frago init
```

### 查看 Click 调试信息

```bash
# Click 内置的调试模式
export CLICK_DEBUG=1
uv run frago init

# 查看 Click 解析的参数
export CLICK_SHOW_ARGS=1
uv run frago init --reset --skip-deps
```

---

## 7. 常见开发任务

### 添加新的安装步骤

1. **更新 `InstallationStep` 枚举**（`models.py`）：
   ```python
   STEP_INSTALL_SOMETHING = "install_something"
   ```

2. **实现安装逻辑**（`installer.py`）：
   ```python
   def install_something():
       """安装某个组件"""
       step = InstallationStep(name="install_something")
       step.start()
       try:
           # 安装逻辑
           run_external_command(["npm", "install", "-g", "something"])
           step.complete()
       except CommandError as e:
           step.fail(str(e), e.code)
           raise
   ```

3. **更新 init 流程**（`init_command.py`）：
   ```python
   if should_install_something:
       install_something()
       temp_state.add_step("install_something")
       save_temp_state(temp_state, STATE_FILE)
   ```

4. **添加测试**：
   ```python
   # tests/unit/init/test_installer.py
   def test_install_something_success():
       with patch('frago.init.installer.run_external_command') as mock_run:
           mock_run.return_value = Mock(returncode=0)
           install_something()
           mock_run.assert_called_once()
   ```

### 添加新的配置选项

1. **更新 `Config` 模型**（`models.py`）：
   ```python
   class Config(BaseModel):
       # ...现有字段
       new_option: bool = False  # 新增字段
   ```

2. **更新配置流程**（`configurator.py`）：
   ```python
   def configure_new_option():
       enabled = click.confirm("Enable new option?", default=False)
       config.new_option = enabled
   ```

3. **更新 schema_version**（如果是破坏性变更）：
   ```python
   schema_version: str = "1.1"  # 从 1.0 升级到 1.1
   ```

4. **添加迁移逻辑**（`configurator.py`）：
   ```python
   def migrate_v1_0_to_v1_1(data: dict) -> dict:
       if "new_option" not in data:
           data["new_option"] = False
       return data
   ```

### 修改交互提示

1. **定位交互代码**（通常在 `init_command.py` 或 `configurator.py`）
2. **修改 Click 提示**：
   ```python
   # 修改前
   choice = click.prompt("Choose option", type=click.Choice(["a", "b"]))

   # 修改后
   click.echo("\n📝 Please choose an option:\n")
   click.echo("  [1] Option A - Description")
   click.echo("  [2] Option B - Description\n")
   choice = click.prompt("Your choice", type=click.Choice(["1", "2"]))
   ```
3. **更新文档**（`contracts/cli_commands.md`）

---

## 8. 性能分析

### 测量 init 执行时间

```bash
# 使用 time 命令
time uv run frago init --non-interactive

# 或在代码中使用 time 模块
import time

start = time.time()
# ... init 逻辑
duration = time.time() - start
click.echo(f"Init completed in {duration:.2f}s")
```

### 分析并行检查性能

```python
# 在 checker.py 中
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

def parallel_dependency_check():
    start = time.time()

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {...}
        # 收集结果
        results = {}
        for future in as_completed(futures):
            ...

    duration = time.time() - start
    logger.info(f"Parallel check completed in {duration:.2f}s")
    return results
```

---

## 9. 故障排查

### 问题：init 命令找不到

```bash
# 检查 frago 是否正确安装
uv run which frago
uv run frago --help

# 重新安装
uv sync --reinstall

# 验证 entry points
python -c "import pkg_resources; print(pkg_resources.get_distribution('frago').get_entry_map())"
```

### 问题：配置文件权限错误

```bash
# 检查目录权限
ls -la ~/.frago/

# 修复权限
chmod 755 ~/.frago
chmod 644 ~/.frago/config.json

# 检查所有者
ls -l ~/.frago/config.json

# 如果需要，修改所有者
sudo chown $USER:$USER ~/.frago/config.json
```

### 问题：测试失败（import error）

```bash
# 确保安装了开发依赖
uv sync --dev

# 检查 Python 路径
python -c "import sys; print('\n'.join(sys.path))"

# 重新安装项目为可编辑模式
uv pip install -e .
```

### 问题：Click 命令未注册

```bash
# 检查 main.py 是否正确导入和注册 init 命令
grep -n "init" src/frago/cli/main.py

# 验证 Click 组
uv run python -c "from frago.cli.main import cli; print(cli.commands)"
```

---

## 10. 提交代码前检查清单

- [ ] 代码格式化：`uv run black src/frago/init/`
- [ ] 代码 lint：`uv run ruff check src/frago/init/`
- [ ] 类型检查：`uv run mypy src/frago/init/`
- [ ] 单元测试通过：`uv run pytest tests/unit/init/ -v`
- [ ] 集成测试通过：`uv run pytest tests/integration/test_init_command.py -v`
- [ ] 测试覆盖率 >= 80%：`uv run pytest --cov=frago.init --cov-report=term`
- [ ] 文档更新：contracts, data-model, 此文件
- [ ] Git 提交信息清晰：遵循 conventional commits

---

## 11. 快速参考

### 常用命令

```bash
# 开发环境设置
uv sync --dev

# 运行 init
uv run frago init

# 运行测试
uv run pytest tests/unit/init/ -v

# 代码格式化
uv run black src/frago/init/
uv run ruff check --fix src/frago/init/

# 清理配置
rm -rf ~/.frago/

# 查看配置
uv run frago init --show-config
```

### 关键文件路径

| 用途 | 路径 |
|------|------|
| 配置文件 | `~/.frago/config.json` |
| 临时状态 | `~/.frago/.init_state.json` |
| 主入口 | `src/frago/cli/main.py` |
| Init 命令 | `src/frago/cli/init_command.py` |
| 数据模型 | `src/frago/init/models.py` |
| 单元测试 | `tests/unit/init/` |
| 集成测试 | `tests/integration/test_init_command.py` |

### 环境变量

```bash
# 调试模式
export CLICK_DEBUG=1
export FRAGO_DEBUG=1

# 自定义配置目录
export FRAGO_CONFIG_DIR=/tmp/frago_test

# 代理设置
export HTTP_PROXY=http://proxy:8080
export HTTPS_PROXY=http://proxy:8080

# 超时设置
export FRAGO_INIT_TIMEOUT=300
```

---

## 总结

本快速入门指南涵盖了开发 `frago init` 命令所需的所有基础知识：

- ✅ 环境准备和依赖安装
- ✅ 代码结构导航
- ✅ 本地运行和测试
- ✅ 配置文件管理
- ✅ 调试技巧
- ✅ 常见开发任务示例
- ✅ 故障排查指南

**下一步**: 开始实现 `src/frago/init/` 模块，参考 `data-model.md` 和 `contracts/cli_commands.md`。
