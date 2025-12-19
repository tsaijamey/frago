---
name: frago-view-content-generate-tips-json
description: JSON 文件内容生成指南。当需要创建可通过 `frago view` 预览的 JSON 文件时使用此 skill。涵盖格式化显示、最佳实践。
---

# JSON 文件内容生成指南

通过 `frago view` 预览 JSON 文件，自动格式化和语法高亮。

## 预览命令

```bash
frago view data.json                      # 默认主题
frago view config.json --theme monokai    # 指定主题
```

---

## 渲染特性

### 自动格式化

- JSON 内容自动美化（Pretty Print）
- 缩进对齐
- 键值对清晰显示

### 语法高亮

| 元素 | 颜色示例（github-dark） |
|------|------------------------|
| 键名 | 紫色 `#d2a8ff` |
| 字符串值 | 蓝色 `#a5d6ff` |
| 数字 | 青色 `#79c0ff` |
| 布尔值 | 红色 `#ff7b72` |
| null | 红色 `#ff7b72` |
| 括号/逗号 | 白色 `#c9d1d9` |

---

## JSON 格式规范

### 正确格式

```json
{
    "name": "项目名称",
    "version": "1.0.0",
    "enabled": true,
    "count": 42,
    "tags": ["tag1", "tag2"],
    "config": {
        "nested": "value"
    },
    "nullable": null
}
```

### 常见错误

| 错误 | 示例 | 修正 |
|------|------|------|
| 尾随逗号 | `{"a": 1,}` | `{"a": 1}` |
| 单引号 | `{'a': 1}` | `{"a": 1}` |
| 无引号键 | `{a: 1}` | `{"a": 1}` |
| 注释 | `// comment` | 不支持注释 |
| undefined | `undefined` | 使用 `null` |

---

## 最佳实践

### 1. 缩进

- 使用 **2 或 4 空格** 缩进
- 保持一致性

### 2. 键命名

- 使用 **snake_case** 或 **camelCase**
- 保持整个文件一致

```json
{
    "user_name": "snake_case 风格",
    "userName": "camelCase 风格"
}
```

### 3. 数据组织

- 相关字段分组
- 重要字段放前面

```json
{
    "id": "001",
    "name": "重要字段优先",
    "metadata": {
        "created_at": "2024-01-01",
        "updated_at": "2024-01-02"
    }
}
```

### 4. 文件大小

- 单文件 < 1MB 最佳
- 大数据考虑分页或分文件

---

## 适用场景

- API 响应数据预览
- 配置文件查看
- 数据结构审查
- 调试数据检查

---

## 显示主题

与代码文件相同，支持以下主题：

| 主题 | 命令 |
|------|------|
| github-dark（默认） | `frago view data.json` |
| monokai | `frago view data.json --theme monokai` |
| atom-one-dark | `frago view data.json --theme atom-one-dark` |

---

## 注意事项

| 问题 | 原因 | 解决 |
|------|------|------|
| 解析失败 | JSON 格式错误 | 使用 JSON 验证器 |
| 显示截断 | 值太长 | 使用嵌套结构 |
| 渲染慢 | 文件太大 | 拆分或精简 |

---

## JSON 验证

预览前确保 JSON 有效：

```bash
# Python 验证
python -m json.tool data.json

# jq 验证
jq . data.json
```

---

## 相关工具

- **jq**：命令行 JSON 处理器
- **jsonlint**：JSON 验证器
- **VSCode**：JSON 编辑和格式化
