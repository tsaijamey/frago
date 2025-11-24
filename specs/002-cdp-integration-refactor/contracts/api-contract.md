# API Contract: CDP集成重构

**Branch**: `002-cdp-integration-refactor` | **Date**: 2025-11-16 | **Spec**: [spec.md](./spec.md)

## 概述

本文档定义了CDP集成重构的API契约，确保Python实现和Shell脚本之间的功能一致性和向后兼容性。

## 核心API契约

### 1. CDP客户端契约

#### CDPClient 基类

```python
class CDPClient(ABC):
    """CDP客户端基础契约"""
    
    @property
    def connected(self) -> bool:
        """检查连接状态"""
        
    @abstractmethod
    def connect(self) -> None:
        """建立CDP连接"""
        
    @abstractmethod
    def disconnect(self) -> None:
        """断开CDP连接"""
        
    @abstractmethod
    def send_command(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """发送CDP命令"""
```

#### CDPSession 实现契约

```python
class CDPSession(CDPClient):
    """CDP会话实现契约"""
    
    def __init__(self, config: Optional[CDPConfig] = None):
        """初始化会话"""
        
    def health_check(self) -> bool:
        """执行连接健康检查"""
        
    # CLI便利方法契约
    def navigate(self, url: str) -> None:
        """导航到指定URL"""
        
    def click(self, selector: str, wait_timeout: int = 10) -> None:
        """点击指定选择器的元素"""
        
    def screenshot(self, output_file: str, full_page: bool = False, quality: int = 80) -> None:
        """截取页面截图并保存到文件"""
        
    def evaluate(self, script: str, return_by_value: bool = True) -> Any:
        """执行JavaScript代码"""
        
    def get_title(self) -> str:
        """获取页面标题"""
        
    def scroll(self, distance: int) -> None:
        """滚动页面"""
        
    def wait(self, seconds: float) -> None:
        """等待指定秒数"""
        
    def zoom(self, factor: float) -> None:
        """设置页面缩放比例"""
        
    def clear_effects(self) -> None:
        """清除所有视觉效果"""
        
    def highlight(self, selector: str, color: str = "yellow") -> None:
        """高亮显示指定元素"""
        
    def pointer(self, selector: str) -> None:
        """在元素上显示鼠标指针"""
        
    def spotlight(self, selector: str) -> None:
        """聚光灯效果显示元素"""
        
    def annotate(self, selector: str, text: str, position: str = "top") -> None:
        """在元素上添加标注"""
        
    def wait_for_selector(self, selector: str, timeout: Optional[float] = None) -> None:
        """等待选择器匹配的元素出现"""
```

### 2. CLI命令契约

#### 基础CLI选项

所有CLI命令必须支持以下基础选项：

```python
@click.option('--debug', is_flag=True, help='启用调试模式')
@click.option('--timeout', type=int, default=30, help='操作超时时间（秒）')
@click.option('--host', type=str, default='127.0.0.1', help='CDP主机地址')
@click.option('--port', type=int, default=9222, help='CDP端口')
@click.option('--proxy-host', type=str, help='代理主机')
@click.option('--proxy-port', type=int, help='代理端口')
@click.option('--no-proxy', is_flag=True, help='绕过代理')
```

#### 具体命令契约

```python
# 导航命令
@click.command()
@click.argument('url')
@click.option('--wait-for', help='等待元素选择器')
def navigate(url: str, wait_for: Optional[str] = None):
    """导航到指定URL"""

# 截图命令
@click.command()
@click.argument('output_file')
@click.option('--full-page', is_flag=True, help='截取完整页面')
@click.option('--quality', type=int, default=80, help='图片质量(0-100)')
def screenshot(output_file: str, full_page: bool = False, quality: int = 80):
    """截取页面截图"""

# JavaScript执行命令
@click.command()
@click.argument('script')
@click.option('--return-by-value', is_flag=True, help='按值返回结果')
def execute_javascript(script: str, return_by_value: bool = True):
    """执行JavaScript代码"""

# 点击命令
@click.command()
@click.argument('selector')
@click.option('--wait-timeout', type=int, default=10, help='等待元素超时时间')
def click_element(selector: str, wait_timeout: int = 10):
    """点击指定选择器的元素"""

# 滚动命令
@click.command()
@click.argument('distance', type=int)
def scroll(distance: int):
    """滚动页面"""

# 等待命令
@click.command()
@click.argument('seconds', type=float)
def wait(seconds: float):
    """等待指定秒数"""

# 缩放命令
@click.command()
@click.argument('factor', type=float)
def zoom(factor: float):
    """设置页面缩放比例"""

# 视觉效果命令
@click.command()
def clear_effects():
    """清除所有视觉效果"""

@click.command()
@click.argument('selector')
@click.option('--color', default='yellow', help='高亮颜色')
def highlight(selector: str, color: str = 'yellow'):
    """高亮显示指定元素"""

@click.command()
@click.argument('selector')
def pointer(selector: str):
    """在元素上显示鼠标指针"""

@click.command()
@click.argument('selector')
def spotlight(selector: str):
    """聚光灯效果显示元素"""

@click.command()
@click.argument('selector')
@click.argument('text')
@click.option('--position', default='top', help='标注位置')
def annotate(selector: str, text: str, position: str = 'top'):
    """在元素上添加标注"""

# 信息获取命令
@click.command()
def get_title():
    """获取页面标题"""

@click.command()
@click.option('--selector', help='元素选择器')
def get_content(selector: Optional[str] = None):
    """获取页面或元素内容"""

@click.command()
def status():
    """检查CDP状态"""
```

### 3. Shell脚本契约

#### 基础脚本结构

所有Shell脚本必须遵循以下结构：

```bash
#!/bin/bash
# 脚本头注释说明功能

# 加载通用函数
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/cdp_common.sh"

# 参数解析
while [[ $# -gt 0 ]]; do
    case $1 in
        --debug)
            DEBUG="--debug"
            shift
            ;;
        --timeout)
            TIMEOUT="--timeout $2"
            shift 2
            ;;
        --host)
            HOST="--host $2"
            shift 2
            ;;
        --port)
            PORT="--port $2"
            shift 2
            ;;
        --proxy-host)
            PROXY_HOST="--proxy-host $2"
            shift 2
            ;;
        --proxy-port)
            PROXY_PORT="--proxy-port $2"
            shift 2
            ;;
        --no-proxy)
            NO_PROXY="--no-proxy"
            shift
            ;;
        # 脚本特定参数
        *)
            # 处理脚本特定参数
            ;;
    esac
done

# 调用Python CLI
PYTHON_CMD="python -m frago.cli command-name ${SPECIFIC_ARGS} ${DEBUG} ${TIMEOUT} ${HOST} ${PORT} ${PROXY_HOST} ${PROXY_PORT} ${NO_PROXY}"
eval "$PYTHON_CMD"
```

#### 参数映射契约

Shell脚本参数必须与Python CLI参数一一对应：

| Shell参数 | Python CLI参数 | 说明 |
|-----------|----------------|------|
| `--debug` | `--debug` | 调试模式 |
| `--timeout <seconds>` | `--timeout <seconds>` | 超时时间 |
| `--host <host>` | `--host <host>` | CDP主机 |
| `--port <port>` | `--port <port>` | CDP端口 |
| `--proxy-host <host>` | `--proxy-host <host>` | 代理主机 |
| `--proxy-port <port>` | `--proxy-port <port>` | 代理端口 |
| `--no-proxy` | `--no-proxy` | 绕过代理 |

### 4. 错误处理契约

#### 退出代码

所有脚本和命令必须使用一致的退出代码：

| 退出代码 | 含义 |
|----------|------|
| 0 | 成功 |
| 1 | 参数错误 |
| 2 | 连接错误 |
| 3 | 超时错误 |
| 4 | 执行错误 |
| 5 | 环境错误 |

#### 错误消息格式

```python
# Python错误消息格式
raise CDPError("错误类型: 具体错误描述")

# Shell脚本错误消息格式
echo "错误: 具体错误描述" >&2
exit 错误代码
```

### 5. 配置契约

#### 环境变量

| 环境变量 | 用途 | 默认值 |
|----------|------|--------|
| `FRAGO_LOG_LEVEL` | 日志级别 | `INFO` |
| `FRAGO_CDP_HOST` | CDP主机 | `127.0.0.1` |
| `FRAGO_CDP_PORT` | CDP端口 | `9222` |
| `HTTP_PROXY` | HTTP代理 | 无 |
| `HTTPS_PROXY` | HTTPS代理 | 无 |
| `NO_PROXY` | 绕过代理的主机 | 无 |

#### 配置文件

支持 `.env` 文件配置：

```env
FRAGO_LOG_LEVEL=DEBUG
FRAGO_CDP_HOST=localhost
FRAGO_CDP_PORT=9222
HTTP_PROXY=http://proxy.example.com:8080
NO_PROXY=localhost,127.0.0.1
```

## 向后兼容性保证

### 1. Shell脚本兼容性

- 所有现有Shell脚本必须继续工作
- 新增参数必须是可选的
- 默认行为必须保持不变

### 2. Python API兼容性

- 现有公共API必须保持稳定
- 新增方法必须向后兼容
- 参数变更必须提供默认值

### 3. 行为一致性

- Python实现和Shell脚本的行为必须一致
- 错误处理和退出代码必须一致
- 输出格式必须一致

## 验证机制

### 1. 功能映射验证

```python
def validate_function_mapping() -> FunctionMappingReport:
    """验证功能映射一致性"""
    

def test_shell_python_equivalence() -> bool:
    """测试Shell和Python行为等价性"""
```

### 2. 代理配置验证

```python
def test_proxy_configuration() -> bool:
    """测试代理配置正确性"""
    

def test_no_proxy_behavior() -> bool:
    """测试绕过代理行为"""
```

这个API契约确保了CDP集成重构的功能一致性和向后兼容性，为开发和测试提供了明确的规范。