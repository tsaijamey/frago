# Data Model: 重构CDP集成

**Branch**: `002-cdp-integration-refactor` | **Date**: 2025-11-16 | **Spec**: [spec.md](./spec.md)

## 核心数据模型

### 1. CDP配置模型

```python
class CDPConfig(BaseModel):
    """CDP配置数据模型"""
    
    # 基础连接配置
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=9222)
    
    # 超时配置
    connect_timeout: float = Field(default=30.0)
    command_timeout: float = Field(default=60.0)
    
    # 重试配置
    max_retries: int = Field(default=3)
    retry_delay: float = Field(default=1.0)
    
    # 日志配置
    log_level: str = Field(default="INFO")
    debug: bool = Field(default=False)
    
    # 新增: 代理配置
    proxy_host: Optional[str] = None
    proxy_port: Optional[int] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None
    no_proxy: bool = Field(default=False, description="是否绕过代理")
    
    # 计算属性
    @property
    def websocket_url(self) -> str:
        return f"ws://{self.host}:{self.port}/devtools/browser"
    
    @property
    def http_url(self) -> str:
        return f"http://{self.host}:{self.port}"
```

### 2. 功能映射模型

```python
@dataclass
class FunctionMapping:
    """功能映射数据模型"""
    
    shell_script: str
    python_module: str
    python_function: str
    implemented: bool
    behavior_consistent: bool
    parameters_match: bool
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "shell_script": self.shell_script,
            "python_module": self.python_module,
            "python_function": self.python_function,
            "implemented": self.implemented,
            "behavior_consistent": self.behavior_consistent,
            "parameters_match": self.parameters_match
        }


class FunctionMappingReport:
    """功能映射报告"""
    
    def __init__(self):
        self.mappings: List[FunctionMapping] = []
        self.total_functions: int = 0
        self.implemented_count: int = 0
        self.consistent_count: int = 0
        
    def add_mapping(self, mapping: FunctionMapping):
        self.mappings.append(mapping)
        self.total_functions += 1
        if mapping.implemented:
            self.implemented_count += 1
        if mapping.behavior_consistent:
            self.consistent_count += 1
    
    def get_coverage(self) -> float:
        return (self.implemented_count / self.total_functions) * 100 if self.total_functions > 0 else 0.0
    
    def get_consistency(self) -> float:
        return (self.consistent_count / self.implemented_count) * 100 if self.implemented_count > 0 else 0.0
```

### 3. 代理配置模型

```python
@dataclass
class ProxyConfig:
    """代理配置数据模型"""
    
    enabled: bool
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    no_proxy_hosts: List[str] = field(default_factory=list)
    
    def get_websocket_proxy_config(self) -> Dict[str, Any]:
        """获取WebSocket代理配置"""
        if not self.enabled or self.no_proxy:
            return {}
        
        config = {}
        if self.host and self.port:
            config["http_proxy_host"] = self.host
            config["http_proxy_port"] = self.port
            
        if self.username and self.password:
            config["http_proxy_auth"] = (self.username, self.password)
            
        return config
    
    @property
    def no_proxy(self) -> bool:
        """是否绕过代理"""
        return not self.enabled or len(self.no_proxy_hosts) > 0
```

## 数据流分析

### 1. CDP连接数据流

```
用户输入/Shell脚本 → CLI参数 → CDPConfig → CDPSession → WebSocket连接
```

**关键数据转换**:
- Shell脚本参数 → Python CLI参数
- CLI参数 → CDPConfig实例
- CDPConfig → WebSocket连接配置

### 2. 功能映射数据流

```
Shell脚本扫描 → 功能清单 → Python代码扫描 → 功能清单 → 映射分析 → 报告生成
```

**关键数据**:
- Shell脚本功能签名
- Python函数签名
- 参数类型和数量
- 返回值类型

### 3. 代理配置数据流

```
环境变量/CLI参数 → ProxyConfig → WebSocket代理配置 → 连接建立
```

**关键配置项**:
- HTTP_PROXY, HTTPS_PROXY 环境变量
- --no-proxy CLI参数
- 代理认证信息

## 数据验证规则

### 1. CDP配置验证

```python
def validate_cdp_config(config: CDPConfig) -> List[str]:
    """验证CDP配置"""
    errors = []
    
    # 主机验证
    if not config.host or config.host.strip() == "":
        errors.append("主机地址不能为空")
    
    # 端口验证
    if config.port < 1 or config.port > 65535:
        errors.append("端口必须在1-65535范围内")
    
    # 超时验证
    if config.connect_timeout <= 0:
        errors.append("连接超时必须大于0")
    
    if config.command_timeout <= 0:
        errors.append("命令超时必须大于0")
    
    # 代理验证
    if config.proxy_host and not config.proxy_port:
        errors.append("代理主机必须指定端口")
    
    return errors
```

### 2. 功能映射验证

```python
def validate_function_mapping(mapping: FunctionMapping) -> List[str]:
    """验证功能映射"""
    errors = []
    
    if not mapping.shell_script:
        errors.append("Shell脚本名称不能为空")
    
    if mapping.implemented and not mapping.python_function:
        errors.append("已实现的函数必须指定Python函数名")
    
    return errors
```

## 数据持久化

### 1. 配置持久化

- **环境变量**: 支持通过环境变量设置代理配置
- **配置文件**: 支持 `.env` 文件配置
- **CLI参数**: 支持命令行参数覆盖

### 2. 映射报告持久化

- **JSON格式**: 功能映射报告保存为JSON文件
- **HTML报告**: 生成可视化的HTML报告
- **控制台输出**: 实时显示验证进度和结果

## 数据关系图

```
CDPConfig ────┐
              ├── CDPSession ──── WebSocket连接
ProxyConfig ──┘
              
FunctionMapping ─── FunctionMappingReport
    │
    ├── Shell脚本功能
    └── Python函数实现
```

这个数据模型为CDP集成重构提供了清晰的数据结构和验证规则，确保功能统一和代理参数的正确使用。