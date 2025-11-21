# ONES Create Task 表单填写示例

## 示例 1：填写基础任务

### 目标
创建一个简单任务，只填写必填字段和描述。

### 代码

```javascript
(function fillBasicTask() {
  const modal = document.querySelectorAll('.ones-modal')[0];

  // 辅助函数
  function fillInput(element, value) {
    const setter = Object.getOwnPropertyDescriptor(
      element.tagName === 'INPUT' ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype,
      'value'
    ).set;

    element.focus();
    setter.call(element, value);
    element.dispatchEvent(new Event('input', { bubbles: true }));
    element.dispatchEvent(new Event('change', { bubbles: true }));
    element.blur();
  }

  // 1. 填写标题（必填）
  const titleInput = modal.querySelector('#summary');
  fillInput(titleInput, '实现用户登录功能');

  // 2. 填写描述
  const descTextarea = modal.querySelector('textarea');
  fillInput(descTextarea, '实现用户通过邮箱和密码登录系统的功能');

  console.log('基础任务填写完成');
  return { success: true, title: titleInput.value };
})();
```

### 执行

```bash
uv run auvima exec-js "(function() {
  const modal = document.querySelectorAll('.ones-modal')[0];

  const fillInput = (el, val) => {
    const setter = Object.getOwnPropertyDescriptor(
      el.tagName === 'INPUT' ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype, 'value'
    ).set;
    el.focus();
    setter.call(el, val);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.blur();
  };

  fillInput(modal.querySelector('#summary'), '实现用户登录功能');
  fillInput(modal.querySelector('textarea'), '实现用户通过邮箱和密码登录系统的功能');

  return '任务填写完成';
})()" --return-value
```

---

## 示例 2：填写完整任务（包含验收标准和工时）

### 目标
创建一个完整的开发任务，包含描述、验收标准、预估工时。

### 代码

```javascript
(function fillCompleteTask() {
  const modal = document.querySelectorAll('.ones-modal')[0];
  const formItems = modal.querySelectorAll('.ones-form-item');

  function fillInput(element, value) {
    const setter = Object.getOwnPropertyDescriptor(
      element.tagName === 'INPUT' ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype,
      'value'
    ).set;

    element.focus();
    setter.call(element, value);
    element.dispatchEvent(new Event('input', { bubbles: true }));
    element.dispatchEvent(new Event('change', { bubbles: true }));
    element.blur();
  }

  // 1. 标题
  fillInput(modal.querySelector('#summary'), '【功能开发】实现数据导出功能');

  // 2. 描述
  fillInput(
    modal.querySelector('textarea'),
    `## 功能描述
实现将表格数据导出为 Excel 文件的功能。

## 技术方案
- 使用 XLSX.js 库
- 支持自定义列选择
- 支持数据过滤后导出

## 实现要点
- 前端生成 Excel 文件
- 使用 Blob 下载
- 文件名包含时间戳`
  );

  // 3. 验收标准（第5个 form-item）
  const acceptanceTextarea = formItems[4].querySelector('textarea');
  if (acceptanceTextarea) {
    fillInput(
      acceptanceTextarea,
      `- [ ] 能够正确导出当前表格数据
- [ ] 导出的 Excel 文件格式正确
- [ ] 支持中文字符
- [ ] 文件名包含时间戳
- [ ] 代码通过 Code Review`
    );
  }

  // 4. 预估工时
  const numberInput = modal.querySelector('.ones-input-number-input');
  if (numberInput) {
    fillInput(numberInput, '8 hours');
  }

  console.log('完整任务填写完成');
  return {
    title: modal.querySelector('#summary').value,
    hours: numberInput?.value
  };
})();
```

### 执行

```bash
uv run auvima exec-js "完整任务脚本" --return-value
```

---

## 示例 3：通过 Label 动态查找字段

### 目标
不依赖固定索引，通过字段标签动态查找并填写。

### 代码

```javascript
(function fillTaskByLabels() {
  const modal = document.querySelectorAll('.ones-modal')[0];

  // 通用工具函数
  function getFieldByLabel(labelText) {
    const formItems = modal.querySelectorAll('.ones-form-item');
    for (const item of formItems) {
      const label = item.querySelector('label');
      if (label && label.textContent.includes(labelText)) {
        return item.querySelector('input, textarea, .ones-select');
      }
    }
    return null;
  }

  function fillInput(element, value) {
    if (!element) return false;

    const setter = Object.getOwnPropertyDescriptor(
      element.tagName === 'INPUT' ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype,
      'value'
    ).set;

    element.focus();
    setter.call(element, value);
    element.dispatchEvent(new Event('input', { bubbles: true }));
    element.dispatchEvent(new Event('change', { bubbles: true }));
    element.blur();

    return true;
  }

  // 按标签填写字段
  const fieldsToFill = {
    'Title': '【Bug修复】修复登录页面样式问题',
    '描述': `## 问题描述
登录页面在移动端显示异常。

## 复现步骤
1. 打开登录页面
2. 切换到移动端视图
3. 观察布局

## 期望结果
布局自适应移动端屏幕`,
    '验收标准': `- [ ] 移动端布局正常
- [ ] 桌面端不受影响
- [ ] 通过 UI 测试`
  };

  const results = {};
  for (const [label, value] of Object.entries(fieldsToFill)) {
    const field = getFieldByLabel(label);
    results[label] = fillInput(field, value);
  }

  console.log('填写结果：', results);
  return results;
})();
```

---

## 示例 4：选择下拉菜单选项

### 目标
选择任务类型、负责人等下拉菜单字段。

### 代码

```javascript
(async function fillTaskWithSelections() {
  const modal = document.querySelectorAll('.ones-modal')[0];
  const formItems = modal.querySelectorAll('.ones-form-item');

  // 选择下拉菜单选项
  function selectDropdownOption(selectBox, optionText) {
    return new Promise((resolve, reject) => {
      selectBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
      selectBox.click();

      setTimeout(() => {
        const dropdown = document.querySelector('.ones-select-dropdown:not(.ones-select-dropdown-hidden)');
        if (!dropdown) {
          reject(new Error('下拉菜单未打开'));
          return;
        }

        const options = dropdown.querySelectorAll('.ones-select-item');
        const targetOption = Array.from(options).find(opt =>
          opt.textContent.trim().includes(optionText)
        );

        if (targetOption) {
          targetOption.click();
          resolve(true);
        } else {
          reject(new Error(`选项 "${optionText}" 未找到`));
        }
      }, 300);
    });
  }

  // 1. 填写标题
  const titleInput = modal.querySelector('#summary');
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(titleInput, '【需求】添加导出功能');
  titleInput.dispatchEvent(new Event('input', { bubbles: true }));

  // 2. 选择任务类型（假设在第6个 form-item）
  try {
    const taskTypeSelect = formItems[6].querySelector('.ones-select');
    await selectDropdownOption(taskTypeSelect, '功能开发');
    console.log('任务类型已选择');
  } catch (err) {
    console.error('选择任务类型失败：', err.message);
  }

  // 3. 选择负责人（假设在第7个 form-item）
  try {
    const ownerSelect = formItems[7].querySelector('.ones-select');
    await selectDropdownOption(ownerSelect, '张三');
    console.log('负责人已选择');
  } catch (err) {
    console.error('选择负责人失败：', err.message);
  }

  return '任务创建完成';
})();
```

**注意**：由于使用了 `async/await`，需要在支持异步的环境中执行，或手动处理 Promise。

---

## 示例 5：批量创建多个任务

### 目标
循环创建多个任务，每个任务有不同的标题和描述。

### 代码

```javascript
(function batchCreateTasks() {
  const tasks = [
    {
      title: '【功能】实现用户注册',
      description: '允许新用户通过邮箱注册账号',
      acceptance: '- [ ] 邮箱验证有效\n- [ ] 密码强度检查'
    },
    {
      title: '【功能】实现密码重置',
      description: '用户忘记密码时可以通过邮箱重置',
      acceptance: '- [ ] 邮件发送成功\n- [ ] 重置链接有效期24小时'
    },
    {
      title: '【优化】登录页面性能优化',
      description: '减少登录页面加载时间',
      acceptance: '- [ ] 加载时间 < 2s\n- [ ] 首屏渲染 < 1s'
    }
  ];

  function fillTask(taskData) {
    const modal = document.querySelectorAll('.ones-modal')[0];
    const formItems = modal.querySelectorAll('.ones-form-item');

    function fillInput(element, value) {
      const setter = Object.getOwnPropertyDescriptor(
        element.tagName === 'INPUT' ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype,
        'value'
      ).set;

      element.focus();
      setter.call(element, value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
      element.blur();
    }

    // 填写标题
    fillInput(modal.querySelector('#summary'), taskData.title);

    // 填写描述
    fillInput(modal.querySelector('textarea'), taskData.description);

    // 填写验收标准
    const acceptanceTextarea = formItems[4].querySelector('textarea');
    if (acceptanceTextarea) {
      fillInput(acceptanceTextarea, taskData.acceptance);
    }
  }

  // 填写第一个任务
  fillTask(tasks[0]);

  console.log(`已填写任务 1/${tasks.length}`);
  console.log('请手动提交此任务，然后再次打开 Create Task 弹窗创建下一个任务');
  console.log('下一个任务数据：', tasks[1]);

  // 返回剩余任务列表
  return {
    currentTask: tasks[0],
    remainingTasks: tasks.slice(1)
  };
})();
```

**注意**：ONES 需要手动提交每个任务后才能创建下一个，因此批量创建需要配合用户操作或完整的自动化流程。

---

## 示例 6：填写日期字段

### 目标
设置任务的截止日期和计划日期。

### 代码

```javascript
(function fillTaskWithDates() {
  const modal = document.querySelectorAll('.ones-modal')[0];
  const formItems = modal.querySelectorAll('.ones-form-item');

  function fillDateInput(dateInput, dateString) {
    if (!dateInput) return false;

    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value'
    ).set;

    dateInput.focus();
    setter.call(dateInput, dateString);
    dateInput.dispatchEvent(new Event('input', { bubbles: true }));
    dateInput.dispatchEvent(new Event('change', { bubbles: true }));
    dateInput.blur();

    return true;
  }

  // 1. 填写标题
  const titleInput = modal.querySelector('#summary');
  const inputSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  inputSetter.call(titleInput, '【紧急】修复生产环境Bug');
  titleInput.dispatchEvent(new Event('input', { bubbles: true }));

  // 2. 设置截止日期（第9个 form-item）
  const deadlineInput = formItems[8].querySelector('input');
  fillDateInput(deadlineInput, '2025-11-25');  // YYYY-MM-DD 格式

  // 3. 设置计划开始日期（第16个 form-item）
  const startDateInput = formItems[15].querySelector('input');
  fillDateInput(startDateInput, '2025-11-21');

  // 4. 设置计划完成日期（第17个 form-item）
  const endDateInput = formItems[16].querySelector('input');
  fillDateInput(endDateInput, '2025-11-24');

  console.log('日期字段填写完成');
  return {
    deadline: deadlineInput?.value,
    startDate: startDateInput?.value,
    endDate: endDateInput?.value
  };
})();
```

---

## 示例 7：完整工作流（包含验证）

### 目标
填写任务并验证所有字段是否正确设置。

### 代码

```javascript
(function fillAndValidateTask() {
  const modal = document.querySelectorAll('.ones-modal')[0];

  // 工具函数
  function fillInput(element, value) {
    const setter = Object.getOwnPropertyDescriptor(
      element.tagName === 'INPUT' ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype,
      'value'
    ).set;

    element.focus();
    setter.call(element, value);
    element.dispatchEvent(new Event('input', { bubbles: true }));
    element.dispatchEvent(new Event('change', { bubbles: true }));
    element.blur();
  }

  // 1. 填写字段
  const taskData = {
    title: '【测试】自动化表单填写功能验证',
    description: '验证所有字段能够正确填写和提交',
    hours: '2 hours'
  };

  fillInput(modal.querySelector('#summary'), taskData.title);
  fillInput(modal.querySelector('textarea'), taskData.description);

  const numberInput = modal.querySelector('.ones-input-number-input');
  if (numberInput) {
    fillInput(numberInput, taskData.hours);
  }

  // 2. 验证填写结果
  const validation = {
    title: modal.querySelector('#summary').value === taskData.title,
    description: modal.querySelector('textarea').value === taskData.description,
    hours: numberInput ? numberInput.value === taskData.hours : null
  };

  console.log('=== 验证结果 ===');
  console.log('标题:', validation.title ? '✓' : '✗');
  console.log('描述:', validation.description ? '✓' : '✗');
  console.log('工时:', validation.hours ? '✓' : '✗');

  const allValid = Object.values(validation).every(v => v === true || v === null);

  return {
    success: allValid,
    validation: validation,
    data: taskData
  };
})();
```

---

## 通过 AuViMa 执行的快捷脚本

### 脚本 1：快速填写标题和描述

```bash
uv run auvima exec-js "(function() {
  const m = document.querySelectorAll('.ones-modal')[0];
  const f = (e, v) => {
    const s = Object.getOwnPropertyDescriptor((e.tagName === 'INPUT' ? window.HTMLInputElement : window.HTMLTextAreaElement).prototype, 'value').set;
    s.call(e, v);
    e.dispatchEvent(new Event('input', {bubbles: true}));
  };

  f(m.querySelector('#summary'), '任务标题');
  f(m.querySelector('textarea'), '任务描述');

  return 'OK';
})()" --return-value
```

### 脚本 2：查看当前表单数据

```bash
uv run auvima exec-js "(function() {
  const m = document.querySelectorAll('.ones-modal')[0];
  return JSON.stringify({
    title: m.querySelector('#summary')?.value,
    desc: m.querySelector('textarea')?.value,
    hours: m.querySelector('.ones-input-number-input')?.value
  });
})()" --return-value
```
