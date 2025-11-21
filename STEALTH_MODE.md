# AuViMa Stealth 模式使用指南

## 概述

Stealth 模式是一种无感知的 Chrome 启动方式，结合 headless 模式和反检测技术，可以绕过大部分网站的自动化检测。

## 三种模式对比

| 模式 | 窗口可见性 | 任务栏 | 资源占用 | 反检测能力 | 适用场景 |
|------|----------|--------|---------|-----------|---------|
| **正常模式** | ✅ 可见 | ✅ 显示 | 高 | ❌ 无 | 开发调试 |
| **虚空模式** (`--void`) | ❌ 屏幕外 | ✅ 显示 | 高 | ❌ 无 | 后台运行，需真实渲染 |
| **Stealth模式** (`--stealth`) | ❌ 无窗口 | ❌ 不显示 | 低 | ✅ 强 | 生产环境，避免检测 |

## 使用方法

### 1. 启动 Chrome（Stealth 模式）

```bash
# 直接运行启动器
uv run python src/chrome_cdp_launcher.py --stealth

# 或者正常模式
uv run python src/chrome_cdp_launcher.py

# 或者虚空模式
uv run python src/chrome_cdp_launcher.py --void
```

### 2. 在 Python 代码中使用

```python
from chrome_cdp_launcher import ChromeCDPLauncher

# Stealth 模式
launcher = ChromeCDPLauncher(stealth=True)
launcher.launch()

# 虚空模式
launcher = ChromeCDPLauncher(void=True)
launcher.launch()

# 正常模式
launcher = ChromeCDPLauncher()
launcher.launch()
```

### 3. 配合 AuViMa CDP 客户端使用反检测脚本

Stealth 模式的启动参数已经包含基础反检测，但要完全绕过检测，需要在每个新页面加载前注入反检测脚本：

```python
from auvima.cdp.session import CDPSession

# 创建 CDP 会话
with CDPSession() as session:
    # 读取反检测脚本
    with open('src/stealth.js', 'r') as f:
        stealth_script = f.read()

    # 在每个新页面加载前注入脚本
    session.send('Page.addScriptToEvaluateOnNewDocument', {
        'source': stealth_script
    })

    # 现在可以正常导航
    session.navigate('https://example.com')
```

### 4. 测试 Stealth 效果

启动 Chrome 后，访问测试页面：

```bash
# 在浏览器中打开
file:///home/yammi/repos/AuViMa/test_stealth.html
```

或使用 AuViMa CLI：

```bash
uv run auvima navigate "file:///home/yammi/repos/AuViMa/test_stealth.html"
uv run auvima screenshot test_result.png
```

## 反检测技术说明

### 启动参数层面

- `--headless=new` - 新版 headless，渲染更接近真实浏览器
- `--disable-blink-features=AutomationControlled` - 移除自动化标志
- `--user-agent=...` - 自定义 User-Agent
- `--window-size=1280,960` - 设置固定窗口尺寸

### JavaScript 注入层面

`src/stealth.js` 覆盖了以下检测点：

- `navigator.webdriver` → `false`
- `navigator.plugins` → 伪造 PDF 插件等
- `navigator.languages` → `['zh-CN', 'zh', 'en-US', 'en']`
- `window.chrome.runtime` → 添加 Chrome 特有对象
- `navigator.permissions.query` → 覆盖权限查询
- `navigator.hardwareConcurrency` → `8`
- `navigator.deviceMemory` → `8`
- WebGL Renderer 信息伪造

## 绕过能力评估

| 检测类型 | 绕过能力 | 说明 |
|---------|---------|------|
| 基础 webdriver 检测 | ✅ 高 | 通过参数和脚本完全隐藏 |
| Plugins/Languages 检测 | ✅ 高 | 伪造真实浏览器特征 |
| WebGL 指纹检测 | ⚠️ 中 | 基础伪造，高级检测可能识别 |
| Canvas 指纹检测 | ⚠️ 中 | headless 渲染差异可能暴露 |
| 行为检测（鼠标轨迹等） | ❌ 低 | 需要额外模拟人类行为 |
| Google reCAPTCHA v3 | ⚠️ 中 | 基础检测可过，高级可能失败 |
| Cloudflare 人机验证 | ❌ 低 | 需要更复杂的绕过方案 |

## 注意事项

1. **安全性**：`--no-sandbox` 参数会降低浏览器安全性，仅在可信环境使用
2. **兼容性**：某些网站功能在 headless 下可能异常（如某些视频播放）
3. **持续对抗**：反爬虫技术持续升级，需要定期更新反检测脚本
4. **道德使用**：请遵守网站 robots.txt 和服务条款，避免滥用

## 进阶：自定义反检测脚本

修改 `src/stealth.js`，添加更多伪造特征：

```javascript
// 伪造电池状态
navigator.getBattery = () => Promise.resolve({
    charging: true,
    level: 0.99
});

// 伪造触摸支持
Object.defineProperty(navigator, 'maxTouchPoints', {
    get: () => 0  // 桌面浏览器
});

// 伪造连接信息
Object.defineProperty(navigator, 'connection', {
    get: () => ({
        effectiveType: '4g',
        downlink: 10,
        rtt: 50
    })
});
```

## 故障排除

### 问题1: 仍然被检测为 headless

**解决方案**：
1. 确认 `stealth.js` 已正确注入（检查控制台是否有 `[AuViMa Stealth]` 日志）
2. 在 `Page.addScriptToEvaluateOnNewDocument` 中注入脚本，而非页面加载后
3. 检查网站具体检测哪个特征，针对性修改脚本

### 问题2: Chrome 启动失败

**解决方案**：
- 某些环境不支持 `--no-sandbox`，可以移除该参数（修改 `chrome_cdp_launcher.py:235`）
- 检查 Chrome 版本是否支持 `--headless=new`（需 Chrome 109+）

### 问题3: CDP 连接失败

**解决方案**：
- 延长等待时间：修改 `wait_for_cdp(timeout=30)`
- 检查防火墙是否阻止 9222 端口
- 确认没有其他进程占用 9222 端口

## 相关资源

- [Chrome DevTools Protocol 文档](https://chromedevtools.github.io/devtools-protocol/)
- [Puppeteer Stealth Plugin](https://github.com/berstend/puppeteer-extra/tree/master/packages/puppeteer-extra-plugin-stealth)
- [Headless 检测工具](https://arh.antoinevastel.com/bots/areyouheadless)
