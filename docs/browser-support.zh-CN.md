[English](browser-support.md)

# 浏览器支持

frago 通过 Chrome DevTools Protocol (CDP) 控制基于 Chromium 的浏览器。本文档说明支持的浏览器及使用方法。

## 支持的浏览器

| 浏览器 | 支持状态 | 说明 |
|--------|----------|------|
| **Chrome** | ✅ 完整支持 | 默认选择，推荐使用 |
| **Edge** | ✅ 完整支持 | 与 Chrome 使用相同的 CDP 协议 |
| **Chromium** | ✅ 完整支持 | 开源版本 |
| **Firefox** | ❌ 不支持 | Firefox 141 (2025) 已移除 CDP |
| **Safari** | ❌ 不支持 | 无 CDP 支持 |

所有支持的浏览器使用相同的 CDP 协议，命令在 Chrome、Edge、Chromium 间通用。

---

## 浏览器检测

frago 使用三层策略自动检测已安装的浏览器：

1. **PATH 查找** - 检查系统 PATH 中是否存在浏览器命令（最高优先级）
2. **默认路径** - 检查平台特定的安装位置
3. **注册表查询** - 仅限 Windows，查询 App Paths 注册表以发现非标准安装

### 查看可用浏览器

```bash
frago chrome detect
```

输出示例：
```
Available browsers:

  Chrome     ✓  /usr/bin/google-chrome
  Edge       ✓  /usr/bin/microsoft-edge
  Chromium   ✗  not found

Default: chrome (first available)
```

---

## 浏览器生命周期命令

### 启动浏览器

```bash
# 自动检测浏览器（优先级：Chrome > Edge > Chromium）
frago chrome start

# 指定浏览器
frago chrome start --browser chrome
frago chrome start --browser edge
frago chrome start -b chromium
```

**启动模式**：

| 模式 | 参数 | 说明 |
|------|------|------|
| 普通 | （默认） | 标准浏览器窗口 |
| 无头 | `--headless` | 无 UI，适用于服务器端自动化 |
| 隐藏 | `--void` | 窗口移至屏幕外 |
| 应用 | `--app --app-url URL` | 无边框窗口，用于特定 URL |

```bash
# 无头模式（无窗口）
frago chrome start --headless

# 隐藏模式（窗口在屏幕外）
frago chrome start --void

# 应用模式（无边框窗口）
frago chrome start --app --app-url http://localhost:8080
```

**其他选项**：

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `--port` | 9222 | CDP 调试端口 |
| `--width` | 1280 | 窗口宽度 |
| `--height` | 960 | 窗口高度 |
| `--profile-dir` | 自动 | 用户数据目录 |
| `--no-kill` | false | 不关闭现有 CDP 进程 |
| `--keep-alive` | false | 保持运行直到 Ctrl+C |

### 检查状态

```bash
frago chrome status
```

### 停止浏览器

```bash
frago chrome stop

# 停止特定端口的浏览器
frago chrome stop --port 9333
```

---

## 页面操作

所有页面操作在支持的浏览器间完全通用。

### 导航

```bash
# 导航到 URL
frago chrome navigate https://example.com

# 等待页面加载
frago chrome wait 2000
```

### 元素交互

```bash
# 点击元素
frago chrome click "#submit-button"
frago chrome click "button[type=submit]"

# 执行 JavaScript
frago chrome exec-js "document.title"
frago chrome exec-js "return document.querySelectorAll('a').length"
```

### 页面内容

```bash
# 获取页面标题
frago chrome get-title

# 获取页面内容（HTML 或文本）
frago chrome get-content
frago chrome get-content --format text
```

### 截图

```bash
# 全页截图
frago chrome screenshot output.png

# 元素截图
frago chrome screenshot element.png --selector "#main-content"
```

### 滚动

```bash
# 按像素滚动
frago chrome scroll 500

# 滚动到元素
frago chrome scroll-to "#footer"
```

### 缩放

```bash
# 设置缩放级别（1.0 = 100%）
frago chrome zoom 1.5
```

---

## 标签页管理

```bash
# 列出所有标签页
frago chrome list-tabs

# 切换到指定标签页
frago chrome switch-tab 0
```

---

## 视觉效果

这些命令用于调试和演示目的添加视觉标记。

```bash
# 高亮元素
frago chrome highlight "#target-element"

# 添加指针标记
frago chrome pointer 100 200

# 聚焦元素（其他区域变暗）
frago chrome spotlight "#focus-element"

# 添加文字注释
frago chrome annotate "#element" "这里很重要"

# 下划线
frago chrome underline "#text-element"

# 清除所有视觉效果
frago chrome clear-effects
```

---

## Profile 管理

每种浏览器使用独立的 profile 目录：

| 浏览器 | Profile 目录 |
|--------|--------------|
| Chrome | `~/.frago/chrome_profile` |
| Edge | `~/.frago/edge_profile` |
| Chromium | `~/.frago/chromium_profile` |

Profile 会自动从系统浏览器 profile 初始化（书签、扩展、Cookie 等）。

**自定义 Profile**：
```bash
frago chrome start --profile-dir /path/to/custom/profile
```

**端口专用 Profile**（用于运行多个实例）：
```bash
frago chrome start --port 9333
# 使用 ~/.frago/chrome_profile_9333
```

---

## 平台特定说明

### Linux

- Wayland 会话自动使用 XWayland 实现隐藏模式
- root 用户自动禁用沙箱（`--no-sandbox`）

### Windows

- 浏览器检测包含注册表查询，可发现非标准安装
- Windows 10/11 预装 Edge

### macOS

- 在 `/Applications/` 目录检测浏览器
- Edge 需要手动安装

---

## 故障排查

### 未找到浏览器

```bash
# 检查可用浏览器
frago chrome detect

# 验证浏览器在 PATH 中
which google-chrome
which microsoft-edge
```

### CDP 连接失败

```bash
# 检查 CDP 端口是否被占用
lsof -i :9222  # Linux/macOS
netstat -an | findstr 9222  # Windows

# 停止现有浏览器并重启
frago chrome stop
frago chrome start
```

### 权限拒绝（Linux）

以 root 运行需要禁用沙箱：
```bash
# frago 会自动处理，也可以手动设置：
export FRAGO_NO_SANDBOX=1
frago chrome start
```
