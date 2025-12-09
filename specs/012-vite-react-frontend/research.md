# Research: Vite React 前端重构与 Linux 依赖自动安装

**Date**: 2025-12-09
**Feature**: 012-vite-react-frontend

## 1. Vite + React + TypeScript 与 pywebview 集成

### 决策：采用双模式加载策略

**选择**：开发模式加载 Vite 开发服务器，生产模式加载构建产物

**理由**：
- 开发模式获得 HMR 支持，提升迭代效率
- 生产模式使用 `file://` 协议加载本地文件，与现有架构兼容
- pywebview 的 `window.pywebview.api` 不受浏览器 CORS 限制

**考虑的替代方案**：
- 始终使用静态文件：放弃 HMR，开发体验差
- 始终使用开发服务器：需要 Node.js 运行时，部署复杂

### 关键技术细节

**开发模式检测**：
```python
# 通过环境变量控制
if os.getenv('FRAGO_GUI_DEV') == '1':
    url = "http://localhost:5173"
else:
    url = f"file://{get_asset_path('index.html')}"
```

**TypeScript 类型定义**：
- 创建 `src/types/pywebview.d.ts` 声明 `window.pywebview.api` 接口
- 使用 Pydantic 的 `model_dump(mode="json")` 确保序列化兼容性
- datetime 类型自动转换为 ISO 字符串

**Vite 配置要点**：
- `outDir` 指向 `../assets/`
- 无需特殊 CORS 配置
- 启用 `sourcemap: false` 减小生产包体积

---

## 2. Linux 发行版检测与依赖安装

### 决策：基于 /etc/os-release 的 ID 字段检测

**选择**：解析 `/etc/os-release` 文件的 `ID` 字段识别发行版

**理由**：
- FreeDesktop 标准，覆盖所有主流发行版
- 机器可解析，避免 `NAME` 字段的本地化问题
- 可通过 `ID_LIKE` 字段处理衍生版

**考虑的替代方案**：
- `lsb_release` 命令：部分系统未安装
- `hostnamectl`：需要 systemd
- Python `distro` 包：增加外部依赖

### 决策：pkexec 作为权限提升方式

**选择**：使用 pkexec 获取管理员权限

**理由**：
- GUI 环境下弹出图形化密码对话框，用户体验更好
- 不依赖终端输入，适合桌面应用
- PolicyKit 规则可实现细粒度权限控制

**考虑的替代方案**：
- sudo：需要终端密码输入，GUI 中体验差
- gksudo/kdesudo：已废弃

### 依赖检测策略

三层检测：
1. 检查 `pywebview` 是否可导入
2. 检查 GTK 绑定（`gi.require_version("WebKit2", "4.1")`）
3. 检查 Qt 后端作为备选

### 发行版包名映射

| 发行版 | ID | 包管理器 | GTK 绑定 | WebKit |
|--------|-----|---------|---------|--------|
| Ubuntu/Debian | ubuntu/debian | apt | python3-gi | gir1.2-webkit2-4.1 |
| Fedora/RHEL | fedora/rhel | dnf | python3-gobject | webkit2gtk4.1 |
| Arch/Manjaro | arch/manjaro | pacman | python-gobject | webkit2gtk-4.1 |
| openSUSE | opensuse | zypper | python3-gobject | webkit2gtk3 |

---

## 3. TailwindCSS 主题切换

### 决策：保持现有 CSS 变量系统

**选择**：保留 `[data-theme]` 属性选择器方案，TailwindCSS 作为补充

**理由**：
- 现有设计系统完整，无需大规模重构
- CSS 变量提供主题独立性，易于维护
- TailwindCSS 提供工具类加速开发，两者互补

**考虑的替代方案**：
- 完全迁移到 Tailwind darkMode：需重构所有样式
- 使用 CSS-in-JS：增加运行时开销

### FOUC 预防策略

**选择**：在 HTML `<html>` 标签设置默认 `data-theme` 属性

```html
<html data-theme="dark">
```

**理由**：
- 在 CSS 加载时立即应用正确主题
- 无需等待 JavaScript 执行
- 用户无感知的主题切换

### 状态持久化

优先级：`localStorage.theme` > `prefers-color-scheme` > 应用默认值

```javascript
const theme = localStorage.theme ||
  (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
```

### 优化建议

1. 应用主题时设置 `document.documentElement.style.colorScheme = theme`
2. 切换时临时禁用过渡动画避免闪烁
3. 监听 `storage` 事件实现跨 Tab 同步

---

## 4. 技术栈选择确认

| 技术 | 版本 | 用途 |
|------|------|------|
| Vite | 5.x | 构建工具，HMR 支持 |
| React | 18 | UI 框架 |
| TypeScript | 5.x | 类型安全 |
| TailwindCSS | 3.x | 原子化 CSS |
| Zustand | 4.x | 状态管理（轻量，无 Provider） |

---

## 5. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Vite HMR 与 pywebview 不兼容 | 开发体验 | 回退到 `location.reload()` |
| pkexec 在无 GUI 环境失败 | 自动安装 | 检测环境，回退到命令行提示 |
| 构建产物体积过大 | 包大小 | 启用 tree-shaking，代码分割 |
| 旧浏览器兼容性 | 功能异常 | pywebview 使用系统 WebView，版本可控 |
