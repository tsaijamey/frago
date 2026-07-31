/**
 * Frago Stealth Mode - Anti-detection script
 *
 * Used to bypass common headless/automation detection mechanisms
 * Usage: Inject before page load via CDP Page.addScriptToEvaluateOnNewDocument
 */

// Hide webdriver flag
Object.defineProperty(navigator, 'webdriver', {
    get: () => false
});

// Spoof plugins
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

// Spoof mimeTypes
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

// Spoof languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en-US', 'en']
});

// Add chrome runtime
if (!window.chrome) {
    window.chrome = {};
}
if (!window.chrome.runtime) {
    window.chrome.runtime = {};
}

// Override permissions query
const originalQuery = navigator.permissions.query;
navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({state: Notification.permission}) :
        originalQuery(parameters)
);

// Spoof hardware concurrency
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 8
});

// Spoof device memory
Object.defineProperty(navigator, 'deviceMemory', {
    get: () => 8
});

// Spoof platform
Object.defineProperty(navigator, 'platform', {
    get: () => 'Linux x86_64'
});

// Spoof vendor
Object.defineProperty(navigator, 'vendor', {
    get: () => 'Google Inc.'
});

// Override getUserMedia detection
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    // Spoof renderer info
    if (parameter === 37445) {
        return 'Intel Inc.';
    }
    if (parameter === 37446) {
        return 'Intel Iris OpenGL Engine';
    }
    return getParameter.call(this, parameter);
};

// Remove headless characteristics
if (navigator.webdriver === false) {
    // Already handled
}

// Override Chrome-specific properties
Object.defineProperty(window, 'outerWidth', {
    get: () => window.innerWidth
});

Object.defineProperty(window, 'outerHeight', {
    get: () => window.innerHeight
});

// Spoof battery API
if (navigator.getBattery) {
    navigator.getBattery = () => Promise.resolve({
        charging: true,
        chargingTime: 0,
        dischargingTime: Infinity,
        level: 1
    });
}

// Override Notification.permission (avoid detection)
try {
    if (Notification && Notification.permission === 'default') {
        Object.defineProperty(Notification, 'permission', {
            get: () => 'denied'
        });
    }
} catch (e) {
    // Ignore error
}

console.log('[Frago Stealth] Anti-detection script loaded');
