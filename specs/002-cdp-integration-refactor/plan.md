# Implementation Plan: 重构CDP集成

**Branch**: `002-cdp-integration-refactor` | **Date**: 2025-11-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-cdp-integration-refactor/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

重构CDP集成以统一Python实现和Shell脚本功能，确保功能一致性并检查代理参数使用。通过创建清晰的目录结构、功能映射验证和代理配置检查来提升开发体验和系统可靠性。

## Technical Context

**Language/Version**: Python 3.9+  
**Primary Dependencies**: websocket-client, click, pydantic, python-dotenv, websocat  
**Storage**: N/A (运行时状态管理)  
**Testing**: pytest, pytest-cov, pytest-asyncio  
**Target Platform**: macOS/Linux (Chrome DevTools Protocol)  
**Project Type**: 库项目 (Python包)  
**Performance Goals**: CDP连接延迟<500ms，操作成功率>95%  
**Constraints**: 必须兼容现有Shell脚本，保持向后兼容性  
**Scale/Scope**: 18个CDP功能，统一Python和Shell实现

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**状态**: 通过

**分析**:
- 项目遵循Python包开发最佳实践
- 提供CLI接口与Shell脚本对应
- 现有结构已模块化，符合库优先原则
- 测试框架配置完整，支持TDD
- 向后兼容性得到保证

## Project Structure

### Documentation (this feature)

```text
specs/002-cdp-integration-refactor/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/
└── frago/
    ├── __init__.py
    ├── cdp/
    │   ├── __init__.py
    │   ├── client.py              # CDP客户端基类
    │   ├── session.py             # WebSocket会话实现
    │   ├── config.py              # 配置管理
    │   ├── exceptions.py          # 异常定义
    │   ├── logger.py              # 日志配置
    │   ├── retry.py               # 重试机制
    │   ├── types.py               # 类型定义
    │   └── commands/
    │       ├── __init__.py
    │       ├── page.py            # 页面相关命令
    │       ├── input.py           # 输入相关命令
    │       ├── runtime.py         # JavaScript执行
    │       └── dom.py             # DOM操作
    └── cli/
        ├── __init__.py
        ├── main.py                # CLI入口点
        └── commands.py            # CLI命令实现

tests/
├── unit/
├── integration/
└── contract/

scripts/
├── share/
│   ├── cdp_navigate.sh           # 导航脚本
│   ├── cdp_screenshot.sh         # 截图脚本
│   ├── cdp_exec_js.sh            # JS执行脚本
│   ├── cdp_click.sh              # 点击脚本
│   ├── cdp_scroll.sh             # 滚动脚本
│   ├── cdp_wait.sh               # 等待脚本
│   ├── cdp_zoom.sh               # 缩放脚本
│   ├── cdp_get_title.sh          # 获取标题
│   ├── cdp_get_content.sh        # 获取内容
│   ├── cdp_status.sh             # 状态检查
│   ├── cdp_help.sh               # 帮助信息
│   ├── cdp_common.sh             # 通用函数
│   └── check_python_env.sh       # 环境检查
└── generate/
    ├── cdp_highlight.sh          # 高亮效果
    ├── cdp_pointer.sh            # 指针动画
    ├── cdp_spotlight.sh          # 聚光灯效果
    ├── cdp_annotate.sh           # 标注效果
    └── cdp_clear_effects.sh      # 清除效果
```

**Structure Decision**: 采用单项目结构，Python包作为核心实现，Shell脚本作为兼容层。现有结构已合理，重构主要关注功能统一和代理参数检查。

## Implementation Status

### Phase 0: Research - ✅ 完成
- [x] 分析现有Python CDP实现状态
- [x] 检查代理参数使用情况
- [x] 分析功能对应关系
- [x] 评估目录结构优化需求
- [x] 创建 [research.md](./research.md)

### Phase 1: Design - ✅ 完成
- [x] 定义核心数据模型
- [x] 创建API契约规范
- [x] 制定快速入门指南
- [x] 创建 [data-model.md](./data-model.md)
- [x] 创建 [quickstart.md](./quickstart.md)
- [x] 创建 [contracts/api-contract.md](./contracts/api-contract.md)

### Phase 2: Implementation - 🔄 待执行
- [ ] 实现代理参数支持
- [ ] 开发功能映射验证工具
- [ ] 优化目录结构组织
- [ ] 确保功能一致性
- [ ] 创建测试套件

### Phase 3: Testing - 🔄 待执行
- [ ] 运行功能映射验证
- [ ] 测试代理配置
- [ ] 验证向后兼容性
- [ ] 性能测试

## Complexity Tracking

**状态**: 无复杂性违规

**分析**: 重构保持现有架构，主要关注功能统一和配置改进，不引入不必要的复杂性。
