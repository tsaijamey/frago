# Feature Specification: Vite React 前端重构与 Linux 依赖自动安装

**Feature Branch**: `012-vite-react-frontend`
**Created**: 2025-12-09
**Status**: Draft
**Input**: 将 Frago GUI 前端从原生 JS 迁移到 Vite + React + TypeScript + TailwindCSS，并实现 Linux 系统依赖自动安装

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 开发者体验改进 (Priority: P1)

作为 Frago 开发者，希望前端代码采用现代化技术栈，以便获得更好的开发体验和代码可维护性。

开发者在进行前端修改时，代码保存后界面能快速刷新反映变化，无需手动刷新或重启应用。代码具备类型检查，能在编写阶段发现潜在错误。组件结构清晰，便于定位和修改特定功能。

**Why this priority**: 开发体验直接影响迭代效率，是整个重构的核心价值所在

**Independent Test**: 可通过启动开发服务器、修改组件代码、观察界面更新速度来验证

**Acceptance Scenarios**:

1. **Given** 开发服务器正在运行, **When** 开发者修改某个组件的样式代码, **Then** 界面在数秒内自动更新显示变化
2. **Given** 开发者编写组件代码, **When** 调用 API 时参数类型错误, **Then** 编辑器显示类型错误提示
3. **Given** 开发者需要修改任务列表功能, **When** 查找相关代码, **Then** 能通过清晰的目录结构快速定位到 TaskList 组件

---

### User Story 2 - 功能完整性保持 (Priority: P1)

作为 Frago 用户，希望迁移后的 GUI 保持所有现有功能正常工作，不因技术栈变更而丧失任何能力。

用户打开 GUI 后，所有页面（Tips、Tasks、Recipes、Skills、Settings）都能正常访问和交互。任务列表实时更新，任务详情正确显示，配方运行功能完好。

**Why this priority**: 功能完整性是迁移的基本要求，不能因为"升级"而退步

**Independent Test**: 可通过启动生产版本 GUI，逐一测试各页面功能来验证

**Acceptance Scenarios**:

1. **Given** 用户启动 Frago GUI, **When** 点击 Tasks 标签, **Then** 显示任务列表，包含任务状态颜色指示
2. **Given** 用户在任务列表页面, **When** 后台有新任务产生, **Then** 列表自动更新显示新任务
3. **Given** 用户在 Settings 页面, **When** 切换主题选项, **Then** 整个界面颜色方案立即切换
4. **Given** 用户在 Recipes 页面, **When** 点击某个配方, **Then** 显示配方详情信息

---

### User Story 3 - Linux 首次运行自动安装 (Priority: P2)

作为 Linux 用户，希望首次运行 `frago gui` 时系统能自动检测并安装缺失的 GUI 依赖，无需手动查找和安装包。

用户在新安装的 Linux 系统上运行 `frago gui` 命令，系统检测到缺少 WebKit/GTK 依赖后，询问是否自动安装。用户确认后，系统通过图形化密码对话框获取权限并完成安装，随后 GUI 自动启动。

**Why this priority**: 降低 Linux 用户的安装门槛，但需要前端迁移完成后才有意义

**Independent Test**: 可在缺少 GUI 依赖的 Linux 环境中运行 `frago gui` 命令，观察自动安装流程

**Acceptance Scenarios**:

1. **Given** Linux 系统缺少 WebKit 依赖, **When** 用户运行 `frago gui`, **Then** 系统提示"检测到缺少 GUI 系统依赖，是否自动安装？"
2. **Given** 用户确认自动安装, **When** 系统执行安装, **Then** 弹出图形化密码对话框（pkexec）而非命令行密码输入
3. **Given** 依赖安装成功, **When** 安装完成, **Then** GUI 自动启动无需用户再次输入命令
4. **Given** 用户拒绝自动安装, **When** 选择"否", **Then** 系统打印针对当前发行版的手动安装命令

---

### User Story 4 - 多发行版兼容 (Priority: P3)

作为使用非主流 Linux 发行版的用户，希望即使自动安装不支持我的发行版，也能获得明确的手动安装指导。

不同发行版的用户（Ubuntu、Fedora、Arch、openSUSE 等）运行 `frago gui` 时，系统能识别发行版并使用正确的包管理器和包名。对于不支持的发行版，提供通用的依赖说明。

**Why this priority**: 扩大用户覆盖范围，但核心功能不依赖此特性

**Independent Test**: 可在不同发行版的虚拟机或容器中测试自动安装流程

**Acceptance Scenarios**:

1. **Given** 用户使用 Ubuntu 系统, **When** 执行自动安装, **Then** 系统使用 apt 安装 python3-gi 等包
2. **Given** 用户使用 Fedora 系统, **When** 执行自动安装, **Then** 系统使用 dnf 安装 python3-gobject 等包
3. **Given** 用户使用不支持的发行版, **When** 运行 `frago gui`, **Then** 系统显示"无法识别您的发行版，请手动安装以下依赖：..."

---

### Edge Cases

- 用户在开发模式下关闭 Vite 开发服务器后尝试启动 GUI 会发生什么？系统应检测到连接失败并提示启动开发服务器
- 用户在没有图形界面的纯终端环境运行 `frago gui` 会发生什么？pkexec 无法工作时应回退到命令行提示
- 构建产物损坏或缺失时启动 GUI 会发生什么？系统应显示友好的错误提示而非崩溃
- Linux 用户网络离线时尝试自动安装会发生什么？系统应检测到包管理器失败并提示检查网络

## Requirements *(mandatory)*

### Functional Requirements

**前端重构**

- **FR-001**: 系统必须支持开发模式，从本地开发服务器加载前端界面
- **FR-002**: 系统必须支持生产模式，从打包后的静态文件加载前端界面
- **FR-003**: 前端必须实现所有现有页面功能：Tips、Tasks、Recipes、Skills、Settings
- **FR-004**: 前端必须保持与现有 pywebview API 的完整兼容
- **FR-005**: 前端必须支持深色和浅色主题切换
- **FR-006**: 任务列表必须支持实时更新，反映后台任务状态变化
- **FR-007**: 任务详情必须支持步骤分页加载
- **FR-008**: 构建产物必须输出到指定目录以便 Python 包打包分发
- **FR-015**: 旧版前端文件（`app.js`、`main.css`）必须保留在仓库中并标记为 deprecated，作为实现参考

**Linux 依赖自动安装**

- **FR-009**: 系统必须能检测当前 Linux 发行版类型
- **FR-010**: 系统必须能检测 WebKit/GTK 依赖是否已安装
- **FR-011**: 系统必须支持通过 pkexec 获取管理员权限执行安装
- **FR-012**: 系统必须支持至少以下发行版：Ubuntu、Debian、Fedora、RHEL/CentOS、Arch、Manjaro、openSUSE
- **FR-013**: 系统必须在不支持自动安装时提供手动安装指南
- **FR-014**: 系统必须在安装成功后自动重启 GUI

### Key Entities

- **页面 (Page)**: GUI 中的独立功能区域，包含 Tips、Tasks、Recipes、Skills、Settings 五种类型
- **任务 (Task)**: Agent 会话实例，具有唯一标识、状态（运行中/成功/失败）、步骤列表等属性
- **配方 (Recipe)**: 可复用的自动化脚本，具有名称、描述、参数等属性
- **技能 (Skill)**: Claude Code 技能定义，具有名称、描述、位置等属性
- **配置 (Config)**: 用户偏好设置，包含主题、轮询间隔等属性
- **Linux 发行版**: 操作系统类型，关联对应的包管理器和依赖包名

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 开发者修改组件代码后，界面更新时间不超过 3 秒
- **SC-002**: 生产构建的 GUI 启动后，所有 5 个页面功能完整可用
- **SC-003**: 前端代码具备完整的类型定义，TypeScript 编译零错误
- **SC-004**: Linux 用户在支持的发行版上首次运行时，整个自动安装流程可在 5 分钟内完成（含下载依赖时间）
- **SC-005**: 用户切换主题后，界面颜色变化延迟不超过 500 毫秒
- **SC-006**: 任务列表在后台有新任务时，更新延迟不超过配置的轮询间隔时间
- **SC-007**: 对于不支持的 Linux 发行版，系统在 10 秒内提供手动安装指南

## Clarifications

### Session 2025-12-09

- Q: 新版 React 前端完成后，旧版前端文件（`assets/scripts/app.js`、`assets/styles/main.css`）应如何处理？ → A: 保留但弃用 - 保留旧文件但标记为 deprecated，作为参考文档存在

## Technical Notes

### pywebview + Vite 集成关键问题 (2025-12-09)

在将 Vite + React 前端集成到 pywebview (WebKit2GTK backend) 时发现两个关键兼容性问题：

**问题 1: 脚本加载时序**

Vite 默认将构建后的 `<script>` 标签放在 `<head>` 中。由于 IIFE 格式的脚本会立即执行，此时 `<div id="root">` 尚未解析，导致 `document.getElementById('root')` 返回 `null`，React 无法挂载。

解决方案：在 `vite.config.ts` 中通过 `transformIndexHtml` 钩子将脚本移至 `</body>` 前。

**问题 2: localStorage 不可用**

pywebview 的 WebKit2GTK 环境中 `localStorage` 为 `null`（非 `undefined`）。直接调用 `localStorage.getItem()` 会抛出 `TypeError: null is not an object`，阻止整个应用初始化。

解决方案：封装 `safeLocalStorage()` 函数，使用 try-catch 和 null 检查保护所有 localStorage 访问。

**Vite 构建配置要点**

```typescript
// vite.config.ts
build: {
  modulePreload: false,        // 必须：禁用模块预加载避免 CORS
  rollupOptions: {
    output: {
      format: 'iife',          // 必须：使用 IIFE 避免 ES modules 问题
      inlineDynamicImports: true,
    },
  },
}
```

`transformIndexHtml` 插件需移除 `crossorigin` 和 `type="module"` 属性，并将脚本移至 body 末尾。

## Assumptions

- pywebview 已正确集成且 API 保持稳定
- 用户的 Node.js 环境版本不低于 18.x（用于开发构建）
- Linux 用户具有 sudo 权限或 pkexec 可用
- 主流 Linux 发行版的包仓库中包含所需的 WebKit/GTK 依赖
