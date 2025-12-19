---
name: frago-view-content-generate-tips-code
description: 代码文件内容生成指南。当需要创建可通过 `frago view` 预览的代码文件时使用此 skill。涵盖支持的语言、主题选择、最佳实践。
---

# 代码文件内容生成指南

通过 `frago view` 预览代码文件，自动语法高亮。

## 预览命令

```bash
frago view script.py                      # 默认主题
frago view script.py --theme monokai      # 指定主题
```

---

## 支持的文件类型

| 扩展名 | 语言 | highlight.js 标记 |
|--------|------|------------------|
| `.py` | Python | python |
| `.js` | JavaScript | javascript |
| `.ts` | TypeScript | typescript |
| `.jsx` | JSX | javascript |
| `.tsx` | TSX | typescript |
| `.css` | CSS | css |
| `.scss` | SCSS | scss |
| `.html` | HTML | html |
| `.json` | JSON | json |
| `.yaml` / `.yml` | YAML | yaml |
| `.toml` | TOML | toml |
| `.xml` | XML | xml |
| `.sql` | SQL | sql |
| `.sh` / `.bash` | Bash | bash |
| `.go` | Go | go |
| `.rs` | Rust | rust |
| `.java` | Java | java |
| `.c` / `.h` | C | c |
| `.cpp` / `.hpp` | C++ | cpp |
| `.rb` | Ruby | ruby |
| `.php` | PHP | php |
| `.swift` | Swift | swift |
| `.kt` | Kotlin | kotlin |
| `.lua` | Lua | lua |
| `.r` | R | r |
| `.txt` | 纯文本 | plaintext |

---

## 代码主题

| 主题 | 风格 | 适用场景 |
|------|------|---------|
| `github-dark` | GitHub 深色（默认） | 日常使用 |
| `github` | GitHub 浅色 | 白色背景偏好 |
| `monokai` | Monokai 经典 | 开发者偏好 |
| `atom-one-dark` | Atom 深色 | 现代风格 |
| `atom-one-light` | Atom 浅色 | 浅色偏好 |
| `vs2015` | Visual Studio | Windows 风格 |

```bash
# 使用不同主题预览
frago view main.py --theme monokai
frago view config.yaml --theme atom-one-dark
```

---

## 最佳实践

### 1. 文件编码

- **必须使用 UTF-8 编码**
- 避免 BOM 头
- 换行符使用 LF（Unix 风格）

### 2. 行长度

- 单行不超过 **120 字符**
- 超长行会被截断显示

### 3. 注释规范

```python
# 单行注释清晰简洁

"""
多行注释用于：
- 模块说明
- 函数文档
- 复杂逻辑解释
"""
```

### 4. 代码结构

- 逻辑分组，空行分隔
- 函数/类之间空两行
- 相关导入分组

---

## 显示特性

### 自动行号

代码预览自动显示行号，便于定位。

### 语法高亮

基于 highlight.js 自动识别语言并高亮：
- 关键字
- 字符串
- 注释
- 数字
- 函数名
- 类名

### 样式参考（github-dark）

| 元素 | 颜色 |
|------|------|
| 背景 | `#0d1117` |
| 文字 | `#c9d1d9` |
| 关键字 | `#ff7b72` |
| 字符串 | `#a5d6ff` |
| 注释 | `#8b949e` |
| 函数 | `#d2a8ff` |
| 数字 | `#79c0ff` |

---

## 注意事项

| 问题 | 原因 | 解决 |
|------|------|------|
| 无语法高亮 | 扩展名未识别 | 使用标准扩展名 |
| 中文乱码 | 编码问题 | 确保 UTF-8 |
| 显示截断 | 行太长 | 控制行长度 |
| 渲染慢 | 文件太大 | 拆分或精简 |

---

## 适用场景

- 代码片段展示
- 配置文件预览
- 脚本审查
- 代码分享

**不适用**：大型项目完整源码（建议使用 IDE）
