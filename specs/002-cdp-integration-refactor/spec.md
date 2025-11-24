# Feature Specification: 重构CDP集成

**Feature Branch**: `002-cdp-integration-refactor`  
**Created**: 2025-11-16  
**Status**: Draft  
**Input**: User description: "重构CDP集成：统一Python实现和Shell脚本，检查代理参数"

## 现有脚本功能清单

### 基础操作脚本 (scripts/share/)

- **cdp_navigate.sh** - 导航到指定URL，支持等待元素、调试模式、超时设置
- **cdp_screenshot.sh** - 页面截图功能，保存为PNG格式到指定目录
- **cdp_exec_js.sh** - 在页面上下文中执行JavaScript代码
- **cdp_click.sh** - 通过CSS选择器点击页面元素，支持等待超时
- **cdp_scroll.sh** - 控制页面滚动，支持上下滚动、滚动到顶部/底部、指定像素滚动
- **cdp_wait.sh** - 等待指定CSS选择器的元素出现，支持超时设置
- **cdp_zoom.sh** - 调整页面缩放级别，支持0.5-3.0倍缩放
- **cdp_get_title.sh** - 获取当前页面标题
- **cdp_get_content.sh** - 获取页面或指定元素的文本内容
- **cdp_status.sh** - 检查Chrome和页面状态，获取页面列表并截图
- **cdp_help.sh** - 显示所有CDP脚本的使用说明和示例
- **cdp_common.sh** - 通用函数库，提供CDP环境检查、WebSocket连接、错误处理等基础功能

### 视觉效果脚本 (scripts/generate/)

- **cdp_highlight.sh** - 为元素添加彩色边框高亮效果，支持自定义颜色和边框宽度
- **cdp_pointer.sh** - 创建动态鼠标指针动画，模拟从屏幕角落移动到目标元素
- **cdp_spotlight.sh** - 聚光灯效果，突出显示元素并将周围区域变暗
- **cdp_annotate.sh** - 给元素添加边框标注，用于界面说明和用户指导
- **cdp_clear_effects.sh** - 清除所有由Frago脚本添加的视觉效果元素

### 环境检查脚本

- **check_python_env.sh** - 检查Python环境配置

## User Scenarios & Testing *(mandatory)*

<!--
  IMPORTANT: User stories should be PRIORITIZED as user journeys ordered by importance.
  Each user story/journey must be INDEPENDENTLY TESTABLE - meaning if you implement just ONE of them,
  you should still have a viable MVP (Minimum Viable Product) that delivers value.
  
  Assign priorities (P1, P2, P3, etc.) to each story, where P1 is the most critical.
  Think of each story as a standalone slice of functionality that can be:
  - Developed independently
  - Tested independently
  - Deployed independently
  - Demonstrated to users independently
-->

### User Story 1 - 统一的CDP方法目录结构 (Priority: P1)

作为开发者，我希望在src/frago/cdp目录下有清晰的方法目录结构，这样我就能轻松找到和使用所有CDP相关功能，而不需要在Python代码和Shell脚本之间来回切换。

**Why this priority**: 这是重构的核心目标，直接影响开发效率和代码维护性。统一的目录结构是其他改进的基础。

**Independent Test**: 可以独立验证新的目录结构是否完整覆盖所有现有CDP功能，并且每个方法都有对应的Python实现。

**Acceptance Scenarios**:

1. **Given** 开发者需要导航到网页，**When** 他们查看src/frago/cdp目录，**Then** 应该找到清晰的导航方法实现
2. **Given** 开发者需要截图功能，**When** 他们查看src/frago/cdp目录，**Then** 应该找到截图方法实现
3. **Given** 开发者需要执行JavaScript，**When** 他们查看src/frago/cdp目录，**Then** 应该找到JS执行方法实现

---

### User Story 2 - Python和Shell脚本功能对应 (Priority: P2)

作为开发者，我希望Python代码中的CDP功能与scripts目录下的Shell脚本一一对应，这样我就能确保两种实现方式的功能一致性。

**Why this priority**: 确保功能一致性对于系统可靠性至关重要，避免Python和Shell脚本之间的功能差异。

**Independent Test**: 可以独立验证每个Shell脚本功能在Python代码中都有对应的实现，并且行为一致。

**Acceptance Scenarios**:

1. **Given** scripts/share目录下的cdp_navigate.sh脚本，**When** 检查Python实现，**Then** 应该有对应的导航方法
2. **Given** scripts/share目录下的cdp_screenshot.sh脚本，**When** 检查Python实现，**Then** 应该有对应的截图方法
3. **Given** scripts/share目录下的cdp_exec_js.sh脚本，**When** 检查Python实现，**Then** 应该有对应的JS执行方法

---

### User Story 3 - 代理参数检查 (Priority: P3)

作为开发者，我希望Python代码通过websocket访问CDP时正确使用--no-proxy参数，这样就能避免在代理环境中出现连接问题。

**Why this priority**: 确保在各种网络环境下都能可靠连接，特别是企业代理环境。

**Independent Test**: 可以独立验证所有websocket连接代码都正确使用了代理配置参数。

**Acceptance Scenarios**:

1. **Given** 系统运行在代理环境中，**When** Python代码连接CDP，**Then** 应该正确使用--no-proxy参数
2. **Given** 系统运行在无代理环境中，**When** Python代码连接CDP，**Then** 连接应该正常工作

### Edge Cases

- 当CDP连接失败时，系统如何处理重连？
- 当Python方法和Shell脚本行为不一致时，如何检测和报告？
- 当代理配置复杂时，如何确保--no-proxy参数正确工作？
- 当网络环境变化时，CDP连接如何适应？

## Requirements *(mandatory)*

<!--
  ACTION REQUIRED: The content in this section represents placeholders.
  Fill them out with the right functional requirements.
-->

### Functional Requirements

- **FR-001**: 系统必须在src/frago/cdp目录下创建清晰的方法目录结构
- **FR-002**: 系统必须确保每个Shell脚本功能在Python代码中都有对应实现  
- **FR-003**: 系统必须检查并确保所有websocket连接正确使用代理参数
- **FR-004**: 系统必须提供功能一致性验证机制
- **FR-005**: 系统必须记录所有CDP操作和连接状态
- **FR-006**: 系统必须处理CDP连接失败和重连场景

### Key Entities

- **CDP方法**: 代表单个Chrome DevTools Protocol操作，包含Python实现和可能的Shell脚本对应
- **代理配置**: 代表网络代理设置，影响websocket连接行为
- **功能映射**: 代表Python实现和Shell脚本之间的对应关系

## Success Criteria *(mandatory)*

<!--
  ACTION REQUIRED: Define measurable success criteria.
  These must be technology-agnostic and measurable.
-->

### Measurable Outcomes

- **SC-001**: 开发者可以在3分钟内找到任何CDP功能的Python实现
- **SC-002**: 所有现有Shell脚本功能在Python代码中都有100%对应实现
- **SC-003**: 在代理环境中CDP连接成功率从70%提高到95%以上
- **SC-004**: 功能一致性验证机制可以检测到所有Python-Shell实现差异
- **SC-005**: 开发者对CDP功能查找的满意度提高40%
