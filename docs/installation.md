# 安装指南

## 基础安装

安装核心功能（CDP 操作 + Recipe 系统核心）：

```bash
# 使用 pip
pip install frago

# 使用 uv（推荐）
uv add frago
```

**核心功能包含**：
- ✅ Chrome DevTools Protocol (CDP) 操作
- ✅ Recipe 系统（列表、执行、元数据管理）
- ✅ 输出到 stdout 和 file
- ✅ Python/Shell Recipe 执行
- ✅ Workflow 编排

---

## 可选功能

### 剪贴板支持

如果需要将 Recipe 结果输出到剪贴板：

```bash
# 使用 pip
pip install frago[clipboard]

# 使用 uv
uv add "frago[clipboard]"
```

**提供的额外功能**：
- ✅ `--output-clipboard` 选项
- ✅ `clipboard_read` Recipe（系统剪贴板读取）

---

### 完整安装（所有可选功能）

安装所有功能：

```bash
# 使用 pip
pip install frago[all]

# 使用 uv
uv add "frago[all]"
```

---

## 开发环境安装

如果要参与开发或运行测试：

```bash
# 克隆仓库
git clone https://github.com/frago/frago.git
cd frago

# 使用 uv 安装开发依赖（推荐）
uv sync --all-extras --dev

# 或使用 pip
pip install -e ".[dev,all]"
```

**开发依赖包含**：
- pytest（测试框架）
- pytest-cov（覆盖率）
- ruff（代码检查）
- mypy（类型检查）
- black（代码格式化）

---

## 依赖说明

### 强制依赖（所有用户都会安装）

```toml
dependencies = [
    "websocket-client>=1.9.0",  # CDP WebSocket 连接
    "click>=8.1.0",             # CLI 框架
    "pydantic>=2.0.0",          # 数据验证
    "python-dotenv>=1.0.0",     # 环境变量
    "pyyaml>=6.0.0",            # Recipe 元数据解析
]
```

### 可选依赖（按需安装）

```toml
[project.optional-dependencies]
clipboard = ["pyperclip>=1.8.0"]  # 剪贴板功能
all = ["pyperclip>=1.8.0"]         # 所有可选功能
dev = ["pytest>=7.4.0", ...]       # 开发工具
```

---

## 系统要求

- **Python**: 3.9+
- **操作系统**: macOS, Linux, Windows
- **Chrome 浏览器**: 用于 chrome-js Recipe 执行

---

## 验证安装

安装后验证：

```bash
# 检查版本
frago --version

# 列出可用 Recipe
frago recipe list

# 查看帮助
frago --help
```

---

## 升级

```bash
# 使用 pip
pip install --upgrade frago

# 使用 uv
uv add --upgrade frago
```

---

## 卸载

```bash
# 使用 pip
pip uninstall frago

# 使用 uv
uv remove frago
```
