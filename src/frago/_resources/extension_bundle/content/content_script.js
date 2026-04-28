// frago bridge — content script.
//
// P1 scope: the heavy lifting for dom.exec_js / dom.click / dom.get_content
// is done via chrome.scripting.executeScript from the service worker, which
// is simpler and works in MV3. The content script is present so future
// event-driven features (mutation observers, humanize, overlay UI) have a
// per-tab execution context. It currently only announces itself.

(() => {
    if (window.__fragoBridgeInjected) return;
    window.__fragoBridgeInjected = true;
    try {
        chrome.runtime.sendMessage({ type: "frago.content_ready",
                                     url: location.href });
    } catch (_) { /* SW may be asleep; ignore */ }
})();
