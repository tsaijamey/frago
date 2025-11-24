# Quickstart: 重构CDP集成

**Branch**: `002-cdp-integration-refactor` | **Date**: 2025-11-16 | **Spec**: [spec.md](./spec.md)

## 概述

本快速入门指南介绍如何验证和实现CDP集成的重构，确保Python实现与Shell脚本功能一致，并正确使用代理参数。

## 环境准备

### 1. 检查当前环境

```bash
# 检查Python环境
cd /Users/chagee/Repos/Frago
source .venv/bin/activate

# 检查依赖
python -c "import websocket; import click; print('依赖检查通过')"

# 检查Chrome CDP连接
./scripts/share/cdp_status.sh
```

### 2. 验证现有功能

```bash
# 测试基础导航功能
./scripts/share/cdp_navigate.sh https://www.google.com

# 测试Python CLI对应功能
python -m frago.cli navigate https://www.google.com
```

## 功能映射验证

### 1. 运行功能映射工具

```bash
# 生成功能映射报告
python -m frago.tools.function_mapping

# 输出示例:
# ================================
# 功能映射验证报告
# ================================
# 总功能数: 18
# 已实现: 15 (83.3%)
# 行为一致: 12 (80.0%)
# ================================
```

### 2. 查看详细报告

```bash
# 生成详细HTML报告
python -m frago.tools.function_mapping --format html --output function_mapping_report.html

# 在浏览器中查看报告
open function_mapping_report.html
```

## 代理参数测试

### 1. 测试代理环境

```bash
# 设置代理环境变量
export HTTP_PROXY=http://proxy.example.com:8080
export HTTPS_PROXY=http://proxy.example.com:8080

# 测试有代理环境下的连接
./scripts/share/cdp_navigate.sh https://www.google.com

# 测试绕过代理
./scripts/share/cdp_navigate.sh https://www.google.com --no-proxy
```

### 2. 验证Python代理支持

```bash
# 测试Python CLI代理支持
python -m frago.cli navigate https://www.google.com --proxy-host proxy.example.com --proxy-port 8080

# 测试绕过代理
python -m frago.cli navigate https://www.google.com --no-proxy
```

## 开发工作流

### 1. 添加新功能

```python
# 1. 在 src/frago/cdp/commands/ 下创建新模块
# 例如: src/frago/cdp/commands/new_feature.py

# 2. 实现功能类
class NewFeatureCommands:
    def __init__(self, session):
        self.session = session
    
    def new_function(self, param1: str, param2: int) -> Dict[str, Any]:
        """新功能实现"""
        # 实现逻辑
        pass

# 3. 在 session.py 中添加便利方法
class CDPSession(CDPClient):
    # ... 现有代码 ...
    
    def new_function(self, param1: str, param2: int) -> None:
        """新功能便利方法"""
        self.new_feature.new_function(param1, param2)
    
    @property
    def new_feature(self):
        if self._new_feature is None:
            from .commands.new_feature import NewFeatureCommands
            self._new_feature = NewFeatureCommands(self)
        return self._new_feature
```

### 2. 创建对应Shell脚本

```bash
#!/bin/bash
# scripts/share/cdp_new_feature.sh

# 加载通用函数
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/cdp_common.sh"

# 解析参数
PARAM1=""
PARAM2=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --param1)
            PARAM1="$2"
            shift 2
            ;;
        --param2)
            PARAM2="$2"
            shift 2
            ;;
        -*)
            echo "错误: 未知选项 $1"
            exit 1
            ;;
        *)
            echo "错误: 未知参数 $1"
            exit 1
            ;;
    esac
done

# 调用Python CLI
python -m frago.cli new-feature --param1 "${PARAM1}" --param2 "${PARAM2}"
```

### 3. 注册CLI命令

```python
# 在 src/frago/cli/commands.py 中添加
@click.command()
@click.option('--param1', required=True, help='参数1说明')
@click.option('--param2', type=int, default=0, help='参数2说明')
@click.pass_context
def new_feature(ctx, param1: str, param2: int):
    """新功能命令"""
    config = CDPConfig(
        host=ctx.obj['HOST'],
        port=ctx.obj['PORT'],
        timeout=ctx.obj['TIMEOUT']
    )
    
    with CDPSession(config) as session:
        session.new_function(param1, param2)

# 在 src/frago/cli/main.py 中注册
cli.add_command(new_feature)
```

## 测试验证

### 1. 单元测试

```bash
# 运行所有测试
pytest tests/

# 运行特定测试
pytest tests/unit/test_cdp_session.py -v
pytest tests/integration/test_function_mapping.py -v
```

### 2. 集成测试

```bash
# 测试功能一致性
./scripts/test/function_consistency.sh

# 测试代理配置
./scripts/test/proxy_configuration.sh
```

### 3. 性能测试

```bash
# 测试CDP连接性能
./scripts/benchmark/cdp_connection.sh

# 测试功能执行性能
./scripts/benchmark/function_execution.sh
```

## 故障排除

### 1. 常见问题

**问题**: CDP连接失败
```bash
# 检查Chrome是否运行在CDP模式
ps aux | grep chrome

# 检查端口是否被占用
lsof -i :9222

# 重启Chrome CDP模式
./scripts/start_chrome_cdp.sh
```

**问题**: 代理连接失败
```bash
# 检查代理设置
env | grep -i proxy

# 测试代理连接
curl -x http://proxy.example.com:8080 https://www.google.com

# 使用无代理测试
./scripts/share/cdp_navigate.sh https://www.google.com --no-proxy
```

**问题**: 功能不一致
```bash
# 重新生成功能映射报告
python -m frago.tools.function_mapping --verbose

# 检查具体功能差异
python -m frago.tools.function_mapping --function cdp_navigate
```

### 2. 调试模式

```bash
# 启用详细日志
./scripts/share/cdp_navigate.sh https://www.google.com --debug

# Python CLI调试模式
python -m frago.cli navigate https://www.google.com --debug

# 设置日志级别
export FRAGO_LOG_LEVEL=DEBUG
```

## 下一步

完成快速入门后，您可以：

1. **查看详细文档**: 阅读 [spec.md](./spec.md) 和 [plan.md](./plan.md)
2. **运行完整测试**: 执行完整的测试套件
3. **贡献代码**: 按照开发工作流添加新功能
4. **报告问题**: 使用功能映射工具识别和报告功能不一致问题

这个快速入门指南帮助您快速验证CDP集成重构的状态，并提供了开发和测试的标准工作流。