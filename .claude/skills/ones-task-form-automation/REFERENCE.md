# ONES Create Task 表单详细参考

## 完整字段列表

### 文本输入字段

| 索引 | 字段名称 | 选择器 | 元素类型 | 必填 | 说明 |
|-----|---------|--------|---------|------|------|
| 0 | Title（标题） | `#summary` | `<input type="text">` | ✓ | 任务标题，最重要的字段 |
| 3 | 描述 | `.ones-form-item:nth-child(4) textarea` | `<textarea>` | - | 多行文本描述 |
| 4 | 验收标准 | `.ones-form-item:nth-child(5) textarea` | `<textarea>` | - | 任务验收条件 |
| 8 | 截止日期 | `.ones-form-item:nth-child(9) input` | `<input type="text">` | - | 日期选择器 |
| 9 | 预估工时 | `.ones-input-number-input` | `<input type="text">` | - | 数字输入（如 "2.5 hours"） |
| 15 | 计划开始日期 | `.ones-form-item:nth-child(16) input` | `<input type="text">` | - | 日期选择器 |
| 16 | 计划完成日期 | `.ones-form-item:nth-child(17) input` | `<input type="text">` | - | 日期选择器 |

### 下拉选择字段

| 索引 | 字段名称 | `.ones-form-item` 索引 | 当前值示例 | 说明 |
|-----|---------|----------------------|-----------|------|
| 1 | 项目选择 | 1 | 【Scrum】D端-算法/AI应用 | 选择所属项目 |
| 2 | 任务类别 | 2 | Task | Task/Story/Bug/Epic 等 |
| 5 | 所属迭代 | 5 | None | 选择 Sprint 迭代 |
| 6 | 任务类型 | 6 | None | 自定义任务类型（功能开发/Bug修复等） |
| 7 | 负责人 | 7 | 佳蔡佳(caijia@chagee.com) | 团队成员选择 |
| 9 | 所属模块 | 9 | None | 模块/组件分类 |
| 13 | 优先级 | 13 | None | 优先级等级 |
| 19 | 额外成员 | 19 | Select a member | 协作成员 |

### 其他控件

| 字段 | 类型 | 说明 |
|-----|------|------|
| 进度条 | 进度组件 | 任务完成百分比 |
| 文件上传 | `<input type="file">` | 附件上传 |
| 关联任务 | 复选框 | 是否创建关联 |

## 定位策略详解

### 策略 1：通过 ID（最稳定）

```javascript
// 标题字段有固定 ID
const titleInput = document.querySelector('#summary');
```

**优点**：最可靠，不受页面结构变化影响
**缺点**：只有少数字段有 ID

### 策略 2：通过 `.ones-form-item` 索引

```javascript
const formItems = document.querySelectorAll('.ones-form-item');
const descField = formItems[3].querySelector('textarea');
```

**优点**：简单直接
**缺点**：字段顺序变化会失效

### 策略 3：通过 Label 文本（推荐）

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
const descField = getFieldByLabel('描述');
```

**优点**：最灵活，适应页面结构变化
**缺点**：可能受多语言影响

## 下拉菜单操作详解

### 下拉菜单结构

ONES 使用 Ant Design 风格的 Select 组件：

```html
<div class="ones-select">
  <div class="ones-select-selector">
    <span class="ones-select-selection-item">当前选中值</span>
    <input type="search" class="ones-select-selection-search-input">
  </div>
</div>

<!-- 点击后动态生成的下拉菜单（在 body 末尾）-->
<div class="ones-select-dropdown" style="...">
  <div class="rc-virtual-list">
    <div class="ones-select-item">选项1</div>
    <div class="ones-select-item ones-select-item-option-selected">选项2</div>
    <div class="ones-select-item">选项3</div>
  </div>
</div>
```

### 选择选项的完整流程

```javascript
function selectDropdownOption(selectBox, optionText) {
  return new Promise((resolve, reject) => {
    // 1. 滚动到元素可见区域
    selectBox.scrollIntoView({ behavior: 'smooth', block: 'center' });

    // 2. 点击打开下拉菜单
    selectBox.click();

    // 3. 等待下拉菜单渲染（异步）
    setTimeout(() => {
      // 4. 查找下拉菜单
      const dropdown = document.querySelector(
        '.ones-select-dropdown:not(.ones-select-dropdown-hidden)'
      );

      if (!dropdown) {
        reject(new Error('下拉菜单未打开'));
        return;
      }

      // 5. 查找目标选项
      const options = dropdown.querySelectorAll('.ones-select-item');
      const targetOption = Array.from(options).find(opt =>
        opt.textContent.trim() === optionText
      );

      if (targetOption) {
        // 6. 点击选项
        targetOption.click();
        resolve(true);
      } else {
        reject(new Error(`选项 "${optionText}" 未找到`));
      }
    }, 300);  // 等待 300ms
  });
}

// 使用（异步）
const modal = document.querySelectorAll('.ones-modal')[0];
const taskTypeSelect = modal.querySelectorAll('.ones-form-item')[6].querySelector('.ones-select');

selectDropdownOption(taskTypeSelect, '功能开发')
  .then(() => console.log('选择成功'))
  .catch(err => console.error(err));
```

### 搜索型下拉菜单

部分下拉菜单支持搜索（如成员选择）：

```javascript
function selectWithSearch(selectBox, searchText) {
  // 1. 打开下拉菜单
  selectBox.click();

  setTimeout(() => {
    // 2. 找到搜索输入框
    const searchInput = selectBox.querySelector('.ones-select-selection-search-input');

    // 3. 输入搜索文本
    const inputSetter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value'
    ).set;
    inputSetter.call(searchInput, searchText);
    searchInput.dispatchEvent(new Event('input', { bubbles: true }));

    // 4. 等待搜索结果
    setTimeout(() => {
      const dropdown = document.querySelector('.ones-select-dropdown:not(.ones-select-dropdown-hidden)');
      const firstOption = dropdown.querySelector('.ones-select-item');
      firstOption?.click();
    }, 500);
  }, 300);
}
```

## 日期选择器操作

日期字段使用 DatePicker 组件：

```javascript
function selectDate(dateInput, dateString) {
  // 方法 1：直接填写日期字符串（简单但可能失效）
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value'
  ).set;
  setter.call(dateInput, dateString);  // 格式：YYYY-MM-DD
  dateInput.dispatchEvent(new Event('input', { bubbles: true }));
  dateInput.dispatchEvent(new Event('change', { bubbles: true }));

  // 方法 2：打开日期选择器并点击（更可靠）
  dateInput.click();  // 打开日期面板

  setTimeout(() => {
    // 查找对应日期的单元格并点击
    const datePicker = document.querySelector('.ones-picker-dropdown');
    const targetCell = Array.from(datePicker.querySelectorAll('.ones-picker-cell'))
      .find(cell => cell.getAttribute('title') === dateString);
    targetCell?.click();
  }, 300);
}
```

## 数字输入框

预估工时等数字字段：

```javascript
function fillNumberInput(numberInput, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value'
  ).set;

  // 支持两种格式
  const displayValue = typeof value === 'number' ? `${value} hours` : value;

  setter.call(numberInput, displayValue);
  numberInput.dispatchEvent(new Event('input', { bubbles: true }));
  numberInput.dispatchEvent(new Event('change', { bubbles: true }));
}

// 使用
const numberInput = document.querySelector('.ones-input-number-input');
fillNumberInput(numberInput, 5);     // 自动格式化为 "5 hours"
fillNumberInput(numberInput, '2.5'); // 或直接传字符串
```

## 文件上传

```javascript
// 文件上传需要构造 File 对象
const fileInput = document.querySelector('input[type="file"]');

// 方法 1：通过文件路径（需要用户交互）
fileInput.click();  // 触发文件选择对话框

// 方法 2：程序化创建 File 对象（适用于自动化）
const file = new File(['文件内容'], 'filename.txt', { type: 'text/plain' });
const dataTransfer = new DataTransfer();
dataTransfer.items.add(file);
fileInput.files = dataTransfer.files;

// 触发 change 事件
fileInput.dispatchEvent(new Event('change', { bubbles: true }));
```

## 调试工具函数

### 查看所有表单数据

```javascript
function dumpFormData() {
  const modal = document.querySelectorAll('.ones-modal')[0];
  const formItems = modal.querySelectorAll('.ones-form-item');

  console.log('=== ONES Create Task 表单数据 ===\n');

  formItems.forEach((item, index) => {
    const label = item.querySelector('label')?.textContent.trim() || `(无标签 ${index})`;
    const input = item.querySelector('input, textarea');
    const select = item.querySelector('.ones-select');

    let value = '';
    if (input) {
      value = input.value || '(空)';
    } else if (select) {
      value = select.querySelector('.ones-select-selection-item, .ones-select-selection-placeholder')?.textContent.trim() || '(未选择)';
    }

    console.log(`${index}. ${label}`);
    console.log(`   值: ${value}\n`);
  });
}

// 使用
dumpFormData();
```

### 验证必填字段

```javascript
function validateRequiredFields() {
  const modal = document.querySelectorAll('.ones-modal')[0];
  const titleInput = modal.querySelector('#summary');

  const errors = [];

  if (!titleInput.value.trim()) {
    errors.push('标题不能为空');
  }

  if (errors.length > 0) {
    console.error('验证失败：', errors);
    return false;
  }

  console.log('验证通过');
  return true;
}
```

## 事件监听器分析

查看元素上的事件监听器（Chrome DevTools Console）：

```javascript
// 查看标题输入框的所有事件监听器
const titleInput = document.querySelector('#summary');
getEventListeners(titleInput);

// 输出示例：
// {
//   input: [...]   // input 事件监听器
//   change: [...]  // change 事件监听器
//   focus: [...]   // focus 事件监听器
//   blur: [...]    // blur 事件监听器
// }
```

## 性能考虑

### 批量填写优化

批量填写多个字段时，避免频繁触发事件：

```javascript
function fillMultipleFields(fieldMap) {
  const modal = document.querySelectorAll('.ones-modal')[0];

  // 1. 先填写所有字段（不触发事件）
  for (const [selector, value] of Object.entries(fieldMap)) {
    const element = modal.querySelector(selector);
    const setter = Object.getOwnPropertyDescriptor(
      element.tagName === 'INPUT' ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype,
      'value'
    ).set;
    setter.call(element, value);
  }

  // 2. 统一触发 change 事件
  for (const selector of Object.keys(fieldMap)) {
    const element = modal.querySelector(selector);
    element.dispatchEvent(new Event('change', { bubbles: true }));
  }
}

// 使用
fillMultipleFields({
  '#summary': '批量任务标题',
  'textarea': '批量任务描述',
  '.ones-input-number-input': '3 hours'
});
```

## 常见错误处理

### 错误 1：元素未找到

```javascript
function safeQuerySelector(selector, context = document) {
  const element = context.querySelector(selector);
  if (!element) {
    throw new Error(`元素未找到：${selector}`);
  }
  return element;
}

// 使用
try {
  const titleInput = safeQuerySelector('#summary', modal);
  fillTextField(titleInput, '标题');
} catch (err) {
  console.error(err.message);
}
```

### 错误 2：下拉菜单未打开

```javascript
function selectWithRetry(selectBox, optionText, maxRetries = 3) {
  let attempts = 0;

  function trySelect() {
    return selectDropdownOption(selectBox, optionText)
      .catch(err => {
        attempts++;
        if (attempts < maxRetries) {
          console.log(`重试 ${attempts}/${maxRetries}`);
          return new Promise(resolve => setTimeout(resolve, 500))
            .then(trySelect);
        }
        throw err;
      });
  }

  return trySelect();
}
```

### 错误 3：React 状态未更新

某些情况下，即使触发了事件，React 仍可能未更新状态。可以尝试：

```javascript
// 方法 1：触发更多事件类型
element.dispatchEvent(new InputEvent('input', { bubbles: true, cancelable: true }));
element.dispatchEvent(new Event('blur', { bubbles: true }));

// 方法 2：模拟键盘输入
element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
element.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter' }));
```
