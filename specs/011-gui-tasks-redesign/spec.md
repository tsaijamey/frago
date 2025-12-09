# Feature Specification: Frago GUI Tasks Redesign

**Feature Branch**: `011-gui-tasks-redesign`
**Created**: 2025-12-05
**Status**: Draft
**Input**: User description: "经过目前的迭代,我们已经能够确保 `frago agent {...}` 运行时能够实时获得claude原生会话内容了. 现在我们需要来迭代 GUI. 1. 打开默认应该是tips, 一个新页面; 2. "主页"改名叫"Tasks", 主页下是所有已运行的tasks的列表, 红黄绿三种状态,红=error退出/停止,绿=完成,黄=进行中, 点tasks列表项进入任务详情,任务详情即加载对应任务的 session 内容;"

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

### User Story 1 - 启动GUI并查看Tips页面 (Priority: P1)

作为Frago用户，当我启动GUI应用程序时，我希望默认看到Tips页面，这样我可以在开始工作前获得有用的提示和指导。

**Why this priority**: 这是用户首次接触GUI的核心体验，直接影响用户对产品的第一印象和使用体验。Tips页面可以帮助用户快速了解新功能和使用技巧。

**Independent Test**: 可以通过启动GUI应用程序并验证默认显示的页面是否为Tips页面来独立测试。这提供了立即的用户价值——用户无需任何配置即可获得有用的指导信息。

**Acceptance Scenarios**:

1. **Given** Frago GUI应用程序已安装
   **When** 用户启动应用程序
   **Then** 默认显示Tips页面，包含有用的提示信息

2. **Given** 用户正在查看其他页面（如Tasks页面）
   **When** 用户点击导航菜单中的"Tips"选项
   **Then** 切换到Tips页面，显示最新的提示内容

---

### User Story 2 - 查看Tasks列表和状态 (Priority: P1)

作为Frago用户，我希望在Tasks页面看到所有已运行tasks的列表，并能通过红黄绿三种颜色快速识别任务状态，这样我可以一目了然地了解任务执行情况。

**Why this priority**: 这是GUI的核心功能，为用户提供任务管理的可视化界面。状态颜色编码是快速理解任务状态的关键机制。

**Independent Test**: 可以通过运行一个frago任务，然后在GUI中查看Tasks页面是否显示该任务及其正确状态来独立测试。这提供了核心的用户价值——任务状态监控。

**Acceptance Scenarios**:

1. **Given** 用户有正在运行的frago任务
   **When** 用户打开GUI并导航到Tasks页面
   **Then** 看到任务列表，每个任务显示名称、开始时间和状态指示器

2. **Given** 任务列表中有多个任务
   **When** 用户查看Tasks页面
   **Then** 任务按状态颜色分组或标记：
   - 红色：任务出错或已停止
   - 黄色：任务正在进行中
   - 绿色：任务已完成

3. **Given** 任务状态发生变化（如从进行中变为完成）
   **When** 用户刷新Tasks页面或状态自动更新
   **Then** 任务状态颜色相应更新

---

### User Story 3 - 查看任务详情和Session内容 (Priority: P1)

作为Frago用户，当我点击Tasks列表中的任务项时，我希望看到该任务的详细信息和对应的session内容，这样我可以深入了解任务执行过程和结果。

**Why this priority**: 这是从概览到详细信息的自然工作流，为用户提供完整的任务上下文。基于已有的`frago agent {...}`实时获取claude原生会话内容功能，这是GUI的核心价值体现。

**Independent Test**: 可以通过点击Tasks列表中的任务项，验证是否显示任务详情页面并加载对应的session内容来独立测试。这提供了深入分析任务的能力。

**Acceptance Scenarios**:

1. **Given** Tasks页面显示任务列表
   **When** 用户点击列表中的某个任务项
   **Then** 进入任务详情页面，显示：
   - 任务基本信息（名称、状态、开始/结束时间）
   - 任务执行日志或摘要
   - 对应的claude原生会话内容

2. **Given** 用户正在查看任务详情页面
   **When** session内容有更新（如frago agent正在运行）
   **Then** 页面自动或手动刷新显示最新的session内容

3. **Given** 用户正在查看任务详情
   **When** 用户点击返回按钮或导航到其他页面
   **Then** 返回到Tasks列表页面，保持之前的滚动位置和筛选状态

---

### User Story 4 - 页面导航和布局 (Priority: P2)

作为Frago用户，我希望GUI有清晰的导航结构，包括Tips页面和Tasks页面的切换，以及直观的页面布局，这样我可以轻松在不同功能间切换。

**Why this priority**: 良好的导航体验是GUI可用性的基础，虽然不是核心功能，但对用户体验有重要影响。

**Independent Test**: 可以通过测试页面间的导航是否流畅、布局是否合理来独立测试。这提供了基本的用户界面交互能力。

**Acceptance Scenarios**:

1. **Given** 用户正在查看Tips页面
   **When** 用户点击导航菜单中的"Tasks"
   **Then** 切换到Tasks页面，显示任务列表

2. **Given** GUI应用程序有多个页面
   **When** 用户使用应用程序
   **Then** 导航菜单清晰显示当前所在页面，并提供快速切换选项

### Edge Cases

- 当没有正在运行或已完成的任务时，Tasks页面显示什么内容？
- 当任务数量非常多（如超过100个）时，Tasks列表如何显示和滚动？
- 当session内容非常大（如超过10MB）时，任务详情页面如何加载和显示？
- 当网络连接不稳定时，GUI如何保持可用性和数据同步？
- 当frago agent进程意外终止时，GUI如何更新任务状态？
- 当用户同时打开多个GUI实例时，数据如何保持一致？
- 当Tips页面内容需要更新时，如何获取最新内容？
- 当任务状态颜色对色盲用户不友好时，是否有替代的标识方式？

## Requirements *(mandatory)*

<!--
  ACTION REQUIRED: The content in this section represents placeholders.
  Fill them out with the right functional requirements.
-->

### Functional Requirements

- **FR-001**: GUI MUST 默认显示Tips页面作为启动时的初始页面
- **FR-002**: GUI MUST 提供导航菜单，包含"Tips"和"Tasks"页面选项
- **FR-003**: Tasks页面 MUST 显示所有已运行frago任务的列表
- **FR-004**: Tasks列表中的每个任务项 MUST 使用颜色编码显示状态：
  - 红色：任务出错或已停止
  - 黄色：任务正在进行中
  - 绿色：任务已完成
- **FR-005**: 用户 MUST 能够点击Tasks列表中的任务项进入任务详情页面
- **FR-006**: 任务详情页面 MUST 显示任务的基本信息（名称、状态、时间等）
- **FR-007**: 任务详情页面 MUST 加载并显示对应任务的claude原生会话内容
- **FR-008**: GUI MUST 支持页面间的流畅导航（Tips ↔ Tasks ↔ 任务详情）
- **FR-009**: Tasks页面 MUST 在任务状态变化时更新显示（自动或手动刷新）
- **FR-010**: 当没有任务时，Tasks页面 MUST 显示友好的空状态提示

*已明确的事项：*

- **FR-011**: Tasks列表的排序方式应为按开始时间倒序（最新的任务显示在最前面）
- **FR-012**: 任务详情页面中session内容的更新频率应采用智能检测策略：根据任务状态自动切换更新方式（进行中时实时更新，完成后停止自动更新）
- **FR-013**: Tips页面的内容暂时留空，GUI显示空状态或占位内容，未来可通过其他机制添加内容

### Key Entities

- **Task**: 表示一个frago任务的执行实例
  - 属性：任务ID、名称、状态（错误/停止、进行中、完成）、开始时间、结束时间、执行命令
  - 关系：关联到一个或多个Session内容

- **Session Content**: 表示claude原生会话内容
  - 属性：会话ID、内容文本、时间戳、关联的任务ID
  - 关系：属于一个特定的Task

- **Tips Content**: 表示Tips页面显示的内容
  - 属性：标题、内容、类别、发布时间、优先级
  - 关系：独立于任务，为全局指导信息

## Success Criteria *(mandatory)*

<!--
  ACTION REQUIRED: Define measurable success criteria.
  These must be technology-agnostic and measurable.
-->

### Measurable Outcomes

- **SC-001**: 用户启动GUI后能在3秒内看到Tips页面内容
- **SC-002**: Tasks页面加载并显示任务列表的时间不超过2秒（即使有50个任务）
- **SC-003**: 用户从Tasks列表点击到查看完整任务详情的操作流程能在5秒内完成
- **SC-004**: 90%的用户能够正确理解红黄绿三种状态颜色的含义（通过可用性测试）
- **SC-005**: 任务状态变化时，Tasks页面在10秒内自动更新显示（或提供明显的手动刷新提示）
- **SC-006**: 当session内容较大时（超过1MB），任务详情页面仍能在5秒内加载并显示可浏览的内容
- **SC-007**: 页面间导航（Tips ↔ Tasks ↔ 任务详情）的切换时间不超过1秒
- **SC-008**: 在同时运行10个frago任务的情况下，GUI保持流畅响应，无卡顿或崩溃

## Assumptions

1. **已有基础架构**：假设`frago agent {...}`已经能够实时获取claude原生会话内容，GUI只需消费这些数据
2. **任务数据源**：假设frago任务的元数据（ID、名称、状态、时间等）已经存在并可被GUI访问
3. **用户熟悉度**：假设用户基本了解frago CLI工具的使用，GUI提供更友好的可视化界面
4. **性能环境**：假设在标准开发机器上运行（8GB RAM，4核CPU，SSD存储）
5. **颜色可访问性**：假设红黄绿颜色编码是行业标准，但会考虑色盲用户的替代方案
6. **数据持久化**：假设任务和session数据有适当的存储机制，GUI负责展示而非存储
7. **并发处理**：假设GUI能处理多个同时运行的frago任务的状态监控
8. **Tips内容**：假设Tips页面初始内容为空，未来可通过其他机制添加内容，GUI需要优雅处理空状态
