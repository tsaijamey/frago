# Research: Frago 环境初始化命令

**Feature**: 006-init-command
**Date**: 2025-11-25
**Related**: [plan.md](./plan.md) | [spec.md](./spec.md)

本文档记录 Phase 0 研究阶段的技术决策和实现指导。

---

## 1. Windows 平台支持

### 决策

**仅检测并提供手动安装指引，不支持 Windows 自动安装（MVP 阶段）**

### 理由

1. **复杂度控制**：Windows 平台的 Node.js 版本管理工具生态复杂（nvm-windows、fnm、volta、scoop、chocolatey），自动安装需要处理多种场景
2. **用户基础**：Frago 主要面向开发者，Windows 用户通常已有 Node.js 环境或有能力手动安装
3. **优先级**：Linux/macOS 用户占主要市场份额（根据类似 CLI 工具的用户分布）
4. **迭代策略**：MVP 先验证核心流程，后续版本根据用户反馈决定是否投入 Windows 自动安装

### 考虑的替代方案

| 方案 | 优点 | 缺点 | 为何未采用 |
|------|------|------|-----------|
| **支持 nvm-windows 自动安装** | 提供完整体验 | nvm-windows 与 Unix nvm 命令差异大，需要单独实现；安装需要管理员权限 | 实现成本高，MVP 阶段不值得 |
| **支持 fnm 自动安装** | fnm 跨平台一致，命令统一 | fnm 需要用户手动配置 shell 环境；Windows 上需要处理 PowerShell profile | 环境配置自动化复杂 |
| **推荐 scoop/chocolatey** | 包管理器方式简洁 | 要求用户先安装 scoop/choco；不是所有用户都熟悉 | 引入额外依赖 |

### 实现指导

#### Windows 检测逻辑

```python
import platform
import subprocess
import shutil
from pathlib import Path

def detect_platform() -> str:
    """检测操作系统平台"""
    return platform.system()  # 返回 'Windows', 'Linux', 'Darwin'

def check_node_windows() -> dict:
    """Windows 平台的 Node.js 检查"""
    result = {
        "installed": False,
        "version": None,
        "path": None,
        "npm_version": None,
        "manual_install_guide": None,
    }

    # 检查 node 命令是否存在
    node_path = shutil.which("node")
    if not node_path:
        result["manual_install_guide"] = (
            "未检测到 Node.js。请访问以下链接手动安装：\n"
            "  1. 官方安装器：https://nodejs.org/en/download/\n"
            "  2. fnm (推荐)：https://github.com/Schniz/fnm\n"
            "  3. nvm-windows：https://github.com/coreybutler/nvm-windows\n"
        )
        return result

    # 检查版本
    try:
        version_output = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if version_output.returncode == 0:
            version = version_output.stdout.strip().lstrip('v')
            result["installed"] = True
            result["version"] = version
            result["path"] = node_path

            # 检查 npm
            npm_output = subprocess.run(
                ["npm", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if npm_output.returncode == 0:
                result["npm_version"] = npm_output.stdout.strip()
    except Exception as e:
        result["error"] = str(e)

    return result
```

#### Windows 错误提示模板

```text
错误: Windows 平台暂不支持自动安装。

检测结果:
  - Node.js: 未安装
  - Claude Code: 未检测到

建议操作:
1. 安装 Node.js 20+ (推荐使用 fnm):
   > winget install Schniz.fnm
   > fnm install 20
   > fnm use 20

2. 安装 Claude Code:
   > npm install -g @anthropic-ai/claude-code

3. 重新运行: frago init
```

---

## 2. 并行检查实现策略

### 决策

**使用 `concurrent.futures.ThreadPoolExecutor` + `subprocess.run`**

### 理由

1. **简单性**：线程池 API 简单直观，适合 I/O 密集型任务（外部命令调用）
2. **同步风格**：与现有 Frago 代码风格一致（非 async 项目）
3. **错误处理**：线程池的 Future.result() 自然抛出异常，便于统一处理
4. **GIL 影响小**：外部命令调用大部分时间在等待 I/O，GIL 不是瓶颈
5. **Python 版本兼容性**：Python 3.9+ 都内置支持，无需额外依赖

### 考虑的替代方案

| 方案 | 优点 | 缺点 | 为何未采用 |
|------|------|------|-----------|
| **asyncio + create_subprocess_exec** | 性能理论上更优；适合大量并发 | 需要改造整个命令为 async；学习曲线陡；错误处理复杂 | 过度工程；仅 2 个并发检查不值得 |
| **multiprocessing.Pool** | 真正并行（多进程） | 进程创建开销大；序列化开销；过度设计 | 杀鸡用牛刀 |
| **顺序执行（不并行）** | 代码最简单；易调试 | 用户体验差（等待时间长） | 违反规格要求 |

### 实现指导

#### 并行检查模式

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Callable
import subprocess

def check_dependency(name: str, command: list, version_arg: str = "--version") -> dict:
    """检查单个依赖项"""
    try:
        result = subprocess.run(
            command + [version_arg],
            capture_output=True,
            text=True,
            timeout=5,  # 5秒超时
        )
        return {
            "name": name,
            "installed": result.returncode == 0,
            "output": result.stdout.strip() if result.returncode == 0 else None,
            "error": result.stderr.strip() if result.returncode != 0 else None,
        }
    except FileNotFoundError:
        return {"name": name, "installed": False, "error": "Command not found"}
    except subprocess.TimeoutExpired:
        return {"name": name, "installed": False, "error": "Command timeout"}
    except Exception as e:
        return {"name": name, "installed": False, "error": str(e)}

def parallel_dependency_check() -> Dict[str, dict]:
    """并行检查所有依赖"""
    checks = {
        "node": (["node"], "--version"),
        "npm": (["npm"], "--version"),
        "claude-code": (["claude-code"], "--version"),
    }

    results = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        # 提交所有任务
        future_to_name = {
            executor.submit(check_dependency, name, cmd, ver): name
            for name, (cmd, ver) in checks.items()
        }

        # 收集结果（as_completed 按完成顺序返回）
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results[name] = future.result()
            except Exception as e:
                results[name] = {"name": name, "installed": False, "error": str(e)}

    return results
```

#### 错误处理策略

```python
def handle_check_results(results: Dict[str, dict]) -> dict:
    """处理检查结果，生成安装计划"""
    missing = []
    installed = []
    errors = []

    for name, result in results.items():
        if result["installed"]:
            installed.append(name)
        elif result.get("error"):
            errors.append((name, result["error"]))
        else:
            missing.append(name)

    return {
        "missing": missing,
        "installed": installed,
        "errors": errors,
        "needs_install": len(missing) > 0,
    }
```

---

## 3. 外部命令调用的错误处理

### 决策

**采用分层错误处理 + 标准化错误码系统**

### 理由

1. **用户体验**：清晰的错误分类帮助用户快速定位问题
2. **自动化友好**：错误码支持脚本调用和 CI/CD 集成
3. **可调试性**：详细的错误信息方便用户报告问题
4. **一致性**：所有外部命令使用统一的错误处理模式

### 错误分类体系

| 错误类型 | 退出码 | 示例场景 | 用户操作 |
|---------|--------|---------|---------|
| **命令不存在** | 10 | `node` 命令找不到 | 安装依赖 |
| **版本不足** | 11 | Node.js 18.x < 20.x | 升级版本 |
| **权限错误** | 12 | `npm install -g` 无权限 | 使用 sudo 或配置 npm prefix |
| **网络错误** | 13 | npm install 超时 | 检查网络/代理 |
| **安装失败** | 14 | npm install 返回非 0 | 查看详细日志 |
| **配置错误** | 3 | config.json 格式错误 | 修复或删除配置文件 |
| **环境错误** | 10 | 主目录不可写 | 检查文件系统权限 |

### 实现指导

#### 错误处理包装器

```python
from enum import IntEnum
from typing import Optional, List
import subprocess
import shutil

class InitErrorCode(IntEnum):
    """Init 命令错误码"""
    SUCCESS = 0
    INSTALL_FAILED = 1
    USER_CANCELLED = 2
    CONFIG_ERROR = 3
    COMMAND_NOT_FOUND = 10
    VERSION_INSUFFICIENT = 11
    PERMISSION_ERROR = 12
    NETWORK_ERROR = 13
    INSTALL_ERROR = 14

class CommandError(Exception):
    """外部命令执行错误"""
    def __init__(self, message: str, code: InitErrorCode, details: Optional[str] = None):
        self.message = message
        self.code = code
        self.details = details
        super().__init__(message)

def run_external_command(
    cmd: List[str],
    timeout: int = 120,
    check: bool = True,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """执行外部命令并处理错误"""

    # 1. 检查命令是否存在
    if not shutil.which(cmd[0]):
        raise CommandError(
            f"命令未找到: {cmd[0]}",
            InitErrorCode.COMMAND_NOT_FOUND,
            f"请确保 {cmd[0]} 已安装并在 PATH 中",
        )

    try:
        # 2. 执行命令
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            check=False,  # 手动检查返回码
        )

        # 3. 检查返回码
        if check and result.returncode != 0:
            # 分析错误类型
            stderr_lower = result.stderr.lower()

            if "permission denied" in stderr_lower or "eacces" in stderr_lower:
                raise CommandError(
                    f"权限不足: {' '.join(cmd)}",
                    InitErrorCode.PERMISSION_ERROR,
                    f"尝试使用 sudo 或配置 npm prefix:\n"
                    f"  npm config set prefix ~/.npm-global\n"
                    f"  export PATH=~/.npm-global/bin:$PATH",
                )

            elif "timeout" in stderr_lower or "etimedout" in stderr_lower:
                raise CommandError(
                    f"网络超时: {' '.join(cmd)}",
                    InitErrorCode.NETWORK_ERROR,
                    "请检查网络连接或配置代理:\n"
                    "  export HTTP_PROXY=http://proxy:port\n"
                    "  export HTTPS_PROXY=http://proxy:port",
                )

            else:
                raise CommandError(
                    f"命令执行失败: {' '.join(cmd)}",
                    InitErrorCode.INSTALL_ERROR,
                    f"返回码: {result.returncode}\n"
                    f"错误输出:\n{result.stderr}",
                )

        return result

    except subprocess.TimeoutExpired as e:
        raise CommandError(
            f"命令执行超时 ({timeout}s): {' '.join(cmd)}",
            InitErrorCode.NETWORK_ERROR,
            "请检查网络连接或增加超时时间",
        ) from e
```

#### 错误信息模板

```python
def format_error_message(error: CommandError) -> str:
    """格式化错误消息"""
    lines = [
        f"\n❌ 错误 [{error.code.name}]",
        f"   {error.message}",
    ]

    if error.details:
        lines.append(f"\n详细信息:")
        for line in error.details.split('\n'):
            lines.append(f"   {line}")

    lines.append(f"\n退出码: {error.code}")
    return '\n'.join(lines)
```

---

## 4. 交互式 CLI 实现

### 决策

**使用 Click 内置功能 (`click.prompt`, `click.confirm`, `click.Choice`)**

### 理由

1. **零额外依赖**：Click 已是项目依赖，无需引入新库
2. **一致性**：与 Frago 现有 CLI 风格统一
3. **足够强大**：Click 提供的交互功能满足需求（选择、确认、输入）
4. **稳定性**：Click 是成熟库，文档完善，社区活跃
5. **维护成本低**：减少依赖数量，降低维护负担

### 考虑的替代方案

| 方案 | 优点 | 缺点 | 为何未采用 |
|------|------|------|-----------|
| **inquirer / questionary** | UI 更美观；支持复杂交互（多选列表） | 额外依赖；终端兼容性问题；样式与 Frago 不一致 | 过度设计；MVP 不需要复杂 UI |
| **simple-term-menu** | 轻量级；支持方向键选择 | 又一个依赖；Windows 支持不佳 | 依赖成本不值得 |
| **原生 input()** | 无依赖 | 无类型检查；无默认值；错误处理繁琐 | Click 已提供更好方案 |

### 实现指导

#### 交互式选择模式

```python
import click
from typing import Optional

def prompt_auth_method() -> str:
    """提示用户选择认证方式"""
    click.echo("\n🔐 请选择认证方式:\n")

    choice = click.prompt(
        "认证方式",
        type=click.Choice(["official", "custom"], case_sensitive=False),
        default="official",
        show_choices=True,
        show_default=True,
    )

    return choice.lower()

def confirm_install(component: str) -> bool:
    """询问是否安装组件"""
    return click.confirm(
        f"\n是否安装 {component}?",
        default=True,
    )

def prompt_api_key(provider: str) -> str:
    """提示输入 API Key"""
    return click.prompt(
        f"{provider} API Key",
        hide_input=True,  # 隐藏输入
        confirmation_prompt=False,
        type=str,
    )

def prompt_custom_endpoint() -> Optional[str]:
    """提示输入自定义端点 URL"""
    url = click.prompt(
        "自定义端点 URL (留空使用默认)",
        default="",
        type=str,
        show_default=False,
    )
    return url if url else None
```

#### Ctrl+C 信号处理

```python
import signal
import sys
from pathlib import Path

class GracefulInterruptHandler:
    """优雅处理 Ctrl+C 中断"""

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.interrupted = False

        # 注册信号处理器
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """信号处理器"""
        if self.interrupted:
            # 第二次 Ctrl+C 强制退出
            click.echo("\n\n强制退出（未保存状态）")
            sys.exit(130)  # 128 + SIGINT

        self.interrupted = True
        click.echo("\n\n⚠️  检测到中断信号（Ctrl+C）")
        click.echo("正在保存进度...")

        # 保存状态逻辑在调用方实现
        # 这里仅标记中断状态
        raise KeyboardInterrupt("User interrupted")

# 使用示例
def init_command():
    state_file = Path.home() / ".frago" / ".init_state.json"
    handler = GracefulInterruptHandler(state_file)

    try:
        # 执行 init 流程
        ...
    except KeyboardInterrupt:
        if handler.interrupted:
            # 保存临时状态
            save_temp_state(state_file, current_step)
            click.echo("进度已保存。下次运行 'frago init' 时可继续。")
            sys.exit(2)  # USER_CANCELLED
```

---

## 5. 配置文件版本兼容性

### 决策

**使用 `schema_version` 字段 + Pydantic 默认值机制**

### 理由

1. **前向兼容**：新版本可读取旧配置文件
2. **自动迁移**：Pydantic 的默认值自动填充缺失字段
3. **可追踪性**：schema_version 记录配置文件格式版本
4. **验证严格**：Pydantic 确保配置文件类型正确
5. **迁移可控**：需要破坏性变更时可通过版本号触发迁移逻辑

### 配置文件版本策略

| schema_version | 变更内容 | 兼容性 |
|---------------|---------|--------|
| **1.0** | 初始版本（MVP） | N/A |
| **1.1** | 新增可选字段（如 `ccr_config_path`） | ✅ 向后兼容（使用默认值） |
| **2.0** | 重命名字段（如 `auth_method` → `authentication_type`） | ⚠️ 需要迁移脚本 |

### 实现指导

#### Pydantic 配置模型

```python
from pydantic import BaseModel, Field, validator
from typing import Optional, Literal
from datetime import datetime
from pathlib import Path
import json

class APIEndpoint(BaseModel):
    """API 端点配置"""
    type: Literal["deepseek", "aliyun", "m2", "custom"]
    url: Optional[str] = None
    api_key: str

    @validator("url")
    def validate_url(cls, v, values):
        """验证 URL 必填性"""
        if values.get("type") == "custom" and not v:
            raise ValueError("Custom endpoint requires URL")
        return v

class Config(BaseModel):
    """Frago 配置"""
    schema_version: str = "1.0"

    # 依赖信息
    node_version: Optional[str] = None
    node_path: Optional[str] = None
    npm_version: Optional[str] = None
    claude_code_version: Optional[str] = None
    claude_code_path: Optional[str] = None

    # 认证配置（互斥）
    auth_method: Literal["official", "custom"] = "official"
    api_endpoint: Optional[APIEndpoint] = None

    # 可选功能
    ccr_enabled: bool = False
    ccr_config_path: Optional[str] = None  # v1.1 新增

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    init_completed: bool = False

    @validator("api_endpoint")
    def validate_auth_consistency(cls, v, values):
        """验证认证配置一致性"""
        if values.get("auth_method") == "custom" and not v:
            raise ValueError("Custom auth requires api_endpoint")
        if values.get("auth_method") == "official" and v:
            raise ValueError("Official auth cannot have api_endpoint")
        return v

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }

def load_config(config_file: Path) -> Config:
    """加载配置文件（带版本兼容）"""
    if not config_file.exists():
        return Config()

    try:
        with open(config_file, 'r') as f:
            data = json.load(f)

        # 检查版本并迁移
        schema_version = data.get("schema_version", "1.0")
        if schema_version != "1.0":
            data = migrate_config(data, schema_version)

        return Config(**data)
    except Exception as e:
        # 配置文件损坏，备份后创建新配置
        backup_file = config_file.with_suffix(".json.bak")
        config_file.rename(backup_file)
        click.echo(f"配置文件损坏，已备份到: {backup_file}")
        return Config()

def save_config(config: Config, config_file: Path):
    """保存配置文件"""
    config.updated_at = datetime.now()
    config_file.parent.mkdir(parents=True, exist_ok=True)

    with open(config_file, 'w') as f:
        json.dump(config.dict(), f, indent=2, default=str)

def migrate_config(data: dict, from_version: str) -> dict:
    """配置文件迁移"""
    # 未来版本的迁移逻辑
    if from_version == "1.1" and "ccr_config_path" not in data:
        data["ccr_config_path"] = None

    return data
```

---

## 6. 临时状态文件的生命周期管理

### 决策

**按需创建 + 成功后删除 + 7天自动过期**

### 理由

1. **简洁性**：成功完成后自动清理，避免文件累积
2. **恢复友好**：保留 7 天窗口期，用户有足够时间恢复
3. **防止陈旧**：过期自动忽略，避免误恢复到旧状态
4. **主动控制**：提供 `--reset` 选项手动清理

### 状态文件生命周期

| 阶段 | 操作 | 文件状态 |
|------|------|---------|
| **流程开始** | 创建 `.init_state.json` | 空状态 |
| **每步完成** | 更新 `completed_steps` | 追加步骤名 |
| **Ctrl+C 中断** | 保存当前进度 + 标记 `recoverable=true` | 保留文件 |
| **安装失败** | 不保存状态（直接退出） | 不创建或删除文件 |
| **成功完成** | 删除 `.init_state.json` | 文件消失 |
| **7 天后** | 检测到过期状态 | 忽略并删除 |
| **--reset 选项** | 手动删除状态文件 | 文件消失 |

### 实现指导

#### 临时状态模型

```python
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import List, Optional
from pathlib import Path
import json

class TemporaryState(BaseModel):
    """临时状态（Ctrl+C 恢复用）"""
    completed_steps: List[str] = []
    current_step: Optional[str] = None
    interrupted_at: datetime = Field(default_factory=datetime.now)
    recoverable: bool = True

    def is_expired(self, days: int = 7) -> bool:
        """检查是否过期"""
        return datetime.now() - self.interrupted_at > timedelta(days=days)

    def add_step(self, step: str):
        """记录完成步骤"""
        if step not in self.completed_steps:
            self.completed_steps.append(step)

    def set_current_step(self, step: str):
        """设置当前步骤"""
        self.current_step = step

def load_temp_state(state_file: Path) -> Optional[TemporaryState]:
    """加载临时状态（如果存在且未过期）"""
    if not state_file.exists():
        return None

    try:
        with open(state_file, 'r') as f:
            data = json.load(f)

        state = TemporaryState(**data)

        # 检查过期
        if state.is_expired():
            click.echo("检测到过期的临时状态（7天前），已忽略。")
            state_file.unlink()
            return None

        # 检查可恢复性
        if not state.recoverable:
            click.echo("上次运行因错误终止，无法恢复。")
            state_file.unlink()
            return None

        return state

    except Exception as e:
        click.echo(f"加载临时状态失败: {e}")
        state_file.unlink()
        return None

def save_temp_state(state: TemporaryState, state_file: Path):
    """保存临时状态"""
    state_file.parent.mkdir(parents=True, exist_ok=True)

    with open(state_file, 'w') as f:
        json.dump(state.dict(), f, indent=2, default=str)

def delete_temp_state(state_file: Path):
    """删除临时状态文件"""
    if state_file.exists():
        state_file.unlink()

def prompt_resume(state: TemporaryState) -> bool:
    """询问用户是否恢复"""
    click.echo("\n⚠️  检测到未完成的初始化")
    click.echo(f"   上次中断于: {state.interrupted_at.strftime('%Y-%m-%d %H:%M:%S')}")
    click.echo(f"   已完成步骤: {len(state.completed_steps)}")
    click.echo(f"   当前步骤: {state.current_step or '未知'}\n")

    return click.confirm("是否从上次中断处继续?", default=True)
```

---

## 总结

所有研究任务已完成，关键决策总结：

1. ✅ **Windows 支持**：仅检测 + 手动安装指引（MVP）
2. ✅ **并行检查**：ThreadPoolExecutor + subprocess
3. ✅ **错误处理**：分层错误码 + CommandError 封装
4. ✅ **交互式 CLI**：Click 内置功能（无额外依赖）
5. ✅ **配置兼容性**：schema_version + Pydantic 默认值
6. ✅ **状态管理**：按需创建 + 成功后删除 + 7天过期

**下一步**: 进入 Phase 1 - 设计与契约，生成 `data-model.md` 和 `contracts/` 文件。
