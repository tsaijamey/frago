/**
 * Recipe: test_inspect_tab
 * Platform: test
 * Description: 
 * Version: 1
 */

(function() {
  // 
  const info = {
    timestamp: new Date().toISOString(),
    page: {
      title: document.title,
      url: window.location.href,
      domain: window.location.hostname,
      protocol: window.location.protocol.replace(':', ''),
      readyState: document.readyState,
      characterSet: document.characterSet
    },
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
      devicePixelRatio: window.devicePixelRatio,
      screen: `${window.screen.width}x${window.screen.height}`
    },
    navigator: {
      userAgent: navigator.userAgent,
      language: navigator.language,
      platform: navigator.platform,
      cookiesEnabled: navigator.cookieEnabled,
      onLine: navigator.onLine
    },
    performance: {
      // 
      loadTime: window.performance.timing.loadEventEnd - window.performance.timing.navigationStart,
      domReadyTime: window.performance.timing.domContentLoadedEventEnd - window.performance.timing.navigationStart
    }
  };

  // 
  const report = [
    `===
 ===`,
    `Time: ${info.timestamp}`,
    ``,
    `---
 ---`,
    `Title:  ${info.page.title}`,
    `URL:    ${info.page.url}`,
    `State:  ${info.page.readyState}`,
    ``,
    `---
 ---`,
    `Size:   ${info.viewport.width}x${info.viewport.height} (DPR: ${info.viewport.devicePixelRatio})`,
    `Screen: ${info.viewport.screen}`,
    ``,
    `---
 ---`,
    `Load:   ${info.performance.loadTime > 0 ? info.performance.loadTime + 'ms' : 'Pending...'}`,
    ``,
    `---
 ---`,
    `UA:     ${info.navigator.userAgent.substring(0, 50)}...`
  ].join('\n');

  return report;
})();
