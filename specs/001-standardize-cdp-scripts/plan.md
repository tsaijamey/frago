# Implementation Plan: CDP控制系统Python重构

**Branch**: `001-standardize-cdp-scripts` | **Date**: 2025-11-16 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-standardize-cdp-scripts/spec.md`

**Note**: 根据澄清会话更新 - 从Shell脚本迁移到Python实现

## Summary

将项目中所有CDP Shell脚本重构为Python实现，创建面向对象的CDP客户端库。采用一次性重写策略，使用uv+pyproject.toml管理依赖，实现可配置的错误重试机制（默认3次，指数退避）。保留Shell包装器以确保CLI接口兼容性。

## Technical Context

**Language/Version**: Python 3.8+  
**Primary Dependencies**: websocket-client, click (CLI), pydantic (类型安全)  
**Package Manager**: uv + pyproject.toml  
**Architecture**: 面向对象（Session类 + 命令方法）  
**Testing**: pytest + unittest.mock  
**Target Platform**: macOS/Linux/Windows (跨平台)  
**Project Type**: Python包 + Shell CLI包装器  
**Performance Goals**: WebSocket持久连接，减少90% JSON处理开销  
**Constraints**: 保持CLI向后兼容，支持同步调用  
**Scale/Scope**: 约17个CDP脚本需要重写

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

基于更新后的技术决策：

- ✅ **Python实现**: 使用Python 3.8+，面向对象设计
- ✅ **标准化CDP协议**: 通过WebSocket协议直接通信  
- ✅ **依赖管理**: uv + pyproject.toml现代化管理
- ✅ **错误处理**: 可配置重试机制，结构化异常
- ✅ **测试覆盖**: pytest单元测试，类型安全

## Project Structure

### Documentation (this feature)

```text
specs/001-standardize-cdp-scripts/
├── plan.md              # 本文件（更新后的实施计划）
├── spec.md              # 功能规格（已更新）
├── research.md          # Python CDP库研究
├── data-model.md        # CDP Session类设计
├── quickstart.md        # 快速开始指南
├── contracts/           # API接口定义
│   ├── cdp_session.py   # Session类接口
│   └── commands.py      # CDP命令接口
└── tasks.md             # 实施任务清单
```

### Source Code (repository root)

```text
# Python CDP库项目结构
frago/
├── pyproject.toml        # 项目配置和依赖
├── uv.lock              # 锁定依赖版本
├── src/
│   └── frago/
│       ├── __init__.py
│       ├── cdp/
│       │   ├── __init__.py
│       │   ├── client.py      # CDP客户端核心
│       │   ├── session.py     # Session类实现
│       │   ├── commands/      # CDP命令封装
│       │   │   ├── __init__.py
│       │   │   ├── page.py    # Page域命令
│       │   │   ├── input.py   # Input域命令
│       │   │   ├── runtime.py # Runtime域命令
│       │   │   └── dom.py     # DOM域命令
│       │   ├── exceptions.py  # 自定义异常
│       │   ├── retry.py       # 重试机制
│       │   └── config.py      # 配置管理
│       └── cli/
│           ├── __init__.py
│           └── main.py        # CLI入口

scripts/                  # Shell包装器（向后兼容）
├── cdp_navigate.sh      → 调用 python -m frago.cli navigate
├── cdp_click.sh         → 调用 python -m frago.cli click
├── cdp_screenshot.sh    → 调用 python -m frago.cli screenshot
└── ...

tests/
├── unit/                # 单元测试
│   ├── test_session.py
│   ├── test_commands.py
│   └── test_retry.py
├── integration/         # 集成测试
│   └── test_cdp_flow.py
└── fixtures/           # 测试数据
```

**Structure Decision**: Python包结构，采用src布局，清晰的模块划分。Shell脚本作为薄包装器调用Python CLI。

## Complexity Tracking

> 无违规项。Python实现符合更新后的技术约束。

## 阶段2：实施任务

### 任务分组

#### 组1：Python CDP核心库（优先级：P1）
1. **创建项目骨架**
   - 初始化pyproject.toml
   - 配置uv环境
   - 设置项目结构

2. **实现CDP Session类**
   - WebSocket连接管理
   - 请求/响应关联
   - 连接池支持

3. **实现重试机制**
   - 可配置重试策略
   - 指数退避算法
   - 超时处理

4. **实现错误处理**
   - 自定义异常类
   - 结构化错误信息
   - 调试日志

#### 组2：CDP命令封装（优先级：P1）
5. **Page域命令**
   - navigate()
   - screenshot()
   - waitForSelector()

6. **Input域命令**
   - click()
   - type()
   - scroll()

7. **Runtime域命令**
   - evaluate()
   - getProperties()

8. **DOM域命令**
   - getDocument()
   - querySelector()

#### 组3：CLI接口（优先级：P2）
9. **创建CLI框架**
   - 使用click库
   - 参数解析
   - 输出格式化

10. **实现主要命令**
    - navigate
    - click
    - screenshot
    - exec-js
    - get-title

#### 组4：Shell包装器（优先级：P2）
11. **创建包装器脚本**
    - 保持原有接口
    - 调用Python CLI
    - 错误码映射

#### 组5：测试套件（优先级：P1）
12. **单元测试**
    - Session类测试
    - 命令测试
    - 重试机制测试

13. **集成测试**
    - 端到端流程
    - 错误场景
    - 性能基准

#### 组6：文档和迁移（优先级：P3）
14. **API文档**
    - 类和方法文档
    - 使用示例
    - 迁移指南

15. **迁移验证**
    - 功能对比测试
    - 性能对比
    - 兼容性检查

### 实施顺序（一次性重写）
1. 第1-2天：组1 - Python CDP核心库
2. 第3-4天：组2 - CDP命令封装
3. 第5天：组3 - CLI接口
4. 第6天：组4 - Shell包装器
5. 第7-8天：组5 - 测试套件
6. 第9天：组6 - 文档和迁移
7. 第10天：切换部署

### 成功标准验证
- [ ] Python CDP库完整实现
- [ ] 所有原Shell脚本功能覆盖
- [ ] 单元测试覆盖率>80%
- [ ] JSON处理代码减少90%
- [ ] WebSocket连接持久化
- [ ] CLI接口100%兼容
- [ ] 错误处理显著改善
- [ ] 重试机制正常工作