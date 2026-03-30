# selector-priority

分类: 效率（AVAILABLE）

## 解决什么问题
agent 写 Recipe JS 时使用脆弱选择器（CSS-in-JS class、深层结构路径），导致 Recipe 频繁失效。按稳定性排序选择器可大幅提高 Recipe 生命周期。

## 优先级排序（5 最高，1 最低）

| 优先级 | 类型 | 示例 | 稳定性 |
|--------|------|------|--------|
| 5 | ARIA 标签 | [aria-label="Button"] | 很稳定，不受布局变化影响 |
| 5 | data 属性 | [data-testid="submit"] | 很稳定，专为测试设计 |
| 4 | 语义 ID | #main-button | 稳定，语义化命名 |
| 3 | 语义 class | .btn-primary | 中等，BEM 命名约定 |
| 3 | HTML5 语义标签 | button, nav | 中等，标准语义标签 |
| 2 | 结构选择器 | div > button | 脆弱，依赖 DOM 结构 |
| 1 | 生成的 class | .css-abc123 | 极脆弱，随时变化 |

## 识别脆弱选择器

应避免或作为最后 fallback：
- .css-* 或 ._* 前缀（CSS-in-JS 生成）
- 纯数字 ID：#12345
- 超长 ID/class（>20 字符）
- 深层嵌套：div > div > div > span

## Fallback 选择器模式

在 Recipe 中提供 2-3 个按优先级排列的 fallback：

  function findElement(selectors, description) {
    for (const sel of selectors) {
      const elem = document.querySelector(sel.selector);
      if (elem) return elem;
    }
    throw new Error(`Unable to find ${description}`);
  }

  const elem = findElement([
    { selector: '[aria-label="Submit"]', priority: 5 },
    { selector: '[data-testid="submit-btn"]', priority: 5 },
    { selector: '#submit-button', priority: 4 },
    { selector: '.btn-submit', priority: 3 }
  ], 'submit button');

## 验证选择器

创建 Recipe 前用 frago 命令验证选择器有效性：

  # 验证选择器是否存在
  frago chrome exec-js "document.querySelector('[aria-label=\"Submit\"]') !== null" --return-value

  # 高亮元素确认位置
  frago chrome highlight '[aria-label="Submit"]'

  # 获取元素文本确认内容
  frago chrome exec-js "document.querySelector('[aria-label=\"Submit\"]')?.textContent" --return-value

## waitForElement 模式

操作步骤后用 waitForElement 验证结果：

  async function waitForElement(selector, description, timeout = 5000) {
    const startTime = Date.now();
    while (Date.now() - startTime < timeout) {
      const elem = document.querySelector(selector);
      if (elem) return elem;
      await new Promise(r => setTimeout(r, 100));
    }
    throw new Error(`Wait timeout: ${description} (${selector})`);
  }

  elem.click();
  await waitForElement('.result-panel', 'result panel appears');

## 常见网站选择器特征

| 网站 | 推荐选择器类型 | 说明 |
|------|---------------|------|
| YouTube | aria-label, data-* | 大部分 class 是生成的 |
| Twitter/X | data-testid, aria-label | class 极不稳定 |
| GitHub | ID, 语义 class | 相对稳定 |
| Upwork | data-*, 语义 class | 部分生成 class |
