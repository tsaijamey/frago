# Research: 重构CDP集成

**Branch**: `002-cdp-integration-refactor` | **Date**: 2025-11-16 | **Spec**: [spec.md](./spec.md)

## 技术未知项分析

### 1. 当前Python实现状态

**发现**:
- Python CDP实现已存在，位于 `src/frago/cdp/`
- 包含基础客户端、会话管理、命令封装
- 已有导航、截图、JS执行等核心功能
- 使用 `websocket-client` 库进行WebSocket通信

**问题**:
- 代理参数使用未明确检查
- Python实现与Shell脚本功能对应关系不清晰
- 目录结构需要优化以更好对应Shell脚本

### 2. 代理参数使用分析

**Shell脚本**:
- 使用 `websocat` 工具进行WebSocket通信
- 通过环境变量和命令行参数处理代理
- 支持 `--no-proxy` 参数绕过代理

**Python实现**:
- 使用 `websocket-client` 库
- 当前配置中未明确处理代理参数
- `session.py:57-60` 中直接创建WebSocket连接

**解决方案**:
- 检查 `websocket-client` 的代理支持
- 在 `CDPConfig` 中添加代理相关配置
- 确保WebSocket连接正确处理代理环境

### 3. 功能对应关系分析

**Shell脚本功能清单** (18个):
- 基础操作: 导航、截图、JS执行、点击、滚动、等待、缩放、获取标题、获取内容、状态检查、帮助、通用函数
- 视觉效果: 高亮、指针动画、聚光灯、标注、清除效果
- 环境检查: Python环境检查

**Python实现现状**:
- `session.py` 中已实现大部分CLI便利方法
- `commands/` 目录包含基础CDP命令封装
- 部分视觉效果功能通过JavaScript注入实现

**功能映射差距**:
- 需要验证所有Shell脚本功能在Python中都有对应实现
- 确保行为一致性
- 建立功能映射验证机制

### 4. 目录结构优化

**当前结构**:
```
src/frago/cdp/
├── commands/
│   ├── page.py
│   ├── input.py  
│   ├── runtime.py
│   └── dom.py
└── session.py (包含CLI便利方法)
```

**优化建议**:
- 在 `commands/` 目录下按功能域组织
- 确保每个Shell脚本对应一个Python模块或方法
- 建立清晰的命名约定

## 技术决策

### 1. 代理参数处理

**决策**: 在 `CDPConfig` 中添加代理配置选项

```python
class CDPConfig(BaseModel):
    # 现有配置...
    proxy_host: Optional[str] = None
    proxy_port: Optional[int] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None
    no_proxy: bool = Field(default=False, description="是否绕过代理")
```

**实现**: 修改 `session.py` 中的WebSocket连接逻辑，支持代理配置

### 2. 功能映射验证

**决策**: 创建功能映射验证工具

- 扫描所有Shell脚本，提取功能清单
- 扫描Python实现，提取功能清单
- 对比两个清单，识别缺失或不一致的功能
- 生成功能映射报告

### 3. 目录结构统一

**决策**: 保持现有结构，但优化命令组织

- 在 `commands/` 目录下按功能类型组织
- 确保每个Shell脚本都有对应的Python模块
- 建立清晰的导入和调用路径

## 风险评估

### 低风险
- 目录结构调整 - 不影响现有API
- 代理参数添加 - 可选配置，不影响现有功能

### 中风险  
- 功能映射验证 - 可能发现现有实现问题
- 行为一致性 - 需要详细测试验证

### 高风险
- 向后兼容性 - 必须确保现有脚本继续工作
- WebSocket连接稳定性 - 代理配置可能影响连接可靠性

## 下一步行动

1. **Phase 1 设计**: 创建数据模型和API契约
2. **代理参数实现**: 在 `CDPConfig` 和 `session.py` 中添加代理支持
3. **功能映射工具**: 开发功能对应关系验证工具
4. **目录结构优化**: 按功能域重新组织命令模块
5. **测试验证**: 确保所有Shell脚本功能在Python中都有对应实现