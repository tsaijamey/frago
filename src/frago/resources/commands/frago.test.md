---
description: "测试并验证现有的Frago配方脚本"
---

# /frago.test - 配方测试指令

测试并验证现有配方。

## 参考文档

| 类型 | 文档 | 说明 |
|------|------|------|
| **规则** | [SCREENSHOT_RULES.md](frago/rules/SCREENSHOT_RULES.md) | 截图规范 |
| **指南** | [RECIPE_FIELDS.md](frago/guides/RECIPE_FIELDS.md) | 配方字段规范 |
| **示例** | [common_commands.sh](frago/scripts/common_commands.sh) | 通用命令 |

---

## 核心定位

| 项目 | 说明 |
|------|------|
| **角色** | 自动化测试工程师（QA） |
| **目标** | 验证配方是否正常工作、输出是否符合预期 |
| **关键** | 能运行 ≠ 结果正确 |

---

## 执行流程

### 1. 定位配方

```bash
# 查找配方
frago recipe list
frago recipe info <recipe_name>
```

### 2. 基础验证

**在功能测试前，先验证配方结构完整性**：

```bash
frago recipe validate <配方目录>
```

详见 [RECIPE_FIELDS.md](frago/guides/RECIPE_FIELDS.md)。验证失败则先修复结构问题。

### 3. 理解需求

读取 `recipe.md`，重点关注：
- **前置条件**：当前页面需要是什么？
- **预期输出**：成功应该返回什么格式的数据？

### 4. 环境检查

```bash
# 检查 CDP 连接
frago status

# 检查当前页面
frago chrome exec-js "window.location.href" --return-value
frago chrome get-title
```

**如果页面不符合前置条件，中止测试并提示用户导航。**

### 5. 执行测试

```bash
# 推荐方式
frago recipe run <recipe_name> --output-file result.json

# 传统方式（chrome-js）
frago chrome exec-js examples/atomic/chrome/<recipe_name>/recipe.js --return-value
```

### 6. 结果验证

**严格校验数据**，不要仅因脚本没报错就判定成功。

---

## 测试报告

### 场景 A: 测试通过

```markdown
## ✅ 测试通过: <配方名>

**返回数据**:
```json
<返回的数据>
```

**数据校验**:
- [x] 格式符合文档定义
- [x] 关键字段非空
```

### 场景 B: 执行成功但数据异常

```markdown
## ⚠️ 执行成功但数据异常: <配方名>

**返回数据**: `""` (空字符串) 或 `null`
**文档预期**: <文档中的描述>
**分析**: 脚本运行未崩溃，但未能提取到有效信息。可能是选择器失效。
```

### 场景 C: 执行报错

```markdown
## ❌ 测试失败: <配方名>

**错误信息**: <错误日志>
**原因分析**: 选择器失效 / 页面状态不正确
**建议**:
1. 确认当前页面是否正确
2. 使用 `/frago.recipe update <名称>` 修复
```

---

## 截图规范

详见 [SCREENSHOT_RULES.md](frago/rules/SCREENSHOT_RULES.md)

| 用途 | 说明 |
|------|------|
| ✅ 校验页面状态 | 确认前置条件 |
| ✅ 记录失败现场 | 调试问题 |
| ❌ 读取内容 | 用 get-content |

---

## 常用命令

```bash
# 查找配方
frago recipe list
frago recipe info <name>

# 基础验证（结构完整性）
frago recipe validate <配方目录>
frago recipe validate <配方目录> --format json

# 检查状态
frago chrome status
frago chrome exec-js "window.location.href" --return-value

# 执行配方
frago recipe run <name>
frago recipe run <name> --output-file result.json

# 直接执行 chrome-js
frago chrome exec-js examples/atomic/chrome/<name>/recipe.js --return-value
```

---

## 测试层次

| 层次 | 命令 | 检查内容 |
|------|------|---------|
| **结构验证** | `frago recipe validate` | 字段完整性、格式、脚本存在 |
| **功能测试** | `frago recipe run` | 实际执行、返回数据 |
| **数据校验** | 手动检查 | 返回数据是否符合预期 |

