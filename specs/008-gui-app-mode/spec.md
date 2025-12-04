# Feature Specification: Frago GUI应用模式

**Feature Branch**: `008-gui-app-mode`
**Created**: 2025-12-03
**Status**: Draft
**Input**: User description: "我们要做一个新的迭代，使frago支持以GUI方式运行，期望的方式是 `frago --gui`，期望使用一个轻量级的桌面应用框架来运行一个实质上是html的无边框浏览器窗口，窗口尺寸限定宽度和高度，通过一个html页面来展示frago的一些功能和按钮。整个页面模拟一个app方式。"

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

### User Story 1 - 启动GUI应用模式 (Priority: P1)

作为frago用户，我希望能够通过`frago --gui`命令启动GUI界面，这样我就可以在图形界面中使用frago的功能，而不必依赖命令行。

**Why this priority**: 这是整个GUI功能的基础，没有这个功能，其他所有GUI功能都无法使用。它提供了从命令行到图形界面的入口点。

**Independent Test**: 可以通过执行`frago --gui`命令并验证GUI窗口是否正确启动来独立测试。这个功能本身就能提供价值——让用户看到frago的GUI界面。

**Acceptance Scenarios**:

1. **Given** 用户已安装frago并打开终端
   **When** 用户执行`frago --gui`命令
   **Then** 系统启动一个无边框GUI窗口，显示frago的欢迎界面

2. **Given** GUI窗口已启动
   **When** 用户查看窗口
   **Then** 窗口尺寸符合预设的宽度和高度，且窗口无边框

---

### User Story 2 - 使用App式界面访问frago功能 (Priority: P2)

作为frago用户，我希望在GUI界面中通过App式UI页切换来访问frago的核心功能，包括设置、配方列表、skills列表等，这样我可以通过直观的界面组织和使用frago的各种功能。

**Why this priority**: 在GUI窗口启动后，用户需要能够通过现代化的App式界面来访问和组织frago功能，提供更好的用户体验。

**Independent Test**: 可以通过在GUI界面中切换不同的页面（如设置页、配方列表页、skills列表页）并验证页面内容是否正确显示来独立测试。

**Acceptance Scenarios**:

1. **Given** GUI窗口已启动
   **When** 用户查看主界面
   **Then** 界面显示App式的页面切换导航，包括设置按钮、配方列表、skills列表等入口

2. **Given** 用户在GUI主界面
   **When** 用户点击"配方列表"页面
   **Then** 系统显示可用的frago配方列表，并支持通过点击运行配方

---

### User Story 3 - 通过输入区域调用frago agent (Priority: P2)

作为frago用户，我希望在GUI界面中通过输入区域输入命令或问题，然后点击发送按钮来调用`frago agent`，这样我可以通过自然语言或命令与frago交互，而不必记忆具体的命令行语法。

**Why this priority**: 这是GUI界面的核心交互方式——提供类似聊天界面的输入方式，降低使用门槛。

**Independent Test**: 可以通过在输入区域输入一个frago相关的问题或命令，点击发送按钮，并验证是否成功调用了`frago agent`来独立测试。

**Acceptance Scenarios**:

1. **Given** 用户在GUI界面的输入区域
   **When** 用户输入"如何打开浏览器"并点击发送按钮
   **Then** 系统调用`frago agent`处理输入，并在结果区域显示响应

2. **Given** 用户正在执行一个frago任务
   **When** `frago agent`返回stream-json格式的进度消息
   **Then** GUI界面实时解析并显示进度信息在特定区域中

---

### User Story 4 - 查看执行结果和日志 (Priority: P3)

作为frago用户，我希望在GUI界面中能够查看命令执行的结果和日志，这样我可以方便地了解操作的状态和输出。

**Why this priority**: 完整的用户体验需要包括结果反馈。用户需要知道他们的操作是否成功以及执行的结果。

**Independent Test**: 可以通过执行一个命令并验证执行结果是否在GUI界面中正确显示来独立测试。

**Acceptance Scenarios**:

1. **Given** 用户执行了一个frago命令
   **When** 命令执行完成
   **Then** GUI界面显示执行结果，包括成功/失败状态和输出信息

2. **Given** 用户执行了多个命令
   **When** 用户查看历史记录
   **Then** GUI界面显示命令执行的历史记录和状态

### Edge Cases

- 当用户在没有图形界面的服务器环境（headless模式）中运行`frago --gui`时，系统应该如何处理？
- 当GUI框架未安装或版本不兼容时，系统应该提供清晰的错误信息
- 当用户在输入区域输入大量文本时，界面应该如何适应？
- 当`frago agent`返回的stream-json消息格式不正确时，GUI界面应该如何优雅地处理？
- 当用户在页面切换过程中快速点击时，界面应该如何防止重复加载？
- 当配方列表或skills列表为空时，界面应该如何显示？
- 当用户尝试启动新任务而已有任务正在运行时，GUI界面应该提示用户等待当前任务完成或取消当前任务
- 当网络连接不稳定导致与`frago agent`通信中断时，界面应该允许用户查看历史记录和配置，但明确提示需要连接才能执行新任务
- 当用户调整窗口大小时，界面布局应该如何适应？（特别是600×1434的特定比例）
- 当frago命令执行失败时，GUI界面应该使用非阻塞式Toast通知（显示3秒后自动消失）并在结果区域显示详细的错误信息，包括错误类型、原因和建议的解决方案

## Requirements *(mandatory)*

<!--
  ACTION REQUIRED: The content in this section represents placeholders.
  Fill them out with the right functional requirements.
-->

### Functional Requirements

- **FR-001**: 系统必须支持通过`frago --gui`命令启动GUI界面
- **FR-002**: GUI窗口必须是无边框的，尺寸限定在预设的宽度和高度范围内
- **FR-003**: GUI界面必须通过HTML页面实现，使用轻量级的桌面应用框架渲染
- **FR-004**: 用户必须能够在GUI界面中通过App式UI页切换访问不同功能模块
- **FR-005**: 系统必须提供输入区域和发送按钮，支持用户输入文本并调用`frago agent`
- **FR-006**: 系统必须实时解析并显示`frago agent`返回的stream-json格式消息
- **FR-007**: GUI界面必须提供类似原生应用的交互体验，包括流畅的页面切换
- **FR-008**: 系统必须使用非阻塞式Toast通知（显示3秒后自动消失）并在结果区域显示详细的错误信息来处理GUI相关的错误情况
- **FR-009**: GUI界面必须保持响应，即使在执行长时间运行的任务时
- **FR-010**: 系统必须支持从GUI界面查看命令执行的历史记录
- **FR-014**: 系统必须提供设置按钮，允许用户配置GUI相关选项
- **FR-015**: 系统必须显示配方列表，支持用户查看和运行可用配方
- **FR-016**: 系统必须显示skills列表，展示可用的frago技能
- **FR-017**: 当GUI窗口关闭时，系统必须根据是否有`frago agent`运行来智能提示退出确认
- **FR-018**: 系统必须在`~/.frago/`目录下持久化存储用户配置、偏好设置和历史记录
- **FR-019**: 系统必须能够从`~/.claude`目录提取会话上下文数据，以保持多轮prompt的连续性
- **FR-020**: 系统必须在GUI重启时恢复之前的窗口状态、配置和会话上下文
- **FR-021**: 系统必须限制同时只能运行一个frago任务，当有任务正在运行时阻止新任务启动
- **FR-022**: 系统必须在无网络连接时提供有限的离线功能（查看历史记录、配置设置），并明确提示需要连接才能执行新任务

*需要明确的事项（已解决）:*

- **FR-011**: GUI窗口的默认尺寸应该是 **600×1434像素**（宽度600px，宽高比1:2.39）
- **FR-012**: GUI界面应该支持 **设置按钮、输入区域、发送按钮、配方列表、skills列表、App式UI页切换**。输入后发送实际上调用`frago agent`，运行时的stream-json消息返回的解析结果呈现在窗口的特定区域中
- **FR-013**: 当GUI窗口关闭时，系统应该检查是否有`frago agent`正在运行。如果有，警告用户是否要退出（默认否，`否`选项自动倒计时，倒计时结束取消退出）。如果无运行，则仍提示是否要退出（默认是，`是`自动倒计时）

### Key Entities

- **GUI窗口配置**: 定义GUI窗口的显示属性，包括宽度、高度、是否无边框、标题等
- **功能模块**: 表示frago在GUI界面中展示的功能类别，如浏览器自动化、配方管理、项目运行等
- **命令执行记录**: 记录用户在GUI界面中执行的frago命令及其结果，包括命令、参数、执行时间、状态和输出
- **界面状态**: 跟踪GUI界面的当前状态，包括当前显示的功能模块、用户输入的数据、执行进度等
- **用户配置数据**: 存储在`~/.frago/`目录下的用户偏好设置，包括主题、布局、快捷键等
- **会话上下文数据**: 从`~/.claude`目录提取的对话历史，用于保持多轮prompt的上下文连续性

## Success Criteria *(mandatory)*

<!--
  ACTION REQUIRED: Define measurable success criteria.
  These must be technology-agnostic and measurable.
-->

### Measurable Outcomes

- **SC-001**: 用户可以在5秒内通过`frago --gui`命令成功启动GUI界面
- **SC-002**: 90%的用户能够在首次使用GUI界面时，在3分钟内完成一个frago命令的执行
- **SC-003**: GUI界面在执行命令时保持响应，用户操作延迟不超过500毫秒
- **SC-004**: 95%的命令执行结果能够在GUI界面中正确显示
- **SC-005**: 用户通过GUI界面执行命令的成功率不低于通过命令行执行的成功率
- **SC-006**: 80%的现有frago用户表示愿意在适合的场景中使用GUI界面替代命令行

## Assumptions

- 用户的操作系统支持图形界面（非headless环境）
- GUI框架与用户的Python环境兼容
- 用户已经安装了frago并配置了基本环境
- GUI界面主要面向不熟悉命令行或偏好图形界面的用户
- 首版GUI界面不需要支持所有frago功能，可以逐步完善
- GUI界面的响应性要求适用于现代桌面计算机配置

## 澄清

### 会话 2025-12-03

- Q: 设计草图应该包含什么内容？ → A: 提供详细的UI布局描述，包括组件位置、尺寸和交互区域
- Q: GUI数据持久化范围？ → A: 持久化所有数据（配置+会话+历史），使用`~/.frago/`目录，会话数据从`~/.claude`提取以保持上下文
- Q: 错误处理的具体用户界面？ → A: 使用非阻塞式Toast通知 + 结果区域详细错误信息
- Q: 多任务并发处理策略？ → A: 暂时不支持并发任务
- Q: 离线工作能力？ → A: 提供有限的离线功能（查看历史、配置），需要连接时明确提示

## 设计草图描述

以下是为nano banana pro生成草图提供的详细UI布局描述：

### 窗口总体布局
- **窗口尺寸**: 600px宽 × 1434px高（宽高比1:2.39）
- **窗口样式**: 无边框，类似原生应用
- **整体分区**: 垂直分为三个主要区域

### 顶部导航栏（高度: 60px）
- **位置**: 窗口顶部，固定高度
- **组件**:
  1. **应用标题**: 左侧显示"Frago GUI"（字体大小: 18px）
  2. **设置按钮**: 右侧齿轮图标，点击打开设置面板
  3. **页面切换标签**: 中部水平排列的标签式导航
     - 主页 (默认选中)
     - 配方列表
     - Skills列表
     - 历史记录

### 中部内容区域（高度: 1100px）
- **位置**: 导航栏下方，占据主要空间
- **分区**: 左右两栏布局

#### 左栏（宽度: 400px）
- **功能面板区域**:
  1. **输入区域**（高度: 200px）:
     - 多行文本输入框，带占位符"输入命令或问题..."
     - 右下角: 发送按钮（绿色，带箭头图标）
  2. **结果展示区域**（高度: 700px）:
     - 实时显示`frago agent`返回的stream-json解析结果
     - 支持滚动查看历史消息
     - 消息样式: 用户输入（右对齐，浅蓝色背景），系统响应（左对齐，浅灰色背景）
  3. **状态指示器**（高度: 200px）:
     - 当前任务执行状态
     - 进度条（长时间任务时显示）
     - 连接状态指示（绿色=已连接，红色=断开）

#### 右栏（宽度: 200px）
- **快捷功能面板**:
  1. **常用配方列表**（高度: 500px）:
     - 垂直滚动列表
     - 每个配方显示: 图标 + 名称 + 简短描述
     - 点击直接运行
  2. **Skills快捷入口**（高度: 300px）:
     - 图标网格布局（2列×3行）
     - 每个skill显示图标和名称
  3. **快速操作按钮**（高度: 300px）:
     - "新建项目"按钮
     - "打开浏览器"按钮
     - "查看日志"按钮

### 底部状态栏（高度: 174px）
- **位置**: 窗口底部
- **组件**:
  1. **系统状态**: 左侧显示CPU/内存使用情况
  2. **连接状态**: 中部显示`frago agent`连接状态
  3. **操作按钮**: 右侧小型按钮
     - 最小化
     - 最大化/还原
     - 关闭（触发智能退出确认）

### 交互细节
- **页面切换**: 点击导航标签时，内容区域平滑过渡到对应页面
- **输入发送**: 点击发送按钮或按Ctrl+Enter发送输入
- **实时更新**: 结果区域自动滚动到最新消息
- **响应式设计**: 组件尺寸随窗口微调保持比例

### 视觉风格
- **颜色主题**: 深色模式为主（背景: #1e1e1e，文字: #ffffff）
- **字体**: 系统默认等宽字体（Consolas, Monaco等）
- **间距**: 组件间使用一致的8px网格间距
- **圆角**: 所有按钮和面板使用4px圆角
- **阴影**: 轻微阴影提升层次感
