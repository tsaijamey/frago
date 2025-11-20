# upwork_extract_job_details_as_markdown

## 功能描述

从Upwork job详情页提取完整的工作信息并格式化为结构化的Markdown文档。适用于需要批量收集Upwork工作机会信息、建立工作档案库或进行市场分析的场景。

配方会自动提取以下信息：
- **Job基础信息**：标题、发布时间、地点、项目类型
- **预算与工作量**：预算方式（按小时/固定价格）、具体金额、工作时长、项目持续时间、经验级别要求
- **工作详情**：完整的Job描述内容、所需技能列表、当前提案数量
- **客户背景**：评分、评论数、历史发布工作数、雇佣率、总支出、平均时薪、会员加入时间

所有信息以混合格式呈现：元数据使用Markdown表格便于快速浏览，描述内容保留段落格式确保可读性。

## 使用方法

**配方执行器说明**：生成的配方本质上是JavaScript代码，通过CDP的Runtime.evaluate接口注入到浏览器中执行。因此，执行配方的标准方式是使用 `uv run auvima exec-js` 命令。

1. 在浏览器中打开任意Upwork job详情页面（URL格式：`https://www.upwork.com/jobs/~<job_id>`）
2. 确保Chrome CDP已连接（默认端口9222）
3. 执行配方：
   ```bash
   # 将配方JS文件内容作为脚本注入浏览器执行
   uv run auvima exec-js recipes/upwork_extract_job_details_as_markdown.js --return-value
   ```
4. 配方会返回格式化的Markdown文本，你可以：
   - 直接复制到剪贴板
   - 重定向到文件：`uv run auvima exec-js recipes/upwork_extract_job_details_as_markdown.js --return-value > job_details.md`
   - 通过管道传递给其他工具进行后续处理

**注意**：AI调试时请记住，你生成的 `.js` 文件不是在 Node.js 环境中运行，而是在浏览器的上下文中运行（类似 Chrome Console）。因此：
- 不能使用 `require()` 或 `import`
- 可以直接使用 `document`, `window` 等浏览器 API
- `console.log` 的输出通常需要查看 `--return-value` 或浏览器控制台

## 前置条件

- 浏览器已打开一个Upwork job详情页（非搜索结果列表页，必须是具体的job详情）
- Chrome DevTools Protocol连接已建立（通过 `chrome --remote-debugging-port=9222` 启动）
- 页面加载完成（所有动态内容已渲染）
- 无需登录Upwork账号（公开job信息可直接访问）

## 预期输出

脚本成功执行后会返回一个包含完整job信息的Markdown文本，结构如下：

```markdown
# <Job标题>

## Job元数据

| 字段 | 值 |
|------|-----|
| **发布时间** | Posted X minutes/hours/days ago |
| **地点** | 地理位置或"Worldwide" |
| **项目类型** | Ongoing project / One-time project |
| **预算方式** | Hourly / Fixed Price |
| **预算** | $XX.XX |
| **工作量** | Less than 30 hrs/week / ... |
| **项目时长** | 1 to 3 months / ... |
| **经验级别** | Entry / Intermediate / Expert |
| **提案数量** | 数字范围 或 "Less than X" |

## Job描述

<完整的job描述段落文本，保留原始换行和格式>

## 技能要求

- 技能1
- 技能2
- ...

## 客户信息

| 字段 | 值 |
|------|-----|
| **评分** | X.X (XXX reviews) |
| **地点** | 国家/城市 |
| **发布工作数** | XXX |
| **雇佣率** | XX% |
| **总支出** | $X.XK/M |
| **总雇佣次数** | XXX |
| **平均时薪** | $X.XX/hr |
| **成员时间** | Month DD, YYYY |
```

## 注意事项

- **选择器稳定性**：配方使用了2个高优先级data-test选择器（`[data-test="Description"]` 和 `[data-test="about-client-container"]`），稳定性较高。其他信息通过DOM结构和文本模式匹配提取，可能受页面改版影响。

- **脆弱选择器**：
  - `h2, h3, h4`（Job标题）：依赖HTML标签顺序，Upwork改版可能影响
  - `main ul li`（元数据列表）：依赖DOM结构，较脆弱
  - 技能列表的提取逻辑依赖class名称模糊匹配，可能需要调整

- **页面加载时机**：如果页面还在加载中（动态内容未完全渲染），可能提取到不完整的信息。建议在执行配方前添加短暂等待：
  ```bash
  uv run auvima wait 2  # 等待2秒确保页面完全加载
  uv run auvima exec-js recipes/upwork_extract_job_details_as_markdown.js --return-value
  ```

- **提案数量隐私**：部分job可能隐藏提案数量，此时会显示"N/A"

- **错误处理**：如果关键元素（如描述、客户信息）找不到，脚本会抛出明确的错误信息，指出缺失的选择器

- **更新建议**：如Upwork改版导致脚本失效，使用 `/auvima.recipe update upwork_extract_job_details_as_markdown "Upwork改版，XXX选择器失效"` 更新配方

## 更新历史

| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-20 | v1 | 初始版本，支持提取job完整信息并格式化为Markdown |
