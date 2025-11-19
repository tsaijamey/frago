# test_inspect_tab

## 功能描述
获取当前浏览器标签页的详细诊断信息，包括标题、URL、视口尺寸、性能指标和环境信息。

> **注意**：由于浏览器安全沙箱限制，页面内的JavaScript无法访问或列出浏览器中的*其他*标签页。此配方仅报告执行它的那个标签页的状态。

## 使用方法

**配方执行器说明**：生成的配方本质上是JavaScript代码，通过CDP的Runtime.evaluate接口注入到浏览器中执行。因此，执行配方的标准方式是使用 `uv run auvima exec-js` 命令。

1. 确保Chrome已启动并连接
2. 执行配方：
   ```bash
   # 将配方JS文件内容作为脚本注入浏览器执行
   uv run auvima exec-js src/auvima/recipes/test_inspect_tab.js --return-value
   ```
3. 查看控制台输出的格式化报告

## 前置条件
- Chrome CDP已连接
- 任意页面已加载

## 预期输出
返回一个格式化的文本报告，包含页面标题、URL、视口信息等。

示例：
```
=== 📋 Browser Tab Inspection Report ===
Time: 2023-11-19T10:00:00.000Z

--- 📄 Page Info ---
Title:  GitHub
URL:    https://github.com/
...
```

## 注意事项
- 此脚本不依赖任何特定网站的DOM结构，可在任何页面运行
- `loadTime` 在页面完全加载前可能显示为负数或不准确

## 更新历史
| 日期 | 版本 | 变更说明 |
|------|------|----------|
| 2025-11-19 | v1 | 初始版本 |
