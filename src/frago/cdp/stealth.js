/**
 * Frago Stealth Mode - 反检测脚本
 *
 * 用于绕过常见的 headless/自动化检测机制
 * 使用方法：通过 CDP Page.addScriptToEvaluateOnNewDocument 在页面加载前注入
 */

// 隐藏 webdriver 标志
Object.defineProperty(navigator, 'webdriver', {
    get: () => false
});

// 伪造 plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        {
            0: {
                type: "application/x-google-chrome-pdf",
                suffixes: "pdf",
                description: "Portable Document Format"
            },
            description: "Portable Document Format",
            filename: "internal-pdf-viewer",
            length: 1,
            name: "Chrome PDF Plugin"
        },
        {
            0: {
                type: "application/x-nacl",
                suffixes: "",
                description: "Native Client Executable"
            },
            description: "Native Client Executable",
            filename: "internal-nacl-plugin",
            length: 2,
            name: "Native Client"
        }
    ]
});

// 伪造 mimeTypes
Object.defineProperty(navigator, 'mimeTypes', {
    get: () => [
        {
            type: "application/x-google-chrome-pdf",
            suffixes: "pdf",
            description: "Portable Document Format",
            enabledPlugin: {name: "Chrome PDF Plugin"}
        },
        {
            type: "application/x-nacl",
            suffixes: "",
            description: "Native Client Executable",
            enabledPlugin: {name: "Native Client"}
        }
    ]
});

// 伪造 languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en-US', 'en']
});

// 添加 chrome runtime
if (!window.chrome) {
    window.chrome = {};
}
if (!window.chrome.runtime) {
    window.chrome.runtime = {};
}

// 覆盖 permissions query
const originalQuery = navigator.permissions.query;
navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({state: Notification.permission}) :
        originalQuery(parameters)
);

// 伪造硬件并发数
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 8
});

// 伪造设备内存
Object.defineProperty(navigator, 'deviceMemory', {
    get: () => 8
});

// 伪造平台
Object.defineProperty(navigator, 'platform', {
    get: () => 'Linux x86_64'
});

// 伪造 vendor
Object.defineProperty(navigator, 'vendor', {
    get: () => 'Google Inc.'
});

// 覆盖 getUserMedia 检测
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    // 伪造渲染器信息
    if (parameter === 37445) {
        return 'Intel Inc.';
    }
    if (parameter === 37446) {
        return 'Intel Iris OpenGL Engine';
    }
    return getParameter.call(this, parameter);
};

// 移除 headless 特征
if (navigator.webdriver === false) {
    // 已处理
}

// 覆盖 Chrome 特有属性
Object.defineProperty(window, 'outerWidth', {
    get: () => window.innerWidth
});

Object.defineProperty(window, 'outerHeight', {
    get: () => window.innerHeight
});

// 伪造电池 API
if (navigator.getBattery) {
    navigator.getBattery = () => Promise.resolve({
        charging: true,
        chargingTime: 0,
        dischargingTime: Infinity,
        level: 1
    });
}

// 覆盖 Notification.permission（避免检测）
try {
    if (Notification && Notification.permission === 'default') {
        Object.defineProperty(Notification, 'permission', {
            get: () => 'denied'
        });
    }
} catch (e) {
    // 忽略错误
}

console.log('[Frago Stealth] 反检测脚本已加载');
