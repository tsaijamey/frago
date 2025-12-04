# Quickstart: Frago GUI 应用模式

**Feature**: 008-gui-app-mode
**Date**: 2025-12-04

## 安装

### 快速检查

```bash
# 检查 GUI 依赖状态
frago gui-deps

# 查看安装命令
frago gui-deps --install
```

### Ubuntu / Debian

```bash
# 方式 1: 使用系统包（推荐，无需编译）
sudo apt install -y python3-gi python3-gi-cairo gir1.2-webkit2-4.1
pip install pywebview

# 方式 2: 从源码编译
sudo apt install -y libcairo2-dev libgirepository1.0-dev \
    libgirepository-2.0-dev gir1.2-webkit2-4.1 python3-dev
pip install pywebview PyGObject
```

### Fedora / RHEL / CentOS

```bash
sudo dnf install -y python3-gobject python3-gobject-base webkit2gtk4.1
pip install pywebview
```

### Arch Linux

```bash
sudo pacman -S python-gobject webkit2gtk-4.1
pip install pywebview
```

### macOS

```bash
pip install pywebview
# macOS 使用原生 WebKit，无需额外依赖
```

### Windows

```bash
pip install pywebview
# Windows 使用 Edge WebView2，可能需要安装 Edge WebView2 Runtime
```

## 启动 GUI

```bash
frago --gui
```

首次启动时，系统会：
1. 检测图形环境
2. 创建配置目录 `~/.frago/`
3. 启动 600×1434 无边框窗口

## 界面概览

```
┌────────────────────────────────────────────┐
│  Frago GUI              ⚙ 设置             │ ← 顶部导航栏
├─────────┬─────────┬─────────┬──────────────┤
│  主页   │ 配方    │ Skills  │ 历史         │ ← 页面标签
├─────────┴─────────┴─────────┴──────────────┤
│                                            │
│  ┌─────────────────────────────────────┐   │
│  │ 输入命令或问题...                   │   │ ← 输入区域
│  │                              [发送] │   │
│  └─────────────────────────────────────┘   │
│                                            │
│  ┌─────────────────────────────────────┐   │
│  │                                     │   │
│  │          结果展示区域               │   │ ← 响应区域
│  │                                     │   │
│  └─────────────────────────────────────┘   │
│                                            │
│  [进度条]                                  │ ← 任务进度
│                                            │
├────────────────────────────────────────────┤
│  CPU: 12%  MEM: 45%  ● 已连接              │ ← 状态栏
└────────────────────────────────────────────┘
```

## 基本操作

### 发送命令

1. 在输入框输入内容
2. 点击「发送」或按 `Ctrl+Enter`
3. 等待 agent 响应

### 运行配方

1. 切换到「配方」页面
2. 点击配方名称
3. 查看执行结果

### 查看历史

1. 切换到「历史」页面
2. 浏览命令执行记录
3. 点击条目查看详情

### 修改设置

1. 点击右上角「设置」图标
2. 调整主题、字体大小等
3. 设置自动保存

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Enter` | 发送消息 |
| `Ctrl+L` | 清空输出 |
| `Ctrl+,` | 打开设置 |
| `Escape` | 取消当前任务 |

## 配置文件

配置存储在 `~/.frago/gui_config.json`：

```json
{
  "theme": "dark",
  "font_size": 14,
  "confirm_on_exit": true,
  "auto_scroll_output": true
}
```

## 故障排除

### 检查依赖状态

```bash
# 首先运行依赖检查
frago gui-deps

# 如果有缺失，查看安装命令
frago gui-deps --install
```

### 无法启动 GUI

```
Error: No display found
```

解决：确保在图形桌面环境中运行，或检查 `$DISPLAY` 环境变量。

### "pywebview is not installed"

运行 `frago gui-deps --install` 查看适合你系统的安装命令。

### "GTK cannot be loaded" / "QT cannot be loaded"

需要安装系统级 GTK/WebKit 依赖。

**Ubuntu/Debian**:
```bash
# 推荐：使用系统包
sudo apt install -y python3-gi python3-gi-cairo gir1.2-webkit2-4.1

# 如果需要编译安装
sudo apt install -y libcairo2-dev libgirepository1.0-dev \
    libgirepository-2.0-dev gir1.2-webkit2-4.1 python3-dev
pip install PyGObject
```

**Fedora**:
```bash
sudo dnf install -y python3-gobject webkit2gtk4.1
```

### pycairo / PyGObject 编译失败

缺少编译依赖：

```bash
# Ubuntu/Debian
sudo apt install -y libcairo2-dev libgirepository1.0-dev \
    libgirepository-2.0-dev python3-dev

# Fedora
sudo dnf install -y cairo-devel gobject-introspection-devel python3-devel
```

### 任务无响应

1. 检查状态栏连接状态
2. 点击「取消」终止当前任务
3. 查看历史记录中的错误信息

## 开发模式

```bash
# 启用调试工具
frago --gui --debug
```

调试模式下：
- 打开 WebView 开发者工具
- 输出详细日志到终端
- 热重载前端资源（开发用）

## 下一步

- 阅读 [API 契约](./contracts/js-python-api.md) 了解 JS-Python 通信
- 阅读 [数据模型](./data-model.md) 了解实体定义
- 阅读 [研究文档](./research.md) 了解技术选型
