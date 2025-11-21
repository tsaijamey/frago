---
name: ones-task-form-automation
description: 自动填写 ONES 项目管理系统的 Create Task 表单。包含表单定位、字段识别、React 兼容的填写方法和下拉菜单操作。当需要在 ONES 系统中批量创建或自动填写任务时使用。
---

# ONES Create Task 表单自动化

通过 Chrome CDP 和 JavaScript 自动填写 ONES 项目管理系统的创建任务表单。

## 快速参考

### 表单定位

```javascript
// 定位 Create Task 弹窗（第一个模态框）
const modal = document.querySelectorAll('.ones-modal')[0];
```

### 核心填写方法

```javascript
// 1. 获取原生 setter（绕过 React 拦截）
const inputSetter = Object.getOwnPropertyDescriptor(
  window.HTMLInputElement.prototype, 'value'
).set;

// 2. 设置值
element.focus();
inputSetter.call(element, newValue);

// 3. 触发事件（让框架感知变化）
element.dispatchEvent(new Event('input', { bubbles: true }));
element.dispatchEvent(new Event('change', { bubbles: true }));
element.blur();
```

### 主要字段快速索引

| 字段 | 选择器 | 类型 | 必填 |
|-----|--------|------|-----|
| 标题 | `#summary` | input | ✓ |
| 描述 | `textarea` (第1个) | textarea | - |
| 验收标准 | `.ones-form-item:nth-child(5) textarea` | textarea | - |
| 负责人 | `.ones-form-item:nth-child(8) .ones-select` | select | - |

## Instructions

### 1. 填写文本字段

使用 `fillTextField` 工具函数：

```javascript
function fillTextField(element, value) {
  const tagName = element.tagName.toLowerCase();

  // 获取对应的原生 setter
  const nativeSetter = Object.getOwnPropertyDescriptor(
    tagName === 'input' ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype,
    'value'
  ).set;

  // 设置值并触发事件
  element.focus();
  nativeSetter.call(element, value);
  element.dispatchEvent(new Event('input', { bubbles: true }));
  element.dispatchEvent(new Event('change', { bubbles: true }));
  element.blur();
}

// 使用
const modal = document.querySelectorAll('.ones-modal')[0];
const titleInput = modal.querySelector('#summary');
fillTextField(titleInput, '新任务标题');
```

### 2. 通过标签查找字段

```javascript
function getFieldByLabel(labelText) {
  const formItems = document.querySelectorAll('.ones-form-item');
  for (const item of formItems) {
    const label = item.querySelector('label');
    if (label && label.textContent.includes(labelText)) {
      return item.querySelector('input, textarea, .ones-select');
    }
  }
  return null;
}

// 使用
const titleField = getFieldByLabel('Title');
fillTextField(titleField, '任务标题');
```

### 3. 完整表单填写工作流

- [ ] 定位 Create Task 弹窗
- [ ] 填写标题字段（必填）
- [ ] 填写描述（可选）
- [ ] 填写验收标准（可选）
- [ ] 选择负责人（可选）
- [ ] 验证填写结果

## 通过 AuViMa 执行

```bash
# 基础示例
uv run auvima exec-js "(function() {
  const modal = document.querySelectorAll('.ones-modal')[0];
  const titleInput = modal.querySelector('#summary');

  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(titleInput, '自动填写的任务');
  titleInput.dispatchEvent(new Event('input', { bubbles: true }));

  return '标题已填写：' + titleInput.value;
})()" --return-value
```

## 技术要点

### 为什么使用原生 setter？

现代框架（React/Vue）会拦截属性赋值。直接 `element.value = xxx` 不会触发框架的数据绑定。

**解决方案**：通过 `Object.getOwnPropertyDescriptor` 获取原生 setter，直接调用底层方法。

### 必须触发的事件

- `input` - 输入过程中触发
- `change` - 值改变后触发

两者都需要设置 `{ bubbles: true }` 让事件冒泡到父组件。

### 下拉菜单的异步特性

ONES 下拉菜单是动态渲染的：

1. 点击 `.ones-select` 打开菜单
2. 异步加载选项到 `.ones-select-dropdown`
3. 点击目标选项

需要使用 `setTimeout` 或等待逻辑。

## 常见问题

### 填写后值消失？

**原因**：没有触发事件，框架未感知变化。

**解决**：确保使用了 原生 setter + 事件触发 的完整流程。

### 下拉菜单点不开？

**检查**：
- 元素是否可见：`element.offsetParent !== null`
- 尝试滚动到元素：`element.scrollIntoView()`

## 详细文档

- 完整字段列表和定位方法：[REFERENCE.md](REFERENCE.md)
- 更多使用示例：[EXAMPLES.md](EXAMPLES.md)
