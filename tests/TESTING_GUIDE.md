# Frago Init 功能测试指南

**当前完成进度**: Phase 1-2 (基础架构) ✅
**测试覆盖率**: 100% (frago.init 模块)
**测试数量**: 31 个单元测试全部通过

---

## 🎯 当前可以测试的功能

### 1. 数据模型 (Models)

#### Config - 配置管理
- ✅ 创建默认配置
- ✅ 添加 Node.js/npm 版本信息
- ✅ 添加 Claude Code 版本信息
- ✅ 官方认证配置
- ✅ 自定义 API 端点配置（Deepseek/Aliyun/M2/自定义）
- ✅ 认证方式互斥性验证
- ✅ JSON 序列化和反序列化

#### APIEndpoint - API 端点配置
- ✅ 预设端点类型（deepseek, aliyun, m2）
- ✅ 自定义端点（必须提供 URL）
- ✅ API Key 管理

#### TemporaryState - 临时状态恢复
- ✅ 记录已完成步骤
- ✅ 设置当前步骤
- ✅ 检查步骤是否完成
- ✅ 过期检查（7天自动失效）

#### InstallationStep - 安装步骤状态机
- ✅ 状态转换：pending → in_progress → completed/failed/skipped
- ✅ 记录开始/完成时间
- ✅ 记录错误信息和错误码

#### DependencyCheckResult - 依赖检查结果
- ✅ 检测依赖是否安装
- ✅ 检测版本是否满足要求
- ✅ 生成状态显示（✅/⚠️/❌）

### 2. 异常处理 (Exceptions)

#### InitErrorCode - 错误码
- ✅ SUCCESS (0)
- ✅ INSTALL_FAILED (1)
- ✅ USER_CANCELLED (2)
- ✅ CONFIG_ERROR (3)
- ✅ COMMAND_NOT_FOUND (10)
- ✅ VERSION_INSUFFICIENT (11)
- ✅ PERMISSION_ERROR (12)
- ✅ NETWORK_ERROR (13)
- ✅ INSTALL_ERROR (14)

#### CommandError - 命令执行错误
- ✅ 错误消息格式化
- ✅ 错误详情显示
- ✅ 异常抛出和捕获

---

## 🧪 运行测试

### 快速测试命令

```bash
# 1. 运行所有单元测试
uv run pytest tests/unit/init/ -v

# 2. 运行手动交互测试
uv run python tests/manual_test_models.py

# 3. 查看测试覆盖率
uv run pytest tests/unit/init/ --cov=frago.init --cov-report=term-missing

# 4. 生成 HTML 覆盖率报告
uv run pytest tests/unit/init/ --cov=frago.init --cov-report=html
# 查看报告: open htmlcov/index.html
```

### 详细测试场景

#### 场景 1: 测试配置创建

```python
from frago.init.models import Config, APIEndpoint

# 默认配置
config = Config()
print(f"认证方式: {config.auth_method}")  # official

# 自定义端点配置
config = Config(
    auth_method="custom",
    api_endpoint=APIEndpoint(
        type="deepseek",
        api_key="sk-your-key"
    )
)
```

#### 场景 2: 测试临时状态恢复

```python
from frago.init.models import TemporaryState

# 创建临时状态
state = TemporaryState()

# 记录步骤
state.add_step("check_dependencies")
state.add_step("install_node")
state.set_current_step("install_claude_code")

# 检查进度
print(f"已完成: {state.completed_steps}")
print(f"当前: {state.current_step}")

# 检查是否过期
print(f"过期? {state.is_expired(days=7)}")
```

#### 场景 3: 测试安装步骤状态机

```python
from frago.init.models import InstallationStep

# 创建步骤
step = InstallationStep(name="install_node")

# 开始执行
step.start()
print(f"状态: {step.status.value}")  # in_progress

# 成功完成
step.complete()
print(f"状态: {step.status.value}")  # completed

# 或者失败
# step.fail("Network timeout", 13)
```

#### 场景 4: 测试依赖检查

```python
from frago.init.models import DependencyCheckResult

# 检查未安装的依赖
result = DependencyCheckResult(
    name="node",
    installed=False,
    required_version="20.0.0"
)

print(result.display_status())  # ❌ node: 未安装
print(result.needs_install())   # True
```

#### 场景 5: 测试异常处理

```python
from frago.init.exceptions import CommandError, InitErrorCode

try:
    raise CommandError(
        "Permission denied",
        InitErrorCode.PERMISSION_ERROR,
        details="需要 sudo 权限"
    )
except CommandError as e:
    print(f"错误码: {e.code}")
    print(f"消息: {e.message}")
    print(str(e))
```

#### 场景 6: 测试 JSON 持久化

```python
from frago.init.models import Config, APIEndpoint
import json

# 创建配置
config = Config(
    node_version="20.11.0",
    auth_method="custom",
    api_endpoint=APIEndpoint(
        type="deepseek",
        api_key="sk-test"
    )
)

# 序列化
config_dict = config.model_dump()
config_json = json.dumps(config_dict, indent=2, default=str)

# 反序列化
loaded_config = Config.model_validate(json.loads(config_json))

print(f"版本匹配? {loaded_config.node_version == config.node_version}")
```

---

## 📊 测试结果

### 单元测试统计

```
测试文件: 2
测试类: 8
测试用例: 31
通过率: 100%
覆盖率: 100% (frago.init 模块)
```

### 覆盖的模块

| 模块 | 语句数 | 覆盖率 | 说明 |
|------|--------|--------|------|
| `frago.init.__init__.py` | 3 | 100% | 模块导出 |
| `frago.init.models.py` | 93 | 100% | 所有数据模型 |
| `frago.init.exceptions.py` | 23 | 100% | 异常类 |

---

## ❌ 尚未实现的功能

以下功能在 Phase 3 中实现，目前无法测试：

### 1. 依赖检查器 (checker.py)
- ❌ check_node() - 检测 Node.js 版本
- ❌ check_claude_code() - 检测 Claude Code
- ❌ parallel_dependency_check() - 并行检查

### 2. 安装器 (installer.py)
- ❌ run_external_command() - 外部命令执行
- ❌ install_node() - 安装 Node.js
- ❌ install_claude_code() - 安装 Claude Code

### 3. CLI 命令 (init_command.py)
- ❌ frago init 命令
- ❌ --reset, --show-config, --skip-deps 选项
- ❌ 交互式配置流程

### 4. 集成测试
- ❌ 完整初始化流程测试
- ❌ Ctrl+C 恢复测试
- ❌ 错误场景测试

---

## 🚀 下一步

继续实施 Phase 3 (User Story 1 - MVP):

1. **实现依赖检查器** - 并行检查 Node.js 和 Claude Code
2. **实现安装器** - 智能安装缺失组件
3. **实现 CLI 命令** - `frago init` 主命令
4. **集成测试** - 测试完整流程

运行以下命令继续实施：

```bash
# 继续运行 /speckit.implement 命令
# 或手动按照 tasks.md 中的任务列表实现
```

---

## 📚 参考文档

- **规格说明**: `specs/006-init-command/spec.md`
- **实施计划**: `specs/006-init-command/plan.md`
- **数据模型**: `specs/006-init-command/data-model.md`
- **任务列表**: `specs/006-init-command/tasks.md`
- **CLI 契约**: `specs/006-init-command/contracts/cli_commands.md`

---

**测试报告生成时间**: 2025-11-25
**当前分支**: 006-init-command
**基础架构状态**: ✅ 就绪
